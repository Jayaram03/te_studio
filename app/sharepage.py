"""The public page a customer opens from a shared link: /share/<token>. Read-only, no API key."""
from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

import html
from datetime import date


def _e(s) -> str:
    return html.escape(str(s or ""))


def _money(n, cur) -> str:
    if n is None:
        return ""
    v = int(Decimal(str(n)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    if cur == "INR":
        s = str(abs(v))
        head, tail = s[:-3], s[-3:]
        parts = []
        while len(head) > 2:
            parts.insert(0, head[-2:])
            head = head[:-2]
        if head:
            parts.insert(0, head)
        return "₹" + (",".join(parts) + "," + tail if parts else tail)
    return f"{cur} {v:,}"


def _d(iso) -> str:
    return date.fromisoformat(iso).strftime("%d %b %Y").lstrip("0") if iso else ""


def render(v: dict, settings: dict, preparer: dict | None, token: str, base: str = "/share") -> str:
    from .trips import options_display, shown_items
    c, q = settings["company"], settings["quote"]
    options = options_display(v)
    choosing = bool(options) and not v["totals"].get("chosen_option")
    T, cur = v["totals"], v["totals"]["currency"]
    show = v["share_prices"]
    kids = v["children_with_bed"] + v["children_without_bed"]
    pax = f"{v['adults']} adult{'s' if v['adults'] != 1 else ''}" + (f", {kids} child{'ren' if kids != 1 else ''}" if kids else "")
    nights = max(len(v["days"]) - 1, 0)
    hotels = [h for i in shown_items(v) if i["kind"] == "package" for h in i["details"].get("hotels", [])]
    by: dict = {}
    for h in hotels:
        by.setdefault((h["city"], h["nights"]), []).append(h["hotel"])
    stays = [i for i in shown_items(v) if i["kind"] == "hotel"]
    opts = [i for i in v["items"] if i["optional"]]
    phone = (preparer or {}).get("phone", "")
    wa = "".join(ch for ch in phone if ch.isdigit())
    days_html = "".join(f"""<article class="day"><div class="num">{d['position']:02d}</div><div>
        <h3>{_e(d['title'])}</h3><p class="meta">{_e(' · '.join(x for x in [_d(d['date']), d['overnight'] and 'Overnight: ' + d['overnight'], d['meals'] and 'Meals: ' + d['meals']] if x))}</p>
        <p>{_e(d['description'])}</p></div></article>""" for d in v["days"])
    stay_rows = "".join(f"<tr><td>{_e(city)}</td><td>{_e(n)}</td><td>{_e(', '.join(names[:4]))} or similar</td></tr>"
                        for (city, n), names in by.items()) + "".join(
        f"<tr><td colspan='3'>{_e(s['description'])}</td></tr>" for s in stays)
    lst = lambda xs: "".join(f"<li>{_e(x)}</li>" for x in xs)
    terms = list(dict.fromkeys((v.get("terms") or []) + (q.get("terms") or [])))
    ig = (c.get("instagram") or "").lstrip("@")
    price_html = ""
    if choosing:
        rows = "".join(f"<tr><td><b>{_e(o['label'])}</b></td><td>{'<br>'.join(_e(x) for x in o['lines']) or '—'}</td>"
                       + (f"<td style='text-align:right'>{_money(o['per_person'], cur)}</td><td style='text-align:right'>"
                          f"<b>{_money(o['sell'], cur)}</b></td>" if show else "") + "</tr>" for o in options)
        price_html = ("<h2>Your hotel options</h2><table><tr><th>Option</th><th>Hotels and what differs</th>"
                      + ("<th style='text-align:right'>Per person</th><th style='text-align:right'>Total</th>" if show else "")
                      + "</tr>" + rows + "</table>")
    if show and not choosing:
        gst_note = f" · includes GST {v['gst_pct']:g}%" if v["gst_pct"] else ""
        price_html = (f'<h2>Price</h2><div class="price"><div>Total for {_e(pax)}<br><span class="sub">'
                      f'{_money(T["per_person"], cur)} per person{gst_note}</span></div>'
                      f'<div class="big">{_money(T["sell"], cur)}</div></div>')
    if show:
        if opts:
            rows = "".join('<tr><td>' + _e(o["description"]) + '</td><td style="text-align:right">'
                           + _money(o["amount"], o["currency"]) + '</td></tr>' for o in opts)
            price_html += "<h2>Optional add-ons</h2><table>" + rows + "</table>"
        if q.get("payment_terms"):
            price_html += "<p><b>Payment:</b> " + _e(q["payment_terms"]) + "</p>"
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{_e(v['title'])} · {_e(c.get('name'))}</title><link rel="icon" href="/static/brand/favicon.png">
<meta property="og:title" content="{_e(v['title'])}"><meta property="og:description" content="{_e(v.get('destination') or '')} · {_e(pax)} · {_e(c.get('name'))}">
<style>
@font-face{{font-family:Poppins;src:url(/static/fonts/Poppins-Regular.ttf);font-weight:400}}
@font-face{{font-family:Poppins;src:url(/static/fonts/Poppins-Medium.ttf);font-weight:500}}
@font-face{{font-family:Poppins;src:url(/static/fonts/Poppins-Bold.ttf);font-weight:700}}
@font-face{{font-family:Poppins;src:url(/static/fonts/Poppins-Light.ttf);font-weight:300}}
:root{{--lav:#8286cb;--org:#ef712c;--ink:#4f4c4d;--mut:#5f6062;--mist:#e2e3f3;--soft:#a5a4d4;--cream:#fae7b6}}
*{{box-sizing:border-box}}body{{margin:0;font:15px/1.65 Poppins,system-ui,sans-serif;color:var(--ink);background:#fff}}
.wrap{{max-width:860px;margin:0 auto;padding:28px 18px 60px;position:relative}}
.tab{{position:fixed;left:-26px;top:180px;width:48px;height:170px;border-radius:9999px;background:var(--lav)}}
.dots{{position:absolute;right:18px;top:24px;display:grid;grid-template-columns:repeat(8,6px);gap:8px 11px}}
.dots i{{width:5px;height:5px;border-radius:50%;background:var(--lav)}}.dots i:nth-child(n+9):nth-child(-n+16),.dots i:nth-child(n+25){{background:var(--org)}}
header img{{height:64px}}h1{{font-size:clamp(26px,5vw,38px);line-height:1.15;margin:26px 0 4px;font-weight:700}}
.sub{{color:var(--mut)}}.glance{{display:flex;flex-wrap:wrap;gap:0;background:var(--mist);border-radius:24px;padding:16px 8px;margin:22px 0}}
.glance div{{flex:1 1 140px;padding:4px 14px}}.glance small{{display:block;font-size:11px;font-weight:300;letter-spacing:.04em;text-transform:uppercase;color:var(--mut)}}
.glance b{{font-weight:500}}h2{{font-size:21px;margin:36px 0 12px}}
.day{{display:grid;grid-template-columns:56px 1fr;gap:10px;padding:14px 0;border-bottom:1px solid var(--mist)}}
.day .num{{font-size:28px;font-weight:700;color:var(--org);line-height:1}}.day h3{{margin:0;font-size:17px;font-weight:500}}
.day .meta{{margin:2px 0 6px;color:var(--mut);font-size:13px}}.day p{{margin:0}}
table{{width:100%;border-collapse:collapse}}th,td{{text-align:left;padding:9px 10px;border-bottom:1px solid var(--mist);vertical-align:top}}
th{{background:var(--mist);font-weight:500}}.cols{{display:grid;grid-template-columns:1fr 1fr;gap:24px}}
ul{{padding-left:18px}}li{{margin:3px 0}}.price{{background:var(--mist);border-radius:24px;padding:20px 24px;display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:10px}}
.price .big{{font-size:34px;font-weight:700;color:var(--org)}}.btns{{display:flex;flex-wrap:wrap;gap:10px;margin:18px 0}}
.btn{{display:inline-block;cursor:pointer;font-family:inherit;padding:10px 18px;border-radius:9999px;background:var(--ink);color:#fff;font-weight:700;text-decoration:none;font-size:15px}}
.btn.alt{{background:#fff;color:var(--ink);border:1.5px solid var(--soft)}}.contact{{background:var(--cream);border-radius:24px;padding:20px 24px;margin-top:34px}}
.contact a{{color:var(--ink)}}@media(max-width:640px){{.cols{{grid-template-columns:1fr}}.tab{{display:none}}}}
@media print{{.btns,.tab{{display:none}}}}
</style></head><body><div class="tab"></div><div class="wrap">
<div class="dots">{'<i></i>' * 32}</div>
<header><img src="/static/brand/logo.png" alt="{_e(c.get('name'))}"></header>
<h1>{_e(v['title'])}</h1><div class="sub">{_e(' · '.join(x for x in [v.get('customer_name') and 'Prepared for ' + v['customer_name'], v.get('start_date') and _d(v['start_date']) + ' – ' + _d(v['end_date'])] if x))}</div>
<div class="glance"><div><small>Destination</small><b>{_e(v.get('destination') or '—')}</b></div>
<div><small>Duration</small><b>{nights} nights / {len(v['days'])} days</b></div><div><small>Travellers</small><b>{_e(pax)}</b></div>
<div><small>Hotels</small><b>{_e(v.get('category') or 'As listed')}</b></div>{f"<div><small>{'From, per person' if choosing else 'Per person'}</small><b>{_money(T['per_person'], cur)}</b></div>" if show and T.get('per_person') else ''}</div>
<div class="btns"><a class="btn" href="{base}/{_e(token)}/pdf">Download PDF</a>{f'<a class="btn alt" href="https://wa.me/{wa}?text={_e("Hi, about " + v["title"])}">WhatsApp us</a>' if wa else ''}
<button class="btn alt" id="print" type="button">Print</button></div>
<h2>Day by day</h2>{days_html}
{f"<h2>Where you stay</h2><table><tr><th>Place</th><th>Nights</th><th>Hotel</th></tr>{stay_rows}</table>" if stay_rows else ''}
<div class="cols"><div>{f"<h2>Included</h2><ul>{lst(v['inclusions'])}</ul>" if v['inclusions'] else ''}</div><div>{f"<h2>Not included</h2><ul>{lst(v['exclusions'])}</ul>" if v['exclusions'] else ''}</div></div>
{price_html}
{f"<h2>Good to know</h2><ul>{lst(terms)}</ul>" if terms else ''}
<div class="contact"><b>Talk to us</b><br>{_e((preparer or {}).get('name') or c.get('name'))}{' · <a href="tel:' + _e(phone) + '">' + _e(phone) + '</a>' if phone else ''}<br>
{f'<a href="mailto:{_e(c["email"])}">{_e(c["email"])}</a><br>' if c.get('email') else ''}{f'<a href="https://www.instagram.com/{_e(ig)}/">@{_e(ig)}</a><br>' if ig else ''}
<span class="sub">{_e(c.get('address')).replace(chr(10), '<br>')}</span></div>
<p class="sub" style="margin-top:22px">{_e(q.get('footer'))}</p></div><script src="/static/share.js"></script></body></html>"""
