"""Keep secrets out of server logs.

1. HTTP-client loggers (httpx, httpcore, Google's SDK) are held at WARNING, so
   request URLs are never logged. NCBI requires its API key as a URL query
   parameter, and httpx logs full URLs at INFO.
2. Every log record is passed through a redactor that masks `api_key=...`-style
   query values, passwords in database URLs, and the literal values of the
   configured secrets (NCBI, Gemini and Resend keys, database password), and
   "Bearer <token>" values, including in exception tracebacks.
"""

import logging
import re
import traceback

from sqlalchemy.engine import make_url

from app.config import Settings

REDACTED = "[REDACTED]"
QUIET_LOGGERS = ("httpx", "httpcore", "google_genai", "google.genai", "urllib3")

# key=value pairs in URLs / messages whose value must never be logged.
_SECRET_PARAM_RE = re.compile(
    r"(?i)\b(api[_-]?key|key|access[_-]?token|token|password|passwd|secret)=([^&\s\"'<>]+)"
)
# "Authorization: Bearer <token>" (e.g. the Resend API key), should a header ever be logged.
_BEARER_RE = re.compile(r"(?i)\b(bearer\s+)([A-Za-z0-9._~+/=-]+)")
# scheme://user:password@host
_URL_PASSWORD_RE = re.compile(r"(?i)(\b[a-z][a-z0-9+.-]*://[^/\s:@]+:)([^@\s/]+)(@)")
# Literal secret values shorter than this are not redacted (too likely to match ordinary text).
_MIN_SECRET_LENGTH = 6

_installed_secrets: list[str] = []


def _secret_values(settings: Settings) -> list[str]:
    values = [settings.ncbi_api_key or "", settings.gemini_key_value or "", settings.resend_key_value or ""]
    try:
        values.append(make_url(settings.database_url.get_secret_value()).password or "")
    except Exception:  # noqa: BLE001 - an unparsable URL simply has no password to hide
        pass
    return sorted({v for v in values if len(v) >= _MIN_SECRET_LENGTH}, key=len, reverse=True)


def redact(text: str, secrets: list[str] | None = None) -> str:
    """Mask secret query values, URL passwords and known secret values in `text`."""
    for value in _installed_secrets if secrets is None else secrets:
        text = text.replace(value, REDACTED)
    text = _SECRET_PARAM_RE.sub(lambda m: f"{m.group(1)}={REDACTED}", text)
    text = _BEARER_RE.sub(lambda m: f"{m.group(1)}{REDACTED}", text)
    return _URL_PASSWORD_RE.sub(lambda m: f"{m.group(1)}{REDACTED}{m.group(3)}", text)


def install_log_redaction(settings: Settings) -> None:
    """Install once at startup (idempotent; later calls just refresh the secret list)."""
    _installed_secrets[:] = _secret_values(settings)
    for name in QUIET_LOGGERS:
        logger = logging.getLogger(name)
        if logger.level == logging.NOTSET or logger.level < logging.WARNING:
            logger.setLevel(logging.WARNING)

    current = logging.getLogRecordFactory()
    if getattr(current, "_redacting", False):
        return

    def factory(*args, **kwargs) -> logging.LogRecord:
        record = current(*args, **kwargs)
        try:
            message = record.getMessage()
        except Exception:  # noqa: BLE001 - malformed format args: leave the record alone
            return record
        record.msg = redact(message)
        record.args = None
        if record.exc_info and record.exc_info[0] is not None:
            # Pre-render the traceback so formatters print the redacted version.
            record.exc_text = redact("".join(traceback.format_exception(*record.exc_info)).rstrip())
        return record

    factory._redacting = True  # type: ignore[attr-defined]
    logging.setLogRecordFactory(factory)
