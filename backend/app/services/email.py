"""Email sending through Resend (https://resend.com/docs/api-reference/emails/send-email).

The rest of the app depends only on the EmailSender protocol, so tests use a fake
and the provider can be swapped later. Every error message here is written to be
safe to show users: nothing from the provider's response is passed through, and
only the HTTP status and Resend's fixed error name are logged (never the API key,
the recipient address or the provider's free-text message).
"""

import logging
from dataclasses import dataclass
from typing import Protocol

import httpx

from app.config import Settings

logger = logging.getLogger(__name__)


class EmailError(Exception):
    """Sending failed. `str(error)` is safe to show the user."""


class EmailNotConfiguredError(EmailError):
    """Email is switched off, or the provider rejected or lacks the API key."""


class EmailRejectedError(EmailError):
    """The provider refused this message (e.g. test-mode recipient restriction, bad sender)."""


class EmailRateLimitError(EmailError):
    def __init__(self, message: str, retry_after_seconds: int | None = None) -> None:
        super().__init__(message)
        self.retry_after_seconds = retry_after_seconds


class EmailTimeoutError(EmailError):
    pass


class EmailUnavailableError(EmailError):
    pass


@dataclass(frozen=True)
class EmailMessage:
    to: str
    subject: str
    html: str
    text: str


@dataclass(frozen=True)
class SentEmail:
    provider_message_id: str


class EmailSender(Protocol):
    async def send(self, message: EmailMessage, *, idempotency_key: str) -> SentEmail: ...


class ResendEmailSender:
    def __init__(self, settings: Settings, http_client: httpx.AsyncClient) -> None:
        self._settings = settings
        self._http = http_client

    async def send(self, message: EmailMessage, *, idempotency_key: str) -> SentEmail:
        api_key = self._settings.resend_key_value
        if not api_key:
            raise EmailNotConfiguredError(
                "Email is not configured on the server: RESEND_API_KEY is missing. "
                "Add it to backend/.env and restart the backend."
            )
        try:
            response = await self._http.post(
                f"{self._settings.resend_api_url.rstrip('/')}/emails",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    # Resend sends at most one email per key (kept for 24 hours), so a
                    # retried request can't deliver the same digest twice.
                    "Idempotency-Key": idempotency_key,
                },
                json={
                    "from": self._settings.email_from,
                    "to": [message.to],
                    "subject": message.subject,
                    "html": message.html,
                    "text": message.text,
                },
                timeout=self._settings.email_timeout_seconds,
            )
        except httpx.TimeoutException:
            logger.warning("Resend request timed out")
            raise EmailTimeoutError("The email service took too long to respond. Please try again.") from None
        except httpx.HTTPError as exc:
            logger.warning("Resend network error: %s", type(exc).__name__)
            raise EmailUnavailableError("Could not reach the email service. Please try again shortly.") from None

        if response.status_code == 200:
            message_id = _json_field(response, "id")
            if not message_id:
                logger.warning("Resend returned 200 without a message id")
                raise EmailUnavailableError("The email service returned an unexpected response.")
            return SentEmail(provider_message_id=message_id)
        raise self._map_error(response)

    def _map_error(self, response: httpx.Response) -> EmailError:
        status = response.status_code
        # Resend's `name` is a fixed identifier such as "validation_error"; its
        # `message` can contain the recipient address, so it is not logged.
        logger.warning("Resend error: status=%s name=%s", status, _json_field(response, "name") or "-")

        if status == 401:
            return EmailNotConfiguredError(
                "The email service rejected the server's API key. Check RESEND_API_KEY in backend/.env."
            )
        if status == 403:
            return EmailRejectedError(
                "The email service refused to send this email. With the test sender (onboarding@resend.dev), "
                "Resend only delivers to the address you signed up to Resend with, so it must match your "
                "account email. Also check that the API key has sending access."
            )
        if status == 429:
            retry_after = response.headers.get("retry-after", "")
            return EmailRateLimitError(
                "The email service's rate limit or daily quota was reached. Please try again later.",
                retry_after_seconds=int(retry_after) if retry_after.isdigit() else None,
            )
        if status in (400, 422):
            return EmailRejectedError(
                "The email service rejected the message. Check EMAIL_FROM in backend/.env "
                "(it must be onboarding@resend.dev or an address on a domain verified in Resend)."
            )
        if status >= 500:
            return EmailUnavailableError("The email service is temporarily unavailable. Please try again shortly.")
        return EmailUnavailableError("The email service could not send this email.")


def _json_field(response: httpx.Response, field: str) -> str | None:
    try:
        body = response.json()
    except ValueError:
        return None
    value = body.get(field) if isinstance(body, dict) else None
    return value if isinstance(value, str) else None
