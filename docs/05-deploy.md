# 5 · Deploy: Vercel + Supabase, on your own domain

The Studio runs as **its own Vercel project** on a subdomain such as `studio.travelepisodes.in`. Your existing website isn't touched: different project, same Vercel account, same domain.

There's **no build step**. Vercel installs `requirements.txt` and runs the FastAPI app named in `pyproject.toml`.

**Before you start:**

- A Supabase project with its Transaction pooler string ([guide 4](04-database-supabase.md)).
- The code in a GitHub repository. It can be a folder inside your website's repo.
- A Vercel **Pro** plan (see *Which Vercel plan* at the end).

---

## Step by step

### 1. Create the Vercel project

1. Go to vercel.com and choose **Add New… → Project**. Import the GitHub repository.
2. **Root Directory:** the folder that contains `pyproject.toml` and `app/`, for example `studio`. If the whole repo is the Studio, leave it at `./`.
3. Framework preset: leave the detected value (*FastAPI* or *Other*). There's no build command or output directory to set.

### 2. Environment variables

In the same screen, or later in Project → Settings → Environment Variables, add the following for **Production**:

| Name | Value |
|---|---|
| `DATABASE_URL` | Supabase **Transaction pooler** URI (port **6543**), with the password filled in |
| `SECRET_KEY` | Output of `python -c "import secrets; print(secrets.token_urlsafe(48))"`. Save it in your password manager too. |
| `CRON_SECRET` | Another random string from the same command |
| `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` | From Google Cloud ([below](#google-sign-in)). The first admin, travelepisodeschennai@gmail.com, signs in with Google. |
| `PUBLIC_URL` | `https://studio.travelepisodes.in` |
| `ADMIN_PASSWORD` | Optional: 10+ characters, if the first admin should also have a password (e.g. before Google is set up). Remove it after the first sign-in. |
| `ADMIN_EMAIL` | Optional: only if the first admin is not travelepisodeschennai@gmail.com |
| `ANTHROPIC_API_KEY` | Optional. You can paste the key in Settings → AI connector instead. |

Leave `FIXTURES_DIR` **unset**. Every option is explained in [guide 3](03-configuration.md).

> **Preview deployments** (built from other branches) use Preview variables. If you give Preview the same `DATABASE_URL`, test branches work on your real data. Either leave Preview without variables, or point it at a second Supabase project.

### 3. Deploy

Press **Deploy**. When it finishes:

1. Open `https://<project>.vercel.app/api/health`. You should see `{"ok":true}`.
2. Open `https://<project>.vercel.app`. You should be sent to the sign-in page.
3. Sign in: **Sign in with Google** as travelepisodeschennai@gmail.com (or your `ADMIN_EMAIL`), or with `ADMIN_PASSWORD`. The first start created every table and the first admin.
4. Settings → **System** should show *Supabase · transaction pooler* and **Data API: locked**, with no warnings about demo mode or `SECRET_KEY`.
5. Settings → **AI connector**: paste the Claude key if you didn't set it as a variable, then **Save** and **Test connection**.

### 4. Your domain

1. Project → Settings → **Domains** → add `studio.travelepisodes.in`.
2. Add the DNS record Vercel shows at your domain registrar. It's usually a **CNAME** from `studio` to `cname.vercel-dns.com`. If the domain's DNS is already managed by Vercel, this happens automatically.
3. HTTPS certificates are issued automatically, usually within minutes.

### 5. Finish up

- Remove `ADMIN_PASSWORD` from the environment variables. It was only needed once; Settings → System reminds you. Then redeploy.
- Settings → **Team & sign-in**: add the other admins.
- Settings → **Company** and **Quotes**: fill in your GSTIN, bank details, terms and team phones.
- Check that the daily job appears under Project → Settings → **Cron Jobs** (from `vercel.json`).

---

## Google sign-in

About 10 minutes, once.

1. Go to **console.cloud.google.com**, signed in as travelepisodeschennai@gmail.com. Create a project, e.g. *Travel Episodes Studio*.
2. **APIs & Services → OAuth consent screen**:
   - User type **External**;
   - app name *Travel Episodes Studio*, support email, and your domain;
   - scopes: only the defaults (`openid`, `email`, `profile`);
   - **Publish app**. While it's in "Testing", only listed test users can sign in.
3. **APIs & Services → Credentials → Create credentials → OAuth client ID**:
   - type **Web application**;
   - Authorised JavaScript origins: `https://studio.travelepisodes.in`;
   - Authorised redirect URIs: `https://studio.travelepisodes.in/auth/google/callback`. For local testing also add `http://localhost:8000/auth/google/callback`.
4. Copy the **Client ID** and **Client secret** into Vercel as `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET`. Set `PUBLIC_URL` to your Studio address and redeploy.
5. The sign-in page now shows **Sign in with Google**.

Who gets in: only emails listed in Settings → Team & sign-in, and only while active. Everyone else is told they aren't an admin, and no session is created. Google confirms who the person is; the Studio decides whether they're allowed.

To add Rakesh and Jayaram: Settings → Team & sign-in → Add an admin → their Gmail address, tick *Google sign-in only*.

## What `vercel.json` sets

```json
{
  "regions": ["bom1"],                                   // run in Mumbai, next to the Supabase database
  "functions": { "app/api.py": { "maxDuration": 300 } }, // allow 5 minutes for reading a long document
  "crons": [{ "path": "/api/cron/daily", "schedule": "30 21 * * *" }]   // 03:00 IST every day
}
```

(The real file has no comments; JSON doesn't allow them.)

**Why Mumbai matters:** Vercel's default region is Washington DC. Every page makes several database queries, and each one would cross the world and back. Keep the Vercel region and the Supabase region together.

---

## Updating the app

- **Push to the main branch.** Vercel deploys automatically.
- **Database changes deploy themselves.** New migrations run on the first request after the deploy.
- **Roll back:** Project → Deployments → an older deployment → **Promote to Production**. Migrations only move forward, and so far they only add tables, so an older version still runs on a newer database.

---

## Limits to know

| Limit | Value | What to do |
|---|---|---|
| Upload size | 4.5 MB per request (Vercel) | Settings → Processing → Largest upload is set to 4.4 MB. Compress bigger PDFs (e.g. ilovepdf.com) or split them. |
| Time to read one document | 300 s on Hobby, up to 800 s on Pro | Typical rate sheets take 20–90 s. For huge brochures, lower the chunk size (Settings → Processing) or split the PDF. |
| Cold starts | the first request after idle takes a few seconds | Normal for serverless |

---

## Which Vercel plan

Vercel's Hobby (free) plan is for **non-commercial personal use only**. Their rules say all commercial use requires Pro or Enterprise, and that includes a site advertising a business's services. The Studio is a business tool, so plan on **Vercel Pro**. Pro also raises the time limit to 800 s.

Cheaper alternatives, if you prefer:

- **Render, Railway or Fly.io:** run the included `Dockerfile` with the same environment variables. Use Supabase's **Session pooler** string (5432), and set `PROCESS_MODE=background` if you like.
- **Your own server (VPS):** `docker compose up -d --build` runs the app and its own PostgreSQL. Put it behind **Caddy** or **nginx** for HTTPS on your subdomain. With the bundled PostgreSQL, run `pg_dump` backups yourself.

On a normal server there's no 4.5 MB upload cap or 300 s time limit. Raise *Largest upload* in Settings → Processing to match.

---

## Pre-launch checklist

- [ ] `/api/health` returns ok, and the sign-in page loads on your domain over HTTPS
- [ ] Settings → System: Supabase, Data API locked, `SECRET_KEY` set, `CRON_SECRET` set, no warnings
- [ ] Google sign-in works for travelepisodeschennai@gmail.com, and a non-admin Gmail is refused
- [ ] The other admins are added (Google sign-in only)
- [ ] AI connector: Test connection succeeds; prices and a monthly budget are set
- [ ] Company and Quotes details filled in; team phones set; other admins added
- [ ] `ADMIN_PASSWORD` removed from Vercel (if you set one); `FIXTURES_DIR` not set
- [ ] Upload one real rate sheet, review it, save it; upload the same sheet again and see "already in the library"
- [ ] Build a trip with two hotel options, save a quotation, download its PDF, open its client link on a phone
- [ ] First Excel backup downloaded (Settings → Data)
