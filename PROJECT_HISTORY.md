# Healthcare Research Intelligence Agent: Project History

This file records what has been built, milestone by milestone, and the decisions that matter. For setup and run instructions, see [README.md](README.md).

**What it is:** a web app that helps biomedical researchers find, filter, rank and understand papers from **PubMed** (the only literature source). Gemini analyzes a paper on request, and an optional account adds saved searches and preferences.

| Part | Technology |
|---|---|
| Backend | Python 3.12, FastAPI, Pydantic (`backend/`, port **8010**) |
| Frontend | Next.js 16 (App Router), TypeScript, Tailwind CSS (`frontend/`, port **3000**) |
| Literature | NCBI PubMed E-utilities (ESearch and EFetch only) |
| AI | Google Gemini via the `google-genai` SDK (default model `gemini-3.5-flash-lite`) |
| Database | PostgreSQL 14 with SQLAlchemy 2 (async) and Alembic migrations |

---

## Milestone timeline

| Step | What | Backend tests | Git |
|---|---|---|---|
| Setup | Git repo, `.gitignore`, NCBI API key | – | – |
| Milestone 1 | PubMed search API | – | `2fc0d01` |
| Milestone 2 | Ranking, filters, dedup, error handling | 89 | `2fc0d01` |
| Milestone 3 | Next.js search interface | 90 | `2fc0d01` |
| Product update | Hero search, period, filter sidebar, summary level | 116 | `2fc0d01` |
| Maintenance | `dev.sh`, README, CORS, first commit | 128 | `2fc0d01` |
| Milestone 4 | Gemini paper analysis | 190 | `071da4d` |
| Milestone 5 | Accounts, preferences, saved searches | 251 | `96fd5b6` |
| Step A | Persistent research subscriptions | 301 | `f9ef312` (branch `feature/research-subscriptions`) |
| Step B | Security hardening (AI login, usage limits, log redaction) | 338 | `f9ef312` |
| Step C | Manual test email digests (Resend) | 397 | `f9ef312` |
| Step D | Scheduled digest delivery (test modes only, off by default) | see PROJECT_DOCUMENTATION.txt §9 | same branch, not committed yet |

Commits up to `96fd5b6` are on `main` and on GitHub (`Bhumi8051/Healthcare-Research`). Steps A–C are commit `f9ef312` on `feature/research-subscriptions`, which has never been pushed. Step D is uncommitted work on that branch.

---

## Setup (before Milestone 1)

- Turned the folder into a Git repository on branch `main`.
- Added `.gitignore` so secrets (`.env`, `.env.local`) and generated folders (`.venv`, `node_modules`, `.next`) are never committed.
- Got a free **NCBI API key**, which raises PubMed's limit from 3 to 10 requests per second, and stored it only in `backend/.env`.
- **Port choice:** ports 8000 and 8001 were already used by other projects on this Mac, so the backend runs on **8010**.

## Milestone 1: PubMed search API

- Created the Python virtual environment (`backend/.venv`) and the FastAPI app.
- **`services/pubmed.py`:**
  - **ESearch** turns a query into PMIDs, sorted by PubMed's relevance.
  - **EFetch** downloads the full XML records, which are parsed into clean `Paper` objects: title, authors, journal, date, abstract (structured sections keep their labels), DOI, PubMed link.
- **Endpoints:** `GET /api/search?q=...&max_results=...` and `GET /health`.
- **Settings** are read from `backend/.env` through `config.py` (Pydantic Settings).

## Milestone 2: Ranking, filters, deduplication, error handling

- **Relevance ranking:** keyword overlap between the query and each paper. A title match counts 3× more than an abstract match, and scores run from 0 to 1. Text is normalized first (lowercase, accents removed, plurals stemmed, stopwords dropped). PubMed's own order breaks ties.
- **Candidate pool:** the search fetches 3× more papers than requested (up to 200), then ranks and trims them.
- **Date filter:**
  - Accepts `YYYY`, `YYYY-MM` or `YYYY-MM-DD`.
  - Partial dates cover the whole period, so `2020` means Jan 1 to Dec 31.
  - The filter is applied both in PubMed and on our side.
  - Papers with no usable date can optionally be kept.
- **Result limit:** 1–100, default 20, configurable.
- **Deduplication:** by PMID, then DOI, then normalized title. When two copies match, the one with an abstract is kept.
- **Error handling:**
  - A rate limiter keeps requests within NCBI's limit.
  - Timeouts, 429s and 5xx errors are retried with backoff.
  - Malformed JSON or XML becomes a clear error, and a single broken record is skipped.
  - Responses use clear HTTP codes (422, 429, 502, 504).
- **Tests:** pytest with a mocked PubMed, so they make no network calls.

## Milestone 3: Next.js frontend

- A Next.js 16 app in `frontend/`.
- **`lib/api/client.ts`** is the only file that talks to the backend; its types mirror the backend's schema.
- **Paper cards** show the title, authors, journal, date, abstract (collapsible), PMID, DOI link, keyword-match score, PubMed link and a "Retracted" badge.
- **States:** loading skeletons, empty results, readable errors with "Try again", input validation.
- **Accessibility:** labels, live regions, keyboard support, dark mode, mobile layout.
- **Backend change:** CORS was added so the browser on port 3000 can call the API on 8010.

## Product requirements update

- A centered **hero search bar** ("Search for a keyword or phrase, or ask a question").
- A **summary level** selector (High School / College / PhD), used later by Gemini.
- A **publication period** selector (Past Week / Past Month / All Time):
  - Calculated from today's date on every request.
  - Filters on PubMed's Publication Date field (`pdat` / `[dp]`), which covers both print and online dates.
- A **PubMed-style filter sidebar:**
  - Custom date range, **article type** (10 PubMed `[pt]` types), **language** (9 `[la]` languages), result limit.
  - Filters re-run the search immediately, with removable chips and "Clear all".
  - Only allowlisted values reach PubMed. An unknown tag such as `klingon[la]` would otherwise silently return 0 results.
- A **Log in** placeholder, replaced in Milestone 5.
- Tested in headless Chrome, including screenshots at desktop and mobile sizes.

## Maintenance

- **Fallback URL:** the frontend's default backend URL changed from 8000 to **8010**.
- **CORS:** any `localhost` or `127.0.0.1` port is allowed in development; production uses explicit origins.
- **Clearer error:** "Could not reach the API" now lists its 3 likely causes (backend not running, wrong `NEXT_PUBLIC_API_URL`, CORS).
- **`./dev.sh`** starts both servers. One Ctrl+C stops both, closing the terminal also stops both, and an already-running backend is reused.
- **Root README:** setup, environment variables, troubleshooting.
- **First commit:** `2fc0d01`, after checking that no secrets were included.

## Milestone 4: Gemini paper analysis

- **Endpoint:** `POST /api/papers/{pmid}/analyze` with body `{"summary_level": "high_school" | "college" | "phd"}`.
- **The backend fetches the paper from PubMed itself;** the browser only sends the PMID and the reading level.
- **Report sections (9):**
  1. Plain-language overview
  2. Research question
  3. Background
  4. Methods
  5. Key findings
  6. Interpretation
  7. Limitations
  8. What the paper does not establish
  9. Questions for further investigation
- **Every point is labelled** Reported, AI interpretation, or Not reported.
- **Grounding safeguards:**
  - Strict evidence rules in the instructions: no invented numbers, methods or citations, no medical advice, and no claim to have read the full text.
  - The abstract is passed as untrusted data and escaped, to defend against prompt injection.
  - Structured JSON output is validated with Pydantic. Invalid output becomes an error, never made-up content.
  - Numbers or links that don't appear in the PubMed record are flagged as warnings.
- **Errors:**
  - 503: key missing or rejected.
  - 429: quota reached.
  - 504: timeout.
  - 502: provider error or invalid output.

  The API key never appears in responses or logs.
- **Frontend:** an **Analyze paper** button on each card, with loading, retry and re-analyze at a new level. Nothing is analyzed automatically.
- **Model choice:** `gemini-3.5-flash-lite`, which is stable, free-tier eligible, and Google's recommended cost-effective model. On the free tier, Google may use prompts to improve its products.
- **Tests:** 62 new tests with a mocked Gemini, plus an opt-in live test (`RUN_GEMINI_LIVE=1`).

## Milestone 5: Accounts, preferences, saved searches

- **Database:** local PostgreSQL with 4 tables (`users`, `user_sessions`, `research_preferences`, `saved_searches`), created by an Alembic migration.
- **Security:**
  - **Passwords** are hashed with **Argon2id**, never stored in plain text, and must be 10–128 characters.
  - **Sessions** use a random token in an **HttpOnly, SameSite=Lax cookie**. The database stores only a **SHA-256 hash** of it. Sessions expire after 14 days, and logging out deletes them on the server.
  - **CSRF protection:** every request that changes data must send an `X-Requested-With: fetch` header.
  - **Login throttling:** 5 failures per email in 15 minutes, then 429. Failed logins get one generic message whether the email exists or not.
  - **Data isolation:** users only ever see their own data. Another user's saved search answers 404.
  - **If PostgreSQL is down,** account features return 503, and search and analysis keep working.
- **Features:**
  - Log in / sign-up dialog and an account menu.
  - `/account` page: default summary level, up to 20 research interests, list of saved searches.
  - **Save search** above results stores the query and all filters. **Run search** reopens it via `/?saved=<id>`.
  - Your preferred summary level is applied when you log in or change it, and interests appear as one-click searches.
- **Tests:** 54 database tests against `healthcare_research_test`, including a migration round-trip and a check that the models match the migrations. Plus a full browser test of the account flow.

## Research subscriptions and email (branch `feature/research-subscriptions`)

Full details are in [PROJECT_DOCUMENTATION.txt](PROJECT_DOCUMENTATION.txt) (Sections 4.9, 4.10 and 4.12).

- **Prototype:** a bell beside the search box, "Follow topic" on paper cards, a subscription dialog, and a list on `/account`. UI refined after feedback (uniform controls, a ringing bell, a time dropdown instead of Safari's time input).
- **Step A, persistent subscriptions:** a `research_subscriptions` table (migration `b4f1c80f6ca2`) and a login-protected `/api/subscriptions` API. Each topic can be followed once per user. Settings are validated on the server, and other users' subscriptions answer 404.
- **Step B, security hardening:**
  - AI analysis now requires login.
  - Daily AI limits (20 per user, 200 overall) are enforced in PostgreSQL (migration `bd806695a174`), and failures are refunded.
  - Logins and sign-ups are limited per IP, in memory.
  - API keys and passwords are removed from logs, and PubMed errors shown to users are generic.
- **Step C, manual test email digests:**
  - From `/account`, preview a digest for 1–3 subscriptions, or send one test email to yourself through Resend.
  - Each topic gets a PubMed search and one Gemini request summarizing its papers. Summaries are checked against the abstracts, and abstract excerpts are used if AI isn't available.
  - Safety: email is off unless `EMAIL_ENABLED=true`. The recipient is always your own account email, which must be in `EMAIL_TEST_RECIPIENTS`. Sends are limited per hour.
  - **A real test email was delivered on 2026-10-25 (UTC).**
- **Step D, scheduled delivery (uncommitted):**
  - **Off by default.** The modes are `off`, `dry_run` (built, never sent) and `allowlist` (approved addresses only). There's no mode that emails everyone.
  - **How it works:** PostgreSQL is the job queue, and each run of each subscription exists once.
    - Each email is frozen before it's sent, and retries use an idempotency key.
    - An email that *might* have gone out is never resent automatically; it's marked "needs review".
    - The papers already sent are tracked, so later digests only show new ones.
  - **Unsubscribing:** every email has its own unsubscribe link, and only a hash of the token is stored. Unsubscribing needs no login and is safe to repeat. One-click unsubscribe in mail apps needs https and a verified domain.
  - **Tools:**
    - `python -m app.jobs.digests` commands: `status`, `run-once --dry-run`, `review` and `resolve`.
    - `/health` shows the scheduler's heartbeat.
    - `/account` shows each subscription's status and the delivery history.
  - **Guide:** [docs/SCHEDULED_DIGESTS.md](docs/SCHEDULED_DIGESTS.md). No scheduled email has been sent yet.

---

## Important things to remember

- **Where secrets live:** only `backend/.env` (NCBI key, Gemini key, Resend key, database URL). Git ignores it. `frontend/.env.local` holds only the public API URL. Never paste keys into chats or frontend code.
- **After editing `.env`, restart the backend.** `--reload` only watches `.py` files.
- **"Address already in use"** means a server is already running on that port. Find it with `lsof -nP -iTCP:8010 -sTCP:LISTEN`.
- **Open the app at `http://localhost:3000`, not `127.0.0.1`,** or the login cookie won't be sent.
- **After pulling new database changes,** run `cd backend && .venv/bin/alembic upgrade head`.
- **Next.js 16 keeps pages you navigate away from alive in the background,** so page state survives navigation. Keep this in mind when writing UI code or tests.

## Run and test

```bash
./dev.sh                                                  # backend :8010 + frontend :3000
cd backend && .venv/bin/python -m pytest                  # full suite + 1 opt-in live test (PostgreSQL must be running)
cd frontend && npx tsc --noEmit && npm run lint && npm run build
```

## Not done yet

- **Milestone 6:** deployment and production settings, including `SESSION_COOKIE_SECURE=true` and turning off local CORS.
- **Sending scheduled digests to real users:** this needs account email verification, a verified sending domain (DKIM), https addresses and an always-on host. Step D stops at test modes.
- **Later:** password reset, email verification, account deletion in the UI, caching of AI analyses.
