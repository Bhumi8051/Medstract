#!/usr/bin/env bash
# Start the backend (FastAPI, port 8010) and frontend (Next.js, port 3000) together.
# Press Ctrl+C once to stop both.
#
#   ./dev.sh
#
# Optional overrides: BACKEND_PORT=8020 FRONTEND_PORT=3005 ./dev.sh
# If a healthy backend is already running on BACKEND_PORT, it is reused (and left running on exit).

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_PORT="${BACKEND_PORT:-8010}"
FRONTEND_PORT="${FRONTEND_PORT:-3000}"
BACKEND_PID=""
FRONTEND_PID=""

say()  { printf '\033[1;36m[dev]\033[0m %s\n' "$*"; }
fail() { printf '\033[1;31m[dev]\033[0m %s\n' "$*" >&2; exit 1; }
port_in_use() { lsof -nP -iTCP:"$1" -sTCP:LISTEN >/dev/null 2>&1; }
backend_healthy() { curl -fsS -m 2 "http://localhost:$BACKEND_PORT/health" >/dev/null 2>&1; }

# Each server runs in its own process group (set -m), so killing the group also
# stops the processes it spawned (uvicorn's reloader worker, npm's next server).
stop_group() {
  local pid="$1"
  [ -n "$pid" ] || return 0
  kill -TERM -- "-$pid" 2>/dev/null || kill -TERM "$pid" 2>/dev/null || true
}

cleanup() {
  trap - INT TERM HUP EXIT
  # Never abort cleanup halfway: if the terminal was closed, even printing fails.
  set +e
  # Stop the servers before printing anything, for the same reason.
  stop_group "$FRONTEND_PID"
  stop_group "$BACKEND_PID"
  { echo; say "Shutting down…"; } 2>/dev/null
  # Give them a moment to exit cleanly, then force anything left.
  for _ in 1 2 3 4 5; do
    { [ -z "$FRONTEND_PID" ] || ! kill -0 "$FRONTEND_PID" 2>/dev/null; } &&
      { [ -z "$BACKEND_PID" ] || ! kill -0 "$BACKEND_PID" 2>/dev/null; } && break
    sleep 1
  done
  [ -n "$FRONTEND_PID" ] && kill -KILL -- "-$FRONTEND_PID" 2>/dev/null
  [ -n "$BACKEND_PID" ] && kill -KILL -- "-$BACKEND_PID" 2>/dev/null
  say "Stopped." 2>/dev/null
}
# INT = Ctrl+C, TERM = kill, HUP = terminal window closed. Without HUP the
# servers would keep running as orphans after the terminal is closed.
trap cleanup INT TERM HUP EXIT

# ---------- preflight checks ----------
[ -x "$ROOT/backend/.venv/bin/uvicorn" ] ||
  fail "Backend not set up. Run: cd backend && python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt"
[ -d "$ROOT/frontend/node_modules" ] ||
  fail "Frontend not set up. Run: cd frontend && npm install"
[ -f "$ROOT/backend/.env" ] ||
  say "Note: backend/.env not found; PubMed works without an API key but is limited to 3 requests/second. See README.md."

if port_in_use "$FRONTEND_PORT"; then
  fail "Port $FRONTEND_PORT is already in use (is the frontend already running?). See: lsof -nP -iTCP:$FRONTEND_PORT -sTCP:LISTEN"
fi

set -m

# ---------- backend ----------
if port_in_use "$BACKEND_PORT"; then
  if backend_healthy; then
    say "Backend already running on port $BACKEND_PORT; reusing it (it will keep running after exit)."
  else
    fail "Port $BACKEND_PORT is in use by something that isn't this backend. See: lsof -nP -iTCP:$BACKEND_PORT -sTCP:LISTEN"
  fi
else
  say "Starting backend on http://localhost:$BACKEND_PORT …"
  (cd "$ROOT/backend" && exec .venv/bin/uvicorn app.main:app --reload --port "$BACKEND_PORT") &
  BACKEND_PID=$!
  for _ in $(seq 1 60); do
    backend_healthy && break
    kill -0 "$BACKEND_PID" 2>/dev/null || fail "Backend exited during startup (see the output above)."
    sleep 0.5
  done
  backend_healthy || fail "Backend did not become healthy within 30 seconds."
fi

# ---------- frontend ----------
# Only override NEXT_PUBLIC_API_URL when the backend port was changed; otherwise
# frontend/.env.local (or the client's 8010 default) stays in charge.
if [ "$BACKEND_PORT" != "8010" ]; then
  export NEXT_PUBLIC_API_URL="http://localhost:$BACKEND_PORT"
fi
say "Starting frontend on http://localhost:$FRONTEND_PORT …"
(cd "$ROOT/frontend" && exec npm run dev -- --port "$FRONTEND_PORT") &
FRONTEND_PID=$!

say "Ready soon:  app → http://localhost:$FRONTEND_PORT   API docs → http://localhost:$BACKEND_PORT/docs"
say "Press Ctrl+C to stop."

# ---------- wait (bash 3.2 compatible: no `wait -n`) ----------
# Ctrl+C is handled by the trap above. If either server exits on its own,
# stop the other one and report failure.
while true; do
  if ! kill -0 "$FRONTEND_PID" 2>/dev/null; then
    fail "Frontend stopped unexpectedly (see the output above). If it says another next dev server is running, stop that one first."
  fi
  if [ -n "$BACKEND_PID" ] && ! kill -0 "$BACKEND_PID" 2>/dev/null; then
    fail "Backend stopped unexpectedly (see the output above)."
  fi
  sleep 1
done
