"""FastAPI application entry point. Run with: uvicorn app.main:app --reload --port 8010"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import httpx
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import Settings, get_settings
from app.db import create_engine, create_sessionmaker
from app.routers import account, analysis, auth, search
from app.services.auth import LoginThrottle
from app.services.gemini import GeminiReportGenerator
from app.services.pubmed import PubMedClient

# http(s)://localhost, 127.0.0.1 or [::1], on any port (or none). Anchored so
# look-alikes such as http://localhost.evil.example don't match.
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
        # PostgreSQL for accounts. Creating the engine doesn't connect, so the app
        # starts (and search works) even if the database is down.
        engine = create_engine(settings)
        app.state.db_sessionmaker = create_sessionmaker(engine)
        try:
            yield
        finally:
            await app.state.report_generator.aclose()
            await engine.dispose()


app = FastAPI(title="Healthcare Research Intelligence Agent", lifespan=lifespan)
# Lets the frontend (a different origin, e.g. localhost:3000) call this API from the browser.
app.add_middleware(CORSMiddleware, **cors_options(get_settings()))
# In-memory failed-login counter (see services/auth.py), shared by all requests.
app.state.login_throttle = LoginThrottle(
    get_settings().login_max_failures, get_settings().login_failure_window_seconds
)
app.include_router(search.router)
app.include_router(analysis.router)
app.include_router(auth.router)
app.include_router(account.router)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
