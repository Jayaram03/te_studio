"""AI connector: which AI reads the documents, with which key and limits, and what it costs.

Everything here is editable from Settings → AI connector. Claude (Anthropic) is the default. Any provider with
an OpenAI-compatible API also works (OpenAI, Google Gemini, Groq, OpenRouter, a local Ollama server, ...).

Where the API key comes from, in order:
  1. a key saved in the app (encrypted with SECRET_KEY)
  2. the provider's environment variable (ANTHROPIC_API_KEY, OPENAI_API_KEY, GEMINI_API_KEY, ...)
"""
from __future__ import annotations

import os
import time
from datetime import date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from . import db, secretbox
from .config import get_settings

PROVIDERS = {
    "anthropic": {"label": "Claude (Anthropic)", "kind": "anthropic", "base_url": None, "env": "ANTHROPIC_API_KEY",
                  "default_model": "claude-sonnet-5-5",
                  "models": ["claude-sonnet-5-5", "claude-opus-5-5", "claude-haiku-4-5-20251001"],
                  "note": "Default. Reads PDFs natively, including scans.", "keys_url": "https://console.anthropic.com"},
    "openai": {"label": "OpenAI", "kind": "openai", "base_url": "https://api.openai.com/v1", "env": "OPENAI_API_KEY",
               "default_model": "", "models": [], "note": "Use a model that supports function calling and images.",
               "keys_url": "https://platform.openai.com/api-keys"},
    "gemini": {"label": "Google Gemini", "kind": "openai",
               "base_url": "https://generativelanguage.googleapis.com/v1beta/openai", "env": "GEMINI_API_KEY",
               "default_model": "gemini-3.8-flash",
               "models": ["gemini-3.8-flash", "gemini-3.7-flash", "gemini-3.6-flash", "gemini-3.5-flash",
                          "gemini-3.5-flash-lite", "gemini-3.1-flash-lite"],
               "default_fallbacks": ["gemini-3.7-flash", "gemini-3.6-flash", "gemini-3.5-flash", "gemini-3.5-flash-lite"],
               "note": "Through Google's OpenAI-compatible endpoint. Free tier: limits are per model, so backup "
                       "models take over when one is used up. On the free tier Google may use what you send to "
                       "improve its products.",
               "keys_url": "https://aistudio.google.com/apikey"},
    "groq": {"label": "Groq", "kind": "openai", "base_url": "https://api.groq.com/openai/v1", "env": "GROQ_API_KEY",
             "default_model": "", "models": [], "note": "Fast and cheap; check the model supports tool calls.",
             "keys_url": "https://console.groq.com/keys"},
    "openrouter": {"label": "OpenRouter", "kind": "openai", "base_url": "https://openrouter.ai/api/v1",
                   "env": "OPENROUTER_API_KEY", "default_model": "", "models": [],
                   "note": "One key for many models from different companies.", "keys_url": "https://openrouter.ai/keys"},
    "custom": {"label": "Other (OpenAI-compatible)", "kind": "openai", "base_url": "", "env": "CUSTOM_AI_API_KEY",
               "default_model": "", "models": [], "note": "Any server with an OpenAI-style /chat/completions API, "
               "e.g. a local Ollama (http://localhost:11434/v1).", "keys_url": ""},
}

DEFAULTS = {"provider": "anthropic", "model": "", "base_url": "", "api_key_enc": None, "max_tokens": None,
            "price_input_per_mtok": None, "price_output_per_mtok": None, "price_currency": "USD",
            "monthly_budget": None, "enabled": True, "extra_instructions": "", "max_pdf_pages": 20,
            "fallback_models": []}      # tried in order when the main model hits a rate limit or is overloaded


class AIError(Exception):
    pass


# ------------------------------------------------------------------ settings
def load(s: Session) -> dict:
    row = s.get(db.AppSetting, "ai")
    cfg = {**DEFAULTS, **(row.value if row and isinstance(row.value, dict) else {})}
    if cfg["provider"] not in PROVIDERS:
        cfg["provider"] = "anthropic"
    return cfg


def _key(cfg: dict) -> tuple[str | None, str | None]:
    """(api key, where it came from)."""
    if cfg.get("api_key_enc"):
        try:
            return secretbox.decrypt(cfg["api_key_enc"]), "app"
        except secretbox.SecretError:
            return None, "unreadable"
    env = PROVIDERS[cfg["provider"]]["env"]
    val = os.environ.get(env) or getattr(get_settings(), env.lower(), None)   # environment or .env file
    return (val, "environment") if val else (None, None)


def resolved(cfg: dict) -> dict:
    p = PROVIDERS[cfg["provider"]]
    return {"provider": cfg["provider"], "kind": p["kind"],
            "model": cfg.get("model") or p["default_model"] or (get_settings().extraction_model if cfg["provider"] == "anthropic" else ""),
            "base_url": (cfg.get("base_url") or p["base_url"] or "").rstrip("/"),
            "max_tokens": int(cfg.get("max_tokens") or get_settings().extraction_max_tokens)}


def public_view(s: Session) -> dict:
    cfg = load(s)
    key, source = _key(cfg)
    r = resolved(cfg)
    return {**{k: v for k, v in cfg.items() if k != "api_key_enc"}, **r,
            "key_set": bool(key), "key_hint": secretbox.hint(key), "key_source": source,
            "key_env_var": PROVIDERS[cfg["provider"]]["env"], "can_save_keys": secretbox.available(),
            "demo_mode": bool(get_settings().fixtures_dir),
            "providers": [{"id": k, **{x: v[x] for x in ("label", "kind", "base_url", "env", "default_model", "models", "note", "keys_url")},
                           "default_fallbacks": v.get("default_fallbacks", []),
                           "env_key_set": bool(os.environ.get(v["env"]) or getattr(get_settings(), v["env"].lower(), None))}
                          for k, v in PROVIDERS.items()]}


def save(s: Session, data: dict) -> dict:
    cfg = load(s)
    if "provider" in data:
        if data["provider"] not in PROVIDERS:
            raise AIError("Unknown provider")
        if data["provider"] != cfg["provider"]:
            cfg["api_key_enc"] = None            # a key belongs to one provider
        cfg["provider"] = data["provider"]
    for k in ("model", "base_url", "price_currency", "extra_instructions"):
        if k in data:
            cfg[k] = (data[k] or "").strip()
    if len(cfg.get("extra_instructions") or "") > 4000:
        raise AIError("Keep the extra instructions under 4,000 characters")
    if "fallback_models" in data:
        raw = data["fallback_models"]
        items = raw.split(",") if isinstance(raw, str) else (raw or [])
        cfg["fallback_models"] = list(dict.fromkeys(m.strip() for m in items if m and m.strip()))[:6]
    if "max_pdf_pages" in data and data["max_pdf_pages"] not in (None, ""):
        cfg["max_pdf_pages"] = max(1, min(100, int(data["max_pdf_pages"])))
    for k in ("max_tokens", "price_input_per_mtok", "price_output_per_mtok", "monthly_budget"):
        if k in data:
            v = data[k]
            cfg[k] = None if v in (None, "") else float(v)
    if cfg.get("max_tokens"):
        cfg["max_tokens"] = int(cfg["max_tokens"])
    if "enabled" in data:
        cfg["enabled"] = bool(data["enabled"])
    if data.get("clear_key"):
        cfg["api_key_enc"] = None
    if data.get("api_key"):
        try:
            cfg["api_key_enc"] = secretbox.encrypt(data["api_key"].strip())
        except secretbox.SecretError as e:
            raise AIError(str(e))
    if PROVIDERS[cfg["provider"]]["kind"] == "openai":
        if not (cfg.get("base_url") or PROVIDERS[cfg["provider"]]["base_url"]):
            raise AIError("Enter the provider's base URL")
        if not cfg.get("model"):
            raise AIError("Enter the model name exactly as your provider lists it")
    row = s.get(db.AppSetting, "ai")
    if row:
        row.value = cfg
    else:
        s.add(db.AppSetting(key="ai", value=cfg))
    s.commit()
    return public_view(s)


# ------------------------------------------------------------------ usage & cost
CACHE_READ_FACTOR = Decimal("0.1")   # cached input is billed at about a tenth of the normal input price


def cost_of(cfg: dict, tin: int, tout: int, cached: int = 0) -> Decimal | None:
    """Estimated cost from the prices entered in Settings. `cached` input tokens (part of tin) are counted at
    the provider's cache-read discount."""
    pi, po = cfg.get("price_input_per_mtok"), cfg.get("price_output_per_mtok")
    if pi is None and po is None:
        return None
    cached = min(cached or 0, tin or 0)
    billable_in = Decimal(tin - cached) + Decimal(cached) * CACHE_READ_FACTOR
    return (Decimal(str(pi or 0)) * billable_in + Decimal(str(po or 0)) * tout) / Decimal(1_000_000)


def recorder(s: Session, cfg: dict, purpose: str, document_id: int | None = None):
    """Returns the callback extractors use to log each AI call."""
    def rec(provider, model, input_tokens, output_tokens, duration_ms, ok, error=None, cached_tokens=0):
        s.add(db.AIUsage(provider=provider, model=model, purpose=purpose, document_id=document_id,
                         input_tokens=input_tokens or 0, output_tokens=output_tokens or 0,
                         cost=cost_of(cfg, input_tokens or 0, output_tokens or 0, cached_tokens),
                         duration_ms=duration_ms,
                         ok=ok, error=(error or "")[:2000] or None))
        s.commit()
    return rec


def month_cost(s: Session, today: date | None = None) -> float:
    """This month's cost, counted exactly like the AI connector screen shows it: the cost recorded with each
    call, or -- for calls made before prices were entered -- an estimate at today's prices. The budget check
    uses this, so what you see is what's enforced."""
    today = today or date.today()
    start = datetime(today.year, today.month, 1)
    cfg = load(s)
    recorded = s.scalar(select(func.coalesce(func.sum(db.AIUsage.cost), 0)).where(db.AIUsage.at >= start)) or 0
    tin, tout = s.execute(select(func.coalesce(func.sum(db.AIUsage.input_tokens), 0),
                                 func.coalesce(func.sum(db.AIUsage.output_tokens), 0))
                          .where(db.AIUsage.at >= start, db.AIUsage.cost.is_(None))).one()
    estimate = cost_of(cfg, int(tin), int(tout)) or 0
    return float(Decimal(str(recorded)) + Decimal(str(estimate)))


def usage_summary(s: Session, days: int = 30) -> dict:
    now = datetime.utcnow()
    since = now - timedelta(days=days - 1)
    since = datetime(since.year, since.month, since.day)
    month_start = datetime(now.year, now.month, 1)
    cfg = load(s)

    def rcost(u):   # recorded cost, or an estimate from today's prices for calls made before prices were set
        if u.cost is not None:
            return float(u.cost)
        c = cost_of(cfg, u.input_tokens, u.output_tokens)
        return float(c) if c is not None else 0.0

    def totals(start):
        rows_ = s.scalars(select(db.AIUsage).where(db.AIUsage.at >= start)).all()
        n = len(rows_)
        return {"calls": n, "input_tokens": sum(u.input_tokens for u in rows_),
                "output_tokens": sum(u.output_tokens for u in rows_),
                "cost": round(sum(rcost(u) for u in rows_), 4), "failed": sum(1 for u in rows_ if not u.ok),
                "avg_seconds": round(sum(u.duration_ms or 0 for u in rows_) / n / 1000, 1) if n else None}

    rows = s.scalars(select(db.AIUsage).where(db.AIUsage.at >= since).order_by(db.AIUsage.at)).all()
    daily = {}
    for i in range(days):
        d = (since + timedelta(days=i)).date().isoformat()
        daily[d] = {"date": d, "calls": 0, "input_tokens": 0, "output_tokens": 0, "cost": 0.0}
    by_model: dict[str, dict] = {}
    for r in rows:
        d = daily.setdefault(r.at.date().isoformat(), {"date": r.at.date().isoformat(), "calls": 0,
                                                        "input_tokens": 0, "output_tokens": 0, "cost": 0.0})
        d["calls"] += 1
        d["input_tokens"] += r.input_tokens
        d["output_tokens"] += r.output_tokens
        d["cost"] += rcost(r)
        m = by_model.setdefault(f"{r.provider} · {r.model}", {"model": f"{r.provider} · {r.model}", "calls": 0,
                                                             "input_tokens": 0, "output_tokens": 0, "cost": 0.0})
        m["calls"] += 1
        m["input_tokens"] += r.input_tokens
        m["output_tokens"] += r.output_tokens
        m["cost"] += rcost(r)
    recent = s.execute(select(db.AIUsage, db.SourceDocument.filename)
                       .outerjoin(db.SourceDocument, db.AIUsage.document_id == db.SourceDocument.id)
                       .order_by(db.AIUsage.at.desc()).limit(12)).all()
    month = totals(month_start)
    budget = cfg.get("monthly_budget")
    return {"month": month, "period": totals(since), "days": days, "daily": list(daily.values()),
            "by_model": sorted(by_model.values(), key=lambda m: -m["calls"]),
            "budget": budget, "price_currency": cfg.get("price_currency") or "USD",
            "budget_used_pct": round(100 * (month["cost"] or 0) / budget, 1) if budget else None,
            "prices_set": cfg.get("price_input_per_mtok") is not None or cfg.get("price_output_per_mtok") is not None,
            "recent": [{"id": u.id, "at": u.at.isoformat() + "Z", "provider": u.provider, "model": u.model,
                        "purpose": u.purpose, "document_id": u.document_id, "document": fn,
                        "input_tokens": u.input_tokens, "output_tokens": u.output_tokens,
                        "cost": rcost(u) if (u.cost is not None or cfg.get("price_input_per_mtok") is not None) else None, "seconds":
                        round(u.duration_ms / 1000, 1) if u.duration_ms else None, "ok": u.ok, "error": u.error}
                       for u, fn in recent]}


# ------------------------------------------------------------------ building the extractor
def build_extractor(s: Session, purpose: str = "extraction", document_id: int | None = None):
    """The extractor for the current AI settings, logging usage. Raises AIError with a readable reason."""
    from .extractor import ClaudeExtractor, FixtureExtractor, OpenAICompatExtractor

    st = get_settings()
    if st.fixtures_dir:
        return FixtureExtractor(st.fixtures_dir)
    cfg = load(s)
    if not cfg.get("enabled", True):
        raise AIError("AI reading is switched off in Settings → AI connector")
    budget = cfg.get("monthly_budget")
    if budget and month_cost(s) >= budget:
        raise AIError(f"This month's AI budget ({budget:g} {cfg.get('price_currency') or 'USD'}) is used up. "
                      "Raise it in Settings → AI connector.")
    key, source = _key(cfg)
    if not key:
        raise AIError("No API key for " + PROVIDERS[cfg["provider"]]["label"] + ". Add one in Settings → AI connector"
                      + (" (the saved key can't be read because SECRET_KEY changed)" if source == "unreadable" else ""))
    r = resolved(cfg)
    rec = recorder(s, cfg, purpose, document_id)
    extra = cfg.get("extra_instructions") or None
    backups = [m for m in (cfg.get("fallback_models") or []) if m != r["model"]]
    if r["kind"] == "anthropic":
        return ClaudeExtractor(api_key=key, model=r["model"], max_tokens=r["max_tokens"], recorder=rec,
                               extra_instructions=extra, fallback_models=backups)
    return OpenAICompatExtractor(base_url=r["base_url"], api_key=key, model=r["model"], max_tokens=r["max_tokens"],
                                 provider=cfg["provider"], recorder=rec, extra_instructions=extra,
                                 max_pdf_pages=int(cfg.get("max_pdf_pages") or 20), fallback_models=backups)


def test_connection(s: Session) -> dict:
    t0 = time.time()
    try:
        ex = build_extractor(s, purpose="test")
        if not hasattr(ex, "ping"):
            return {"ok": True, "reply": "Demo mode: saved extractions are used, no AI is called.", "seconds": 0}
        out = ex.ping()
        return {"ok": True, **out, "seconds": round(time.time() - t0, 1)}
    except Exception as e:  # noqa: BLE001 - shown to the admin
        return {"ok": False, "error": str(e)[:500], "seconds": round(time.time() - t0, 1)}
