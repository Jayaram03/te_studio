"""The Claude call is checked with a stand-in client (no API key / network needed)."""
import json
from types import SimpleNamespace

from app.config import get_settings
from app.extractor import ClaudeExtractor, _batch, merge_extractions
from app.parsers import parse_file
from conftest import FIXTURES, SAMPLES


class FakeMessages:
    def __init__(self, answer):
        self.answer, self.calls = answer, []

    def stream(self, **kw):
        self.calls.append(kw)
        msg = SimpleNamespace(stop_reason="tool_use", content=[SimpleNamespace(type="tool_use", input=self.answer)],
                              usage=SimpleNamespace(input_tokens=1234, output_tokens=567))

        class _S:
            def __enter__(s): return s
            def __exit__(s, *a): return False
            def get_final_message(s): return msg
        return _S()


def _extractor(answer):
    ex = ClaudeExtractor.__new__(ClaudeExtractor)
    ex.settings, ex.model_name, ex.max_tokens, ex.recorder = get_settings(), "claude-sonnet-5-5", 32000, None
    ex.client = SimpleNamespace(messages=FakeMessages(answer))
    return ex


def test_text_pdf_is_sent_as_text_with_forced_tool():
    answer = json.loads((FIXTURES / "misty_hills_munnar_2026-27.json").read_text())
    ex = _extractor(answer)
    out = ex.extract(parse_file(SAMPLES / "misty_hills_munnar_2026-27.pdf"), "misty.pdf", "Misty Hills")
    kw = ex.client.messages.calls[0]
    assert kw["tool_choice"] == {"type": "tool", "name": "record_extraction"}
    assert kw["tools"][0]["input_schema"]["properties"]["hotels"]
    content = kw["messages"][0]["content"]
    assert content[0]["type"] == "text" and "Premium Valley View" in content[0]["text"]
    assert "Supplier (told by the agent): Misty Hills" in content[0]["text"]
    assert len(out["hotels"][0]["rates"]) == 50


def test_scanned_pdf_and_images_go_native():
    ex = _extractor({"document_type": "unknown"})
    doc = parse_file(SAMPLES / "misty_hills_munnar_2026-27.pdf")
    doc.has_text_layer = False
    ex.extract(doc, "scan.pdf")
    assert ex.client.messages.calls[0]["messages"][0]["content"][0]["type"] == "document"
    img = parse_file("card.png", b"\x89PNG fake")
    ex.extract(img, "card.png")
    assert ex.client.messages.calls[1]["messages"][0]["content"][0]["type"] == "image"


def test_big_documents_are_chunked_and_merged():
    assert _batch(["a" * 10, "b" * 10, "c" * 10], 25) == [["a" * 10, "b" * 10], ["c" * 10]]
    p1 = {"document_type": "hotel_rate_sheet", "supplier": {"name": "X"}, "currency": "INR", "validity": None,
          "taxes": "unknown", "rate_type": "net", "seasons": [{"key": "peak", "name": "Peak", "periods": [{"start": "1", "end": "2"}]}],
          "hotels": [{"name": "H", "rates": [1], "supplements": [], "blackout_dates": []}], "packages": [],
          "services": [], "general_terms": [], "warnings": []}
    p2 = {**p1, "supplier": {"name": None, "email": "a@b"}, "taxes": "excluded",
          "seasons": [{"key": "peak", "name": "Peak", "periods": [{"start": "3", "end": "4"}]}],
          "hotels": [{"name": "h ", "rates": [2], "supplements": [], "blackout_dates": []}]}
    m = merge_extractions([p1, p2])
    assert m["supplier"]["name"] == "X" and m["supplier"]["email"] == "a@b" and m["taxes"] == "excluded"
    assert len(m["seasons"][0]["periods"]) == 2 and m["hotels"][0]["rates"] == [1, 2]


def test_known_names_and_prompt_caching():
    ex = _extractor({"document_type": "unknown"})
    ex.extract(parse_file(SAMPLES / "misty_hills_munnar_2026-27.pdf"), "misty.pdf", None,
               reference="Supplier: Misty Hills\nHotel: Misty Hills Resort & Spa (Munnar) - rooms: Deluxe Room")
    kw = ex.client.messages.calls[0]
    text = kw["messages"][0]["content"][0]["text"]
    assert "KNOWN NAMES" in text and "Misty Hills Resort & Spa (Munnar)" in text
    # the fixed instructions + schema are cached between calls
    assert kw["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert "base_name" in kw["tools"][0]["input_schema"]["$defs"]["PackageBlock"]["properties"]
    assert "REVISED AND REPEATED SHEETS" in kw["system"][0]["text"]


def test_cached_tokens_are_recorded_and_priced_lower():
    from decimal import Decimal
    from app import ai
    ex = _extractor({"document_type": "unknown"})
    seen = []
    ex.recorder = lambda *a, **k: seen.append((a, k))
    msg_usage = SimpleNamespace(input_tokens=1000, output_tokens=100, cache_read_input_tokens=9000,
                                cache_creation_input_tokens=0)
    orig = ex.client.messages.stream

    def stream(**kw):
        ctx = orig(**kw)
        ctx.get_final_message().usage = msg_usage
        return ctx
    ex.client.messages.stream = stream
    ex.extract(parse_file("card.png", b"\x89PNG fake"), "card.png")
    (provider, model, tin, tout, _ms, ok, _err), extra = seen[0]
    assert (tin, tout, extra["cached_tokens"]) == (10000, 100, 9000)
    cfg = {"price_input_per_mtok": 3, "price_output_per_mtok": 15}
    # 1,000 full-price + 9,000 cached at a tenth = 1,900 input-token equivalents
    assert ai.cost_of(cfg, tin, tout, extra["cached_tokens"]) == (Decimal(3) * Decimal("1900") + 15 * 100) / Decimal(1_000_000)


def test_supplier_names_from_earlier_sheets_are_given_to_the_ai(session, extractor):
    from app import pipeline
    from conftest import sample
    doc, _ = pipeline.ingest(session, *sample("misty_hills_munnar_2026-27.pdf"), extractor)
    assert extractor.last_reference is None                 # first sheet from this supplier: nothing to match
    pipeline.approve(session, doc)
    pipeline.ingest(session, *sample("misty_hills_munnar_2026-27_revised.pdf"), extractor)
    ref = extractor.last_reference
    assert "Misty Hills Resort & Spa" in ref and "Premium Valley View" in ref
