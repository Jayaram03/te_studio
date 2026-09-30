# 7 · Operations, security & troubleshooting

## Routine care

| When | Do | Where |
|---|---|---|
| Daily | Work the **Follow-ups due** list | Dashboard |
| Weekly | Download the **full backup (Excel)** and keep it off the laptop (Google Drive, email to yourself) | Settings → Data |
| Weekly | Review documents waiting in **Documents** (the sidebar badge shows how many) | Documents |
| Weekly | Look at **Catalog → Price changes**, and at trips with a *newer version* banner | Catalog, Trips |
| Monthly | **Suppliers**: merge any *possible duplicates* shown on supplier pages | Catalog → Suppliers |
| Monthly | `pg_dump` of the whole database ([guide 4](04-database-supabase.md#backups-and-restore)), until you're on Supabase Pro | Laptop |
| Monthly | Check AI cost against the budget, and the database size | Settings → AI connector, System |
| Monthly | **Rates running out**: ask those suppliers for new sheets | Tools, or the dashboard |
| When people leave | **Disable** their admin account. This signs them out everywhere at once. | Settings → Team & sign-in |

## Running costs (rough, at the time of writing)

| Item | Cost |
|---|---|
| Vercel Pro | $20 per member per month (required for business use) |
| Supabase | Free to start; Pro $25/month adds daily backups and 8 GB |
| AI | Pay per use. With a typical rate-sheet volume, a few dollars a month. The AI connector shows the real trend; set a budget there. |
| Domain | You already own it |

## Security

**Who can get in**

- Only admin accounts can sign in, with a password or with Google (same email). There's no public sign-up, and each admin is added by another admin.
- **Google sign-in:** OpenID Connect with PKCE, state and nonce. The ID token is checked for issuer, audience, expiry, nonce and verified email. Only an *existing, active* admin gets a session.
- Passwords are stored as salted **scrypt** hashes and never in readable form. They need at least 10 characters and can't contain the person's own name or email name.
- **5 wrong passwords** lock the account for 15 minutes. The error message never reveals whether an email exists.
- Sessions:
  - a random token in an `HttpOnly`, `SameSite=Lax` cookie (`Secure` over HTTPS);
  - only a hash of the token is stored;
  - they expire after *Sign-in length* (Settings → Processing);
  - they end on sign-out, on a password change, and when an account is disabled.
- **CSRF protection:** every change request must carry the `X-Requested-With` header, which other websites can't add. The web app sends it automatically.

**What's public**

- The sign-in page, the logo and fonts, and `/api/health`.
- **Client share links** (`/share/<random token>`): only the trips you chose to share, and prices only if you left them on. You can turn a link off at any time; the old link then shows "no longer active".
- The daily job URL, which refuses anything without `CRON_SECRET`.

**Browser protections** (on every response): a Content-Security-Policy that allows only the Studio's own scripts, `X-Frame-Options: DENY`, `nosniff`, a strict referrer policy (client-link tokens never leak to other sites), HSTS over HTTPS, and `no-store` on API answers.

**Uploads:** the real file type is detected from its content; damaged or unsupported files are refused before storing. XML is read with a parser that blocks entity-expansion attacks. Files are kept in the database and never written to disk or run.

**Secrets**

- AI keys saved in Settings are encrypted with `SECRET_KEY`.
- The database password lives only in `DATABASE_URL`, on Vercel or in `.env`.
- Settings → System shows *whether* each secret is set, never its value.
- On Supabase, the public Data API is locked out of every table ([guide 4](04-database-supabase.md)).

**Good habits**

- Give each person their own admin account; never share one.
- Share temporary passwords in person or on a call.
- Remove `ADMIN_PASSWORD` from Vercel after setup.
- Keep `SECRET_KEY`, `CRON_SECRET` and the database password in a password manager.
- Don't put `.env` in git, email or chat.

**Changing secrets**

| Secret | How | Side effect |
|---|---|---|
| Database password | Supabase → Project Settings → Database → Reset password. Then update `DATABASE_URL` in Vercel and redeploy. | The app is down between the two steps |
| `SECRET_KEY` | Change it in Vercel and redeploy | AI keys saved in Settings must be entered again |
| `CRON_SECRET`, `API_KEY` | Change in Vercel and redeploy | Update any system that uses `API_KEY` |
| An admin's password | Settings → Team & sign-in → Reset password | They're signed out and choose a new one |

## Logs

Every request gets one log line with a **request id**, the user, the status and the time taken. Errors are logged with their full detail. The person on screen only sees *"Something went wrong on our side. Reference: 7f3a2c1b"*.

```
2026-09-30 10:12:03 INFO  app.api [req=7f3a2c1b user=Rakesh] POST /api/documents 202 8123ms
2026-09-30 10:12:03 WARNING app.api [req=7f3a2c1b user=Rakesh] document 42 not read: This month's AI budget ... is used up
```

- **Where:** Vercel → Project → **Logs** (search for the reference). With Docker: `docker compose logs app`.
- `LOG_LEVEL=DEBUG` for more detail; `LOG_FORMAT=json` for log tools.
- Never logged: passwords, cookies, API keys, document contents.

## Mistakes and how to undo them

| Mistake | Fix |
|---|---|
| Uploaded the wrong file (not saved yet) | **Cancel upload** on the review screen |
| Saved a wrong sheet to the library | Documents → open it → **Take out of library**: its rates, packages and add-ons are removed and the rates it replaced come back exactly as they were. Refused if trips use its packages (move them to another version first) or a later sheet built on it (undo that first). |
| One rate is wrong | Catalog → hotel or add-on → **✎** correct it, or **Retire** it. The change is noted on the rate. |
| A package was matched to the wrong earlier package | Before saving: *This package is* → pick the right one or *a separate new package*. After saving: take it out of the library and save again with the right choice. |
| The same supplier appears twice | Supplier page → **Merge into this** |
| A quotation was sent with a mistake | Open it → *Edit quotation* → fix → *Save changes* (same number), or save a new version |

## Locked out

- **One admin forgot their password:** another admin → Settings → Team & sign-in → **Reset password**.
- **Locked by wrong passwords:** wait 15 minutes, or reset the password as above.
- **The only admin forgot their password,** or every admin is disabled. From a laptop with the code:

  ```bash
  # .env with DATABASE_URL = the Supabase SESSION pooler string (port 5432)
  python -m app.cli reset-password --email you@example.com     # also unlocks and re-enables the account
  # or add a new admin:
  python -m app.cli create-admin --email new@example.com --name "Name"
  ```

## Troubleshooting

| What you see | Likely cause | Fix |
|---|---|---|
| Vercel: *500 / Internal Server Error* on every page right after deploying | `DATABASE_URL` wrong or missing, or the Supabase project is paused | Check the variable (password filled in? port 6543?). Supabase dashboard → *Resume project* if paused. Read the error in Vercel → Deployments → the deployment → **Logs**. |
| `password authentication failed for user "postgres..."` | Wrong database password, or special characters not URL-encoded | Reset the password in Supabase, or encode `@` as `%40` and so on |
| `prepared statement "_pg3_…" already exists` | A pooled connection whose port isn't 6543, so it wasn't detected | Use the Transaction pooler string exactly as Supabase shows it |
| Upload fails with *413* or *FUNCTION_PAYLOAD_TOO_LARGE* | File over 4.5 MB on Vercel | Compress or split the PDF |
| Upload spins, then *504* / timed out | The document took more than 300 s | Lower Chunk size (Settings → Processing), split the PDF, or use Vercel Pro (800 s) |
| Document *failed* with an AI message | Key, budget or model issue | See [AI connector → Common errors](06-ai-connector.md#common-errors), then press **Try again** |
| Keeps returning to the sign-in page | Cookies blocked for the site, or the clock on the device is far off | Allow cookies for the Studio domain; check the device date |
| *Missing X-Requested-With header* (403) from your own integration | A script calling the API without the header | Send `X-API-Key: <API_KEY>` (integrations) or `X-Requested-With: yes` |
| Settings → System: *Data API open* | New tables added outside the app | Restart or redeploy the app; it locks them on start |
| Upload refused: *damaged or not really a .docx* | The file is broken or misnamed | Open it and save it again, or export it as PDF |
| *This is an old Word file (.doc)* | Word 97–2003 format | Save as `.docx` or PDF |
| Sign-in page: *That Google account isn't an admin here* | That email isn't in Team & sign-in (or is spelled differently) | Add it in Settings → Team & sign-in |
| Google: *redirect_uri_mismatch* | The redirect URI in Google Cloud doesn't match | Add `https://<your domain>/auth/google/callback` exactly, and set `PUBLIC_URL` |
| A trip shows *A newer version of … has been uploaded* | The supplier sent a revised package | Press **Use v2 and reprice** (or keep the old price if already confirmed) |
| Supabase says *project paused* | 7 quiet days on the Free plan and no `CRON_SECRET` | Resume it in Supabase, then set `CRON_SECRET` in Vercel so the daily job keeps it awake |

**Where to look**

- **App errors:** Vercel → Project → **Logs**. Filter by status 500 or search for the route.
- **Database errors:** Supabase → **Logs** → Postgres.
- **AI calls:** Settings → AI connector → Recent AI calls. Hover *failed* for the reason.
- **One document:** open it in Documents; the reason is shown at the top.
