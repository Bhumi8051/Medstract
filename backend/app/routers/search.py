"""HTTP endpoint for searching PubMed."""

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from app.config import Settings, get_settings
from app.models import ArticleType, Language, Period, SearchResponse
from app.services.dates import combine_period_and_range, parse_date_bound
from app.services.pubmed import (
    PubMedClient,
    PubMedError,
    PubMedRateLimitError,
    PubMedTimeoutError,
)
from app.services.search_service import search_papers

router = APIRouter(prefix="/api", tags=["search"])


def get_pubmed_client(request: Request) -> PubMedClient:
    """The shared PubMedClient created at startup (see main.py)."""
    return request.app.state.pubmed_client


def get_today() -> date:
    """Today's date, as a dependency so tests can pin it."""
    return date.today()


@router.get("/search", response_model=SearchResponse)
async def search(
    client: Annotated[PubMedClient, Depends(get_pubmed_client)],
    settings: Annotated[Settings, Depends(get_settings)],
    today: Annotated[date, Depends(get_today)],
    q: Annotated[
        str, Query(min_length=2, max_length=500, description="Research question or keywords")
    ],
    max_results: Annotated[
        int | None,
        Query(description="How many papers to return (default 20, allowed 1-100)."),
    ] = None,
    start_date: Annotated[
        str | None,
        Query(description="Earliest publication date: YYYY, YYYY-MM or YYYY-MM-DD", examples=["2020"]),
    ] = None,
    end_date: Annotated[
        str | None,
        Query(description="Latest publication date: YYYY, YYYY-MM or YYYY-MM-DD", examples=["2024-06"]),
    ] = None,
    period: Annotated[
        Period,
        Query(
            description=(
                "Relative publication period ending today (PubMed Publication Date, [dp]). "
                "Combined with start_date/end_date when both are given."
            )
        ),
    ] = Period.ALL,
    article_type: Annotated[
        list[ArticleType] | None,
        Query(description="PubMed publication type; repeat for several (matched with OR)."),
    ] = None,
    language: Annotated[
        list[Language] | None,
        Query(description="Article language; repeat for several (matched with OR)."),
    ] = None,
    include_undated: Annotated[
        bool, Query(description="Keep papers with no usable date when a date filter is set.")
    ] = False,
) -> SearchResponse:
    query = q.strip()
    if len(query) < 2:
        raise HTTPException(status_code=422, detail="Query must contain at least 2 characters.")

    limit = settings.search_default_results if max_results is None else max_results
    if not settings.search_min_results <= limit <= settings.search_max_results:
        raise HTTPException(
            status_code=422,
            detail=(
                f"max_results must be between {settings.search_min_results} "
                f"and {settings.search_max_results}."
            ),
        )

    try:
        start = parse_date_bound(start_date, is_end=False) if start_date else None
        end = parse_date_bound(end_date, is_end=True) if end_date else None
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    if start and end and start > end:
        raise HTTPException(status_code=422, detail="start_date must be on or before end_date.")
    try:
        start, end = combine_period_and_range(period, start, end, today=today)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    try:
        return await search_papers(
            client,
            settings,
            query,
            max_results=limit,
            start_date=start,
            end_date=end,
            include_undated=include_undated,
            period=period,
            article_types=article_type,
            languages=language,
        )
    except PubMedTimeoutError:
        raise HTTPException(status_code=504, detail="PubMed timed out. Please try again.")
    except PubMedRateLimitError:
        raise HTTPException(
            status_code=429, detail="PubMed rate limit reached. Wait a moment and retry."
        )
    except PubMedError as exc:
        raise HTTPException(status_code=502, detail=f"PubMed error: {exc}")
