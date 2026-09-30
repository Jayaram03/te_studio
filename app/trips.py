"""Trip builder: turn the rate library into a priced, day-wise trip for a customer.

A trip has
  - days   : the itinerary (copied from a supplier package, picked from the day library of ANY package,
             or written by hand) -- so itineraries from different packages can be combined;
  - items  : cost lines -- a package price (by hotel category and group size), hotel stays priced night by
             night, activities / transfers / tickets, or custom lines. Optional items are shown as add-ons.
Totals: cost -> markup -> GST -> selling price and price per person.

Hotel options: a line can carry an option label ("Option A", "Deluxe"). Lines without a label are in every
option; each option's price = shared lines + its own lines. The customer picks one (chosen_option); until
then the headline price is the cheapest option ("from").

Every priced item remembers the inputs it was priced with (details.inputs), so when the travellers or dates
change, `reprice_trip` prices everything again from the live rates.
"""
from __future__ import annotations

import math
import secrets
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from . import db, history
from .normalize import name_key
from .rates import price_hotel_stay


class TripError(ValueError):
    pass


def _q(x) -> Decimal:
    return Decimal(str(x)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _f(x) -> float | None:
    return None if x is None else float(_q(x))


# ------------------------------------------------------------------ package pricing
def package_categories(pkg: db.Package) -> list[str]:
    seen = []
    for p in pkg.prices:
        if p.category and p.category not in seen:
            seen.append(p.category)
    return seen


def price_package(pkg: db.Package, category: str | None, adults: int, extra_beds: int = 0,
                  children_with_bed: int = 0, children_without_bed: int = 0, single_rooms: int = 0,
                  travel_date: date | None = None, pax_tier: int | None = None) -> dict:
    """Price a supplier package for a group.

    adults            all adults (including those on an extra bed or in single rooms)
    extra_beds        adults sleeping on an extra bed (3rd adult in a room) -> extra bed rate
    single_rooms      adults in a room of their own -> twin rate + single supplement
    The per-person twin-sharing rate is chosen from the group-size tiers (2 pax, 4 pax ...) using the number
    of adults on twin sharing; `pax_tier` forces a tier.
    """
    errors, warnings, lines = [], [], []
    cats = package_categories(pkg)
    if category is None and cats:
        category = cats[0]
    if category not in cats:
        raise TripError(f"Category '{category}' not in this package. Available: {', '.join(cats) or 'none'}")
    prices = [p for p in pkg.prices if p.category == category]
    if travel_date:
        valid = [p for p in prices if p.valid_from <= travel_date <= p.valid_to]
        if not valid:
            ranges = sorted({(p.valid_from, p.valid_to) for p in prices})
            errors.append(f"Package prices are not valid on {travel_date}. Valid: " +
                          ", ".join(f"{a} to {b}" for a, b in ranges))
            valid = prices
        prices = valid

    def rate(occ):
        c = [p for p in prices if p.occupancy == occ]
        return c[0] if c else None

    twin = adults - extra_beds
    if twin < 1:
        raise TripError("At least one adult must be on twin sharing")
    tiers = sorted({p.pax_min for p in prices if p.occupancy == "double" and p.pax_min}, key=int)
    tier_rows = {p.pax_min: p for p in prices if p.occupancy == "double" and p.pax_min}
    if pax_tier:
        if pax_tier not in tier_rows:
            raise TripError(f"No {pax_tier} pax rate. Tiers: {', '.join(map(str, tiers))}")
        tier = pax_tier
    elif tiers:
        fitting = [t for t in tiers if t <= twin]
        tier = fitting[-1] if fitting else tiers[0]
        if tier != twin:
            warnings.append(f"No exact {twin} pax rate - used the {tier} pax rate")
    else:
        tier = None
    base = tier_rows.get(tier) if tier else rate("double")
    if not base:
        errors.append(f"No per-person twin sharing rate for {category}")
    else:
        lines.append({"item": f"{category} - {twin} adult(s) on twin sharing" + (f" ({tier} pax rate)" if tier else ""),
                      "unit": _f(base.amount), "qty": twin, "amount": _f(base.amount * twin)})
    if twin % 2 and not single_rooms:
        warnings.append(f"{twin} adults on twin sharing is an odd number - add an extra bed or a single room")

    def add(occ, qty, label, fallback=None):
        if not qty:
            return
        r = rate(occ) or (rate(fallback) if fallback else None)
        if not r:
            errors.append(f"No {label} rate for {category}")
            return
        lines.append({"item": f"{label} x {qty}", "unit": _f(r.amount), "qty": qty, "amount": _f(r.amount * qty)})

    add("extra_adult", extra_beds, "Extra bed (adult)")
    add("child_with_bed", children_with_bed, "Child with bed", fallback="extra_adult")
    add("child_without_bed", children_without_bed, "Child without bed")
    add("single_supplement", single_rooms, "Single supplement")
    currencies = {p.currency for p in prices}
    total = sum(Decimal(str(l["amount"])) for l in lines)
    return {"package_id": pkg.id, "package": pkg.title, "category": category, "pax_tier": tier,
            "lines": lines, "total": _f(total), "currency": currencies.pop() if len(currencies) == 1 else None,
            "is_net": prices[0].is_net if prices else None, "errors": errors, "warnings": warnings,
            "tiers": tiers, "categories": cats}


# ------------------------------------------------------------------ trips
TRIP_FIELDS = ("title", "customer_name", "customer_phone", "customer_email", "lead_source", "assigned_to",
               "follow_up_date", "destination", "start_date", "adults", "children_with_bed", "children_without_bed",
               "extra_beds", "category", "currency", "markup_pct", "gst_pct", "status", "lost_reason", "notes",
               "inclusions", "exclusions", "terms", "created_by", "share_prices", "is_template", "chosen_option")
DATE_FIELDS = ("start_date", "follow_up_date")
REQUIRED = ("title", "adults", "children_with_bed", "children_without_bed", "extra_beds", "currency", "markup_pct",
            "gst_pct", "status", "share_prices")


def create_trip(s: Session, data: dict) -> db.Trip:
    if data.get("template_id"):
        tpl = s.get(db.Trip, int(data["template_id"]))
        if not tpl or not tpl.is_template:
            raise TripError("Template not found")
        t = duplicate(s, tpl, data.get("title") or tpl.title)
        _apply(t, {k: v for k, v in data.items() if k not in ("title", "is_template")})
        t.is_template = False
        t.notes_log[-1].text = f"Started from the template '{tpl.title}'"
        s.commit()
        if t.start_date:
            reprice_trip(s, t)
        return t
    t = db.Trip(title=data.get("title") or "New trip")
    _apply(t, data)
    s.add(t)
    s.commit()
    return t


def _apply(t: db.Trip, data: dict):
    for f in TRIP_FIELDS:
        if f not in data:
            continue
        v = data[f]
        if f in DATE_FIELDS and isinstance(v, str):
            v = date.fromisoformat(v) if v else None
        if v is None and f in REQUIRED:
            continue
        if f == "status" and v not in db.TRIP_STATUSES:
            raise TripError(f"Status must be one of {', '.join(db.TRIP_STATUSES)}")
        setattr(t, f, v)


def update_trip(s: Session, t: db.Trip, data: dict, reprice: bool = True) -> db.Trip:
    pax_before = (t.adults, t.children_with_bed, t.children_without_bed, t.extra_beds, t.start_date, t.category)
    status_before = t.status
    _apply(t, data)
    if t.status != status_before:
        why = f" ({t.lost_reason})" if t.status == "lost" and t.lost_reason else ""
        t.notes_log.append(db.TripNote(author=data.get("by") or t.assigned_to,
                                       text=f"Status changed: {status_before} -> {t.status}{why}"))
    s.flush()
    if reprice and pax_before != (t.adults, t.children_with_bed, t.children_without_bed, t.extra_beds,
                                  t.start_date, t.category):
        reprice_trip(s, t)
    s.commit()
    return t


def _day_date(t: db.Trip, position: int | None) -> date | None:
    if not t.start_date or not position:
        return None
    return t.start_date + timedelta(days=position - 1)


def _renumber(t: db.Trip):
    for i, d in enumerate(sorted(t.days, key=lambda d: d.position), 1):
        d.position = i


def apply_package(s: Session, t: db.Trip, package_id: int, category: str | None = None,
                  replace_days: bool = True, include_price: bool = True, all_categories: bool = False) -> dict:
    """Start the trip from a supplier package: copy its days, terms and price it for the trip's group.
    all_categories: one priced line per hotel category, each as its own option (Standard / Deluxe / ...)."""
    pkg = s.get(db.Package, package_id)
    if not pkg:
        raise TripError("Package not found")
    if all_categories and include_price and pkg.prices:
        result = apply_package(s, t, package_id, package_categories(pkg)[0], replace_days, include_price=False)
        for cat in package_categories(pkg):
            add_package_price(s, t, package_id, cat, option_label=cat)
        return result
    if replace_days:
        t.days.clear()
        s.flush()
    start = max((d.position for d in t.days), default=0)
    for d in pkg.days_list:
        t.days.append(db.TripDay(position=start + d.day_number, title=d.title, description=d.description,
                                 overnight=d.overnight, meals=d.meals, source_package_id=pkg.id, source_day_id=d.id))
    _renumber(t)
    t.inclusions = list(dict.fromkeys((t.inclusions or []) + (pkg.inclusions or [])))
    t.exclusions = list(dict.fromkeys((t.exclusions or []) + (pkg.exclusions or [])))
    t.terms = list(dict.fromkeys((t.terms or []) + (pkg.terms or [])))
    if not t.destination:
        t.destination = pkg.region or ", ".join(pkg.destinations or [])
    result = {}
    if include_price and pkg.prices:
        category = category or t.category or package_categories(pkg)[0]
        t.category = category
        item = db.TripItem(trip_id=t.id, kind="package", ref_id=pkg.id, day_position=start + 1 if start else None,
                           description="", unit_amount=0, amount=0,
                           details={"inputs": {"package_id": pkg.id, "category": category}})
        t.items.append(item)
        s.flush()
        result = _price_item(s, t, item)
    s.commit()
    return result


def add_package_price(s: Session, t: db.Trip, package_id: int, category: str | None = None,
                      option_label: str | None = None, day_position: int | None = None) -> db.TripItem:
    pkg = s.get(db.Package, package_id)
    if not pkg:
        raise TripError("Package not found")
    item = db.TripItem(trip_id=t.id, kind="package", ref_id=pkg.id, day_position=day_position, description="",
                       unit_amount=0, amount=0, option_label=_label(option_label),
                       details={"inputs": {"package_id": pkg.id, "category": category}})
    t.items.append(item)
    s.flush()
    _price_item(s, t, item)
    s.commit()
    return item


def _label(v) -> str | None:
    v = (v or "").strip()
    return v[:60] or None


def library_days(s: Session, q: str | None = None, destination: str | None = None, limit: int = 100) -> list[dict]:
    """Every day of every active package -- the building blocks for combined itineraries."""
    stmt = (select(db.PackageDay, db.Package).join(db.Package, db.PackageDay.package_id == db.Package.id)
            .where(db.Package.status == "active"))
    if q:
        like = f"%{q}%"
        stmt = stmt.where(or_(db.PackageDay.title.ilike(like), db.PackageDay.description.ilike(like),
                              db.PackageDay.overnight.ilike(like)))
    rows = s.execute(stmt.order_by(db.Package.title, db.PackageDay.day_number).limit(500)).all()
    out = []
    for d, p in rows:
        if destination:
            hay = " ".join([p.region or "", *(p.destinations or []), d.title or "", d.overnight or ""]).lower()
            if destination.lower() not in hay:
                continue
        out.append({"id": d.id, "package_id": p.id, "package": p.title, "region": p.region, "day": d.day_number,
                    "title": d.title, "description": d.description, "overnight": d.overnight, "meals": d.meals})
        if len(out) >= limit:
            break
    return out


def add_library_days(s: Session, t: db.Trip, day_ids: list[int], after_position: int | None = None):
    days = [s.get(db.PackageDay, i) for i in day_ids]
    if any(d is None for d in days):
        raise TripError("Unknown day id")
    pos = after_position if after_position is not None else max((d.position for d in t.days), default=0)
    for d in t.days:
        if d.position > pos:
            d.position += len(days)
    for i, d in enumerate(days, 1):
        t.days.append(db.TripDay(position=pos + i, title=d.title, description=d.description, overnight=d.overnight,
                                 meals=d.meals, source_package_id=d.package_id, source_day_id=d.id))
    s.flush()
    _renumber(t)
    s.commit()


def set_days(s: Session, t: db.Trip, days: list[dict]):
    """Replace the itinerary with the edited list from the screen (order = position)."""
    t.days.clear()
    s.flush()
    for i, d in enumerate(days, 1):
        t.days.append(db.TripDay(position=i, title=d.get("title"), description=d.get("description"),
                                 overnight=d.get("overnight"), meals=d.get("meals"),
                                 source_package_id=d.get("source_package_id"), source_day_id=d.get("source_day_id")))
    s.commit()


# ------------------------------------------------------------------ cost items
def default_rooms(t: db.Trip) -> list[dict]:
    """Adults in twin rooms (a 3rd adult on an extra bed), children with the first room."""
    rooms, left = [], t.adults
    extra = t.extra_beds
    while left > 0:
        take = 3 if (extra and left >= 3) else min(2, left)
        if take == 3:
            extra -= 1
        rooms.append({"adults": take, "children_with_bed": 0, "children_without_bed": 0})
        left -= take
    if rooms:
        rooms[0]["children_with_bed"] = t.children_with_bed
        rooms[0]["children_without_bed"] = t.children_without_bed
    return rooms


def add_hotel(s: Session, t: db.Trip, hotel_id: int, room_type: str, meal_plan: str, nights: int,
              day_position: int = 1, check_in: date | None = None, rooms: list[dict] | None = None,
              option_label: str | None = None) -> db.TripItem:
    item = db.TripItem(trip_id=t.id, kind="hotel", ref_id=hotel_id, day_position=day_position, description="",
                       unit_amount=0, amount=0, option_label=_label(option_label),
                       details={"inputs": {"hotel_id": hotel_id, "room_type": room_type, "meal_plan": meal_plan,
                                           "nights": nights, "check_in": check_in.isoformat() if check_in else None,
                                           "rooms": rooms}})
    t.items.append(item)
    s.flush()
    _price_item(s, t, item)
    s.commit()
    return item


def service_quantity(svc: db.ServiceRate, t: db.Trip) -> tuple[float, str]:
    children = t.children_with_bed + t.children_without_bed
    pax = t.adults + children
    if svc.basis == "per_vehicle":
        seats = svc.pax_max or 0
        n = math.ceil(pax / seats) if seats else 1
        return n, (f"{n} vehicle(s) for {pax} travellers ({seats} seats each)" if seats else "1 vehicle")
    if svc.basis == "per_adult":
        return t.adults, f"{t.adults} adult(s)"
    if svc.basis == "per_child":
        return children, f"{children} child(ren)"
    if svc.basis in ("per_group", "unknown"):
        return 1, "1 (check basis)" if svc.basis == "unknown" else "1 group"
    return pax, f"{pax} traveller(s)"


def add_service(s: Session, t: db.Trip, service_id: int, day_position: int | None = None,
                quantity: float | None = None, optional: bool | None = None,
                option_label: str | None = None) -> db.TripItem:
    svc = s.get(db.ServiceRate, service_id)
    if not svc:
        raise TripError("Service not found")
    item = db.TripItem(trip_id=t.id, kind="service", ref_id=service_id, day_position=day_position, description="",
                       unit_amount=0, amount=0, optional=svc.optional if optional is None else optional,
                       option_label=_label(option_label),
                       details={"inputs": {"service_id": service_id, "quantity": quantity}})
    t.items.append(item)
    s.flush()
    _price_item(s, t, item)
    s.commit()
    return item


def add_custom(s: Session, t: db.Trip, description: str, unit_amount: float, quantity: float = 1,
               day_position: int | None = None, optional: bool = False, currency: str | None = None,
               option_label: str | None = None) -> db.TripItem:
    if not (description or "").strip():
        raise TripError("Describe the line")
    item = db.TripItem(trip_id=t.id, kind="custom", description=description, quantity=_q(quantity),
                       option_label=_label(option_label),
                       unit_amount=_q(unit_amount), amount=_q(Decimal(str(unit_amount)) * Decimal(str(quantity))),
                       day_position=day_position, optional=optional, currency=currency or t.currency,
                       details={"inputs": {}})
    t.items.append(item)
    s.commit()
    return item


def update_item(s: Session, t: db.Trip, item_id: int, data: dict) -> db.TripItem:
    item = next((i for i in t.items if i.id == item_id), None)
    if not item:
        raise TripError("Item not found")
    details = dict(item.details or {})
    inputs = dict(details.get("inputs") or {})
    if "optional" in data:
        item.optional = bool(data["optional"])
    if "description" in data and data["description"]:
        item.description = data["description"]
        details["manual_description"] = True
    if "day_position" in data:
        item.day_position = data["day_position"]
    if "option_label" in data:
        item.option_label = _label(data["option_label"])
    if "quantity" in data and data["quantity"] is not None:
        item.quantity = _q(data["quantity"])
        inputs["quantity"] = float(data["quantity"])
    if "unit_amount" in data and data["unit_amount"] is not None:
        item.unit_amount = _q(data["unit_amount"])
        details["manual_price"] = True                      # a negotiated price sticks when repricing
    for k in ("category", "pax_tier", "room_type", "meal_plan", "nights", "check_in"):
        if k in data:
            inputs[k] = data[k]
    details["inputs"] = inputs
    item.details = details
    if item.kind == "custom" or details.get("manual_price"):
        item.amount = _q(Decimal(item.unit_amount) * Decimal(item.quantity))
    else:
        _price_item(s, t, item)
    s.commit()
    return item


def delete_item(s: Session, t: db.Trip, item_id: int):
    item = next((i for i in t.items if i.id == item_id), None)
    if not item:
        raise TripError("Item not found")
    t.items.remove(item)
    s.commit()


def reprice_trip(s: Session, t: db.Trip):
    for item in t.items:
        if item.kind != "custom":
            _price_item(s, t, item)      # a manually negotiated unit price is kept; quantities still follow the group
    s.commit()


def _price_item(s: Session, t: db.Trip, item: db.TripItem) -> dict:
    details = dict(item.details or {})
    inp = dict(details.get("inputs") or {})
    result: dict = {}
    manual_unit = item.unit_amount
    if item.kind == "package":
        pkg = s.get(db.Package, inp["package_id"])
        result = price_package(pkg, inp.get("category") or t.category, t.adults, t.extra_beds, t.children_with_bed,
                               t.children_without_bed, travel_date=t.start_date, pax_tier=inp.get("pax_tier"))
        desc = f"{pkg.title} - {result['category']} ({t.adults} adult{'s' if t.adults != 1 else ''}"
        desc += (f", {t.children_with_bed + t.children_without_bed} child" if t.children_with_bed + t.children_without_bed else "") + ")"
        item.quantity, item.unit_amount, item.amount = 1, _q(result["total"]), _q(result["total"])
        item.currency = result["currency"] or t.currency
        details["breakdown"] = result["lines"]
        details["hotels"] = [{"city": h.city, "hotel": h.hotel_name, "hotel_id": h.hotel_id, "nights": h.nights,
                              "meal_plan": h.meal_plan} for h in pkg.hotels if h.category == result["category"]]
    elif item.kind == "hotel":
        check_in = date.fromisoformat(inp["check_in"]) if inp.get("check_in") else _day_date(t, item.day_position)
        if not check_in:
            raise TripError("Set the trip start date (or a check-in date) to price a hotel")
        nights = int(inp.get("nights") or 1)
        result = price_hotel_stay(s, inp["hotel_id"], inp["room_type"], inp["meal_plan"], check_in,
                                  check_in + timedelta(days=nights), rooms=inp.get("rooms") or default_rooms(t))
        desc = (f"{result['hotel']} - {result['room_type']}, {result['meal_plan']}, {nights} night"
                f"{'s' if nights != 1 else ''} from {check_in:%d %b %Y}, {len(result['rooms'])} room"
                f"{'s' if len(result['rooms']) != 1 else ''}")
        item.quantity, item.unit_amount, item.amount = 1, _q(result["cost"]), _q(result["cost"])
        item.currency = result["currency"] or t.currency
        details["breakdown"] = [{"item": f"{n['date']} ({n['day']})", "amount": n["total"]} for n in result["nights"]]
        details["breakdown"] += [{"item": x["item"], "amount": x["amount"]} for x in result["supplements"]]
    elif item.kind == "service":
        svc = s.get(db.ServiceRate, inp["service_id"])
        auto_qty, qty_note = service_quantity(svc, t)
        qty = inp.get("quantity") if inp.get("quantity") is not None else auto_qty
        unit = item.unit_amount if details.get("manual_price") else _q(svc.amount)
        desc = svc.name + (f" ({svc.vehicle_type})" if svc.vehicle_type else "")
        item.quantity, item.unit_amount = _q(qty), _q(unit)
        item.amount = _q(Decimal(item.unit_amount) * Decimal(item.quantity))
        item.currency = svc.currency
        warnings = []
        if svc.amount_max is not None and not details.get("manual_price"):
            warnings.append(f"Price range {float(svc.amount):,.0f}-{float(svc.amount_max):,.0f}: low end used, "
                            f"edit the unit price if needed")
        on = _day_date(t, item.day_position) or t.start_date
        if on and not (svc.valid_from <= on <= svc.valid_to):
            warnings.append(f"Rate valid {svc.valid_from} to {svc.valid_to}, not on {on}")
        result = {"errors": [], "warnings": warnings}
        details["quantity_note"] = qty_note if inp.get("quantity") is None else "set manually"
        details["notes"] = svc.notes
    else:
        return {}
    if details.get("manual_price") and item.kind in ("package", "hotel"):
        item.unit_amount = manual_unit
        item.amount = _q(Decimal(manual_unit) * Decimal(item.quantity))
    if not details.get("manual_description"):
        item.description = desc
    details["errors"] = result.get("errors", [])
    details["warnings"] = result.get("warnings", [])
    item.details = details
    return result


# ------------------------------------------------------------------ pipeline helpers
def add_note(s: Session, t: db.Trip, text: str, author: str | None = None, follow_up_date: str | None = None):
    if not (text or "").strip():
        raise TripError("Note is empty")
    t.notes_log.append(db.TripNote(author=author, text=text.strip()))
    if follow_up_date is not None:
        t.follow_up_date = date.fromisoformat(follow_up_date) if follow_up_date else None
    s.commit()


def add_payment(s: Session, t: db.Trip, amount: float, paid_on: str | None = None, mode: str | None = None,
                reference: str | None = None, note: str | None = None):
    if not amount or amount <= 0:
        raise TripError("Amount must be positive")
    t.payments.append(db.TripPayment(amount=_q(amount), paid_on=date.fromisoformat(paid_on) if paid_on else date.today(),
                                     mode=mode, reference=reference, note=note))
    t.notes_log.append(db.TripNote(text=f"Payment received: {t.currency} {amount:,.0f}" + (f" by {mode}" if mode else "")))
    s.commit()


def delete_payment(s: Session, t: db.Trip, payment_id: int):
    p = next((x for x in t.payments if x.id == payment_id), None)
    if not p:
        raise TripError("Payment not found")
    t.payments.remove(p)
    s.commit()


def share(s: Session, t: db.Trip, enable: bool = True, prices: bool | None = None) -> str | None:
    if enable and not t.share_token:
        t.share_token = secrets.token_urlsafe(18)
    if not enable:
        t.share_token = None
    if prices is not None:
        t.share_prices = prices
    s.commit()
    return t.share_token


def duplicate(s: Session, t: db.Trip, title: str | None = None) -> db.Trip:
    """Re-use a quote for a similar enquiry: same days and costs, fresh customer / status / payments."""
    n = db.Trip(title=title or f"Copy of {t.title}")
    for f in TRIP_FIELDS:
        if f not in ("title", "status", "lost_reason", "customer_name", "customer_phone", "customer_email",
                     "follow_up_date", "created_by"):
            setattr(n, f, getattr(t, f))
    n.status = "enquiry"
    n.days = [db.TripDay(position=d.position, title=d.title, description=d.description, overnight=d.overnight,
                         meals=d.meals, source_package_id=d.source_package_id, source_day_id=d.source_day_id)
              for d in t.days]
    n.items = [db.TripItem(kind=i.kind, ref_id=i.ref_id, day_position=i.day_position, description=i.description,
                           quantity=i.quantity, unit_amount=i.unit_amount, amount=i.amount, currency=i.currency,
                           optional=i.optional, option_label=i.option_label,
                           details=dict(i.details or {})) for i in t.items]
    n.notes_log = [db.TripNote(text=f"Created as a copy of trip #{t.id} ({t.title})")]
    n.is_template = False
    s.add(n)
    s.commit()
    return n


def option_labels(t: db.Trip) -> list[str]:
    return list(dict.fromkeys(i.option_label for i in t.items if i.option_label))


def _price_of(t: db.Trip, items) -> dict:
    cost = sum((Decimal(i.amount) for i in items), Decimal(0))
    markup = cost * Decimal(t.markup_pct or 0) / 100
    gst = (cost + markup) * Decimal(t.gst_pct or 0) / 100
    sell = cost + markup + gst
    travellers = t.adults + t.children_with_bed + t.children_without_bed
    return {"cost": cost, "markup": markup, "gst": gst, "sell": sell,
            "per_person": sell / travellers if travellers else None}


def totals(t: db.Trip) -> dict:
    included = [i for i in t.items if not i.optional]
    currencies = {i.currency for i in included}
    shared = [i for i in included if not i.option_label]
    options = []
    for label in option_labels(t):
        p = _price_of(t, shared + [i for i in included if i.option_label == label])
        options.append({"label": label, **{k: _f(v) for k, v in p.items()}})
    chosen = t.chosen_option if t.chosen_option in {o["label"] for o in options} else None
    head = chosen or (min(options, key=lambda o: o["sell"])["label"] if options else None)
    p = _price_of(t, shared + [i for i in included if head and i.option_label == head])
    paid = sum((Decimal(x.amount) for x in t.payments), Decimal(0))
    travellers = t.adults + t.children_with_bed + t.children_without_bed
    return {"cost": _f(p["cost"]), "markup": _f(p["markup"]), "gst": _f(p["gst"]), "sell": _f(p["sell"]),
            "profit": _f(p["markup"]), "per_person": _f(p["per_person"]) if p["per_person"] is not None else None,
            "travellers": travellers, "paid": _f(paid), "balance": _f(p["sell"] - paid),
            "options": options, "option": head, "chosen_option": chosen,
            "is_from_price": bool(options) and not chosen,
            "currency": next(iter(currencies)) if len(currencies) == 1 else t.currency, "_currencies": currencies}


# ------------------------------------------------------------------ newer package versions
def newer_versions(s: Session, t: db.Trip) -> list[dict]:
    """Packages this trip uses for which a newer supplier version has been uploaded."""
    used = {i.ref_id for i in t.items if i.kind == "package"} | {d.source_package_id for d in t.days if d.source_package_id}
    out = []
    for pid in sorted(x for x in used if x):
        p = s.get(db.Package, pid)
        if not p:
            continue
        n = history.newer_version(s, p, t.start_date)
        if n:
            out.append({"from_id": p.id, "from_version": p.version or 1, "to_id": n.id, "to_version": n.version or 1,
                        "title": n.title, "old_title": p.title})
    return out


def upgrade_package(s: Session, t: db.Trip, from_id: int, to_id: int) -> None:
    """Move the trip to a newer version of a package: its price lines and the days copied from it.
    Days you edited keep your text; untouched days take the new version's text."""
    old, new = s.get(db.Package, from_id), s.get(db.Package, to_id)
    if not old or not new or (new.family_id or new.id) != (old.family_id or old.id):
        raise TripError("Those are not versions of the same package")
    old_days = {d.id: d for d in old.days_list}
    new_days = {d.day_number: d for d in new.days_list}
    for d in t.days:
        if d.source_package_id != old.id:
            continue
        src = old_days.get(d.source_day_id)
        nd = new_days.get(src.day_number) if src else None
        d.source_package_id = new.id
        d.source_day_id = nd.id if nd else None
        if nd and src and (d.title, d.description) == (src.title, src.description):
            d.title, d.description, d.overnight, d.meals = nd.title, nd.description, nd.overnight, nd.meals
    cats = package_categories(new)
    for i in t.items:
        if i.kind == "package" and i.ref_id == old.id:
            inputs = dict((i.details or {}).get("inputs") or {})
            inputs["package_id"] = new.id
            if inputs.get("category") not in cats:
                inputs["category"] = cats[0] if cats else None
            i.ref_id = new.id
            i.details = {**(i.details or {}), "inputs": inputs}
            _price_item(s, t, i)
    t.notes_log.append(db.TripNote(text=f"Moved to version {new.version} of '{new.title}'"))
    s.commit()


def dashboard(s: Session, today: date | None = None) -> dict:
    today = today or date.today()
    month_start = today.replace(day=1)
    rows = s.scalars(select(db.Trip).where(db.Trip.is_template.is_(False)).order_by(db.Trip.id.desc())).all()
    pipeline = {st: {"count": 0, "value": 0.0} for st in db.TRIP_STATUSES}
    sources: dict[str, dict] = {}
    follow, upcoming, recent = [], [], []
    month = {"enquiries": 0, "quoted_value": 0.0, "confirmed": 0, "confirmed_value": 0.0, "profit": 0.0}
    balance_due = 0.0
    for t in rows:
        tt = totals(t)
        pipeline.setdefault(t.status, {"count": 0, "value": 0.0})
        pipeline[t.status]["count"] += 1
        pipeline[t.status]["value"] += tt["sell"] or 0
        src = sources.setdefault(t.lead_source or "Not set", {"trips": 0, "confirmed": 0, "value": 0.0})
        src["trips"] += 1
        if t.status in ("confirmed", "completed"):
            src["confirmed"] += 1
            src["value"] += tt["sell"] or 0
            balance_due += max(tt["balance"] or 0, 0)
        brief = {"id": t.id, "title": t.title, "customer_name": t.customer_name, "status": t.status,
                 "assigned_to": t.assigned_to, "start_date": t.start_date and t.start_date.isoformat(),
                 "follow_up_date": t.follow_up_date and t.follow_up_date.isoformat(), "sell": tt["sell"],
                 "balance": tt["balance"], "currency": tt["currency"], "customer_phone": t.customer_phone}
        if t.follow_up_date and t.follow_up_date <= today and t.status in ("enquiry", "quoted"):
            follow.append({**brief, "overdue_days": (today - t.follow_up_date).days})
        if t.start_date and today <= t.start_date <= today + timedelta(days=30) and t.status == "confirmed":
            upcoming.append(brief)
        created = t.created_at.date() if t.created_at else today
        if created >= month_start:
            month["enquiries"] += 1
            if t.status != "enquiry":
                month["quoted_value"] += tt["sell"] or 0
            if t.status in ("confirmed", "completed"):
                month["confirmed"] += 1
                month["confirmed_value"] += tt["sell"] or 0
                month["profit"] += tt["profit"] or 0
        if len(recent) < 8:
            recent.append(brief)
    decided = pipeline["confirmed"]["count"] + pipeline["completed"]["count"] + pipeline["lost"]["count"]
    won = pipeline["confirmed"]["count"] + pipeline["completed"]["count"]
    return {"pipeline": pipeline, "month": month, "follow_ups": sorted(follow, key=lambda x: x["follow_up_date"]),
            "upcoming_departures": sorted(upcoming, key=lambda x: x["start_date"]), "recent": recent,
            "lead_sources": [{"source": k, **v} for k, v in sorted(sources.items(), key=lambda kv: -kv[1]["trips"])],
            "conversion_pct": round(100 * won / decided, 1) if decided else None, "balance_due": round(balance_due, 2)}


# ------------------------------------------------------------------ views
def trip_view(s: Session, t: db.Trip) -> dict:
    tt = totals(t)
    currencies = tt.pop("_currencies")
    problems = [e for i in t.items for e in (i.details or {}).get("errors", [])]
    if len(currencies) > 1:
        problems.append(f"Items are in different currencies ({', '.join(sorted(currencies))}) - convert before quoting")
    newer = newer_versions(s, t)
    for n in newer:
        problems.append(f"A newer version (v{n['to_version']}) of '{n['title']}' has been uploaded - "
                        f"this trip still uses v{n['from_version']}. Use the latest version to reprice.")
    priced = {i.ref_id for i in t.items if i.kind == "package"}
    for pid in {d.source_package_id for d in t.days if d.source_package_id} - priced:
        pkg = s.get(db.Package, pid)
        n = sum(1 for d in t.days if d.source_package_id == pid)
        problems.append(f"{n} day(s) come from '{pkg.title if pkg else pid}' but nothing in the costing covers them - "
                        f"add hotel stays, transfers or activities for those days")
    return {
        "id": t.id, "title": t.title, "customer_name": t.customer_name, "customer_phone": t.customer_phone,
        "customer_email": t.customer_email, "lead_source": t.lead_source, "assigned_to": t.assigned_to,
        "follow_up_date": t.follow_up_date and t.follow_up_date.isoformat(), "lost_reason": t.lost_reason,
        "share_token": t.share_token, "share_prices": t.share_prices,
        "created_at": t.created_at and t.created_at.isoformat(),
        "destination": t.destination, "start_date": t.start_date and t.start_date.isoformat(),
        "end_date": (t.start_date + timedelta(days=max(len(t.days) - 1, 0))).isoformat() if t.start_date else None,
        "adults": t.adults, "children_with_bed": t.children_with_bed, "children_without_bed": t.children_without_bed,
        "extra_beds": t.extra_beds, "category": t.category, "currency": t.currency, "status": t.status,
        "is_template": bool(t.is_template), "chosen_option": t.chosen_option, "newer_versions": newer,
        "markup_pct": float(t.markup_pct or 0), "gst_pct": float(t.gst_pct or 0), "notes": t.notes,
        "inclusions": t.inclusions or [], "exclusions": t.exclusions or [], "terms": t.terms or [],
        "days": [{"id": d.id, "position": d.position, "date": (_day_date(t, d.position) or "") and
                  _day_date(t, d.position).isoformat(), "title": d.title, "description": d.description,
                  "overnight": d.overnight, "meals": d.meals, "source_package_id": d.source_package_id,
                  "source_day_id": d.source_day_id} for d in sorted(t.days, key=lambda d: d.position)],
        "items": [{"id": i.id, "kind": i.kind, "ref_id": i.ref_id, "day_position": i.day_position,
                   "description": i.description, "quantity": float(i.quantity), "unit_amount": float(i.unit_amount),
                   "amount": float(i.amount), "currency": i.currency, "optional": i.optional,
                   "option_label": i.option_label, "details": i.details or {}} for i in t.items],
        "totals": tt,
        "notes_log": [{"id": n.id, "author": n.author, "text": n.text, "at": n.created_at and n.created_at.isoformat()}
                      for n in reversed(t.notes_log)],
        "payments": [{"id": p.id, "paid_on": p.paid_on.isoformat(), "amount": float(p.amount), "mode": p.mode,
                      "reference": p.reference, "note": p.note} for p in t.payments],
        "problems": problems,
        "suggested_addons": suggested_addons(s, t),
    }


def suggested_addons(s: Session, t: db.Trip) -> list[dict]:
    """Optional activities from the suppliers whose packages are in this trip, not yet added."""
    pkg_ids = {d.source_package_id for d in t.days if d.source_package_id}
    if not pkg_ids:
        return []
    fams = {p.family_id or p.id for p in s.scalars(select(db.Package).where(db.Package.id.in_(pkg_ids))).all()}
    docs = select(db.Package.source_document_id).where(db.Package.family_id.in_(fams))
    used = {i.ref_id for i in t.items if i.kind == "service"}
    rows = s.scalars(select(db.ServiceRate).where(db.ServiceRate.source_document_id.in_(docs),
                                                  db.ServiceRate.status == "active")).all()
    return [{"id": r.id, "kind": r.kind, "name": r.name, "destination": r.destination, "basis": r.basis,
             "amount": float(r.amount), "amount_max": _f(r.amount_max), "currency": r.currency,
             "pax_max": r.pax_max, "notes": r.notes} for r in rows if r.id not in used]


def options_display(v: dict) -> list[dict]:
    """Hotel options for quotes, PDFs and client pages: each option's price and what it contains."""
    T = v["totals"]
    out = []
    for o in T.get("options") or []:
        lines = []
        for i in v["items"]:
            if i.get("option_label") != o["label"] or i["optional"]:
                continue
            if i["kind"] == "package" and i["details"].get("hotels"):
                by: dict[str, list[str]] = {}
                for h in i["details"]["hotels"]:
                    by.setdefault(h["city"] or "", []).append(h["hotel"])
                lines += [f"{city}: {', '.join(names[:3])}{' or similar' if len(names) else ''}".strip(": ")
                          for city, names in by.items()]
            else:
                lines.append(i["description"])
        out.append({**o, "lines": lines, "chosen": o["label"] == T.get("chosen_option")})
    return out


def shown_items(v: dict) -> list[dict]:
    """Items to list as the trip's accommodation / inclusions: shared lines + the chosen option's lines
    (when there are options and none is chosen yet, the options table shows the option lines instead)."""
    chosen = v["totals"].get("chosen_option")
    return [i for i in v["items"] if not i.get("option_label") or i.get("option_label") == chosen]


def itinerary_text(s: Session, t: db.Trip, include_prices: bool = True) -> str:
    """Plain text version for WhatsApp / email."""
    return itinerary_text_from_view(trip_view(s, t), include_prices)


def itinerary_text_from_view(v: dict, include_prices: bool = True) -> str:
    cur = v["totals"]["currency"]
    lines = [f"*{v['title']}*"]
    if v.get("customer_name"):
        lines.append(f"For: {v['customer_name']}")
    pax = f"{v['adults']} adult{'s' if v['adults'] != 1 else ''}"
    kids = v["children_with_bed"] + v["children_without_bed"]
    if kids:
        pax += f", {kids} child{'ren' if kids != 1 else ''}"
    when = f"{_fmt_date(v['start_date'])} - {_fmt_date(v['end_date'])}" if v["start_date"] else ""
    lines.append(" | ".join(x for x in [v.get("destination"), when, pax, v.get("category")] if x))
    lines.append("")
    for d in v["days"]:
        head = f"*Day {d['position']}" + (f" ({_fmt_date(d['date'])})" if d["date"] else "") + f": {d['title'] or ''}*"
        lines += [head, d["description"] or ""]
        if d["overnight"]:
            lines.append(f"Overnight: {d['overnight']}")
        lines.append("")
    pkg_hotels = [h for i in shown_items(v) if i["kind"] == "package" for h in i["details"].get("hotels", [])]
    stays = [i for i in shown_items(v) if i["kind"] == "hotel"]
    if pkg_hotels or stays:
        lines.append("*Hotels*")
        by_city: dict[str, list[str]] = {}
        for h in pkg_hotels:
            by_city.setdefault(f"{h['city']} ({h['nights']}N)", []).append(h["hotel"])
        for city, names in by_city.items():
            lines.append(f"{city}: {', '.join(names[:4])}{' or similar' if names else ''}")
        for i in stays:
            lines.append(i["description"])
        lines.append("")
    if v.get("inclusions"):
        lines += ["*Inclusions*"] + [f"- {x}" for x in v["inclusions"]] + [""]
    if v.get("exclusions"):
        lines += ["*Exclusions*"] + [f"- {x}" for x in v["exclusions"]] + [""]
    opts = options_display(v)
    if opts and not v["totals"].get("chosen_option"):
        lines.append("*Hotel options*")
        for o in opts:
            lines.append(f"{o['label']}: {cur} {o['sell']:,.0f}" +
                         (f" ({cur} {o['per_person']:,.0f} per person)" if include_prices and o["per_person"] else "")
                         if include_prices else o["label"])
            lines += [f"  - {x}" for x in o["lines"]]
        lines.append("")
    if include_prices and not (opts and not v["totals"].get("chosen_option")):
        tot = v["totals"]
        lines.append(f"*Package cost: {cur} {tot['sell']:,.0f}*" +
                     (f" ({cur} {tot['per_person']:,.0f} per person)" if tot["per_person"] else ""))
        opts = [i for i in v["items"] if i["optional"]]
        if opts:
            lines.append("Optional: " + "; ".join(f"{i['description']} {i['currency']} {i['amount']:,.0f}" for i in opts))
    return "\n".join(lines).strip()


def _fmt_date(iso: str | None) -> str:
    return date.fromisoformat(iso).strftime("%d %b %Y") if iso else ""
