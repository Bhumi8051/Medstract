"""Google Gemini adapter: the only module that talks to the google-genai SDK.

It sends one structured-output request and turns every SDK/network failure
into one of the AnalysisError types below, whose messages are safe to show
users (no keys, no provider internals).
"""

import asyncio
import logging
from typing import Any, Protocol

import httpx
from google import genai
from google.genai import errors as genai_errors
from google.genai import types

from app.config import Settings

logger = logging.getLogger(__name__)


class AnalysisError(Exception):
    """Base class. `str(error)` is a user-safe message."""


class AnalysisNotConfiguredError(AnalysisError):
    """No (valid) Gemini API key is configured."""


class AnalysisRateLimitError(AnalysisError):
    """Gemini quota or rate limit reached."""

    def __init__(self, message: str, retry_after_seconds: int | None = None) -> None:
        super().__init__(message)
        self.retry_after_seconds = retry_after_seconds


class AnalysisTimeoutError(AnalysisError):
    """Gemini did not answer in time."""


class AnalysisUnavailableError(AnalysisError):
    """Gemini could not be reached, the model is unavailable, or it returned a server error."""


class AnalysisOutputError(AnalysisError):
    """Gemini answered, but the output was blocked, truncated or not valid."""


class ReportGenerator(Protocol):
    """Anything that turns a prompt into JSON text. Tests use a fake implementation."""

    model: str

    async def generate(self, *, system_instruction: str, prompt: str, response_schema: dict[str, Any]) -> str: ...


# Finish reasons that mean the text is unusable.
_BLOCKED_REASONS = {"SAFETY", "RECITATION", "BLOCKLIST", "PROHIBITED_CONTENT", "SPII", "LANGUAGE", "OTHER"}


class GeminiReportGenerator:
    def __init__(self, settings: Settings, client: Any | None = None) -> None:
        self.model = settings.gemini_model
        self._settings = settings
        self._client = client  # injected in tests; otherwise created on first use

    def _get_client(self) -> Any:
        if self._client is None:
            api_key = self._settings.gemini_key_value
            if not api_key:
                raise AnalysisNotConfiguredError(
                    "AI analysis is not configured on the server: GEMINI_API_KEY is missing. "
                    "Add it to backend/.env and restart the backend."
                )
            self._client = genai.Client(
                api_key=api_key,
                http_options=types.HttpOptions(
                    timeout=int(self._settings.gemini_timeout_seconds * 1000),  # milliseconds
                    # No automatic retries: on the free tier they would only burn quota.
                    retry_options=types.HttpRetryOptions(attempts=1),
                ),
            )
        return self._client

    async def aclose(self) -> None:
        if self._client is not None and hasattr(self._client, "aio"):
            try:
                await self._client.aio.aclose()
            except Exception:  # shutting down; nothing useful to do
                pass

    async def generate(self, *, system_instruction: str, prompt: str, response_schema: dict[str, Any]) -> str:
        client = self._get_client()
        config = types.GenerateContentConfig(
            system_instruction=system_instruction,
            response_mime_type="application/json",
            response_json_schema=response_schema,
            temperature=0.2,  # low: we want faithful summaries, not creativity
            max_output_tokens=self._settings.gemini_max_output_tokens,
        )
        try:
            # Backstop in case the SDK's own timeout doesn't fire.
            response = await asyncio.wait_for(
                client.aio.models.generate_content(model=self.model, contents=prompt, config=config),
                timeout=self._settings.gemini_timeout_seconds + 5,
            )
        except genai_errors.APIError as exc:
            raise self._map_api_error(exc) from None
        except (asyncio.TimeoutError, httpx.TimeoutException):
            logger.warning("Gemini request timed out (model=%s)", self.model)
            raise AnalysisTimeoutError("The AI model took too long to respond. Please try again.") from None
        except httpx.HTTPError as exc:
            logger.warning("Gemini network error: %s", type(exc).__name__)
            raise AnalysisUnavailableError("Could not reach the AI service. Please try again shortly.") from None

        return self._extract_text(response)

    def _map_api_error(self, exc: genai_errors.APIError) -> AnalysisError:
        code = getattr(exc, "code", None)
        status = str(getattr(exc, "status", "") or "")
        # Log only the type and codes: provider messages are not shown to users.
        logger.warning("Gemini API error: %s code=%s status=%s", type(exc).__name__, code, status)

        if code == 429 or status == "RESOURCE_EXHAUSTED":
            return AnalysisRateLimitError(
                "The AI service's rate limit or free-tier quota was reached. Wait a minute and try again.",
                retry_after_seconds=60,
            )
        message = str(getattr(exc, "message", "") or "").lower()
        if code in (401, 403) or "api key" in message or "api_key" in message:
            return AnalysisNotConfiguredError(
                "The AI service rejected the server's API key. Check GEMINI_API_KEY in backend/.env."
            )
        if code == 404:
            return AnalysisUnavailableError(
                f"The configured AI model '{self.model}' is not available. Check GEMINI_MODEL in backend/.env."
            )
        if code == 504 or status == "DEADLINE_EXCEEDED":
            return AnalysisTimeoutError("The AI model took too long to respond. Please try again.")
        if isinstance(exc, genai_errors.ServerError) or (code is not None and code >= 500):
            return AnalysisUnavailableError("The AI service is temporarily unavailable. Please try again shortly.")
        return AnalysisUnavailableError("The AI service could not process this request.")

    def _extract_text(self, response: Any) -> str:
        feedback = getattr(response, "prompt_feedback", None)
        if feedback is not None and getattr(feedback, "block_reason", None):
            raise AnalysisOutputError("The AI service declined to analyze this paper.")

        candidates = getattr(response, "candidates", None) or []
        reason = getattr(getattr(candidates[0], "finish_reason", None), "name", None) if candidates else None
        if reason == "MAX_TOKENS":
            raise AnalysisOutputError("The AI response was cut off before it was complete. Please try again.")
        if reason in _BLOCKED_REASONS:
            raise AnalysisOutputError("The AI service declined to analyze this paper.")

        text = getattr(response, "text", None)
        if not text or not text.strip():
            raise AnalysisOutputError("The AI service returned an empty response. Please try again.")
        return text
