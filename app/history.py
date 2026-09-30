"""Rate history: how a hotel's, add-on's or package's prices moved from one supplier sheet to the next.

Every rate row keeps its dates and the file it came from, and a newer row links to the one it replaced
(`previous_rate_id`, `change_pct`). Packages form families of versions. This module only reads.

State of a row, as shown in the app:
  current   live, valid today            upcoming  live, starts later
  expired   live, but its dates are past  replaced  superseded by a newer sheet
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import db
from .loader import compare_prices


def rate_state(status: str, valid_from: date | None, valid_to: date | None, today: date | None = None) -> str:
    today = today or date.today()
    if status != "active":
        return "replaced"
    if valid_to and valid_to < today:
        return "expired"
    if valid_from and valid_from > today:
        return "upcoming"
    return "current"


def _f(x):
    return None if x is None else float(x)


def _docs(s: Session, ids) -> dict[int, db.SourceDocument]:
    ids = {i for i in ids if i}
    if not ids:
        return {}
    return {d.id: d for d in s.scalars(select(db.SourceDocument).where(db.SourceDocument.id.in_(ids))).all()}


def _doc_ref(d: db.SourceDocument | None) -> dict | None:
    if not d:
        return None
    when = d.approved_at or d.created_at
    return {"id": d.id, "filename": d.filename, "approved_at": when and when.isoformat(timespec="minutes")}


# ------------------------------------------------------------------ packages: which version applies
def covers(p: db.Package, d: date) -> bool:
    if p.valid_from and p.valid_to and not (p.valid_from <= d <= p.valid_to):
        return False
    return any(q.valid_from <= d <= q.valid_to for q in p.prices) or not p.prices


def pick_for_date(members: list[db.Package], d: date) -> db.Package | None:
    """Of a family's live versions, the newest one sold on date d (newer wins where editions overlap)."""
    fit = [m for m in members if m.status == "active" and covers(m, d)]
    return max(fit, key=lambda m: (m.version or 1, m.id)) if fit else None


def primary_version(members: list[db.Package], today: date | None = None) -> db.Package:
    """The version a family shows by default: valid today, else the next one to start, else the newest."""
    today = today or date.today()
    live = [m for m in members if m.status == "active"] or members
    now = pick_for_date(live, today)
    if now:
        return now
    upcoming = [m for m in live if m.valid_from and m.valid_from > today]
    if upcoming:
        return min(upcoming, key=lambda m: (m.valid_from, -(m.version or 1)))
    return max(live, key=lambda m: (m.version or 1, m.id))


def family(s: Session, p: db.Package) -> list[db.Package]:
    return s.scalars(select(db.Package).where(db.Package.family_id == (p.family_id or p.id))
                     .order_by(db.Package.version.desc(), db.Package.id.desc())).all()


def newer_version(s: Session, p: db.Package, on: date | None = None) -> db.Package | None:
    """A newer live version that should be used instead of p (for the trip's date, if known)."""
    members = [m for m in family(s, p) if m.id != p.id and (m.version or 1) > (p.version or 1) and m.status == "active"]
    if not members:
        return None
    if on:
        best = pick_for_date(members, on)
        if best:
            return best
        return max(members, key=lambda m: m.version or 1) if p.status != "active" else None
    if p.status != "active":
        return max(members, key=lambda m: m.version or 1)
    # still live, no date: only a newer version with the same or wider validity replaces it
    wider = [m for m in members if not (p.valid_from and p.valid_to and m.valid_from and m.valid_to)
             or (m.valid_from <= p.valid_from and m.valid_to >= p.valid_to)]
    return max(wider, key=lambda m: m.version or 1) if wider else None


def package_versions(s: Session, package_id: int) -> dict | None:
    p = s.get(db.Package, package_id)
    if not p:
        return None
    members = family(s, p)
    docs = _docs(s, [m.source_document_id for m in members])
    twin = lambda m: min((float(q.amount) for q in m.prices if q.occupancy == "double"), default=None)
    versions = [{"id": m.id, "version": m.version or 1, "title": m.title, "edition": m.edition,
                 "status": m.status, "state": rate_state(m.status, m.valid_from, m.valid_to),
                 "valid_from": m.valid_from and m.valid_from.isoformat(), "valid_to": m.valid_to and m.valid_to.isoformat(),
                 "from_price": twin(m), "currency": m.prices[0].currency if m.prices else None,
                 "document": _doc_ref(docs.get(m.source_document_id)),
                 "replaced_at": m.replaced_at and m.replaced_at.isoformat(timespec="minutes"),
                 "is_this": m.id == p.id} for m in members]
    prev = s.get(db.Package, p.previous_version_id) if p.previous_version_id else None
    # a line per category at a common group size, across versions (oldest first): the price trend chart
    trend = defaultdict(list)
    for m in sorted(members, key=lambda m: m.version or 1):
        tiers = sorted({q.pax_min for q in m.prices if q.occupancy == "double" and q.pax_min})
        tier = 2 if 2 in tiers else (tiers[0] if tiers else None)
        for q in m.prices:
            if q.occupancy == "double" and q.pax_min == tier:
                trend[q.category or "-"].append({"version": m.version or 1, "amount": float(q.amount), "pax": tier})
    return {"family_id": p.family_id or p.id, "versions": versions,
            "comparison": compare_prices(prev.prices, p.prices) if prev else None,
            "compared_with": {"id": prev.id, "version": prev.version or 1, "title": prev.title} if prev else None,
            "trend": [{"category": k, "points": v} for k, v in trend.items()]}


# ------------------------------------------------------------------ hotels
def hotel_history(s: Session, hotel_id: int, today: date | None = None) -> dict | None:
    h = s.get(db.Hotel, hotel_id)
    if not h:
        return None
    rows = s.scalars(select(db.HotelRate).where(db.HotelRate.hotel_id == h.id)
                     .order_by(db.HotelRate.valid_from, db.HotelRate.id)).all()
    docs = _docs(s, [r.source_document_id for r in rows])
    by_id = {r.id: r for r in rows}
    series = defaultdict(list)
    for r in rows:
        key = (r.room_type.name, r.meal_plan, r.occupancy, r.weekdays or "", r.is_net)
        series[key].append({"id": r.id, "valid_from": r.valid_from.isoformat(), "valid_to": r.valid_to.isoformat(),
                            "amount": float(r.amount), "currency": r.currency, "season": r.season_name,
                            "state": rate_state(r.status, r.valid_from, r.valid_to, today),
                            "change_pct": _f(r.change_pct), "previous_rate_id": r.previous_rate_id,
                            "document": _doc_ref(docs.get(r.source_document_id))})
    changes = []
    for r in rows:
        if r.previous_rate_id and r.previous_rate_id in by_id and r.change_pct is not None and r.change_pct != 0:
            o = by_id[r.previous_rate_id]
            changes.append({"room_type": r.room_type.name, "meal_plan": r.meal_plan, "occupancy": r.occupancy,
                            "weekdays": r.weekdays, "old": float(o.amount), "new": float(r.amount),
                            "pct": float(r.change_pct), "currency": r.currency,
                            "valid_from": r.valid_from.isoformat(), "valid_to": r.valid_to.isoformat(),
                            "old_valid_from": o.valid_from.isoformat(), "old_valid_to": o.valid_to.isoformat(),
                            "document": _doc_ref(docs.get(r.source_document_id)),
                            "at": (r.created_at or datetime.now()).isoformat(timespec="minutes")})
    changes.sort(key=lambda c: c["at"], reverse=True)
    return {"hotel_id": h.id, "hotel": h.name,
            "series": [{"room_type": k[0], "meal_plan": k[1], "occupancy": k[2], "weekdays": k[3] or None,
                        "is_net": k[4], "points": v} for k, v in series.items()],
            "changes": changes, "documents": [_doc_ref(d) for d in sorted(docs.values(), key=lambda d: d.id)]}


# ------------------------------------------------------------------ everything that moved recently
def recent_changes(s: Session, days: int = 90, limit: int = 300) -> dict:
    """Price moves from the documents approved in the last `days` days, newest first."""
    since = datetime.now() - timedelta(days=days)
    docs = s.scalars(select(db.SourceDocument).where(db.SourceDocument.status == "approved",
                                                     db.SourceDocument.approved_at >= since)
                     .order_by(db.SourceDocument.approved_at.desc())).all()
    items, packages, totals = [], [], defaultdict(int)
    for d in docs:
        ch = d.changes or {}
        ref = _doc_ref(d)
        for k, v in (ch.get("summary") or {}).items():
            if isinstance(v, int):
                totals[k] += v
        for i in ch.get("items") or []:
            if i["change"] in ("up", "down", "new_season") and i.get("pct") not in (None, 0):
                items.append({**i, "document": ref})
        for p in ch.get("packages") or []:
            if p.get("matched"):
                packages.append({**{k: p.get(k) for k in ("title", "package_id", "version", "family_id")},
                                 "counts": (p.get("prices") or {}).get("counts"),
                                 "avg_change_pct": (p.get("prices") or {}).get("avg_change_pct"), "document": ref})
    ups = [i["pct"] for i in items if i["pct"] > 0]
    downs = [i["pct"] for i in items if i["pct"] < 0]
    return {"days": days, "documents": len(docs), "totals": dict(totals),
            "up": len(ups), "down": len(downs),
            "avg_up_pct": round(sum(ups) / len(ups), 1) if ups else None,
            "avg_down_pct": round(sum(downs) / len(downs), 1) if downs else None,
            "items": items[:limit], "packages": packages}
