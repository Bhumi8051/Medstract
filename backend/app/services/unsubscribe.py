"""Unsubscribe links for scheduled digests (Step D, stage 3).

Each scheduled email gets its own random token (256 bits, URL-safe). Only its
SHA-256 is stored, on that email's digest_deliveries row; the token itself is in
the email and, while a retry may still resend that exact email, in the frozen
copy of it, which is scrubbed once the delivery is final (scrub_tokens).

Using a link needs no login. Unsubscribing is idempotent: it sets
unsubscribed_at once, turns email off, clears next_run_at and cancels queued
deliveries (cancel_queued keeps "may have been sent" ones as needs_review).
"""

import re
import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime
from urllib.parse import quote

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.db_models import DigestDelivery, ResearchSubscription
from app.services.auth import hash_token

TOKEN_BYTES = 32
# token_urlsafe(32) is always 43 characters from this alphabet.
TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{43}$")
# Finds tokens inside stored emails and headers, for scrubbing.
_TOKEN_IN_URL_RE = re.compile(r"(token=)[A-Za-z0-9_-]{43}")
REMOVED = "removed"


def new_token() -> tuple[str, str]:
    """(token, sha256 hex). The token goes into the email; only the hash is stored."""
    token = secrets.token_urlsafe(TOKEN_BYTES)
    return token, hash_token(token)


def valid_format(token: str | None) -> bool:
    return bool(token) and bool(TOKEN_RE.match(token))


def page_url(settings: Settings, token: str) -> str:
    """The frontend confirmation page (the link shown in the email body)."""
    return f"{settings.public_app_url.rstrip('/')}/unsubscribe?token={quote(token)}"


def one_click_url(settings: Settings, token: str) -> str:
    """The backend endpoint mail providers POST to (RFC 8058)."""
    return f"{settings.public_api_url.rstrip('/')}/api/unsubscribe/one-click?token={quote(token)}"


def list_unsubscribe_headers(settings: Settings, token: str) -> dict[str, str]:
    headers = {"List-Unsubscribe": f"<{one_click_url(settings, token)}>"}
    # RFC 8058: one-click needs an https URI (and a DKIM signature covering these
    # headers, which a verified sending domain provides).
    if settings.public_api_url.startswith("https://"):
        headers["List-Unsubscribe-Post"] = "List-Unsubscribe=One-Click"
    return headers


def scrub_tokens(text: str | None) -> str | None:
    return _TOKEN_IN_URL_RE.sub(rf"\g<1>{REMOVED}", text) if text else text


@dataclass(frozen=True)
class LinkInfo:
    subscription_id: uuid.UUID
    topic: str
    unsubscribed: bool


async def find_link(db: AsyncSession, token: str | None) -> LinkInfo | None:
    """Look a token up without changing anything (for the confirmation page)."""
    if not valid_format(token):
        return None
    row = (
        await db.execute(
            select(ResearchSubscription)
            .join(DigestDelivery, DigestDelivery.subscription_id == ResearchSubscription.id)
            .where(DigestDelivery.unsubscribe_token_hash == hash_token(token))
        )
    ).scalar_one_or_none()
    if row is None:
        return None
    return LinkInfo(row.id, row.topic, row.unsubscribed_at is not None)


async def unsubscribe(db: AsyncSession, token: str | None, now: datetime) -> tuple[LinkInfo, bool] | None:
    """Unsubscribe the subscription this token belongs to.

    Returns (info, changed): changed is False when it was already unsubscribed.
    None means the token is malformed or unknown. Commits.
    """
    if not valid_format(token):
        return None
    sub_id = await db.scalar(
        select(DigestDelivery.subscription_id).where(DigestDelivery.unsubscribe_token_hash == hash_token(token))
    )
    if sub_id is None:
        return None
    sub = (
        await db.execute(select(ResearchSubscription).where(ResearchSubscription.id == sub_id).with_for_update())
    ).scalar_one_or_none()
    if sub is None:
        return None
    from app.services.delivery import cancel_queued  # local import: delivery.py imports this module

    changed = sub.unsubscribed_at is None
    if changed:
        sub.unsubscribed_at = now
    sub.email_enabled = False
    sub.next_run_at = None
    await cancel_queued(db, sub.id, "unsubscribed")  # harmless if nothing is queued
    await db.commit()
    return LinkInfo(sub.id, sub.topic, True), changed
