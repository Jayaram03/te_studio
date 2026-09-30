import json
from datetime import datetime

import httpx
from sqlalchemy import select

from app import ai, db, pipeline, runtime, secretbox
from app.config import get_settings
from app.extractor import ClaudeExtractor, OpenAICompatExtractor, dereference
from app.parsers import parse_file
from app.schema import tool_schema
from conftest import FIXTURES, SAMPLES, sample, signed_in_client

MISTY = json.loads((FIXTURES / "misty_hills_munnar_2026-27.json").read_text())


def fake_openai(answer: dict, seen: list):
    def handler(request: httpx.Request):
        body = json.loads(request.content)
        seen.append(body)
        if body["messages"][-1]["content"] == "Reply with the single word OK.":
            return httpx.Response(200, json={"choices": [{"message": {"content": "OK"}}], "usage": {"prompt_tokens": 12, "completion_tokens": 1}})
        return httpx.Response(200, json={"choices": [{"finish_reason": "tool_calls", "message": {"tool_calls": [
            {"type": "function", "function": {"name": "record_extraction", "arguments": json.dumps(answer)}}]}}],
            "usage": {"prompt_tokens": 5000, "completion_tokens": 2500}})
    return httpx.MockTransport(handler)


def test_secret_box_and_masking(session):
    tok = secretbox.encrypt("sk-live-1234567890abcd")
    assert "sk-live" not in tok and secretbox.decrypt(tok) == "sk-live-1234567890abcd"
    assert secretbox.hint("sk-live-1234567890abcd") == "••••abcd"


def test_default_is_claude_and_keys_never_leave_the_server(session, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    get_settings().anthropic_api_key = None
    get_settings().fixtures_dir = None
    c = signed_in_client(session)
    v = c.get("/api/ai/settings").json()
    assert v["provider"] == "anthropic" and v["model"] == "claude-sonnet-5-5" and not v["key_set"]
    assert {p["id"] for p in v["providers"]} >= {"anthropic", "openai", "gemini", "groq", "openrouter", "custom"}
    v = c.put("/api/ai/settings", json={"api_key": "sk-ant-secret-key-9876"}).json()
    assert v["key_set"] and v["key_source"] == "app" and v["key_hint"] == "••••9876"
    assert "sk-ant-secret" not in json.dumps(v)
    stored = session.get(db.AppSetting, "ai").value
    assert "sk-ant" not in json.dumps(stored)                              # encrypted at rest
    assert isinstance(ai.build_extractor(session), ClaudeExtractor)


def test_switch_to_openai_compatible_in_ui(session):
    get_settings().fixtures_dir = None
    c = signed_in_client(session)
    assert c.put("/api/ai/settings", json={"provider": "gemini"}).status_code == 400      # needs a model name
    v = c.put("/api/ai/settings", json={"provider": "gemini", "model": "gemini-model-x", "api_key": "AIza-test-key-000"}).json()
    assert v["provider"] == "gemini" and v["base_url"].startswith("https://generativelanguage.googleapis.com")
    ex = ai.build_extractor(session)
    assert isinstance(ex, OpenAICompatExtractor) and ex.model_name == "gemini-model-x"
    v = c.put("/api/ai/settings", json={"provider": "custom", "model": "llama3", "base_url": "http://localhost:11434/v1"}).json()
    assert not v["key_set"]                                               # switching provider drops the old key


def test_openai_compatible_extraction_logs_tokens_and_cost(session):
    ai.save(session, {"provider": "openai", "model": "some-model", "price_input_per_mtok": 3, "price_output_per_mtok": 15})
    seen = []
    ex = OpenAICompatExtractor("https://api.example.test/v1", "k", "some-model", provider="openai",
                               recorder=ai.recorder(session, ai.load(session), "extraction"), transport=fake_openai(MISTY, seen))
    out = ex.extract(parse_file(SAMPLES / "misty_hills_munnar_2026-27.pdf"), "misty.pdf")
    assert len(out["hotels"][0]["rates"]) == 50
    body = seen[0]
    assert body["tool_choice"]["function"]["name"] == "record_extraction"
    assert "$ref" not in json.dumps(body["tools"][0]["function"]["parameters"])
    u = session.scalar(select(db.AIUsage))
    assert (u.provider, u.input_tokens, u.output_tokens, u.ok) == ("openai", 5000, 2500, True)
    assert float(u.cost) == (5000 * 3 + 2500 * 15) / 1_000_000


def test_scanned_pdf_goes_as_page_images(session):
    seen = []
    ex = OpenAICompatExtractor("https://x.test/v1", "k", "m", transport=fake_openai(MISTY, seen))
    doc = parse_file(SAMPLES / "misty_hills_munnar_2026-27.pdf")
    doc.has_text_layer = False
    ex.extract(doc, "scan.pdf")
    parts = seen[0]["messages"][1]["content"]
    assert [p["type"] for p in parts].count("image_url") == 1 and parts[0]["image_url"]["url"].startswith("data:image/jpeg")
    assert ex.ping()["reply"] == "OK"


def test_dereference_inlines_all_refs():
    d = dereference(tool_schema())
    assert "$ref" not in json.dumps(d) and "$defs" not in d
    assert d["properties"]["hotels"]["items"]["properties"]["rates"]["items"]["properties"]["room_type"]["type"] == "string"


def test_budget_and_missing_key_fail_readably(session, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    get_settings().anthropic_api_key = None
    get_settings().fixtures_dir = None
    from app import api
    api.set_extractor(None)
    c = signed_in_client(session)
    with open(SAMPLES / "misty_hills_munnar_2026-27.pdf", "rb") as f:
        d = c.post("/api/documents", files={"file": ("m.pdf", f, "application/pdf")}).json()
    assert d["status"] == "failed" and "No API key" in d["error"]
    ai.save(session, {"api_key": "sk-ant-abc-123456", "monthly_budget": 1, "price_input_per_mtok": 3})
    session.add(db.AIUsage(provider="anthropic", model="m", purpose="extraction", input_tokens=10, output_tokens=0, cost=2))
    session.commit()
    try:
        ai.build_extractor(session)
        raise AssertionError("budget should block")
    except ai.AIError as e:
        assert "budget" in str(e)


def test_usage_summary_and_test_endpoint(session):
    for i in range(3):
        session.add(db.AIUsage(provider="anthropic", model="claude-sonnet-5-5", purpose="extraction",
                               input_tokens=1000 * (i + 1), output_tokens=500, cost=0.01, ok=i != 2))
    session.commit()
    c = signed_in_client(session)
    u = c.get("/api/ai/usage", params={"days": 7}).json()
    assert len(u["daily"]) == 7 and u["month"]["calls"] == 3 and u["month"]["input_tokens"] == 6000
    assert u["month"]["failed"] == 1 and u["by_model"][0]["calls"] == 3 and len(u["recent"]) == 3
    get_settings().fixtures_dir = FIXTURES
    assert c.post("/api/ai/test").json()["ok"]                            # demo mode: no AI call


def test_processing_options_from_ui_take_effect(session):
    c = signed_in_client(session)
    assert c.put("/api/settings/processing", json={"pdf_mode": "sideways"}).status_code == 400
    v = c.put("/api/settings/processing", json={"default_currency": "USD", "weekend_days": "sat,sun", "chunk_chars": 30000}).json()
    assert v["values"]["default_currency"] == "USD" and get_settings().chunk_chars == 30000
    x = json.loads((FIXTURES / "misty_hills_munnar_2026-27.json").read_text())
    x["currency"] = None
    for r in x["hotels"][0]["rates"]:
        r["currency"] = None
    from app.normalize import normalize
    n = normalize(x)
    assert n["hotels"][0]["rates"][0]["currency"] == "USD"
    c.put("/api/settings/processing", json={"default_currency": "INR", "weekend_days": "fri,sat", "chunk_chars": 60000})


def test_extra_instructions_reach_the_ai(session):
    ai.save(session, {"provider": "openai", "model": "m", "extra_instructions": "Treat 'Room + Brekkie' as CP."})
    seen = []
    ex = OpenAICompatExtractor("https://api.example.test/v1", "k", "m", provider="openai",
                               transport=fake_openai(MISTY, seen), extra_instructions=ai.load(session)["extra_instructions"])
    ex.extract(parse_file(SAMPLES / "misty_hills_munnar_2026-27.pdf"), "misty.pdf")
    system = seen[0]["messages"][0]["content"]
    assert system.startswith("You extract supplier data") and "Treat 'Room + Brekkie' as CP." in system
    import pytest
    with pytest.raises(ai.AIError):
        ai.save(session, {"extra_instructions": "x" * 4001})


def test_system_status_shows_state_not_secrets(session):
    from conftest import signed_in_client
    from app.config import get_settings
    c = signed_in_client(session)
    r = c.get("/api/system").json()
    assert r["database"]["schema_version"] and r["counts"]["users"] == 1
    names = {e["name"]: e for e in r["env"]}
    assert names["SECRET_KEY"]["set"] is True
    assert get_settings().secret_key not in str(r)                     # the value itself is never returned
    from fastapi.testclient import TestClient
    from app import api
    assert TestClient(api.app).get("/api/system").status_code == 401    # admins only


def test_budget_counts_calls_made_before_prices_were_set(session):
    """What the screen shows as spent is what the budget enforces."""
    rec = ai.recorder(session, ai.load(session), "extraction")          # no prices yet -> cost not recorded
    for _ in range(4):
        rec("anthropic", "m", 1_000_000, 200_000, 1000, True)
    assert session.scalar(select(db.AIUsage.cost)) is None
    ai.save(session, {"price_input_per_mtok": 3, "price_output_per_mtok": 15, "monthly_budget": 20})
    shown = ai.usage_summary(session)["month"]["cost"]
    assert shown == ai.month_cost(session) == 4 * (3 + 0.2 * 15)          # 24.0 on screen and for the budget
    import pytest
    with pytest.raises(ai.AIError, match="budget"):
        ai.build_extractor(session)                                       # 24 >= 20 -> stops, as the screen says


def test_backup_models_take_over_when_one_hits_its_free_limit(session):
    """Gemini free tier: limits are per model. A 429 on one model moves the document to the next backup."""
    answer = json.loads((FIXTURES / "misty_hills_munnar_2026-27.json").read_text())
    calls = []

    def handler(request: httpx.Request):
        body = json.loads(request.content)
        calls.append(body["model"])
        if body["model"] == "gemini-3.8-flash":
            return httpx.Response(429, json={"error": {"code": 429, "status": "RESOURCE_EXHAUSTED",
                                                       "message": "Quota exceeded for requests per day"}})
        if body["model"] == "gemini-3.7-flash":
            return httpx.Response(503, json={"error": {"code": 503, "message": "The model is overloaded"}})
        return httpx.Response(200, json={"choices": [{"finish_reason": "tool_calls", "message": {"tool_calls": [
            {"type": "function", "function": {"name": "record_extraction", "arguments": json.dumps(answer)}}]}}],
            "usage": {"prompt_tokens": 5000, "completion_tokens": 2500}})
    ai.save(session, {"provider": "gemini", "model": "gemini-3.8-flash",
                      "fallback_models": "gemini-3.7-flash, gemini-3.6-flash, gemini-3.5-flash"})
    cfg = ai.load(session)
    assert cfg["fallback_models"] == ["gemini-3.7-flash", "gemini-3.6-flash", "gemini-3.5-flash"]
    ex = OpenAICompatExtractor("https://example.test/v1beta/openai", "k", cfg["model"], provider="gemini",
                               recorder=ai.recorder(session, cfg, "extraction"), transport=httpx.MockTransport(handler),
                               fallback_models=cfg["fallback_models"])
    out = ex.extract(parse_file(SAMPLES / "misty_hills_munnar_2026-27.pdf"), "misty.pdf")
    assert len(out["hotels"][0]["rates"]) == 50
    assert calls == ["gemini-3.8-flash", "gemini-3.7-flash", "gemini-3.6-flash"] and ex.model_name == "gemini-3.6-flash"
    rows = session.scalars(select(db.AIUsage).order_by(db.AIUsage.id)).all()
    assert [(r.model, r.ok) for r in rows] == [("gemini-3.8-flash", False), ("gemini-3.7-flash", False), ("gemini-3.6-flash", True)]
    assert "limit reached" in rows[0].error


def test_when_every_model_is_used_up_the_message_says_so(session):
    def handler(request):
        return httpx.Response(429, json={"error": {"status": "RESOURCE_EXHAUSTED"}})
    ex = OpenAICompatExtractor("https://example.test/v1", "k", "a", provider="gemini", transport=httpx.MockTransport(handler),
                               fallback_models=["b"])
    import pytest
    with pytest.raises(RuntimeError, match="Every model's limit is used up"):
        ex.extract(parse_file(SAMPLES / "misty_hills_munnar_2026-27.pdf"), "misty.pdf")


def test_a_real_error_is_not_retried_on_other_models(session):
    seen = []

    def handler(request):
        seen.append(1)
        return httpx.Response(401, json={"error": {"message": "API key not valid"}})
    ex = OpenAICompatExtractor("https://example.test/v1", "k", "a", provider="gemini", transport=httpx.MockTransport(handler),
                               fallback_models=["b", "c"])
    import pytest
    with pytest.raises(RuntimeError, match="401"):
        ex.extract(parse_file(SAMPLES / "misty_hills_munnar_2026-27.pdf"), "misty.pdf")
    assert len(seen) == 1


def test_gemini_gets_a_plainer_schema():
    from app.extractor import simplify
    s = json.dumps(simplify(dereference(tool_schema())))
    assert '"type": "null"' not in s and '"default"' not in s and '"nullable": true' in s
    assert '"hotels"' in s and '"base_name"' in s
