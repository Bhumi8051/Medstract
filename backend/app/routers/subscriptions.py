"""The logged-in user's research subscriptions (Step A: stored settings only).

Same conventions as saved searches: login required, CSRF header on changes,
every query filtered by the current user, and another user's subscription
answers 404 (not 403) so its existence isn't revealed. Each save keeps
next_run_at (the next due time, UTC) up to date for the Step D scheduler, but
no scheduler runs yet and responses always carry delivery_active=false.
"""

import uuid
from datetime import datetime, time
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.db_models import ResearchSubscription
from app.models import (
    MAX_SUBSCRIPTIONS_PER_USER,
    SubscriptionFrequency,
    SubscriptionIn,
    SubscriptionOut,
    SummaryLevel,
)
from app.routers.deps import DB, AppSettings, CSRFProtected, CurrentUser, get_utc_now
from app.services.delivery import cancel_queued, scheduled_delivery_active
from app.services.schedule import next_run_after
from app.services.text import normalize_title

router = APIRouter(prefix="/api/subscriptions", tags=["subscriptions"])

DUPLICATE_TOPIC = "You already have a subscription for this topic."
UNIQUE_CONSTRAINT = "uq_research_subscriptions_user_topic"


def subscription_out(row: ResearchSubscription, *, sending: bool = False) -> SubscriptionOut:
    """`sending`: the scheduler would email this account now (scheduled_delivery_active)."""
    return SubscriptionOut(
        id=row.id,
        topic=row.topic,
        frequency=SubscriptionFrequency(row.frequency),
        weekday=row.weekday,
        month_day=row.month_day,
        delivery_time=row.delivery_time.strftime("%H:%M"),
        time_zone=row.time_zone,
        paper_count=row.paper_count,
        reading_level=SummaryLevel(row.reading_level),
        email_enabled=row.email_enabled,
        email_when_no_new_papers=row.email_when_no_new_papers,
        delivery_active=sending and row.email_enabled and row.unsubscribed_at is None,
        next_run_at=row.next_run_at,
        last_sent_at=row.last_sent_at,
        unsubscribed_at=row.unsubscribed_at,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def apply_settings(row: ResearchSubscription, body: SubscriptionIn) -> None:
    hours, minutes = (int(part) for part in body.delivery_time.split(":"))
    row.topic = body.topic
    row.topic_key = normalize_title(body.topic)
    row.frequency = body.frequency.value
    row.weekday = body.weekday
    row.month_day = body.month_day
    row.delivery_time = time(hours, minutes)
    row.time_zone = body.time_zone
    row.paper_count = body.paper_count
    row.reading_level = body.reading_level.value
    row.email_enabled = body.email_enabled
    row.email_when_no_new_papers = body.email_when_no_new_papers


def schedule_state(row: ResearchSubscription) -> tuple:
    """Everything that decides when (and whether) the next digest is due."""
    return (
        row.frequency,
        row.weekday,
        row.month_day,
        row.delivery_time,
        row.time_zone,
        row.email_enabled,
        row.unsubscribed_at,
    )


def refresh_schedule(row: ResearchSubscription, now: datetime, *, changed: bool) -> None:
    """Keep next_run_at in step with the settings (Step D).

    NULL while email is off or the subscription is unsubscribed, so the
    scheduler never picks it up. Otherwise it is recomputed from `now` whenever
    the schedule or status changed, and left alone for other edits (a topic
    rename doesn't move the next delivery).
    """
    if not row.email_enabled or row.unsubscribed_at is not None:
        row.next_run_at = None
        return
    if changed or row.next_run_at is None:
        row.next_run_at = next_run_after(
            frequency=SubscriptionFrequency(row.frequency),
            weekday=row.weekday,
            month_day=row.month_day,
            delivery_time=row.delivery_time,
            time_zone=row.time_zone,
            after=now,
        )


Now = Annotated[datetime, Depends(get_utc_now)]


async def get_owned(db: DB, user_id: uuid.UUID, subscription_id: uuid.UUID) -> ResearchSubscription:
    row = (
        await db.execute(
            select(ResearchSubscription).where(
                ResearchSubscription.id == subscription_id, ResearchSubscription.user_id == user_id
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Subscription not found.")
    return row


async def commit_or_conflict(db: DB) -> None:
    """Commit; turn the per-user unique-topic constraint into a clear 409."""
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        if UNIQUE_CONSTRAINT in str(exc.orig):
            raise HTTPException(status_code=409, detail=DUPLICATE_TOPIC) from None
        raise


@router.get("", response_model=list[SubscriptionOut])
async def list_subscriptions(user: CurrentUser, db: DB, settings: AppSettings) -> list[SubscriptionOut]:
    rows = (
        await db.execute(
            select(ResearchSubscription)
            .where(ResearchSubscription.user_id == user.id)
            .order_by(ResearchSubscription.created_at.desc())
            .limit(MAX_SUBSCRIPTIONS_PER_USER)
        )
    ).scalars()
    sending = scheduled_delivery_active(settings, user.email)
    return [subscription_out(row, sending=sending) for row in rows]


@router.post("", status_code=201, response_model=SubscriptionOut, dependencies=[CSRFProtected])
async def create_subscription(
    body: SubscriptionIn, user: CurrentUser, db: DB, now: Now, settings: AppSettings
) -> SubscriptionOut:
    count = await db.scalar(
        select(func.count()).select_from(ResearchSubscription).where(ResearchSubscription.user_id == user.id)
    )
    if (count or 0) >= MAX_SUBSCRIPTIONS_PER_USER:
        raise HTTPException(
            status_code=409,
            detail=f"You can have up to {MAX_SUBSCRIPTIONS_PER_USER} subscriptions. Remove one to add another.",
        )
    row = ResearchSubscription(user_id=user.id)
    apply_settings(row, body)
    refresh_schedule(row, now, changed=True)
    db.add(row)
    await commit_or_conflict(db)
    return subscription_out(row, sending=scheduled_delivery_active(settings, user.email))


@router.get("/{subscription_id}", response_model=SubscriptionOut)
async def get_subscription(
    subscription_id: uuid.UUID, user: CurrentUser, db: DB, settings: AppSettings
) -> SubscriptionOut:
    row = await get_owned(db, user.id, subscription_id)
    return subscription_out(row, sending=scheduled_delivery_active(settings, user.email))


@router.put("/{subscription_id}", response_model=SubscriptionOut, dependencies=[CSRFProtected])
async def update_subscription(
    subscription_id: uuid.UUID, body: SubscriptionIn, user: CurrentUser, db: DB, now: Now, settings: AppSettings
) -> SubscriptionOut:
    row = await get_owned(db, user.id, subscription_id)
    before = schedule_state(row)
    was_enabled = row.email_enabled
    apply_settings(row, body)
    if row.email_enabled and not was_enabled:
        row.unsubscribed_at = None  # turning email back on in the app re-subscribes
    changed = schedule_state(row) != before
    refresh_schedule(row, now, changed=changed)
    if changed:
        # A digest queued for the old schedule (or while email was on) must not go out.
        await cancel_queued(db, row.id, "email_off" if not row.email_enabled else "schedule_changed")
    await commit_or_conflict(db)
    return subscription_out(row, sending=scheduled_delivery_active(settings, user.email))


@router.delete("/{subscription_id}", status_code=204, dependencies=[CSRFProtected])
async def delete_subscription(subscription_id: uuid.UUID, user: CurrentUser, db: DB) -> Response:
    row = await get_owned(db, user.id, subscription_id)
    await db.delete(row)
    await db.commit()
    return Response(status_code=204)
