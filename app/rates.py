"""Querying the live rates: search, stay pricing, and expiry alerts.

`price_hotel_stay` is the building block the package builder uses: it prices every night of a stay
with the rate that is valid *that* night (so a stay crossing from regular into peak season is priced
correctly), adds mandatory supplements (gala dinners), and refuses blackout dates or nights with no rate.
"""
from __future__ import annotations

from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from . import db
from .normalize import DAYS, name_key, norm_meal_plan


def _money(x) -> float:
    return float(Decimal(x).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def _active_on(model, d: date):
    return [model.status == "active", model.valid_from <= d, model.valid_to >= d]


# ------------------------------------------------------------------ search
def search_hotel_rates(s: Session, destination: str | None = None, hotel: str | None = None, on_date: date | None = None,
                       meal_plan: str | None = None, occupancy: str = "double", max_amount: float | None = None,
                       net_only: bool = False, limit: int = 200) -> list[dict]:
    """e.g. 'double room rates in Munnar on 20 Dec with breakfast under 6000'."""
    on_date = on_date or date.today()
    q = (select(db.HotelRate, db.Hotel, db.RoomType).join(db.Hotel, db.HotelRate.hotel_id == db.Hotel.id)
         .join(db.RoomType, db.HotelRate.room_type_id == db.RoomType.id)
         .where(*_active_on(db.HotelRate, on_date)))
    if destination:
        like = f"%{destination}%"
        q = q.where(or_(db.Hotel.city.ilike(like), db.Hotel.destination.ilike(like)))
    if hotel:
        q = q.where(db.Hotel.name_key.like(f"%{name_key(hotel)}%"))
    if meal_plan:
        q = q.where(db.HotelRate.meal_plan == (norm_meal_plan(meal_plan) or meal_plan.upper()))
    if occupancy:
        q = q.where(db.HotelRate.occupancy == occupancy)
    if max_amount is not None:
        q = q.where(db.HotelRate.amount <= max_amount)
    if net_only:
        q = q.where(db.HotelRate.is_net.is_(True))
    out = []
    dow = DAYS[on_date.weekday()]
    for r, h, rt in s.execute(q.order_by(db.HotelRate.amount).limit(limit)).all():
        if r.weekdays and dow not in r.weekdays.split(","):
            continue
        out.append({"rate_id": r.id, "hotel_id": h.id, "hotel": h.name, "city": h.city, "star_rating": h.star_rating,
                    "room_type": rt.name, "meal_plan": r.meal_plan, "occupancy": r.occupancy, "basis": r.basis,
                    "amount": _money(r.amount), "currency": r.currency, "is_net": r.is_net,
                    "taxes_included": r.taxes_included, "season": r.season_name, "weekdays": r.weekdays,
                    "valid_from": r.valid_from.isoformat(), "valid_to": r.valid_to.isoformat(),
                    "source_document_id": r.source_document_id})
    return out


def search_services(s: Session, destination: str | None = None, kind: str | None = None, text: str | None = None,
                    on_date: date | None = None) -> list[dict]:
    on_date = on_date or date.today()
    q = select(db.ServiceRate).where(*_active_on(db.ServiceRate, on_date))
    if destination:
        # DMCs often tag transfers with the region ("Kerala") while the route names the town ("... – Munnar")
        q = q.where(or_(db.ServiceRate.destination.ilike(f"%{destination}%"),
                        db.ServiceRate.name_key.like(f"%{name_key(destination)}%")))
    if kind:
        q = q.where(db.ServiceRate.kind == kind)
    if text:
        q = q.where(db.ServiceRate.name_key.like(f"%{name_key(text)}%"))
    return [{"id": r.id, "kind": r.kind, "name": r.name, "destination": r.destination, "vehicle_type": r.vehicle_type,
             "basis": r.basis, "pax_min": r.pax_min, "pax_max": r.pax_max, "amount": _money(r.amount),
             "currency": r.currency, "is_net": r.is_net, "valid_from": r.valid_from.isoformat(),
             "valid_to": r.valid_to.isoformat()} for r in s.scalars(q.order_by(db.ServiceRate.name)).all()]


def search_packages(s: Session, destination: str | None = None, on_date: date | None = None) -> list[dict]:
    on_date = on_date or date.today()
    from .history import pick_for_date   # (history imports the loader; keep this module import-light)
    pkgs = s.scalars(select(db.Package).where(db.Package.status == "active")).all()
    fams: dict[int, list] = {}
    for p in pkgs:
        fams.setdefault(p.family_id or p.id, []).append(p)
    pkgs = [x for x in (pick_for_date(m, on_date) for m in fams.values()) if x]   # newest edition on that date
    out = []
    for p in pkgs:
        if destination and not any(destination.lower() in d.lower() for d in (p.destinations or [])) \
                and destination.lower() not in p.title.lower():
            continue
        prices = [q for q in p.prices if q.valid_from <= on_date <= q.valid_to]
        if not prices:
            continue
        out.append(package_detail(p, prices))
    return out


def package_detail(p: db.Package, prices=None) -> dict:
    prices = p.prices if prices is None else prices
    return {"id": p.id, "title": p.title, "destinations": p.destinations, "nights": p.nights, "days": p.days,
            "valid_from": p.valid_from and p.valid_from.isoformat(), "valid_to": p.valid_to and p.valid_to.isoformat(),
            "itinerary": [{"day": d.day_number, "title": d.title, "description": d.description,
                           "overnight": d.overnight, "meals": d.meals} for d in p.days_list],
            "hotels": [{"city": h.city, "hotel": h.hotel_name, "hotel_id": h.hotel_id, "category": h.category,
                        "nights": h.nights, "room_type": h.room_type, "meal_plan": h.meal_plan} for h in p.hotels],
            "prices": [{"category": q.category, "pax_min": q.pax_min, "pax_max": q.pax_max, "occupancy": q.occupancy,
                        "basis": q.basis, "amount": _money(q.amount), "currency": q.currency, "is_net": q.is_net,
                        "season": q.season_name, "valid_from": q.valid_from.isoformat(),
                        "valid_to": q.valid_to.isoformat()} for q in prices],
            "inclusions": p.inclusions, "exclusions": p.exclusions, "terms": p.terms,
            "source_document_id": p.source_document_id}


def expiring_soon(s: Session, within_days: int = 30, today: date | None = None) -> list[dict]:
    """Suppliers whose rates run out soon -> time to ask them for a new rate sheet."""
    today = today or date.today()
    limit = today + timedelta(days=within_days)
    groups: dict[tuple, dict] = {}
    rows = s.execute(select(db.HotelRate, db.Hotel).join(db.Hotel).where(
        db.HotelRate.status == "active", db.HotelRate.valid_to >= today, db.HotelRate.valid_to <= limit)).all()
    for r, h in rows:
        g = groups.setdefault(("hotel", h.id), {"type": "hotel", "name": h.name, "last_valid_date": r.valid_to})
        g["last_valid_date"] = max(g["last_valid_date"], r.valid_to)
    # only report if there is no later rate for the same hotel
    out = []
    for (kind, hid), g in groups.items():
        later = s.scalar(select(db.HotelRate.id).where(db.HotelRate.hotel_id == hid, db.HotelRate.status == "active",
                                                       db.HotelRate.valid_to > limit).limit(1))
        if not later:
            out.append({**g, "last_valid_date": g["last_valid_date"].isoformat()})
    for r in s.scalars(select(db.ServiceRate).where(db.ServiceRate.status == "active", db.ServiceRate.valid_to >= today,
                                                     db.ServiceRate.valid_to <= limit)).all():
        out.append({"type": r.kind, "name": f"{r.name} ({r.vehicle_type or ''})",
                    "last_valid_date": r.valid_to.isoformat()})
    return sorted(out, key=lambda x: x["last_valid_date"])


# ------------------------------------------------------------------ stay pricing
def price_hotel_stay(s: Session, hotel_id: int, room_type: str, meal_plan: str, check_in: date, check_out: date,
                     rooms: list[dict] | None = None, prefer_net: bool = True, markup_pct: float = 0) -> dict:
    """rooms: [{"adults": 2, "children_with_bed": 0, "children_without_bed": 1}, ...]"""
    rooms = rooms or [{"adults": 2}]
    hotel = s.get(db.Hotel, hotel_id)
    if not hotel:
        raise ValueError(f"Hotel {hotel_id} not found")
    mp = norm_meal_plan(meal_plan) or meal_plan.upper()
    room_rows = s.scalars(select(db.RoomType).where(db.RoomType.hotel_id == hotel_id)).all()
    key = name_key(room_type)
    room = next((r for r in room_rows if r.name_key == key), None) or \
        next((r for r in room_rows if key in r.name_key or r.name_key in key), None)
    if not room:
        raise ValueError(f"Room type '{room_type}' not found. Available: {', '.join(r.name for r in room_rows)}")
    n_nights = (check_out - check_in).days
    if n_nights <= 0:
        raise ValueError("check_out must be after check_in")

    rates = s.scalars(select(db.HotelRate).where(
        db.HotelRate.room_type_id == room.id, db.HotelRate.meal_plan == mp, db.HotelRate.status == "active",
        db.HotelRate.valid_from <= check_out - timedelta(days=1), db.HotelRate.valid_to >= check_in)).all()
    surcharges = s.scalars(select(db.HotelSurcharge).where(
        db.HotelSurcharge.hotel_id == hotel_id, db.HotelSurcharge.status == "active",
        db.HotelSurcharge.date_from <= check_out - timedelta(days=1), db.HotelSurcharge.date_to >= check_in)).all()

    errors, warnings = [], []
    currencies, net_flags, tax_flags = set(), set(), set()

    def pick(occ, d):
        dow = DAYS[d.weekday()]
        c = [r for r in rates if r.occupancy == occ and r.valid_from <= d <= r.valid_to
             and (r.weekdays is None or dow in r.weekdays.split(","))]
        if not c:
            return None
        # day-specific beats general; preferred net/rack beats the other; then the newest sheet
        c.sort(key=lambda r: (r.weekdays is not None, (r.is_net is True) == prefer_net, r.source_document_id),
               reverse=True)
        return c[0]

    def use(r, label, qty=1):
        currencies.add(r.currency)
        net_flags.add(r.is_net)
        tax_flags.add(r.taxes_included)
        unit = Decimal(r.amount)
        return {"item": label, "unit": _money(unit), "qty": qty, "amount": _money(unit * qty),
                "season": r.season_name}

    nights = []
    total_adults = sum(r.get("adults", 0) for r in rooms)
    total_children = sum(r.get("children_with_bed", 0) + r.get("children_without_bed", 0) for r in rooms)
    for i in range(n_nights):
        d = check_in + timedelta(days=i)
        lines, missing = [], []
        for bo in (x for x in surcharges if x.kind == "blackout" and x.date_from <= d <= x.date_to):
            if bo.room_type and name_key(bo.room_type) not in room.name_key and room.name_key not in name_key(bo.room_type):
                continue
            errors.append(f"{d}: blackout / stop sale at {hotel.name}" + (f" ({bo.room_type})" if bo.room_type else ""))
        for ri, rm in enumerate(rooms, 1):
            a = rm.get("adults", 2)
            cwb, cnb = rm.get("children_with_bed", 0), rm.get("children_without_bed", 0)
            plan: list[tuple[str, int]] = []
            if a <= 1:
                if pick("single", d):
                    plan.append(("single", 1))
                else:
                    plan.append(("double", 1))
                    warnings.append(f"{d}: no single rate, used double rate for room {ri}")
            elif a == 2:
                plan.append(("double", 1))
            elif a == 3 and pick("triple", d):
                plan.append(("triple", 1))
            else:
                plan += [("double", 1), ("extra_adult", a - 2)]
                if a > 3:
                    warnings.append(f"Room {ri} has {a} adults - check the hotel allows it")
            if cwb:
                plan.append(("child_with_bed", cwb))
            if cnb:
                plan.append(("child_without_bed", cnb))
            for occ, qty in plan:
                r = pick(occ, d)
                if not r and occ == "double":
                    r = pick("per_person", d)
                    if r:
                        occ, qty = "per_person", a
                if not r and occ == "child_with_bed" and pick("extra_adult", d):
                    r = pick("extra_adult", d)
                    warnings.append(f"{d}: no child-with-bed rate, used extra adult rate")
                if not r:
                    missing.append(f"{occ.replace('_', ' ')} (room {ri})")
                    continue
                if r.basis == "per_person_per_night" and occ in ("double", "single", "triple"):
                    qty = {"single": 1, "double": 2, "triple": 3}[occ]
                lines.append(use(r, f"Room {ri}: {occ.replace('_', ' ')}", qty))
            if (r0 := pick("double", d) or pick("single", d)) and r0.min_nights and n_nights < r0.min_nights:
                warnings.append(f"{d}: minimum stay is {r0.min_nights} nights")
        if missing:
            errors.append(f"{d}: no valid rate for " + ", ".join(missing))
        nights.append({"date": d.isoformat(), "day": DAYS[d.weekday()], "lines": lines,
                       "total": _money(sum(Decimal(str(l["amount"])) for l in lines))})

    supp_lines = []
    for sc in (x for x in surcharges if x.kind == "supplement" and x.mandatory):
        if sc.amount is None:
            warnings.append(f"Supplement '{sc.name}' applies but has no amount - check with the hotel")
            continue
        nights_hit = sum(1 for i in range(n_nights) if sc.date_from <= check_in + timedelta(days=i) <= sc.date_to)
        if not nights_hit:
            continue
        qty = {"per_adult": total_adults, "per_person": total_adults + total_children, "per_child": total_children,
               "per_room": len(rooms), "per_room_per_night": len(rooms) * nights_hit,
               "per_booking": 1}.get(sc.basis or "", None)
        if qty is None:
            qty = total_adults
            warnings.append(f"Supplement '{sc.name}' basis not stated - charged per adult")
        if sc.currency:
            currencies.add(sc.currency)
        supp_lines.append({"item": sc.name, "unit": _money(sc.amount), "qty": qty,
                           "amount": _money(Decimal(sc.amount) * qty)})

    if len(currencies) > 1:
        errors.append(f"Rates are in different currencies: {', '.join(sorted(currencies))}")
    subtotal = sum(Decimal(str(n["total"])) for n in nights) + sum(Decimal(str(l["amount"])) for l in supp_lines)
    markup = subtotal * Decimal(str(markup_pct)) / 100
    return {
        "hotel": hotel.name, "hotel_id": hotel.id, "room_type": room.name, "meal_plan": mp,
        "check_in": check_in.isoformat(), "check_out": check_out.isoformat(), "nights_count": n_nights,
        "rooms": rooms, "nights": nights, "supplements": supp_lines,
        "cost": _money(subtotal), "markup_pct": markup_pct, "markup": _money(markup), "sell": _money(subtotal + markup),
        "currency": next(iter(currencies)) if len(currencies) == 1 else None,
        "rates_are_net": next(iter(net_flags)) if len(net_flags) == 1 else None,
        "taxes_included": next(iter(tax_flags)) if len(tax_flags) == 1 else None,
        "ok": not errors, "errors": errors, "warnings": sorted(set(warnings)),
    }
