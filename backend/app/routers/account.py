"""The logged-in user's research preferences and saved searches.

Every query is filtered by the current user's id. Another user's saved search
answers 404 (not 403), so its existence isn't revealed.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import func, select

from app.db_models import SavedSearch
from app.models import (
    MAX_SAVED_SEARCHES_PER_USER,
    PreferencesIn,
    PreferencesOut,
    SavedSearchCreate,
    SavedSearchFilters,
    SavedSearchOut,
    AiUsageOut,
    SummaryLevel,
)
from app.routers.auth import load_preferences
from app.routers.deps import DB, CSRFProtected, CurrentUser, get_ai_usage_guard
from app.services.usage import AiUsageGuard

router = APIRouter(prefix="/api", tags=["account"])


def saved_search_out(row: SavedSearch) -> SavedSearchOut:
    return SavedSearchOut(
        id=row.id,
        name=row.name,
        query=row.query,
        filters=SavedSearchFilters.model_validate(row.filters),
        created_at=row.created_at,
    )


async def get_owned_search(db: DB, user_id: uuid.UUID, search_id: uuid.UUID) -> SavedSearch:
    row = (
        await db.execute(select(SavedSearch).where(SavedSearch.id == search_id, SavedSearch.user_id == user_id))
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Saved search not found.")
    return row


# ---------- preferences ----------


@router.get("/me/preferences", response_model=PreferencesOut)
async def get_preferences(user: CurrentUser, db: DB) -> PreferencesOut:
    preferences = await load_preferences(db, user)
    await db.commit()
    return PreferencesOut(
        summary_level=SummaryLevel(preferences.summary_level),
        research_interests=list(preferences.research_interests),
    )


@router.put("/me/preferences", response_model=PreferencesOut, dependencies=[CSRFProtected])
async def update_preferences(body: PreferencesIn, user: CurrentUser, db: DB) -> PreferencesOut:
    preferences = await load_preferences(db, user)
    preferences.summary_level = body.summary_level.value
    preferences.research_interests = body.research_interests
    await db.commit()
    return PreferencesOut(summary_level=body.summary_level, research_interests=body.research_interests)


# ---------- AI usage ----------


@router.get("/me/ai-usage", response_model=AiUsageOut)
async def get_ai_usage(user: CurrentUser, usage: Annotated[AiUsageGuard, Depends(get_ai_usage_guard)]) -> AiUsageOut:
    """Today's AI analysis allowance (UTC day). Enforcement happens on the server in the analyze endpoint."""
    snapshot = await usage.snapshot(user.id)
    return AiUsageOut(
        used=snapshot.used, limit=snapshot.limit, remaining=snapshot.remaining, resets_at=snapshot.resets_at
    )


# ---------- saved searches ----------


@router.get("/saved-searches", response_model=list[SavedSearchOut])
async def list_saved_searches(user: CurrentUser, db: DB) -> list[SavedSearchOut]:
    rows = (
        await db.execute(
            select(SavedSearch)
            .where(SavedSearch.user_id == user.id)
            .order_by(SavedSearch.created_at.desc())
            .limit(MAX_SAVED_SEARCHES_PER_USER)
        )
    ).scalars()
    return [saved_search_out(row) for row in rows]


@router.post("/saved-searches", status_code=201, response_model=SavedSearchOut, dependencies=[CSRFProtected])
async def create_saved_search(body: SavedSearchCreate, user: CurrentUser, db: DB) -> SavedSearchOut:
    count = await db.scalar(select(func.count()).select_from(SavedSearch).where(SavedSearch.user_id == user.id))
    if (count or 0) >= MAX_SAVED_SEARCHES_PER_USER:
        raise HTTPException(
            status_code=409,
            detail=f"You can keep up to {MAX_SAVED_SEARCHES_PER_USER} saved searches. Delete some to save more.",
        )
    row = SavedSearch(
        user_id=user.id,
        name=body.name or body.query[:120],
        query=body.query,
        filters=body.filters.model_dump(mode="json"),
    )
    db.add(row)
    await db.commit()
    return saved_search_out(row)


@router.get("/saved-searches/{search_id}", response_model=SavedSearchOut)
async def get_saved_search(search_id: uuid.UUID, user: CurrentUser, db: DB) -> SavedSearchOut:
    return saved_search_out(await get_owned_search(db, user.id, search_id))


@router.delete("/saved-searches/{search_id}", status_code=204, dependencies=[CSRFProtected])
async def delete_saved_search(search_id: uuid.UUID, user: CurrentUser, db: DB) -> Response:
    row = await get_owned_search(db, user.id, search_id)
    await db.delete(row)
    await db.commit()
    return Response(status_code=204)
