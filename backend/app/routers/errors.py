"""Map service errors to HTTP errors with user-safe messages (shared by all routers)."""

import logging

from fastapi import HTTPException

from app.services.analysis import PaperNotFoundError
from app.services.email import (
    EmailError,
    EmailNotConfiguredError,
    EmailRateLimitError,
    EmailRejectedError,
    EmailTimeoutError,
)
from app.services.gemini import (
    AnalysisError,
    AnalysisNotConfiguredError,
    AnalysisOutputError,
    AnalysisRateLimitError,
    AnalysisTimeoutError,
)
from app.services.pubmed import PubMedError, PubMedRateLimitError, PubMedTimeoutError

logger = logging.getLogger(__name__)


def pubmed_http_error(exc: PubMedError) -> HTTPException:
    if isinstance(exc, PubMedTimeoutError):
        return HTTPException(status_code=504, detail="PubMed timed out. Please try again.")
    if isinstance(exc, PubMedRateLimitError):
        return HTTPException(status_code=429, detail="PubMed rate limit reached. Wait a moment and retry.")
    # Details stay in the server log (which redacts secrets); users get a fixed message.
    logger.warning("PubMed error: %s", exc)
    return HTTPException(status_code=502, detail="PubMed returned an unexpected response. Please try again.")


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


def email_http_error(exc: EmailError) -> HTTPException:
    """EmailError messages are written by us; the provider's response text is never passed through."""
    if isinstance(exc, EmailNotConfiguredError):
        return HTTPException(status_code=503, detail=str(exc))
    if isinstance(exc, EmailRateLimitError):
        headers = {"Retry-After": str(exc.retry_after_seconds)} if exc.retry_after_seconds else None
        return HTTPException(status_code=429, detail=str(exc), headers=headers)
    if isinstance(exc, EmailTimeoutError):
        return HTTPException(status_code=504, detail=str(exc))
    if isinstance(exc, EmailRejectedError):
        return HTTPException(status_code=502, detail=str(exc))
    return HTTPException(status_code=502, detail=str(exc) or "The email could not be sent.")
