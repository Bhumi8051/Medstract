"""Server-side Gemini usage limits (Step B).

Each analysis first *reserves* one unit of the user's daily allowance and of the
overall daily allowance, in one database transaction:

    INSERT ... VALUES (..., used = 1)
    ON CONFLICT (key) DO UPDATE SET used = used + 1 WHERE used < :limit
    RETURNING used

No row returned means the limit was already reached. PostgreSQL locks the row
for the update, so concurrent requests can't both slip past the limit. If the
analysis then fails, the reservation is refunded, so only successful analyses
count. Days are UTC.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.db_models import AiUsageDaily, AiUsageDailyTotal
from app.services.auth import SlidingWindowLimiter


class UsageLimitError(Exception):
    """A usage limit was reached. `str(error)` is safe to show the user."""

    def __init__(self, message: str, retry_after_seconds: int) -> None:
        super().__init__(message)
        self.retry_after_seconds = retry_after_seconds


@dataclass(frozen=True)
class Reservation:
    user_id: uuid.UUID
    usage_date: date
    counted_total: bool


@dataclass(frozen=True)
class UsageSnapshot:
    used: int
    limit: int
    remaining: int
    resets_at: datetime


def next_utc_midnight(now: datetime) -> datetime:
    return datetime.combine(now.astimezone(UTC).date() + timedelta(days=1), time.min, tzinfo=UTC)


def seconds_until_reset(now: datetime) -> int:
    return max(1, int((next_utc_midnight(now) - now).total_seconds()))


class AiUsageGuard:
    """Per-request helper: burst check + atomic daily reservation, refund, and snapshot."""

    def __init__(self, db: AsyncSession, settings: Settings, burst: SlidingWindowLimiter, now: datetime) -> None:
        self._db = db
        self._settings = settings
        self._burst = burst
        self._now = now

    async def reserve(self, user_id: uuid.UUID) -> Reservation:
        # 1. Short-term brake (in memory, per user).
        if (wait := self._burst.hit(str(user_id))) is not None:
            raise UsageLimitError("You're starting analyses too quickly. Wait a moment and try again.", wait)

        day = self._now.astimezone(UTC).date()
        reset_in = seconds_until_reset(self._now)
        total_limit = self._settings.ai_daily_limit_total
        user_limit = self._settings.ai_daily_limit_per_user
        try:
            # 2. Overall daily cap (all users), if enabled.
            if total_limit > 0:
                stmt = pg_insert(AiUsageDailyTotal).values(usage_date=day, used=1)
                stmt = stmt.on_conflict_do_update(
                    index_elements=[AiUsageDailyTotal.usage_date],
                    set_={"used": AiUsageDailyTotal.used + 1},
                    where=AiUsageDailyTotal.used < total_limit,
                ).returning(AiUsageDailyTotal.used)
                if (await self._db.execute(stmt)).first() is None:
                    raise UsageLimitError(
                        "The daily AI analysis capacity for this service has been reached. "
                        "Please try again after midnight UTC.",
                        reset_in,
                    )
            # 3. This user's daily cap.
            stmt = pg_insert(AiUsageDaily).values(user_id=user_id, usage_date=day, used=1)
            stmt = stmt.on_conflict_do_update(
                index_elements=[AiUsageDaily.user_id, AiUsageDaily.usage_date],
                set_={"used": AiUsageDaily.used + 1},
                where=AiUsageDaily.used < user_limit,
            ).returning(AiUsageDaily.used)
            if (await self._db.execute(stmt)).first() is None:
                raise UsageLimitError(
                    f"You've used all {user_limit} AI analyses for today. They reset at midnight UTC.",
                    reset_in,
                )
        except UsageLimitError:
            await self._db.rollback()  # also undoes the overall-cap increment
            raise
        await self._db.commit()  # visible to concurrent requests before Gemini is called
        return Reservation(user_id=user_id, usage_date=day, counted_total=total_limit > 0)

    async def refund(self, reservation: Reservation) -> None:
        """Give the unit back (the analysis failed). Never goes below zero."""
        await self._db.rollback()  # discard anything half-done in this session
        await self._db.execute(
            update(AiUsageDaily)
            .where(AiUsageDaily.user_id == reservation.user_id, AiUsageDaily.usage_date == reservation.usage_date)
            .values(used=func.greatest(AiUsageDaily.used - 1, 0))
        )
        if reservation.counted_total:
            await self._db.execute(
                update(AiUsageDailyTotal)
                .where(AiUsageDailyTotal.usage_date == reservation.usage_date)
                .values(used=func.greatest(AiUsageDailyTotal.used - 1, 0))
            )
        await self._db.commit()

    async def snapshot(self, user_id: uuid.UUID) -> UsageSnapshot:
        day = self._now.astimezone(UTC).date()
        used = await self._db.scalar(
            select(AiUsageDaily.used).where(AiUsageDaily.user_id == user_id, AiUsageDaily.usage_date == day)
        )
        used = used or 0
        limit = self._settings.ai_daily_limit_per_user
        remaining = max(0, limit - used)
        if self._settings.ai_daily_limit_total > 0:
            total_used = await self._db.scalar(
                select(AiUsageDailyTotal.used).where(AiUsageDailyTotal.usage_date == day)
            )
            remaining = min(remaining, max(0, self._settings.ai_daily_limit_total - (total_used or 0)))
        return UsageSnapshot(used=used, limit=limit, remaining=remaining, resets_at=next_utc_midnight(self._now))
