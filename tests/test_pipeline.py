from datetime import date

from sqlalchemy import func, select

from app import db, pipeline, rates
from app.parsers import parse_file
from conftest import SAMPLES, sample


def test_parsers_read_every_sample():
    pdf = parse_file(SAMPLES / "misty_hills_munnar_2026-27.pdf")
    assert pdf.has_text_layer and "Premium Valley View" in pdf.text and "| Deluxe Room | CPAI |" in pdf.text
    xl = parse_file(SAMPLES / "siam_link_thailand_2026-27.xlsx")
    assert "Sheet: Transfers & Tours" in xl.text
    # merged season header repeated over both of its columns
    assert xl.text.count("High Season 20 Dec 2026 - 15 Jan 2027") == 2


def _approve(s, name, ex, **ov):
    doc, _ = pipeline.ingest(s, *sample(name), ex)
    assert doc.status == "needs_review", doc.error
    pipeline.approve(s, doc, ov or None, approved_by="test")
    return doc


def test_ingest_review_approve(session, extractor):
    doc, is_new = pipeline.ingest(session, *sample("misty_hills_munnar_2026-27.pdf"), extractor)
    assert is_new and doc.status == "needs_review"
    assert doc.normalized["stats"]["hotel_rates"] == 72
    assert session.scalar(select(func.count(db.HotelRate.id))) == 0       # nothing live before approval
    stats = pipeline.approve(session, doc, approved_by="Dhineshwar")
    assert stats["hotel_rates"] == 72 and doc.status == "approved"
    assert session.scalar(select(func.count(db.Hotel.id))) == 1
    assert session.scalar(select(func.count(db.RoomType.id))) == 3


def test_same_file_twice_is_not_reingested(session, extractor):
    d1, new1 = pipeline.ingest(session, *sample("misty_hills_munnar_2026-27.pdf"), extractor)
    d2, new2 = pipeline.ingest(session, *sample("misty_hills_munnar_2026-27.pdf"), extractor)
    assert new1 and not new2 and d1.id == d2.id


def test_stay_crossing_seasons_prices_each_night(session, extractor):
    _approve(session, "misty_hills_munnar_2026-27.pdf", extractor)
    hotel = session.scalar(select(db.Hotel))
    # 18,19 Dec regular (5000) ; 20,21 Dec peak (7500)
    q = rates.price_hotel_stay(session, hotel.id, "Deluxe Room", "CP", date(2026, 12, 18), date(2026, 12, 22))
    assert q["ok"], q["errors"]
    assert [n["total"] for n in q["nights"]] == [5000, 5000, 7500, 7500]
    assert q["cost"] == 25000 and q["currency"] == "INR" and q["rates_are_net"] is True
    assert q["taxes_included"] is False


def test_family_room_with_gala_dinner_and_markup(session, extractor):
    _approve(session, "misty_hills_munnar_2026-27.pdf", extractor)
    hotel = session.scalar(select(db.Hotel))
    q = rates.price_hotel_stay(session, hotel.id, "Premium Valley View", "MAP", date(2026, 12, 30), date(2027, 1, 1),
                               rooms=[{"adults": 3, "children_with_bed": 1}], markup_pct=10)
    assert q["ok"], q["errors"]
    # per night: double 11900 + extra adult 3100 + CWB 2500 = 17500 x 2 nights
    assert [n["total"] for n in q["nights"]] == [17500, 17500]
    # gala dinner: 3 adults x 3500 + 1 child x 1750
    assert sum(s["amount"] for s in q["supplements"]) == 3 * 3500 + 1750
    assert q["cost"] == 35000 + 12250
    assert q["sell"] == round(47250 * 1.1, 2)


def test_blackout_only_hits_its_room_type(session, extractor):
    _approve(session, "misty_hills_munnar_2026-27.pdf", extractor)
    hotel = session.scalar(select(db.Hotel))
    villa = rates.price_hotel_stay(session, hotel.id, "Pool Villa", "MAP", date(2026, 12, 23), date(2026, 12, 26))
    assert not villa["ok"] and any("blackout" in e for e in villa["errors"])
    deluxe = rates.price_hotel_stay(session, hotel.id, "Deluxe Room", "MAP", date(2026, 12, 23), date(2026, 12, 26))
    assert deluxe["ok"]


def test_no_rate_outside_validity(session, extractor):
    _approve(session, "misty_hills_munnar_2026-27.pdf", extractor)
    hotel = session.scalar(select(db.Hotel))
    q = rates.price_hotel_stay(session, hotel.id, "Deluxe Room", "CP", date(2027, 3, 30), date(2027, 4, 2))
    assert not q["ok"]
    assert any("2027-04-01" in e for e in q["errors"])


def test_revised_sheet_supersedes_only_changed_period(session, extractor):
    _approve(session, "misty_hills_munnar_2026-27.pdf", extractor)
    _approve(session, "misty_hills_munnar_2026-27_revised.pdf", extractor)
    assert session.scalar(select(func.count(db.Hotel.id))) == 1              # same hotel, not duplicated
    hotel = session.scalar(select(db.Hotel))
    q = rates.price_hotel_stay(session, hotel.id, "Deluxe Room", "CP", date(2026, 12, 19), date(2026, 12, 21))
    assert [n["total"] for n in q["nights"]] == [5000, 8000]                 # regular unchanged, peak revised
    live = rates.search_hotel_rates(session, "Munnar", on_date=date(2026, 12, 25), meal_plan="CP")
    deluxe = [r for r in live if r["room_type"] == "Deluxe Room"]
    assert len(deluxe) == 1 and deluxe[0]["amount"] == 8000
    # only the two changed peak rates are replaced; the other 70 rates, 2 gala dinners and 1 blackout are
    # recognised as unchanged and not duplicated. The old peak rows are kept as history and the new ones point back to them.
    assert session.scalar(select(func.count(db.HotelRate.id)).where(db.HotelRate.status == "superseded")) == 2
    assert session.scalar(select(func.count(db.HotelRate.id))) == 74
    new = session.scalar(select(db.HotelRate).where(db.HotelRate.amount == 8000))
    old = session.get(db.HotelRate, new.previous_rate_id)
    assert old.amount == 7500 and old.status == "superseded" and float(new.change_pct) == 6.7
    assert session.scalar(select(func.count(db.HotelSurcharge.id))) == 3


def test_partial_overlap_trims_and_splits(session, extractor):
    _approve(session, "misty_hills_munnar_2026-27.pdf", extractor)
    # a new sheet covering only 1-15 Nov for Deluxe CP double
    doc, _ = pipeline.intake(session, "nov_special.txt", b"special", None)
    doc.extraction = {
        "document_type": "hotel_rate_sheet", "supplier": {"name": "Misty Hills Resort and Spa"},
        "currency": "INR", "rate_type": "net", "taxes": "excluded",
        "hotels": [{"name": "Misty Hills Resort & Spa", "city": "Munnar", "rates": [
            {"room_type": "Deluxe Room", "meal_plan": "CP", "occupancy": "Double", "amount": 4200,
             "valid_from": "2026-11-01", "valid_to": "2026-11-15", "rate_type": "net", "taxes": "excluded"}]}]}
    doc.status = "needs_review"
    session.commit()
    stats = pipeline.approve(session, doc)
    assert stats["older_rates_adjusted"] == 1
    hotel = session.scalar(select(db.Hotel))
    q = rates.price_hotel_stay(session, hotel.id, "Deluxe Room", "CP", date(2026, 10, 31), date(2026, 11, 17))
    totals = {n["date"]: n["total"] for n in q["nights"]}
    assert totals["2026-10-31"] == 5000 and totals["2026-11-01"] == 4200
    assert totals["2026-11-15"] == 4200 and totals["2026-11-16"] == 5000


def test_dmc_package_and_services(session, extractor):
    _approve(session, "misty_hills_munnar_2026-27.pdf", extractor)
    _approve(session, "green_valley_kerala_classic.pdf", extractor)
    pk = rates.search_packages(session, "Munnar", date(2026, 11, 10))
    assert len(pk) == 1 and pk[0]["nights"] == 4 and len(pk[0]["itinerary"]) == 5
    std2 = [p for p in pk[0]["prices"] if p["category"] == "Standard" and p["pax_min"] == 2 and p["occupancy"] == "double"]
    assert std2[0]["amount"] == 18500
    # package not sold over New Year
    assert rates.search_packages(session, "Munnar", date(2026, 12, 28)) == []
    # the package's Deluxe Munnar hotel is linked to the hotel we already hold rates for
    assert any(h["hotel_id"] for h in pk[0]["hotels"] if h["hotel"] == "Misty Hills Resort & Spa")
    svc = rates.search_services(session, "Kerala", "transfer", "cochin airport munnar", date(2026, 11, 10))
    assert {s["vehicle_type"]: s["amount"] for s in svc} == {"Sedan (Dzire)": 3800, "Innova Crysta": 5200,
                                                              "Tempo Traveller 12 seater": 7500}


def test_excel_weekend_rates_and_foreign_currency(session, extractor):
    _approve(session, "siam_link_thailand_2026-27.xlsx", extractor)
    hotel = session.scalar(select(db.Hotel).where(db.Hotel.name == "Patong Beach Hotel"))
    # Thu 19 Nov, Fri 20, Sat 21 (weekend), Sun 22
    q = rates.price_hotel_stay(session, hotel.id, "Superior", "CP", date(2026, 11, 19), date(2026, 11, 23))
    assert [n["total"] for n in q["nights"]] == [2200, 2600, 2600, 2200]
    assert q["currency"] == "THB" and q["taxes_included"] is True
    tours = rates.search_services(session, "Phuket", "sightseeing", on_date=date(2027, 5, 1))
    assert {(t["basis"], t["amount"]) for t in tours} == {("per_adult", 1900), ("per_child", 1400)}


def test_errors_block_approval(session, extractor):
    doc, _ = pipeline.ingest(session, *sample("misty_hills_munnar_2026-27.pdf"), extractor)
    x = dict(doc.extraction)
    x["hotels"][0]["rates"][0]["meal_plan"] = "???"
    pipeline.update_extraction(session, doc, x)
    try:
        pipeline.approve(session, doc)
        raise AssertionError("should not approve")
    except pipeline.PipelineError as e:
        assert "must be fixed" in str(e)
    assert session.scalar(select(func.count(db.HotelRate.id))) == 0


def test_expiring_alert(session, extractor):
    _approve(session, "misty_hills_munnar_2026-27.pdf", extractor)
    soon = rates.expiring_soon(session, within_days=30, today=date(2027, 3, 10))
    assert soon and soon[0]["name"] == "Misty Hills Resort & Spa" and soon[0]["last_valid_date"] == "2027-03-31"
    assert rates.expiring_soon(session, within_days=30, today=date(2026, 10, 1)) == []


def test_failed_extraction_is_recorded(session, tmp_path):
    from app.extractor import FixtureExtractor
    doc, _ = pipeline.ingest(session, *sample("misty_hills_munnar_2026-27.pdf"), FixtureExtractor(tmp_path))
    assert doc.status == "failed" and "No fixture" in doc.error
