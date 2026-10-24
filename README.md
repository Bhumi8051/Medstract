# Healthcare Research Intelligence Agent

Search, filter and rank biomedical papers from **PubMed** (the only literature source).

- **Backend:** Python, FastAPI and Pydantic, in `backend/`. It calls NCBI E-utilities (ESearch and EFetch).
- **Frontend:** Next.js App Router, TypeScript and Tailwind CSS, in `frontend/`.

## Prerequisites

- Python 3.12+
- Node.js 20.9+ and npm (required by Next.js 16)
- macOS or Linux shell (for `./dev.sh`)
- Optional: a free [NCBI API key](https://account.ncbi.nlm.nih.gov/settings/) under "API Key Management". It raises PubMed's limit from 3 to 10 requests per second.

## Setup (once)

```bash
# Backend
cd backend
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
cp .env.example .env          # then edit .env (see below)

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
| `backend/.env` | `CORS_ALLOW_LOCAL_ORIGINS` | `true` by default: lets any `localhost`/`127.0.0.1` port call the API. Set to `false` in production |
| `backend/.env` | `CORS_ORIGINS` | Exact allowed origins for production, as JSON, e.g. `["https://research.example.org"]` |
| `frontend/.env.local` | `NEXT_PUBLIC_API_URL` | Backend URL (default `http://localhost:8010`). It is visible in the browser, so **never put secrets here** |

`backend/.env.example` lists the optional tuning settings: timeouts, retries, result limits and ranking weights.

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
cd backend && .venv/bin/python -m pytest
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
- **Few results for "Past Week".** Recent papers can take a few days to appear in PubMed's date index.

## Not yet implemented

AI summaries (Gemini), accounts and login, saved searches, and weekly email digests. The Login button and the summary-level selector are placeholders for these.
