"""Company profile and app defaults (Settings page). Stored in app_settings; these are the starting values."""
from __future__ import annotations

from sqlalchemy.orm import Session

from . import db

DEFAULTS: dict = {
    "company": {
        "name": "Travel Episodes",
        "tagline": "Every trip, an episode",
        "address": "No-# 1 Etti Annal Nagar Poonamallee,\nChennai 600 056.",
        "email": "travelepisodeschennai@gmail.com",
        "instagram": "travel_episodes_",
        "website": "",
        "gst_number": "",
    },
    "team": [
        {"name": "Dhineshwar", "phone": "+91 98418 44977"},
        {"name": "Rakesh", "phone": "+91 89397 18676"},
        {"name": "Jayaram", "phone": "+91 95519 33805"},
    ],
    "quote": {
        "default_markup_pct": 10,
        "default_gst_pct": 5,
        "validity_days": 7,
        "terms": [
            "Prices are per the travellers and dates shown and may change with hotel or transport tariffs.",
            "Hotels are subject to availability at the time of booking; similar hotels are offered if unavailable.",
        ],
        "payment_terms": "50% advance to confirm, balance 15 days before travel.",
        "bank_details": "",
        "footer": "Thank you for planning with Travel Episodes.",
    },
    "lead_sources": ["Instagram", "WhatsApp", "Referral", "Agilysis", "Website", "Google", "Walk-in", "Repeat customer", "Other"],
}


def get_all(s: Session) -> dict:
    stored = {r.key: r.value for r in s.query(db.AppSetting).all()}
    out = {}
    for k, v in DEFAULTS.items():
        if k in stored and isinstance(v, dict) and isinstance(stored[k], dict):
            out[k] = {**v, **stored[k]}
        else:
            out[k] = stored.get(k, v)
    return out


def save(s: Session, data: dict) -> dict:
    for k, v in data.items():
        if k not in DEFAULTS:
            continue
        row = s.get(db.AppSetting, k)
        if row:
            row.value = v
        else:
            s.add(db.AppSetting(key=k, value=v))
    s.commit()
    return get_all(s)


def team_member(s: Session, name: str | None) -> dict | None:
    if not name:
        return None
    return next((m for m in get_all(s)["team"] if m.get("name", "").lower() == name.lower()), {"name": name})
