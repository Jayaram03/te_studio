"""Generate realistic sample rate sheets into ./samples (for tests and demos)."""
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

OUT = Path(__file__).resolve().parent.parent / "samples"
ss = getSampleStyleSheet()
GRID = TableStyle([("GRID", (0, 0), (-1, -1), 0.5, colors.grey), ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
                   ("FONTSIZE", (0, 0), (-1, -1), 9)])


def pdf(name, flow):
    SimpleDocTemplate(str(OUT / name), pagesize=A4, title=name).build(flow)


def hotel_sheet(name, peak):
    P = lambda t, st="Normal": Paragraph(t, ss[st])
    flow = [P("Misty Hills Resort &amp; Spa, Munnar", "Title"),
            P("Pallivasal, Munnar, Kerala 685612 · 4 Star · reservations@mistyhills.example · +91 4865 000000"),
            P("<b>B2B NET RATES FOR TRAVEL AGENTS</b> — Validity: 01/10/2026 to 31/03/2027"),
            P("Regular Season: 01 Oct 26 – 19 Dec 26 &amp; 06 Jan 27 – 31 Mar 27 &nbsp;&nbsp; "
              "Peak Season: 20 Dec 26 – 05 Jan 27"), Spacer(1, 8),
            P("All rates in INR per room per night. GST 18% extra.")]
    reg = [["Room Category", "Plan", "Single", "Double", "Extra Adult", "CWB (6-12)", "CNB (below 6)"],
           ["Deluxe Room", "CPAI", "4,500/-", "5,000/-", "1,500/-", "1,200/-", "600/-"],
           ["Deluxe Room", "MAPAI", "5,700/-", "7,400/-", "2,200/-", "1,800/-", "900/-"],
           ["Premium Valley View", "CPAI", "6,200/-", "6,800/-", "1,800/-", "1,400/-", "700/-"],
           ["Premium Valley View", "MAPAI", "7,400/-", "9,200/-", "2,500/-", "2,000/-", "1,000/-"],
           ["Pool Villa", "MAPAI", "On request", "14,500/-", "3,000/-", "2,400/-", "1,200/-"]]
    flow += [Spacer(1, 6), P("<b>Regular Season</b>"), Table(reg, style=GRID), Spacer(1, 10),
             P("<b>Peak Season</b> (minimum stay 2 nights)"), Table(peak, style=GRID), Spacer(1, 10),
             P("<b>Supplements:</b> Compulsory New Year Eve Gala Dinner on 31.12.2026 — Rs 3,500 per adult, "
               "Rs 1,750 per child (6-12)."),
             P("<b>Blackout:</b> 24 Dec 2026 – 25 Dec 2026 stop sale on Pool Villa."),
             P("<b>Child policy:</b> Below 6 years complimentary without extra bed. 6-12 years charged as CWB/CNB."),
             P("<b>Cancellation:</b> 30 days prior free; 15-29 days 50%; within 14 days 100%. Peak season non-refundable."),
             P("<b>Check-in</b> 14:00 / <b>Check-out</b> 11:00")]
    pdf(name, flow)


def main():
    OUT.mkdir(exist_ok=True)
    peak = [["Room Category", "Plan", "Single", "Double", "Extra Adult", "CWB (6-12)", "CNB (below 6)"],
            ["Deluxe Room", "CPAI", "7,000/-", "7,500/-", "2,000/-", "1,600/-", "800/-"],
            ["Deluxe Room", "MAPAI", "8,200/-", "9,900/-", "2,800/-", "2,200/-", "1,100/-"],
            ["Premium Valley View", "CPAI", "8,800/-", "9,500/-", "2,400/-", "1,900/-", "950/-"],
            ["Premium Valley View", "MAPAI", "10,000/-", "11,900/-", "3,100/-", "2,500/-", "1,250/-"],
            ["Pool Villa", "MAPAI", "On request", "19,500/-", "3,800/-", "3,000/-", "1,500/-"]]
    hotel_sheet("misty_hills_munnar_2026-27.pdf", peak)
    revised = [r[:] for r in peak]
    revised[1][3], revised[2][3] = "8,000/-", "10,500/-"          # revised peak doubles
    hotel_sheet("misty_hills_munnar_2026-27_revised.pdf", revised)

    # ---- DMC package + transfer sheet
    P = lambda t, st="Normal": Paragraph(t, ss[st])
    flow = [P("Green Valley Holidays (DMC) — Kerala", "Title"),
            P("Kochi · sales@greenvalley.example · +91 484 0000000 · Agent Net Rates"),
            P("<b>KERALA CLASSIC — 4 Nights / 5 Days</b> (Munnar 2N · Alleppey Houseboat 1N · Kochi 1N)", "Heading2"),
            P("Package validity: 01-Oct-2026 to 31-Mar-2027 (excluding 20 Dec – 05 Jan)"),
            P("<b>Day 1: Cochin – Munnar.</b> Pick up from Cochin airport, drive to Munnar (4 hrs), en route Cheeyappara "
              "waterfalls. Overnight Munnar."),
            P("<b>Day 2: Munnar sightseeing.</b> Eravikulam National Park, tea museum, Mattupetty dam, Echo point. "
              "Overnight Munnar."),
            P("<b>Day 3: Munnar – Alleppey.</b> Drive to Alleppey, board private houseboat, cruise the backwaters. "
              "All meals on board. Overnight houseboat."),
            P("<b>Day 4: Alleppey – Kochi.</b> Disembark, drive to Kochi. Fort Kochi, Chinese fishing nets, "
              "Jew Town. Overnight Kochi."),
            P("<b>Day 5: Departure.</b> Drop at Cochin airport."), Spacer(1, 8),
            P("<b>Hotels</b>"),
            Table([["City", "Standard (3*)", "Deluxe (4*)", "Nights"],
                   ["Munnar", "Tea Valley Resort", "Misty Hills Resort & Spa", "2"],
                   ["Alleppey", "Deluxe Houseboat", "Premium Houseboat", "1"],
                   ["Kochi", "Harbour Inn", "Grand Bay Hotel", "1"]], style=GRID), Spacer(1, 8),
            P("<b>Package cost per person on twin sharing (INR, net)</b>"),
            Table([["Pax", "Standard", "Deluxe"], ["2 Pax", "18,500", "24,900"], ["4 Pax", "15,200", "21,600"],
                   ["6 Pax", "13,900", "20,100"], ["Single supplement", "7,500", "11,000"],
                   ["Child with bed (6-11)", "9,800", "12,500"], ["Child without bed (6-11)", "6,200", "7,900"]],
                  style=GRID), Spacer(1, 8),
            P("<b>Inclusions:</b> Accommodation as above on CP (MAP in Munnar), all meals on houseboat, all transfers "
              "and sightseeing by private AC vehicle, driver allowance, toll and parking."),
            P("<b>Exclusions:</b> Airfare, GST 5%, entry tickets, anything not mentioned in inclusions."),
            Spacer(1, 10), P("<b>Transfer / Vehicle Rates (per vehicle, INR)</b>"),
            Table([["Route", "Sedan (Dzire)", "Innova Crysta", "Tempo Traveller 12 seater"],
                   ["Cochin Airport – Munnar", "3,800", "5,200", "7,500"],
                   ["Munnar local sightseeing (full day)", "2,800", "3,600", "5,000"],
                   ["Munnar – Alleppey", "4,200", "5,800", "8,200"],
                   ["Alleppey – Cochin Airport", "2,500", "3,300", "4,800"]], style=GRID),
            P("Vehicle rates valid 01.10.2026 – 31.03.2027. Add 20% for 20 Dec – 05 Jan.")]
    pdf("green_valley_kerala_classic.pdf", flow)

    # ---- Excel (Thailand DMC) with merged header cells
    wb = Workbook()
    ws = wb.active
    ws.title = "Hotels"
    ws["A1"] = "SIAM LINK DMC — Thailand Hotel Net Rates 2026-27 (THB per room per night, incl. breakfast)"
    ws.merge_cells("A1:H1")
    ws["A1"].font = Font(bold=True)
    ws["A3"], ws["B3"], ws["C3"] = "City", "Hotel", "Room"
    ws["D3"] = "Green Season 01 Nov 2026 - 19 Dec 2026"
    ws.merge_cells("D3:E3")
    ws["F3"] = "High Season 20 Dec 2026 - 15 Jan 2027"
    ws.merge_cells("F3:G3")
    ws["H3"] = "Extra bed"
    for c, v in zip("DEFG", ["SGL/DBL", "Weekend (Fri-Sat)", "SGL/DBL", "Weekend (Fri-Sat)"]):
        ws[f"{c}4"] = v
    rows = [["Phuket", "Patong Beach Hotel", "Superior", 2200, 2600, 3400, 3900, 900],
            ["Phuket", "Patong Beach Hotel", "Deluxe Pool Access", 3100, 3500, 4600, 5200, 900],
            ["Bangkok", "Riverside Grand", "Deluxe", 2800, 3200, 3900, 4300, 1100]]
    for i, r in enumerate(rows, start=5):
        for j, v in enumerate(r):
            ws.cell(row=i, column=j + 1, value=v)
    ws["A9"] = "Rates are NET, inclusive of service charge & VAT. Child below 4 free sharing bed."
    ws2 = wb.create_sheet("Transfers & Tours")
    ws2.append(["Service", "Type", "Basis", "Rate (THB)"])
    ws2.append(["Phuket Airport - Patong hotel", "Private van (up to 9)", "per vehicle", 1200])
    ws2.append(["Phi Phi Island by speedboat with lunch", "SIC", "per adult", 1900])
    ws2.append(["Phi Phi Island by speedboat with lunch", "SIC", "per child", 1400])
    ws2.append(["Bangkok city & temple tour", "SIC", "per person", 1100])
    ws2.append([])
    ws2.append(["Valid 01 Nov 2026 - 31 Oct 2027"])
    for w in (ws, ws2):
        for col in "ABCDEFGH":
            w.column_dimensions[col].width = 22
        w["A1"].alignment = Alignment(wrap_text=True)
    wb.save(OUT / "siam_link_thailand_2026-27.xlsx")
    print("samples written to", OUT)


if __name__ == "__main__":
    main()
