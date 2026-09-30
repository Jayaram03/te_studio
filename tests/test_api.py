from fastapi.testclient import TestClient

from app import api, db
from conftest import signed_in_client, SAMPLES


def test_api_upload_review_approve_quote(session, extractor):
    api.set_extractor(extractor)
    c = signed_in_client(session)
    assert "Travel Episodes" in c.get("/").text
    with open(SAMPLES / "misty_hills_munnar_2026-27.pdf", "rb") as f:
        r = c.post("/api/documents", files={"file": ("misty_hills_munnar_2026-27.pdf", f, "application/pdf")},
                   data={"supplier": "Misty Hills"})
    assert r.status_code == 202, r.text
    doc_id = r.json()["id"]
    d = c.get(f"/api/documents/{doc_id}").json()          # background task has run inside TestClient
    assert d["status"] == "needs_review" and d["stats"]["hotel_rates"] == 72

    r = c.post(f"/api/documents/{doc_id}/approve", json={"approved_by": "Rakesh"})
    assert r.status_code == 200 and r.json()["loaded"]["hotel_rates"] == 72
    assert c.post(f"/api/documents/{doc_id}/approve", json={}).status_code == 409

    found = c.get("/api/rates/hotels", params={"destination": "munnar", "on_date": "2026-11-05",
                                               "meal_plan": "MAP", "max_amount": 8000}).json()
    assert [(x["room_type"], x["amount"]) for x in found] == [("Deluxe Room", 7400.0)]

    hotels = c.get("/api/hotels").json()
    q = c.post("/api/quote/hotel-stay", json={"hotel_id": hotels[0]["id"], "room_type": "Deluxe Room",
                                              "meal_plan": "CP", "check_in": "2026-11-05", "check_out": "2026-11-07",
                                              "rooms": [{"adults": 2}], "markup_pct": 12}).json()
    assert q["cost"] == 10000 and q["sell"] == 11200

    with open(SAMPLES / "misty_hills_munnar_2026-27.pdf", "rb") as f:
        dup = c.post("/api/documents", files={"file": ("again.pdf", f, "application/pdf")}).json()
    assert dup["duplicate"] and dup["id"] == doc_id


def test_api_rejects_unsupported(session, extractor):
    api.set_extractor(extractor)
    c = signed_in_client(session)
    r = c.post("/api/documents", files={"file": ("notes.docx", b"x", "application/octet-stream")})
    assert r.status_code == 400 and "damaged" in r.json()["detail"]
    r = c.post("/api/documents", files={"file": ("tool.exe", b"MZ\x90\x00", "application/octet-stream")})
    assert r.status_code == 400 and "Unsupported" in r.json()["detail"]
