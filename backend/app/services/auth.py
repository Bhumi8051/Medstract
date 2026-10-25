"""Password hashing, login sessions and login throttling.

- Passwords: Argon2id (argon2-cffi defaults, per RFC 9106). Hashing runs in a
  worker thread so it doesn't block other requests.
- Sessions: a random 256-bit token goes to the browser in an HttpOnly cookie;
  the database stores only its SHA-256, so a database leak can't be replayed.
- Throttling: failed logins are counted per email in memory (single process).
"""

import hashlib
import secrets
import time
import uuid
from collections import deque
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from app.config import Settings
from app.db_models import User, UserSession

_hasher = PasswordHasher()
# Verified against when the email doesn't exist, so "unknown email" and
# "wrong password" take the same time and can't be told apart.
_DUMMY_HASH = _hasher.hash(secrets.token_urlsafe(16))


async def hash_password(password: str) -> str:
    return await run_in_threadpool(_hasher.hash, password)


async def verify_password(password_hash: str | None, password: str) -> bool:
    def _verify() -> bool:
        try:
            return _hasher.verify(password_hash or _DUMMY_HASH, password) and password_hash is not None
        except (VerifyMismatchError, VerificationError, InvalidHashError):
            return False

    return await run_in_threadpool(_verify)


def needs_rehash(password_hash: str) -> bool:
    """True if the hash was made with weaker parameters than the current defaults."""
    return _hasher.check_needs_rehash(password_hash)


def normalize_email(email: str) -> str:
    return email.strip().lower()


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


async def create_session(db: AsyncSession, user: User, settings: Settings) -> tuple[str, datetime]:
    """Store a new session and return (token for the cookie, expiry). Also prunes the user's expired sessions."""
    now = datetime.now(UTC)
    await db.execute(delete(UserSession).where(UserSession.user_id == user.id, UserSession.expires_at <= now))
    token = secrets.token_urlsafe(32)
    expires_at = now + timedelta(days=settings.session_ttl_days)
    db.add(UserSession(user_id=user.id, token_hash=hash_token(token), expires_at=expires_at))
    return token, expires_at


async def user_for_token(db: AsyncSession, token: str | None) -> User | None:
    if not token or len(token) > 200:
        return None
    stmt = (
        select(User)
        .join(UserSession, UserSession.user_id == User.id)
        .where(UserSession.token_hash == hash_token(token), UserSession.expires_at > datetime.now(UTC))
    )
    return (await db.execute(stmt)).scalar_one_or_none()


async def delete_session(db: AsyncSession, token: str | None) -> None:
    if token:
        await db.execute(delete(UserSession).where(UserSession.token_hash == hash_token(token)))


async def delete_all_sessions(db: AsyncSession, user_id: uuid.UUID) -> None:
    await db.execute(delete(UserSession).where(UserSession.user_id == user_id))


class SlidingWindowLimiter:
    """At most `max_events` events per key within `window_seconds`.

    Used for failed logins (per email and per IP), registrations per IP and
    analysis bursts per user.

    IN-MEMORY ONLY: counters reset when the server restarts and are NOT shared
    between multiple workers or servers. That is fine for the current single-
    process development setup; switch to a shared store (Redis or PostgreSQL)
    before running several workers, or each worker gets its own allowance.
    """

    _MAX_TRACKED = 10_000  # bound memory if someone sprays random keys

    def __init__(self, max_events: int, window_seconds: int, clock: Callable[[], float] = time.monotonic) -> None:
        self.max_events = max_events
        self.window_seconds = window_seconds
        self._clock = clock
        self._events: dict[str, deque[float]] = {}

    def _recent(self, key: str, now: float) -> deque[float]:
        events = self._events.get(key, deque())
        while events and now - events[0] > self.window_seconds:
            events.popleft()
        return events

    def retry_after(self, key: str) -> int | None:
        """Seconds until another event is allowed, or None if allowed now."""
        now = self._clock()
        events = self._recent(key, now)
        if len(events) < self.max_events:
            return None
        return max(1, int(self.window_seconds - (now - events[0])) + 1)

    def record(self, key: str) -> None:
        now = self._clock()
        if key not in self._events and len(self._events) >= self._MAX_TRACKED:
            self._events.pop(next(iter(self._events)))
        events = self._recent(key, now)
        events.append(now)
        self._events[key] = events

    def hit(self, key: str) -> int | None:
        """Check and record in one step: returns retry-after seconds if over the limit, else records and returns None."""
        wait = self.retry_after(key)
        if wait is None:
            self.record(key)
        return wait

    def reset(self, key: str) -> None:
        self._events.pop(key, None)


class LoginThrottle(SlidingWindowLimiter):
    """Failed logins per email (kept for compatibility; same in-memory caveats)."""

    def __init__(self, max_failures: int, window_seconds: int, clock: Callable[[], float] = time.monotonic) -> None:
        super().__init__(max_failures, window_seconds, clock)

    @property
    def max_failures(self) -> int:
        return self.max_events

    def record_failure(self, key: str) -> None:
        self.record(key)
