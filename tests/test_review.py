"""Review before saving: edit what was read, type rates by hand, cancel, undo an approval, correct the library."""
import copy

from sqlalchemy import func, select

from app import api, db, pipeline
from conftest import sample, signed_in_client

MISTY = "misty_hills_munnar_2026-27.pdf"


def _upload(c, extractor, name=MISTY):
    api.set_extractor(extractor)
    with open(f"samples/{name}", "rb") as f:
        return c.post("/api/documents", files={"file": (name, f, "application/pdf")}).json()


def test_nothing_is_saved_until_approved_and_edits_are_checked_again(session, extractor):
    c = signed_in_client(session)
    d = _upload(c, extractor)
    doc = c.get(f"/api/documents/{d['id']}").json()
    assert doc["status"] == "needs_review" and doc["changes"]["summary"]["new"] == 72
    assert session.scalar(select(func.count(db.HotelRate.id))) == 0
    # edit a rate and delete another, as the review screen does
    x = copy.deepcopy(doc["extraction"])
    x["hotels"][0]["rates"][0]["amount"] = 4999
    del x["hotels"][0]["rates"][1]
    doc = c.put(f"/api/documents/{d['id']}/extraction", json=x).json()
    assert doc["normalized"]["stats"]["hotel_rates"] < 72
    assert doc["changes"]["summary"]["new"] == doc["normalized"]["stats"]["hotel_rates"], [i for i in doc["issues"] if i["level"] == "error"]
    # a mistake the checks catch blocks approval
    x["hotels"][0]["rates"][0]["amount"] = -5
    doc = c.put(f"/api/documents/{d['id']}/extraction", json=x).json()
    assert any(i["level"] in ("error", "warning") for i in doc["issues"])
    # invalid shapes are refused with a message, not a crash
    assert c.put(f"/api/documents/{d['id']}/extraction", json={"document_type": "nonsense"}).status_code == 422


def test_cancel_discards_the_upload(session, extractor):
    c = signed_in_client(session)
    d = _upload(c, extractor)
    assert c.delete(f"/api/documents/{d['id']}").status_code == 200
    assert c.get(f"/api/documents/{d['id']}").status_code == 404
    assert session.scalar(select(func.count(db.HotelRate.id))) == 0
    d = _upload(c, extractor)                                            # the same file can be uploaded again
    assert d["status"] == "needs_review" and not d["duplicate"]


def test_manual_entry_goes_through_the_same_checks(session):
    c = signed_in_client(session)
    doc = c.post("/api/documents/manual", json={"supplier": "Houseboat Hari", "document_type": "hotel_rate_sheet"}).json()
    assert doc["status"] == "needs_review" and doc["filename"].startswith("Manual entry - Houseboat Hari")
    x = doc["extraction"]
    x["currency"], x["rate_type"], x["taxes"] = "INR", "net", "included"
    x["hotels"] = [{"name": "Hari's Premium Houseboat", "city": "Alleppey", "property_type": "houseboat",
                    "rates": [{"room_type": "2 bedroom", "meal_plan": "AP", "occupancy": "double", "amount": 9500,
                               "valid_from": "2026-10-01", "valid_to": "2027-03-31"}]}]
    doc = c.put(f"/api/documents/{doc['id']}/extraction", json=x).json()
    assert not [i for i in doc["issues"] if i["level"] == "error"], doc["issues"]
    assert c.post(f"/api/documents/{doc['id']}/approve", json={}).status_code == 200
    r = c.get("/api/rates/hotels", params={"destination": "Alleppey", "on_date": "2026-12-01", "meal_plan": "AP"}).json()
    assert r[0]["amount"] == 9500
    assert c.post(f"/api/documents/{doc['id']}/reprocess").status_code == 409


def test_undo_an_approval_restores_the_earlier_rates_exactly(session, extractor):
    c = signed_in_client(session)
    d1 = _upload(c, extractor)
    c.post(f"/api/documents/{d1['id']}/approve", json={})
    before = {(r.id, r.valid_from, r.valid_to, r.status, float(r.amount)) for r in session.scalars(select(db.HotelRate))}
    d2 = _upload(c, extractor, "misty_hills_munnar_2026-27_revised.pdf")
    c.post(f"/api/documents/{d2['id']}/approve", json={})
    assert c.post(f"/api/documents/{d1['id']}/undo").status_code == 409     # a later sheet built on it
    r = c.post(f"/api/documents/{d2['id']}/undo")
    assert r.status_code == 200, r.text
    session.expire_all()
    after = {(r.id, r.valid_from, r.valid_to, r.status, float(r.amount)) for r in session.scalars(select(db.HotelRate))}
    assert after == before
    assert c.get(f"/api/documents/{d2['id']}").json()["status"] == "needs_review"


def test_undo_is_refused_while_trips_use_the_package(session, extractor):
    c = signed_in_client(session)
    d = _upload(c, extractor, "Off_Season_2026_Kashmir_package_5N_6D.pdf")
    c.post(f"/api/documents/{d['id']}/approve", json={"rate_type": "net"})
    pk = c.get("/api/catalog/packages").json()[0]
    c.post("/api/trips", json={"title": "x", "adults": 2, "start_date": "2026-09-05", "package_id": pk["id"]})
    assert "Trips use packages" in c.post(f"/api/documents/{d['id']}/undo").json()["detail"]


def test_correct_or_retire_a_live_rate(session, extractor):
    c = signed_in_client(session)
    d = _upload(c, extractor)
    c.post(f"/api/documents/{d['id']}/approve", json={})
    h = c.get("/api/catalog/hotels").json()[0]
    rate = c.get(f"/api/catalog/hotels/{h['id']}").json()["rates"][0]
    r = c.patch(f"/api/catalog/hotel-rates/{rate['id']}", json={"amount": 5100}).json()
    assert r["amount"] == 5100 and "Edited by" in r["notes"]
    assert c.patch(f"/api/catalog/hotel-rates/{rate['id']}", json={"amount": "abc"}).status_code == 400
    assert c.patch(f"/api/catalog/hotel-rates/{rate['id']}", json={"valid_from": "2030-01-01"}).status_code == 400
    assert c.patch(f"/api/catalog/hotel-rates/{rate['id']}", json={"status": "retired"}).json()["status"] == "superseded"
    assert rate["id"] not in [x["id"] for x in c.get(f"/api/catalog/hotels/{h['id']}").json()["rates"]]


def test_supplier_directory_edit_and_merge(session, extractor):
    c = signed_in_client(session)
    for n in (MISTY, "green_valley_kerala_classic.pdf"):
        d = _upload(c, extractor, n)
        c.post(f"/api/documents/{d['id']}/approve", json={"rate_type": "net"})
    sups = c.get("/api/catalog/suppliers").json()
    misty = next(x for x in sups if "Misty" in x["name"])
    det = c.get(f"/api/catalog/suppliers/{misty['id']}").json()
    assert det["documents"] and det["hotels"] and det["rates_valid_until"]
    # a duplicate record for the same company, e.g. from a manual entry with another spelling
    dup = c.post("/api/documents/manual", json={"supplier": "Misty Hills Resorts"}).json()
    session.add(db.Supplier(name="Misty Hills Resorts", name_key="misty hills resorts", phone=det["phone"]))
    session.commit()
    det = c.get(f"/api/catalog/suppliers/{misty['id']}").json()
    other = det["possible_duplicates"][0]
    assert "similar name" in other["why"]
    assert c.patch(f"/api/catalog/suppliers/{misty['id']}", json={"contact_person": "Mr. Joseph"}).json()["contact_person"] == "Mr. Joseph"
    r = c.post(f"/api/catalog/suppliers/{misty['id']}/merge", json={"merge_id": other["id"]}).json()
    assert r["kept"] == misty["id"]
    assert other["id"] not in [x["id"] for x in c.get("/api/catalog/suppliers").json()]
    assert c.post(f"/api/catalog/suppliers/{misty['id']}/merge", json={"merge_id": misty["id"]}).status_code == 400
