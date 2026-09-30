"""Re-uploads: the same supplier package / hotel / add-on sent again with new prices or new dates."""
import copy
import json
from datetime import date

from sqlalchemy import func, select

from app import catalog, db, history, pipeline, trips
from app.extractor import FixtureExtractor
from app.loader import core_title
from conftest import FIXTURES, SAMPLES, sample

KASHMIR = "Off_Season_2026_Kashmir_package_5N_6D"


def _base():
    return json.loads((FIXTURES / f"{KASHMIR}.json").read_text())


def _upload(s, tmp_path, stem, extraction, **ov):
    """Upload the Kashmir PDF under another name (a different file) with the given extraction."""
    (tmp_path / f"{stem}.json").write_text(json.dumps(extraction))
    data = (SAMPLES / f"{KASHMIR}.pdf").read_bytes() + f"\n% {stem}\n".encode()
    doc, _ = pipeline.ingest(s, f"{stem}.pdf", data, FixtureExtractor(tmp_path))
    assert doc.status == "needs_review", doc.error
    return doc


def _approve_original(s, extractor):
    doc, _ = pipeline.ingest(s, *sample(f"{KASHMIR}.pdf"), extractor)
    pipeline.approve(s, doc, {"rate_type": "net"})
    return s.scalar(select(db.Package))


def _revised(pct=5):
    x = _base()
    p = x["packages"][0]
    p["title"] = "Kashmir Off Season 5N/6D (Revised rates)"
    for q in p["prices"]:
        if q["category"] == "Deluxe":
            q["amount"] = round(q["amount"] * (1 + pct / 100))
    for sv in x["services"]:
        if sv["name"] == "Gulmarg Gondola ride - Phase 1":
            sv["amount"] = 950
    return x


def test_core_title_ignores_season_and_year_words():
    assert core_title("Kashmir Off Season 5N/6D") == core_title("Kashmir Summer Special 2027 - 5N 6D (Revised)") == "kashmir"
    assert core_title("Kashmir with Gurez 5N/6D") != core_title("Kashmir Off Season 5N/6D")
    assert core_title("Anything", base_name="Kerala Classic") == "kerala classic"


def test_revised_package_becomes_version_2_and_replaces_version_1(session, extractor, tmp_path):
    v1 = _approve_original(session, extractor)
    doc = _upload(session, tmp_path, "Kashmir_revised_rates", _revised(), )
    # the review screen already knows what approving will do -- and nothing was written yet
    ch = doc.changes
    assert ch and not ch["applied"]
    pk = ch["packages"][0]
    assert pk["matched"] and pk["version"] == 2 and pk["older_versions"][0]["action"] == "replaced"
    assert pk["prices"]["counts"]["up"] == 9 and pk["prices"]["counts"]["same"] == 27     # the 9 Deluxe cells
    assert pk["prices"]["avg_change_pct"] == 5.0
    assert session.scalar(select(func.count(db.Package.id))) == 1

    pipeline.approve(session, doc, {"rate_type": "net"})
    v2 = session.scalar(select(db.Package).where(db.Package.version == 2))
    session.refresh(v1)
    assert v1.status == "superseded" and v1.replaced_by_document_id == doc.id
    assert v2.family_id == v1.id and v2.previous_version_id == v1.id and v2.status == "active"
    # one card in the catalog, not two
    cards = catalog.packages(session, q="Kashmir")
    assert len(cards) == 1 and cards[0]["id"] == v2.id and cards[0]["version"] == 2 and cards[0]["versions"] == 2
    # hotels named in both versions are not duplicated
    assert len(catalog.hotels(session)) == 110
    # the gondola add-on changed price: new row linked to the old one; unchanged add-ons are not re-added
    gondola = session.scalars(select(db.ServiceRate).where(db.ServiceRate.name.like("%Phase 1%"))).all()
    assert sorted(float(g.amount) for g in gondola) == [850, 950]
    new_g = next(g for g in gondola if g.amount == 950)
    assert new_g.previous_rate_id and float(new_g.change_pct) == 11.8
    assert session.scalar(select(func.count(db.ServiceRate.id)).where(db.ServiceRate.status == "active")) == 10
    # the package page still offers all ten add-ons, whichever version they were first read from
    assert len(catalog.package_full(session, v2.id)["addons"]) == 10
    # version history with the price comparison
    h = history.package_versions(session, v2.id)
    assert [v["version"] for v in h["versions"]] == [2, 1] and h["versions"][1]["state"] == "replaced"
    assert h["comparison"]["counts"]["up"] == 9


def test_same_content_again_changes_nothing(session, extractor, tmp_path):
    _approve_original(session, extractor)
    doc = _upload(session, tmp_path, "Kashmir_same_again", _base())
    s = doc.changes["summary"]
    assert s["new"] == 0 and s["up"] == 0 and s["down"] == 0 and s["same"] == 10      # the ten add-ons
    assert doc.changes["packages"][0]["prices"]["counts"]["same"] == 36
    before = session.scalar(select(func.count(db.ServiceRate.id)))
    pipeline.approve(session, doc, {"rate_type": "net"})
    assert session.scalar(select(func.count(db.ServiceRate.id))) == before


def test_other_season_edition_stays_live_next_to_the_first(session, extractor, tmp_path):
    v1 = _approve_original(session, extractor)
    x = _base()
    p = x["packages"][0]
    p["title"], p["valid_from"], p["valid_to"] = "Kashmir Winter 5N/6D", "Nov 2026", "Mar 2027"
    x["validity"] = {"start": "Nov 2026", "end": "Mar 2027"}
    for q in p["prices"]:
        q["amount"] += 2000
    doc = _upload(session, tmp_path, "Kashmir_winter", x)
    assert doc.changes["packages"][0]["older_versions"][0]["action"] == "kept (other dates)"
    pipeline.approve(session, doc, {"rate_type": "net"})
    session.refresh(v1)
    both = session.scalars(select(db.Package).where(db.Package.status == "active")).all()
    assert len(both) == 2 and v1.status == "active" and {b.family_id for b in both} == {v1.id}
    # for a travel date only the edition valid then is offered
    assert [c["title"] for c in catalog.packages(session, on_date=date(2026, 12, 10))] == ["Kashmir Winter 5N/6D"]
    assert [c["title"] for c in catalog.packages(session, on_date=date(2026, 9, 10))] == ["Kashmir Off Season 5N/6D"]
    # without a date: one card for the family, showing the other edition
    cards = catalog.packages(session)
    assert len(cards) == 1 and len(cards[0]["other_editions"]) == 1


def test_reviewer_can_keep_a_look_alike_as_a_separate_package(session, extractor, tmp_path):
    _approve_original(session, extractor)
    doc = _upload(session, tmp_path, "Kashmir_other", _revised())
    pipeline.approve(session, doc, {"rate_type": "net", "package_links": {"0": "new"}})
    assert session.scalar(select(func.count(db.Package.id)).where(db.Package.status == "active")) == 2
    assert session.scalar(select(func.count(func.distinct(db.Package.family_id)))) == 2


def test_trip_on_an_old_version_is_told_and_can_move_to_the_new_one(session, extractor, tmp_path):
    v1 = _approve_original(session, extractor)
    t = trips.create_trip(session, {"title": "Iyer family", "start_date": "2026-09-10", "adults": 2})
    trips.apply_package(session, t, v1.id, "Deluxe")
    old_price = trips.totals(t)["cost"]
    doc = _upload(session, tmp_path, "Kashmir_revised_rates", _revised(10))
    pipeline.approve(session, doc, {"rate_type": "net"})
    v = trips.trip_view(session, t)
    assert v["newer_versions"] and v["newer_versions"][0]["to_version"] == 2
    assert any("newer version" in p for p in v["problems"])
    trips.upgrade_package(session, t, v1.id, v["newer_versions"][0]["to_id"])
    v = trips.trip_view(session, t)
    assert not v["newer_versions"] and v["totals"]["cost"] == round(old_price * 1.1)
    assert v["days"] and all(d["source_package_id"] != v1.id for d in v["days"])


def test_hotel_rate_history_series(session, extractor):
    for name in ("misty_hills_munnar_2026-27.pdf", "misty_hills_munnar_2026-27_revised.pdf"):
        doc, _ = pipeline.ingest(session, *sample(name), extractor)
        pipeline.approve(session, doc)
    hotel = session.scalar(select(db.Hotel))
    h = history.hotel_history(session, hotel.id)
    peak = next(sr for sr in h["series"] if sr["room_type"] == "Deluxe Room" and sr["meal_plan"] == "CP"
                and sr["occupancy"] == "double")
    amounts = [(p["amount"], p["state"]) for p in peak["points"]]
    assert (7500.0, "replaced") in amounts
    assert (8000.0, "current") in amounts or (8000.0, "upcoming") in amounts
    assert h["changes"][0]["pct"] in (6.7, 6.1)
    feed = history.recent_changes(session, days=30)
    assert {c["change"] for c in feed["items"]} == {"up"} and len(feed["items"]) == 2
