# 2 · Set up on your computer

This gets the Studio running on your laptop, so you can try it or change the code. To put it online, see [guide 5](05-deploy.md).

## What you need

| Tool | Version | Check with | Get it |
|---|---|---|---|
| Python | 3.11 or newer | `python3 --version` | python.org, or `brew install python` / `winget install Python.Python.3.12` |
| Git | any | `git --version` | git-scm.com |
| PostgreSQL | 14 or newer | — | **Required.** Easiest: Docker (below). Or a Supabase project, or PostgreSQL installed on your computer. |
| Docker | recommended | `docker --version` | docker.com. Runs PostgreSQL for you with one command. |

The Studio uses **PostgreSQL only**, the same database locally, in tests and in production, so what works on your laptop works on Supabase.

## 1. Get the code

```bash
git clone <your-repo-url> travel-episodes-studio
cd travel-episodes-studio          # the folder with app/, docs/, requirements.txt
```

## 2. Python environment

```bash
python3 -m venv .venv
source .venv/bin/activate           # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt # app + test tools
```

`requirements.txt` is what the server needs. `requirements-dev.txt` adds `pytest` and friends for tests.

## 3. A database

```bash
docker compose up -d db              # PostgreSQL 16 on localhost:5432 (user rates, password rates, database rates)
```

Or use a Supabase project: its **Session pooler** connection string (port 5432) works from a laptop ([guide 4](04-database-supabase.md)).

## 4. Settings file

```bash
cp .env.example .env                # Windows: copy .env.example .env
```

Open `.env` and set at least these:

```ini
DATABASE_URL=postgresql://rates:rates@localhost:5432/rates   # the Docker database above (or Supabase)
SECRET_KEY=<paste output of: python -c "import secrets; print(secrets.token_urlsafe(48))">
ADMIN_PASSWORD=<10+ characters>          # lets the first admin sign in with a password on your laptop
```

The first admin is `travelepisodeschennai@gmail.com` unless you set `ADMIN_EMAIL`. Google sign-in usually isn't set up on a laptop, so `ADMIN_PASSWORD` is the easy way in there.

Every option is explained in `.env.example` itself and in [guide 3](03-configuration.md). `.env` holds secrets, so **never commit it**. It's already listed in `.gitignore`.

## 5. Run it

```bash
uvicorn app.api:app --reload
```

Open **http://localhost:8000**. You'll land on the sign-in page. Sign in with `travelepisodeschennai@gmail.com` (or your `ADMIN_EMAIL`) and `ADMIN_PASSWORD`.

On first start the app:

- creates every table (database migrations run automatically);
- creates the first admin, only while no users exist yet.

`--reload` restarts the server whenever you save a code file.

## 6. Add an AI key

Go to Settings → **AI connector**, paste your Claude API key (console.anthropic.com), then **Save** and **Test connection**.

Or put `ANTHROPIC_API_KEY=...` in `.env`. A key saved in the app wins over the environment variable.

## Test mode: see the whole app without an AI key

This fills a separate database with realistic data and runs the app in demo mode. Nothing calls the AI.

```bash
docker compose up -d db
docker compose exec db createdb -U rates rates_demo
export DATABASE_URL=postgresql://rates:rates@localhost:5432/rates_demo
python scripts/demo_seed.py            # suppliers, 4 sheets, revised versions, trips at every stage,
                                       # hotel options, quotations, a template, a Word sheet to review
FIXTURES_DIR=tests/fixtures ADMIN_PASSWORD=demo-password-2026 uvicorn app.api:app --port 8000
```

Sign in as `travelepisodeschennai@gmail.com` / `demo-password-2026`. What to look at:

- **Documents #6:** a revised Kashmir package, *What changes* tab: every changed price struck through.
- **Documents #7:** a Word sheet waiting for review. Try *Edit data*, then *Save to library* or *Cancel upload*.
- **Catalog → Hotels → Misty Hills:** the rate history chart.
- **Catalog → Price changes.**
- **Trips → Munnar getaway:** two hotel options.
- **Quotations.**

Uploads of the files in `samples/` are recognised from the saved examples. **Never set `FIXTURES_DIR` in production.**

## Run everything in Docker

```bash
docker compose up --build            # app on http://localhost:8000 with its own PostgreSQL
```

## Command line

All commands read the same `.env`.

| Command | What it does |
|---|---|
| `python -m app.cli create-admin --email a@b.com --name "Rakesh"` | Add an admin. It asks for the password without showing it. Add `--google-only` for an admin who signs in with Google (no password). |
| `python -m app.cli reset-password --email a@b.com` | Set a new password. This also unlocks and re-enables the account and signs it out everywhere. |
| `python -m app.cli users` | List admins |
| `python -m app.cli ingest samples/ --supplier "Green Valley"` | Read files or folders (uses the AI connector) |
| `python -m app.cli list` / `show 3` / `approve 3 --net` | Review from the terminal |
| `python -m app.cli rates --destination Munnar --date 2026-12-24 --meal CP` | Search live hotel rates |
| `python -m app.cli quote --hotel-id 1 --room "Deluxe Room" --meal CP --in 2026-12-18 --out 2026-12-22` | Price a stay |

## Tests

```bash
docker compose up -d db && docker compose exec db createdb -U rates rates_test
TEST_DATABASE_URL=postgresql://rates:rates@localhost:5432/rates_test pytest -q     # about 2 minutes
```

The test database is **emptied for every test**, so use a throwaway database, never your real one. Without `TEST_DATABASE_URL` the tests use `postgresql://postgres:postgres@localhost:5432/rates_test`.

130+ tests cover:

- every file format (PDF, Excel, CSV, Word, XML, HTML, JSON), damaged and unsupported files;
- the AI calls (Claude and OpenAI-compatible providers, with fake network responses), the known-names context and prompt caching;
- normalisation, validation and pricing;
- re-uploads: revised packages becoming version 2, identical content skipped, other-season editions, undoing an approval;
- the review editor, manual entry and discarding;
- trips, hotel options, templates, quotations and their history, exports, share links;
- password and Google sign-in, lockout, CSRF;
- a security sweep of every route, XSS, SQL injection, uploads, headers and error leaks;
- migrations and the Supabase Data API lock.

The suite also passes through PgBouncer in transaction mode, the same way Supabase's pooler works.

**In a real browser:** `tests/browser/e2e_browser.py` clicks through the main flows against a running demo app (see its first lines).

## Changing the code

The main places:

- Database tables: `app/db.py`
- API: `app/api.py`
- Web app: `app/static/app.js` (pages), `review.js` (document review and editor), `quotes.js` (quotations and hotel options), `history.js` (rate history, suppliers), `index.html` (layout and styles)
- Business logic: `app/trips.py`, `rates.py`, `catalog.py`

See [guide 8](08-architecture.md) for how they fit together.

**After changing a table in `app/db.py`**, create a migration so existing databases get the change:

```bash
alembic revision --autogenerate -m "add customer notes column"
# check the new file in app/migrations/versions/, then commit it with your change
```

Migrations run by themselves on the next start, both locally and on Vercel.
