# Travel Episodes Studio — documentation

Start here. Each guide is self-contained.

| # | Guide | For | Read when |
|---|---|---|---|
| 1 | [User guide](01-user-guide.md) | Everyone who uses the app | First day; keep open while learning |
| 2 | [Set up on your computer](02-local-setup.md) | Whoever runs or changes the code | Before anything technical |
| 3 | [Configuration](03-configuration.md) | Admin / developer | Every setting: where it lives, what it does |
| 4 | [Database & Supabase](04-database-supabase.md) | Admin / developer | Creating the database, backups, useful SQL |
| 5 | [Deploy (Vercel + Supabase)](05-deploy.md) | Developer | Putting it online on your domain |
| 6 | [AI connector](06-ai-connector.md) | Admin | Choosing / switching AI, keys, tokens, cost |
| 7 | [Operations & troubleshooting](07-operations.md) | Admin / developer | Something's wrong; routine care; security |
| 8 | [Architecture & data flow](08-architecture.md) | Developer | Diagrams, how re-uploads are decided, code map, "should we use React?" |
| 9 | [Security, testing & production readiness](09-security-and-testing.md) | Owners / developer | Before launch: test results, security checks, go-live checklist |

## The whole setup in one screen

1. **Database:** create a Supabase project (Mumbai region) and copy its *Transaction pooler* connection string. See [guide 4](04-database-supabase.md).
2. **Code:** put this folder in your GitHub repo.
3. **Google sign-in:** create an OAuth client in Google Cloud ([guide 5](05-deploy.md#google-sign-in)).
4. **Vercel (Pro):** create a new project from that repo, add `DATABASE_URL`, `SECRET_KEY`, `CRON_SECRET`, `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` and `PUBLIC_URL`, and deploy. See [guide 5](05-deploy.md).
5. **Domain:** add `studio.yourdomain` in Vercel → Domains.
6. **Sign in with Google** as travelepisodeschennai@gmail.com (the first admin). Then:
   - In Settings → AI connector, paste the Claude API key and press *Test connection*.
   - In Settings → Company and Quotes, fill in your GSTIN, bank details and terms.
   - In Settings → Team & sign-in, add the other admins (Google sign-in only).
7. **Use it:** upload a rate sheet, review it, save it to the library, build a trip, save a quotation.

To see everything without an AI key first, use **test mode** ([guide 2](02-local-setup.md#test-mode-see-the-whole-app-without-an-ai-key)).
