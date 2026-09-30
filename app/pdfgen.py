"""Branded PDFs (Travel Episodes design system): client quotes / itineraries and package rate cards.

Brand rules applied: Poppins; lavender #8286CB and orange #EF712C lead; charcoal body text on white;
orange text only at 24pt+; flat colour, rounded shapes, a dot-grid patch and a lavender pill tab; no gradients
or shadows; the logo is used as supplied (never redrawn).
"""
from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

import io
from datetime import date, timedelta
from pathlib import Path

from reportlab.lib.colors import HexColor, white
from reportlab.lib.enums import TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    Image, KeepTogether, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle,
)

STATIC = Path(__file__).parent / "static"
LAVENDER, ORANGE, CHARCOAL, GRAPHITE = HexColor("#8286CB"), HexColor("#EF712C"), HexColor("#4F4C4D"), HexColor("#5F6062")
MIST, CREAM, LAV_SOFT = HexColor("#E2E3F3"), HexColor("#FAE7B6"), HexColor("#A5A4D4")

_fonts = False


def _register():
    global _fonts
    if _fonts:
        return
    for name, file in (("Poppins", "Poppins-Regular"), ("Poppins-Light", "Poppins-Light"),
                       ("Poppins-Medium", "Poppins-Medium"), ("Poppins-Bold", "Poppins-Bold")):
        pdfmetrics.registerFont(TTFont(name, str(STATIC / "fonts" / f"{file}.ttf")))
    pdfmetrics.registerFontFamily("Poppins", normal="Poppins", bold="Poppins-Bold", italic="Poppins-Light",
                                  boldItalic="Poppins-Bold")
    _fonts = True


def _styles():
    _register()
    base = dict(fontName="Poppins", textColor=CHARCOAL)
    return {
        "title": ParagraphStyle("title", fontName="Poppins-Bold", fontSize=24, leading=29, textColor=CHARCOAL),
        "meta": ParagraphStyle("meta", fontName="Poppins", fontSize=10, leading=15, textColor=GRAPHITE),
        "h2": ParagraphStyle("h2", fontName="Poppins-Bold", fontSize=15, leading=20, textColor=CHARCOAL, spaceBefore=14, spaceAfter=6),
        "daynum": ParagraphStyle("daynum", fontName="Poppins-Bold", fontSize=24, leading=26, textColor=ORANGE),
        "daytitle": ParagraphStyle("daytitle", fontName="Poppins-Medium", fontSize=12.5, leading=17, textColor=CHARCOAL),
        "body": ParagraphStyle("body", fontSize=9.8, leading=15, **base),
        "small": ParagraphStyle("small", fontName="Poppins", fontSize=8.5, leading=12, textColor=GRAPHITE),
        "label": ParagraphStyle("label", fontName="Poppins-Light", fontSize=7.5, leading=10, textColor=GRAPHITE),
        "cell": ParagraphStyle("cell", fontSize=9, leading=12.5, **base),
        "cellb": ParagraphStyle("cellb", fontName="Poppins-Medium", fontSize=9, leading=12.5, textColor=CHARCOAL),
        "right": ParagraphStyle("right", fontSize=9, leading=12.5, alignment=TA_RIGHT, **base),
        "price": ParagraphStyle("price", fontName="Poppins-Bold", fontSize=24, leading=28, textColor=ORANGE, alignment=TA_RIGHT),
        "bullet": ParagraphStyle("bullet", fontSize=9.3, leading=13.5, leftIndent=10, bulletIndent=0, **base),
    }


def _e(s) -> str:
    return (str(s or "")).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace("\n", "<br/>")


def _money(n, cur) -> str:
    if n is None:
        return ""
    v = int(Decimal(str(n)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    s = f"{v:,}"
    if cur == "INR":                 # Indian grouping: 1,33,634
        neg, v = v < 0, abs(v)
        head, tail = str(v)[:-3], str(v)[-3:]
        parts = []
        while len(head) > 2:
            parts.insert(0, head[-2:])
            head = head[:-2]
        if head:
            parts.insert(0, head)
        s = ("-" if neg else "") + (",".join(parts) + "," + tail if parts else tail)
        return f"₹{s}" if _has_rupee() else f"INR {s}"
    return f"{cur} {s}" if cur else s


def _has_rupee() -> bool:
    _register()
    try:
        return pdfmetrics.getFont("Poppins").face.charToGlyph.get(0x20B9) is not None
    except Exception:  # noqa: BLE001
        return False


def _fmt_date(d) -> str:
    if not d:
        return ""
    d = date.fromisoformat(d) if isinstance(d, str) else d
    return d.strftime("%d %b %Y").lstrip("0")


def _decorate(company: dict, footer_note: str):
    def draw(c, doc):
        w, h = A4
        c.saveState()
        # lavender pill tab bleeding off the left edge
        c.setFillColor(LAVENDER)
        c.roundRect(-14 * mm, h - 95 * mm, 20 * mm, 52 * mm, 10 * mm, stroke=0, fill=1)
        # dot-grid patch near the top-right corner: rows alternate lavender / orange
        for r in range(4):
            c.setFillColor(LAVENDER if r % 2 == 0 else ORANGE)
            for col in range(8):
                c.circle(w - 18 * mm - col * 4.5 * mm, h - 10 * mm - r * 3.8 * mm, 0.7 * mm, stroke=0, fill=1)
        # footer
        c.setFillColor(GRAPHITE)
        c.setFont("Poppins", 7.5)
        em = STATIC / "brand" / "emblem.png"
        if em.exists():
            c.drawImage(str(em), 18 * mm, 9 * mm, 7 * mm, 7 * mm, mask="auto")
        c.drawString(27 * mm, 11.5 * mm, f"{company.get('name', 'Travel Episodes')}  ·  {company.get('email', '')}")
        c.drawRightString(w - 18 * mm, 11.5 * mm, f"{footer_note}   page {doc.page}")
        c.restoreState()
    return draw


def _table(rows, widths, header=True, zebra=False):
    t = Table(rows, colWidths=widths, hAlign="LEFT")
    style = [("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 7),
             ("RIGHTPADDING", (0, 0), (-1, -1), 7), ("TOPPADDING", (0, 0), (-1, -1), 5),
             ("BOTTOMPADDING", (0, 0), (-1, -1), 5), ("LINEBELOW", (0, 0), (-1, -1), 0.4, LAV_SOFT)]
    if header:
        style += [("BACKGROUND", (0, 0), (-1, 0), MIST), ("LINEBELOW", (0, 0), (-1, 0), 0, MIST)]
    if zebra:
        style += [("ROWBACKGROUNDS", (0, 1), (-1, -1), [white, HexColor("#F6F6FB")])]
    t.setStyle(TableStyle(style))
    return t


def _logo(width=58 * mm):
    p = STATIC / "brand" / "logo.png"
    if not p.exists():
        return Spacer(1, 1)
    img = Image(str(p), width=width, height=width * 313 / 900)
    img.hAlign = "LEFT"
    return img


def _contact(st, company: dict, preparer: dict | None) -> list:
    rows = []
    if preparer and preparer.get("name"):
        rows.append([Paragraph("PREPARED BY", st["label"]),
                     Paragraph(f"<b>{_e(preparer['name'])}</b>" + (f"  ·  {_e(preparer.get('phone'))}" if preparer.get("phone") else ""), st["cell"])])
    if company.get("email"):
        rows.append([Paragraph("EMAIL", st["label"]),
                     Paragraph(f'<link href="mailto:{_e(company["email"])}" color="#4F4C4D">{_e(company["email"])}</link>', st["cell"])])
    if company.get("instagram"):
        ig = company["instagram"].lstrip("@")
        rows.append([Paragraph("INSTAGRAM", st["label"]),
                     Paragraph(f'<link href="https://www.instagram.com/{_e(ig)}/" color="#4F4C4D">@{_e(ig)}</link>', st["cell"])])
    if company.get("address"):
        rows.append([Paragraph("VISIT", st["label"]), Paragraph(_e(company["address"]), st["cell"])])
    if company.get("gst_number"):
        rows.append([Paragraph("GSTIN", st["label"]), Paragraph(_e(company["gst_number"]), st["cell"])])
    box = Table(rows, colWidths=[28 * mm, 120 * mm], hAlign="LEFT")
    box.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("TOPPADDING", (0, 0), (-1, -1), 4),
                             ("BOTTOMPADDING", (0, 0), (-1, -1), 4), ("LEFTPADDING", (0, 0), (-1, -1), 0)]))
    return [KeepTogether([Paragraph("Talk to us", st["h2"]), box])]


def _bullets(st, items):
    return [Paragraph(_e(x), st["bullet"], bulletText="•") for x in items]


# ------------------------------------------------------------------ trip quote / itinerary
def trip_pdf(view: dict, settings: dict, preparer: dict | None = None, show_prices: bool = True) -> bytes:
    st = _styles()
    company, quote_cfg = settings["company"], settings["quote"]
    buf = io.BytesIO()
    qinfo = view.get("quote") or {}
    if qinfo.get("number"):
        note = (f"Quotation {qinfo['number']}" + (f" · valid until {_fmt_date(qinfo['valid_until'])}"
                                                  if qinfo.get("valid_until") and show_prices else ""))
    else:
        valid_until = date.today() + timedelta(days=int(quote_cfg.get("validity_days") or 7))
        note = f"Quote #{view['id']} · valid until {_fmt_date(valid_until)}" if show_prices else f"Itinerary #{view['id']}"
    from .trips import options_display, shown_items
    options = options_display(view)
    choosing = bool(options) and not view["totals"].get("chosen_option")
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm, topMargin=16 * mm,
                            bottomMargin=22 * mm, title=view["title"], author=company.get("name"))
    T = view["totals"]
    cur = T["currency"]
    flow = [_logo(), Spacer(1, 10), Paragraph(_e(view["title"]), st["title"])]
    pax = f"{view['adults']} adult{'s' if view['adults'] != 1 else ''}"
    kids = view["children_with_bed"] + view["children_without_bed"]
    if kids:
        pax += f", {kids} child{'ren' if kids != 1 else ''}"
    meta = [f"Prepared for {view['customer_name']}" if view.get("customer_name") else None,
            f"{_fmt_date(view['start_date'])} – {_fmt_date(view['end_date'])}" if view.get("start_date") else None]
    flow.append(Paragraph(_e("  ·  ".join(x for x in meta if x)), st["meta"]))
    flow.append(Spacer(1, 10))

    nights = max(len(view["days"]) - 1, 0)
    glance = [("DESTINATION", view.get("destination") or "—"),
              ("DURATION", f"{nights} nights / {len(view['days'])} days" if view["days"] else "—"),
              ("TRAVELLERS", pax), ("HOTELS", view.get("category") or "As listed")]
    if show_prices and T.get("per_person"):
        glance.append(("FROM, PER PERSON" if choosing else "PER PERSON", _money(T["per_person"], cur)))
    cells = [[Paragraph(k, st["label"]) for k, _ in glance], [Paragraph(f"<b>{_e(v)}</b>", st["cell"]) for _, v in glance]]
    g = Table(cells, colWidths=[174 * mm / len(glance)] * len(glance), hAlign="LEFT")
    g.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), MIST), ("LEFTPADDING", (0, 0), (-1, -1), 9),
                           ("TOPPADDING", (0, 0), (-1, 0), 8), ("BOTTOMPADDING", (0, -1), (-1, -1), 9),
                           ("ROUNDEDCORNERS", [8, 8, 8, 8])]))
    flow += [g, Spacer(1, 6)]

    if view["days"]:
        flow.append(Paragraph("Day by day", st["h2"]))
        for d in view["days"]:
            head = Table([[Paragraph(f"{d['position']:02d}", st["daynum"]),
                           [Paragraph(_e(d["title"] or ""), st["daytitle"]),
                            Paragraph(_e("  ·  ".join(x for x in [_fmt_date(d["date"]) if d.get("date") else "",
                                                                  f"Overnight: {d['overnight']}" if d.get("overnight") else "",
                                                                  f"Meals: {d['meals']}" if d.get("meals") else ""] if x)), st["small"])]]],
                         colWidths=[16 * mm, 158 * mm], hAlign="LEFT")
            head.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0),
                                      ("TOPPADDING", (0, 0), (-1, -1), 0)]))
            body = Paragraph(_e(d.get("description") or ""), st["body"])
            flow.append(KeepTogether([head, Table([[body]], colWidths=[158 * mm], hAlign="RIGHT",
                                                  style=[("LEFTPADDING", (0, 0), (-1, -1), 0)]), Spacer(1, 8)]))

    # accommodation
    pkg_hotels = [h for i in shown_items(view) if i["kind"] == "package" for h in i["details"].get("hotels", [])]
    stays = [i for i in shown_items(view) if i["kind"] == "hotel"]
    if pkg_hotels or stays:
        rows = [[Paragraph("<b>Where you stay</b>", st["cellb"]), Paragraph("<b>Nights</b>", st["cellb"]),
                 Paragraph("<b>Hotel</b>", st["cellb"])]]
        by: dict[tuple, list] = {}
        for h in pkg_hotels:
            by.setdefault((h["city"] or "", h["nights"] or ""), []).append(h["hotel"])
        for (city, n), names in by.items():
            shown = ", ".join(names[:4]) + (" or similar" if names else "")
            rows.append([Paragraph(_e(city), st["cell"]), Paragraph(str(n), st["cell"]), Paragraph(_e(shown), st["cell"])])
        for sItem in stays:
            rows.append([Paragraph("", st["cell"]), Paragraph("", st["cell"]), Paragraph(_e(sItem["description"]), st["cell"])])
        flow += [Paragraph("Accommodation", st["h2"]), _table(rows, [38 * mm, 18 * mm, 118 * mm])]

    if view["inclusions"] or view["exclusions"]:
        inc = [Paragraph("Included", st["h2"])] + _bullets(st, view["inclusions"])
        exc = [Paragraph("Not included", st["h2"])] + _bullets(st, view["exclusions"])
        two = Table([[inc, exc]], colWidths=[87 * mm, 87 * mm], hAlign="LEFT")
        two.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0)]))
        flow.append(two)

    if choosing:
        head = [Paragraph("<b>Option</b>", st["cellb"]), Paragraph("<b>Hotels and what differs</b>", st["cellb"])]
        if show_prices:
            head += [Paragraph("<b>Per person</b>", st["right"]), Paragraph("<b>Total</b>", st["right"])]
        rows = [head]
        for o in options:
            r = [Paragraph(f"<b>{_e(o['label'])}</b>", st["cell"]),
                 Paragraph("<br/>".join(_e(x) for x in o["lines"]) or "—", st["cell"])]
            if show_prices:
                r += [Paragraph(_money(o["per_person"], cur), st["right"]), Paragraph(f"<b>{_money(o['sell'], cur)}</b>", st["right"])]
            rows.append(r)
        widths = [30 * mm, 84 * mm, 28 * mm, 32 * mm] if show_prices else [30 * mm, 144 * mm]
        flow += [Paragraph("Your hotel options", st["h2"]), _table(rows, widths)]
    if show_prices and not choosing:
        rows = [[Paragraph("Total trip cost" + (f" · {_e(T['chosen_option'])}" if T.get("chosen_option") else ""),
                           st["daytitle"]), Paragraph(_money(T["sell"], cur), st["price"])],
                [Paragraph(f"Per person ({T['travellers']} travellers)", st["meta"]),
                 Paragraph(_money(T["per_person"], cur), st["right"])]]
        if view["gst_pct"]:
            rows.append([Paragraph(f"Includes GST {view['gst_pct']:g}%", st["small"]), Paragraph("", st["small"])])
        pt = Table(rows, colWidths=[110 * mm, 64 * mm], hAlign="LEFT")
        pt.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), MIST), ("ROUNDEDCORNERS", [10, 10, 10, 10]),
                                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("LEFTPADDING", (0, 0), (-1, -1), 10),
                                ("RIGHTPADDING", (0, 0), (-1, -1), 10), ("TOPPADDING", (0, 0), (0, 0), 10),
                                ("BOTTOMPADDING", (0, -1), (-1, -1), 10)]))
        flow += [Paragraph("Price", st["h2"]), KeepTogether(pt)]
    if show_prices:
        if choosing and view["gst_pct"]:
            flow.append(Paragraph(f"Prices include GST {view['gst_pct']:g}%.", st["small"]))
        opts = [i for i in view["items"] if i["optional"]]
        if opts:
            rows = [[Paragraph("<b>Optional add-ons</b>", st["cellb"]), Paragraph("<b>Price</b>", st["right"])]]
            rows += [[Paragraph(_e(o["description"]) + (f" <font color='#5F6062'>({o['quantity']:g} × {_money(o['unit_amount'], o['currency'])})</font>" if o["quantity"] != 1 else ""), st["cell"]),
                      Paragraph(_money(o["amount"], o["currency"]), st["right"])] for o in opts]
            flow += [Spacer(1, 8), _table(rows, [134 * mm, 40 * mm])]
        if quote_cfg.get("payment_terms"):
            flow += [Spacer(1, 6), Paragraph(f"<b>Payment:</b> {_e(quote_cfg['payment_terms'])}", st["body"])]
        if quote_cfg.get("bank_details"):
            flow += [Paragraph(f"<b>Bank details:</b><br/>{_e(quote_cfg['bank_details'])}", st["body"])]

    terms = (view.get("terms") or []) + (quote_cfg.get("terms") or [])
    if terms:
        flow += [Paragraph("Good to know", st["h2"])] + _bullets(st, list(dict.fromkeys(terms)))
    flow += [Spacer(1, 8)] + _contact(st, company, preparer)
    if quote_cfg.get("footer"):
        flow += [Spacer(1, 10), Paragraph(_e(quote_cfg["footer"]), st["meta"])]
    doc.build(flow, onFirstPage=_decorate(company, note), onLaterPages=_decorate(company, note))
    return buf.getvalue()


# ------------------------------------------------------------------ package rate card (internal, net rates)
def package_pdf(p: dict, settings: dict) -> bytes:
    st = _styles()
    company = settings["company"]
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm, topMargin=16 * mm,
                            bottomMargin=22 * mm, title=p["title"], author=company.get("name"))
    flow = [_logo(46 * mm), Spacer(1, 8), Paragraph(_e(p["title"]), st["title"]),
            Paragraph(_e("  ·  ".join(x for x in [p.get("supplier"), p.get("region"), " → ".join(p.get("destinations") or []),
                                               f"{p.get('nights')}N/{p.get('days')}D" if p.get("nights") else None,
                                               f"valid {_fmt_date(p.get('valid_from'))} – {_fmt_date(p.get('valid_to'))}"] if x)), st["meta"]),
            Paragraph("INTERNAL RATE CARD · SUPPLIER NET RATES · NOT FOR CUSTOMERS", st["label"]), Spacer(1, 6)]
    g = p["price_grid"]
    if g["rows"]:
        head = [Paragraph(f"<b>Per person ({_e(g.get('currency') or '')})</b>", st["cellb"])] + \
               [Paragraph(f"<b>{_e(c)}</b>", st["right"]) for c in g["categories"]]
        rows = [head] + [[Paragraph(_e(r["label"]), st["cell"])] +
                         [Paragraph(f"{r['values'][c]:,.0f}" if r["values"].get(c) is not None else "–", st["right"])
                          for c in g["categories"]] for r in g["rows"]]
        w = 174 * mm
        flow += [Paragraph("Prices", st["h2"]), _table(rows, [50 * mm] + [(w - 50 * mm) / max(len(g["categories"]), 1)] * len(g["categories"]), zebra=True)]
    if p["itinerary"]:
        flow.append(Paragraph("Itinerary", st["h2"]))
        for d in p["itinerary"]:
            flow.append(Paragraph(f"<b>Day {d['day']}: {_e(d['title'])}</b>" +
                                  (f" <font color='#5F6062'>· {_e(d['overnight'])}</font>" if d.get("overnight") else ""), st["cell"]))
            flow += [Paragraph(_e(d.get("description") or ""), st["body"]), Spacer(1, 4)]
    for c in p.get("hotels_by_city", []):
        cats = list(c["categories"].items())
        head = [Paragraph(f"<b>{_e(k)}</b>", st["cellb"]) for k, _ in cats]
        body = [Paragraph("<br/>".join(_e(h["name"]) for h in v), st["cell"]) for _, v in cats]
        flow += [Paragraph(f"{_e(c['city'])} hotels" + (f" · {c['nights']} night(s)" if c.get("nights") else ""), st["h2"]),
                 _table([head, body], [174 * mm / max(len(cats), 1)] * len(cats))]
    if p.get("addons"):
        rows = [[Paragraph(f"<b>{x}</b>", st["cellb"]) for x in ("Add-on / service", "Basis", "Price")]]
        for a in p["addons"]:
            price = f"{a['amount']:,.0f}" + (f"–{a['amount_max']:,.0f}" if a.get("amount_max") else "") + f" {a['currency']}"
            basis = a["basis"].replace("_", " ") + (f" ({a['pax_max']} seats)" if a.get("pax_max") and a["basis"] == "per_vehicle" else "")
            rows.append([Paragraph(_e(a["name"]) + (f" <font color='#5F6062'>· {_e(a['notes'])}</font>" if a.get("notes") else ""), st["cell"]),
                         Paragraph(_e(basis), st["cell"]), Paragraph(_e(price), st["right"])])
        flow += [Paragraph("Add-ons & extra costs", st["h2"]), _table(rows, [100 * mm, 38 * mm, 36 * mm], zebra=True)]
    if p.get("inclusions"):
        flow += [Paragraph("Included", st["h2"])] + _bullets(st, p["inclusions"])
    if p.get("exclusions"):
        flow += [Paragraph("Not included", st["h2"])] + _bullets(st, p["exclusions"])
    note = f"Rate card #{p['id']} · {_fmt_date(date.today())}"
    doc.build(flow, onFirstPage=_decorate(company, note), onLaterPages=_decorate(company, note))
    return buf.getvalue()
