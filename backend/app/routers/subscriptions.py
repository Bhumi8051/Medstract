"""The logged-in user's research subscriptions (Step A: stored settings only).

Same conventions as saved searches: login required, CSRF header on changes,
every query filtered by the current user, and another user's subscription
answers 404 (not 403) so its existence isn't revealed. Nothing is scheduled
or emailed yet; responses always carry delivery_active=false.
"""

import uuid
from datetime import time

from fastapi import APIRouter, HTTPException, Response
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
from app.routers.deps import DB, CSRFProtected, CurrentUser
from app.services.text import normalize_title

router = APIRouter(prefix="/api/subscriptions", tags=["subscriptions"])

DUPLICATE_TOPIC = "You already have a subscription for this topic."
UNIQUE_CONSTRAINT = "uq_research_subscriptions_user_topic"


def subscription_out(row: ResearchSubscription) -> SubscriptionOut:
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
async def list_subscriptions(user: CurrentUser, db: DB) -> list[SubscriptionOut]:
    rows = (
        await db.execute(
            select(ResearchSubscription)
            .where(ResearchSubscription.user_id == user.id)
            .order_by(ResearchSubscription.created_at.desc())
            .limit(MAX_SUBSCRIPTIONS_PER_USER)
        )
    ).scalars()
    return [subscription_out(row) for row in rows]


@router.post("", status_code=201, response_model=SubscriptionOut, dependencies=[CSRFProtected])
async def create_subscription(body: SubscriptionIn, user: CurrentUser, db: DB) -> SubscriptionOut:
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
    db.add(row)
    await commit_or_conflict(db)
    return subscription_out(row)


@router.get("/{subscription_id}", response_model=SubscriptionOut)
async def get_subscription(subscription_id: uuid.UUID, user: CurrentUser, db: DB) -> SubscriptionOut:
    return subscription_out(await get_owned(db, user.id, subscription_id))


@router.put("/{subscription_id}", response_model=SubscriptionOut, dependencies=[CSRFProtected])
async def update_subscription(
    subscription_id: uuid.UUID, body: SubscriptionIn, user: CurrentUser, db: DB
) -> SubscriptionOut:
    row = await get_owned(db, user.id, subscription_id)
    apply_settings(row, body)
    await commit_or_conflict(db)
    return subscription_out(row)


@router.delete("/{subscription_id}", status_code=204, dependencies=[CSRFProtected])
async def delete_subscription(subscription_id: uuid.UUID, user: CurrentUser, db: DB) -> Response:
    row = await get_owned(db, user.id, subscription_id)
    await db.delete(row)
    await db.commit()
    return Response(status_code=204)
