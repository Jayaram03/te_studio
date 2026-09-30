"""Processing options editable from Settings → Processing (stored in app_settings["processing"]).

Environment variables give the starting values; anything saved in the app overrides them. `refresh(s)` is
called before documents are processed, so a change made on one server instance reaches the others too.
"""
from __future__ import annotations

import time

from sqlalchemy.orm import Session

from . import db
from .config import get_settings

# option -> (type, help text shown in Settings)
OPTIONS = {
    "pdf_mode": (str, "auto: text for normal PDFs, the PDF itself for scans · text: always text · native: always send the PDF/pages"),
    "chunk_chars": (int, "Very long documents are read in parts of about this many characters"),
    "default_currency": (str, "Used (with a warning) when a sheet doesn't state its currency"),
    "weekend_days": (str, "What 'weekend' means on a rate sheet, e.g. fri,sat"),
    "auto_approve": (bool, "Save straight to the library when a document has no errors (skip review)"),
    "session_days": (int, "How many days a sign-in lasts"),
    "max_upload_mb": (float, "Largest upload accepted (Vercel's hard limit is 4.5 MB)"),
}
_baseline: dict | None = None
_last = 0.0


def _base() -> dict:
    global _baseline
    if _baseline is None:
        st = get_settings()
        _baseline = {k: getattr(st, k) for k in OPTIONS}
    return _baseline


def values(s: Session) -> dict:
    row = s.get(db.AppSetting, "processing")
    saved = row.value if row and isinstance(row.value, dict) else {}
    return {k: saved.get(k, _base()[k]) for k in OPTIONS}


def refresh(s: Session, force: bool = False):
    global _last
    if not force and time.time() - _last < 20:
        return
    st = get_settings()
    for k, v in values(s).items():
        setattr(st, k, v)
    _last = time.time()


def save(s: Session, data: dict) -> dict:
    clean = {}
    for k, (typ, _) in OPTIONS.items():
        if k in data and data[k] not in (None, ""):
            v = data[k]
            clean[k] = (v in (True, "true", "1", 1, "on")) if typ is bool else typ(v)
    if clean.get("pdf_mode") and clean["pdf_mode"] not in ("auto", "text", "native"):
        raise ValueError("PDF mode must be auto, text or native")
    if clean.get("chunk_chars") is not None and not 5000 <= clean["chunk_chars"] <= 400000:
        raise ValueError("Chunk size must be between 5,000 and 400,000 characters")
    if clean.get("session_days") is not None and not 1 <= clean["session_days"] <= 90:
        raise ValueError("Sign-in length must be 1–90 days")
    row = s.get(db.AppSetting, "processing")
    if row:
        row.value = clean
    else:
        s.add(db.AppSetting(key="processing", value=clean))
    s.commit()
    refresh(s, force=True)
    return view(s)


def view(s: Session) -> dict:
    v = values(s)
    return {"values": v, "defaults": _base(), "help": {k: h for k, (_, h) in OPTIONS.items()}}


def reset_cache():   # tests
    global _baseline, _last
    _baseline, _last = None, 0.0
