# 3 · Configuration

Settings live in exactly **two places**:

| Where | What goes there | How to change it |
|---|---|---|
| **The app: Settings screens** (stored in the database) | Everything used day to day: company details, quote terms, team, admin users, the **AI connector** (provider, model, key, prices, budget, extra instructions), processing options | Change it on screen. It applies immediately on every server, with no redeploy. |
| **Server environment**: the `.env` file locally, or Vercel → Project → Settings → Environment Variables when hosted | The few things the app needs **before** it can open the database: the database address, the encryption secret, the first admin, and integration secrets | Edit, then restart (local) or redeploy (Vercel) |

**The one configuration file is `.env`.** Its template, `.env.example`, lists every server option with a comment explaining it. Copy it to `.env` and fill it in. `app/config.py` is the code that reads it, and the comments there match.

Settings → **System** shows which server settings are set, without ever showing their values.

## Server environment variables

**Required**

| Variable | Example / default | What it's for |
|---|---|---|
| `DATABASE_URL` | `postgresql://postgres.<ref>:<pw>@aws-0-ap-south-1.pooler.supabase.com:6543/postgres` | Where all data lives: **PostgreSQL only**. The app refuses to start without it. On Vercel, use Supabase's **Transaction pooler** (port 6543). On a laptop or server, use the **Session pooler** (port 5432) or the Docker database. SSL and pooler settings are applied automatically ([guide 4](04-database-supabase.md)). |
| `SECRET_KEY` | 48+ random characters | Encrypts AI keys saved in Settings. **Never change it**: if it changes, saved AI keys must be entered again. Generate one with `python -c "import secrets; print(secrets.token_urlsafe(48))"`. |
| `ADMIN_EMAIL`, `ADMIN_NAME`, `ADMIN_PASSWORD` | default `travelepisodeschennai@gmail.com`, `Travel Episodes`, empty | The first admin ([below](#first-admin)). |

**Recommended**

| Variable | Default | What it's for |
|---|---|---|
| `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` | empty | Turns on **Sign in with Google** ([guide 5](05-deploy.md#google-sign-in)). Only emails already added as admins get in. |
| `PUBLIC_URL` | empty | The Studio's address, e.g. `https://studio.travelepisodes.in`. Used for the Google redirect; without it the address of the request is used. |


| Variable | Default | What it's for |
|---|---|---|
| `CRON_SECRET` | empty | Protects the daily job in `vercel.json`. The job keeps a Supabase Free project from pausing and tidies up expired sign-ins. Vercel sends it automatically. |

**Optional**

| Variable | Default | What it's for |
|---|---|---|
| `API_KEY` | empty | Lets another system (e.g. your main website's server) call `/api/...` with the header `X-API-Key`. Leave empty if nothing else calls the app. |
| `CORS_ORIGINS` | empty | Websites allowed to call the API **from a browser**, comma-separated |
| `ENABLE_API_DOCS` | `false` | `true` shows the interactive API reference at `/api/docs` (admins only) |
| `ANTHROPIC_API_KEY` | empty | Claude key used when no key is saved in Settings → AI connector |
| `OPENAI_API_KEY`, `GEMINI_API_KEY`, `GROQ_API_KEY`, `OPENROUTER_API_KEY`, `CUSTOM_AI_API_KEY` | empty | Only if you pick that provider in Settings and prefer environment variables to saving the key in the app |
| `EXTRACTION_MODEL` | `claude-sonnet-5-5` | Model used when none is chosen in Settings |
| `EXTRACTION_MAX_TOKENS` | `32000` | Default maximum answer length (overridden in Settings) |
| `PROCESS_MODE` | `inline` | `inline` reads documents during the upload (**required on Vercel**). `background` is for normal servers. |
| `PDF_MODE`, `CHUNK_CHARS`, `DEFAULT_CURRENCY`, `WEEKEND_DAYS`, `AUTO_APPROVE`, `MAX_UPLOAD_MB`, `SESSION_DAYS` | see `.env.example` | Starting values only. **Settings → Processing overrides them.** |
| `FIXTURES_DIR` | empty | Demo mode: uploads use saved examples instead of AI. **Leave empty in real use.** |
| `LOG_LEVEL` | `INFO` | `DEBUG`, `INFO`, `WARNING`, `ERROR` |
| `LOG_FORMAT` | text | `json` writes one JSON object per line, for log tools |

## First admin

On the first start with an empty database, the app creates one admin:

| Setting | Result |
|---|---|
| nothing set | **travelepisodeschennai@gmail.com**, name *Travel Episodes*, **Google sign-in only**. Secure by default: only whoever owns that Gmail account can get in, and only once Google sign-in is set up. |
| `ADMIN_EMAIL=someone@…` | that email instead |
| `ADMIN_PASSWORD=…` (10+ characters) | the admin can also sign in with this password. Set it later and restart to add a password to a Google-only first admin. Remove it after use. |

Other admins are added in Settings → Team & sign-in (Google-only, or with a temporary password), or from the command line:

```bash
python -m app.cli create-admin --email rakesh@gmail.com --name Rakesh --google-only
python -m app.cli create-admin --email jayaram@gmail.com --name Jayaram          # asks for a password
```

The SQL way (Supabase → SQL Editor), for a Google-only admin:

```sql
insert into users (email, name, password_hash, role, active, failed_logins, must_change_password, created_at)
values ('rakesh@gmail.com', 'Rakesh', '!', 'admin', true, 0, false, now());
```

`'!'` means "no password": that account can only sign in with Google. Never put a real password in SQL; use the app or the CLI, which store a salted hash.

## Which value wins

- **AI key:** a key saved in Settings → AI connector wins over the environment variable. Remove the saved key to fall back to the environment.
- **Processing options and AI settings:** the value saved in Settings wins. The environment gives the value used until one is saved; Settings → Processing shows the default next to each option.
- **The first admin:** created once, only while there are no users. Later, `ADMIN_PASSWORD` can only add a password to that admin if it has none. Manage people in Settings → Team & sign-in.

## Settings screens: what each option does

**Company** (printed on quotes, PDFs and client links): name, tagline, address, email, Instagram handle, website, GSTIN.

**Quotes:**

- default markup %;
- default GST %;
- days a quotation is valid (printed on the PDF; after it, a draft or sent quotation is marked *expired* by the daily job);
- payment terms;
- bank details (printed on quotes);
- standard terms (one per line);
- closing line;
- **lead sources** (the list shown on trips and the dashboard).

**Team & sign-in:**

- team names and phones, printed as "Prepared by";
- admin users: add one as *Google sign-in only* or with a temporary password they must change; reset or give a password; disable (signs them out everywhere);
- change your own password.

**AI connector** ([guide 6](06-ai-connector.md)):

- provider;
- model;
- base URL (non-Claude providers);
- API key (stored encrypted), plus **Remove saved key**;
- AI reading on/off;
- max tokens per answer;
- scanned-PDF pages to send (non-Claude providers);
- price per 1M input and output tokens, and currency;
- monthly budget;
- **extra instructions**;
- **Test connection**.

**Processing:**

| Option | Values | Effect |
|---|---|---|
| PDF mode | `auto` / `text` / `native` | `auto`: text for normal PDFs, the file itself for scans. `native` suits odd layouts but uses more tokens. |
| Chunk size | 5,000–400,000 characters | Very long documents are read in parts of about this size |
| Default currency | e.g. `INR` | Used, with a warning, when a sheet doesn't state its currency |
| Weekend days | e.g. `fri,sat` | What "weekend" means on a rate sheet |
| Auto-approve | on / off | On: documents with no errors skip review. Keep it off; a human check protects margins. |
| Largest upload | MB | Vercel's hard limit is 4.5 MB |
| Sign-in length | 1–90 days | How long before admins must sign in again |

**Data:** full Excel backup; single-list CSVs.

**System** (read-only):

- database type, host, schema version, size;
- Supabase Data API lock status;
- which environment variables are set;
- app version;
- counts;
- warnings.

## Files at a glance

| File | Purpose |
|---|---|
| `.env.example` | Template for all server settings, with comments. Copy to `.env`. |
| `.env` | Your real settings. **Never commit it.** |
| `app/config.py` | Code that reads `.env` and the environment (same names, lowercase) |
| `vercel.json` | Vercel: Mumbai region (`bom1`), 300 s function limit, daily cron job |
| `pyproject.toml` | Tells Vercel where the app is (`app.api:app`) |
| `alembic.ini`, `app/migrations/` | Database migrations; they run automatically on start |
| `docker-compose.yml`, `Dockerfile` | Running with Docker on your own server |
