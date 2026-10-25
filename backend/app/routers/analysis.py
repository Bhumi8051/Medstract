"""HTTP endpoint for on-demand AI analysis of a single paper."""

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Request

from app.models import AnalyzeRequest, PaperAnalysis
from app.routers.deps import CurrentUser, get_ai_usage_guard
from app.routers.errors import analysis_http_error, pubmed_http_error
from app.routers.search import get_pubmed_client
from app.services.analysis import analyze_paper
from app.services.gemini import AnalysisError, ReportGenerator
from app.services.pubmed import PubMedClient, PubMedError
from app.services.usage import AiUsageGuard, UsageLimitError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["analysis"])


def get_report_generator(request: Request) -> ReportGenerator:
    """The shared Gemini generator created at startup (see main.py)."""
    return request.app.state.report_generator


@router.post("/papers/{pmid}/analyze", response_model=PaperAnalysis)
async def analyze(
    pmid: Annotated[str, Path(pattern=r"^[1-9]\d{0,9}$", description="PubMed ID, e.g. 30903363")],
    body: AnalyzeRequest,
    user: CurrentUser,
    pubmed: Annotated[PubMedClient, Depends(get_pubmed_client)],
    generator: Annotated[ReportGenerator, Depends(get_report_generator)],
    usage: Annotated[AiUsageGuard, Depends(get_ai_usage_guard)],
) -> PaperAnalysis:
    """Analyze one paper with Gemini, using only its PubMed metadata and abstract.

    Requires login. Each successful analysis uses one unit of the user's daily
    allowance (and of the overall daily allowance); failures are refunded.
    Runs only when called (never automatically) and is not cached.
    """
    try:
        reservation = await usage.reserve(user.id)
    except UsageLimitError as exc:
        raise HTTPException(
            status_code=429, detail=str(exc), headers={"Retry-After": str(exc.retry_after_seconds)}
        ) from None

    try:
        return await analyze_paper(pubmed, generator, pmid, body.summary_level)
    except BaseException as exc:
        # Nothing was delivered, so it shouldn't count against the user's allowance.
        try:
            await usage.refund(reservation)
        except Exception:  # noqa: BLE001 - never hide the original error
            logger.error("Could not refund AI usage reservation (%s)", type(exc).__name__)
        if isinstance(exc, PubMedError):
            raise pubmed_http_error(exc) from None
        if isinstance(exc, AnalysisError):
            raise analysis_http_error(exc) from None
        raise
