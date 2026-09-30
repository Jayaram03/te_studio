# 1 · User guide

Travel Episodes Studio keeps every supplier rate in one place, knows when a supplier sends a new version, and turns it all into priced, branded quotations. The daily loop:

**upload a rate sheet → review what was read (edit if needed) → save to library → build a trip → save a quotation → share → follow up → record payment.**

Only admins can sign in. Ask an existing admin to add you (Settings → Team & sign-in).

---

## Signing in

- Open the Studio (for example `https://studio.travelepisodes.in`).
- **Sign in with Google** (when it's set up): press the Google button and pick the Google account whose email an admin added for you. Any other Google account is refused with *"isn't an admin here"*.
- **Or with a password**, if an admin gave you one. The first time, you choose your own password.
- **5 wrong passwords** lock the account for 15 minutes. That's a safety measure, not an error.
- **Forgot your password?** Another admin resets it (Settings → Team & sign-in). Google sign-in keeps working anyway. If you are the only admin, see [Operations](07-operations.md#locked-out).
- Sign out from the bottom of the left sidebar, especially on shared computers.

The first admin is **travelepisodeschennai@gmail.com** (Google sign-in). See [Configuration](03-configuration.md#first-admin) to change that.

---

## Dashboard

- **Greeting bar:** follow-ups due and open enquiries, with shortcuts.
- **This month:** enquiries, total quoted, total confirmed, markup earned, conversion rate, balance to collect.
- **Follow-ups due:** today's and overdue follow-ups, with call and WhatsApp buttons.
- **Pipeline, lead sources, departures in 30 days, rate library status** (documents waiting, rates expiring soon).

---

## Documents: getting rates in

### Upload

**Documents → drop files.** Any of these, in any layout:

| Format | Notes |
|---|---|
| PDF | Text PDFs are read directly; scanned PDFs and photos are read visually by the AI |
| Excel `.xlsx` `.xls`, CSV / TSV | Every visible sheet; merged header cells understood; `;` separators and Windows encodings handled |
| Word `.docx` | Paragraphs, tables and page headers (validity is often printed there). A Word file that only wraps a scanned picture is sent as the picture. |
| XML, HTML, JSON, TXT | Booking-system exports and saved web pages; an "`.xls`" that is really a web page is detected |
| Photos (JPG, PNG, WEBP) | Photos of rate cards, WhatsApp screenshots |

Old `.doc`, `.odt`, `.rtf` or iPhone `.heic`: the app tells you to save it as `.docx`, PDF or JPG first. Damaged files are refused with a clear message, before anything is stored.

Optionally type the **supplier** first. The AI is then given the names that supplier used in earlier sheets, so repeats are spelled the same way and match cleanly.

### Review: nothing is saved until you say so

Click a document. The review screen has three tabs.

**Review**

- **What was found:** counts of hotel rates, package prices, hotels, add-ons and places.
- **What saving will change**, worked out against your library:

  | Label | Meaning |
  |---|---|
  | *new* | not in the library yet |
  | *price up* / *price down* | same room, meal plan, occupancy and dates (or same service) at a new price. The old rate is kept as history. |
  | *new season (compared with last)* | new dates, compared with the same season last time |
  | *same price, new dates* | validity extended |
  | *already in the library (skipped)* | identical: **not stored again** |
  | *older rates replaced or trimmed* | earlier rates whose dates the new sheet takes over |

  When a document changes nothing, it says so plainly.
- **Packages:** "→ version 2" when it's a new version of a package you already have, with how many prices went up or down. The **This package is** menu lets you correct the match: *new version of …* (automatic), a different family, or *a separate new package*.
- **Checks:**
  - **Must fix** (red) blocks saving. Examples: unreadable dates, two prices for the same room and dates.
  - **Check** (yellow) is worth a look. Examples: currency not stated, 8 pax costing more per person than 6 pax.
- **Fill in what the document doesn't say:** validity, currency, net or rack, taxes, approved by. Press **Check again**.
- **Everything that was read:** all the data laid out as tables, to compare with the original (**open original**).

**Edit data** — fix or add anything:

- every rate, supplement, blackout, package price, hotel, itinerary day, add-on and place is an editable cell;
- **+ Add row**, **⎘** copy a row, **✕** delete a row, **+ Add hotel / package**, **Delete hotel / package**;
- **Save edits & check again** re-runs every check and the change preview. **Undo my edits** goes back.
- While edits are unsaved, *Save to library* is locked so nothing half-edited is saved.

**What changes** — every change line by line (old price, new price, %, dates), and for a package the full price grid with old prices struck through. Tick *show unchanged* to see the skipped ones too.

### The buttons

| Button | What it does |
|---|---|
| **Save to library** | Loads it. Only now does anything change. |
| **Check again** | Re-runs the checks with what you filled in |
| **Read again** | Sends the file to the AI again (after changing AI settings or instructions) |
| **Reject** | Keeps the record but uses nothing |
| **Cancel upload** | Deletes the upload and everything read from it |
| **Take out of library** (after saving) | Removes what it added and **puts back the earlier rates exactly**. Refused if trips use its packages, or if a later sheet already built on it (undo that one first). |

### Enter rates by hand

**Documents → Enter rates by hand.** For a rate you got on the phone or on WhatsApp. Pick the supplier and what you're entering; the same editor opens with a blank row, and it goes through the same checks, preview and save.

### When a supplier sends a new or revised sheet

You don't need to do anything special. Upload it and the app:

- matches hotels, rooms and add-ons to what you have, even if they're worded a little differently;
- **stores only what changed**. Unchanged rates are skipped, not duplicated.
- replaces only the overlapping dates of older rates; the rest stay valid;
- keeps every older rate as history, linked to the new one with the % change;
- makes a revised package **version 2** of the same package. The old version is *replaced* if the new one covers its dates; an edition for other dates (for example a winter version) stays live next to it.
- warns on every trip that still uses an old version (see [Trips](#newer-package-versions)).

> Tip: if one supplier's sheets keep coming out wrong, add a rule in Settings → AI connector → **Extra instructions**, for example *"Abdaal Travels prices are always net B2B."*, then **Read again**.

---

## Catalog

Tabs: **Packages · Hotels · Activities & transfers · Places · Suppliers · Price changes**.

- **Packages:** one card per package, even after several uploads. Cards show:
  - the version (*v2*);
  - the price change against the previous version;
  - other live editions (*Also: Kashmir Winter 5N/6D, Nov – Mar*).

  With a travel date, only the edition sold on that date is shown. The package page has:
  - the price grid, itinerary, hotels by city and category, add-ons, inclusions and exclusions;
  - **Quick price** for any group and date;
  - **Versions:** every version with dates, state and source sheet, a **price trend chart** per category, and the price grid compared with the previous version;
  - a banner if a newer version exists.
- **Hotels:** open a hotel for:
  - **live rates**, filterable by room and meal plan, each with a state (*current*, *upcoming*, *expired*) and its change against before;
  - **✎** to correct a rate by hand, or **Retire** it. The edit is noted on the rate.
  - **Rate history:** a timeline chart (pick room, meal plan and occupancy). Each bar is a rate over its dates; dashed grey bars were replaced by a newer sheet. Hover a bar for its amount and source file.
  - **Price changes** table: before → now, %, dates, the sheet it came from.
- **Activities & transfers:** every add-on with its % change, and ✎ to correct.
- **Suppliers:** click one for its page:
  - contact details, editable, with Call, WhatsApp and *Ask for new rates* (email) buttons;
  - rates valid until;
  - its packages, hotels, add-ons and every sheet received, with what each sheet changed;
  - **Possible duplicates** (similar name, same GSTIN, email or phone), with **Merge into this**: everything moves across and the duplicate disappears. You can also merge any supplier by hand.
- **Price changes:** everything that went up or down in the last 30 / 90 / 180 / 365 days, with averages, package updates and the source sheets.
- **Export:** CSV of any list, or the whole library as one Excel file.

---

## Trips

### Board, list and templates

**Trips** shows the board **enquiry → quoted → confirmed → completed / lost**. Cards show the value ("from …" when there are hotel options) and how many quotations were saved. You can also switch to **List**, or to **Templates**: your own ready-made itineraries.

### New trip

Enter the customer, lead source, who's handling it, follow-up date, travellers, markup and GST. **Start from:**

- **a supplier package** and its hotel category. Tick **quote every category as options** to get Standard / Deluxe / Premium / Luxury as options in one quote.
- **one of your templates**: its itinerary and costing, repriced for these travellers and dates.
- **nothing**: build it day by day.

### The trip workspace

- **Trip details:** dates, travellers, markup, GST. **Save & reprice** recalculates everything from the live rates.
- **Itinerary:** edit, reorder, remove days. **Days from other packages** inserts any day from any package, which is how combined itineraries are built.
- **Costing:**
  - **+ Activity / transfer:** per person, or per vehicle with the number of cabs worked out from the seats.
  - **+ Hotel stay:** priced night by night across seasons, with supplements and blackout checks.
  - **+ Package price:** optionally every category as options.
  - **+ Custom line.**
  - **add-on** marks an item as optional, not counted in the total.
  - A **negotiated unit price** stays when repricing.
  - **Suggested add-ons** come from this trip's suppliers.

### Hotel options: several hotels in one quote

To let the customer choose between hotels, give each hotel line an **Option** (column in the costing, or the *Hotel option* field when adding). Examples: *Option A · Deluxe* and *Option B · Premium*, or *Standard* / *Deluxe*.

- Lines without an option (cab, activities) belong to every option.
- The **Price** panel shows each option's total and per-person price; the headline is the cheapest, shown as "from".
- When the customer decides, tick their option. The trip price, payments and balance then follow it.
- The quote PDF, the client link and the WhatsApp text show a **"Your hotel options"** table: each option with its hotels and price.

### Newer package versions

If a trip uses a package for which a newer version was uploaded, a banner says so: **Use v2 and reprice**. That moves its price lines and days to the new version. Days you edited keep your text; untouched days take the new version's text.

### Quotations

- **Save as quotation** (Quotations card, or More) keeps a numbered copy, **TE-Q-2026-0007**, of the itinerary, costing, options and totals exactly as they are now. It has its own PDF and client link.
- The next save is **version 2**, and so on. Every version stays in the history.
- Saving the first quotation moves an enquiry to *quoted*.

### Templates

**More → Save as template** keeps a copy of this trip's itinerary and costing, without the customer, as your own package to re-use. Templates are listed under Trips → Templates and in **New trip → Start from**.

### Share and download

- **Share:**
  - client link: a private page with a *Download PDF* button;
  - send on WhatsApp or by email;
  - copy the itinerary as text;
  - show or hide prices;
  - turn off the link: the old link stops working at once.
- **Download:** quote PDF (with prices), itinerary PDF (without), Excel, CSV.

### Sale, payments and notes

- Status, who's handling it, follow-up date, lead source and *why lost* go in the right-hand panel. Every status change is logged.
- Record payments by UPI, bank, card or cash; the balance follows the chosen option.
- The notes log records calls and messages. Set the next follow-up date there.

---

## Quotations

The **Quotations** page lists every quotation saved: number, version, trip, customer, status, date saved, validity (red when past), total ("from" with options). Search by number, customer, trip or destination, or filter by status.

A quotation's page shows it exactly as sent: days, costing, options, price. From there you can:

- **Edit quotation:** loads it back into its trip, replacing the trip's current plan (you're asked first). A banner then offers **Save changes to TE-Q-…**, which keeps the same number, or **Save as quotation**, which makes a new version.
- **New trip from this:** the same plan for another customer.
- **Status:**
  - *draft → sent → accepted / declined*;
  - *expired* is set automatically after the **valid until** date (default 7 days, Settings → Quotes);
  - *accepted* confirms the trip;
  - record which option the customer chose, and an internal note.
- **PDF**, **client link**, **WhatsApp**.
- **Delete quotation:** the trip stays. Deleting a trip keeps its quotations as history.

---

## Tools

- **Price a hotel stay:** any hotel, rooms and dates, night by night, with markup.
- **Rates running out:** suppliers to ask for new sheets.

---

## Settings

| Tab | What's there |
|---|---|
| Company | Name, address, GSTIN, contact, used on every PDF and client page |
| Quotes | Default markup and GST, quotation validity (days), terms, payment terms, bank details, footer |
| Team & sign-in | People printed as "Prepared by"; **admin users**. Add an admin as *Google sign-in only* (no password to share) or with a temporary password. Disable, reset password. |
| AI connector | Provider (Claude by default), model, key, prices, monthly budget, extra instructions; token and cost charts ([guide 6](06-ai-connector.md)) |
| Processing | PDF mode, chunk size, default currency, weekend days, auto-approve, sign-in length, largest upload |
| Data | Downloads, including the full Excel backup |
| System | Database, server settings (set or not, never the values), warnings |
