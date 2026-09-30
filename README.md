# Travel Episodes Studio

Rates, trips and quotations in one place, for Travel Episodes (Chennai).

- **Documents:** upload any supplier document in any layout: PDF, Excel, CSV, Word, XML, HTML, or a photo of a rate card. The AI reads it; the app compares it with your library (new, price up or down, unchanged, a new version of a package). You review and edit everything on screen, then save or cancel. You can also enter rates by hand.
- **Library with history:** re-sent sheets don't create duplicates. Only changes are stored, and older rates are kept as history, with rate-history charts, package versions, a price-changes feed and a supplier directory (with merging of duplicate suppliers).
- **Trips & quotations:**
  - priced, day-wise trips that combine days from any package;
  - **hotel options** (Option A / B / C) in one quote;
  - templates;
  - numbered quotations kept as sent, which you can edit, copy or delete, each with a branded PDF and a client link.
- **Admin only:** Google sign-in or password, for listed admins only.
- **Settings in the UI:** everything, including the AI connector (Claude by default or any other AI, with keys, token and cost charts, and a budget).

## Documentation

**[docs/README.md](docs/README.md)** is the index:

1. [User guide](docs/01-user-guide.md)
2. [Set up on your computer](docs/02-local-setup.md), including test mode
3. [Configuration](docs/03-configuration.md), including the first admin
4. [Database & Supabase](docs/04-database-supabase.md)
5. [Deploy: Vercel + Supabase + Google sign-in](docs/05-deploy.md)
6. [AI connector](docs/06-ai-connector.md)
7. [Operations & troubleshooting](docs/07-operations.md)
8. [Architecture & data flow](docs/08-architecture.md)
9. [Security, testing & production readiness](docs/09-security-and-testing.md)

## Quick start (laptop)

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
docker compose up -d db          # PostgreSQL (the only database the app uses)
cp .env.example .env             # DATABASE_URL, SECRET_KEY, ADMIN_PASSWORD (see the comments inside)
uvicorn app.api:app --reload     # http://localhost:8000
TEST_DATABASE_URL=postgresql://rates:rates@localhost:5432/rates_test pytest -q
```

All server settings are in **`.env`**. `.env.example` is the commented template. Everything else is set in the app under **Settings**.

## Stack

- **Backend:** Python, FastAPI, SQLAlchemy, Alembic
- **Database:** PostgreSQL only (Supabase in production, Docker locally)
- **Web app:** plain JavaScript, no build step
- **Hosting:** Vercel, Mumbai region
- **AI:** Claude by default, switchable in Settings
