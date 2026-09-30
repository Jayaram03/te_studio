# 9 · Security, testing & production readiness

This is the state as of **30 Sep 2026**: what was tested, how, and what must be done at launch.

## Verdict

**Go for production** on Vercel Pro + Supabase (Mumbai), once the launch checklist below is done. The code, the database and the security controls are ready.

The one thing that could not be verified here is how accurately the AI reads **your own suppliers' real sheets**; the tests use saved example readings. So treat the first two weeks as a pilot:

- keep *Auto-approve* off;
- review every document before saving;
- start with 5–10 real sheets of different layouts;
- use *Edit data* and *Extra instructions* for anything a supplier's layout gets wrong.

## Automated tests

| Suite | Result | Where |
|---|---|---|
| Full test suite on PostgreSQL 16 | **132 passed** | `pytest -q` |
| Same suite through PgBouncer in transaction mode (like Supabase's pooler, port 6543) | **130 passed** (the 2 skipped tests create databases, which a pooler can't) | `TEST_DATABASE_URL=…:6543/…` |
| Real-browser run (Chromium) against a running demo app | **17 of 17 steps passed, no JavaScript errors** | `tests/browser/e2e_browser.py` |
| Upgrade of a real database from the previous version (schema 0002 → 0003, with data) | passed, data kept, packages became version 1 of their families | — |

What the suite covers:

- **File formats:**
  - PDF, Excel (`.xlsx` / `.xls`), CSV with `;` and Windows encoding, Word with merged cells and page headers, XML, HTML (including an "`.xls`" that is really HTML), JSON, text, photos;
  - long sheets split with their headers repeated;
  - damaged, empty, old-Word and unsupported files refused with clear messages.
- **Re-uploads**, using the Kashmir package:
  - a revised version becomes v2, replaces v1, and the price comparison is exact (9 cells up, 27 unchanged, +5%);
  - identical content changes nothing, and no rows are added;
  - a winter edition stays live beside the off-season one, and each travel date gets the right edition;
  - the reviewer can keep a look-alike as a separate package;
  - trips on v1 are told and can move to v2 at the new price;
  - add-ons changed or unchanged, hotel rate history, recent-changes feed.
- **Revised hotel sheet:** only the 2 changed rates are replaced; the other 70 rates, 2 supplements and 1 blackout are recognised as unchanged.
- **Review:**
  - nothing is saved before approval;
  - edits are re-checked;
  - invalid edits are refused;
  - cancel deletes the upload;
  - manual entry goes through the same checks;
  - undoing an approval restores the earlier rates *exactly* (checked row by row);
  - undo is refused when trips use the package or a later sheet built on it;
  - library corrections and retirement.
- **Suppliers:** detail page, editing, duplicate detection and merging.
- **Quotations:** numbering, versions, the snapshot staying unchanged after the trip changes, edit and save back, status (accepted confirms the trip), new trip from a quotation, delete, a quotation outliving its deleted trip, PDF, public client link.
- **Hotel options:** per-option totals, "from" price, the customer's choice driving the price and balance, every package category as options, WhatsApp text and PDF.
- **Templates:** saved from a trip, kept off the board, can't be quoted, start new trips repriced for new travellers.
- **AI:**
  - Claude and OpenAI-compatible calls (fake network);
  - the forced tool call;
  - the known-names context;
  - prompt caching and its cost accounting;
  - budget;
  - extra instructions.

## Security testing

| Area | Test | Result |
|---|---|---|
| Access control | Every one of the 80+ private routes, called without signing in | all refused (401 / redirect to sign-in) |
| Sessions | Forged cookie refused; cookie is `HttpOnly`, `SameSite=Lax`, `Secure` over HTTPS; only a SHA-256 hash of the token is stored | pass |
| Passwords | scrypt hashes; lockout after 5 wrong passwords; the same message for unknown email and wrong password | pass |
| Google sign-in | Stranger's account, unverified email, wrong audience, wrong issuer, replayed nonce, expired token, forged state, missing cookie, disabled admin: all refused; no open redirect after sign-in; tampered cookie refused | pass |
| CSRF | Changes without the `X-Requested-With` header refused | pass |
| XSS | `<script>` and `onerror=` typed into titles, names, days and costing lines: escaped on client pages and quotation pages; PDFs build fine | pass |
| SQL injection | `' or 1=1 --`, `'); drop table …`, `%`, `_`, `\` in every search | pass: all queries are parameterised |
| Uploads | Size limit (413), unsupported / damaged / renamed files, a `../../` file name (only a label; nothing is written to disk), an XML entity-expansion bomb | pass |
| Error leaks | An internal error with a "password" in its message | the user sees only *"Something went wrong… Reference: …"*; the detail goes to the log |
| Headers | CSP (`script-src 'self'`, no inline script), `X-Frame-Options: DENY`, `nosniff`, `Referrer-Policy`, HSTS on HTTPS, `no-store` on the API | pass |
| Secrets | `/api/users`, `/api/system`, `/api/ai/settings` never contain password hashes, secret key or saved AI keys | pass |
| Client links | 24+ random characters; wrong or turned-off link gives 404; share pages don't open the API | pass |
| Daily job | Refused without, or with the wrong, `CRON_SECRET` | pass |
| Static analysis (bandit) | 7,300 lines | 0 medium or high findings; 4 low, all reviewed as false positives (a URL, the "no password" marker, a deliberate try/except around logging) |
| Dependencies (pip-audit) | `requirements.txt` | no known vulnerabilities |
| Supabase | Data API locked with row-level security on every table; the app, as owner, still works | pass |

### Known limits (accepted)

- **Sign-in throttling is per account**, not per IP. The 5-try lockout plus Google sign-in make guessing impractical; add Vercel's firewall rate limits if you ever see attacks in the logs.
- **The ID token signature isn't re-verified.** The token comes straight from Google's token endpoint over TLS in exchange for the client secret, which OpenID Connect allows (Core 3.1.3.7).
- **Supabase Free has no backups.** Download the Excel backup weekly (Settings → Data), or move to Supabase Pro for daily backups.
- **Vercel limits:** 4.5 MB per upload and 300 s (Hobby) / 800 s (Pro) per document. Very large brochures should be split.

## Launch checklist

1. **Supabase:** a project in Mumbai; copy the Transaction pooler string ([guide 4](04-database-supabase.md)).
2. **Vercel Pro** project in Mumbai, with these variables ([guide 5](05-deploy.md)):
   - `DATABASE_URL`, `SECRET_KEY`, `CRON_SECRET`;
   - `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `PUBLIC_URL`;
   - **not** `FIXTURES_DIR`.
3. **Google OAuth client** with the redirect URI `https://studio.travelepisodes.in/auth/google/callback`, and the consent screen **published** ([guide 5](05-deploy.md#google-sign-in)).
4. Sign in as **travelepisodeschennai@gmail.com** with Google. Check that a non-admin Gmail is refused.
5. **Settings:**
   - AI connector: paste the Claude key, set prices and a monthly budget, *Test connection*;
   - Company and Quotes details;
   - add Rakesh and Jayaram (Google sign-in only).
6. **Settings → System** shows no warnings, and *Data API: locked*.
7. **Pilot:** upload 5–10 real sheets of different layouts, review and save them. Upload one of them again and check *already in the library*. Build one quote with hotel options and open its client link on a phone.
8. Download the first Excel backup, and put a weekly reminder in the calendar.
