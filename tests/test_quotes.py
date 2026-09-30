"""Quotations (history, edit, copy, delete, share), hotel options and templates -- through the API."""
from app import api
from conftest import sample, signed_in_client

KASHMIR = "Off_Season_2026_Kashmir_package_5N_6D.pdf"
MISTY = "misty_hills_munnar_2026-27.pdf"


def _library(c, extractor, *names):
    api.set_extractor(extractor)
    for n in names:
        with open(f"samples/{n}", "rb") as f:
            d = c.post("/api/documents", files={"file": (n, f, "application/pdf")}).json()
        assert c.post(f"/api/documents/{d['id']}/approve", json={"rate_type": "net"}).status_code == 200


def test_hotel_options_price_each_option_and_follow_the_customers_choice(session, extractor):
    c = signed_in_client(session)
    _library(c, extractor, MISTY)
    h = c.get("/api/hotels").json()[0]
    t = c.post("/api/trips", json={"title": "Munnar honeymoon", "adults": 2, "start_date": "2026-11-10",
                                   "markup_pct": 0, "gst_pct": 0}).json()
    tid = t["id"]
    c.post(f"/api/trips/{tid}/items", json={"kind": "custom", "description": "Cab for 3 days", "unit_amount": 9000})
    for room, label in (("Deluxe Room", "Option A"), ("Premium Valley View", "Option B")):
        r = c.post(f"/api/trips/{tid}/items", json={"kind": "hotel", "hotel_id": h["id"], "room_type": room,
                                                     "meal_plan": "CP", "nights": 2, "option_label": label})
        assert r.status_code == 200, r.text
    t = r.json()
    opts = {o["label"]: o["sell"] for o in t["totals"]["options"]}
    assert set(opts) == {"Option A", "Option B"} and opts["Option A"] == 9000 + 2 * 5000
    assert opts["Option B"] > opts["Option A"]
    # no choice yet: headline = cheapest option, shown as a "from" price
    assert t["totals"]["sell"] == opts["Option A"] and t["totals"]["is_from_price"]
    text = c.get(f"/api/trips/{tid}/text").text
    assert "Hotel options" in text and "Option B" in text
    assert c.get(f"/api/trips/{tid}/pdf").status_code == 200
    t = c.patch(f"/api/trips/{tid}", json={"chosen_option": "Option B"}).json()
    assert t["totals"]["sell"] == opts["Option B"] and not t["totals"]["is_from_price"]
    assert t["totals"]["balance"] == opts["Option B"]


def test_package_with_every_category_as_options(session, extractor):
    c = signed_in_client(session)
    _library(c, extractor, KASHMIR)
    pk = c.get("/api/catalog/packages").json()[0]
    t = c.post("/api/trips", json={"title": "Kashmir family", "adults": 2, "start_date": "2026-09-05",
                                   "package_id": pk["id"], "all_categories": True, "markup_pct": 0, "gst_pct": 0}).json()
    labels = [o["label"] for o in t["totals"]["options"]]
    assert labels == pk["categories"] and len(t["days"]) == 6
    std = next(o for o in t["totals"]["options"] if o["label"] == "Standard")
    assert std["sell"] == 2 * 14800


def test_quotation_history_edit_copy_share_delete(session, extractor):
    c = signed_in_client(session)
    _library(c, extractor, KASHMIR)
    pk = c.get("/api/catalog/packages").json()[0]
    t = c.post("/api/trips", json={"title": "Kashmir for the Iyers", "customer_name": "R. Iyer", "adults": 2,
                                   "start_date": "2026-09-05", "package_id": pk["id"], "category": "Deluxe"}).json()
    tid = t["id"]
    q1 = c.post(f"/api/trips/{tid}/quotations", json={"note": "first price"}).json()
    assert q1["number"].startswith("TE-Q-") and q1["version"] == 1 and q1["status"] == "draft"
    assert c.get(f"/api/trips/{tid}").json()["status"] == "quoted"        # saving a quote moves the enquiry on
    # change the trip and save version 2; version 1 keeps what the customer was sent
    c.patch(f"/api/trips/{tid}", json={"markup_pct": 20})
    q2 = c.post(f"/api/trips/{tid}/quotations", json={}).json()
    assert q2["version"] == 2 and q2["total"] > q1["total"] and q2["number"] != q1["number"]
    assert c.get(f"/api/quotations/{q1['id']}").json()["total"] == q1["total"]
    lst = c.get("/api/quotations", params={"trip_id": tid}).json()
    assert [x["version"] for x in lst] == [2, 1]
    assert c.get("/api/quotations", params={"q": "Iyer"}).json()
    # PDF and client link come from the saved copy
    assert c.get(f"/api/quotations/{q1['id']}/pdf").status_code == 200
    q1 = c.post(f"/api/quotations/{q1['id']}/share", json={}).json()
    page = c.get(f"/q/{q1['share_token']}")
    assert page.status_code == 200 and "Kashmir for the Iyers" in page.text
    anon = api.app and __import__("fastapi.testclient", fromlist=["TestClient"]).TestClient(api.app)
    assert anon.get(f"/q/{q1['share_token']}").status_code == 200            # public, like /share links
    assert anon.get(f"/api/quotations/{q1['id']}").status_code in (401, 403)
    # edit version 1: its itinerary and costing go back into the trip, then save it back under the same number
    t = c.post(f"/api/quotations/{q1['id']}/restore").json()
    assert t["markup_pct"] == q1_markup(c, q1)
    c.post(f"/api/trips/{tid}/items", json={"kind": "custom", "description": "Shikara ride", "unit_amount": 1500})
    q1b = c.post(f"/api/quotations/{q1['id']}/update").json()
    assert q1b["number"] == q1["number"] and q1b["total"] > q1["total"]
    # status: sent -> accepted confirms the trip
    assert c.patch(f"/api/quotations/{q1['id']}", json={"status": "sent"}).json()["sent_at"]
    c.patch(f"/api/quotations/{q1['id']}", json={"status": "accepted"})
    assert c.get(f"/api/trips/{tid}").json()["status"] == "confirmed"
    # a new trip from a quotation, for someone else
    n = c.post(f"/api/quotations/{q2['id']}/new-trip", json={"title": "Kashmir for the Raos"}).json()
    assert n["id"] != tid and n["customer_name"] is None and len(n["days"]) == 6 and n["totals"]["cost"] > 0
    # delete a quotation: the trip stays; delete the trip: the quotations stay (history)
    assert c.delete(f"/api/quotations/{q2['id']}").status_code == 200
    assert c.get(f"/api/trips/{tid}").status_code == 200
    c.delete(f"/api/trips/{tid}")
    left = c.get(f"/api/quotations/{q1['id']}").json()
    assert left["trip_id"] is None and left["number"] == q1["number"]
    assert c.post(f"/api/quotations/{q1['id']}/update").status_code == 400
    assert c.post(f"/api/quotations/{q1['id']}/restore").status_code == 200    # makes a new trip from it


def q1_markup(c, q):
    return c.get(f"/api/quotations/{q['id']}").json()["snapshot"]["markup_pct"]


def test_templates(session, extractor):
    c = signed_in_client(session)
    _library(c, extractor, KASHMIR)
    pk = c.get("/api/catalog/packages").json()[0]
    t = c.post("/api/trips", json={"title": "Kashmir classic", "customer_name": "A", "adults": 2,
                                   "start_date": "2026-09-05", "package_id": pk["id"], "category": "Deluxe"}).json()
    tpl = c.post(f"/api/trips/{t['id']}/save-template", json={"title": "Kashmir 6 days - our plan"}).json()
    assert tpl["is_template"] and tpl["customer_name"] is None
    assert [x["title"] for x in c.get("/api/templates").json()] == ["Kashmir 6 days - our plan"]
    assert tpl["id"] not in [x["id"] for x in c.get("/api/trips").json()]          # not on the sales board
    assert c.post(f"/api/trips/{tpl['id']}/quotations", json={}).status_code == 400
    n = c.post("/api/trips", json={"template_id": tpl["id"], "title": "Kashmir for the Menons",
                                   "customer_name": "Menon", "start_date": "2026-10-01", "adults": 4}).json()
    assert not n["is_template"] and len(n["days"]) == 6 and n["customer_name"] == "Menon" and n["adults"] == 4
    assert n["totals"]["cost"] == 4 * 14000          # repriced for 4 adults (Deluxe 4 pax rate)
