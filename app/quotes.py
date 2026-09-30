"""Quotations: numbered, frozen copies of a trip as it was sent to the customer.

  save            trip -> new quotation (TE-Q-2026-0007, version 1, 2, 3 ... per trip)
  update          write the trip's current state back into an existing quotation (same number)
  restore         copy a quotation back into its trip to edit it (the trip is the working copy)
  new_trip_from   start a new trip from a quotation (same plan, another customer)
  delete          remove a quotation (the trip stays)

The copy (`snapshot`) is the full trip view: itinerary, costing, options, totals, inclusions, terms. The
quotation PDF and its client link are made from the copy, so they never change when the trip is edited.
"""
from __future__ import annotations

import secrets
from datetime import date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from . import company, db, trips


class QuoteError(ValueError):
    pass


def _snapshot(s: Session, t: db.Trip) -> dict:
    v = trips.trip_view(s, t)
    for k in ("notes_log", "payments", "suggested_addons", "share_token", "problems", "newer_versions"):
        v.pop(k, None)
    return v


def _fill(q: db.Quotation, t: db.Trip, snap: dict):
    tt = snap["totals"]
    q.title, q.customer_name, q.customer_phone, q.customer_email = t.title, t.customer_name, t.customer_phone, t.customer_email
    q.destination, q.start_date, q.travellers = t.destination, t.start_date, tt["travellers"]
    q.currency = tt["currency"] or t.currency
    q.total = Decimal(str(tt["sell"])) if tt["sell"] is not None else None
    q.per_person = Decimal(str(tt["per_person"])) if tt["per_person"] is not None else None
    q.options = [{"label": o["label"], "sell": o["sell"], "per_person": o["per_person"]} for o in tt["options"]]
    q.snapshot = snap


def save(s: Session, t: db.Trip, by: str | None = None, note: str | None = None,
         valid_days: int | None = None) -> db.Quotation:
    if t.is_template:
        raise QuoteError("Templates can't be quoted - start a trip from the template first")
    if not t.items and not t.days:
        raise QuoteError("Add an itinerary or costs before saving a quotation")
    snap = _snapshot(s, t)
    version = (s.scalar(select(func.max(db.Quotation.version)).where(db.Quotation.trip_id == t.id)) or 0) + 1
    days = valid_days if valid_days is not None else int(company.get_all(s)["quote"].get("validity_days") or 7)
    q = db.Quotation(trip_id=t.id, version=version, status="draft", created_by=by, note=note,
                     valid_until=date.today() + timedelta(days=days), share_prices=t.share_prices)
    _fill(q, t, snap)
    s.add(q)
    s.flush()
    q.number = f"TE-Q-{date.today().year}-{q.id:04d}"
    if t.status == "enquiry":
        t.status = "quoted"
    t.notes_log.append(db.TripNote(author=by, text=f"Quotation {q.number} (v{version}) saved: "
                                                   f"{q.currency} {float(q.total or 0):,.0f}"))
    s.commit()
    return q


def update(s: Session, q: db.Quotation, by: str | None = None) -> db.Quotation:
    """Overwrite the quotation with its trip's current itinerary and costing (keeps number and version)."""
    t = s.get(db.Trip, q.trip_id) if q.trip_id else None
    if not t:
        raise QuoteError("The trip for this quotation was deleted - start a new trip from it instead")
    _fill(q, t, _snapshot(s, t))
    q.updated_at = datetime.now()
    t.notes_log.append(db.TripNote(author=by, text=f"Quotation {q.number} updated: {q.currency} {float(q.total or 0):,.0f}"))
    s.commit()
    return q


def patch(s: Session, q: db.Quotation, data: dict) -> db.Quotation:
    if "status" in data:
        if data["status"] not in db.QUOTE_STATUSES:
            raise QuoteError(f"Status must be one of {', '.join(db.QUOTE_STATUSES)}")
        if data["status"] == "sent" and not q.sent_at:
            q.sent_at = datetime.now()
        q.status = data["status"]
        t = s.get(db.Trip, q.trip_id) if q.trip_id else None
        if t and q.status == "accepted":
            if t.status in ("enquiry", "quoted"):
                t.status = "confirmed"
            chosen = data.get("chosen_option") or t.chosen_option
            t.notes_log.append(db.TripNote(text=f"Quotation {q.number} accepted" + (f" ({chosen})" if chosen else "")))
    if "chosen_option" in data and q.trip_id:
        t = s.get(db.Trip, q.trip_id)
        if t:
            t.chosen_option = data["chosen_option"] or None
    if "valid_until" in data:
        q.valid_until = date.fromisoformat(data["valid_until"]) if data["valid_until"] else None
    if "note" in data:
        q.note = data["note"] or None
    if "title" in data and data["title"]:
        q.title = data["title"]
        q.snapshot = {**q.snapshot, "title": data["title"]}
    s.commit()
    return q


def restore(s: Session, q: db.Quotation, by: str | None = None) -> db.Trip:
    """Put the quotation's itinerary and costing back into its trip, to edit it. Returns the trip."""
    t = s.get(db.Trip, q.trip_id) if q.trip_id else None
    if not t:
        return new_trip_from(s, q, by)
    _load_snapshot(t, q.snapshot)
    t.notes_log.append(db.TripNote(author=by, text=f"Opened quotation {q.number} for editing"))
    s.commit()
    return t


def new_trip_from(s: Session, q: db.Quotation, by: str | None = None, title: str | None = None) -> db.Trip:
    t = db.Trip(title=title or q.snapshot.get("title") or q.title, created_by=by, status="enquiry")
    _load_snapshot(t, q.snapshot)
    for f in ("customer_name", "customer_phone", "customer_email", "lead_source", "assigned_to"):
        if not title:                         # a copy for another customer starts blank; an edit keeps them
            setattr(t, f, q.snapshot.get(f))
    t.notes_log.append(db.TripNote(author=by, text=f"Started from quotation {q.number}"))
    s.add(t)
    s.commit()
    return t


def _load_snapshot(t: db.Trip, v: dict):
    for f in ("destination", "adults", "children_with_bed", "children_without_bed", "extra_beds", "category",
              "currency", "markup_pct", "gst_pct", "inclusions", "exclusions", "terms", "chosen_option", "share_prices"):
        if f in v and v[f] is not None:
            setattr(t, f, v[f])
    t.title = v.get("title") or t.title
    t.start_date = date.fromisoformat(v["start_date"]) if v.get("start_date") else None
    t.days.clear()
    t.items.clear()
    for d in v.get("days", []):
        t.days.append(db.TripDay(position=d["position"], title=d.get("title"), description=d.get("description"),
                                 overnight=d.get("overnight"), meals=d.get("meals"),
                                 source_package_id=d.get("source_package_id"), source_day_id=d.get("source_day_id")))
    for i in v.get("items", []):
        t.items.append(db.TripItem(kind=i["kind"], ref_id=i.get("ref_id"), day_position=i.get("day_position"),
                                   description=i["description"], quantity=Decimal(str(i["quantity"])),
                                   unit_amount=Decimal(str(i["unit_amount"])), amount=Decimal(str(i["amount"])),
                                   currency=i["currency"], optional=i.get("optional", False),
                                   option_label=i.get("option_label"), details=i.get("details") or {}))


def share(s: Session, q: db.Quotation, enable: bool = True, prices: bool | None = None) -> db.Quotation:
    if enable and not q.share_token:
        q.share_token = secrets.token_urlsafe(18)
    if not enable:
        q.share_token = None
    if prices is not None:
        q.share_prices = prices
    s.commit()
    return q


def expire_old(s: Session, today: date | None = None) -> int:
    """Drafts and sent quotations past their validity become 'expired' (run by the daily job)."""
    today = today or date.today()
    rows = s.scalars(select(db.Quotation).where(db.Quotation.status.in_(("draft", "sent")),
                                                db.Quotation.valid_until < today)).all()
    for q in rows:
        q.status = "expired"
    s.commit()
    return len(rows)


def view(q: db.Quotation, full: bool = False) -> dict:
    out = {"id": q.id, "number": q.number, "trip_id": q.trip_id, "version": q.version, "title": q.title,
           "customer_name": q.customer_name, "customer_phone": q.customer_phone, "customer_email": q.customer_email,
           "destination": q.destination, "start_date": q.start_date and q.start_date.isoformat(),
           "travellers": q.travellers, "status": q.status,
           "valid_until": q.valid_until and q.valid_until.isoformat(),
           "is_expired": bool(q.valid_until and q.valid_until < date.today() and q.status in ("draft", "sent")),
           "currency": q.currency, "total": float(q.total) if q.total is not None else None,
           "per_person": float(q.per_person) if q.per_person is not None else None, "options": q.options or [],
           "share_token": q.share_token, "share_prices": q.share_prices, "note": q.note, "created_by": q.created_by,
           "created_at": q.created_at and q.created_at.isoformat(timespec="minutes"),
           "updated_at": q.updated_at and q.updated_at.isoformat(timespec="minutes"),
           "sent_at": q.sent_at and q.sent_at.isoformat(timespec="minutes"),
           "days": len(q.snapshot.get("days", [])), "items": len(q.snapshot.get("items", []))}
    if full:
        out["snapshot"] = q.snapshot
    return out


def listing(s: Session, q: str | None = None, status: str | None = None, trip_id: int | None = None) -> list[dict]:
    stmt = select(db.Quotation).order_by(db.Quotation.id.desc())
    if trip_id:
        stmt = stmt.where(db.Quotation.trip_id == trip_id)
    if status:
        stmt = stmt.where(db.Quotation.status == status)
    if q:
        like = f"%{q}%"
        stmt = stmt.where(or_(db.Quotation.number.ilike(like), db.Quotation.title.ilike(like),
                              db.Quotation.customer_name.ilike(like), db.Quotation.destination.ilike(like)))
    return [view(x) for x in s.scalars(stmt.limit(500)).all()]
