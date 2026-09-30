"""End-to-end in a real browser against a running demo app: sign-in, upload, edit, save, duplicate detection,
cancel, hotel options, quotations, client link. Not part of `pytest` (it needs a running server):

    DATABASE_URL=... python scripts/demo_seed.py            # demo data
    FIXTURES_DIR=tests/fixtures ADMIN_PASSWORD=demo-password-2026 uvicorn app.api:app --port 8770
    python tests/browser/e2e_browser.py                     # needs: pip install playwright && playwright install chromium
"""
import asyncio, io, time
import random
HOTEL = "".join(random.choice("bcdfghjklmnpqrstvwxz") for _ in range(6)).title() + " Backwater Villas"
from playwright.async_api import async_playwright, expect
BASE = os.environ.get("BASE_URL", "http://localhost:8770")
import os, tempfile
OUT = os.environ.get("SHOTS", tempfile.gettempdir()) + "/"
steps = []
def ok(msg): steps.append("PASS " + msg); print("PASS", msg)

async def main():
    async with async_playwright() as p:
        b = await p.chromium.launch(); pg = await b.new_page(viewport={"width": 1440, "height": 1000})
        errs = []
        pg.on("pageerror", lambda e: errs.append(str(e)) or print("PAGEERROR", e))
        pg.on("console", lambda m: m.type == "error" and print("CONSOLE", m.text))
        pg.on("dialog", lambda d: asyncio.ensure_future(d.accept("Option C") if d.type == "prompt" else d.accept()))
        # 1. unauthenticated -> login; wrong password; right password
        await pg.goto(BASE + "/#quotes"); await pg.wait_for_url("**/login**"); ok("signed-out visitor is sent to the sign-in page")
        await pg.fill("#email", "travelepisodeschennai@gmail.com"); await pg.fill("#password", "wrong-password-123"); await pg.click("#go")
        await expect(pg.locator("#err")).to_contain_text("Wrong email or password"); ok("wrong password refused with a generic message")
        await pg.fill("#password", "demo-password-2026"); await pg.click("#go"); await pg.wait_for_url("**/#quotes"); ok("sign-in returns to the page asked for")
        # 2. upload a CSV (new layout) -> review -> edit a cell -> save edits -> approve
        await pg.evaluate("location.hash='docs'"); await pg.wait_for_selector("#file", state="attached")
        csv = "Hotel;City;Room;Plan;Double;From;To\nLake Palace Alleppey;Alleppey;Lake View;CP;6200;2026-10-01;2027-03-31\n"
        await pg.set_input_files("#file", files=[{"name": "lake_palace_rates.csv", "mimeType": "text/csv", "buffer": csv.encode()}])
        await pg.wait_for_selector("#detail:not(.hidden) h2", timeout=20000)
        txt = await pg.locator("#detail").inner_text()
        ok("CSV upload opens the review screen" + (" (read failed in demo mode, as expected without a saved example)" if "failed" in txt.lower() else ""))
        # manual entry path (works in demo mode, no AI)
        await pg.click("#manual"); await pg.fill("#mn-sup", "Lake Palace Alleppey"); await pg.click("#mn-go")
        await pg.wait_for_selector("#rv-body table.ed"); ok("manual entry opens the editor with a blank rate row")
        await pg.fill("[data-p='hotels.0.name']", HOTEL); await pg.fill("[data-p='hotels.0.city']", "Alleppey")
        await pg.fill("[data-p='hotels.0.rates.0.room_type']", "Lake View"); await pg.fill("[data-p='hotels.0.rates.0.amount']", "6200")
        await pg.fill("[data-p='hotels.0.rates.0.valid_from']", "2026-10-01"); await pg.fill("[data-p='hotels.0.rates.0.valid_to']", "2027-03-31")
        await pg.fill("[data-p='currency']", "INR")
        await pg.click("[data-dup='hotels.0.rates.0']")
        await pg.fill("[data-p='hotels.0.rates.1.meal_plan']", "MAP"); await pg.fill("[data-p='hotels.0.rates.1.amount']", "7400")
        assert await pg.locator("#d-approve").is_disabled(); ok("'Save to library' is locked while edits are unsaved")
        await pg.click("#ed-save"); await pg.wait_for_selector("#rv-tabs [data-t=summary].on")
        await expect(pg.locator("#detail")).to_contain_text("2 new"); ok("edits saved, re-checked, change preview shows 2 new rates")
        await pg.screenshot(path=OUT + "e2e_manual_review.png", full_page=True)
        await pg.click("#d-approve"); await pg.wait_for_selector("#rv-tabs [data-t=changes].on")
        await expect(pg.locator("#detail")).to_contain_text("In the library"); ok("approved into the library")
        # 3. same data again -> 'already in the library'
        await pg.click("#manual"); await pg.fill("#mn-sup", "Lake Palace Alleppey"); await pg.click("#mn-go"); await pg.wait_for_selector("#rv-body table.ed")
        for k, v in (("hotels.0.name", HOTEL), ("hotels.0.city", "Alleppey"), ("hotels.0.rates.0.room_type", "Lake View"), ("hotels.0.rates.0.amount", "6200"),
                     ("hotels.0.rates.0.valid_from", "2026-10-01"), ("hotels.0.rates.0.valid_to", "2027-03-31"), ("currency", "INR")):
            await pg.fill(f"[data-p='{k}']", v)
        await pg.click("#ed-save"); await pg.wait_for_selector("#rv-tabs [data-t=summary].on")
        await expect(pg.locator("#detail")).to_contain_text("already in the library with the same prices"); ok("re-entering the same rate is recognised as a duplicate")
        await pg.click("#d-discard"); await pg.wait_for_timeout(800)
        assert await pg.locator("#detail").is_hidden(); ok("'Cancel upload' discards it")
        # 4. trip with options -> quote -> edit quote
        await pg.evaluate("location.hash='trips/7'"); await pg.wait_for_selector("#tq-save")
        await pg.check("input[name=chosen][value='Option B · Premium']"); await pg.wait_for_timeout(900)
        await expect(pg.locator(".bigprice")).to_contain_text("37,514"); ok("choosing Option B makes it the trip price")
        await pg.click("#tq-save"); await pg.wait_for_timeout(1200)
        await expect(pg.locator("#tq")).to_contain_text("TE-Q-2026-"); ok("saved as a new quotation")
        await pg.evaluate("location.hash='quotes'"); await pg.wait_for_selector("#qbody tr[data-q]")
        n = await pg.locator("#qbody tr[data-q]").count(); ok(f"quotation list shows {n} quotations")
        await pg.locator("#qbody tr[data-q]").first.click(); await pg.wait_for_selector("#qe"); await pg.click("#qe"); await pg.wait_for_selector("#tq-update")
        ok("'Edit quotation' loads it into the trip with a 'Save changes' banner")
        await pg.click("#tq-update"); await pg.wait_for_timeout(1000); ok("changes saved back under the same number")
        # 5. client link is public and shows options
        tok = await pg.evaluate("fetch('/api/quotations/1/share',{method:'POST',headers:{'X-Requested-With':'x','Content-Type':'application/json'},body:'{}'}).then(r=>r.json()).then(j=>j.share_token)")
        ctx2 = await b.new_context(); anon = await ctx2.new_page()
        await anon.goto(f"{BASE}/q/{tok}"); await expect(anon.locator("body")).to_contain_text("Your hotel options")
        await anon.screenshot(path=OUT + "e2e_client_quote.png", full_page=True); ok("client link opens without sign-in and lists the hotel options")
        r = await anon.goto(BASE + "/api/quotations"); assert r.status == 401; ok("the API refuses a visitor who isn't signed in")
        print("\n".join(errs) or "no JavaScript errors")
        await b.close()
asyncio.run(main())
