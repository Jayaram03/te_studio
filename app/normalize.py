"""Stage 3: normalize + validate.

Turns the raw `Extraction` into clean rows ready for the database:
- meal plans   -> EP / CP / MAP / AP / AI
- occupancies  -> single / double / triple / extra_adult / child_with_bed / child_without_bed / per_person
- dates        -> real dates, Indian day-first format, missing years inferred, seasons expanded
- currencies   -> ISO codes
- day limits   -> "fri,sat"
Every problem is recorded as an issue. `error` issues block approval; `warning`s are shown for review.
"""
from __future__ import annotations

import re
from datetime import date, datetime, timedelta

from dateutil import parser as dparser

from .config import get_settings

# ------------------------------------------------------------------ vocabularies
MEAL_PLANS = {
    "EP": ["ep", "epai", "room only", "ro", "european plan", "without breakfast", "no meals"],
    "CP": ["cp", "cpai", "bb", "b&b", "bed and breakfast", "bed & breakfast", "breakfast", "with breakfast",
           "continental plan", "room with breakfast", "rb"],
    "MAP": ["map", "mapai", "hb", "half board", "modified american plan", "breakfast and dinner",
            "breakfast & dinner", "breakfast + dinner", "breakfast and lunch or dinner", "b/d"],
    "AP": ["ap", "apai", "fb", "full board", "american plan", "all meals", "breakfast lunch dinner",
           "breakfast, lunch & dinner", "b/l/d"],
    "AI": ["ai", "all inclusive", "all-inclusive"],
}
OCCUPANCIES = {
    "single": ["single", "sgl", "single occupancy", "single room", "single sharing", "sngl", "per person single"],
    "double": ["double", "dbl", "twin", "twn", "double occupancy", "twin sharing", "double sharing", "couple",
               "per couple", "per person twin sharing", "per person on twin sharing", "pp twin sharing",
               "twin/double", "dbl/twn", "base", "sgl/dbl", "single/double", "sgl / dbl", "single or double"],
    "triple": ["triple", "tpl", "trpl", "triple sharing", "triple occupancy", "per person triple sharing"],
    "extra_adult": ["extra adult", "extra bed", "exb", "eb", "extra bed adult", "extra person", "eab",
                    "extra adult with bed", "third adult", "3rd adult", "extra adult bed"],
    "child_with_bed": ["child with bed", "cwb", "child with extra bed", "child extra bed", "extra bed child",
                       "child (with bed)"],
    "child_without_bed": ["child without bed", "cnb", "cwob", "child no bed", "child without extra bed",
                          "child (without bed)", "child sharing bed"],
    "per_person": ["per person", "pp", "ppn", "per pax", "per head", "adult"],
    "quad": ["quad", "quad sharing", "quadruple"],
    "single_supplement": ["single supplement", "single suppl", "sgl supplement", "single supp", "sgl supp"],
}
CURRENCIES = {
    "INR": ["inr", "₹", "rs", "rs.", "rupees", "rupee", "indian rupee"],
    "USD": ["usd", "$", "us$", "us dollar", "dollar"],
    "EUR": ["eur", "€", "euro"], "GBP": ["gbp", "£", "pound"],
    "AED": ["aed", "dhs", "dirham"], "THB": ["thb", "฿", "baht"],
    "SGD": ["sgd", "s$"], "MYR": ["myr", "rm", "ringgit"], "IDR": ["idr", "rp", "rupiah"],
    "LKR": ["lkr", "sri lankan rupee"], "MVR": ["mvr", "rufiyaa"], "NPR": ["npr", "nepalese rupee"],
    "VND": ["vnd", "dong"], "BTN": ["btn", "ngultrum"], "JPY": ["jpy", "¥", "yen"],
    "AUD": ["aud", "a$"], "CHF": ["chf"], "TRY": ["try", "lira"], "KZT": ["kzt"], "AZN": ["azn"],
}
DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


def _lookup(value: str | None, table: dict[str, list[str]]) -> str | None:
    if value is None:
        return None
    v = " ".join(re.sub(r"[()\[\]]", " ", str(value)).lower().replace("_", " ").split())
    for code, words in table.items():
        if v == code.lower().replace("_", " ") or v in words:
            return code
    def found(w):
        return len(w) >= 2 and re.search(rf"(?<![a-z]){re.escape(w)}(?![a-z])", v)

    # 1) a code written inside a longer label: "Deluxe - MAP", "CPAI (breakfast)"
    codes = [(len(w), code) for code, words in table.items()
             for w in [code.lower().replace("_", " "), code.lower() + "ai"] if found(w)]
    if codes:
        return max(codes)[1]
    # 2) otherwise the longest matching phrase wins ("breakfast and dinner" beats "breakfast")
    phrases = [(len(w), code) for code, words in table.items() for w in words if found(w)]
    return max(phrases)[1] if phrases else None


def norm_meal_plan(v): return _lookup(v, MEAL_PLANS)
def norm_occupancy(v): return _lookup(v, OCCUPANCIES)


def norm_currency(v: str | None) -> str | None:
    if not v:
        return None
    s = str(v).strip()
    if re.fullmatch(r"[A-Za-z]{3}", s) and s.upper() in CURRENCIES:
        return s.upper()
    return _lookup(s, CURRENCIES)


def name_key(s: str | None) -> str:
    return " ".join(re.sub(r"[^a-z0-9 ]+", " ", (s or "").lower()).split())


# ------------------------------------------------------------------ dates
_ISO = re.compile(r"^\s*(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})\s*$")
_ORD = re.compile(r"(\d)(st|nd|rd|th)\b", re.I)


def parse_date(s, ref: date | None = None) -> tuple[date | None, bool]:
    """Parse a date as Indian sheets write it (day first). Returns (date, year_was_given)."""
    if s is None or str(s).strip() == "":
        return None, False
    if isinstance(s, datetime):
        return s.date(), True
    if isinstance(s, date):
        return s, True
    txt = _ORD.sub(r"\1", str(s).strip()).replace("’", "'")
    txt = re.sub(r"'(\d{2})\b", r"20\1", txt)                    # Dec'26 -> Dec 2026
    if m := _ISO.match(txt):
        try:
            return date(int(m[1]), int(m[2]), int(m[3])), True
        except ValueError:
            return None, False
    ref = ref or date.today()
    try:
        a = dparser.parse(txt, dayfirst=True, default=datetime(2001, 1, 1))
        b = dparser.parse(txt, dayfirst=True, default=datetime(2002, 1, 1))
    except (ValueError, OverflowError):
        return None, False
    if a.year != b.year:                                         # no year in the text
        d = dparser.parse(txt, dayfirst=True, default=datetime(ref.year, 1, 1)).date()
        return d, False
    return a.date(), True


def _day_missing(txt: str) -> bool:
    """'Aug 2026' has no day of month; '12 Aug 2026' does."""
    try:
        a = dparser.parse(txt, dayfirst=True, default=datetime(2001, 1, 1))
        b = dparser.parse(txt, dayfirst=True, default=datetime(2001, 1, 28))
        return a.day != b.day
    except (ValueError, OverflowError):
        return False


def _month_end(d: date) -> date:
    nxt = date(d.year + (d.month == 12), d.month % 12 + 1, 1)
    return nxt - timedelta(days=1)


def parse_range(start, end, ref: date | None = None) -> tuple[date | None, date | None]:
    s, s_has_year = parse_date(start, ref)
    if s and not s_has_year and ref and s < ref - timedelta(days=31):
        s = s.replace(year=s.year + 1)                           # "5 Jan" in a sheet valid from Oct -> next Jan
    e, e_has_year = parse_date(end, s or ref)
    if e and isinstance(end, str) and not _ISO.match(end) and _day_missing(_ORD.sub(r"\1", end)):
        e = _month_end(e)                                        # "Aug 2026 - Oct 2026" -> ends 31 Oct
    if s and e and e < s and not e_has_year:
        e = e.replace(year=e.year + 1)                           # 20 Dec - 5 Jan
    return s, e


def parse_weekdays(v: str | None) -> tuple[str | None, bool]:
    """'Fri-Sat' -> 'fri,sat'. Returns (value, understood). None value = every day."""
    if not v or not str(v).strip():
        return None, True
    t = str(v).lower()
    weekend = [d.strip() for d in get_settings().weekend_days.split(",")]
    if re.search(r"week\s*days?|weekday", t) and "weekend" not in t:
        return ",".join(d for d in DAYS if d not in weekend), True
    if "weekend" in t:
        return ",".join(d for d in DAYS if d in weekend), True
    if re.search(r"all\s*days|daily|every\s*day", t):
        return None, True
    found = re.findall(r"(mon|tue|wed|thu|fri|sat|sun)[a-z]*", t)
    if not found:
        return None, False
    idx = [DAYS.index(f) for f in found]
    if len(idx) == 2 and re.search(r"(mon|tue|wed|thu|fri|sat|sun)[a-z]*\s*(-|–|to|till|through)\s*"
                                   r"(mon|tue|wed|thu|fri|sat|sun)", t):
        a, b = idx
        rng = list(range(a, b + 1)) if a <= b else list(range(a, 7)) + list(range(0, b + 1))
        idx = rng
    return ",".join(DAYS[i] for i in sorted(set(idx))), True


# ------------------------------------------------------------------ main
class _Issues(list):
    def err(self, where, msg): self.append({"level": "error", "where": where, "message": msg})
    def warn(self, where, msg): self.append({"level": "warning", "where": where, "message": msg})


def normalize(extraction: dict, overrides: dict | None = None, today: date | None = None) -> dict:
    """overrides (all optional): valid_from, valid_to, currency, rate_type ('net'|'rack'), taxes ('included'|'excluded')"""
    ov = overrides or {}
    today = today or date.today()
    settings = get_settings()
    issues = _Issues()
    x = extraction

    for w in x.get("warnings") or []:
        issues.warn("document", f"AI note: {w}")

    # document level defaults ------------------------------------------------
    doc_from = doc_to = None
    if x.get("validity"):
        doc_from, doc_to = parse_range(x["validity"].get("start"), x["validity"].get("end"), today)
    if ov.get("valid_from") or ov.get("valid_to"):
        of, ot = parse_range(ov.get("valid_from"), ov.get("valid_to"), today)
        doc_from, doc_to = of or doc_from, ot or doc_to
    ref = doc_from or today

    doc_currency = norm_currency(ov.get("currency")) or norm_currency(x.get("currency"))
    doc_rate_type = ov.get("rate_type") or x.get("rate_type") or "unknown"
    doc_taxes = ov.get("taxes") or x.get("taxes") or "unknown"

    seasons: dict[str, dict] = {}
    for i, s in enumerate(x.get("seasons") or []):
        periods = []
        for p in s.get("periods") or []:
            a, b = parse_range(p.get("start"), p.get("end"), ref)
            if not a or not b:
                issues.err(f"seasons[{i}]", f"Season '{s.get('name') or s['key']}' has an unreadable date range "
                                            f"{p.get('start')} - {p.get('end')}")
                continue
            if a > b:
                issues.err(f"seasons[{i}]", f"Season '{s.get('name') or s['key']}' starts after it ends ({a} > {b})")
                continue
            periods.append((a, b))
        seasons[s["key"]] = {"name": s.get("name") or s["key"], "periods": periods}

    unknown_net = unknown_tax = 0
    missing_currency = 0

    def resolve_periods(where, line, fallback_from=None, fallback_to=None):
        """-> list of (from, to, season_name)."""
        if line.get("valid_from") or line.get("valid_to"):
            a, b = parse_range(line.get("valid_from"), line.get("valid_to"), ref)
            a, b = a or fallback_from or doc_from, b or fallback_to or doc_to
            if a and b:
                return [(a, b, None)]
        if line.get("season_key"):
            s = seasons.get(line["season_key"])
            if not s:
                issues.err(where, f"Refers to unknown season '{line['season_key']}'")
                return []
            if s["periods"]:
                return [(a, b, s["name"]) for a, b in s["periods"]]
            issues.err(where, f"Season '{s['name']}' has no dates")
            return []
        a, b = fallback_from or doc_from, fallback_to or doc_to
        if a and b:
            return [(a, b, None)]
        issues.err(where, "No validity dates (set a default validity when approving)")
        return []

    def currency_of(line_cur, *more):
        nonlocal missing_currency
        c = norm_currency(line_cur)
        for m in more:
            c = c or norm_currency(m)
        c = c or doc_currency
        if not c:
            missing_currency += 1
            c = settings.default_currency
        return c

    def net_flag(rt):
        nonlocal unknown_net
        rt = rt if rt and rt != "unknown" else doc_rate_type
        if rt == "unknown":
            unknown_net += 1
            return None
        return rt == "net"

    def tax_flag(t):
        nonlocal unknown_tax
        t = t if t and t != "unknown" else doc_taxes
        if t == "unknown":
            unknown_tax += 1
            return None
        return t == "included"

    def check_period(where, a, b):
        if a > b:
            issues.err(where, f"Valid from {a} is after valid to {b}")
            return False
        if b < today:
            issues.warn(where, f"Rate expired on {b}")
        if (b - a).days > 730:
            issues.warn(where, f"Validity longer than 2 years ({a} to {b}) - check the dates")
        return True

    # hotels -------------------------------------------------------------------
    hotels_out = []
    for hi, h in enumerate(x.get("hotels") or []):
        hw = f"hotels[{hi}] {h.get('name')}"
        if not (h.get("name") or "").strip():
            issues.err(hw, "Hotel without a name")
            continue
        rows = []
        for ri, r in enumerate(h.get("rates") or []):
            w = f"{hw} / rate {ri + 1} ({r.get('room_type')}, {r.get('meal_plan')}, {r.get('occupancy')})"
            if r.get("amount") is None:
                issues.warn(w, "No amount (on request?) - skipped")
                continue
            if r["amount"] <= 0:
                issues.err(w, f"Amount must be positive, got {r['amount']}")
                continue
            if not (r.get("room_type") or "").strip():
                issues.err(w, "Missing room type")
                continue
            mp = norm_meal_plan(r.get("meal_plan"))
            if not mp:
                issues.err(w, f"Meal plan '{r.get('meal_plan')}' not recognised (use EP/CP/MAP/AP/AI)")
                continue
            occ = norm_occupancy(r.get("occupancy"))
            if not occ:
                issues.err(w, f"Occupancy '{r.get('occupancy')}' not recognised")
                continue
            wd, ok = parse_weekdays(r.get("days"))
            if not ok:
                issues.warn(w, f"Day restriction '{r.get('days')}' not understood - treated as every day")
            for a, b, sname in resolve_periods(w, r):
                if not check_period(w, a, b):
                    continue
                rows.append({
                    "room_type": r["room_type"].strip(), "room_key": name_key(r["room_type"]),
                    "meal_plan": mp, "occupancy": occ,
                    "basis": r.get("basis") if r.get("basis") in ("per_room_per_night", "per_person_per_night")
                    else ("per_person_per_night" if occ == "per_person" else "per_room_per_night"),
                    "amount": round(float(r["amount"]), 2), "currency": currency_of(r.get("currency")),
                    "is_net": net_flag(r.get("rate_type")), "taxes_included": tax_flag(r.get("taxes")),
                    "valid_from": a.isoformat(), "valid_to": b.isoformat(), "weekdays": wd,
                    "min_nights": r.get("min_nights"), "season_name": sname, "notes": r.get("notes"),
                })
        _check_duplicates(hw, rows, issues)
        _check_child_rates(hw, rows, issues)

        surcharges = []
        for si, s in enumerate(h.get("supplements") or []):
            w = f"{hw} / supplement '{s.get('name')}'"
            a, b = parse_range(s.get("date_from"), s.get("date_to") or s.get("date_from"), ref)
            if not a or not b:
                issues.err(w, "Supplement without readable dates")
                continue
            if s.get("amount") is None:
                issues.warn(w, "Supplement without an amount")
            surcharges.append({"kind": "supplement", "name": s.get("name"), "date_from": a.isoformat(),
                               "date_to": b.isoformat(), "amount": s.get("amount"),
                               "currency": currency_of(s.get("currency")), "basis": s.get("basis"),
                               "mandatory": bool(s.get("mandatory", True)), "notes": s.get("notes"), "room_type": None})
        for bi, bo in enumerate(h.get("blackout_dates") or []):
            a, b = parse_range(bo.get("start"), bo.get("end") or bo.get("start"), ref)
            if not a or not b:
                issues.err(f"{hw} / blackout {bi + 1}", "Unreadable blackout dates")
                continue
            surcharges.append({"kind": "blackout", "name": "Blackout / stop sale", "date_from": a.isoformat(),
                               "date_to": b.isoformat(), "amount": None, "currency": None, "basis": None,
                               "mandatory": True, "notes": bo.get("notes"), "room_type": bo.get("room_type")})
        if h.get("rates") and not rows:
            issues.warn(hw, "No usable rates for this hotel")
        hotels_out.append({
            "name": h["name"].strip(), "name_key": name_key(h["name"]), "city": h.get("city"),
            "category": h.get("category"), "property_type": h.get("property_type"),
            "destination": h.get("destination") or h.get("city"), "star_rating": h.get("star_rating"),
            "address": h.get("address"), "child_policy": h.get("child_policy"), "notes": h.get("notes"),
            "rates": rows, "surcharges": surcharges,
        })

    # packages -----------------------------------------------------------------
    packages_out = []
    for pi, p in enumerate(x.get("packages") or []):
        pw = f"packages[{pi}] {p.get('title')}"
        pf, pt = parse_range(p.get("valid_from"), p.get("valid_to"), ref)
        pf, pt = pf or doc_from, pt or doc_to
        prices = []
        for qi, q in enumerate(p.get("prices") or []):
            w = f"{pw} / price {qi + 1} ({q.get('category')}, {q.get('occupancy')})"
            if q.get("amount") is None or q["amount"] <= 0:
                issues.warn(w, "No usable amount - skipped")
                continue
            occ = norm_occupancy(q.get("occupancy")) or "double"
            for a, b, sname in resolve_periods(w, q, pf, pt):
                if not check_period(w, a, b):
                    continue
                prices.append({"category": q.get("category"), "pax_min": q.get("pax_min"), "pax_max": q.get("pax_max"),
                               "occupancy": occ, "basis": q.get("basis") if q.get("basis") != "unknown" else "per_person",
                               "amount": round(float(q["amount"]), 2), "currency": currency_of(q.get("currency")),
                               "is_net": net_flag(q.get("rate_type")), "valid_from": a.isoformat(),
                               "valid_to": b.isoformat(), "season_name": sname})
        _check_group_prices(pw, prices, issues)
        if not prices:
            issues.warn(pw, "Package has no usable prices")
        if not p.get("itinerary"):
            issues.warn(pw, "Package has no day-wise itinerary")
        if p.get("nights") and p.get("itinerary") and len(p["itinerary"]) not in (p["nights"], p["nights"] + 1):
            issues.warn(pw, f"{p['nights']} nights but {len(p['itinerary'])} itinerary days")
        packages_out.append({
            "title": p["title"].strip(), "title_key": name_key(p["title"]), "region": p.get("region"),
            "base_name": (p.get("base_name") or "").strip() or None, "edition": (p.get("edition") or "").strip() or None,
            "destinations": p.get("destinations") or [],
            "nights": p.get("nights"), "days": p.get("days"),
            "valid_from": pf.isoformat() if pf else None, "valid_to": pt.isoformat() if pt else None,
            "itinerary": [{"day": d.get("day"), "title": d.get("title"), "description": d.get("description"),
                           "overnight": d.get("overnight"), "meals": d.get("meals")} for d in p.get("itinerary") or []],
            "hotels": _package_hotels(p.get("hotels") or []),
            "prices": prices, "inclusions": p.get("inclusions") or [], "exclusions": p.get("exclusions") or [],
            "terms": p.get("terms") or [],
        })

    # services -----------------------------------------------------------------
    services_out = []
    for si, s in enumerate(x.get("services") or []):
        w = f"services[{si}] {s.get('name')} ({s.get('vehicle_type') or ''})"
        if s.get("amount") is None or s["amount"] <= 0:
            issues.warn(w, "No usable amount - skipped")
            continue
        lo, hi = float(s["amount"]), s.get("amount_max")
        if hi is not None and hi < lo:
            lo, hi = hi, lo
        if hi == lo:
            hi = None
        for a, b, sname in resolve_periods(w, s):
            if not check_period(w, a, b):
                continue
            services_out.append({
                "kind": s["kind"], "name": s["name"].strip(), "name_key": name_key(s["name"]),
                "destination": s.get("destination"), "vehicle_type": s.get("vehicle_type"),
                "basis": s.get("basis") or "unknown", "pax_min": s.get("pax_min"), "pax_max": s.get("pax_max"),
                "amount": round(lo, 2), "amount_max": round(float(hi), 2) if hi is not None else None,
                "optional": bool(s.get("optional")), "currency": currency_of(s.get("currency")),
                "is_net": net_flag(s.get("rate_type")), "valid_from": a.isoformat(), "valid_to": b.isoformat(),
                "season_name": sname, "notes": s.get("notes"),
            })

    # places -------------------------------------------------------------------
    places_out, seen_places = [], set()
    for pl in x.get("places") or []:
        k = (name_key(pl.get("name")), name_key(pl.get("destination")))
        if not k[0] or k in seen_places:
            continue
        seen_places.add(k)
        places_out.append({"name": pl["name"].strip(), "name_key": k[0], "destination": pl.get("destination"),
                           "region": pl.get("region"), "kind": pl.get("kind"), "description": pl.get("description"),
                           "availability": pl.get("availability")})

    # document level summaries -----------------------------------------------
    if missing_currency:
        issues.warn("document", f"Currency not stated for {missing_currency} rate(s) - assumed "
                                f"{settings.default_currency}")
    if unknown_net:
        issues.warn("document", f"{unknown_net} rate(s) not marked as net (B2B) or rack - set it when approving")
    if unknown_tax:
        issues.warn("document", f"{unknown_tax} rate(s) don't say whether taxes are included")
    n_rows = (sum(len(h["rates"]) for h in hotels_out) + len(services_out) + len(hotels_out) + len(places_out)
              + sum(len(p["prices"]) + len(p["itinerary"]) for p in packages_out))
    if n_rows == 0:
        issues.err("document", "Nothing usable was extracted")

    sup = dict(x.get("supplier") or {})
    sup["name_key"] = name_key(sup.get("name"))
    return {
        "document_type": x.get("document_type"),
        "supplier": sup,
        "general_terms": x.get("general_terms") or [],
        "hotels": hotels_out, "packages": packages_out, "services": services_out, "places": places_out,
        "issues": list(issues),
        "stats": {"hotels": len(hotels_out), "hotel_rates": sum(len(h["rates"]) for h in hotels_out),
                  "packages": len(packages_out), "package_prices": sum(len(p["prices"]) for p in packages_out),
                  "package_hotels": sum(len(p["hotels"]) for p in packages_out),
                  "services": len(services_out), "places": len(places_out),
                  "errors": sum(1 for i in issues if i["level"] == "error"),
                  "warnings": sum(1 for i in issues if i["level"] == "warning")},
    }


def _check_group_prices(where, prices, issues):
    """Per-person package prices normally fall as the group grows; a rise is usually a typo in the sheet."""
    groups: dict[tuple, list[dict]] = {}
    for q in prices:
        if q["pax_min"] and q["basis"] == "per_person":
            groups.setdefault((q["category"], q["occupancy"], q["valid_from"], q["currency"]), []).append(q)
    for (cat, occ, _, cur), rows in groups.items():
        rows.sort(key=lambda q: q["pax_min"])
        for a, b in zip(rows, rows[1:]):
            if b["amount"] > a["amount"]:
                issues.warn(where, f"{cat}: {b['pax_min']} pax costs more per person ({b['amount']:,.0f}) than "
                                   f"{a['pax_min']} pax ({a['amount']:,.0f}) - check with the supplier")


def _package_hotels(rows: list[dict]) -> list[dict]:
    out, seen = [], set()
    for hh in rows:
        name = " ".join((hh.get("hotel_name") or "").split())
        k = (name_key(name), name_key(hh.get("city")), name_key(hh.get("category")))
        if not k[0] or k in seen:
            continue
        seen.add(k)
        out.append({**hh, "hotel_name": name, "name_key": k[0],
                    "meal_plan": norm_meal_plan(hh.get("meal_plan")) or hh.get("meal_plan")})
    return out


def _overlaps(a, b):
    return a["valid_from"] <= b["valid_to"] and b["valid_from"] <= a["valid_to"]


def _check_duplicates(where, rows, issues):
    seen: dict[tuple, list[dict]] = {}
    keep = []
    for r in rows:
        k = (r["room_key"], r["meal_plan"], r["occupancy"], r["weekdays"], r["is_net"], r["currency"])
        dup = False
        for o in seen.get(k, []):
            if _overlaps(o, r):
                if o["amount"] == r["amount"]:
                    dup = True
                else:
                    issues.err(where, f"Two different rates for {r['room_type']} {r['meal_plan']} {r['occupancy']} "
                                      f"on overlapping dates: {o['amount']} ({o['valid_from']}..{o['valid_to']}) vs "
                                      f"{r['amount']} ({r['valid_from']}..{r['valid_to']})")
        if not dup:
            seen.setdefault(k, []).append(r)
            keep.append(r)
    rows[:] = keep


def _check_child_rates(where, rows, issues):
    for r in rows:
        if r["occupancy"] in ("child_with_bed", "child_without_bed"):
            dbl = [o for o in rows if o["occupancy"] == "double" and o["room_key"] == r["room_key"]
                   and o["meal_plan"] == r["meal_plan"] and _overlaps(o, r)]
            if dbl and r["amount"] > dbl[0]["amount"]:
                issues.warn(where, f"Child rate {r['amount']} is higher than the double room rate {dbl[0]['amount']} "
                                   f"({r['room_type']} {r['meal_plan']}) - check")
