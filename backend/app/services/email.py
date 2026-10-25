"""Email sending through Resend (https://resend.com/docs/api-reference/emails/send-email).

The rest of the app depends only on the EmailSender protocol, so tests use a fake
and the provider can be swapped later. Every error message here is written to be
safe to show users: nothing from the provider's response is passed through, and
only the HTTP status and Resend's fixed error name are logged (never the API key,
the recipient address or the provider's free-text message).
"""

import logging
import time
from dataclasses import dataclass, field
from typing import Protocol

import httpx

from app.config import Settings

logger = logging.getLogger(__name__)


class EmailError(Exception):
    """Sending failed. `str(error)` is safe to show the user.

    For the scheduler (Step D):
      code            - short fixed identifier, safe to store and log
      retryable       - trying again later (same idempotency key) may succeed
      outcome_unknown - the request may have reached the provider, so the email
                        might have been sent even though we got no confirmation
    """

    default_code = "email_error"

    def __init__(
        self, message: str, *, code: str | None = None, retryable: bool = False, outcome_unknown: bool = False
    ) -> None:
        super().__init__(message)
        self.code = code or self.default_code
        self.retryable = retryable
        self.outcome_unknown = outcome_unknown


class EmailNotConfiguredError(EmailError):
    """Email is switched off, or the provider rejected or lacks the API key."""

    default_code = "email_not_configured"


class EmailRejectedError(EmailError):
    """The provider refused this message (e.g. test-mode recipient restriction, bad sender)."""

    default_code = "email_rejected"


class EmailRateLimitError(EmailError):
    default_code = "resend_429"

    def __init__(self, message: str, retry_after_seconds: int | None = None) -> None:
        super().__init__(message, retryable=True)  # refused before sending: definitely not sent
        self.retry_after_seconds = retry_after_seconds


class EmailTimeoutError(EmailError):
    default_code = "timeout"


class EmailUnavailableError(EmailError):
    default_code = "email_unavailable"


@dataclass(frozen=True)
class EmailMessage:
    to: str
    subject: str
    html: str
    text: str
    # Extra email headers, e.g. List-Unsubscribe for scheduled digests.
    headers: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class SentEmail:
    provider_message_id: str


class EmailSender(Protocol):
    async def send(self, message: EmailMessage, *, idempotency_key: str) -> SentEmail: ...


def mask_email(address: str | None) -> str:
    """"ada@example.org" -> "a***@example.org", for logs. Never log full addresses."""
    if not address or "@" not in address:
        return "-"
    name, domain = address.split("@", 1)
    return f"{name[:1]}***@{domain}"


class ResendEmailSender:
    def __init__(self, settings: Settings, http_client: httpx.AsyncClient) -> None:
        self._settings = settings
        self._http = http_client

    async def send(self, message: EmailMessage, *, idempotency_key: str) -> SentEmail:
        """Send one email, logging the attempt and its outcome.

        Logs contain the masked recipient, the idempotency key (as "ref", because the
        log redactor masks anything written as "key="), Resend's message id
        or error details and the duration. Never the API key, the full address, the
        subject (it names research topics) or the body. "Accepted" means Resend
        took the email for delivery; delivery itself is only visible in Resend
        (dashboard or webhooks), not here.
        """
        recipient = mask_email(message.to)
        started = time.monotonic()
        logger.info("Email send attempt: to=%s ref=%s", recipient, idempotency_key)
        try:
            sent = await self._send(message, idempotency_key=idempotency_key)
        except EmailError as exc:
            logger.warning(
                "Email send failed: to=%s ref=%s code=%s retryable=%s outcome_unknown=%s after %dms",
                recipient, idempotency_key, exc.code, exc.retryable, exc.outcome_unknown,
                (time.monotonic() - started) * 1000,
            )
            raise
        logger.info(
            "Email accepted by Resend (not a delivery confirmation): to=%s ref=%s id=%s after %dms",
            recipient, idempotency_key, sent.provider_message_id, (time.monotonic() - started) * 1000,
        )
        return sent

    async def _send(self, message: EmailMessage, *, idempotency_key: str) -> SentEmail:
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
                    **({"headers": message.headers} if message.headers else {}),
                },
                timeout=self._settings.email_timeout_seconds,
            )
        except httpx.ConnectTimeout:
            # No connection was made, so the request never reached Resend.
            logger.warning("Resend connect timeout")
            raise EmailUnavailableError(
                "Could not reach the email service. Please try again shortly.", code="connect_timeout", retryable=True
            ) from None
        except httpx.TimeoutException:
            # The request may have been received and processed: outcome unknown.
            logger.warning("Resend request timed out")
            raise EmailTimeoutError(
                "The email service took too long to respond. Please try again.", retryable=True, outcome_unknown=True
            ) from None
        except httpx.ConnectError as exc:
            logger.warning("Resend network error: %s", type(exc).__name__)
            raise EmailUnavailableError(
                "Could not reach the email service. Please try again shortly.", code="connect_error", retryable=True
            ) from None
        except httpx.HTTPError as exc:
            logger.warning("Resend network error: %s", type(exc).__name__)
            raise EmailUnavailableError(
                "Could not reach the email service. Please try again shortly.",
                code="network_error",
                retryable=True,
                outcome_unknown=True,
            ) from None

        if response.status_code == 200:
            message_id = _json_field(response, "id")
            if not message_id:
                logger.warning("Resend returned 200 without a message id")
                raise EmailUnavailableError(
                    "The email service returned an unexpected response.",
                    code="no_message_id",
                    retryable=True,
                    outcome_unknown=True,
                )
            return SentEmail(provider_message_id=message_id)
        raise self._map_error(response)

    def _map_error(self, response: httpx.Response) -> EmailError:
        status = response.status_code
        # Resend's `name` is a fixed identifier such as "validation_error"; its
        # `message` can contain the recipient address, so it is not logged.
        name = _json_field(response, "name")
        logger.warning("Resend error: status=%s name=%s", status, name or "-")

        if status == 401:
            return EmailNotConfiguredError(
                "The email service rejected the server's API key. Check RESEND_API_KEY in backend/.env.",
                code="resend_401",
            )
        if status == 403:
            return EmailRejectedError(
                "The email service refused to send this email. With the test sender (onboarding@resend.dev), "
                "Resend only delivers to the address you signed up to Resend with, so it must match your "
                "account email. Also check that the API key has sending access.",
                code="resend_403",
            )
        if status == 409 and name == "concurrent_idempotent_requests":
            # Another request with this key is still being processed: retry later.
            return EmailUnavailableError(
                "The email is already being sent. Please wait and try again.",
                code="idempotency_in_progress",
                retryable=True,
                outcome_unknown=True,
            )
        if status == 409:
            # invalid_idempotent_request: the key was already used with a DIFFERENT
            # payload, so something was probably sent before. Never retry blindly.
            return EmailRejectedError(
                "The email service reports this email was already sent with different content.",
                code="idempotency_conflict",
                outcome_unknown=True,
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
                "(it must be onboarding@resend.dev or an address on a domain verified in Resend).",
                code=f"resend_{status}",
            )
        if status >= 500:
            # The provider failed while handling the request: it may or may not have sent.
            return EmailUnavailableError(
                "The email service is temporarily unavailable. Please try again shortly.",
                code=f"resend_{status}",
                retryable=True,
                outcome_unknown=True,
            )
        return EmailUnavailableError("The email service could not send this email.", code=f"resend_{status}")


def _json_field(response: httpx.Response, field: str) -> str | None:
    try:
        body = response.json()
    except ValueError:
        return None
    value = body.get(field) if isinstance(body, dict) else None
    return value if isinstance(value, str) else None
