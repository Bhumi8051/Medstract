"""Database tables. Schema changes go through Alembic migrations (backend/migrations)."""

import uuid
from datetime import date, datetime, time

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
    Time,
    UniqueConstraint,
    Uuid,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base

# Load server-generated values (created_at, updated_at) back in the INSERT/UPDATE
# itself, so async code never triggers a hidden lazy load.
EAGER = {"eager_defaults": True}


class User(Base):
    __tablename__ = "users"
    __mapper_args__ = EAGER

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    # Stored lowercased by the app; the unique index on lower(email) enforces it in the database too.
    email: Mapped[str] = mapped_column(String(254), nullable=False)
    # Argon2id hash (includes its own salt and parameters). Never the plain password.
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    preferences: Mapped["ResearchPreferences"] = relationship(
        back_populates="user", cascade="all, delete-orphan", uselist=False, lazy="raise"
    )

    __table_args__ = (Index("uq_users_email_lower", func.lower(email), unique=True),)


class UserSession(Base):
    """A login session. Only a SHA-256 hash of the cookie token is stored."""

    __tablename__ = "user_sessions"
    __mapper_args__ = EAGER

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)


class ResearchPreferences(Base):
    __tablename__ = "research_preferences"
    __mapper_args__ = EAGER

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    summary_level: Mapped[str] = mapped_column(String(20), nullable=False, server_default="college")
    research_interests: Mapped[list[str]] = mapped_column(
        ARRAY(String(100)), nullable=False, server_default=text("'{}'::varchar[]")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    user: Mapped[User] = relationship(back_populates="preferences", lazy="raise")

    __table_args__ = (
        CheckConstraint(
            "summary_level IN ('high_school', 'college', 'phd')", name="ck_research_preferences_summary_level"
        ),
    )


class SavedSearch(Base):
    __tablename__ = "saved_searches"
    __mapper_args__ = EAGER

    # Random UUIDs, so IDs can't be guessed or enumerated.
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    query: Mapped[str] = mapped_column(String(500), nullable=False)
    # Validated SavedSearchFilters (app/models.py) as JSON.
    filters: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (Index("ix_saved_searches_user_created", "user_id", text("created_at DESC")),)


class ResearchSubscription(Base):
    """A user's research subscription (stored settings, Step A).

    Nothing is sent on its schedule yet: email_enabled is a stored preference
    until a scheduler exists (Step D). Manual test digests (Step C) read these
    settings but don't change them.
    """

    __tablename__ = "research_subscriptions"
    __mapper_args__ = EAGER

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    # Indexed via the unique (user_id, topic_key) constraint and the created_at index.
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    topic: Mapped[str] = mapped_column(String(200), nullable=False)
    # Normalized topic (services/text.normalize_title, same rule as the frontend's
    # topicKey): lowercase, accents removed, punctuation/spacing collapsed.
    topic_key: Mapped[str] = mapped_column(String(200), nullable=False)
    frequency: Mapped[str] = mapped_column(String(10), nullable=False)
    weekday: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)  # 0 = Sunday … 6 = Saturday
    month_day: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)  # 1-28
    delivery_time: Mapped[time] = mapped_column(Time, nullable=False)
    time_zone: Mapped[str] = mapped_column(String(64), nullable=False)
    paper_count: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    reading_level: Mapped[str] = mapped_column(String(20), nullable=False)
    email_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    email_when_no_new_papers: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    # Step D scheduling. next_run_at is the next delivery instant in UTC, computed
    # from the schedule above (services/schedule.py); NULL while email is off or
    # the subscription is unsubscribed, so the scheduler ignores it.
    next_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Set only after the provider confirmed a scheduled digest was accepted.
    last_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Set by an unsubscribe link (services/unsubscribe.py); cleared when the user
    # turns email back on in the app. Tokens live on each delivery, not here.
    unsubscribed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    __table_args__ = (
        # One subscription per topic per user, using the normalized key.
        UniqueConstraint("user_id", "topic_key", name="uq_research_subscriptions_user_topic"),
        CheckConstraint("topic_key <> ''", name="ck_research_subscriptions_topic_key"),
        CheckConstraint("frequency IN ('daily', 'weekly', 'monthly')", name="ck_research_subscriptions_frequency"),
        CheckConstraint(
            # IS NOT NULL matters: "NULL BETWEEN 0 AND 6" is unknown, which a CHECK would let through.
            "(frequency = 'weekly' AND weekday IS NOT NULL AND weekday BETWEEN 0 AND 6 AND month_day IS NULL)"
            " OR (frequency = 'monthly' AND month_day IS NOT NULL AND month_day BETWEEN 1 AND 28 AND weekday IS NULL)"
            " OR (frequency = 'daily' AND weekday IS NULL AND month_day IS NULL)",
            name="ck_research_subscriptions_schedule",
        ),
        CheckConstraint("paper_count IN (5, 10, 15, 20)", name="ck_research_subscriptions_paper_count"),
        CheckConstraint(
            "reading_level IN ('high_school', 'college', 'phd')", name="ck_research_subscriptions_reading_level"
        ),
        Index("ix_research_subscriptions_user_created", "user_id", text("created_at DESC")),
        # The scheduler's "what is due?" query.
        Index("ix_research_subscriptions_next_run", "next_run_at"),
    )


class AiUsageDaily(Base):
    """Successful AI analyses per user per UTC day (Step B usage limit).

    Incremented atomically (INSERT ... ON CONFLICT DO UPDATE ... WHERE used < limit)
    before Gemini is called, and decremented again if the analysis fails.
    """

    __tablename__ = "ai_usage_daily"

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    usage_date: Mapped[date] = mapped_column(Date, primary_key=True)
    used: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))

    __table_args__ = (CheckConstraint("used >= 0", name="ck_ai_usage_daily_used"),)


class AiUsageDailyTotal(Base):
    """Successful AI analyses by all users per UTC day (protects the project's Gemini quota)."""

    __tablename__ = "ai_usage_daily_total"

    usage_date: Mapped[date] = mapped_column(Date, primary_key=True)
    used: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))

    __table_args__ = (CheckConstraint("used >= 0", name="ck_ai_usage_daily_total_used"),)


DELIVERY_STATUSES = (
    "pending",  # waiting to be sent (or to be retried at next_attempt_at)
    "sending",  # claimed by a worker until lease_until
    "sent",  # the provider accepted it (provider_message_id set)
    "dry_run",  # built but deliberately not sent (DIGEST_DELIVERY_MODE=dry_run)
    "skipped_no_new",  # nothing new and the user didn't want "nothing new" emails
    "skipped_missed",  # overdue beyond the grace period (e.g. the server was off)
    "skipped_disabled",  # email turned off / unsubscribed / recipient not allowed when it was due
    "failed",  # permanent error, or retries used up
    "needs_review",  # outcome unknown and too old to retry safely (could duplicate)
)


class DigestDelivery(Base):
    """One scheduled run of one subscription (Step D).

    UNIQUE (subscription_id, scheduled_for) means each scheduled run exists at
    most once, however many schedulers are running. idempotency_key is sent to
    the email provider on every attempt, so a retry after an unclear outcome
    can't deliver twice (within the provider's retention window; see
    first_attempt_at).
    """

    __tablename__ = "digest_deliveries"
    __mapper_args__ = EAGER

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    subscription_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("research_subscriptions.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    scheduled_for: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default=text("'pending'"))
    attempts: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default=text("0"))
    # When the first send attempt started. Retries with the same idempotency key
    # are only safe while the provider still remembers it (Resend: 24 hours).
    first_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    next_attempt_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    idempotency_key: Mapped[str] = mapped_column(String(100), nullable=False)
    # Publication-date window searched (inclusive), recorded when the digest is built.
    window_start: Mapped[date | None] = mapped_column(Date, nullable=True)
    window_end: Mapped[date | None] = mapped_column(Date, nullable=True)
    papers_count: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    # True once an attempt ended without a clear answer (timeout, 5xx, crash while
    # sending): the email may already have been delivered. Sticky until a later
    # attempt with the same key is confirmed.
    outcome_uncertain: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    # Mode when the digest was built ("dry_run" or "allowlist").
    mode: Mapped[str | None] = mapped_column(String(10), nullable=True)
    # The exact email, frozen before the first send attempt. Retries resend it
    # unchanged: Resend answers 409 if an idempotency key is reused with a
    # different payload.
    email_to: Mapped[str | None] = mapped_column(String(254), nullable=True)
    email_subject: Mapped[str | None] = mapped_column(String(200), nullable=True)
    email_html: Mapped[str | None] = mapped_column(Text, nullable=True)
    email_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    # PMIDs in the frozen email; copied to digest_sent_papers only once it is sent.
    paper_pmids: Mapped[list[str] | None] = mapped_column(ARRAY(String(10)), nullable=True)
    # Short, fixed code such as "resend_429" or "timeout_unknown"; never provider text.
    error_code: Mapped[str | None] = mapped_column(String(40), nullable=True)
    provider_message_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    # Extra headers frozen with the email (List-Unsubscribe ...), resent unchanged.
    email_headers: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    # SHA-256 of this email's unsubscribe token. The token itself is only in the
    # email; the stored copy of the email is scrubbed once the delivery is final.
    unsubscribe_token_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint("subscription_id", "scheduled_for", name="uq_digest_deliveries_subscription_run"),
        UniqueConstraint("idempotency_key", name="uq_digest_deliveries_idempotency_key"),
        UniqueConstraint("unsubscribe_token_hash", name="uq_digest_deliveries_unsubscribe_token"),
        CheckConstraint(
            "status IN (" + ", ".join(f"'{s}'" for s in DELIVERY_STATUSES) + ")",
            name="ck_digest_deliveries_status",
        ),
        CheckConstraint("attempts >= 0", name="ck_digest_deliveries_attempts"),
        CheckConstraint("mode IS NULL OR mode IN ('dry_run', 'allowlist')", name="ck_digest_deliveries_mode"),
        CheckConstraint(
            "window_start IS NULL OR window_end IS NULL OR window_start <= window_end",
            name="ck_digest_deliveries_window",
        ),
        # A "sent" row always records what the provider accepted.
        CheckConstraint(
            "status <> 'sent' OR (provider_message_id IS NOT NULL AND sent_at IS NOT NULL)",
            name="ck_digest_deliveries_sent",
        ),
        # The worker's "what can I claim?" query.
        Index("ix_digest_deliveries_due", "status", "next_attempt_at"),
        # A user's delivery history, newest first.
        Index("ix_digest_deliveries_user_created", "user_id", text("created_at DESC")),
    )


class DigestSentPaper(Base):
    """A paper already emailed for a subscription, so later digests skip it.

    Written in the same transaction that marks the delivery "sent", i.e. only
    after the provider confirmed it; a failed or unclear send records nothing.
    """

    __tablename__ = "digest_sent_papers"

    subscription_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("research_subscriptions.id", ondelete="CASCADE"), primary_key=True
    )
    pmid: Mapped[str] = mapped_column(String(10), primary_key=True)
    delivery_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("digest_deliveries.id", ondelete="CASCADE"), nullable=False
    )
    first_sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        CheckConstraint("pmid ~ '^[1-9][0-9]{0,9}$'", name="ck_digest_sent_papers_pmid"),
    )
