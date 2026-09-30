"""Fill a database with the sample documents and a handful of trips at every stage (for demos / screenshots).

    DATABASE_URL=... python scripts/demo_seed.py
"""
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from sqlalchemy import select  # noqa: E402

from app import db, pipeline, trips  # noqa: E402
from app.extractor import FixtureExtractor  # noqa: E402

db.init_db(drop="--reset" in sys.argv)
s = db.SessionLocal()
ex = FixtureExtractor(ROOT / "tests" / "fixtures")
for f, ov in (("Off_Season_2026_Kashmir_package_5N_6D.pdf", {"rate_type": "net"}), ("misty_hills_munnar_2026-27.pdf", None),
              ("green_valley_kerala_classic.pdf", None), ("siam_link_thailand_2026-27.xlsx", None)):
    doc, new = pipeline.ingest(s, f, (ROOT / "samples" / f).read_bytes(), ex)
    if doc.status == "needs_review" and f != "siam_link_thailand_2026-27.xlsx":   # leave one to review
        pipeline.approve(s, doc, ov, approved_by="Rakesh")

kashmir = s.scalar(select(db.Package).where(db.Package.title.like("Kashmir%")))
kerala = s.scalar(select(db.Package).where(db.Package.title.like("Kerala%")))
today = date.today()
demo = [
    ("Kashmir for the Iyer family", "Lakshmi Iyer", "+91 98400 11111", "Instagram", "Rakesh", "quoted", kashmir, "Premium", 4, 1, -2, 20),
    ("Honeymoon in Kashmir", "Arjun & Divya", "+91 98400 22222", "Referral", "Dhineshwar", "confirmed", kashmir, "Luxury", 2, 0, None, 12),
    ("Agilysis team offsite - Kerala", "Agilysis HR", "+91 98400 33333", "Agilysis", "Jayaram", "enquiry", kerala, "Deluxe", 12, 0, 0, 40),
    ("Kerala backwaters for the Menons", "Ravi Menon", "+91 98400 44444", "WhatsApp", "Rakesh", "enquiry", kerala, "Standard", 2, 0, 1, 30),
    ("Srinagar weekend", "Farhan", "+91 98400 55555", "Instagram", "Dhineshwar", "lost", kashmir, "Standard", 2, 0, None, 15),
    ("Kerala Classic - Sharma family", "Neha Sharma", "+91 98400 66666", "Google", "Jayaram", "completed", kerala, "Deluxe", 4, 0, None, -20),
]
if not s.scalar(select(db.Trip)):
    for title, cust, phone, src, owner, status, pkg, cat, adults, cwb, fu, start in demo:
        start_d = today + timedelta(days=start)
        if pkg.valid_from and not (pkg.valid_from <= start_d <= pkg.valid_to):
            start_d = pkg.valid_from + timedelta(days=10)
        t = trips.create_trip(s, {"title": title, "customer_name": cust, "customer_phone": phone, "lead_source": src,
                                  "assigned_to": owner, "start_date": start_d.isoformat(), "adults": adults,
                                  "children_with_bed": cwb, "markup_pct": 10, "gst_pct": 5,
                                  "follow_up_date": (today + timedelta(days=fu)).isoformat() if fu is not None else None})
        trips.apply_package(s, t, pkg.id, cat)
        trips.update_trip(s, t, {"status": status, **({"lost_reason": "Went with a cheaper option"} if status == "lost" else {})})
        if status in ("confirmed", "completed"):
            tot = trips.totals(t)
            trips.add_payment(s, t, round(tot["sell"] / 2), mode="UPI")
            if status == "completed":
                trips.add_payment(s, t, tot["sell"] - round(tot["sell"] / 2), mode="Bank transfer")
    first = s.scalar(select(db.Trip).order_by(db.Trip.id))
    trips.add_note(s, first, "Sent Premium quote on WhatsApp; they are comparing with a Kerala option.", "Rakesh")
    g = s.scalar(select(db.ServiceRate).where(db.ServiceRate.name.like("%Phase 1%")))
    trips.add_service(s, first, g.id, day_position=2)
if not s.scalar(select(db.AIUsage)):
    import random
    from datetime import datetime
    random.seed(7)
    docs = [d.id for d in s.scalars(select(db.SourceDocument)).all()]
    for back in range(28, -1, -1):
        for _ in range(random.choice([0, 0, 1, 1, 2, 3])):
            tin, tout = random.randint(6000, 42000), random.randint(2500, 16000)
            s.add(db.AIUsage(at=datetime.utcnow() - timedelta(days=back, hours=random.randint(0, 8)), provider="anthropic",
                             model="claude-sonnet-5-5", purpose="extraction", document_id=random.choice(docs),
                             input_tokens=tin, output_tokens=tout, duration_ms=random.randint(18000, 95000), ok=random.random() > .05))
    s.commit()

# ---- re-uploads: a revised hotel sheet and a revised Kashmir package (version 2, Deluxe +6%)
import copy, json, tempfile
from app import auth, quotes
if not s.scalar(select(db.SourceDocument).where(db.SourceDocument.filename.like("%revised%"))):
    doc, _ = pipeline.ingest(s, "misty_hills_munnar_2026-27_revised.pdf",
                             (ROOT / "samples" / "misty_hills_munnar_2026-27_revised.pdf").read_bytes(), ex)
    pipeline.approve(s, doc, None, approved_by="Jayaram")
    x = json.loads((ROOT / "tests" / "fixtures" / "Off_Season_2026_Kashmir_package_5N_6D.json").read_text())
    x["packages"][0]["title"] = "Kashmir Off Season 5N/6D (Revised rates)"
    for q in x["packages"][0]["prices"]:
        if q["category"] in ("Deluxe", "Premium"):
            q["amount"] = round(q["amount"] * 1.06 / 10) * 10
    for sv in x["services"]:
        if "Phase 1" in sv["name"]:
            sv["amount"] = 950
    tmp = Path(tempfile.mkdtemp())
    (tmp / "Kashmir_Off_Season_2026_revised.json").write_text(json.dumps(x))
    data = (ROOT / "samples" / "Off_Season_2026_Kashmir_package_5N_6D.pdf").read_bytes() + b"\n% revised\n"
    doc, _ = pipeline.ingest(s, "Kashmir_Off_Season_2026_revised.pdf", data, FixtureExtractor(tmp))
    pipeline.approve(s, doc, {"rate_type": "net"}, approved_by="Rakesh")
    # a Word rate sheet waiting for review
    import docx, io
    d = docx.Document(); d.add_heading("Houseboat Hari - Alleppey tariff 2026-27", 1)
    d.add_paragraph("Valid 1 Oct 2026 to 31 Mar 2027. Net rates in INR incl. GST.")
    tb = d.add_table(rows=3, cols=3)
    for r, row in enumerate([["Boat", "Full board (AP)", "Rate per night"], ["1 bedroom premium", "AP", "8500"], ["2 bedroom premium", "AP", "12500"]]):
        for c, v in enumerate(row):
            tb.cell(r, c).text = v
    buf = io.BytesIO(); d.save(buf)
    tmp2 = Path(tempfile.mkdtemp())
    (tmp2 / "Houseboat_Hari_tariff.json").write_text(json.dumps({"document_type": "hotel_rate_sheet", "supplier": {"name": "Houseboat Hari", "city": "Alleppey", "phone": "+91 94470 12345"},
        "currency": "INR", "rate_type": "net", "taxes": "included", "validity": {"start": "2026-10-01", "end": "2027-03-31"},
        "hotels": [{"name": "Hari Premium Houseboats", "city": "Alleppey", "property_type": "houseboat", "rates": [
            {"room_type": "1 bedroom premium", "meal_plan": "AP", "occupancy": "double", "amount": 8500},
            {"room_type": "2 bedroom premium", "meal_plan": "AP", "occupancy": "double", "amount": 12500}]}]}))
    pipeline.ingest(s, "Houseboat_Hari_tariff.docx", buf.getvalue(), FixtureExtractor(tmp2))

# ---- a trip with hotel options, quotations and a template
if not s.scalar(select(db.Quotation)):
    hotel = s.scalar(select(db.Hotel).where(db.Hotel.name.like("Misty%")))
    t = trips.create_trip(s, {"title": "Munnar getaway for the Pillais", "customer_name": "Anand Pillai", "customer_phone": "+91 98400 77777",
                              "lead_source": "Instagram", "assigned_to": "Dhineshwar", "start_date": (today + timedelta(days=45)).isoformat(),
                              "adults": 2, "markup_pct": 12, "gst_pct": 5, "destination": "Munnar"})
    trips.set_days(s, t, [{"title": "Arrive Cochin, drive to Munnar", "overnight": "Munnar", "description": "Pick-up at Cochin airport, drive past Cheeyappara waterfalls to Munnar."},
                          {"title": "Munnar sightseeing", "overnight": "Munnar", "description": "Eravikulam park, tea museum, Mattupetty dam."},
                          {"title": "Departure", "description": "Drive back to Cochin for your flight."}])
    trips.add_custom(s, t, "Private Innova for 3 days with driver", 13500)
    trips.add_hotel(s, t, hotel.id, "Deluxe Room", "CP", 2, 1, option_label="Option A · Deluxe")
    trips.add_hotel(s, t, hotel.id, "Premium Valley View", "MAP", 2, 1, option_label="Option B · Premium")
    q1 = quotes.save(s, t, "Dhineshwar")
    quotes.patch(s, q1, {"status": "sent"})
    for tt_ in s.scalars(select(db.Trip).where(db.Trip.status.in_(("quoted", "confirmed")))).all():
        if tt_.id != t.id:
            quotes.save(s, tt_, tt_.assigned_to)
    tpl = trips.duplicate(s, s.scalar(select(db.Trip).where(db.Trip.title.like("Honeymoon%"))), "Kashmir honeymoon 6 days (our plan)")
    tpl.is_template, tpl.customer_name, tpl.customer_phone, tpl.start_date = True, None, None, None
    s.commit()
auth.ensure_bootstrap_admin(s)
print("demo data ready")
