"""Stage 4: load an approved document into the live tables -- and handle re-uploads without duplicates.

When a supplier sends a new or revised sheet, every rate in it is compared with what the library holds
for the *same thing* (same hotel + room + meal plan + occupancy + days, or same service + vehicle + basis):

  same price, dates already covered   -> nothing is written (counted as "unchanged")
  same price, new dates               -> "extended": new row, older row trimmed
  different price, overlapping dates  -> "up" / "down": older row trimmed or superseded, new row links to it
  no overlap, but an earlier season
  (same season name, or the same dates
  a year before)                      -> "new season", compared with that earlier price
  nothing comparable                  -> "new"

Older rows are never deleted: a superseded row keeps its dates and amount, and the new row points to it
(previous_rate_id, change_pct). That chain is the rate history shown in the catalog.

Packages are matched to earlier uploads of the same supplier package (same supplier, same nights, similar
name once season / year words are removed, similar places) and become the next *version* of that family.
Only versions whose validity the new one fully covers are superseded; an off-season and a peak-season
edition can both stay live. The reviewer can override the match before approving.

`preview_changes` runs the same code inside a transaction that is rolled back, so what the review screen
shows is exactly what approving will do.
"""
from __future__ import annotations

import re
from collections import Counter
from datetime import date, datetime, timedelta
from decimal import Decimal

from rapidfuzz import fuzz
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import db
from .normalize import name_key

MATCH_THRESHOLD = 88           # hotels, room types, suppliers
SERVICE_MATCH_THRESHOLD = 92   # service names within the same supplier / kind / vehicle / basis
PACKAGE_MATCH_THRESHOLD = 86   # package names once season and year words are removed
SUPPLIER_FIELDS = ("type", "city", "country", "contact_person", "email", "phone", "address", "website", "gst_number")
HOTEL_FIELDS = ("city", "destination", "category", "property_type", "star_rating", "address", "child_policy")


# ------------------------------------------------------------------ fuzzy matching
def _score(a: str, b: str) -> float:
    s = fuzz.token_sort_ratio(a, b)
    # "Misty Hills Resort & Spa" vs "Misty Hills": subset matches only count when both names have 2+ words,
    # so "Royal" doesn't swallow "Royal Batoo" and "Bombay" doesn't swallow "Bombay Palace"
    if min(len(a.split()), len(b.split())) >= 2:
        s = max(s, fuzz.token_set_ratio(a, b) - 5)
    return s


def _best(candidates, key: str, attr="name_key", threshold=MATCH_THRESHOLD):
    best, score = None, 0
    for c in candidates:
        sc = _score(key, getattr(c, attr))
        if sc > score:
            best, score = c, sc
    return best if score >= threshold else None


def find_supplier(s: Session, name: str | None) -> db.Supplier | None:
    return _best(s.scalars(select(db.Supplier)).all(), name_key(name)) if name else None


def get_or_create_supplier(s: Session, sup: dict, hint: str | None) -> db.Supplier | None:
    name = sup.get("name") or hint
    if not name:
        return None
    found = find_supplier(s, name)
    if found:
        for f in SUPPLIER_FIELDS:
            if sup.get(f) and not getattr(found, f):
                setattr(found, f, sup[f])
        return found
    obj = db.Supplier(name=name, name_key=name_key(name), **{f: sup.get(f) for f in SUPPLIER_FIELDS})
    s.add(obj)
    s.flush()
    return obj


def get_or_create_hotel(s: Session, h: dict, supplier: db.Supplier | None) -> db.Hotel:
    q = select(db.Hotel)
    if h.get("city"):
        # hotels are matched within the same city (or with no city recorded)
        q = q.where((db.Hotel.city.is_(None)) | (db.Hotel.city.ilike(h["city"])))
    found = _best(s.scalars(q).all(), h["name_key"])
    if found:
        for f in HOTEL_FIELDS:
            if h.get(f) and not getattr(found, f):
                setattr(found, f, h[f])
        return found
    obj = db.Hotel(name=h["name"], name_key=h["name_key"], supplier_id=supplier.id if supplier else None,
                   notes=h.get("notes"), **{f: h.get(f) for f in HOTEL_FIELDS})
    s.add(obj)
    s.flush()
    return obj


def get_or_create_room(s: Session, hotel: db.Hotel, name: str, key: str) -> db.RoomType:
    rooms = s.scalars(select(db.RoomType).where(db.RoomType.hotel_id == hotel.id)).all()
    found = _best(rooms, key)
    if found:
        return found
    obj = db.RoomType(hotel_id=hotel.id, name=name, name_key=key)
    s.add(obj)
    s.flush()
    return obj


# ------------------------------------------------------------------ package identity
_EDITION_WORDS = {
    "off", "on", "season", "seasonal", "peak", "lean", "high", "low", "shoulder", "summer", "winter", "spring",
    "autumn", "monsoon", "festive", "festival", "diwali", "christmas", "xmas", "newyear", "holi", "puja", "pooja",
    "special", "offer", "offers", "deal", "deals", "promo", "promotional", "early", "bird", "revised", "revision",
    "updated", "update", "new", "latest", "final", "rates", "rate", "tariff", "tariffs", "price", "prices",
    "pricing", "package", "packages", "pkg", "tour", "tours", "holiday", "holidays", "trip", "b2b", "net", "rack",
    "edition", "version", "ver", "sheet", "card", "cost", "costing", "quote", "quotation", "valid", "validity",
    "from", "till", "to", "and", "the", "of", "for", "with", "nights", "night", "days", "day",
    "jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "sept", "oct", "nov", "dec", "january",
    "february", "march", "april", "june", "july", "august", "september", "october", "november", "december",
}


def core_title(title: str | None, base_name: str | None = None) -> str:
    """What stays the same between editions of one package: 'Kashmir Off Season 5N/6D (Revised 2026)' and
    'Kashmir Summer Special 2027 5N 6D' both become 'kashmir'. The AI's base_name is used when given."""
    k = name_key(base_name or title)
    k = re.sub(r"\b(19|20)\d{2}(\s*\d{2,4})?\b", " ", k)                   # years, 2026 27
    k = re.sub(r"\b\d+\s*n\s*\d+\s*d\b|\b\d+\s*[nd]\b|\bv\d+\b|\b\d+(st|nd|rd|th)?\b", " ", k)
    words = [w for w in k.split() if w not in _EDITION_WORDS]
    return " ".join(words) or name_key(title)


def _place_overlap(a: list | None, b: list | None) -> float | None:
    A, B = {name_key(x) for x in a or [] if x}, {name_key(x) for x in b or [] if x}
    if not A or not B:
        return None
    return len(A & B) / len(A | B)


def package_matches(s: Session, p: dict, supplier_id: int | None) -> list[dict]:
    """Earlier packages that look like the same supplier package, best first (one entry per family)."""
    new_core = core_title(p["title"], p.get("base_name"))
    rows = s.scalars(select(db.Package).where(db.Package.supplier_id == supplier_id) if supplier_id is not None
                     else select(db.Package).where(db.Package.supplier_id.is_(None))).all()
    fams: dict[int, dict] = {}
    for c in rows:
        if p.get("nights") and c.nights and p["nights"] != c.nights:
            continue
        score = fuzz.token_sort_ratio(new_core, core_title(c.title, c.base_name))
        places = _place_overlap(p.get("destinations"), c.destinations)
        if places is not None and places < 0.5:
            score -= 20
        fam = c.family_id or c.id
        cur = fams.get(fam)
        latest = cur["latest"] if cur else None
        if latest is None or (c.version or 1) > (latest.version or 1):
            latest = c
        fams[fam] = {"family_id": fam, "score": max(score, cur["score"] if cur else 0), "latest": latest}
    out = sorted(fams.values(), key=lambda f: -f["score"])
    return [{"family_id": f["family_id"], "score": round(f["score"]), "title": f["latest"].title,
             "version": f["latest"].version or 1, "latest": f["latest"]} for f in out]


# ------------------------------------------------------------------ change log
class ChangeLog:
    """Collects what a document does to the library: per rate, per package, and totals."""

    def __init__(self):
        self.counts: Counter = Counter()
        self.items: list[dict] = []
        self.packages: list[dict] = []
        self.restore: list[dict] = []          # earlier rows as they were before this document changed them
        self.clones: list = []                 # rows this document split off from earlier rows

    def remember(self, row) -> None:
        """Keep an earlier row's dates and status so approving can be undone exactly."""
        st = {"t": row.__tablename__, "id": row.id, "status": row.status}
        for a in ("valid_from", "valid_to"):
            if hasattr(row, a) and getattr(row, a) is not None:
                st[a] = getattr(row, a).isoformat()
        if not any(r["t"] == st["t"] and r["id"] == st["id"] for r in self.restore):
            self.restore.append(st)

    def undo_info(self) -> dict:
        return {"restore": self.restore, "clones": [{"t": c.__tablename__, "id": c.id} for c in self.clones]}

    def rate(self, what: str, name: str, kind: str, new=None, old=None, currency=None, valid=None,
             old_valid=None, vs=None):
        self.counts[kind] += 1
        self.items.append({"what": what, "name": name, "change": kind, "new": _num(new), "old": _num(old),
                           "pct": _pct(old, new) if old is not None and new is not None else None,
                           "currency": currency, "valid": valid, "old_valid": old_valid, "vs": vs})

    def as_dict(self) -> dict:
        order = {"up": 0, "down": 1, "new_season": 2, "extended": 3, "new": 4, "same": 5}
        items = sorted(self.items, key=lambda i: (order.get(i["change"], 9), -abs(i["pct"] or 0)))
        moved = [i["pct"] for i in self.items if i["change"] in ("up", "down", "new_season") and i["pct"] is not None]
        return {"summary": {**{k: self.counts.get(k, 0) for k in
                               ("new", "up", "down", "same", "extended", "new_season", "replaced")},
                            "avg_change_pct": round(sum(moved) / len(moved), 1) if moved else None},
                "items": items, "packages": self.packages}


def _num(x):
    return None if x is None else float(x)


def _pct(old, new) -> float | None:
    old, new = _num(old), _num(new)
    if not old:
        return None
    return round((new - old) / old * 100, 1)


def _span(a: date, b: date) -> str:
    return f"{a.isoformat()} – {b.isoformat()}"


# ------------------------------------------------------------------ dated rates
def _overlap_days(a1: date, a2: date, b1: date, b2: date) -> int:
    return max(0, (min(a2, b2) - max(a1, b1)).days + 1)


def _year_later(d: date) -> date:
    try:
        return d.replace(year=d.year + 1)
    except ValueError:                        # 29 Feb
        return d + timedelta(days=365)


def _previous(rows: list, vf: date, vt: date, season: str | None):
    """The earlier rate a new one should be compared with: the one it overlaps most (live rows first), else the
    latest one with the same season name, else the one covering the same dates a year earlier."""
    over = [r for r in rows if _overlap_days(r.valid_from, r.valid_to, vf, vt)]
    if over:
        return max(over, key=lambda r: (r.status == "active", _overlap_days(r.valid_from, r.valid_to, vf, vt), r.id)), "same dates"
    earlier = [r for r in rows if r.valid_to < vf]
    if season:
        same = [r for r in earlier if r.season_name and name_key(r.season_name) == name_key(season)]
        if same:
            return max(same, key=lambda r: (r.valid_to, r.id)), "earlier season"
    shifted = [(r, _overlap_days(_year_later(r.valid_from), _year_later(r.valid_to), vf, vt)) for r in earlier]
    shifted = [x for x in shifted if x[1] > 0]
    if shifted:
        return max(shifted, key=lambda x: (x[1], x[0].id))[0], "a year earlier"
    return None, None


def _trim_overlaps(s: Session, older: list, new_from: date, new_to: date, doc_id: int,
                   log: ChangeLog | None = None) -> int:
    """Make older active rows stop overlapping [new_from, new_to]. Returns rows touched."""
    touched = 0
    for o in older:
        if o.status != "active" or o.valid_to < new_from or o.valid_from > new_to:
            continue
        touched += 1
        if log is not None:
            log.remember(o)
        before = o.valid_from < new_from
        after = o.valid_to > new_to
        if before and after:                      # old range surrounds the new one -> split in two
            tail = _clone(o)
            tail.valid_from = new_to + timedelta(days=1)
            s.add(tail)
            if log is not None:
                log.clones.append(tail)
            o.valid_to = new_from - timedelta(days=1)
        elif before:
            o.valid_to = new_from - timedelta(days=1)
        elif after:
            o.valid_from = new_to + timedelta(days=1)
        else:
            o.status = "superseded"
            o.replaced_by_document_id = doc_id
            o.replaced_at = datetime.now()
    return touched


def _clone(o):
    cls = type(o)
    cols = {c.name: getattr(o, c.name) for c in cls.__table__.columns if c.name not in ("id", "created_at")}
    return cls(**cols)


def _d(v):
    return date.fromisoformat(v) if isinstance(v, str) else v


def _dated_rate(s: Session, log: ChangeLog, stats: Counter, doc: db.SourceDocument, what: str, label: str,
                same_key: list, new_row, same_price) -> None:
    """Shared logic for hotel and service rates. `same_key` = earlier rows of the same thing (any status),
    `same_price(old)` says whether an old row has the same price terms as `new_row`."""
    vf, vt = new_row.valid_from, new_row.valid_to
    live_over = [r for r in same_key if r.status == "active" and _overlap_days(r.valid_from, r.valid_to, vf, vt)]
    covering = next((o for o in live_over if same_price(o) and o.valid_from <= vf and o.valid_to >= vt), None)
    if covering:
        log.rate(what, label, "same", new_row.amount, covering.amount, new_row.currency, _span(vf, vt),
                 _span(covering.valid_from, covering.valid_to))
        stats["unchanged"] += 1
        return
    prev, vs = _previous(same_key, vf, vt, new_row.season_name)
    touched = _trim_overlaps(s, live_over, vf, vt, doc.id, log)
    stats["older_rates_adjusted"] += touched
    log.counts["replaced"] += touched
    if prev is not None:
        new_row.previous_rate_id = prev.id
        pct = _pct(prev.amount, new_row.amount)
        new_row.change_pct = Decimal(str(pct)) if pct is not None else None
        if vs == "same dates":
            kind = "extended" if same_price(prev) else ("up" if new_row.amount > prev.amount else "down")
        else:
            kind = "new_season"
        log.rate(what, label, kind, new_row.amount, prev.amount, new_row.currency, _span(vf, vt),
                 _span(prev.valid_from, prev.valid_to), vs)
    else:
        log.rate(what, label, "new", new_row.amount, None, new_row.currency, _span(vf, vt))
    s.add(new_row)


# ------------------------------------------------------------------ packages
def _covers(new_from, new_to, old: db.Package) -> bool:
    if not (new_from and new_to and old.valid_from and old.valid_to):
        return True                           # validity unknown on either side: the newer upload wins
    return new_from <= old.valid_from and new_to >= old.valid_to


def _price_cell(q) -> tuple:
    g = q.get if isinstance(q, dict) else (lambda k: getattr(q, k))
    return (name_key(g("category")), g("pax_min"), g("pax_max"), g("occupancy"))


def compare_prices(old_prices, new_prices) -> dict:
    """Cell-by-cell comparison of two package price grids (category x group size x occupancy)."""
    old = {}
    for q in old_prices:
        old.setdefault(_price_cell(q), q)
    seen, cells, cnt = set(), [], Counter()
    for q in new_prices:
        k = _price_cell(q)
        if k in seen:
            continue
        seen.add(k)
        g = q.get if isinstance(q, dict) else (lambda a, q=q: getattr(q, a))
        o = old.get(k)
        new_amt = float(g("amount"))
        label = (f"{g('pax_min')} pax" if g("occupancy") == "double" and g("pax_min") else str(g("occupancy")).replace("_", " "))
        if o is None:
            cnt["new"] += 1
            cells.append({"category": g("category"), "label": label, "old": None, "new": new_amt, "pct": None, "change": "new"})
            continue
        old_amt = float(o["amount"] if isinstance(o, dict) else o.amount)
        kind = "same" if old_amt == new_amt else "up" if new_amt > old_amt else "down"
        cnt[kind] += 1
        cells.append({"category": g("category"), "label": label, "old": old_amt, "new": new_amt,
                      "pct": _pct(old_amt, new_amt), "change": kind})
    cnt["removed"] = len(set(old) - seen)
    moved = [c["pct"] for c in cells if c["pct"] not in (None, 0)]
    return {"counts": {k: cnt.get(k, 0) for k in ("up", "down", "same", "new", "removed")},
            "avg_change_pct": round(sum(moved) / len(moved), 1) if moved else 0.0, "cells": cells}


def _load_package(s: Session, doc: db.SourceDocument, p: dict, idx: int, supplier, links: dict,
                  log: ChangeLog, stats: Counter) -> None:
    sup_id = supplier.id if supplier else None
    vf = _d(p["valid_from"]) if p["valid_from"] else None
    vt = _d(p["valid_to"]) if p["valid_to"] else None
    choice = links.get(str(idx), links.get(idx))
    matches = package_matches(s, p, sup_id)
    if choice == "new":
        family = None
    elif choice not in (None, "", "auto"):
        family = next((m for m in matches if m["family_id"] == int(choice)), None)
        if family is None:                    # a family from another supplier, picked by hand
            members = s.scalars(select(db.Package).where(db.Package.family_id == int(choice))
                                .order_by(db.Package.version.desc())).all()
            family = {"family_id": int(choice), "latest": members[0], "score": 100} if members else None
    else:
        family = matches[0] if matches and matches[0]["score"] >= PACKAGE_MATCH_THRESHOLD else None

    members = s.scalars(select(db.Package).where(db.Package.family_id == family["family_id"])).all() if family else []
    version = max((m.version or 1 for m in members), default=0) + 1
    live = [m for m in members if m.status == "active"]
    # compare with the live version whose dates overlap most, else the newest one
    base = None
    if members:
        def overlap(m):
            if not (vf and vt and m.valid_from and m.valid_to):
                return 0
            return _overlap_days(m.valid_from, m.valid_to, vf, vt)
        base = max(live or members, key=lambda m: (overlap(m), m.version or 1))

    pkg = db.Package(
        supplier_id=sup_id, source_document_id=doc.id, title=p["title"], title_key=p["title_key"],
        destinations=p["destinations"], region=p.get("region"), nights=p["nights"], days=p["days"],
        valid_from=vf, valid_to=vt, inclusions=p["inclusions"], exclusions=p["exclusions"], terms=p["terms"],
        base_name=p.get("base_name"), edition=p.get("edition"), version=version,
        family_id=family["family_id"] if family else None, previous_version_id=base.id if base else None)
    pkg.days_list = [db.PackageDay(day_number=d["day"] or i + 1, title=d["title"], description=d["description"],
                                   overnight=d["overnight"], meals=d["meals"]) for i, d in enumerate(p["itinerary"])]
    region = p.get("region") or (p["destinations"][0] if p["destinations"] else None)
    for ph in p["hotels"]:
        # every hotel a package names goes into the hotel catalog (without rates) so it can be browsed,
        # and gets linked to rates we already hold for it
        hotel = get_or_create_hotel(s, {"name": ph["hotel_name"], "name_key": ph["name_key"], "city": ph.get("city"),
                                        "destination": region, "category": ph.get("category"),
                                        "property_type": ph.get("property_type")}, supplier)
        stats["hotels_in_catalog"] += 1
        pkg.hotels.append(db.PackageHotel(city=ph.get("city"), hotel_name=ph["hotel_name"], hotel_id=hotel.id,
                                          category=ph.get("category"), nights=ph.get("nights"),
                                          room_type=ph.get("room_type"), meal_plan=ph.get("meal_plan")))
    pkg.prices = [db.PackagePrice(category=q["category"], pax_min=q["pax_min"], pax_max=q["pax_max"],
                                  occupancy=q["occupancy"], basis=q["basis"], amount=Decimal(str(q["amount"])),
                                  currency=q["currency"], is_net=q["is_net"], valid_from=_d(q["valid_from"]),
                                  valid_to=_d(q["valid_to"]), season_name=q["season_name"]) for q in p["prices"]]
    s.add(pkg)
    s.flush()
    if pkg.family_id is None:
        pkg.family_id = pkg.id

    older = []
    for m in live:
        if _covers(vf, vt, m):
            log.remember(m)
            m.status, m.replaced_by_document_id, m.replaced_at = "superseded", doc.id, datetime.now()
            action = "replaced"
        elif vf and vt and m.valid_from and m.valid_to and _overlap_days(m.valid_from, m.valid_to, vf, vt):
            action = "overlaps (newer wins on shared dates)"
        else:
            action = "kept (other dates)"
        older.append({"id": m.id, "version": m.version or 1, "title": m.title, "action": action,
                      "valid_from": m.valid_from and m.valid_from.isoformat(),
                      "valid_to": m.valid_to and m.valid_to.isoformat()})
    stats["packages"] += 1
    stats["package_versions_replaced"] += sum(1 for o in older if o["action"] == "replaced")
    comparison = compare_prices(base.prices, p["prices"]) if base else None
    log.packages.append({
        "index": idx, "title": p["title"], "package_id": pkg.id, "family_id": pkg.family_id, "version": version,
        "matched": bool(family), "match_score": family["score"] if family else None,
        "match_choice": choice or "auto", "family_title": family["latest"].title if family else None,
        "compared_with": {"id": base.id, "version": base.version or 1, "title": base.title} if base else None,
        "older_versions": older, "prices": comparison,
        "candidates": [{"family_id": m["family_id"], "title": m["title"], "version": m["version"], "score": m["score"]}
                       for m in matches[:8]],
    })


# ------------------------------------------------------------------ entry points
def load_document(s: Session, doc: db.SourceDocument, norm: dict) -> dict:
    """Write the normalized content of `doc` into live tables and record what changed. Caller commits."""
    stats, log = _load(s, doc, norm)
    doc.changes = {**log.as_dict(), "applied": True, "at": datetime.now().isoformat(timespec="seconds"),
                   "undo": log.undo_info()}
    return {**stats, "changes": doc.changes["summary"]}


class UndoError(ValueError):
    pass


_TABLES = {"hotel_rates": db.HotelRate, "service_rates": db.ServiceRate, "hotel_surcharges": db.HotelSurcharge,
           "packages": db.Package}


def undo_document(s: Session, doc: db.SourceDocument) -> dict:
    """Take an approved document out of the library again: remove what it added and put back the earlier
    rates exactly as they were. Refused when trips use its packages or a later document built on it."""
    if doc.status != "approved":
        raise UndoError("Only an approved document can be taken out of the library")
    info = (doc.changes or {}).get("undo")
    if info is None:
        raise UndoError("This document was approved before undo was available - correct the rates instead")
    pkg_ids = [p.id for p in s.scalars(select(db.Package).where(db.Package.source_document_id == doc.id)).all()]
    if pkg_ids:
        used = s.scalar(select(db.TripItem.id).where(db.TripItem.kind == "package", db.TripItem.ref_id.in_(pkg_ids)).limit(1)) \
            or s.scalar(select(db.TripDay.id).where(db.TripDay.source_package_id.in_(pkg_ids)).limit(1))
        if used:
            raise UndoError("Trips use packages from this document. Move those trips to another version first.")
    for model in (db.HotelRate, db.ServiceRate, db.HotelSurcharge, db.Package):
        later = s.scalar(select(model.id).where(model.source_document_id == doc.id,
                                                model.replaced_by_document_id.is_not(None),
                                                model.replaced_by_document_id != doc.id).limit(1))
        if later:
            raise UndoError("A later document replaced some of these rates. Undo that document first.")
    removed = Counter()
    for c in info.get("clones", []):
        row = s.get(_TABLES[c["t"]], c["id"])
        if row is not None:
            s.delete(row)
            removed["split rows"] += 1
    for model, name in ((db.HotelRate, "hotel rates"), (db.ServiceRate, "services"),
                        (db.HotelSurcharge, "surcharges"), (db.Package, "packages"), (db.Place, "places")):
        for row in s.scalars(select(model).where(model.source_document_id == doc.id)).all():
            s.delete(row)
            removed[name] += 1
    s.flush()
    restored = 0
    for r in info.get("restore", []):
        row = s.get(_TABLES[r["t"]], r["id"])
        if row is None:
            continue
        row.status = r["status"]
        for a in ("valid_from", "valid_to"):
            if a in r:
                setattr(row, a, date.fromisoformat(r[a]))
        if hasattr(row, "replaced_by_document_id") and row.replaced_by_document_id == doc.id:
            row.replaced_by_document_id = None
            if hasattr(row, "replaced_at"):
                row.replaced_at = None
        restored += 1
    # hotels that only this document knew about (no rates, not in any package or trip) go too
    for h in s.scalars(select(db.Hotel)).all():
        if not (s.scalar(select(db.HotelRate.id).where(db.HotelRate.hotel_id == h.id).limit(1))
                or s.scalar(select(db.PackageHotel.id).where(db.PackageHotel.hotel_id == h.id).limit(1))
                or s.scalar(select(db.HotelSurcharge.id).where(db.HotelSurcharge.hotel_id == h.id).limit(1))
                or s.scalar(select(db.TripItem.id).where(db.TripItem.kind == "hotel", db.TripItem.ref_id == h.id).limit(1))):
            for rt in list(h.room_types):
                s.delete(rt)
            s.delete(h)
            removed["hotels"] += 1
    doc.status, doc.approved_at, doc.approved_by = "needs_review", None, None
    doc.changes = None
    return {"removed": dict(removed), "restored": restored}


def preview_changes(s: Session, doc: db.SourceDocument, norm: dict) -> dict:
    """What approving would change, without changing anything (the load runs and is rolled back)."""
    s.commit()                                # start from a clean transaction; only the preview is undone
    try:
        _, log = _load(s, doc, norm)
        return {**log.as_dict(), "applied": False}
    finally:
        s.rollback()


def _load(s: Session, doc: db.SourceDocument, norm: dict) -> tuple[dict, ChangeLog]:
    stats: Counter = Counter()
    log = ChangeLog()
    supplier = get_or_create_supplier(s, norm.get("supplier") or {}, doc.supplier_hint)
    doc.supplier_id = supplier.id if supplier else None
    sup_id = supplier.id if supplier else None

    for h in norm["hotels"]:
        hotel = get_or_create_hotel(s, h, supplier)
        for r in h["rates"]:
            room = get_or_create_room(s, hotel, r["room_type"], r["room_key"])
            new = db.HotelRate(
                hotel_id=hotel.id, room_type_id=room.id, supplier_id=sup_id, source_document_id=doc.id,
                meal_plan=r["meal_plan"], occupancy=r["occupancy"], basis=r["basis"],
                amount=Decimal(str(r["amount"])), currency=r["currency"], is_net=r["is_net"],
                taxes_included=r["taxes_included"], valid_from=_d(r["valid_from"]), valid_to=_d(r["valid_to"]),
                weekdays=r["weekdays"], min_nights=r["min_nights"], season_name=r["season_name"], notes=r["notes"])
            same_key = s.scalars(select(db.HotelRate).where(
                db.HotelRate.room_type_id == room.id, db.HotelRate.meal_plan == r["meal_plan"],
                db.HotelRate.occupancy == r["occupancy"], db.HotelRate.source_document_id != doc.id,
                (db.HotelRate.weekdays.is_(None)) if r["weekdays"] is None else (db.HotelRate.weekdays == r["weekdays"]),
                (db.HotelRate.is_net.is_(None)) if r["is_net"] is None else (db.HotelRate.is_net == r["is_net"]),
            )).all()
            label = f"{hotel.name} · {room.name} · {r['meal_plan']} · {r['occupancy'].replace('_', ' ')}" + \
                    (f" · {r['weekdays']}" if r["weekdays"] else "")
            same_price = lambda o, n=new: (o.amount == n.amount and o.currency == n.currency and o.basis == n.basis
                                           and o.taxes_included == n.taxes_included)
            before = stats["unchanged"]
            _dated_rate(s, log, stats, doc, "hotel", label, same_key, new, same_price)
            if stats["unchanged"] == before:
                stats["hotel_rates"] += 1
        for sc in h["surcharges"]:
            df, dt = _d(sc["date_from"]), _d(sc["date_to"])
            amount = Decimal(str(sc["amount"])) if sc["amount"] is not None else None
            older = [o for o in s.scalars(select(db.HotelSurcharge).where(
                db.HotelSurcharge.hotel_id == hotel.id, db.HotelSurcharge.kind == sc["kind"],
                db.HotelSurcharge.status == "active", db.HotelSurcharge.source_document_id != doc.id)).all()
                if name_key(o.name) == name_key(sc["name"]) and name_key(o.room_type) == name_key(sc.get("room_type"))
                and _overlap_days(o.date_from, o.date_to, df, dt)]
            if any(o.date_from == df and o.date_to == dt and o.amount == amount for o in older):
                stats["unchanged"] += 1
                log.counts["same"] += 1
                continue
            for o in older:
                log.remember(o)
                o.status, o.replaced_by_document_id = "superseded", doc.id
                log.counts["replaced"] += 1
            s.add(db.HotelSurcharge(
                hotel_id=hotel.id, source_document_id=doc.id, kind=sc["kind"], name=sc["name"],
                room_type=sc.get("room_type"), date_from=df, date_to=dt, amount=amount, currency=sc["currency"],
                basis=sc["basis"], mandatory=sc["mandatory"], notes=sc["notes"]))
            stats["surcharges"] += 1

    links = norm.get("package_links") or {}
    for i, p in enumerate(norm["packages"]):
        _load_package(s, doc, p, i, supplier, links, log, stats)

    for r in norm["services"]:
        new = db.ServiceRate(
            supplier_id=sup_id, source_document_id=doc.id, kind=r["kind"], name=r["name"], name_key=r["name_key"],
            destination=r["destination"], vehicle_type=r["vehicle_type"], basis=r["basis"], pax_min=r["pax_min"],
            pax_max=r["pax_max"], amount=Decimal(str(r["amount"])),
            amount_max=Decimal(str(r["amount_max"])) if r.get("amount_max") is not None else None,
            optional=r.get("optional", False), currency=r["currency"], is_net=r["is_net"],
            valid_from=_d(r["valid_from"]), valid_to=_d(r["valid_to"]), season_name=r["season_name"], notes=r["notes"])
        candidates = s.scalars(select(db.ServiceRate).where(
            db.ServiceRate.kind == r["kind"], db.ServiceRate.source_document_id != doc.id,
            (db.ServiceRate.supplier_id.is_(None)) if sup_id is None else (db.ServiceRate.supplier_id == sup_id),
            (db.ServiceRate.vehicle_type.is_(None)) if r["vehicle_type"] is None
            else (db.ServiceRate.vehicle_type == r["vehicle_type"]),
            db.ServiceRate.basis == r["basis"])).all()
        # the same service may be worded a little differently in the new sheet
        best = _best(candidates, r["name_key"], threshold=SERVICE_MATCH_THRESHOLD)
        same_key = [c for c in candidates if best is not None and c.name_key == best.name_key]
        label = r["name"] + (f" ({r['vehicle_type']})" if r["vehicle_type"] else "")
        same_price = lambda o, n=new: (o.amount == n.amount and o.amount_max == n.amount_max and o.currency == n.currency)
        before = stats["unchanged"]
        _dated_rate(s, log, stats, doc, "service", label, same_key, new, same_price)
        if stats["unchanged"] == before:
            stats["services"] += 1

    for pl in norm.get("places", []):
        existing = [x for x in s.scalars(select(db.Place).where(db.Place.name_key == pl["name_key"])).all()
                    if not pl.get("destination") or not x.destination
                    or name_key(x.destination) == name_key(pl["destination"])]
        if existing:
            for f in ("destination", "region", "kind", "description", "availability"):
                if pl.get(f) and not getattr(existing[0], f):
                    setattr(existing[0], f, pl[f])
        else:
            s.add(db.Place(supplier_id=sup_id, source_document_id=doc.id,
                           **{f: pl.get(f) for f in ("name", "name_key", "destination", "region", "kind",
                                                     "description", "availability")}))
        stats["places"] += 1
    s.flush()
    keys = ("hotel_rates", "surcharges", "packages", "services", "older_rates_adjusted", "hotels_in_catalog",
            "places", "unchanged", "package_versions_replaced")
    return {k: stats.get(k, 0) for k in keys}, log


# ------------------------------------------------------------------ naming context for the AI
_GENERIC = {"hotel", "hotels", "resort", "resorts", "spa", "and", "the", "travels", "travel", "tours", "tour",
            "holidays", "holiday", "pvt", "ltd", "private", "limited", "llp", "inc", "group", "dmc", "company",
            "services", "service", "trip", "trips", "stay", "stays", "inn", "rates", "rate"}


def supplier_from_filename(s: Session, filename: str) -> db.Supplier | None:
    """'misty_hills_munnar_2026-27_revised.pdf' -> Misty Hills Resort and Spa: the supplier whose distinctive
    words all appear in the file name (at least two of them, or one long one)."""
    words = set(name_key(re.sub(r"[_\-.]+", " ", filename)).split())
    best, best_n = None, 0
    for c in s.scalars(select(db.Supplier)).all():
        own = [w for w in c.name_key.split() if w not in _GENERIC and len(w) >= 3]
        if not own or not all(w in words for w in own):
            continue
        if len(own) >= 2 or len(own[0]) >= 6:
            if len(own) > best_n:
                best, best_n = c, len(own)
    return best



def reference_names(s: Session, supplier_hint: str | None, filename: str | None, limit_chars: int = 6000) -> str | None:
    """Names this supplier's earlier documents used, so the AI can spell repeats the same way.

    The supplier is found from the name typed at upload, or from the file name. Returns None for a supplier
    we have never seen (then there is nothing to be consistent with)."""
    sup = find_supplier(s, supplier_hint) if supplier_hint else None
    if sup is None and filename:
        sup = supplier_from_filename(s, filename)
    if sup is None:
        return None
    lines = [f"Supplier: {sup.name}"]
    pk = s.scalars(select(db.Package).where(db.Package.supplier_id == sup.id, db.Package.status == "active")
                   .order_by(db.Package.id.desc()).limit(40)).all()
    if pk:
        lines.append("Packages: " + "; ".join(dict.fromkeys(p.title for p in pk)))
    hotels = s.scalars(select(db.Hotel).where(db.Hotel.id.in_(
        select(db.HotelRate.hotel_id).where(db.HotelRate.supplier_id == sup.id))).limit(150)).all()
    for h in hotels:
        rooms = ", ".join(r.name for r in h.room_types[:12])
        lines.append(f"Hotel: {h.name}" + (f" ({h.city})" if h.city else "") + (f" - rooms: {rooms}" if rooms else ""))
    svc = s.scalars(select(db.ServiceRate).where(db.ServiceRate.supplier_id == sup.id, db.ServiceRate.status == "active")
                    .limit(150)).all()
    if svc:
        lines.append("Services: " + "; ".join(dict.fromkeys(x.name for x in svc)))
    if pk:                                    # hotels named in its packages, by city (trimmed first if long)
        by_city: dict[str, list[str]] = {}
        for ph in s.scalars(select(db.PackageHotel).where(db.PackageHotel.package_id.in_([p.id for p in pk]))).all():
            by_city.setdefault(ph.city or "?", []).append(ph.hotel_name)
        for city, names in by_city.items():
            lines.append(f"Package hotels ({city}): " + ", ".join(dict.fromkeys(names)))
    text = "\n".join(lines)
    return text[:limit_chars] if len(lines) > 1 else None
