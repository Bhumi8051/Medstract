"""Scheduled digest delivery (Step D, stage 2): the engine behind each scheduler tick.

PostgreSQL is the job queue. One tick:
  0. Fill in next_run_at for active subscriptions that don't have one yet.
  1. Recover deliveries whose worker died (status "sending", lease expired).
  2. Schedule: every active subscription whose next_run_at has passed gets ONE
     digest_deliveries row (UNIQUE subscription_id + scheduled_for, inserted with
     ON CONFLICT DO NOTHING), and next_run_at moves to the next occurrence, in
     the same transaction. Runs overdue beyond a grace period are recorded as
     "skipped_missed" instead of being sent late.
  3. Deliver: claim due "pending" rows one at a time (FOR UPDATE SKIP LOCKED +
     a lease), so concurrent workers never process the same delivery.

Sending rules:
  - Preferences and the recipient rules are checked when a delivery is built
    AND again immediately before the send attempt.
  - The exact email is frozen in the row before the first attempt; every retry
    resends it unchanged with the same Idempotency-Key ("digest-<id>").
  - Before each attempt, outcome_uncertain is set (and committed). A clear
    answer clears it; a timeout, 5xx or crash leaves it set. An uncertain
    delivery is only retried while the provider still remembers the key
    (DIGEST_SAFE_RETRY_HOURS, below Resend's 24 hours). After that, or for
    anything else unclear, it becomes "needs_review" and is never resent
    automatically: a missed digest is better than a duplicate.
  - Sent PMIDs, last_sent_at and the advancing search window are recorded only
    in the transaction that marks the delivery "sent".

Staleness: no digest is ever sent more than its frequency's grace period
(MISSED_GRACE) after its scheduled time - the same rule that skips runs that
were missed while nothing was ticking. Deliveries still queued beyond it (e.g.
delivery was paused with mode "off", or the server was down) are finalized
instead of sent: "skipped_missed" (reason "expired") if they definitely were
not sent, "needs_review" if an earlier attempt may have gone out. Tokens are
scrubbed. This runs at the start of every tick, including in mode "off".

Claim ownership: a worker records the lease it was given and, under a row
lock, re-checks that it still holds it (same lease_until, not yet expired)
before freezing the email and again before sending. A worker that lost its
lease stops without changing the row; the next tick recovers it.

Modes: "off" only does the housekeeping above (recover expired leases, expire
stale deliveries) and never schedules, builds or sends; "dry_run" builds and
stores digests but never sends; "allowlist" sends only to EMAIL_TEST_RECIPIENTS.
There is no unrestricted mode.
"""

import logging
import uuid
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Literal
from zoneinfo import ZoneInfo

from sqlalchemy import Text, case, cast, func, select, update
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.db_models import AiUsageDailyTotal, DigestDelivery, DigestSentPaper, ResearchSubscription, User
from app.models import DigestAiStatus, DigestOut, SubscriptionFrequency
from app.services.analysis import DISCLAIMER
from app.services.digest import DigestContext, SubscriptionSnapshot, assemble_section
from app.services.digest_render import SCHEDULED_NOTICE, SCHEDULED_SUBJECT_PREFIX, render_html, render_text
from app.services.email import EmailError, EmailMessage, EmailSender
from app.services.gemini import ReportGenerator
from app.services.pubmed import PubMedClient, PubMedError
from app.services.schedule import next_run_after
from app.services.search_service import search_papers
from app.services.unsubscribe import list_unsubscribe_headers, new_token, page_url, scrub_tokens
from app.services.usage import UsageLimitError, seconds_until_reset

logger = logging.getLogger(__name__)

Mode = Literal["off", "dry_run", "allowlist"]

# The latest a digest may still be sent after its scheduled time. Applies both
# to newly due runs (skipped_missed) and to queued deliveries waiting for a retry
# or for delivery to resume (expired). Normal retries (5 min + 30 min + 2 h
# backoff, 4 attempts, about 2.6 hours) fit inside even the daily 6 hours.
MISSED_GRACE = {
    SubscriptionFrequency.DAILY: timedelta(hours=6),
    SubscriptionFrequency.WEEKLY: timedelta(hours=24),
    SubscriptionFrequency.MONTHLY: timedelta(hours=24),
}
# Search window (PubMed publication date, inclusive). It starts LOOKBACK days
# before the end of the last successfully sent window, because PubMed often
# indexes papers days after their publication date; papers already sent are
# excluded, so the overlap never repeats a paper. MAX_WINDOW caps how far back
# a digest looks after a long gap. The first digest looks back LOOKBACK days.
LOOKBACK = {SubscriptionFrequency.DAILY: 7, SubscriptionFrequency.WEEKLY: 14, SubscriptionFrequency.MONTHLY: 45}
MAX_WINDOW = {SubscriptionFrequency.DAILY: 14, SubscriptionFrequency.WEEKLY: 35, SubscriptionFrequency.MONTHLY: 92}
# Wait before retry 1, 2, 3, ... (the last value repeats).
BACKOFF = (timedelta(minutes=5), timedelta(minutes=30), timedelta(hours=2))
SCAN_BATCH = 200
NO_NEW_PAPERS_NOTE = "No new PubMed papers matched this topic since your last digest."
# Statuses after which a delivery is never sent again; its stored email is then
# scrubbed of the unsubscribe token (only the hash stays, so the link still works).
ACTIVE_STATUSES = ("pending", "sending")


def email_ready(settings: Settings) -> bool:
    """Everything allowlist sending needs: the email switch, the key and an allowlist."""
    return bool(settings.email_enabled and settings.resend_key_value and settings.email_test_recipient_set)


def scheduled_delivery_active(settings: Settings, email: str) -> bool:
    """Would the running scheduler actually email this address? (For display; the engine re-checks.)"""
    return (
        settings.digest_scheduler_enabled
        and settings.digest_delivery_mode == "allowlist"
        and email_ready(settings)
        and email.lower() in settings.email_test_recipient_set
    )


def effective_mode(settings: Settings, override: Mode | None = None) -> Mode:
    """The mode a tick runs in. "allowlist" quietly becomes "off" unless email is fully set up."""
    mode: Mode = override or settings.digest_delivery_mode
    if mode == "allowlist" and not email_ready(settings):
        logger.warning(
            "DIGEST_DELIVERY_MODE=allowlist needs EMAIL_ENABLED=true, RESEND_API_KEY and EMAIL_TEST_RECIPIENTS; "
            "running as off"
        )
        return "off"
    return mode


def search_window(
    frequency: SubscriptionFrequency, window_end: date, last_sent_end: date | None
) -> tuple[date, date]:
    start = window_end - timedelta(days=LOOKBACK[frequency])
    if last_sent_end is not None:
        start = max(last_sent_end - timedelta(days=LOOKBACK[frequency]), window_end - timedelta(days=MAX_WINDOW[frequency]))
    return min(start, window_end), window_end


def backoff(attempts: int) -> timedelta:
    return BACKOFF[min(max(attempts, 1), len(BACKOFF)) - 1]


def subscription_next_run(row: ResearchSubscription, after: datetime) -> datetime:
    return next_run_after(
        frequency=SubscriptionFrequency(row.frequency),
        weekday=row.weekday,
        month_day=row.month_day,
        delivery_time=row.delivery_time,
        time_zone=row.time_zone,
        after=after,
    )


async def cancel_queued(db: AsyncSession, subscription_id: uuid.UUID, reason: str) -> None:
    """Cancel deliveries of this subscription that are waiting to be sent (not ones in progress).

    Used when the schedule changes, email is turned off, or the user unsubscribes.
    A delivery whose earlier attempt may already have gone out becomes
    needs_review instead, so the history doesn't claim it was never sent.
    The caller commits.
    """
    await db.execute(
        update(DigestDelivery)
        .where(DigestDelivery.subscription_id == subscription_id, DigestDelivery.status == "pending")
        .values(
            status=case((DigestDelivery.outcome_uncertain.is_(True), "needs_review"), else_="skipped_disabled"),
            error_code=reason,
            lease_until=None,
            # Final now, so scrub unsubscribe tokens from the stored email (same rule as _finish).
            email_html=_sql_scrub(DigestDelivery.email_html),
            email_text=_sql_scrub(DigestDelivery.email_text),
            email_headers=cast(_sql_scrub(cast(DigestDelivery.email_headers, Text)), JSONB),
        )
    )


def _sql_scrub(column):
    """PostgreSQL version of unsubscribe.scrub_tokens (NULL stays NULL)."""
    return func.regexp_replace(column, "(token=)[A-Za-z0-9_-]{43}", r"\1removed", "g")


async def expire_stale(db: AsyncSession, now: datetime) -> int:
    """Finalize queued deliveries that are past their grace period. Never sends.

    Definitely-unsent ones become skipped_missed ("expired"): their papers were
    never recorded as sent, so they stay eligible for the next digest. Ones that
    may already have gone out become needs_review, never retried. Unsubscribe
    tokens are scrubbed. The caller commits. Returns the number expired.
    """
    grace = case(
        *((ResearchSubscription.frequency == f.value, MISSED_GRACE[f]) for f in SubscriptionFrequency),
        else_=MISSED_GRACE[SubscriptionFrequency.DAILY],
    )
    result = await db.execute(
        update(DigestDelivery)
        .where(
            DigestDelivery.status == "pending",
            DigestDelivery.subscription_id == ResearchSubscription.id,
            DigestDelivery.scheduled_for + grace < now,
        )
        .values(
            status=case((DigestDelivery.outcome_uncertain.is_(True), "needs_review"), else_="skipped_missed"),
            error_code="expired",
            lease_until=None,
            email_html=_sql_scrub(DigestDelivery.email_html),
            email_text=_sql_scrub(DigestDelivery.email_text),
            email_headers=cast(_sql_scrub(cast(DigestDelivery.email_headers, Text)), JSONB),
        )
        .execution_options(synchronize_session=False)
    )
    return result.rowcount


class GlobalAiBudget:
    """AI summaries for scheduled digests, paid from the OVERALL daily cap only.

    The overall counter is the same row the interactive analyses use
    (ai_usage_daily_total), incremented with one atomic
    INSERT ... ON CONFLICT DO UPDATE ... WHERE used < limit, so concurrent workers
    can never exceed AI_DAILY_LIMIT_TOTAL. Users' own 20/day are not touched.
    Each reservation uses its own short transaction, separate from the
    delivery's session.
    """

    def __init__(self, sessionmaker: async_sessionmaker[AsyncSession], settings: Settings, now: datetime) -> None:
        self._sessionmaker = sessionmaker
        self._settings = settings
        self._now = now
        self.calls = 0  # Gemini requests reserved during this tick

    async def reserve(self, user_id: uuid.UUID) -> tuple[date, bool]:
        if self.calls >= self._settings.digest_max_ai_calls_per_tick:
            raise UsageLimitError("The scheduler's AI limit for this run was reached.", 60)
        day = self._now.astimezone(UTC).date()
        limit = self._settings.ai_daily_limit_total
        if limit > 0:
            async with self._sessionmaker() as db:
                stmt = pg_insert(AiUsageDailyTotal).values(usage_date=day, used=1)
                stmt = stmt.on_conflict_do_update(
                    index_elements=[AiUsageDailyTotal.usage_date],
                    set_={"used": AiUsageDailyTotal.used + 1},
                    where=AiUsageDailyTotal.used < limit,
                ).returning(AiUsageDailyTotal.used)
                if (await db.execute(stmt)).first() is None:
                    await db.rollback()
                    raise UsageLimitError(
                        "The service's daily AI capacity has been reached.", seconds_until_reset(self._now)
                    )
                await db.commit()
        self.calls += 1
        return day, limit > 0

    async def refund(self, reservation: tuple[date, bool]) -> None:
        day, counted = reservation
        if not counted:
            return
        async with self._sessionmaker() as db:
            await db.execute(
                update(AiUsageDailyTotal)
                .where(AiUsageDailyTotal.usage_date == day)
                .values(used=func.greatest(AiUsageDailyTotal.used - 1, 0))
            )
            await db.commit()


@dataclass
class TickResult:
    mode: Mode
    initialized: int = 0
    recovered: int = 0
    expired: int = 0
    scheduled: int = 0
    processed: int = 0
    outcomes: Counter = field(default_factory=Counter)

    def summary(self) -> str:
        parts = [f"mode={self.mode}", f"initialized={self.initialized}", f"recovered={self.recovered}",
                 f"expired={self.expired}", f"scheduled={self.scheduled}", f"processed={self.processed}"]
        parts += [f"{k}={v}" for k, v in sorted(self.outcomes.items())]
        return " ".join(parts)


class DeliveryEngine:
    def __init__(
        self,
        sessionmaker: async_sessionmaker[AsyncSession],
        settings: Settings,
        pubmed: PubMedClient,
        generator: ReportGenerator,
        sender: EmailSender,
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        mode_override: Mode | None = None,
    ) -> None:
        if mode_override not in (None, "off", "dry_run"):
            raise ValueError("mode_override can only make a tick safer (off or dry_run)")
        self._sm = sessionmaker
        self._settings = settings
        self._pubmed = pubmed
        self._generator = generator
        self._sender = sender
        self._clock = clock
        self._mode_override = mode_override

    # ------------------------------------------------------------ tick

    async def tick(self) -> TickResult:
        mode = effective_mode(self._settings, self._mode_override)
        result = TickResult(mode=mode)
        now = self._clock()
        # Housekeeping, in every mode (never sends): requeue crashed claims, then
        # finalize anything queued past its grace period.
        result.recovered = await self._recover(now)
        result.expired = await self._expire(now)
        if mode == "off":
            if result.recovered or result.expired:
                logger.info("Digest tick (off, housekeeping only): %s", result.summary())
            return result
        result.initialized = await self._initialize(now)
        result.scheduled, missed = await self._schedule_due(now)
        result.outcomes["skipped_missed"] += missed
        budget = GlobalAiBudget(self._sm, self._settings, now)
        while result.processed < self._settings.digest_max_per_tick:
            claim = await self._claim(now)
            if claim is None:
                break
            result.processed += 1
            outcome = await self._process(*claim, now, mode, budget)
            result.outcomes[outcome] += 1
        logger.info("Digest tick: %s", result.summary())
        return result

    async def _initialize(self, now: datetime) -> int:
        """Active subscriptions without a next_run_at (created before Step D) get one, from now."""
        async with self._sm() as db:
            rows = (
                await db.execute(
                    select(ResearchSubscription)
                    .where(
                        ResearchSubscription.next_run_at.is_(None),
                        ResearchSubscription.email_enabled.is_(True),
                        ResearchSubscription.unsubscribed_at.is_(None),
                    )
                    .limit(SCAN_BATCH)
                    .with_for_update(skip_locked=True)
                )
            ).scalars().all()
            for row in rows:
                row.next_run_at = subscription_next_run(row, now)
            await db.commit()
            return len(rows)

    async def _recover(self, now: datetime) -> int:
        """Deliveries left in "sending" by a worker that died go back to the queue.

        outcome_uncertain is kept as stored: it was committed as true just before
        the provider was called, so a crash mid-send is remembered.
        """
        async with self._sm() as db:
            result = await db.execute(
                update(DigestDelivery)
                .where(DigestDelivery.status == "sending", DigestDelivery.lease_until < now)
                .values(status="pending", lease_until=None, next_attempt_at=now, error_code="lease_expired")
            )
            await db.commit()
            if result.rowcount:
                logger.warning("Recovered %s digest deliveries with expired leases", result.rowcount)
            return result.rowcount

    async def _expire(self, now: datetime) -> int:
        async with self._sm() as db:
            count = await expire_stale(db, now)
            await db.commit()
        if count:
            logger.warning("Expired %s queued digest deliveries past their grace period (not sent)", count)
        return count

    async def _schedule_due(self, now: datetime) -> tuple[int, int]:
        scheduled = missed = 0
        async with self._sm() as db:
            rows = (
                await db.execute(
                    select(ResearchSubscription)
                    .where(
                        ResearchSubscription.next_run_at <= now,
                        ResearchSubscription.email_enabled.is_(True),
                        ResearchSubscription.unsubscribed_at.is_(None),
                    )
                    .order_by(ResearchSubscription.next_run_at)
                    .limit(SCAN_BATCH)
                    .with_for_update(skip_locked=True)
                )
            ).scalars().all()
            for row in rows:
                scheduled_for = row.next_run_at
                late = now - scheduled_for > MISSED_GRACE[SubscriptionFrequency(row.frequency)]
                delivery_id = uuid.uuid4()
                stmt = (
                    pg_insert(DigestDelivery)
                    .values(
                        id=delivery_id,
                        subscription_id=row.id,
                        user_id=row.user_id,
                        scheduled_for=scheduled_for,
                        status="skipped_missed" if late else "pending",
                        error_code="missed" if late else None,
                        next_attempt_at=now,
                        idempotency_key=f"digest-{delivery_id}",
                    )
                    .on_conflict_do_nothing(constraint="uq_digest_deliveries_subscription_run")
                    .returning(DigestDelivery.id)
                )
                if (await db.execute(stmt)).first() is not None:
                    if late:
                        missed += 1
                    else:
                        scheduled += 1
                # Never schedule into the past: after downtime, skip ahead to the next future run.
                row.next_run_at = subscription_next_run(row, max(scheduled_for, now))
            await db.commit()
        return scheduled, missed

    async def _claim(self, now: datetime) -> tuple[uuid.UUID, datetime] | None:
        """Claim one due delivery. Returns (id, lease_until): the lease identifies this claim."""
        async with self._sm() as db:
            row = (
                await db.execute(
                    select(DigestDelivery)
                    .where(DigestDelivery.status == "pending", DigestDelivery.next_attempt_at <= now)
                    .order_by(DigestDelivery.next_attempt_at, DigestDelivery.scheduled_for)
                    .limit(1)
                    .with_for_update(skip_locked=True)
                )
            ).scalar_one_or_none()
            if row is None:
                return None
            row.status = "sending"
            row.lease_until = now + timedelta(seconds=self._settings.digest_lease_seconds)
            await db.commit()
            return row.id, row.lease_until

    # ------------------------------------------------------------ one delivery

    async def _load(self, db: AsyncSession, delivery_id: uuid.UUID, *, lock: bool = False):
        # populate_existing: always read the current row, never a stale in-memory copy.
        query = select(DigestDelivery).where(DigestDelivery.id == delivery_id).execution_options(populate_existing=True)
        if lock:
            query = query.with_for_update()
        delivery = (await db.execute(query)).scalar_one_or_none()
        if delivery is None:
            return None, None, None
        pair = (
            await db.execute(
                select(ResearchSubscription, User)
                .join(User, User.id == ResearchSubscription.user_id)
                .where(ResearchSubscription.id == delivery.subscription_id)
                .execution_options(populate_existing=True)
            )
        ).first()
        sub, user = pair if pair else (None, None)
        return delivery, sub, user

    def _owns(self, delivery: DigestDelivery | None, lease: datetime) -> bool:
        """Still this worker's claim: same lease (nobody recovered and re-claimed it) and not expired."""
        return (
            delivery is not None
            and delivery.status == "sending"
            and delivery.lease_until == lease
            and self._clock() < lease
        )

    def _skip_reason(self, delivery: DigestDelivery, sub, user, mode: Mode) -> str | None:
        if sub is None or user is None:
            return "subscription_deleted"
        if sub.unsubscribed_at is not None:
            return "unsubscribed"
        if not sub.email_enabled:
            return "email_off"
        if delivery.mode is not None and delivery.mode != mode and delivery.mode != "dry_run":
            return "mode_changed"  # built for sending, but sending has since been switched to dry run
        if mode == "allowlist" and user.email.lower() not in self._settings.email_test_recipient_set:
            return "not_allowlisted"
        if delivery.email_to is not None and delivery.email_to != user.email.lower():
            return "recipient_changed"
        return None

    async def _finish(self, db: AsyncSession, delivery: DigestDelivery, status: str, **fields) -> str:
        delivery.status = status
        delivery.lease_until = None
        for key, value in fields.items():
            setattr(delivery, key, value)
        if status not in ACTIVE_STATUSES:
            delivery.email_html = scrub_tokens(delivery.email_html)
            delivery.email_text = scrub_tokens(delivery.email_text)
            if delivery.email_headers:
                delivery.email_headers = {k: scrub_tokens(v) for k, v in delivery.email_headers.items()}
        await db.commit()
        logger.info(
            "Digest delivery %s: %s%s", delivery.id, status, f" ({delivery.error_code})" if delivery.error_code else ""
        )
        return status

    async def _skip(self, db: AsyncSession, delivery: DigestDelivery, reason: str) -> str:
        # If an earlier attempt may have gone out, don't claim it was never sent.
        status = "needs_review" if delivery.outcome_uncertain else "skipped_disabled"
        return await self._finish(db, delivery, status, error_code=reason)

    async def _process(
        self, delivery_id: uuid.UUID, lease: datetime, now: datetime, mode: Mode, budget: GlobalAiBudget
    ) -> str:
        async with self._sm() as db:
            try:
                return await self._process_in(db, delivery_id, lease, now, mode, budget)
            except Exception as exc:  # noqa: BLE001 - one bad delivery must not stop the tick
                await db.rollback()
                code = "pubmed_error" if isinstance(exc, PubMedError) else "internal_error"
                if code == "internal_error":
                    logger.error("Digest delivery %s failed unexpectedly (%s)", delivery_id, type(exc).__name__)
                return await self._release_for_retry(db, delivery_id, lease, now, code)

    async def _release_for_retry(
        self, db: AsyncSession, delivery_id: uuid.UUID, lease: datetime, now: datetime, code: str
    ) -> str:
        delivery, _, _ = await self._load(db, delivery_id, lock=True)
        if not self._owns(delivery, lease):
            return "lease_lost"
        delivery.attempts += 1
        if delivery.attempts >= self._settings.digest_max_attempts:
            return await self._finish(
                db, delivery, "needs_review" if delivery.outcome_uncertain else "failed", error_code=code
            )
        return await self._finish(
            db, delivery, "pending", error_code=code, next_attempt_at=now + backoff(delivery.attempts)
        )

    async def _process_in(
        self, db: AsyncSession, delivery_id: uuid.UUID, lease: datetime, now: datetime, mode: Mode,
        budget: GlobalAiBudget,
    ) -> str:
        delivery, sub, user = await self._load(db, delivery_id)
        if delivery is None:
            return "gone"  # deleted with its subscription
        if not self._owns(delivery, lease):
            return "lease_lost"
        if delivery.mode == "dry_run":
            return await self._finish(db, delivery, "dry_run")  # e.g. built in a dry run, then a crash
        if reason := self._skip_reason(delivery, sub, user, mode):
            return await self._skip(db, delivery, reason)

        if delivery.email_html is None:
            built = await self._build(db, delivery, lease, sub, user, now, mode, budget)
            if built is not None:
                return built
        if delivery.mode == "dry_run":
            return await self._finish(db, delivery, "dry_run")

        # ---- immediately before sending: fresh state, under a row lock
        await db.commit()
        delivery, sub, user = await self._load(db, delivery_id, lock=True)
        if delivery is None:
            return "gone"
        if not self._owns(delivery, lease):
            # The lease ran out (slow build) or another worker recovered this delivery:
            # don't send. The row is left as it is; a later tick recovers it.
            await db.rollback()
            return "lease_lost"
        if reason := self._skip_reason(delivery, sub, user, mode):
            return await self._skip(db, delivery, reason)
        safe_until = (delivery.first_attempt_at or now) + timedelta(hours=self._settings.digest_safe_retry_hours)
        if delivery.outcome_uncertain and now > safe_until:
            # The provider may have forgotten the key: resending could duplicate.
            return await self._finish(db, delivery, "needs_review", error_code="idempotency_window_expired")

        was_uncertain = delivery.outcome_uncertain
        delivery.attempts += 1
        delivery.first_attempt_at = delivery.first_attempt_at or now
        delivery.outcome_uncertain = True  # committed BEFORE calling the provider
        await db.commit()

        message = EmailMessage(
            to=delivery.email_to,
            subject=delivery.email_subject,
            html=delivery.email_html,
            text=delivery.email_text,
            headers=dict(delivery.email_headers or {}),
        )
        try:
            sent = await self._sender.send(message, idempotency_key=delivery.idempotency_key)
        except EmailError as exc:
            return await self._after_failed_send(db, delivery, now, exc, was_uncertain)
        except Exception as exc:  # noqa: BLE001 - unknown failure: assume it may have been sent
            logger.error("Digest delivery %s: unexpected send error (%s)", delivery.id, type(exc).__name__)
            return await self._after_failed_send(
                db, delivery, now, EmailError("unexpected", code="internal_error", retryable=True, outcome_unknown=True),
                was_uncertain,
            )
        return await self._confirm_sent(db, delivery, sub, now, sent.provider_message_id)

    async def _build(self, db, delivery, lease, sub, user, now, mode, budget) -> str | None:
        """Choose papers and freeze the email. Returns a final status if nothing will be sent.

        The frozen email is only written if this worker still owns the claim, so a
        worker that lost its lease can never overwrite another worker's payload.
        """
        snapshot = SubscriptionSnapshot.of(sub)
        user_id = user.id
        email_when_nothing_new = sub.email_when_no_new_papers
        recipient = user.email.lower()
        local_end = delivery.scheduled_for.astimezone(ZoneInfo(sub.time_zone)).date()
        last_sent_end = await db.scalar(
            select(func.max(DigestDelivery.window_end)).where(
                DigestDelivery.subscription_id == sub.id, DigestDelivery.status == "sent"
            )
        )
        start, end = search_window(snapshot.frequency, local_end, last_sent_end)
        already_sent = set(
            (await db.execute(select(DigestSentPaper.pmid).where(DigestSentPaper.subscription_id == sub.id))).scalars()
        )
        await db.commit()  # don't hold a transaction open across PubMed and Gemini calls

        result = await search_papers(
            self._pubmed,
            self._settings,
            snapshot.topic,
            max_results=min(self._settings.search_max_results, snapshot.paper_count * 3),
            start_date=start,
            end_date=end,
        )
        new = [p for p in result.papers if p.pmid not in already_sent][: snapshot.paper_count]

        if not new and not email_when_nothing_new:
            delivery, _, _ = await self._load(db, delivery.id, lock=True)
            if not self._owns(delivery, lease):
                await db.rollback()
                return "lease_lost"
            return await self._finish(
                db, delivery, "skipped_no_new", window_start=start, window_end=end, papers_count=0, mode=mode
            )

        ctx = DigestContext(self._pubmed, self._settings, self._generator, budget, user_id, end)
        section = await assemble_section(
            ctx,
            snapshot,
            new,
            window=f"{start.isoformat()} to {end.isoformat()} (new since your last digest)",
            used_fallback=False,
            total_results=result.total_results,
            use_ai=mode == "allowlist" or self._settings.digest_dry_run_use_ai,
            empty_note=NO_NEW_PAPERS_NOTE,
        )
        digest = DigestOut(
            subject=f"{SCHEDULED_SUBJECT_PREFIX}: {snapshot.topic}"[:200],
            generated_at=now,
            model=self._generator.model if section.ai_status is DigestAiStatus.GENERATED else None,
            sections=[section],
            disclaimer=DISCLAIMER,
        )
        # Real emails get their own unsubscribe token; dry runs show where the link goes.
        token_hash = headers = None
        if mode == "allowlist":
            token, token_hash = new_token()
            unsubscribe_url = page_url(self._settings, token)
            headers = list_unsubscribe_headers(self._settings, token)
        else:
            unsubscribe_url = page_url(self._settings, "dry-run-preview")
        links = {
            "unsubscribe_url": unsubscribe_url,
            "manage_url": f"{self._settings.public_app_url.rstrip('/')}/account",
            "app_url": self._settings.public_app_url,
        }

        delivery, _, _ = await self._load(db, delivery.id, lock=True)
        if not self._owns(delivery, lease):
            await db.rollback()
            return "lease_lost"
        delivery.unsubscribe_token_hash = token_hash
        delivery.email_headers = headers
        delivery.mode = mode
        delivery.email_to = recipient
        delivery.email_subject = digest.subject
        delivery.email_html = render_html(digest, SCHEDULED_NOTICE, **links)
        delivery.email_text = render_text(digest, SCHEDULED_NOTICE, **links)
        delivery.paper_pmids = [p.pmid for p in new]
        delivery.window_start, delivery.window_end = start, end
        delivery.papers_count = len(new)
        await db.commit()
        return None

    async def _confirm_sent(self, db, delivery, sub, now, message_id: str) -> str:
        """The provider accepted it: record everything in ONE transaction."""
        if delivery.paper_pmids:
            await db.execute(
                pg_insert(DigestSentPaper)
                .values(
                    [
                        {"subscription_id": delivery.subscription_id, "pmid": p, "delivery_id": delivery.id,
                         "first_sent_at": now}
                        for p in delivery.paper_pmids
                    ]
                )
                .on_conflict_do_nothing()
            )
        await db.execute(
            update(ResearchSubscription)
            .where(ResearchSubscription.id == delivery.subscription_id)
            .values(last_sent_at=now)
        )
        return await self._finish(
            db,
            delivery,
            "sent",
            provider_message_id=message_id,
            sent_at=now,
            outcome_uncertain=False,
            error_code=None,
        )

    async def _after_failed_send(self, db, delivery, now, exc: EmailError, was_uncertain: bool) -> str:
        uncertain = was_uncertain or exc.outcome_unknown
        if exc.code == "idempotency_conflict":
            status = "needs_review"
        elif not exc.retryable or delivery.attempts >= self._settings.digest_max_attempts:
            status = "needs_review" if uncertain else "failed"
        else:
            status = "pending"
        fields = {"outcome_uncertain": uncertain, "error_code": exc.code}
        if status == "pending":
            fields["next_attempt_at"] = now + backoff(delivery.attempts)
        return await self._finish(db, delivery, status, **fields)
