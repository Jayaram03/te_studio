"""Browse everything that has been ingested: hotels, packages, activities & transfers, places, suppliers."""
from __future__ import annotations

from collections import defaultdict
from datetime import date

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from . import db, history
from .loader import compare_prices
from .normalize import name_key
from .rates import package_detail


def _f(x):
    return None if x is None else float(x)


def summary(s: Session) -> dict:
    count = lambda m, *w: s.scalar(select(func.count(m.id)).where(*w))
    return {"hotels": count(db.Hotel),
            "hotels_with_rates": s.scalar(select(func.count(func.distinct(db.HotelRate.hotel_id)))
                                          .where(db.HotelRate.status == "active")),
            "hotel_rates": count(db.HotelRate, db.HotelRate.status == "active"),
            "packages": s.scalar(select(func.count(func.distinct(db.Package.family_id))).where(db.Package.status == "active")),
            "services": count(db.ServiceRate, db.ServiceRate.status == "active"),
            "places": count(db.Place), "suppliers": count(db.Supplier),
            "trips": count(db.Trip),
            "documents_to_review": count(db.SourceDocument, db.SourceDocument.status == "needs_review")}


def hotels(s: Session, q: str | None = None, city: str | None = None, category: str | None = None,
           has_rates: bool | None = None, limit: int = 500) -> list[dict]:
    stmt = select(db.Hotel)
    if q:
        stmt = stmt.where(or_(db.Hotel.name_key.like(f"%{name_key(q)}%"), db.Hotel.city.ilike(f"%{q}%"),
                              db.Hotel.destination.ilike(f"%{q}%")))
    if city:
        stmt = stmt.where(or_(db.Hotel.city.ilike(f"%{city}%"), db.Hotel.destination.ilike(f"%{city}%")))
    if category:
        stmt = stmt.where(db.Hotel.category.ilike(category))
    rows = s.scalars(stmt.order_by(db.Hotel.city, db.Hotel.name).limit(limit)).all()
    ids = [h.id for h in rows]
    rate_counts = dict(s.execute(select(db.HotelRate.hotel_id, func.count(db.HotelRate.id))
                                 .where(db.HotelRate.hotel_id.in_(ids), db.HotelRate.status == "active")
                                 .group_by(db.HotelRate.hotel_id)).all()) if ids else {}
    pkg_counts = dict(s.execute(select(db.PackageHotel.hotel_id, func.count(func.distinct(db.PackageHotel.package_id)))
                                .where(db.PackageHotel.hotel_id.in_(ids)).group_by(db.PackageHotel.hotel_id)).all()) if ids else {}
    out = []
    for h in rows:
        n = rate_counts.get(h.id, 0)
        if has_rates is True and not n or has_rates is False and n:
            continue
        out.append({"id": h.id, "name": h.name, "city": h.city, "destination": h.destination, "category": h.category,
                    "property_type": h.property_type, "star_rating": h.star_rating, "rates": n,
                    "in_packages": pkg_counts.get(h.id, 0), "room_types": [r.name for r in h.room_types]})
    return out


def hotel_detail(s: Session, hotel_id: int) -> dict | None:
    h = s.get(db.Hotel, hotel_id)
    if not h:
        return None
    occ_order = {o: i for i, o in enumerate(("single", "double", "triple", "extra_adult", "child_with_bed",
                                                 "child_without_bed", "per_person"))}
    rates = sorted(s.scalars(select(db.HotelRate).where(db.HotelRate.hotel_id == h.id, db.HotelRate.status == "active")).all(),
                   key=lambda r: (r.room_type.name, r.meal_plan, occ_order.get(r.occupancy, 9), r.valid_from, r.weekdays or ""))
    sur = s.scalars(select(db.HotelSurcharge).where(db.HotelSurcharge.hotel_id == h.id,
                                                    db.HotelSurcharge.status == "active")).all()
    pk = s.execute(select(db.PackageHotel, db.Package).join(db.Package, db.PackageHotel.package_id == db.Package.id)
                   .where(db.PackageHotel.hotel_id == h.id, db.Package.status == "active")).all()
    sup = s.get(db.Supplier, h.supplier_id) if h.supplier_id else None
    return {"id": h.id, "name": h.name, "city": h.city, "destination": h.destination, "category": h.category,
            "property_type": h.property_type, "star_rating": h.star_rating, "address": h.address,
            "child_policy": h.child_policy, "supplier": sup.name if sup else None,
            "rates": [{"id": r.id, "room_type": r.room_type.name, "meal_plan": r.meal_plan, "occupancy": r.occupancy,
                       "amount": _f(r.amount), "currency": r.currency, "is_net": r.is_net,
                       "taxes_included": r.taxes_included, "valid_from": r.valid_from.isoformat(),
                       "valid_to": r.valid_to.isoformat(), "weekdays": r.weekdays, "season": r.season_name,
                       "state": history.rate_state(r.status, r.valid_from, r.valid_to),
                       "change_pct": _f(r.change_pct)} for r in rates],
            "history_rows": s.scalar(select(func.count(db.HotelRate.id)).where(db.HotelRate.hotel_id == h.id,
                                                                           db.HotelRate.status != "active")),
            "surcharges": [{"kind": x.kind, "name": x.name, "room_type": x.room_type,
                            "date_from": x.date_from.isoformat(), "date_to": x.date_to.isoformat(),
                            "amount": _f(x.amount), "basis": x.basis} for x in sur],
            "packages": [{"id": p.id, "title": p.title, "category": ph.category, "nights": ph.nights}
                         for ph, p in pk]}


def packages(s: Session, q: str | None = None, destination: str | None = None,
             on_date: date | None = None) -> list[dict]:
    """One card per package *family*: re-uploads of the same supplier package show as one entry.

    With a travel date: the newest version sold on that date. Without: the version valid today (or the next
    one to start); other live editions (e.g. a winter version) are listed on the card."""
    rows = s.scalars(select(db.Package).where(db.Package.status == "active").order_by(db.Package.title)).all()
    fams: dict[int, list[db.Package]] = defaultdict(list)
    for p in rows:
        fams[p.family_id or p.id].append(p)
    counts = dict(s.execute(select(db.Package.family_id, func.count(db.Package.id))
                            .group_by(db.Package.family_id)).all())
    out = []
    for fid, members in fams.items():
        p = history.pick_for_date(members, on_date) if on_date else history.primary_version(members)
        if p is None:
            continue
        hay = " ".join([p.title, p.region or "", *(p.destinations or [])]).lower()
        if q and q.lower() not in hay or destination and destination.lower() not in hay:
            continue
        prices = [x for x in p.prices if not on_date or x.valid_from <= on_date <= x.valid_to]
        twin = [x for x in prices if x.occupancy == "double"]
        cats = []
        for x in p.prices:
            if x.category and x.category not in cats:
                cats.append(x.category)
        prev = s.get(db.Package, p.previous_version_id) if p.previous_version_id else None
        out.append({"id": p.id, "title": p.title, "region": p.region, "destinations": p.destinations,
                    "nights": p.nights, "days": p.days, "supplier": p.supplier.name if p.supplier else None,
                    "valid_from": p.valid_from and p.valid_from.isoformat(),
                    "valid_to": p.valid_to and p.valid_to.isoformat(), "categories": cats,
                    "from_price": min((float(x.amount) for x in twin), default=None),
                    "currency": twin[0].currency if twin else None, "day_count": len(p.days_list),
                    "hotel_options": len(p.hotels), "family_id": fid, "version": p.version or 1,
                    "versions": counts.get(fid, 1), "edition": p.edition,
                    "state": history.rate_state(p.status, p.valid_from, p.valid_to),
                    "change_pct": compare_prices(prev.prices, p.prices)["avg_change_pct"] if prev else None,
                    "other_editions": [{"id": m.id, "title": m.title, "version": m.version or 1,
                                        "valid_from": m.valid_from and m.valid_from.isoformat(),
                                        "valid_to": m.valid_to and m.valid_to.isoformat()}
                                       for m in members if m.id != p.id]})
    return sorted(out, key=lambda x: x["title"].lower())


def package_full(s: Session, package_id: int) -> dict | None:
    p = s.get(db.Package, package_id)
    if not p:
        return None
    d = package_detail(p)
    d["region"] = p.region
    d["supplier"] = p.supplier.name if p.supplier else None
    # price grid: rows = group size / occupancy, columns = category
    cats, grid = [], defaultdict(dict)
    for x in sorted(p.prices, key=lambda x: (x.occupancy != "double", x.pax_min or 999, x.occupancy)):
        if x.category not in cats:
            cats.append(x.category)
        label = f"{x.pax_min} pax" if x.occupancy == "double" and x.pax_min else x.occupancy.replace("_", " ")
        if x.season_name:
            label += f" ({x.season_name})"
        grid[label][x.category] = _f(x.amount)
    d["price_grid"] = {"categories": cats, "rows": [{"label": k, "values": v} for k, v in grid.items()],
                       "currency": p.prices[0].currency if p.prices else None,
                       "basis": "per person" if all(x.basis == "per_person" for x in p.prices) else "mixed"}
    hotels_by = defaultdict(lambda: defaultdict(list))
    for h in p.hotels:
        hotels_by[f"{h.city or '?'}|{h.nights or ''}"][h.category or "-"].append({"name": h.hotel_name, "id": h.hotel_id})
    d["hotels_by_city"] = [{"city": k.split("|")[0], "nights": k.split("|")[1], "categories": dict(v)}
                           for k, v in hotels_by.items()]
    d["addons"] = [_service(r) for r in package_addons(s, p)]
    d.update({"status": p.status, "state": history.rate_state(p.status, p.valid_from, p.valid_to),
              "version": p.version or 1, "family_id": p.family_id or p.id, "edition": p.edition,
              "versions": len(history.family(s, p))})
    newer = history.newer_version(s, p)
    d["newer_version"] = {"id": newer.id, "version": newer.version, "title": newer.title} if newer else None
    return d


def package_addons(s: Session, p: db.Package) -> list[db.ServiceRate]:
    """Live add-ons read from any version of this package (an unchanged add-on is not stored again)."""
    docs = select(db.Package.source_document_id).where(db.Package.family_id == (p.family_id or p.id))
    return s.scalars(select(db.ServiceRate).where(db.ServiceRate.source_document_id.in_(docs),
                                                  db.ServiceRate.status == "active")
                     .order_by(db.ServiceRate.name)).all()


def _service(r: db.ServiceRate) -> dict:
    return {"state": history.rate_state(r.status, r.valid_from, r.valid_to), "change_pct": _f(r.change_pct),
            "previous_rate_id": r.previous_rate_id, "id": r.id, "kind": r.kind, "name": r.name, "destination": r.destination, "vehicle_type": r.vehicle_type,
            "basis": r.basis, "pax_min": r.pax_min, "pax_max": r.pax_max, "amount": _f(r.amount),
            "amount_max": _f(r.amount_max), "currency": r.currency, "optional": r.optional, "is_net": r.is_net,
            "valid_from": r.valid_from.isoformat(), "valid_to": r.valid_to.isoformat(), "notes": r.notes}


def services(s: Session, q: str | None = None, destination: str | None = None, kind: str | None = None,
             on_date: date | None = None) -> list[dict]:
    stmt = select(db.ServiceRate).where(db.ServiceRate.status == "active")
    if q:
        stmt = stmt.where(db.ServiceRate.name_key.like(f"%{name_key(q)}%"))
    if destination:
        # also match add-ons from packages in that region ("Kashmir" finds the Gulmarg gondola and Pahalgam cabs)
        region_docs = select(db.Package.source_document_id).where(or_(
            db.Package.region.ilike(f"%{destination}%"), db.Package.title.ilike(f"%{destination}%")))
        stmt = stmt.where(or_(db.ServiceRate.destination.ilike(f"%{destination}%"),
                              db.ServiceRate.name_key.like(f"%{name_key(destination)}%"),
                              db.ServiceRate.source_document_id.in_(region_docs)))
    if kind:
        stmt = stmt.where(db.ServiceRate.kind == kind)
    if on_date:
        stmt = stmt.where(db.ServiceRate.valid_from <= on_date, db.ServiceRate.valid_to >= on_date)
    return [_service(r) for r in s.scalars(stmt.order_by(db.ServiceRate.destination, db.ServiceRate.name)).all()]


def places(s: Session, q: str | None = None, destination: str | None = None) -> list[dict]:
    stmt = select(db.Place)
    if q:
        stmt = stmt.where(or_(db.Place.name.ilike(f"%{q}%"), db.Place.description.ilike(f"%{q}%")))
    if destination:
        stmt = stmt.where(or_(db.Place.destination.ilike(f"%{destination}%"), db.Place.region.ilike(f"%{destination}%")))
    return [{"id": p.id, "name": p.name, "destination": p.destination, "region": p.region, "kind": p.kind,
             "description": p.description, "availability": p.availability}
            for p in s.scalars(stmt.order_by(db.Place.destination, db.Place.name)).all()]


def suppliers(s: Session) -> list[dict]:
    out = []
    for sp in s.scalars(select(db.Supplier).order_by(db.Supplier.name)).all():
        c = lambda m, *w: s.scalar(select(func.count(m.id)).where(m.supplier_id == sp.id, *w))
        out.append({"id": sp.id, "name": sp.name, "type": sp.type, "city": sp.city, "country": sp.country,
                    "contact_person": sp.contact_person, "email": sp.email, "phone": sp.phone,
                    "address": sp.address, "website": sp.website, "gst_number": sp.gst_number,
                    "hotel_rates": c(db.HotelRate, db.HotelRate.status == "active"),
                    "packages": c(db.Package, db.Package.status == "active"),
                    "services": c(db.ServiceRate, db.ServiceRate.status == "active"),
                    "documents": c(db.SourceDocument)})
    return out


# ------------------------------------------------------------------ corrections to the live library
class EditError(ValueError):
    pass


_EDITABLE = {db.HotelRate: ("amount", "valid_from", "valid_to", "notes", "min_nights", "season_name"),
             db.ServiceRate: ("amount", "amount_max", "valid_from", "valid_to", "notes", "optional", "pax_max")}


def edit_rate(s: Session, model, rate_id: int, data: dict, by: str | None = None) -> dict:
    """Correct one live rate by hand. The change is written into the row's notes (who, when, what)."""
    from datetime import datetime as _dt
    from decimal import Decimal, InvalidOperation
    r = s.get(model, rate_id)
    if not r:
        raise EditError("Rate not found")
    if data.get("status") == "retired":
        r.status = "superseded"
        r.replaced_at = _dt.now()
        r.notes = ((r.notes + " | ") if r.notes else "") + f"Retired by {by or 'admin'} on {date.today():%d %b %Y}"
        s.commit()
        return {"id": r.id, "status": r.status}
    changed = []
    for f in _EDITABLE[model]:
        if f not in data:
            continue
        v = data[f]
        if f in ("amount", "amount_max"):
            try:
                v = None if v in (None, "") and f == "amount_max" else Decimal(str(v))
            except InvalidOperation:
                raise EditError(f"{f} must be a number")
            if f == "amount" and (v is None or v <= 0):
                raise EditError("Amount must be more than 0")
        elif f in ("valid_from", "valid_to"):
            v = date.fromisoformat(v) if isinstance(v, str) else v
        old = getattr(r, f)
        if f != "notes" and old != v:
            changed.append(f"{f} {old} -> {v}")
        setattr(r, f, v)
    if r.valid_from > r.valid_to:
        s.rollback()
        raise EditError("'Valid from' is after 'valid to'")
    if changed:
        r.notes = ((r.notes + " | ") if r.notes else "") + f"Edited by {by or 'admin'} on {date.today():%d %b %Y}: " + ", ".join(changed)
    s.commit()
    return {"id": r.id, "status": r.status, "amount": float(r.amount), "valid_from": r.valid_from.isoformat(),
            "valid_to": r.valid_to.isoformat(), "notes": r.notes}


# ------------------------------------------------------------------ suppliers
SUPPLIER_EDITABLE = ("name", "type", "city", "country", "contact_person", "email", "phone", "address", "website",
                     "gst_number")


def supplier_detail(s: Session, supplier_id: int) -> dict | None:
    sp = s.get(db.Supplier, supplier_id)
    if not sp:
        return None
    docs = s.scalars(select(db.SourceDocument).where(db.SourceDocument.supplier_id == sp.id)
                     .order_by(db.SourceDocument.id.desc())).all()
    hotel_ids = s.scalars(select(func.distinct(db.HotelRate.hotel_id)).where(db.HotelRate.supplier_id == sp.id)).all()
    hotels_ = s.scalars(select(db.Hotel).where(db.Hotel.id.in_(hotel_ids)).order_by(db.Hotel.name)).all() if hotel_ids else []
    pk = s.scalars(select(db.Package).where(db.Package.supplier_id == sp.id, db.Package.status == "active")
                   .order_by(db.Package.title)).all()
    svc = s.scalars(select(db.ServiceRate).where(db.ServiceRate.supplier_id == sp.id, db.ServiceRate.status == "active")
                    .order_by(db.ServiceRate.name)).all()
    last_valid = max([r for r in s.scalars(select(db.HotelRate.valid_to).where(
        db.HotelRate.supplier_id == sp.id, db.HotelRate.status == "active")).all()] +
        [x.valid_to for x in svc] + [p.valid_to for p in pk if p.valid_to], default=None)
    changes = []
    for d in docs:
        sm = (d.changes or {}).get("summary") if d.status == "approved" else None
        if sm:
            changes.append({"document_id": d.id, "filename": d.filename, "at": d.approved_at and d.approved_at.isoformat(timespec="minutes"),
                            **{k: sm.get(k) for k in ("new", "up", "down", "same", "avg_change_pct")}})
    return {**{f: getattr(sp, f) for f in SUPPLIER_EDITABLE}, "id": sp.id,
            "created_at": sp.created_at and sp.created_at.isoformat(timespec="minutes"),
            "rates_valid_until": last_valid and last_valid.isoformat(),
            "documents": [{"id": d.id, "filename": d.filename, "status": d.status, "document_type": d.document_type,
                           "created_at": d.created_at and d.created_at.isoformat(timespec="minutes")} for d in docs],
            "hotels": [{"id": h.id, "name": h.name, "city": h.city} for h in hotels_],
            "packages": [{"id": p.id, "title": p.title, "version": p.version or 1,
                          "valid_from": p.valid_from and p.valid_from.isoformat(),
                          "valid_to": p.valid_to and p.valid_to.isoformat()} for p in pk],
            "services": [_service(x) for x in svc], "price_updates": changes,
            "possible_duplicates": possible_duplicate_suppliers(s, sp)}


def possible_duplicate_suppliers(s: Session, sp: db.Supplier) -> list[dict]:
    """Other suppliers whose name or GSTIN / email / phone suggests they are the same company."""
    from rapidfuzz import fuzz
    out = []
    for o in s.scalars(select(db.Supplier).where(db.Supplier.id != sp.id)).all():
        why = []
        if fuzz.token_set_ratio(o.name_key, sp.name_key) >= 85:
            why.append("similar name")
        if sp.gst_number and o.gst_number and sp.gst_number.strip().upper() == o.gst_number.strip().upper():
            why.append("same GSTIN")
        emails = lambda x: {e.strip().lower() for e in (x.email or "").split(",") if e.strip()}
        if emails(sp) & emails(o):
            why.append("same email")
        digits = lambda x: {"".join(ch for ch in p if ch.isdigit())[-10:] for p in (x.phone or "").split(",") if len("".join(ch for ch in p if ch.isdigit())) >= 8}
        if digits(sp) & digits(o):
            why.append("same phone")
        if why:
            out.append({"id": o.id, "name": o.name, "why": why})
    return out


def update_supplier(s: Session, supplier_id: int, data: dict) -> dict:
    sp = s.get(db.Supplier, supplier_id)
    if not sp:
        raise EditError("Supplier not found")
    for f in SUPPLIER_EDITABLE:
        if f in data:
            v = (data[f] or "").strip() if isinstance(data[f], str) or data[f] is None else data[f]
            if f == "name" and not v:
                raise EditError("Name can't be empty")
            setattr(sp, f, v or None)
    sp.name_key = name_key(sp.name)
    s.commit()
    return supplier_detail(s, sp.id)


def merge_suppliers(s: Session, keep_id: int, merge_id: int) -> dict:
    """Two records for one company (e.g. 'Abdaal Travels' and 'Abdaal Tours & Travels'): everything of
    `merge_id` moves to `keep_id`, empty contact fields are filled in, and `merge_id` is removed."""
    if keep_id == merge_id:
        raise EditError("Pick two different suppliers")
    keep, other = s.get(db.Supplier, keep_id), s.get(db.Supplier, merge_id)
    if not keep or not other:
        raise EditError("Supplier not found")
    moved = {}
    for model in (db.SourceDocument, db.Hotel, db.HotelRate, db.Package, db.ServiceRate, db.Place):
        rows = s.scalars(select(model).where(model.supplier_id == other.id)).all()
        for r in rows:
            r.supplier_id = keep.id
        moved[model.__tablename__] = len(rows)
    for f in SUPPLIER_EDITABLE:
        if not getattr(keep, f) and getattr(other, f):
            setattr(keep, f, getattr(other, f))
    s.flush()
    s.delete(other)
    s.commit()
    return {"kept": keep.id, "moved": moved}
