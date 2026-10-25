"""Background loop that runs the digest delivery engine (Step D).

Started by the FastAPI app only when DIGEST_SCHEDULER_ENABLED=true (default
false). Each tick first takes a PostgreSQL advisory lock, so only one process
ticks at a time even with several backends or a `run-once` command running;
the delivery engine's SKIP LOCKED claims and unique constraints would prevent
duplicates anyway, the lock just avoids wasted work.
"""

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.services.delivery import DeliveryEngine, TickResult

logger = logging.getLogger(__name__)

# Arbitrary constant identifying "the digest scheduler" among advisory locks.
SCHEDULER_LOCK_KEY = 4_815_162_342


@asynccontextmanager
async def scheduler_lock(engine: AsyncEngine) -> AsyncIterator[bool]:
    """Yields True if this process may tick now (held until the block ends)."""
    async with engine.connect() as conn:
        acquired = bool(await conn.scalar(text("SELECT pg_try_advisory_lock(:k)"), {"k": SCHEDULER_LOCK_KEY}))
        try:
            yield acquired
        finally:
            if acquired:
                await conn.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": SCHEDULER_LOCK_KEY})
            await conn.commit()


async def run_locked_tick(engine: AsyncEngine, delivery: DeliveryEngine) -> TickResult | None:
    """One tick if no other scheduler holds the lock; None if it was busy."""
    async with scheduler_lock(engine) as acquired:
        if not acquired:
            logger.info("Digest tick skipped: another scheduler is running")
            return None
        return await delivery.tick()


# Outcomes worth a WARNING (uvicorn shows warnings; routine INFO lines are hidden by default).
NOTABLE_OUTCOMES = ("failed", "needs_review")


class DigestScheduler:
    def __init__(self, engine: AsyncEngine, delivery: DeliveryEngine, interval_seconds: int) -> None:
        self._engine = engine
        self._delivery = delivery
        self._interval = interval_seconds
        self._task: asyncio.Task | None = None
        # Heartbeat, reported by GET /health (in memory, this process only).
        self.started_at: datetime | None = None
        self.last_tick_at: datetime | None = None  # last attempt, successful or not
        self.last_success_at: datetime | None = None
        self.last_summary: str | None = None
        self.last_error: str | None = None  # exception type name only
        self.consecutive_failures = 0

    def start(self) -> None:
        self.started_at = datetime.now(UTC)
        self._task = asyncio.create_task(self._run(), name="digest-scheduler")

    def health(self, now: datetime | None = None) -> dict:
        """Safe-to-share status: times, counts and type names; no addresses, tokens or content."""
        now = now or datetime.now(UTC)
        running = self._task is not None and not self._task.done()
        reference = self.last_tick_at or self.started_at
        stale = running and reference is not None and (now - reference).total_seconds() > 3 * self._interval + 30
        return {
            "running": running,
            "interval_seconds": self._interval,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "last_tick_at": self.last_tick_at.isoformat() if self.last_tick_at else None,
            "last_success_at": self.last_success_at.isoformat() if self.last_success_at else None,
            "last_summary": self.last_summary,
            "last_error": self.last_error,
            "consecutive_failures": self.consecutive_failures,
            "stale": stale,
        }

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def run_once(self) -> None:
        """One loop iteration (also used by tests)."""
        self.last_tick_at = datetime.now(UTC)
        try:
            result = await run_locked_tick(self._engine, self._delivery)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - keep the loop alive; the next tick retries
            self.consecutive_failures += 1
            self.last_error = type(exc).__name__
            logger.error(
                "Digest scheduler tick failed (%s); %s in a row. See GET /health and "
                "`python -m app.jobs.digests status`.", self.last_error, self.consecutive_failures,
            )
            return
        self.consecutive_failures = 0
        self.last_error = None
        self.last_success_at = self.last_tick_at
        if result is None:
            self.last_summary = "skipped: another scheduler holds the lock"
            return
        self.last_summary = result.summary()
        if result.recovered or any(result.outcomes.get(o) for o in NOTABLE_OUTCOMES):
            logger.warning(
                "Digest tick needs attention: %s. Run `python -m app.jobs.digests status`.", self.last_summary
            )

    async def _run(self) -> None:
        while True:
            await self.run_once()
            await asyncio.sleep(self._interval)
