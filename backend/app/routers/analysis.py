"""HTTP endpoint for on-demand AI analysis of a single paper."""

from typing import Annotated

from fastapi import APIRouter, Depends, Path, Request

from app.models import AnalyzeRequest, PaperAnalysis
from app.routers.errors import analysis_http_error, pubmed_http_error
from app.routers.search import get_pubmed_client
from app.services.analysis import analyze_paper
from app.services.gemini import AnalysisError, ReportGenerator
from app.services.pubmed import PubMedClient, PubMedError

router = APIRouter(prefix="/api", tags=["analysis"])


def get_report_generator(request: Request) -> ReportGenerator:
    """The shared Gemini generator created at startup (see main.py)."""
    return request.app.state.report_generator


@router.post("/papers/{pmid}/analyze", response_model=PaperAnalysis)
async def analyze(
    pmid: Annotated[str, Path(pattern=r"^[1-9]\d{0,9}$", description="PubMed ID, e.g. 30903363")],
    body: AnalyzeRequest,
    pubmed: Annotated[PubMedClient, Depends(get_pubmed_client)],
    generator: Annotated[ReportGenerator, Depends(get_report_generator)],
) -> PaperAnalysis:
    """Analyze one paper with Gemini, using only its PubMed metadata and abstract.

    Runs only when called (never automatically for search results) and is not cached.
    """
    try:
        return await analyze_paper(pubmed, generator, pmid, body.summary_level)
    except PubMedError as exc:
        raise pubmed_http_error(exc) from None
    except AnalysisError as exc:
        raise analysis_http_error(exc) from None
