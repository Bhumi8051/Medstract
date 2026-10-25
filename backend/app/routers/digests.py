"""Research digests (Step C): preview a digest, or send ONE test digest by email.

Safety rules for test emails (all checked before any AI is used or email is sent):
  1. EMAIL_ENABLED must be true, and RESEND_API_KEY set.
  2. The recipient is always the signed-in account's email. It is never read
     from the request (the body rejects unknown fields such as "to").
  3. That address must be listed in EMAIL_TEST_RECIPIENTS. Accounts aren't
     email-verified, so owning the account doesn't prove owning the address.
  4. A per-user hourly limit (in memory).
Resend's test sender (onboarding@resend.dev) adds a fifth, provider-side rule:
it only delivers to the Resend account owner's address.

Nothing here runs automatically; scheduled delivery is Step D.
"""

import uuid
from datetime import date, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select

from app.db_models import ResearchSubscription
from app.models import DigestOut, DigestRequest, EmailStatusOut, TestSendOut
from app.routers.analysis import get_report_generator
from app.routers.deps import DB, AppSettings, CSRFProtected, CurrentUser, get_ai_usage_guard, get_utc_now
from app.routers.errors import email_http_error, pubmed_http_error
from app.routers.search import get_pubmed_client, get_today
from app.services.auth import SlidingWindowLimiter
from app.services.digest import DigestContext, build_digest
from app.services.digest_render import render_html, render_text
from app.services.email import EmailError, EmailMessage, EmailSender
from app.services.gemini import ReportGenerator
from app.services.pubmed import PubMedClient, PubMedError
from app.services.usage import AiUsageGuard

router = APIRouter(prefix="/api/digests", tags=["digests"])

TEST_SENDER_DOMAIN = "@resend.dev"


def get_email_sender(request: Request) -> EmailSender:
    """The shared Resend sender created at startup (see main.py)."""
    return request.app.state.email_sender


def get_email_test_limiter(request: Request) -> SlidingWindowLimiter:
    return request.app.state.email_test_limiter


def recipient_allowed(email: str, settings: AppSettings) -> bool:
    return email.lower() in settings.email_test_recipient_set


async def owned_subscriptions(db: DB, user_id: uuid.UUID, ids: list[uuid.UUID]) -> list[ResearchSubscription]:
    rows = (
        await db.execute(
            select(ResearchSubscription).where(
                ResearchSubscription.user_id == user_id, ResearchSubscription.id.in_(ids)
            )
        )
    ).scalars()
    by_id = {row.id: row for row in rows}
    if len(by_id) != len(ids):
        # Missing or someone else's: same answer either way, so ownership isn't revealed.
        raise HTTPException(status_code=404, detail="Subscription not found.")
    return [by_id[i] for i in ids]  # keep the order the user chose


class Builder:
    """Collects the dependencies needed to build a digest."""

    def __init__(
        self,
        user: CurrentUser,
        db: DB,
        settings: AppSettings,
        pubmed: Annotated[PubMedClient, Depends(get_pubmed_client)],
        generator: Annotated[ReportGenerator, Depends(get_report_generator)],
        usage: Annotated[AiUsageGuard, Depends(get_ai_usage_guard)],
        today: Annotated[date, Depends(get_today)],
        now: Annotated[datetime, Depends(get_utc_now)],
    ) -> None:
        # Plain copies: a usage-limit rollback during the build expires ORM rows.
        self.user_id, self.email = user.id, user.email
        self.db, self.now = db, now
        self.ctx = DigestContext(pubmed, settings, generator, usage, user.id, today)

    async def build(self, body: DigestRequest) -> DigestOut:
        subscriptions = await owned_subscriptions(self.db, self.user_id, body.subscription_ids)
        try:
            return await build_digest(self.ctx, subscriptions, self.now)
        except PubMedError as exc:
            raise pubmed_http_error(exc) from None


DigestBuilder = Annotated[Builder, Depends()]


@router.get("/email-status", response_model=EmailStatusOut)
async def email_status(user: CurrentUser, settings: AppSettings) -> EmailStatusOut:
    """What a test send would do for this account. Never returns the API key."""
    return EmailStatusOut(
        enabled=settings.email_enabled,
        configured=settings.resend_key_value is not None,
        recipient=user.email,
        recipient_allowed=recipient_allowed(user.email, settings),
        sender=settings.email_from,
        test_sender=TEST_SENDER_DOMAIN in settings.email_from.lower(),
        sends_per_hour=settings.email_test_sends_per_hour,
    )


@router.post("/preview", response_model=DigestOut, dependencies=[CSRFProtected])
async def preview_digest(body: DigestRequest, builder: DigestBuilder) -> DigestOut:
    """Build the digest and return it. Sends nothing. AI summaries use the daily allowance."""
    return await builder.build(body)


@router.post("/test-send", response_model=TestSendOut, dependencies=[CSRFProtected])
async def send_test_digest(
    body: DigestRequest,
    builder: DigestBuilder,
    settings: AppSettings,
    sender: Annotated[EmailSender, Depends(get_email_sender)],
    limiter: Annotated[SlidingWindowLimiter, Depends(get_email_test_limiter)],
) -> TestSendOut:
    """Send ONE test digest to the signed-in account's own email address."""
    email = builder.email
    if not settings.email_enabled:
        raise HTTPException(
            status_code=503,
            detail="Email sending is turned off on the server. Set EMAIL_ENABLED=true in backend/.env "
            "and restart the backend.",
        )
    if settings.resend_key_value is None:
        raise HTTPException(
            status_code=503,
            detail="Email is not configured on the server: RESEND_API_KEY is missing. "
            "Add it to backend/.env and restart the backend.",
        )
    if not recipient_allowed(email, settings):
        raise HTTPException(
            status_code=403,
            detail="Test emails can only go to addresses listed in EMAIL_TEST_RECIPIENTS on the server, "
            "and your account email isn't listed.",
        )
    # Ownership is checked before the limiter, so a bad id doesn't use up an attempt.
    await owned_subscriptions(builder.db, builder.user_id, body.subscription_ids)
    if (wait := limiter.hit(str(builder.user_id))) is not None:
        raise HTTPException(
            status_code=429,
            detail=f"You can send up to {settings.email_test_sends_per_hour} test emails per hour. "
            "Please wait and try again.",
            headers={"Retry-After": str(wait)},
        )

    digest = await builder.build(body)
    message = EmailMessage(to=email, subject=digest.subject, html=render_html(digest), text=render_text(digest))
    try:
        sent = await sender.send(message, idempotency_key=f"test-digest-{uuid.uuid4()}")
    except EmailError as exc:
        raise email_http_error(exc) from None
    return TestSendOut(sent_to=email, provider_message_id=sent.provider_message_id, digest=digest)
