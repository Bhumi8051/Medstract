# Scheduled research digests: operations guide

How automatic digest delivery (Step D) works, how to test it safely, and what to do when something goes wrong. All commands run from `backend/` unless stated otherwise.

> **Current state:** delivery is **off** by default. There are three modes: `off`, `dry_run` (build, never send) and `allowlist` (send only to approved addresses). **There is no mode that emails everyone.** That needs a verified sending domain and account email verification, neither of which exists yet.

---

## 1. How it works

```
every DIGEST_TICK_SECONDS (if the scheduler runs), or once per `run-once`
  tick ─ housekeeping (in EVERY mode, including off; never sends):
       │  a. recover deliveries stuck in "sending" (worker crashed; lease expired)
       │  b. expire deliveries still queued past their grace period (section 7)
       │  (mode off stops here)
       ├ 0. give active subscriptions a next_run_at if they have none
       ├ 1. schedule: each subscription whose next_run_at has passed gets ONE delivery row
       │      (runs later than the grace period are recorded as "skipped_missed", not sent)
       └ 2. deliver: claim one due row at a time (FOR UPDATE SKIP LOCKED + lease)
              → check preferences, unsubscribe status, mode and allowlist
              → search PubMed for papers new since the last digest, one Gemini summary request
              → check the claim is still ours, then freeze the exact email (subject, HTML, text, headers)
              → check everything AGAIN, including the claim, then send with
                Idempotency-Key "digest-<delivery id>"
              → "sent" (+ record the papers) / retry later / "failed" / "needs_review"
```

- **Where it runs:** either inside the backend (`DIGEST_SCHEDULER_ENABLED=true`) or with `python -m app.jobs.digests run-once` (for example from cron). Several copies at once are safe: a PostgreSQL advisory lock lets one tick at a time, and the database prevents duplicate rows and double claims.
- **Claims:** a worker re-checks, under a row lock, that it still holds its claim (same `lease_until`, not yet expired) before freezing the email and before sending. If its lease ran out (for example, a very slow build) or another worker recovered the delivery, it stops without changing anything. The next tick recovers the delivery.
- **Schedules:** times are wall-clock times in each subscription's time zone. A time that doesn't exist on the spring-forward day (e.g. 02:30) is sent an hour later; a time that occurs twice on the fall-back day is used once, at its first occurrence.
- **Search window** (PubMed publication date): ends on the scheduled local date. It starts 7, 14 or 45 days (daily, weekly, monthly) before the end of the **last successfully sent** window, because PubMed often indexes papers late. Papers already emailed for that subscription are excluded, so the overlap never repeats a paper. The window is capped at 14, 35 or 92 days.
- **AI:** one Gemini request per digest, taken only from the **overall** daily cap (`AI_DAILY_LIMIT_TOTAL`), at most `DIGEST_MAX_AI_CALLS_PER_TICK` per tick. Users' personal 20 a day are untouched. Without AI capacity, digests use abstract excerpts. Dry runs skip AI unless `DIGEST_DRY_RUN_USE_AI=true`.

### Delivery statuses
| Status | Meaning | Sent again automatically? |
|---|---|---|
| `pending` | Waiting to send, or waiting to retry at `next_attempt_at` | yes |
| `sending` | Claimed by a worker until `lease_until` | recovered after the lease |
| `sent` | Resend **accepted** it (`provider_message_id` set). Shown as "Accepted": delivery itself is only visible in the Resend dashboard | never |
| `dry_run` | Built and stored, deliberately not sent | never |
| `skipped_no_new` | Nothing new, and the user chose not to get empty digests | never |
| `skipped_missed` | Too late to send: reason `missed` (nothing was ticking when it was due) or `expired` (it was still queued past its grace period, e.g. while paused) | never |
| `skipped_disabled` | Email off, unsubscribed, schedule changed, mode changed, not allowlisted or recipient changed | never |
| `failed` | Definitely **not** delivered (permanent error, or retries used up on errors where Resend refused) | never |
| `needs_review` | **Might** have been delivered; the outcome is unknown (reasons include `idempotency_window_expired`, `idempotency_conflict`, `expired`, `unsubscribed`) | **never** (see section 7) |

---

## 2. Configuration (`backend/.env`)

Restart the backend after any change: it reads `.env` only at startup.

| Variable | Default | Purpose |
|---|---|---|
| `DIGEST_DELIVERY_MODE` | `off` | `off`, `dry_run` or `allowlist` |
| `DIGEST_SCHEDULER_ENABLED` | `false` | run the loop inside the backend |
| `DIGEST_TICK_SECONDS` | `60` | seconds between ticks |
| `DIGEST_MAX_PER_TICK` | `10` | deliveries processed per tick |
| `DIGEST_MAX_AI_CALLS_PER_TICK` | `5` | Gemini requests per tick |
| `DIGEST_DRY_RUN_USE_AI` | `false` | use Gemini in dry runs |
| `DIGEST_LEASE_SECONDS` | `600` | how long a claim lasts before recovery |
| `DIGEST_MAX_ATTEMPTS` | `4` | attempts before `failed` / `needs_review` |
| `DIGEST_SAFE_RETRY_HOURS` | `23` | retry an *uncertain* send only within this time of the first attempt |
| `EMAIL_ENABLED`, `RESEND_API_KEY`, `EMAIL_TEST_RECIPIENTS` | off / none / empty | **all three** are required for `allowlist`. If any is missing, every tick runs as `off` and logs a WARNING saying what's missing; `status` shows `effective: off` |
| `EMAIL_FROM` | `onboarding@resend.dev` sender | see section 9 |
| `PUBLIC_APP_URL` | `http://localhost:3000` | the frontend: the `/unsubscribe` page, "Manage your subscriptions" links, and the "Visit Medstract" footer link in every digest email (test and scheduled). Use the `https://` address in production |
| `PUBLIC_API_URL` | `http://localhost:8010` | the backend: the one-click unsubscribe endpoint |
| `UNSUBSCRIBE_IP_MAX_INVALID` / `UNSUBSCRIBE_IP_WINDOW_SECONDS` | `30` / `600` | invalid unsubscribe tokens per IP per window before 429 (in memory) |
| `AI_DAILY_LIMIT_TOTAL` | `200` | overall Gemini cap, shared with interactive analyses |

Fixed in code (`app/services/delivery.py`):
- **Grace periods** (`MISSED_GRACE`): 6 hours for daily, 24 hours for weekly and monthly. This is the **latest a digest may be sent after its scheduled time**. It applies both to newly due runs and to queued deliveries (section 7).
- **Retry waits:** 5 minutes, then 30 minutes, then 2 hours. The normal retry chain (4 attempts, about 2.6 hours) fits inside even the daily grace.

**Test runs can never start the scheduler or send real email.** `tests/conftest.py` forces these four settings before any settings exist, and clears the settings cache:
- `DIGEST_SCHEDULER_ENABLED=false`
- `DIGEST_DELIVERY_MODE=off`
- `EMAIL_ENABLED=false`
- `RESEND_API_KEY=` (empty)

They win over both the shell environment and `.env`. A check that runs around every test fails the run if any of them changes. `tests/test_test_safety.py` proves this in fresh processes.

---

## 3. Database migrations

Step D adds three additive revisions on top of `bd806695a174` (Step B):

| Revision | What it adds |
|---|---|
| `96d41bf41bda` | `next_run_at`, `last_sent_at` and `unsubscribed_at` on subscriptions; the `digest_deliveries` and `digest_sent_papers` tables |
| `b4bb321bb07f` | frozen-email columns and `outcome_uncertain` on deliveries |
| `1e29bb4ebd5b` | per-delivery `unsubscribe_token_hash` and `email_headers`. It moves an unused Stage 1 column and **refuses to run** if that column holds data |

```bash
pg_dump -d healthcare_research -Fc -f ~/healthcare_research_backup.dump   # back up first
.venv/bin/alembic current                 # expect 1e29bb4ebd5b (head)
.venv/bin/alembic upgrade head
.venv/bin/alembic downgrade bd806695a174  # remove ALL Step D tables and columns (delivery history is lost)
# Undo from a backup: stop the backend first (it holds connections), then
pg_restore --clean --if-exists -d healthcare_research ~/healthcare_research_backup.dump
```

---

## 4. Commands

```bash
.venv/bin/python -m app.jobs.digests status                  # config, next runs, history, diagnostics (read-only)
.venv/bin/python -m app.jobs.digests run-once --dry-run      # one tick that never sends, whatever the mode
.venv/bin/python -m app.jobs.digests run-once                # one tick in DIGEST_DELIVERY_MODE (off: housekeeping only, never sends)
.venv/bin/python -m app.jobs.digests review                  # deliveries with an unknown outcome (read-only)
.venv/bin/python -m app.jobs.digests resolve <id> --not-delivered
.venv/bin/python -m app.jobs.digests resolve <id> --delivered --message-id <resend email id>
```

- **What the output shows:** no keys and no unsubscribe tokens; recipient addresses are masked (`a***@example.org`).
- **What `status` checks for:** allowlist mode without full email setup, deliveries needing review, failures in the last 7 days (with what to do), queued deliveries past their grace period (they'll be expired, never sent), deliveries stuck in `sending`, and overdue runs or retries (which usually mean no scheduler is running).

**The scheduler's heartbeat** lives only in the backend process:
```bash
curl -s http://localhost:8010/health
# {"status":"ok","digest_scheduler":{"enabled":false,"mode":"off","running":false,"stale":false}}
```
When the scheduler runs, `digest_scheduler` also includes `last_tick_at`, `last_success_at`, `last_summary`, `last_error` (exception type only), `consecutive_failures` and `stale`. Stale means no tick for more than 3 intervals.

**What appears in the backend terminal:**
- Every email attempt and its outcome, with the recipient masked (`a***@example.org`) and never the key, subject or body. A success reads `Email accepted by Resend (not a delivery confirmation): … ref=<idempotency key> id=<Resend message id>`; a failure reads `Email send failed: … code=… retryable=… outcome_unknown=…`. Test sends refused before sending log the reason (`email_disabled`, `no_resend_key`, `not_allowlisted`, `hourly_limit`); previews log `nothing sent`.
- Ticks that need attention (`failed`, `needs_review`, recovered leases) and tick failures are logged as warnings or errors there.
- Routine tick summaries are logged at INFO level, which the default uvicorn console output doesn't show. Use `/health` or `status` for those.

---

## 5. Safe dry-run testing

No `.env` change is needed:
```bash
.venv/bin/python -m app.jobs.digests status
.venv/bin/python -m app.jobs.digests run-once --dry-run      # gives subscriptions their next run time
```
To see a digest built today:
1. On `/account`, create a test subscription: daily, with a delivery time within the next 30 minutes.
2. After that time, run:
```bash
.venv/bin/python -m app.jobs.digests run-once --dry-run
.venv/bin/python -m app.jobs.digests status
psql -d healthcare_research -tAc "select email_html from digest_deliveries where status='dry_run' order by created_at desc limit 1" > ~/Desktop/dry-run-digest.html
open ~/Desktop/dry-run-digest.html
```
The run also appears under **Scheduled digest history** on `/account`.

Things to know about dry runs:
- **A dry run uses up that scheduled run.** It's recorded as `dry_run`, and the schedule moves on.
- **Dry-run emails link to `unsubscribe?token=dry-run-preview`**, which the page rejects as invalid. No real token is created.
- **To clean up, delete the test subscription.** Its delivery history goes with it.

For a dry run inside the backend, set `DIGEST_DELIVERY_MODE=dry_run` and `DIGEST_SCHEDULER_ENABLED=true`, then restart the backend.

---

## 6. Turning on test sending (allowlist), later

Only after reviewing dry runs. The steps:
1. In `.env`, check `EMAIL_ENABLED=true`, `RESEND_API_KEY` and `EMAIL_TEST_RECIPIENTS=<your address>`.
2. With `onboarding@resend.dev`, Resend only delivers to the address that owns the Resend account.
3. Set `DIGEST_DELIVERY_MODE=allowlist` and, optionally, `DIGEST_SCHEDULER_ENABLED=true`. Restart the backend.
4. Run `status`. The first line should say `effective: allowlist`.

Anyone not on the allowlist is recorded as `skipped_disabled (not_allowlisted)`, before any PubMed or AI work.

### Stopping and resuming
| You set | What happens to deliveries already queued for sending |
|---|---|
| `DIGEST_DELIVERY_MODE=dry_run` (restart) | On the next tick they're finalized as `skipped_disabled (mode_changed)`, or `needs_review` if an earlier attempt may have gone out. Never sent. |
| `DIGEST_DELIVERY_MODE=off` (restart) | **Paused.** Nothing is scheduled, built or sent. Queued deliveries wait. Each tick still does housekeeping: if the scheduler loop runs, or you run `run-once`, anything queued past its grace period is expired (`skipped_missed` / `expired`, or `needs_review` if possibly sent) and its token scrubbed. |
| Resume (`allowlist` again) | The first tick expires everything past its grace period **before** sending anything. Deliveries still within it are sent: up to 6 hours late for daily, 24 hours for weekly or monthly. |
| `DIGEST_SCHEDULER_ENABLED=false` with no `run-once` | Nothing runs at all. Queued deliveries (and their stored tokens) stay until the next tick, which expires them if they're past their grace period. |

So **no digest is ever sent more than its grace period after its scheduled time**, however long delivery was paused or the server was off.

---

## 7. Retries, uncertain deliveries and recovery

**Errors where Resend refused the email.** It was definitely not sent:
- **Retried** (5 min → 30 min → 2 h, up to `DIGEST_MAX_ATTEMPTS`): rate limits (`resend_429`) and connection failures. After the last attempt, the delivery becomes `failed`. If a retry would come after the grace period (for example, with a raised `DIGEST_MAX_ATTEMPTS`, or while paused), the delivery is expired instead (`skipped_missed` / `expired`).
- **Not retried** (`failed` at once): `resend_401` (key), `resend_403` (recipient or key permission), `resend_400`/`resend_422` (sender).

**Errors where the email might have gone out** (`outcome_uncertain` set):
- read timeout (`timeout`), Resend 5xx, `idempotency_in_progress`, and a crash during sending.
- These are retried with the **same idempotency key and the identical frozen email**. Resend then returns the original result instead of sending again.
- Resend keeps keys for **24 hours**, so these retries happen only within `DIGEST_SAFE_RETRY_HOURS` (23) of the first attempt, **and** within the grace period after the scheduled time. Whichever limit comes first applies.
- After that, or once attempts run out, the delivery becomes **`needs_review`** and is never sent again automatically. Its reason is `idempotency_window_expired`, `expired` or the last error code.
- `idempotency_conflict` (Resend: the key was already used with different content) also becomes `needs_review` straight away.

**Crashes, restarts and lost claims:**
- A delivery left in `sending` is put back in the queue once its lease expires (`lease_expired`).
- "Might have been sent" is saved *before* every send attempt, so a crash mid-send is never treated as a clean failure.
- A worker that lost its lease (`lease_lost` in the tick summary) stops before freezing or sending. That delivery is handled once, by whoever recovers it.

**Downtime and late emails:**
- **New runs:** runs overdue by more than the grace period are recorded as `skipped_missed` (`missed`), and the schedule jumps to the next future time. Only one is recorded per subscription, however long the downtime.
- **Queued deliveries** (waiting for a retry, or paused) are expired once past the grace period (`expired`), and never sent late.
- **Within the grace period,** a run or retry is still sent, up to 6 hours (daily) or 24 hours (weekly or monthly) after its scheduled time.
- **Expired papers stay eligible:** an expired digest's papers were never recorded as sent, so the next digest can include them.
- **Why the grace period is the limit:** it's the same rule that already decided whether a missed run is still worth sending. Using it for queued deliveries means one consistent answer to "how late is too late", with no extra setting, and it leaves normal retries untouched.

**PubMed outage while building:** retried later (`pubmed_error`). It counts toward the attempts.

### Resolving `needs_review` without duplicates
1. **List them:** run `review`. It shows the id, topic, scheduled time, first-attempt time, reason, subject and masked recipient.
2. **Check Resend:** at <https://resend.com/emails>, look for that subject sent to that recipient around the first-attempt time.
3. **Record the outcome:**
   - **Found, and Delivered or Sent:** `resolve <id> --delivered --message-id <id from Resend>`. This marks it `sent`, records its papers as sent and updates `last_sent_at`.
   - **Not found, or Bounced/Failed:** `resolve <id> --not-delivered`. This marks it `failed`. Its papers stay eligible, so they can appear in the next digest.
4. **Never resend it by hand,** by SQL or by setting it back to `pending`. If it actually arrived, the recipient would get a duplicate. The next scheduled digest covers any papers it missed.

`resolve` never sends email, and only changes deliveries in `needs_review`.

---

## 8. Unsubscribe

- **Tokens:** every real scheduled email has its own random token (256 bits). The database stores only its SHA-256 hash. Links in older emails keep working.
- **In the email:** a body link to `PUBLIC_APP_URL/unsubscribe?token=…`, plus these headers:
  - `List-Unsubscribe: <PUBLIC_API_URL/api/unsubscribe/one-click?token=…>`
  - `List-Unsubscribe-Post: List-Unsubscribe=One-Click`, **only if `PUBLIC_API_URL` is https**
- **The endpoints** (no login and no CSRF header needed; the token is the credential):
  - `GET /api/unsubscribe?token=` reports what the link is for and **changes nothing**. That matters because link scanners and previews open links.
  - `POST /api/unsubscribe {"token": …}` is the confirm button on the page.
  - `POST /api/unsubscribe/one-click?token=` is RFC 8058 one-click: no cookies, an empty 200, no redirect.
- **Repeating is safe:** unsubscribing turns email off, sets `unsubscribed_at` (once), clears `next_run_at` and cancels queued deliveries. Ones that might already have gone out become `needs_review`. Turning email back on in the account re-subscribes.
- **Bad tokens:** unknown or malformed tokens all get the same 404. More than `UNSUBSCRIBE_IP_MAX_INVALID` from one IP within the window gets a 429. Valid links never count toward that limit.

### Where an unsubscribe token can still be seen
| Place | How long | Notes |
|---|---|---|
| The recipient's mailbox | as long as the email is kept | inherent to email links |
| Resend (the email log and dashboard) | Resend's retention | the email body and headers are sent to Resend |
| `digest_deliveries.email_html/text/headers` | **only while `pending` or `sending`**. While a scheduler ticks, that's at most the grace period after the scheduled time (6 h daily, 24 h weekly or monthly); the next tick, in any mode, expires anything older. **If nothing ticks at all** (scheduler disabled, no `run-once`), it stays until the next tick. | needed to resend a byte-identical email. Replaced with `token=removed` as soon as the delivery is final, through any path: sent, failed, skipped, cancelled, expired or `needs_review` |
| Database backups (`pg_dump`) taken while deliveries were queued | as long as the backup is kept | delete old backups when you no longer need them |
| Browser history for the `/unsubscribe?token=` page | browser-controlled | the page sends no Referer and isn't indexed |
| The Next.js dev server terminal | while it's open | `next dev` prints request URLs |
| The backend logs | never | `token=` values in request lines are logged as `[REDACTED]` |

A leaked token can only unsubscribe that one subscription, which the user can undo from their account.

---

## 9. Sending domain, DKIM and local HTTP limits

**Without a verified domain:**
- `onboarding@resend.dev` can only send to the Resend account owner's address. That's fine for allowlist testing.
- Mail from it may land in spam.
- It can't support one-click unsubscribe: mail apps require a DKIM signature from *your* domain covering the `List-Unsubscribe` headers.

**To verify a domain, when needed** (for example `mail.yourdomain.com`):
1. In Resend, go to **Domains → Add domain**.
2. Add the DNS records it lists at your DNS provider: SPF/MX on the sending subdomain, and DKIM. Optionally add a DMARC record (`_dmarc`) such as `v=DMARC1; p=none;`.
3. Wait until Resend shows **Verified**. Resend then signs your email with DKIM.
4. Set `EMAIL_FROM=Research Digest <digest@mail.yourdomain.com>`.
5. Set `PUBLIC_APP_URL` and `PUBLIC_API_URL` to the **https** addresses of the deployed frontend and backend. Only then does the email carry `List-Unsubscribe-Post`, so Gmail and others can show a one-click Unsubscribe button.

**Local HTTP limits:**
- Locally, the links point to `http://localhost`. They work only on the machine running the app, and mail providers can't reach them.
- The one-click endpoint is fully tested, but in local email only the body link (opened on this computer) can be used.

Even with a verified domain, emailing users other than yourself still needs account email verification, which isn't built. That's why there's no "live" mode.

---

## 10. Troubleshooting

| Symptom (`status` / history) | Likely cause | What to do |
|---|---|---|
| `effective: off` although the mode is `allowlist` | `EMAIL_ENABLED`, `RESEND_API_KEY` or `EMAIL_TEST_RECIPIENTS` is missing | fix `.env`, then restart |
| Overdue runs; nothing happens | no scheduler is running | `DIGEST_SCHEDULER_ENABLED=true` and restart, or `run-once` |
| `skipped_missed (missed)` | the computer or backend was off at the scheduled time | expected; the next run proceeds normally |
| `skipped_missed (expired)` | still queued past its grace period (delivery paused, or the server was off during retries) | expected after a pause. Not sent; its papers can appear in the next digest |
| `status` says queued deliveries are past their grace period | nothing has ticked since | run `run-once` (any mode; it never sends stale ones) to finalize them and scrub their tokens |
| `lease_lost` in a tick summary | a worker's claim ran out mid-delivery, or another worker recovered it | nothing to do; the delivery is recovered and handled once |
| `skipped_disabled (not_allowlisted)` | the recipient isn't in `EMAIL_TEST_RECIPIENTS` | add it, or ignore if intended |
| `failed (resend_401)` | wrong or revoked key | fix `RESEND_API_KEY` |
| `failed (resend_403)` | test sender to a non-owner, or a key without sending access | use the Resend owner's address, or verify a domain |
| `failed (resend_422)` / `(resend_400)` | bad `EMAIL_FROM` | use `onboarding@resend.dev` or a verified-domain address |
| `pending (resend_429)` | Resend's rate limit or quota (free plan: 100 a day) | wait; it retries |
| `needs_review` | unknown outcome | section 7 |
| `/health` → `stale: true`, or `consecutive_failures` > 0 | ticks are failing, often because the database is down | check `pg_isready` and the backend terminal for the error type |
| Unsubscribe page says the link is invalid | dry-run link, old link to a deleted subscription, or a mistyped URL | manage email from `/account` |
