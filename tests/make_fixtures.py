"""Writes tests/fixtures/*.json: the extraction Claude would return for each sample sheet.

Values are deliberately left as raw as a real model returns them (CPAI, 'CWB (6-12)', '01 Oct 26',
'31.12.2026', 'SGL/DBL') so the tests exercise the normalizer, not a pre-cleaned happy path.
"""
import json
from pathlib import Path

OUT = Path(__file__).parent / "fixtures"
OCC = ["Single", "Double", "Extra Adult", "CWB (6-12)", "CNB (below 6)"]


def misty(peak_deluxe_dbl=(7500, 9900)):
    regular = {("Deluxe Room", "CPAI"): [4500, 5000, 1500, 1200, 600],
               ("Deluxe Room", "MAPAI"): [5700, 7400, 2200, 1800, 900],
               ("Premium Valley View", "CPAI"): [6200, 6800, 1800, 1400, 700],
               ("Premium Valley View", "MAPAI"): [7400, 9200, 2500, 2000, 1000],
               ("Pool Villa", "MAPAI"): [None, 14500, 3000, 2400, 1200]}
    peak = {("Deluxe Room", "CPAI"): [7000, peak_deluxe_dbl[0], 2000, 1600, 800],
            ("Deluxe Room", "MAPAI"): [8200, peak_deluxe_dbl[1], 2800, 2200, 1100],
            ("Premium Valley View", "CPAI"): [8800, 9500, 2400, 1900, 950],
            ("Premium Valley View", "MAPAI"): [10000, 11900, 3100, 2500, 1250],
            ("Pool Villa", "MAPAI"): [None, 19500, 3800, 3000, 1500]}
    lines = []
    for season, table in (("regular", regular), ("peak", peak)):
        for (room, plan), amounts in table.items():
            for occ, amt in zip(OCC, amounts):
                lines.append({"room_type": room, "meal_plan": plan, "occupancy": occ, "amount": amt,
                              "season_key": season, "basis": "per_room_per_night", "rate_type": "net",
                              "currency": "INR", "taxes": "excluded",
                              "min_nights": 2 if season == "peak" else None,
                              "notes": "On request" if amt is None else None})
    return {
        "document_type": "hotel_rate_sheet",
        "supplier": {"name": "Misty Hills Resort & Spa", "type": "hotel", "city": "Munnar", "country": "India",
                     "email": "reservations@mistyhills.example", "phone": "+91 4865 000000"},
        "currency": "INR", "validity": {"start": "01/10/2026", "end": "31/03/2027"},
        "taxes": "excluded", "rate_type": "net",
        "seasons": [{"key": "regular", "name": "Regular Season",
                     "periods": [{"start": "01 Oct 26", "end": "19 Dec 26"}, {"start": "06 Jan 27", "end": "31 Mar 27"}]},
                    {"key": "peak", "name": "Peak Season", "periods": [{"start": "20 Dec 26", "end": "05 Jan 27"}]}],
        "hotels": [{"name": "Misty Hills Resort & Spa", "city": "Munnar", "destination": "Kerala", "star_rating": 4,
                    "address": "Pallivasal, Munnar, Kerala 685612", "rates": lines,
                    "supplements": [
                        {"name": "New Year Eve Gala Dinner (adult)", "date_from": "31.12.2026", "date_to": "31.12.2026",
                         "amount": 3500, "currency": "Rs", "basis": "per_adult", "mandatory": True},
                        {"name": "New Year Eve Gala Dinner (child 6-12)", "date_from": "31.12.2026",
                         "date_to": "31.12.2026", "amount": 1750, "currency": "Rs", "basis": "per_child",
                         "mandatory": True}],
                    "blackout_dates": [{"start": "24 Dec 2026", "end": "25 Dec 2026", "room_type": "Pool Villa"}],
                    "child_policy": "Below 6 complimentary without extra bed; 6-12 charged as CWB/CNB."}],
        "general_terms": ["Cancellation: 30 days prior free; 15-29 days 50%; within 14 days 100%. "
                          "Peak season non-refundable.", "Check-in 14:00, check-out 11:00"],
        "warnings": ["Pool Villa single occupancy is on request."],
    }


def green_valley():
    prices = []
    for pax, (std, dlx) in {2: (18500, 24900), 4: (15200, 21600), 6: (13900, 20100)}.items():
        for cat, amt in (("Standard", std), ("Deluxe", dlx)):
            prices.append({"category": cat, "pax_min": pax, "pax_max": pax + 1 if pax < 6 else None,
                           "occupancy": "per person twin sharing", "basis": "per_person", "amount": amt,
                           "season_key": "pkg", "rate_type": "net"})
    for occ, (std, dlx) in {"Single supplement": (7500, 11000), "Child with bed (6-11)": (9800, 12500),
                            "Child without bed (6-11)": (6200, 7900)}.items():
        for cat, amt in (("Standard", std), ("Deluxe", dlx)):
            prices.append({"category": cat, "occupancy": occ, "basis": "per_person", "amount": amt,
                           "season_key": "pkg", "rate_type": "net"})
    services = []
    for route, amts in {"Cochin Airport – Munnar": (3800, 5200, 7500),
                        "Munnar local sightseeing (full day)": (2800, 3600, 5000),
                        "Munnar – Alleppey": (4200, 5800, 8200),
                        "Alleppey – Cochin Airport": (2500, 3300, 4800)}.items():
        for veh, amt in zip(("Sedan (Dzire)", "Innova Crysta", "Tempo Traveller 12 seater"), amts):
            services.append({"kind": "sightseeing" if "sightseeing" in route else "transfer", "name": route,
                             "destination": "Kerala", "vehicle_type": veh, "basis": "per_vehicle", "amount": amt,
                             "currency": "INR", "valid_from": "01.10.2026", "valid_to": "31.03.2027",
                             "rate_type": "net"})
    return {
        "document_type": "mixed",
        "supplier": {"name": "Green Valley Holidays", "type": "dmc", "city": "Kochi", "country": "India",
                     "email": "sales@greenvalley.example", "phone": "+91 484 0000000"},
        "currency": "INR", "validity": {"start": "01-Oct-2026", "end": "31-Mar-2027"}, "taxes": "excluded",
        "rate_type": "net",
        "seasons": [{"key": "pkg", "name": "Package validity (excl. peak)",
                     "periods": [{"start": "2026-10-01", "end": "2026-12-19"}, {"start": "2027-01-06", "end": "2027-03-31"}]}],
        "packages": [{
            "title": "Kerala Classic 4N/5D", "destinations": ["Munnar", "Alleppey", "Kochi"], "nights": 4, "days": 5,
            "valid_from": "01-Oct-2026", "valid_to": "31-Mar-2027",
            "itinerary": [
                {"day": 1, "title": "Cochin – Munnar", "description": "Airport pick up, drive to Munnar (4 hrs) via Cheeyappara waterfalls.", "overnight": "Munnar"},
                {"day": 2, "title": "Munnar sightseeing", "description": "Eravikulam National Park, tea museum, Mattupetty dam, Echo point.", "overnight": "Munnar"},
                {"day": 3, "title": "Munnar – Alleppey", "description": "Drive to Alleppey, board private houseboat, backwater cruise.", "overnight": "Alleppey houseboat", "meals": "B/L/D"},
                {"day": 4, "title": "Alleppey – Kochi", "description": "Disembark, Fort Kochi, Chinese fishing nets, Jew Town.", "overnight": "Kochi"},
                {"day": 5, "title": "Departure", "description": "Drop at Cochin airport."}],
            "hotels": [
                {"city": "Munnar", "hotel_name": "Tea Valley Resort", "category": "Standard", "nights": 2, "meal_plan": "MAP"},
                {"city": "Munnar", "hotel_name": "Misty Hills Resort & Spa", "category": "Deluxe", "nights": 2, "meal_plan": "MAP"},
                {"city": "Alleppey", "hotel_name": "Deluxe Houseboat", "category": "Standard", "nights": 1, "meal_plan": "AP"},
                {"city": "Alleppey", "hotel_name": "Premium Houseboat", "category": "Deluxe", "nights": 1, "meal_plan": "AP"},
                {"city": "Kochi", "hotel_name": "Harbour Inn", "category": "Standard", "nights": 1, "meal_plan": "CP"},
                {"city": "Kochi", "hotel_name": "Grand Bay Hotel", "category": "Deluxe", "nights": 1, "meal_plan": "CP"}],
            "prices": prices,
            "inclusions": ["Accommodation on CP (MAP in Munnar)", "All meals on houseboat",
                           "All transfers and sightseeing by private AC vehicle", "Driver allowance, toll and parking"],
            "exclusions": ["Airfare", "GST 5%", "Entry tickets", "Anything not mentioned in inclusions"]}],
        "services": services,
        "warnings": ["Vehicle rates: add 20% for 20 Dec – 05 Jan (not recorded as separate rates).",
                     "Package not valid 20 Dec – 05 Jan."],
    }


def siam():
    lines = []
    rows = [("Patong Beach Hotel", "Superior", 2200, 2600, 3400, 3900, 900),
            ("Patong Beach Hotel", "Deluxe Pool Access", 3100, 3500, 4600, 5200, 900),
            ("Riverside Grand", "Deluxe", 2800, 3200, 3900, 4300, 1100)]
    hotels = {}
    for hotel, room, g, gw, h, hw, eb in rows:
        for season, base, wkd in (("green", g, gw), ("high", h, hw)):
            for occ in ("Single", "Double"):
                hotels.setdefault(hotel, []).append({"room_type": room, "meal_plan": "incl. breakfast", "occupancy": occ,
                                                     "amount": base, "season_key": season})
                hotels[hotel].append({"room_type": room, "meal_plan": "incl. breakfast", "occupancy": occ,
                                      "amount": wkd, "season_key": season, "days": "Weekend (Fri-Sat)"})
            hotels[hotel].append({"room_type": room, "meal_plan": "incl. breakfast", "occupancy": "Extra bed",
                                  "amount": eb, "season_key": season})
    city = {"Patong Beach Hotel": "Phuket", "Riverside Grand": "Bangkok"}
    return {
        "document_type": "dmc_rate_sheet",
        "supplier": {"name": "Siam Link DMC", "type": "dmc", "country": "Thailand"},
        "currency": "THB", "taxes": "included", "rate_type": "net",
        "seasons": [{"key": "green", "name": "Green Season", "periods": [{"start": "01 Nov 2026", "end": "19 Dec 2026"}]},
                    {"key": "high", "name": "High Season", "periods": [{"start": "20 Dec 2026", "end": "15 Jan 2027"}]}],
        "hotels": [{"name": n, "city": city[n], "destination": "Thailand", "rates": r} for n, r in hotels.items()],
        "services": [
            {"kind": "transfer", "name": "Phuket Airport - Patong hotel", "destination": "Phuket",
             "vehicle_type": "Private van (up to 9)", "basis": "per_vehicle", "amount": 1200},
            {"kind": "sightseeing", "name": "Phi Phi Island by speedboat with lunch", "destination": "Phuket",
             "vehicle_type": "SIC", "basis": "per_adult", "amount": 1900},
            {"kind": "sightseeing", "name": "Phi Phi Island by speedboat with lunch", "destination": "Phuket",
             "vehicle_type": "SIC", "basis": "per_child", "amount": 1400},
            {"kind": "sightseeing", "name": "Bangkok city & temple tour", "destination": "Bangkok",
             "vehicle_type": "SIC", "basis": "per_person", "amount": 1100}],
        "general_terms": ["Child below 4 free sharing bed."],
        "warnings": ["Transfer and tour sheet validity: 01 Nov 2026 - 31 Oct 2027; hotel rates only cover the two seasons."],
    }


def kashmir():
    cats = ["Standard", "Deluxe", "Premium", "Luxury"]
    grid = {2: (14800, 17000, 18500, 23000), 4: (11800, 14000, 15300, 19300), 6: (10400, 12500, 13700, 17700),
            8: (10400, 12800, 13800, 17800), 10: (9800, 12000, 13100, 17100), 12: (9500, 11600, 12800, 16800),
            14: (9200, 11300, 12500, 16500)}
    prices = [{"category": c, "pax_min": pax, "pax_max": pax, "occupancy": "per person twin sharing",
               "basis": "per_person", "amount": amt} for pax, row in grid.items() for c, amt in zip(cats, row)]
    prices += [{"category": c, "occupancy": "Per Extra bed/ CWB", "basis": "per_person", "amount": a}
               for c, a in zip(cats, (5000, 6500, 7500, 8500))]
    prices += [{"category": c, "occupancy": "Per CNB", "basis": "per_person", "amount": a}
               for c, a in zip(cats, (4000, 5000, 6500, 6500))]
    srinagar = {
        "Standard": ["Grand Zamin", "Hasanz Enclave", "Alhamrah Retreat", "Karim Retreat", "D Shamoon", "Holiday Villa",
                     "Grand Alden", "Grand MS", "Sideeq Palace", "Golden Sands", "Mehtab Palace", "Royal Milad",
                     "Shamas Residency", "Gurcoo Residency", "Shefaf", "Zaman", "Regal Palace"],
        "Deluxe": ["Adlife Luxury", "Firdous", "Brown Palace", "Hermitage", "Moonstone", "Karam Gold", "Asain Park",
                   "Kareem Residency", "Royal Arabia", "Victory", "Golden Leaf", "Opera Inn", "Moonstone De Luxury",
                   "Blossom", "Grand Fortune"],
        "Premium": ["Downtown", "Montreal", "Sapphire Luxury", "Grand Kaiser", "Blanco", "Ov Boutique", "5 Falcon",
                    "Royal Heritage", "Royal Batoo", "Brown Palace", "Paisley Palace"],
        "Luxury": ["Eternity by Greenscape", "Central Park", "Enco Resorts", "Arco", "Solar Residency", "Palm Spring",
                   "Country Side", "Batra", "Rose Petal", "Royal Comfort", "Regency"]}
    pahalgam = {
        "Standard": ["Mala Resort", "Golf View", "Hills Heevan", "Pahalgam Guestline", "Chinar Palace", "Pahalgam Peaks",
                     "Sun N Shades", "Diamond Star", "Ababeel Heights", "Ahmad Villa", "Shabnum Resort", "Sun N Snow",
                     "Peace Villa", "Vergan Resort", "Ski Hill Resort", "Classic Inn Estate"],
        "Deluxe": ["Himalyan Hill Resort", "Wood Resort", "Lidder Spring", "Grand Salween", "A S Resort", "Black Pearl",
                   "5th Season", "Vista", "Srichan Resort", "Green Height", "Pahalgam Retreat", "Royale Comfort",
                   "Faiz Resort", "Twin Top", "Idyll Resort"],
        "Premium": ["Early Beck Resort", "Pahlagam Dayz", "Pahalgam Shore", "River Side Cottage", "White Water",
                    "White House", "Elegant Resort", "Bombay Palace", "Bombay Residency", "Volga", "Baisaran"],
        "Luxury": ["Vales Lodge", "Kudrat", "Harmukh Hills", "Hill Side Resorts", "Mount View", "Chinar Resorts"]}
    boats = ["Dawn", "Nazneen", "Nanga Parbat", "Azad Palace", "Golden Crown", "Morning Star", "Heevan"]
    houseboats = {"Standard": boats, "Deluxe": boats, "Premium": boats, "Luxury": ["Wanganoo Paradise", "Mahjong"]}
    hotels = []
    for city, nights, table, ptype in (("Srinagar", 3, srinagar, "hotel"), ("Pahalgam", 1, pahalgam, "hotel"),
                                       ("Srinagar", 1, houseboats, "houseboat")):
        for cat, names in table.items():
            hotels += [{"city": city, "hotel_name": n, "category": cat, "nights": nights, "meal_plan": "MAP",
                        "property_type": ptype} for n in names]
    svc = lambda **k: {"destination": "Kashmir", "optional": True, "rate_type": "unknown", **k}
    services = [
        svc(kind="activity", name="Gulmarg Gondola ride - Phase 1", destination="Gulmarg", basis="per_person", amount=850),
        svc(kind="activity", name="Gulmarg Gondola ride - Phase 2", destination="Gulmarg", basis="per_person", amount=1050),
        svc(kind="activity", name="Pony ride", basis="per_person", amount=1200, amount_max=1500, notes="Per location"),
        svc(kind="rental", name="Jackets & snow shoes on rent", destination="Gulmarg", basis="per_person", amount=200),
        svc(kind="activity", name="Special activities at Gulmarg", destination="Gulmarg", basis="unknown", amount=1500,
            amount_max=2500, notes="Depends on activity and distance travelled"),
        svc(kind="transfer", name="Transit cab for Gulmarg", destination="Gulmarg", basis="per_vehicle", pax_max=6,
            amount=2500, notes="Required in case of heavy snow or bad weather"),
        svc(kind="sightseeing", name="Local sightseeing of Gulmarg (Maharaja Palace, Botapatri)", destination="Gulmarg",
            basis="per_vehicle", amount=3500, amount_max=5000, notes="Negotiable"),
        svc(kind="transfer", name="Transit cab for Aru Valley, Betaab Valley & Chandanwari", destination="Pahalgam",
            basis="per_vehicle", pax_max=6, amount=2500),
        svc(kind="transfer", name="Transit cab for Zero Point, Sonamarg", destination="Sonamarg", basis="per_vehicle",
            pax_max=6, amount=4500, amount_max=7500, notes="Negotiable"),
        svc(kind="entry_ticket", name="Mughal Garden entry ticket", destination="Srinagar", basis="per_person", amount=24,
            notes="Per garden"),
    ]
    offbeat = [("Gurez Valley", "Bandipora", "valley", "Remote Himalayan valley with meadows, rivers, Gurez Fort ruins and traditional villages."),
               ("Sinthan Top", "Anantnag", "viewpoint", "High pass at about 3,800 m with wide mountain and valley views."),
               ("Kokernag", "Anantnag", "garden", "Town known for natural springs and gardens at the foot of the Pir Panjal."),
               ("Verinag", "Anantnag", "garden", "Spring that is the source of the Jhelum, with a Mughal-era garden."),
               ("Aharbal", "Kulgam", "offbeat", "Large waterfall surrounded by forest walks."),
               ("Warwan Valley", "Kishtwar", "valley", "Remote trekking valley with traditional villages."),
               ("Lolab Valley", "Kupwara", "valley", "Green valley with forests, streams and old monuments."),
               ("Bungas Valley", "Kupwara", "valley", "High meadows with trekking trails and panoramic views."),
               ("Daksum", "Anantnag", "offbeat", "Forest village popular with trekkers.")]
    places = [{"name": n, "destination": "Kashmir", "region": r, "kind": k, "description": d,
               "availability": "15 Apr - 15 Oct (on request only)"} for n, r, k, d in offbeat]
    places += [{"name": n, "destination": "Kashmir", "region": r, "kind": k, "description": d} for n, r, k, d in [
        ("Nishat Bagh", "Srinagar", "garden", "Terraced Mughal garden on the banks of Dal Lake."),
        ("Shalimar Bagh", "Srinagar", "garden", "Mughal garden with fountains and water channels on Dal Lake."),
        ("Shankaracharya Temple", "Srinagar", "religious", "Hilltop temple overlooking Srinagar."),
        ("Hazratbal Shrine", "Srinagar", "religious", "Shrine on the shore of Dal Lake."),
        ("Dal Lake", "Srinagar", "lake", "Lake known for shikara rides and houseboats."),
        ("Gulmarg", "Baramulla", "attraction", "Ski resort and meadow with gondola and golf course, about 2 hrs from Srinagar."),
        ("Sonamarg", "Ganderbal", "valley", "Meadow on the Sindh river with pony rides to the glaciers."),
        ("Betaab Valley", "Pahalgam", "valley", "Valley near Pahalgam reached by union cab."),
        ("Aru Valley", "Pahalgam", "valley", "Meadow village near Pahalgam reached by union cab."),
        ("Chandanwari", "Pahalgam", "attraction", "Snow point near Pahalgam reached by union cab.")]]
    return {
        "document_type": "package",
        "supplier": {"name": "Abdaal Travels", "type": "dmc", "city": "Srinagar", "country": "India",
                     "contact_person": "Fayaz Ahmad (Managing Director)",
                     "email": "abdaaltravels44@gmail.com, operations.abdaaltravels@gmail.com, operations2.abdaaltravels@gmail.com",
                     "phone": "0194-3573829, +91 7298624934, +91 7889387991, +91 8899885413, +91 9103003422, 9906738898",
                     "address": "2nd Floor, Ibrahim Shopping Complex, Rainawari, Srinagar, Jammu and Kashmir 190003",
                     "website": "abdaaltravels.wordpress.com", "gst_number": "01AEXPF9830N1ZY"},
        "currency": "INR", "validity": {"start": "Aug 2026", "end": "Oct 2026"},
        "taxes": "unknown", "rate_type": "unknown",
        "packages": [{
            "title": "Kashmir Off Season 5N/6D", "region": "Kashmir",
            "destinations": ["Srinagar", "Gulmarg", "Sonamarg", "Pahalgam"], "nights": 5, "days": 6,
            "valid_from": "Aug 2026", "valid_to": "Oct 2026",
            "itinerary": [
                {"day": 1, "title": "Arrival Srinagar", "overnight": "Srinagar", "meals": "D",
                 "description": "Arrive at Srinagar airport, meet our representative and transfer to the hotel. Visit the Mughal gardens - Nishat Bagh and Shalimar Bagh on the banks of Dal Lake - Shankaracharya Temple and Hazratbal Shrine. Check in, dinner and overnight in Srinagar."},
                {"day": 2, "title": "Day excursion to Gulmarg", "overnight": "Srinagar", "meals": "B/D",
                 "description": "After breakfast drive to Gulmarg (60 km / 2 hrs), famous for ski slopes and one of the highest golf courses in the world. Optional Gondola ride to Kongdoori and Marry Shoulder at own cost. Return to Srinagar for the night."},
                {"day": 3, "title": "Day excursion to Sonamarg", "overnight": "Srinagar", "meals": "B/D",
                 "description": "After breakfast full-day excursion to Sonamarg, the 'meadow of gold' on the Sindh river. Optional pony ride to the glaciers at own cost. Return to Srinagar in the evening."},
                {"day": 4, "title": "Srinagar to Pahalgam", "overnight": "Pahalgam", "meals": "B/D",
                 "description": "After breakfast check out and drive to Pahalgam (90 km / 2 hrs), the Valley of Shepherds, visiting saffron fields, Awantipura ruins and a bat factory on the way. Optional Aru Valley, Betaab Valley and Chandanwari by union cab at own cost. Dinner and overnight in Pahalgam."},
                {"day": 5, "title": "Pahalgam to Srinagar houseboat", "overnight": "Srinagar (houseboat)", "meals": "B/D",
                 "description": "After breakfast drive back to Srinagar. Shikara ride on Dal Lake and time for shopping. Check in to the houseboat, dinner and overnight."},
                {"day": 6, "title": "Departure", "meals": "B",
                 "description": "After breakfast transfer to Srinagar airport for departure."}],
            "hotels": hotels, "prices": prices,
            "inclusions": ["Meet and greet on arrival", "Transportation", "Accommodation", "Airport pick up and drop",
                           "Toll", "Parking", "Sightseeing", "Transfers", "Shikara ride at Dal Lake"],
            "exclusions": ["Gondola: 850 per person Phase 1, 1050 per person Phase 2",
                           "Pony rides: 1200-1500 per person per location", "Jackets & snow shoes on rent: 200 per person",
                           "Special activities at Gulmarg: 1500-2500", "Transit cab for Gulmarg: 2500 per cab for 6 pax (heavy snow / bad weather)",
                           "Local sightseeing of Gulmarg: 3500-5000 (negotiable)",
                           "Transit cab for Aru Valley, Betaab Valley & Chandanwari: 2500 per cab for 6 pax",
                           "Transit cabs for Zero Point, Sonamarg: 4500-7500 per cab for 6 pax (negotiable)",
                           "Entry tickets: 24 per person per Mughal garden", "Personal expenses", "Lunch", "Airfare"],
            "terms": ["Hotels are 'or similar' options per category"]}],
        "services": services, "places": places,
        "general_terms": ["Check-in / check-out at all properties 12:00 noon.",
                          "MAP (breakfast & dinner): fixed menu / buffet, no choice of menu.",
                          "Prices may change with hotel tariff revisions, transport / fuel cost hikes or new J&K government taxes.",
                          "Cancellation: no charge 21+ days before check-in; 50% between 21 and 15 days; 100% within 15 days.",
                          "Offbeat places accessible 15 April - 15 October only, costed on request."],
        "warnings": ["Currency not stated - INR assumed.",
                     "Rates not labelled net/B2B or public.",
                     "'Group of Houseboats' is listed as an option but is not a specific property - not recorded.",
                     "Pahalgam Standard list: 'Hills Heevan / Pahalgam / Guestline' read as 'Hills Heevan' and 'Pahalgam Guestline' - check."],
    }


def main():
    OUT.mkdir(exist_ok=True)
    s = siam()
    for sv in s["services"]:
        sv.update(valid_from="01 Nov 2026", valid_to="31 Oct 2027")
    files = {"misty_hills_munnar_2026-27": misty(), "misty_hills_munnar_2026-27_revised": misty((8000, 10500)),
             "green_valley_kerala_classic": green_valley(), "siam_link_thailand_2026-27": s,
             "Off_Season_2026_Kashmir_package_5N_6D": kashmir()}
    for name, data in files.items():
        (OUT / f"{name}.json").write_text(json.dumps(data, indent=2, ensure_ascii=False))
    print("fixtures written:", ", ".join(files))


if __name__ == "__main__":
    main()
