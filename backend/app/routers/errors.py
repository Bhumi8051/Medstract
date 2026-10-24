"""Map service errors to HTTP errors with user-safe messages (shared by all routers)."""

from fastapi import HTTPException

from app.services.analysis import PaperNotFoundError
from app.services.gemini import (
    AnalysisError,
    AnalysisNotConfiguredError,
    AnalysisOutputError,
    AnalysisRateLimitError,
    AnalysisTimeoutError,
)
from app.services.pubmed import PubMedError, PubMedRateLimitError, PubMedTimeoutError


def pubmed_http_error(exc: PubMedError) -> HTTPException:
    if isinstance(exc, PubMedTimeoutError):
        return HTTPException(status_code=504, detail="PubMed timed out. Please try again.")
    if isinstance(exc, PubMedRateLimitError):
        return HTTPException(status_code=429, detail="PubMed rate limit reached. Wait a moment and retry.")
    return HTTPException(status_code=502, detail=f"PubMed error: {exc}")


def analysis_http_error(exc: AnalysisError) -> HTTPException:
    """AnalysisError messages are written to be safe to show; nothing from the provider is passed through."""
    if isinstance(exc, PaperNotFoundError):
        return HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, AnalysisNotConfiguredError):
        return HTTPException(status_code=503, detail=str(exc))
    if isinstance(exc, AnalysisRateLimitError):
        headers = {"Retry-After": str(exc.retry_after_seconds)} if exc.retry_after_seconds else None
        return HTTPException(status_code=429, detail=str(exc), headers=headers)
    if isinstance(exc, AnalysisTimeoutError):
        return HTTPException(status_code=504, detail=str(exc))
    if isinstance(exc, AnalysisOutputError):
        return HTTPException(status_code=502, detail=str(exc))
    return HTTPException(status_code=502, detail=str(exc) or "The AI service could not complete the analysis.")
