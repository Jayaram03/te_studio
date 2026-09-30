"""Stage 2: AI extraction into the fixed schema.

Claude is given the parsed document and *must* answer by calling the `record_extraction` tool
whose input schema is `schema.Extraction`. The result is validated with Pydantic, so anything
that doesn't fit the contract fails loudly instead of landing in the database.
"""
from __future__ import annotations

import base64
import io
import logging
import json
import time
from pathlib import Path
from typing import Protocol

from .config import get_settings
from .parsers import ParsedDocument
from .schema import Extraction, tool_schema

SYSTEM_PROMPT = """You extract supplier data for an Indian travel agency (Travel Episodes, Chennai) from \
hotel rate sheets, DMC (destination management company) rate sheets and holiday package PDFs. \
One document can mix all of these: hotel rates, packages, activity prices and destination descriptions.

Record EVERYTHING by calling the record_extraction tool exactly once. Rules:
- Copy numbers exactly. Never calculate, round, add tax or guess a missing rate. If a rate says \
"on request" or is blank, set amount to null and say so in notes.
- One HotelRateLine per (room type x meal plan x occupancy x season/date range x day restriction). \
A table with columns for CP and MAP and rows for Single/Double becomes 4 lines per season.
- Keep meal plans and occupancies as the sheet writes them (CPAI, MAP, Dbl, EXB, CWB, CNB...). \
"Per couple" means double occupancy per room. If one price covers both single and double (SGL/DBL), \
record it twice: once as single and once as double.
- Seasons: put each season once in `seasons` with ALL its date ranges and reference it from lines by \
season_key. Write dates as YYYY-MM-DD when the year is clear; otherwise copy them as written \
("Aug 2026" is fine for a month).
- rate_type: "net" for B2B / agent / net / contracted rates, "rack" for published / public / rack / \
walk-in rates. If both are given, record both as separate lines.
- taxes: "excluded" if GST/VAT/taxes are extra, "included" if inclusive.

PACKAGES
- Capture the full day-wise itinerary (title, a faithful description, overnight city, meals).
- Prices: one PackagePrice per (hotel category x group size x occupancy). "Cost per person" tables with \
rows "2 Pax, 4 Pax..." and columns "Standard, Deluxe..." -> pax_min = pax_max = that group size, \
occupancy "per person twin sharing", basis per_person. Rows like "Extra bed / CWB" and "CNB" are their \
own occupancies for each category (no pax values). "Single supplement" is its own occupancy.
- Hotels: when a city lists several hotels per category ("any of these or similar"), add one \
PackageHotel per hotel name with that city, category and number of nights. Names can wrap onto the \
next line inside a table cell ("Himalyan Hill" + "Resort" = "Himalyan Hill Resort"); join them. \
Houseboats are property_type "houseboat".
- Priced items under exclusions or "on your own expense" (gondola, pony rides, rentals, transit cabs, \
entry tickets) are services with optional = true. For a range like "1200-1500" put amount = 1200 and \
amount_max = 1500. "per cab for 6 pax" -> basis per_vehicle, pax_max 6. "Negotiable" goes in notes.
- Unpriced exclusions (airfare, lunch, personal expenses) stay only in the package exclusions list.
- Places / offbeat destinations described in the document go in `places` (short summary in your own \
words, availability period if given).

- Package names: `title` exactly as written; `base_name` = the same name without season, year, edition \
or revision words ("Off Season 2026 Kashmir Package 5N/6D (Revised)" -> base_name "Kashmir 5N/6D", \
edition "Off Season 2026 (Revised)"). Two editions of one package must get the same base_name.

REVISED AND REPEATED SHEETS
- Suppliers re-send sheets with new prices or new seasons. Always record every rate the document shows \
as it is now, even if you think it is unchanged; the app compares it with earlier sheets itself.
- If the sheet says it is revised / updated / effective from a date, set is_revision = true and use that \
date as the start of validity for the revised rates. Put the issue date in issued_on if printed.
- "Valid till further notice" or no end date: leave the end date empty and add a warning. Never guess.
- If the message contains KNOWN NAMES from this supplier's earlier documents, and this document has the \
same hotel, room type, package or service, write its name exactly as in that list (same spelling, same \
words) so the two can be matched. Use the list only for spelling: never add anything that is not in \
this document, and never rename something that is clearly different.

OTHER
- Transfers, sightseeing tours, entry tickets, guides and vehicle rates go in `services`.
- Put cancellation, payment, check-in and child policies in general_terms (and child_policy on the hotel).
- Anything ambiguous, unreadable or contradictory -> add a short note to `warnings`. Do not invent data.
- Before calling the tool, check: every price in the document is recorded once; no number was changed, \
rounded or calculated; every rate line has its room type, meal plan, occupancy and dates or season."""

TOOL_NAME = "record_extraction"
log = logging.getLogger(__name__)


class RateLimited(RuntimeError):
    """The provider refused because of a rate limit / quota / overload: the next backup model may still work."""


def _is_rate_limit(status: int, text: str) -> bool:
    t = (text or "").lower()
    return status in (429, 503, 529) or "resource_exhausted" in t or "quota" in t or "rate limit" in t or "overloaded" in t


class Extractor(Protocol):
    model_name: str

    def extract(self, doc: ParsedDocument, filename: str, supplier_hint: str | None = None,
                reference: str | None = None) -> dict: ...


def _reference_block(reference: str | None) -> str:
    if not reference:
        return ""
    return ("KNOWN NAMES from this supplier's earlier documents (for consistent spelling only - "
            "do not add anything that is not in this document):\n" + reference + "\n\n")


class _AIExtractor:
    """Shared logic: decide text vs. native (PDF/image) input, split big documents, merge the parts.
    Subclasses only implement `_call(parts)` for their API. Every call is reported to `recorder`."""
    provider = "ai"
    system_prompt = SYSTEM_PROMPT            # extended per instance with the agency's extra instructions

    def __init__(self, model: str, max_tokens: int | None = None, recorder=None, extra_instructions: str | None = None,
                 fallback_models: list[str] | None = None):
        self.settings = get_settings()
        self.model_name = model
        # backups, tried in order when a model hits its rate limit / quota or is overloaded (free tiers have
        # separate limits per model). A model that ran out stays skipped for the rest of this document.
        self.models = [model] + [m for m in (fallback_models or []) if m and m != model]
        self.exhausted: set[str] = set()
        self.max_tokens = max_tokens or self.settings.extraction_max_tokens
        self.recorder = recorder
        extra = (extra_instructions or "").strip()
        # agency-specific rules from Settings → AI connector, added after the built-in rules
        self.system_prompt = SYSTEM_PROMPT + (f"\n\nADDITIONAL RULES FROM THE AGENCY (follow these too):\n{extra}" if extra else "")

    def extract(self, doc: ParsedDocument, filename: str, supplier_hint: str | None = None,
                reference: str | None = None) -> dict:
        header = (f"File name: {filename}\n" + (f"Supplier (told by the agent): {supplier_hint}\n" if supplier_hint else "")
                  + _reference_block(reference))
        native = doc.kind == "image" or (
            doc.kind == "pdf" and (self.settings.pdf_mode == "native" or
                                   (self.settings.pdf_mode == "auto" and not doc.has_text_layer)))
        if native:
            kind = "pdf" if doc.kind == "pdf" else "image"
            return self._timed([(kind, doc.raw_bytes or b"", doc.media_type),
                                ("text", header + "Extract everything from the attached document.", None)])
        batches = _batch(doc.chunks, self.settings.chunk_chars)
        results = []
        for i, batch in enumerate(batches):
            context = ""
            if i > 0:   # later chunks still need the supplier / validity / season header from page 1
                context = ("Context from the start of the document (do not re-extract it, use it only to "
                           "understand the part below):\n" + doc.chunks[0][:4000] + "\n\n")
            part = f"(part {i + 1} of {len(batches)})\n" if len(batches) > 1 else ""
            results.append(self._timed([("text", f"{header}{part}{context}Document content:\n\n" + "\n\n".join(batch), None)]))
        return merge_extractions(results)

    def _timed(self, parts) -> dict:
        last = None
        if not getattr(self, "models", None):                    # built without __init__ (tests)
            self.models, self.exhausted = [self.model_name], set()
        for model in [m for m in self.models if m not in self.exhausted]:
            self.model_name = model
            t0 = time.time()
            usage = {"in": 0, "out": 0}
            try:
                raw = self._call(parts, usage)
                out = Extraction.model_validate(raw).model_dump()
                self._record(usage, t0, True)
                return out
            except RateLimited as e:
                self._record(usage, t0, False, f"limit reached, trying the next model: {e}")
                self.exhausted.add(model)
                last = e
                log.warning("AI model %s hit its limit (%s); trying the next backup model", model, str(e)[:120])
            except Exception as e:
                self._record(usage, t0, False, f"{type(e).__name__}: {e}")
                raise
        raise RuntimeError("Every model's limit is used up for now (" + ", ".join(self.models) + "). "
                           "Free tiers reset daily; try again later or add a paid key." + (f" Last: {last}" if last else ""))

    def _record(self, usage, t0, ok, error=None):
        if self.recorder:
            try:
                extra = {"cached_tokens": usage["cached"]} if usage.get("cached") else {}
                self.recorder(self.provider, self.model_name, usage["in"], usage["out"],
                              int((time.time() - t0) * 1000), ok, error, **extra)
            except Exception:  # noqa: BLE001 - logging must never break extraction
                pass

    def _call(self, parts, usage: dict) -> dict:
        raise NotImplementedError


class ClaudeExtractor(_AIExtractor):
    provider = "anthropic"

    def __init__(self, api_key: str | None = None, model: str | None = None, max_tokens: int | None = None,
                 recorder=None, extra_instructions: str | None = None, fallback_models: list[str] | None = None):
        import anthropic

        s = get_settings()
        super().__init__(model or s.extraction_model, max_tokens, recorder, extra_instructions, fallback_models)
        key = api_key or s.anthropic_api_key
        if not key:
            raise RuntimeError("No Anthropic API key. Add it in Settings → AI connector.")
        self.client = anthropic.Anthropic(api_key=key)

    def _call(self, parts, usage: dict) -> dict:
        content = []
        for kind, data, media in parts:
            if kind == "text":
                content.append({"type": "text", "text": data})
            elif kind == "pdf":
                content.append({"type": "document", "source": {"type": "base64", "media_type": "application/pdf",
                                                               "data": base64.standard_b64encode(data).decode()}})
            else:
                content.append({"type": "image", "source": {"type": "base64", "media_type": media,
                                                            "data": base64.standard_b64encode(data).decode()}})
        # streamed: package PDFs with long hotel lists produce long answers.
        # The instructions and the (large) output schema are the same for every call, so they are marked for
        # prompt caching: the 2nd..nth part of a long document, and documents read within a few minutes of
        # each other, reuse them at a fraction of the input price.
        import anthropic
        try:
            return self._stream(content, usage)
        except (anthropic.RateLimitError, anthropic.InternalServerError) as e:
            if isinstance(e, anthropic.RateLimitError) or _is_rate_limit(getattr(e, "status_code", 0) or 0, str(e)):
                raise RateLimited(str(e)[:300]) from e
            raise

    def _stream(self, content, usage: dict) -> dict:
        with self.client.messages.stream(
            model=self.model_name,
            max_tokens=self.max_tokens,
            system=[{"type": "text", "text": self.system_prompt, "cache_control": {"type": "ephemeral"}}],
            tools=[{"name": TOOL_NAME, "description": "Record every rate, package, activity, place and term in the document.",
                    "input_schema": tool_schema()}],
            tool_choice={"type": "tool", "name": TOOL_NAME},
            messages=[{"role": "user", "content": content}],
        ) as stream:
            resp = stream.get_final_message()
        if getattr(resp, "usage", None):
            u = resp.usage
            read = getattr(u, "cache_read_input_tokens", 0) or 0
            written = getattr(u, "cache_creation_input_tokens", 0) or 0
            # input_tokens excludes cached parts; record everything sent, and how much came from the cache
            usage["in"] = (u.input_tokens or 0) + read + written
            usage["out"] = u.output_tokens or 0
            usage["cached"] = read
        if resp.stop_reason == "max_tokens":
            raise RuntimeError("Extraction was cut off (document too dense). Lower the chunk size or raise max tokens "
                               "in Settings and read it again.")
        block = next(b for b in resp.content if b.type == "tool_use")
        return block.input

    def ping(self) -> dict:
        r = self.client.messages.create(model=self.model_name, max_tokens=10,
                                        messages=[{"role": "user", "content": "Reply with the single word OK."}])
        tin, tout = r.usage.input_tokens, r.usage.output_tokens
        self._record({"in": tin, "out": tout}, time.time(), True)
        return {"reply": "".join(b.text for b in r.content if b.type == "text").strip(), "model": self.model_name,
                "input_tokens": tin, "output_tokens": tout}


def dereference(schema: dict) -> dict:
    """Inline $ref/$defs: several OpenAI-compatible providers reject references in tool schemas."""
    defs = schema.get("$defs", {})

    def walk(node):
        if isinstance(node, dict):
            if "$ref" in node:
                return walk(defs[node["$ref"].split("/")[-1]])
            return {k: walk(v) for k, v in node.items() if k not in ("$defs", "title")}
        if isinstance(node, list):
            return [walk(x) for x in node]
        return node
    return walk(schema)


def simplify(schema: dict) -> dict:
    """A plainer schema for providers with a stricter JSON-schema dialect (Gemini's function calling):
    "anyOf [X, null]" becomes X with nullable: true, and defaults / titles are dropped. The answer is still
    validated against the full schema afterwards."""
    def walk(node):
        if isinstance(node, list):
            return [walk(x) for x in node]
        if not isinstance(node, dict):
            return node
        node = {k: v for k, v in node.items() if k not in ("default", "title")}
        opts = node.get("anyOf")
        if opts and any(o.get("type") == "null" for o in opts):
            rest = [o for o in opts if o.get("type") != "null"]
            if len(rest) == 1:
                merged = {**{k: v for k, v in node.items() if k != "anyOf"}, **rest[0], "nullable": True}
                return walk(merged)
        return {k: walk(v) for k, v in node.items()}
    return walk(schema)


class OpenAICompatExtractor(_AIExtractor):
    """OpenAI, Google Gemini, Groq, OpenRouter, Ollama... anything with an OpenAI-style /chat/completions."""

    def __init__(self, base_url: str, api_key: str, model: str, max_tokens: int | None = None, provider: str = "openai",
                 recorder=None, transport=None, max_pdf_pages: int = 20, extra_instructions: str | None = None,
                 fallback_models: list[str] | None = None):
        import httpx

        super().__init__(model, max_tokens, recorder, extra_instructions, fallback_models)
        if not base_url or not model:
            raise RuntimeError("Set the base URL and model in Settings → AI connector")
        self.provider = provider
        self.base_url = base_url.rstrip("/")
        self.max_pdf_pages = max_pdf_pages
        self.http = httpx.Client(timeout=600, transport=transport,
                                 headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"})

    def _pdf_pages_as_images(self, data: bytes) -> list[bytes]:
        import pypdfium2 as pdfium
        pdf = pdfium.PdfDocument(data)
        out = []
        for i in range(min(len(pdf), self.max_pdf_pages)):
            img = pdf[i].render(scale=1.6).to_pil()
            buf = io.BytesIO()
            img.convert("RGB").save(buf, format="JPEG", quality=80)
            out.append(buf.getvalue())
        return out

    def _post(self, body: dict) -> dict:
        r = self.http.post(f"{self.base_url}/chat/completions", json=body)
        if r.status_code == 400 and "max_completion_tokens" in r.text and "max_tokens" in body:
            body = {**body, "max_completion_tokens": body.pop("max_tokens")}      # newer OpenAI models
            r = self.http.post(f"{self.base_url}/chat/completions", json=body)
        if r.status_code >= 400:
            if _is_rate_limit(r.status_code, r.text):
                raise RateLimited(f"{self.provider} {r.status_code}: {r.text[:200]}")
            raise RuntimeError(f"{self.provider} API error {r.status_code}: {r.text[:300]}")
        return r.json()

    def _call(self, parts, usage: dict) -> dict:
        content = []
        for kind, data, media in parts:
            if kind == "text":
                content.append({"type": "text", "text": data})
            else:
                images = self._pdf_pages_as_images(data) if kind == "pdf" else [data]
                mt = "image/jpeg" if kind == "pdf" else media
                content += [{"type": "image_url", "image_url": {"url": f"data:{mt};base64,{base64.b64encode(im).decode()}"}}
                            for im in images]
        body = {"model": self.model_name, "max_tokens": self.max_tokens, "temperature": 0,
                "messages": [{"role": "system", "content": self.system_prompt}, {"role": "user", "content": content}],
                "tools": [{"type": "function", "function": {
                    "name": TOOL_NAME, "description": "Record every rate, package, activity, place and term in the document.",
                    "parameters": simplify(dereference(tool_schema())) if self.provider == "gemini"
                                  else dereference(tool_schema())}}],
                "tool_choice": {"type": "function", "function": {"name": TOOL_NAME}}}
        data = self._post(body)
        u = data.get("usage") or {}
        usage["in"], usage["out"] = u.get("prompt_tokens", 0) or 0, u.get("completion_tokens", 0) or 0
        # OpenAI and several compatible providers cache repeated prompt prefixes on their own and report it here
        usage["cached"] = ((u.get("prompt_tokens_details") or {}).get("cached_tokens") or 0)
        choice = (data.get("choices") or [{}])[0]
        if choice.get("finish_reason") == "length":
            raise RuntimeError("Extraction was cut off. Lower the chunk size or raise max tokens in Settings.")
        msg = choice.get("message") or {}
        calls = msg.get("tool_calls") or []
        raw = calls[0]["function"]["arguments"] if calls else msg.get("content") or ""
        if isinstance(raw, dict):
            return raw
        raw = raw.strip()
        if raw.startswith("```"):
            raw = raw.strip("`").split("\n", 1)[-1]
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            raise RuntimeError("The AI did not return the expected structured data. Try a stronger model.")

    def ping(self) -> dict:
        t0 = time.time()
        data = self._post({"model": self.model_name, "max_tokens": 10,
                           "messages": [{"role": "user", "content": "Reply with the single word OK."}]})
        u = data.get("usage") or {}
        self._record({"in": u.get("prompt_tokens", 0), "out": u.get("completion_tokens", 0)}, t0, True)
        return {"reply": ((data.get("choices") or [{}])[0].get("message") or {}).get("content", "").strip(),
                "model": self.model_name, "input_tokens": u.get("prompt_tokens"), "output_tokens": u.get("completion_tokens")}


class FixtureExtractor:
    """Returns pre-written extraction JSON (tests, demos, or re-running without API cost).

    Looks for <fixtures_dir>/<file stem>.json
    """
    model_name = "fixture"

    def __init__(self, fixtures_dir: str | Path):
        self.dir = Path(fixtures_dir)

    def extract(self, doc: ParsedDocument, filename: str, supplier_hint: str | None = None,
                reference: str | None = None) -> dict:
        self.last_reference = reference
        p = self.dir / (Path(filename).stem + ".json")
        if not p.exists():
            raise FileNotFoundError(f"No fixture extraction for {filename} at {p}")
        return Extraction.model_validate(json.loads(p.read_text())).model_dump()


def _batch(chunks: list[str], limit: int) -> list[list[str]]:
    batches, cur, size = [], [], 0
    for c in chunks:
        if cur and size + len(c) > limit:
            batches.append(cur)
            cur, size = [], 0
        cur.append(c)
        size += len(c)
    if cur:
        batches.append(cur)
    return batches or [[""]]


def merge_extractions(parts: list[dict]) -> dict:
    """Merge chunk results: first non-empty header fields win, lists are concatenated,
    hotels with the same name are combined, seasons with the same key have their periods unioned."""
    if len(parts) == 1:
        return parts[0]
    out = Extraction(document_type="unknown").model_dump()
    types = {p["document_type"] for p in parts} - {"unknown"}
    out["document_type"] = types.pop() if len(types) == 1 else ("mixed" if types else "unknown")
    for p in parts:
        for k in ("currency", "validity", "issued_on"):
            out[k] = out[k] or p.get(k)
        out["is_revision"] = out["is_revision"] or bool(p.get("is_revision"))
        for k in ("taxes", "rate_type"):
            if out[k] == "unknown":
                out[k] = p.get(k, "unknown")
        for k, v in (p.get("supplier") or {}).items():
            out["supplier"][k] = out["supplier"].get(k) or v
        for s in p.get("seasons", []):
            existing = next((x for x in out["seasons"] if x["key"] == s["key"]), None)
            if existing:
                existing["periods"] += [pr for pr in s["periods"] if pr not in existing["periods"]]
            else:
                out["seasons"].append(s)
        for h in p.get("hotels", []):
            existing = next((x for x in out["hotels"] if x["name"].strip().lower() == h["name"].strip().lower()), None)
            if existing:
                for k in ("rates", "supplements", "blackout_dates"):
                    existing[k] += h.get(k, [])
            else:
                out["hotels"].append(h)
        for k in ("packages", "services", "places", "general_terms", "warnings"):
            out[k] += p.get(k, [])
    return out
