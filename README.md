# Healthcare Research Intelligence Agent

Search, filter and rank biomedical papers from **PubMed** (the only literature source).

For full technical documentation (architecture, API, configuration, test results, known issues and roadmap), see [PROJECT_DOCUMENTATION.txt](PROJECT_DOCUMENTATION.txt).

- **Backend:** Python, FastAPI and Pydantic, in `backend/`. It calls NCBI E-utilities (ESearch and EFetch).
- **AI analysis:** Google Gemini, on demand per paper, grounded in the PubMed abstract.
- **Accounts:** PostgreSQL (SQLAlchemy and Alembic) for users, research preferences and saved searches.
- **Frontend:** Next.js App Router, TypeScript and Tailwind CSS, in `frontend/`.

## Prerequisites

- Python 3.12+
- Node.js 20.9+ and npm (required by Next.js 16)
- PostgreSQL 14+ running locally (on macOS: `brew install postgresql@14 && brew services start postgresql@14`)
- macOS or Linux shell (for `./dev.sh`)
- Optional: a free [Gemini API key](https://aistudio.google.com/apikey) for AI paper analysis
- Optional: a free [NCBI API key](https://account.ncbi.nlm.nih.gov/settings/) under "API Key Management". It raises PubMed's limit from 3 to 10 requests per second.

## Setup (once)

```bash
# Backend
cd backend
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
cp .env.example .env          # then edit .env (see below)

# Databases (app + tests) and schema
createdb healthcare_research
createdb healthcare_research_test
.venv/bin/alembic upgrade head   # creates/updates the tables; rerun after pulling new migrations

# Frontend
cd ../frontend
npm install
cp .env.example .env.local    # optional, the defaults work locally
```

## Environment variables

Real values live in `backend/.env` and `frontend/.env.local`. Git ignores both. Only the `.env.example` templates are committed.

| File | Variable | Purpose |
|---|---|---|
| `backend/.env` | `NCBI_API_KEY` | Optional NCBI key. **Secret: keep it in this file only.** |
| `backend/.env` | `NCBI_EMAIL` | Contact email NCBI asks every app to send |
| `backend/.env` | `NCBI_TOOL` | App name sent to NCBI (default `healthcare-research-agent`) |
| `backend/.env` | `GEMINI_API_KEY` | Enables AI paper analysis. **Secret.** Without it, search still works and analysis returns a clear error |
| `backend/.env` | `GEMINI_MODEL` | Gemini model ID (default `gemini-3.5-flash-lite`) |
| `backend/.env` | `DATABASE_URL` | PostgreSQL URL (default `postgresql+asyncpg://localhost/healthcare_research`). **Secret if it contains a password** |
| `backend/.env` | `TEST_DATABASE_URL` | Database the tests use (default `…/healthcare_research_test`). Its name must end in `_test`, because tests empty its tables |
| `backend/.env` | `SESSION_COOKIE_SECURE` | `false` locally. **Set to `true` in production** (HTTPS) |
| `backend/.env` | `CORS_ALLOW_LOCAL_ORIGINS` | `true` by default: lets any `localhost`/`127.0.0.1` port call the API. Set to `false` in production |
| `backend/.env` | `CORS_ORIGINS` | Exact allowed origins for production, as JSON, e.g. `["https://research.example.org"]` |
| `frontend/.env.local` | `NEXT_PUBLIC_API_URL` | Backend URL (default `http://localhost:8010`). It is visible in the browser, so **never put secrets here** |

`backend/.env.example` lists every optional setting: timeouts, retries, result limits, ranking weights, session lifetime and login throttling.

## Accounts and security

- **Optional for search.** Searching works without logging in; AI paper analysis requires an account (see below). An account also adds saved searches, a default summary level, and research interests, which show up as one-click searches.
- **Passwords** are hashed with Argon2id; plain-text passwords are never stored or logged. Passwords must be 10–128 characters.
- **Sessions** use a random token in an HttpOnly, `SameSite=Lax` cookie, which JavaScript can't read. The database stores only a SHA-256 hash of the token. Sessions expire after 14 days, and logging out deletes them on the server.
- **CSRF protection:** requests that change data must send an `X-Requested-With: fetch` header. The browser only lets the allowed origins send it.
- **Password-guessing protection:** after 5 failed logins for an email within 15 minutes, further attempts are refused for a while. This counter lives in memory, so it resets when the backend restarts.
- **AI analysis requires login** and is limited to **20 analyses per user per day** and **200 in total per day** (UTC days, configurable). The limits are enforced atomically in PostgreSQL, and only successful analyses count: failures are refunded. There's also a short-term limit of 5 analyses per minute per user. Search stays public.
- **Rate limits on logins and sign-ups:** besides the 5-failures-per-email limit, there are at most 20 failed logins per IP per 15 minutes and 5 sign-up attempts per IP per hour. Both answer `429` with a `Retry-After` header. These counters are kept **in memory**, which suits the current single-process development setup but means they're not shared between multiple workers or servers, and they reset when the backend restarts.
- **Secrets stay out of logs:** HTTP-client loggers are held at WARNING (NCBI requires the API key in the URL), and every log line is filtered to mask `api_key=…` values, database passwords and the configured keys. PubMed errors shown to users are fixed, generic messages.
- **Users only see their own data.** Another user's saved search answers 404. Deleting a user removes all of their data.
- **Schema changes go through Alembic.** After changing `app/db_models.py`, run `.venv/bin/alembic revision --autogenerate -m "describe change"`, review the generated file, then run `.venv/bin/alembic upgrade head`. A test fails if the models and migrations drift apart.

## Test email digests (manual only)

From the **/account** page you can preview a research digest for 1–3 of your subscriptions and send **one test email to your own address**. Nothing is sent automatically yet; scheduled daily/weekly/monthly delivery is a later step.

1. Create a free [Resend](https://resend.com) account with **the same email you log in to this app with**. Resend's test sender (`onboarding@resend.dev`) only delivers to that address.
2. Create an API key with **Sending access** and add it to `backend/.env`. Also add your email to the allowlist and turn sending on:
   ```
   RESEND_API_KEY=re_...
   EMAIL_TEST_RECIPIENTS=you@example.com
   EMAIL_ENABLED=true
   ```
3. Restart the backend. On /account, use **Preview digest** first (it sends nothing), then **Send test email**. Check your inbox and spam folder; the message ID shown matches Resend's dashboard.

Safety: the recipient is always the signed-in account's email (it can't be set in the request), it must be in `EMAIL_TEST_RECIPIENTS`, sending is off unless `EMAIL_ENABLED=true`, and test sends are limited per hour. Each preview or send uses 1 of your daily AI analyses per topic for the summaries; if AI isn't available, the digest uses abstract excerpts instead.

## Run

```bash
./dev.sh
```

This starts the backend on port 8010 and the frontend on port 3000. Press **Ctrl+C** once to stop both. If this project's backend is already running on 8010, `dev.sh` reuses it and leaves it running when you exit. To use other ports: `BACKEND_PORT=8020 FRONTEND_PORT=3005 ./dev.sh`.

Or run the two servers in separate terminals:

```bash
cd backend && source .venv/bin/activate && uvicorn app.main:app --reload --port 8010
cd frontend && npm run dev
```

| URL | What |
|---|---|
| http://localhost:3000 | The app |
| http://localhost:8010/docs | Interactive API docs |
| http://localhost:8010/health | Backend health check |

## Checks

```bash
cd backend && .venv/bin/python -m pytest      # needs PostgreSQL running (uses healthcare_research_test)
cd frontend && npx tsc --noEmit && npm run lint && npm run build
```

## Troubleshooting

- **`[Errno 48] Address already in use` or "Port … is already in use".** Something is already using that port, often an earlier copy of the server in another terminal tab. See what it is with `lsof -nP -iTCP:8010 -sTCP:LISTEN`, then stop it with Ctrl+C in its terminal or `kill <PID>`.
- **"Another next dev server is already running".** Next.js allows one dev server per folder. Stop the existing one; the message shows its PID and URL.
- **"Could not reach the research API".** Check three things:
  1. The backend is running (`curl http://localhost:8010/health`).
  2. `NEXT_PUBLIC_API_URL` is correct.
  3. CORS allows the page's origin.
- **Changed `.env` or `.env.local` but nothing happened.** Restart the server. `--reload` only watches `.py` files, and Next.js reads `NEXT_PUBLIC_*` values when it starts.
- **PubMed error 429 / "rate limit".** Add an `NCBI_API_KEY`, or wait a moment. The backend already retries with backoff.
- **"API key invalid".** Re-copy the key into `backend/.env` with no quotes or spaces, then restart the backend.
- **"Accounts are temporarily unavailable…" (503).** Either PostgreSQL isn't running (`pg_isready`; start it with `brew services start postgresql@14`), or the tables are missing or out of date (`cd backend && .venv/bin/alembic upgrade head`). Search and analysis keep working either way.
- **Login seems to work, but you're logged out again right away.** Open the app at `http://localhost:3000`, not `http://127.0.0.1:3000`. The session cookie belongs to `localhost`, so the browser and the API must both use `localhost`.
- **Database tests are skipped.** PostgreSQL isn't reachable, or `healthcare_research_test` doesn't exist (`createdb healthcare_research_test`).
- **Few results for "Past Week".** Recent papers can take a few days to appear in PubMed's date index.

## Not yet implemented

Automatic (scheduled) email digests for subscriptions (only manual test emails exist so far), password reset, email verification, and changing or deleting an account from the UI.
