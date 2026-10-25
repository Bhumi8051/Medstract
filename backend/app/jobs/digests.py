"""Scheduled-digest commands (Step D). Run from backend/:

    python -m app.jobs.digests status            # read-only overview + diagnostics
    python -m app.jobs.digests run-once --dry-run   # one tick; builds digests, sends nothing
    python -m app.jobs.digests run-once          # one tick in DIGEST_DELIVERY_MODE (off: housekeeping only)
    python -m app.jobs.digests review            # list deliveries that need review
    python -m app.jobs.digests resolve ID --not-delivered
    python -m app.jobs.digests resolve ID --delivered --message-id RESEND_ID

--dry-run can only make a tick safer: it never turns sending on. `review` and
`resolve` never send anything. Output never shows API keys or unsubscribe
tokens; recipient addresses are masked.
"""

import argparse
import asyncio
import sys
import uuid
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import httpx
from sqlalchemy import case, func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.config import Settings, get_settings
from app.db import create_engine, create_sessionmaker
from app.db_models import DigestDelivery, DigestSentPaper, ResearchSubscription
from app.models import SubscriptionFrequency
from app.logging_setup import install_log_redaction
from app.scheduler import run_locked_tick
from app.services.delivery import MISSED_GRACE, DeliveryEngine, effective_mode, email_ready
from app.services.email import ResendEmailSender
from app.services.gemini import GeminiReportGenerator
from app.services.pubmed import PubMedClient
from app.services.unsubscribe import scrub_tokens

# How late something may be before `status` calls it out.
OVERDUE = timedelta(minutes=15)

# What to do about each failure code (shown by `status` and `review`).
HINTS = {
    "resend_401": "The API key was rejected: check RESEND_API_KEY in backend/.env, then restart.",
    "email_not_configured": "RESEND_API_KEY is missing: add it to backend/.env, then restart.",
    "resend_403": "Resend refused the recipient or key. With onboarding@resend.dev, only the address that "
    "owns the Resend account can receive email; also check the key has sending access.",
    "resend_400": "Resend rejected the message: check EMAIL_FROM (onboarding@resend.dev or a verified domain).",
    "resend_422": "Resend rejected the message: check EMAIL_FROM (onboarding@resend.dev or a verified domain).",
    "resend_429": "Resend's rate limit or daily quota (free plan: 100/day) was hit; it retries automatically.",
    "timeout": "Resend didn't answer in time; the email may have been sent. Retried with the same key.",
    "idempotency_window_expired": "Unclear outcome and too old to retry safely. Check the Resend dashboard, "
    "then `resolve`.",
    "idempotency_conflict": "Resend says this key was already used with different content: it was probably "
    "sent. Check the Resend dashboard, then `resolve`.",
    "pubmed_error": "PubMed was unavailable while building the digest; it retries automatically.",
    "internal_error": "Unexpected error: check the backend terminal for the error type.",
    "lease_expired": "A worker stopped mid-delivery (crash/restart); it was recovered automatically.",
    "expired": "Still queued after its grace period (delivery paused or server off), so it was not sent. Its "
    "papers stay eligible for the next digest. As needs_review: an earlier attempt may have gone out; check "
    "the Resend dashboard, then `resolve`.",
}


def mask(email: str | None) -> str:
    if not email or "@" not in email:
        return "-"
    name, domain = email.split("@", 1)
    return f"{name[:1]}***@{domain}"


def local(dt: datetime | None, zone: str) -> str:
    return dt.astimezone(ZoneInfo(zone)).strftime("%a %Y-%m-%d %H:%M %Z") if dt else "-"


# ---------------------------------------------------------------- run-once


async def run_once(dry_run: bool) -> int:
    settings = get_settings()
    mode = effective_mode(settings, "dry_run" if dry_run else None)
    print(f"Mode: {mode}" + (" (forced by --dry-run)" if dry_run else ""))
    if mode == "off":
        print(
            "Delivery is off (or allowlist without full email setup): housekeeping only. Expired claims are "
            "requeued and deliveries queued past their grace period are finalized (never sent)."
        )
    engine = create_engine(settings)
    generator = GeminiReportGenerator(settings)
    try:
        async with httpx.AsyncClient() as http:
            delivery = DeliveryEngine(
                create_sessionmaker(engine),
                settings,
                PubMedClient(settings, http),
                generator,
                ResendEmailSender(settings, http),
                mode_override="dry_run" if dry_run else None,
            )
            result = await run_locked_tick(engine, delivery)
    finally:
        await generator.aclose()
        await engine.dispose()
    if result is None:
        print("Skipped: another scheduler is running right now.")
        return 1
    print(result.summary())
    return 0


# ---------------------------------------------------------------- status


def config_lines(settings: Settings) -> list[str]:
    mode = settings.digest_delivery_mode
    lines = [
        f"DIGEST_DELIVERY_MODE={mode} (effective: {effective_mode(settings)})"
        f" | DIGEST_SCHEDULER_ENABLED={str(settings.digest_scheduler_enabled).lower()}",
        f"Email: EMAIL_ENABLED={str(settings.email_enabled).lower()}, RESEND_API_KEY "
        f"{'set' if settings.resend_key_value else 'missing'}, EMAIL_TEST_RECIPIENTS: "
        f"{len(settings.email_test_recipient_set)} address(es), EMAIL_FROM uses "
        f"{'Resend test sender' if '@resend.dev' in settings.email_from.lower() else 'your domain'}",
        f"Links: PUBLIC_APP_URL={settings.public_app_url} | PUBLIC_API_URL={settings.public_api_url} "
        f"(one-click unsubscribe header: {'on' if settings.public_api_url.startswith('https://') else 'off, needs https'})",
    ]
    return lines


async def status() -> int:
    settings = get_settings()
    engine = create_engine(settings)
    sm = create_sessionmaker(engine)
    now = datetime.now(UTC)
    problems: list[str] = []
    try:
        async with sm() as db:
            print("\n".join(config_lines(settings)))

            counts = dict(
                (await db.execute(select(DigestDelivery.status, func.count()).group_by(DigestDelivery.status))).all()
            )
            print("\nDeliveries by status:", ", ".join(f"{s}={n}" for s, n in sorted(counts.items())) or "none")
            last_activity = await db.scalar(select(func.max(DigestDelivery.updated_at)))
            print("Last delivery activity:", last_activity.astimezone(UTC).strftime("%Y-%m-%d %H:%M UTC")
                  if last_activity else "never")

            print("\nNext scheduled runs:")
            rows = (
                await db.execute(
                    select(ResearchSubscription)
                    .where(ResearchSubscription.next_run_at.is_not(None))
                    .order_by(ResearchSubscription.next_run_at)
                    .limit(10)
                )
            ).scalars().all()
            for r in rows:
                print(f"  {local(r.next_run_at, r.time_zone)}  {r.frequency:<7}  {r.topic}")
            if not rows:
                print("  none (active subscriptions get a time on the first tick)")

            print("\nLatest deliveries:")
            latest = (
                await db.execute(
                    select(DigestDelivery, ResearchSubscription.topic)
                    .join(ResearchSubscription, ResearchSubscription.id == DigestDelivery.subscription_id)
                    .order_by(DigestDelivery.created_at.desc())
                    .limit(10)
                )
            ).all()
            for d, topic in latest:
                print(
                    f"  {d.scheduled_for:%Y-%m-%d %H:%M}Z  {d.status:<16} attempts={d.attempts} "
                    f"papers={d.papers_count if d.papers_count is not None else '-'} "
                    f"{d.error_code or ''}  {topic}"
                )
            if not latest:
                print("  none")

            # ---- diagnostics
            mode = effective_mode(settings)
            if settings.digest_delivery_mode == "allowlist" and not email_ready(settings):
                problems.append(
                    "Mode is allowlist but email isn't fully set up, so ticks run as OFF. Needs EMAIL_ENABLED=true, "
                    "RESEND_API_KEY and EMAIL_TEST_RECIPIENTS."
                )
            if counts.get("needs_review"):
                problems.append(
                    f"{counts['needs_review']} delivery(ies) need review (may or may not have been delivered). "
                    "Run: python -m app.jobs.digests review"
                )
            failures = (
                await db.execute(
                    select(DigestDelivery.error_code, func.count())
                    .where(DigestDelivery.status == "failed", DigestDelivery.updated_at > now - timedelta(days=7))
                    .group_by(DigestDelivery.error_code)
                )
            ).all()
            for code, n in failures:
                problems.append(f"{n} failed in the last 7 days ({code}). {HINTS.get(code, '')}".rstrip())
            grace = case(
                *((ResearchSubscription.frequency == f.value, MISSED_GRACE[f]) for f in SubscriptionFrequency),
                else_=MISSED_GRACE[SubscriptionFrequency.DAILY],
            )
            stale = await db.scalar(
                select(func.count()).select_from(DigestDelivery)
                .join(ResearchSubscription, ResearchSubscription.id == DigestDelivery.subscription_id)
                .where(DigestDelivery.status == "pending", DigestDelivery.scheduled_for + grace < now)
            )
            if stale:
                problems.append(
                    f"{stale} queued delivery(ies) are past their grace period. They will NOT be sent: the next tick "
                    "finalizes them (skipped_missed 'expired', or needs_review if possibly sent) and scrubs their "
                    "unsubscribe tokens. To do that now: python -m app.jobs.digests run-once"
                )
            stuck = await db.scalar(
                select(func.count()).select_from(DigestDelivery)
                .where(DigestDelivery.status == "sending", DigestDelivery.lease_until < now)
            )
            if stuck:
                problems.append(f"{stuck} delivery(ies) stuck in 'sending' (a worker stopped). The next tick recovers them.")
            overdue_retries = await db.scalar(
                select(func.count()).select_from(DigestDelivery)
                .where(DigestDelivery.status == "pending", DigestDelivery.next_attempt_at < now - OVERDUE)
            )
            overdue_runs = await db.scalar(
                select(func.count()).select_from(ResearchSubscription)
                .where(ResearchSubscription.next_run_at < now - OVERDUE)
            )
            if overdue_retries or overdue_runs:
                if mode == "off":
                    problems.append(
                        f"{overdue_runs} run(s) and {overdue_retries} retry(ies) are overdue, but the effective mode "
                        "is off, so nothing will run. (Expected while testing is paused.)"
                    )
                else:
                    problems.append(
                        f"{overdue_runs} run(s) and {overdue_retries} retry(ies) are overdue: no scheduler seems to be "
                        "ticking. Start the backend with DIGEST_SCHEDULER_ENABLED=true or run `run-once`. Runs more "
                        "than the grace period late are skipped, not sent late."
                    )
    finally:
        await engine.dispose()

    print("\nDiagnostics:")
    for p in problems or ["No problems found."]:
        print(f"  - {p}")
    print("\nLive scheduler heartbeat (backend process): GET /health -> digest_scheduler")
    return 0


# ---------------------------------------------------------------- review / resolve


async def review(show_all: bool) -> int:
    settings = get_settings()
    engine = create_engine(settings)
    try:
        async with create_sessionmaker(engine)() as db:
            query = (
                select(DigestDelivery, ResearchSubscription.topic, ResearchSubscription.time_zone)
                .join(ResearchSubscription, ResearchSubscription.id == DigestDelivery.subscription_id)
                .where(DigestDelivery.status == "needs_review")
                .order_by(DigestDelivery.scheduled_for)
            )
            if not show_all:
                query = query.limit(20)
            rows = (await db.execute(query)).all()
    finally:
        await engine.dispose()
    if not rows:
        print("No deliveries need review.")
        return 0
    print(f"{len(rows)} delivery(ies) need review. These are NEVER resent automatically.\n")
    for d, topic, zone in rows:
        print(f"id:            {d.id}")
        print(f"  topic:       {topic}")
        print(f"  scheduled:   {local(d.scheduled_for, zone)}")
        print(f"  first try:   {local(d.first_attempt_at, zone)}   attempts: {d.attempts}")
        print(f"  reason:      {d.error_code}  {HINTS.get(d.error_code, '')}")
        print(f"  subject:     {d.email_subject or '-'}")
        print(f"  recipient:   {mask(d.email_to)}")
        print()
    print(
        "To resolve each one:\n"
        "  1. Open https://resend.com/emails and look for that subject sent to that recipient around the\n"
        "     'first try' time (allow for time zones).\n"
        "  2a. Found, status Delivered/Sent: copy its ID, then run\n"
        "      python -m app.jobs.digests resolve <id> --delivered --message-id <resend-id>\n"
        "  2b. Not there (or Bounced/Failed): python -m app.jobs.digests resolve <id> --not-delivered\n"
        "Neither command sends an email. Its papers stay eligible for the next digest if not delivered."
    )
    return 0


async def resolve(delivery_id: str, delivered: bool, message_id: str | None, assume_yes: bool) -> int:
    try:
        target = uuid.UUID(delivery_id)
    except ValueError:
        print("That isn't a delivery id (copy it from `review`).")
        return 2
    if delivered and not message_id:
        print("--delivered needs --message-id (the email's ID from the Resend dashboard).")
        return 2
    if not assume_yes:
        verdict = "DELIVERED" if delivered else "NOT delivered"
        if input(f"Mark {target} as {verdict}? Nothing will be sent. Type yes: ").strip().lower() != "yes":
            print("Cancelled.")
            return 1

    settings = get_settings()
    engine = create_engine(settings)
    now = datetime.now(UTC)
    try:
        async with create_sessionmaker(engine)() as db:
            d = (
                await db.execute(select(DigestDelivery).where(DigestDelivery.id == target).with_for_update())
            ).scalar_one_or_none()
            if d is None:
                print("No such delivery.")
                return 1
            if d.status != "needs_review":
                print(f"This delivery is '{d.status}', not 'needs_review'; nothing changed.")
                return 1
            d.outcome_uncertain = False
            d.lease_until = None
            d.email_html, d.email_text = scrub_tokens(d.email_html), scrub_tokens(d.email_text)
            if d.email_headers:
                d.email_headers = {k: scrub_tokens(v) for k, v in d.email_headers.items()}
            if delivered:
                sent_at = d.first_attempt_at or now
                d.status, d.provider_message_id, d.sent_at = "sent", message_id[:100], sent_at
                d.error_code = "review_confirmed_delivered"
                if d.paper_pmids:
                    await db.execute(
                        pg_insert(DigestSentPaper)
                        .values([{"subscription_id": d.subscription_id, "pmid": p, "delivery_id": d.id,
                                  "first_sent_at": sent_at} for p in d.paper_pmids])
                        .on_conflict_do_nothing()
                    )
                await db.execute(
                    update(ResearchSubscription)
                    .where(ResearchSubscription.id == d.subscription_id)
                    .values(last_sent_at=func.greatest(func.coalesce(ResearchSubscription.last_sent_at, sent_at), sent_at))
                )
            else:
                d.status, d.error_code = "failed", "review_not_delivered"
            await db.commit()
            print(f"Delivery {target} marked {d.status} ({d.error_code}). No email was sent.")
            return 0
    finally:
        await engine.dispose()


# ---------------------------------------------------------------- entry point


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.jobs.digests", description="Scheduled digest operations.")
    commands = parser.add_subparsers(dest="command", required=True)
    once = commands.add_parser("run-once", help="run one scheduler tick")
    once.add_argument("--dry-run", action="store_true", help="build digests but never send (overrides the mode)")
    commands.add_parser("status", help="configuration, schedule, history and diagnostics (read-only)")
    rev = commands.add_parser("review", help="list deliveries whose outcome is unclear (read-only)")
    rev.add_argument("--all", action="store_true", help="show all, not just the first 20")
    res = commands.add_parser("resolve", help="record what happened to a needs_review delivery (never sends)")
    res.add_argument("delivery_id")
    verdict = res.add_mutually_exclusive_group(required=True)
    verdict.add_argument("--delivered", action="store_true", help="it arrived (confirmed in the Resend dashboard)")
    verdict.add_argument("--not-delivered", action="store_true", help="it was not sent / bounced")
    res.add_argument("--message-id", help="the Resend email ID (required with --delivered)")
    res.add_argument("--yes", action="store_true", help="don't ask for confirmation")
    args = parser.parse_args(argv)

    install_log_redaction(get_settings())
    if args.command == "run-once":
        return asyncio.run(run_once(args.dry_run))
    if args.command == "review":
        return asyncio.run(review(args.all))
    if args.command == "resolve":
        return asyncio.run(resolve(args.delivery_id, args.delivered, args.message_id, args.yes))
    return asyncio.run(status())


if __name__ == "__main__":
    sys.exit(main())
