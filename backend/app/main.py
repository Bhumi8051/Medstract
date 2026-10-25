"""FastAPI application entry point. Run with: uvicorn app.main:app --reload --port 8010"""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import httpx
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import Settings, get_settings
from app.db import create_engine, create_sessionmaker
from app.logging_setup import install_log_redaction
from app.scheduler import DigestScheduler
from app.routers import account, analysis, auth, digests, search, subscriptions, unsubscribe
from app.services.auth import LoginThrottle, SlidingWindowLimiter
from app.services.delivery import DeliveryEngine
from app.services.email import ResendEmailSender
from app.services.gemini import GeminiReportGenerator
from app.services.pubmed import PubMedClient

# http(s)://localhost, 127.0.0.1 or [::1], on any port (or none). Anchored so
# look-alikes such as http://localhost.evil.example don't match.
logger = logging.getLogger(__name__)

LOCAL_ORIGIN_REGEX = r"^https?://(localhost|127\.0\.0\.1|\[::1\])(:\d+)?$"


def cors_options(settings: Settings) -> dict[str, Any]:
    """CORSMiddleware arguments: local dev origins (if enabled) plus any exact origins."""
    return {
        "allow_origins": settings.cors_origins,
        "allow_origin_regex": LOCAL_ORIGIN_REGEX if settings.cors_allow_local_origins else None,
        "allow_methods": ["GET", "POST", "PUT", "DELETE"],
        "allow_headers": ["Accept", "Content-Type", "X-Requested-With"],
        # Lets the browser send the HttpOnly session cookie. Safe only because the
        # origins above are an explicit allowlist (never "*").
        "allow_credentials": True,
        # Let the frontend read how long to wait after a 429 (browsers hide other headers cross-origin).
        "expose_headers": ["Retry-After"],
    }


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    # One shared HTTP client and PubMedClient for the whole app, so connections
    # are reused and the rate limiter covers every request.
    settings = get_settings()
    async with httpx.AsyncClient() as http_client:
        app.state.pubmed_client = PubMedClient(settings, http_client)
        # Created even without GEMINI_API_KEY: search still works, and analysis
        # requests get a clear "not configured" error instead of a crash.
        app.state.report_generator = GeminiReportGenerator(settings)
        # Created even without RESEND_API_KEY; test sends then get a clear error.
        app.state.email_sender = ResendEmailSender(settings, http_client)
        # PostgreSQL for accounts. Creating the engine doesn't connect, so the app
        # starts (and search works) even if the database is down.
        engine = create_engine(settings)
        app.state.db_sessionmaker = create_sessionmaker(engine)
        # Scheduled digests (Step D): only when explicitly switched on. Even then,
        # DIGEST_DELIVERY_MODE (default "off") decides whether ticks do anything.
        scheduler = None
        if settings.digest_scheduler_enabled:
            delivery = DeliveryEngine(
                app.state.db_sessionmaker,
                settings,
                app.state.pubmed_client,
                app.state.report_generator,
                app.state.email_sender,
            )
            scheduler = DigestScheduler(engine, delivery, settings.digest_tick_seconds)
            scheduler.start()
            logger.warning(
                "Digest scheduler started (mode=%s, every %ss)", settings.digest_delivery_mode, settings.digest_tick_seconds
            )
        app.state.digest_scheduler = scheduler
        try:
            yield
        finally:
            if scheduler is not None:
                await scheduler.stop()
            await app.state.report_generator.aclose()
            await engine.dispose()


# Before anything logs: keep API keys and DB passwords out of every log line.
install_log_redaction(get_settings())

# Show the app's own INFO logs (email send attempts and acceptances, digest ticks) in the
# backend terminal. Uvicorn only configures its own loggers, so these were otherwise
# dropped. Redaction above applies to every line.
_app_log = logging.getLogger("app")
if not _app_log.handlers:
    _handler = logging.StreamHandler()
    _handler.setFormatter(logging.Formatter("%(levelname)s:     %(name)s: %(message)s"))
    _app_log.addHandler(_handler)
    _app_log.setLevel(logging.INFO)

app = FastAPI(title="Healthcare Research Intelligence Agent", lifespan=lifespan)
# Lets the frontend (a different origin, e.g. localhost:3000) call this API from the browser.
app.add_middleware(CORSMiddleware, **cors_options(get_settings()))
# In-memory rate limiters (services/auth.py). Shared by all requests in THIS process only:
# not shared across multiple workers/servers, and reset on restart (see config.py).
_settings = get_settings()
app.state.login_throttle = LoginThrottle(_settings.login_max_failures, _settings.login_failure_window_seconds)
app.state.login_ip_limiter = SlidingWindowLimiter(_settings.login_ip_max_failures, _settings.login_ip_window_seconds)
app.state.register_ip_limiter = SlidingWindowLimiter(
    _settings.register_ip_max_attempts, _settings.register_ip_window_seconds
)
app.state.ai_burst_limiter = SlidingWindowLimiter(_settings.ai_burst_per_minute, 60)
app.state.email_test_limiter = SlidingWindowLimiter(_settings.email_test_sends_per_hour, 3600)
app.state.unsubscribe_ip_limiter = SlidingWindowLimiter(
    _settings.unsubscribe_ip_max_invalid, _settings.unsubscribe_ip_window_seconds
)
app.include_router(search.router)
app.include_router(analysis.router)
app.include_router(auth.router)
app.include_router(account.router)
app.include_router(subscriptions.router)
app.include_router(digests.router)
app.include_router(unsubscribe.router)


@app.get("/health")
async def health() -> dict:
    """Liveness plus the digest scheduler's state. "status" is always "ok" while the API
    is up (dev.sh relies on that); check digest_scheduler.stale / last_error for problems."""
    settings = get_settings()
    scheduler: DigestScheduler | None = getattr(app.state, "digest_scheduler", None)
    digest = {
        "enabled": settings.digest_scheduler_enabled,
        "mode": settings.digest_delivery_mode,
        "running": False,
        "stale": False,
    }
    if scheduler is not None:
        digest.update(scheduler.health())
    return {"status": "ok", "digest_scheduler": digest}
