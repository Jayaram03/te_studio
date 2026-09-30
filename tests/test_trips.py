from datetime import date

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app import api, catalog, db, pipeline, trips
from app.config import get_settings
from conftest import signed_in_client, sample

KASHMIR = "Off_Season_2026_Kashmir_package_5N_6D.pdf"


def _approve(s, name, ex, **ov):
    doc, _ = pipeline.ingest(s, *sample(name), ex)
    assert doc.status == "needs_review", doc.error
    return pipeline.approve(s, doc, ov or None, approved_by="test")


def _kashmir(s, ex):
    stats = _approve(s, KASHMIR, ex, rate_type="net")
    return stats, s.scalar(select(db.Package).where(db.Package.title_key.like("kashmir%")))


def test_kashmir_package_is_fully_captured(session, extractor):
    doc, _ = pipeline.ingest(session, *sample(KASHMIR), extractor)
    st = doc.normalized["stats"]
    assert st["package_prices"] == 36 and st["package_hotels"] == 125 and st["services"] == 10 and st["places"] == 19
    msgs = [i["message"] for i in doc.issues]
    assert any("8 pax costs more per person (12,800) than 6 pax (12,500)" in m for m in msgs)
    stats = pipeline.approve(session, doc, {"rate_type": "net"})
    assert stats["packages"] == 1 and stats["services"] == 10 and stats["places"] == 19
    pkg = session.scalar(select(db.Package))
    assert (pkg.valid_from, pkg.valid_to) == (date(2026, 8, 1), date(2026, 10, 31))   # "Aug 2026 - Oct 2026"
    assert pkg.region == "Kashmir" and len(pkg.days_list) == 6
    sup = session.scalar(select(db.Supplier))
    assert sup.gst_number == "01AEXPF9830N1ZY" and "Rainawari" in sup.address


def test_package_hotels_fill_the_hotel_catalog(session, extractor):
    _kashmir(session, extractor)
    all_hotels = catalog.hotels(session)
    # 53 Srinagar hotels (Brown Palace is listed under two categories), 48 Pahalgam, 9 houseboats
    assert len(all_hotels) == 110
    assert len(catalog.hotels(session, city="Pahalgam", category="Luxury")) == 6
    boats = [h for h in all_hotels if h["property_type"] == "houseboat"]
    assert {h["name"] for h in boats} >= {"Dawn", "Nazneen", "Wanganoo Paradise"} and len(boats) == 9
    # similar names stay separate hotels
    names = {h["name"] for h in all_hotels}
    assert {"Bombay Palace", "Bombay Residency", "Royal Batoo", "Royal Heritage", "Moonstone",
            "Moonstone De Luxury"} <= names


def test_package_price_by_group_and_category(session, extractor):
    _, pkg = _kashmir(session, extractor)
    on = date(2026, 9, 15)
    assert trips.price_package(pkg, "Deluxe", 4, travel_date=on)["total"] == 4 * 14000
    five = trips.price_package(pkg, "Deluxe", 5, extra_beds=1, travel_date=on)
    assert five["total"] == 4 * 14000 + 6500 and five["pax_tier"] == 4
    three = trips.price_package(pkg, "Standard", 3, travel_date=on)
    assert three["pax_tier"] == 2 and any("odd number" in w for w in three["warnings"])
    fam = trips.price_package(pkg, "Premium", 2, children_with_bed=1, children_without_bed=1, travel_date=on)
    assert fam["total"] == 2 * 18500 + 7500 + 6500              # CWB uses the "extra bed / CWB" rate
    big = trips.price_package(pkg, "Luxury", 20, travel_date=on)
    assert big["pax_tier"] == 14 and big["total"] == 20 * 16500
    late = trips.price_package(pkg, "Standard", 2, travel_date=date(2026, 11, 10))
    assert late["errors"] and "not valid" in late["errors"][0]


def test_trip_from_package_with_addons_combined_days_and_totals(session, extractor):
    _, pkg = _kashmir(session, extractor)
    _approve(session, "green_valley_kerala_classic.pdf", extractor)
    t = trips.create_trip(session, {"title": "Sharma family - Kashmir", "start_date": "2026-09-10", "adults": 2,
                                    "markup_pct": 10, "gst_pct": 5})
    trips.apply_package(session, t, pkg.id, "Premium")
    v = trips.trip_view(session, t)
    assert len(v["days"]) == 6 and v["days"][0]["date"] == "2026-09-10" and v["days"][5]["date"] == "2026-09-15"
    assert v["totals"]["cost"] == 37000 and v["items"][0]["details"]["hotels"]
    assert len(v["suggested_addons"]) == 10

    gondola = next(a for a in v["suggested_addons"] if "Phase 1" in a["name"])
    trips.add_service(session, t, gondola["id"], day_position=2)                      # optional add-on
    cab = next(a for a in v["suggested_addons"] if a["name"].startswith("Transit cab for Aru"))
    trips.add_service(session, t, cab["id"], day_position=4, optional=False)          # included in price
    v = trips.trip_view(session, t)
    g = next(i for i in v["items"] if "Gondola" in i["description"])
    assert g["optional"] and g["quantity"] == 2 and g["amount"] == 1700
    c = next(i for i in v["items"] if "Aru" in i["description"])
    assert c["quantity"] == 1 and c["amount"] == 2500 and "1 vehicle" in c["details"]["quantity_note"]
    assert v["totals"]["cost"] == 37000 + 2500                                         # optional not counted
    assert v["totals"]["sell"] == round(39500 * 1.1 * 1.05, 2)
    assert v["totals"]["per_person"] == round(39500 * 1.1 * 1.05 / 2, 2)

    # combine: bring a Munnar day from the Kerala DMC package in after day 3
    munnar = [d for d in trips.library_days(session, q="Munnar") if d["title"] == "Munnar sightseeing"]
    trips.add_library_days(session, t, [munnar[0]["id"]], after_position=3)
    v = trips.trip_view(session, t)
    assert [d["title"] for d in v["days"]][2:5] == ["Day excursion to Sonamarg", "Munnar sightseeing",
                                                    "Srinagar to Pahalgam"]
    assert len({d["source_package_id"] for d in v["days"]}) == 2
    assert any("Kerala Classic" in x and "nothing in the costing covers them" in x for x in v["problems"])

    # group grows to 4: everything is repriced from the live rates
    trips.update_trip(session, t, {"adults": 4})
    v = trips.trip_view(session, t)
    assert v["items"][0]["amount"] == 4 * 15300
    assert next(i for i in v["items"] if "Gondola" in i["description"])["quantity"] == 4

    txt = trips.itinerary_text(session, t)
    assert "*Day 1 (10 Sep 2026): Arrival Srinagar*" in txt and "Package cost: INR" in txt and "Optional:" in txt


def test_negotiated_price_survives_repricing(session, extractor):
    _, pkg = _kashmir(session, extractor)
    t = trips.create_trip(session, {"title": "T", "start_date": "2026-09-10", "adults": 6})
    trips.apply_package(session, t, pkg.id, "Standard")
    zero = session.scalar(select(db.ServiceRate).where(db.ServiceRate.name.like("%Zero Point%")))
    item = trips.add_service(session, t, zero.id, day_position=3, optional=False)
    v = trips.trip_view(session, t)
    assert any("Price range" in w for i in v["items"] for w in i["details"].get("warnings", []))
    trips.update_item(session, t, item.id, {"unit_amount": 6000})
    trips.update_trip(session, t, {"adults": 8})
    it = next(i for i in trips.trip_view(session, t)["items"] if i["id"] == item.id)
    assert it["unit_amount"] == 6000 and it["quantity"] == 2 and it["amount"] == 12000   # 8 pax -> 2 cabs of 6


def test_hotel_stay_in_trip(session, extractor):
    _approve(session, "misty_hills_munnar_2026-27.pdf", extractor)
    hotel = session.scalar(select(db.Hotel).where(db.Hotel.name.like("Misty%")))
    t = trips.create_trip(session, {"title": "Munnar", "start_date": "2026-12-18", "adults": 3, "extra_beds": 1})
    trips.add_hotel(session, t, hotel.id, "Deluxe Room", "CP", nights=4, day_position=1)
    v = trips.trip_view(session, t)
    # 3 adults -> one room: double + extra adult; 2 regular nights (5000+1500) + 2 peak nights (7500+2000)
    assert v["items"][0]["amount"] == 2 * 6500 + 2 * 9500 and not v["problems"]


def test_catalog_views(session, extractor):
    _, pkg = _kashmir(session, extractor)
    full = catalog.package_full(session, pkg.id)
    assert full["price_grid"]["categories"] == ["Standard", "Deluxe", "Premium", "Luxury"]
    assert full["price_grid"]["rows"][0] == {"label": "2 pax", "values": {"Standard": 14800, "Deluxe": 17000,
                                                                          "Premium": 18500, "Luxury": 23000}}
    assert {c["city"] for c in full["hotels_by_city"]} == {"Srinagar", "Pahalgam"}
    assert len(full["addons"]) == 10
    assert len(catalog.places(session, destination="Kashmir")) == 19
    # a region search finds add-ons tagged with towns inside it (Gulmarg, Pahalgam, Sonamarg)
    assert len(catalog.services(session, destination="Kashmir")) == 10
    assert catalog.packages(session, destination="Pahalgam")[0]["from_price"] == 9200
    assert catalog.packages(session, on_date=date(2026, 12, 1)) == []
    sm = catalog.summary(session)
    assert sm["packages"] == 1 and sm["places"] == 19 and sm["hotels"] == 110


def test_api_trip_builder_and_api_key(session, extractor):
    api.set_extractor(extractor)
    c = signed_in_client(session)
    with open(sample(KASHMIR)[0] and f"samples/{KASHMIR}", "rb") as f:
        d = c.post("/api/documents", files={"file": (KASHMIR, f, "application/pdf")}).json()
    assert d["status"] == "needs_review"
    assert c.post(f"/api/documents/{d['id']}/approve", json={"rate_type": "net"}).status_code == 200
    pkgs = c.get("/api/catalog/packages").json()
    price = c.get(f"/api/catalog/packages/{pkgs[0]['id']}/price",
                  params={"category": "Deluxe", "adults": 6, "travel_date": "2026-09-01"}).json()
    assert price["total"] == 6 * 12500
    t = c.post("/api/trips", json={"title": "API trip", "adults": 2, "start_date": "2026-10-01",
                                   "package_id": pkgs[0]["id"], "category": "Luxury"}).json()
    assert t["totals"]["cost"] == 46000 and len(t["days"]) == 6
    t = c.post(f"/api/trips/{t['id']}/items", json={"kind": "custom", "description": "Airport flowers",
                                                     "unit_amount": 500}).json()
    assert t["totals"]["cost"] == 46500
    days = t["days"][::-1]
    t = c.put(f"/api/trips/{t['id']}/days", json=days).json()
    assert t["days"][0]["title"] == "Departure"
    assert "Airport flowers" not in c.get(f"/api/trips/{t['id']}/text").text   # prices show totals, not internals
    assert c.get("/api/library/days", params={"destination": "Kashmir"}).json()

    anon = TestClient(api.app)
    get_settings().api_key = "secret-123"
    try:
        assert anon.get("/api/catalog/summary").status_code == 401
        assert anon.get("/api/catalog/summary", headers={"X-API-Key": "wrong"}).status_code == 401
        assert anon.get("/api/catalog/summary", headers={"X-API-Key": "secret-123"}).status_code == 200
        assert c.get("/").status_code == 200                                   # signed in: the app loads
    finally:
        get_settings().api_key = None
