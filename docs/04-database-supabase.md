# 4 · Database & Supabase

The Studio stores everything in one PostgreSQL database:

- rates, packages, hotels, activities, places, suppliers;
- trips, payments, notes;
- users, sign-ins, settings;
- AI usage;
- the uploaded files themselves.

**Supabase** is the recommended host: managed PostgreSQL with a free plan, in Mumbai.

You don't create any tables by hand. On every start the app runs its migrations: it creates the tables, upgrades them when the code changes, and locks Supabase's public Data API away from them.

---

## Create the Supabase database (about 10 minutes)

1. Sign in at **supabase.com**, then **New project**.
   - **Name:** `travel-episodes-studio`
   - **Database password:** press *Generate a password* and **save it in your password manager**. You need it for the connection string, and Supabase won't show it again.
   - **Region:** **South Asia (Mumbai)**, which is closest to Chennai and to the app on Vercel (`bom1`).
   - Plan: Free is fine to start. See *Free plan limits* below.
2. Wait about 2 minutes for the project to be ready.
3. Press **Connect** at the top of the project dashboard. You'll see several connection strings:

   | String | Port | Use it for |
   |---|---|---|
   | **Transaction pooler** | 6543 | **Vercel (production).** This is the one for `DATABASE_URL` on Vercel. |
   | **Session pooler** | 5432 | Your laptop, `pg_dump` backups, a normal server |
   | Direct connection | 5432 | Avoid. It's IPv6-only unless you buy Supabase's IPv4 add-on, and many home and office networks can't reach it. |

4. Copy the **Transaction pooler** URI and replace `[YOUR-PASSWORD]` with the saved password. It looks like:

   ```
   postgresql://postgres.abcdefghijklmnop:YOUR-PASSWORD@aws-0-ap-south-1.pooler.supabase.com:6543/postgres
   ```

   If the password contains `@ : / ? # %`, URL-encode those characters (`@` becomes `%40`), or generate a password without them.

5. Put it in `DATABASE_URL`: in Vercel's environment variables (see [guide 5](05-deploy.md)), or in `.env` for your laptop, where you should use the **Session pooler** string instead.

6. Start or deploy the app once. Then check:
   - Supabase → **Table Editor** shows tables such as `trips`, `hotel_rates` and `users`.
   - Studio → Settings → **System** shows *Supabase · transaction pooler*, a schema version, and **Data API: locked**.
   - Supabase → **Advisors → Security Advisor** shows no "RLS disabled" errors for these tables.

### What the app does for Supabase automatically

| Issue | What the app does |
|---|---|
| Supabase requires encrypted connections | Adds `sslmode=require` to Supabase URLs |
| The transaction pooler (6543) can't keep *prepared statements*. Without handling, you'd get random `prepared statement "_pg3_0" already exists` errors. | Turns prepared statements off on pooled connections. This was tested with PgBouncer in transaction mode, which is how Supabase's pooler works: the full test suite passes through it. |
| Supabase publishes every table in `public` through its Data API, which anyone holding the project's public *anon* key can call. Without protection, users, sessions and rates would be readable that way. | Turns on **Row Level Security** on every app table, with no policies, so the Data API gets nothing. The app connects as the table owner, which RLS doesn't restrict. This runs on every start, so new tables are covered too. |
| Serverless functions shouldn't hold connections | On Vercel the app opens a connection per request (no pool) and relies on Supabase's pooler |

**Don't** create Supabase *policies* for these tables, and **don't** give the anon or service-role keys to anyone. The Studio doesn't use them; it connects with the database password.

---

## Free plan limits, and what to do about them

These are Supabase's rules at the time of writing (check supabase.com/pricing):

| Limit | What it means here | What to do |
|---|---|---|
| **No backups** on Free | If data is deleted by mistake, Supabase can't restore it | Download **Settings → Data → Full backup (Excel)** every week, and take a `pg_dump` (below) monthly. Or move to **Pro ($25/month)**, which has daily backups kept for 7 days. |
| **Pauses after 7 days** of low activity | After a quiet week the app can't reach its data until someone presses *Resume project* in Supabase | Set `CRON_SECRET` on Vercel. The daily job in `vercel.json` touches the database every night. |
| **500 MB** database | Uploaded PDFs are stored in the database, at about 1–4 MB each | Settings → System shows the size. Several hundred documents fit. When it gets close, move to Pro (8 GB). |

---

## Backups and restore

**Weekly, no tools needed:** Settings → Data → **Download full backup (Excel)**. This contains:

- hotel rates, packages, activities, hotels, places, suppliers;
- trips, with values, payments and balances.

It doesn't include the uploaded PDF files or sign-in data.

**Full database backup** (everything, including the files). Install the PostgreSQL client tools, the same major version as *PostgreSQL* in Settings → System or newer, then:

```bash
# use the SESSION pooler string (port 5432)
pg_dump "postgresql://postgres.<ref>:<password>@aws-0-ap-south-1.pooler.supabase.com:5432/postgres" \
  --schema=public --no-owner --format=custom --file=studio-$(date +%F).dump
```

**Restore** into an empty database (for example a new Supabase project):

```bash
pg_restore --no-owner --dbname "postgresql://postgres.<newref>:<password>@...pooler.supabase.com:5432/postgres" studio-2026-10-01.dump
```

It prints **one** error, `schema "public" already exists`, and ends with "errors ignored on restore: 1". That's expected and harmless: every table and row is restored.

Then point `DATABASE_URL` at the new project and redeploy. Keep the **same `SECRET_KEY`**, otherwise AI keys saved in Settings must be entered again. Everything else works regardless.

This backup and restore path was tested: a full dump restored into an empty database brought back every trip, document file and setting, and the app started on it normally.

---

## Tables

| Table | Holds |
|---|---|
| `source_documents` | Every upload or manual entry: the file itself, extracted data, checks, review status, and `changes` (what approving changed: new / up / down / unchanged, plus what's needed to undo it) |
| `suppliers` | DMCs, hotels, transporters, with contact details and GSTIN |
| `hotels`, `room_types`, `hotel_rates`, `hotel_surcharges` | Hotels, rooms, rates with validity dates and seasons, supplements and blackouts. A rate replaced by a newer sheet keeps `status = 'superseded'`; the new one points to it (`previous_rate_id`, `change_pct`). |
| `packages`, `package_days`, `package_hotels`, `package_prices` | Supplier packages: itinerary, hotel options, price grid. Re-uploads of one package share a `family_id`, with `version` 1, 2, 3 … |
| `service_rates` | Transfers, sightseeing, activities, tickets, rentals, with the same history links as hotel rates |
| `places` | Destinations and attractions |
| `trips`, `trip_days`, `trip_items`, `trip_notes`, `trip_payments` | Customer trips and templates (`is_template`): itinerary, costing (`option_label` = hotel option), follow-up log, payments |
| `quotations` | Numbered quotations (`TE-Q-2026-0007`), each with a full `snapshot` of the trip as sent, status, validity, client-link token |
| `users`, `user_sessions` | Admins and their sign-ins (password hashes and token hashes only; `password_hash = '!'` = Google-only) |
| `app_settings` | Everything from the Settings screens (AI keys encrypted) |
| `ai_usage` | One row per AI call: tokens, cost, time |
| `alembic_version` | Schema version (`0003` now), used by migrations |

---

## Useful SQL

Run these in Supabase → **SQL Editor**, or with `psql`. All were tested against a real database. **Queries that change data are marked.**

```sql
-- What's in the library
select (select count(*) from hotels) hotels,
       (select count(*) from hotel_rates where status = 'active') live_hotel_rates,
       (select count(*) from packages where status = 'active') packages,
       (select count(*) from service_rates where status = 'active') activities,
       (select count(*) from trips) trips, (select count(*) from users) users;

-- Double-room rates valid on a date in a city, cheapest first
select h.name hotel, rt.name room, r.meal_plan, r.amount, r.currency, r.valid_from, r.valid_to
from hotel_rates r join hotels h on h.id = r.hotel_id join room_types rt on rt.id = r.room_type_id
where r.status = 'active' and r.occupancy = 'double' and h.city ilike '%munnar%'
  and date '2026-12-24' between r.valid_from and r.valid_to
order by r.amount;

-- Rates expiring in the next 45 days, by supplier: who to call for new sheets
select coalesce(s.name, '(unknown)') supplier, h.name hotel, max(r.valid_to) last_valid
from hotel_rates r join hotels h on h.id = r.hotel_id left join suppliers s on s.id = r.supplier_id
where r.status = 'active' group by 1, 2 having max(r.valid_to) <= current_date + 45 order by 3;

-- Trips per stage
select status, count(*) trips from trips group by status order by 2 desc;

-- AI calls, tokens and recorded cost per month
-- (calls made before prices were entered have no recorded cost; the AI connector screen estimates those)
select to_char(date_trunc('month', at), 'YYYY-MM') as month, count(*) calls,
       sum(input_tokens) tokens_in, sum(output_tokens) tokens_out, round(sum(cost), 2) cost
from ai_usage group by 1 order by 1 desc;

-- Documents waiting for review
select id, filename, created_at from source_documents where status = 'needs_review' order by created_at;

-- Biggest tables (the Free plan allows 500 MB)
select relname as table_name, pg_size_pretty(pg_total_relation_size(c.oid)) size
from pg_class c join pg_namespace n on n.oid = c.relnamespace
where n.nspname = 'public' and c.relkind = 'r' order by pg_total_relation_size(c.oid) desc limit 10;

-- Is the Data API locked? Every row should say true (Supabase only)
select c.relname as table_name, c.relrowsecurity as rls_on
from pg_class c join pg_namespace n on n.oid = c.relnamespace
where n.nspname = 'public' and c.relkind = 'r' order by 1;

-- Schema version
select version_num from alembic_version;

-- CHANGES DATA: unlock an admin locked out by wrong passwords
update users set failed_logins = 0, locked_until = null where email = 'someone@example.com';

-- CHANGES DATA: sign every admin out of every device
delete from user_sessions;
```

To reset a password, use the command line rather than SQL, because passwords are hashed:
`python -m app.cli reset-password --email someone@example.com` (with `DATABASE_URL` pointing at Supabase).

---

### Rate history

```sql
-- every price change of one hotel, newest first (old -> new, %)
select rt.name as room, n.meal_plan, n.occupancy, o.amount as before, n.amount as now, n.change_pct,
       n.valid_from, n.valid_to, d.filename as sheet
from hotel_rates n
join hotel_rates o on o.id = n.previous_rate_id
join room_types rt on rt.id = n.room_type_id
join source_documents d on d.id = n.source_document_id
where n.hotel_id = (select id from hotels where name ilike 'Misty Hills%' limit 1) and n.change_pct <> 0
order by n.created_at desc;

-- average price change per supplier this year
select s.name, count(*) as changes, round(avg(r.change_pct), 1) as avg_pct
from hotel_rates r join suppliers s on s.id = r.supplier_id
where r.change_pct is not null and r.created_at >= date_trunc('year', now())
group by s.name order by avg_pct desc;

-- every version of each package
select family_id, version, title, status, valid_from, valid_to from packages order by family_id, version;
```

### Quotations

```sql
-- quotations sent this month and how they ended
select number, title, customer_name, status, total, valid_until from quotations
where created_at >= date_trunc('month', now()) order by created_at desc;
```

## Other PostgreSQL hosts

Anything running PostgreSQL 14 or newer works: Neon, Vercel Postgres, AWS RDS, your own server. Use the provider's pooled connection string on Vercel. Neon's `-pooler` hosts are detected automatically. The Data API lock only applies on Supabase; other hosts don't have one.

The Studio runs on PostgreSQL only (SQLite is not supported).
