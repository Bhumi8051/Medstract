"""Application settings, loaded from environment variables and backend/.env."""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# backend/ folder, so .env is found no matter which directory you run from.
BACKEND_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=BACKEND_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # NCBI E-utilities (PubMed)
    ncbi_api_key: str | None = None
    ncbi_email: str | None = None
    ncbi_tool: str = "healthcare-research-agent"
    ncbi_base_url: str = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
    ncbi_timeout_seconds: float = Field(default=15.0, gt=0)
    # Retries after a timeout, HTTP 429, or HTTP 5xx (0 = no retries).
    ncbi_max_retries: int = Field(default=2, ge=0, le=5)
    ncbi_retry_backoff_seconds: float = Field(default=1.0, ge=0)
    # None = NCBI's published limit: 10/s with an API key, 3/s without.
    ncbi_requests_per_second: float | None = Field(default=None, gt=0)

    # Search result limits (the max_results query parameter)
    search_default_results: int = Field(default=20, ge=1)
    search_min_results: int = Field(default=1, ge=1)
    search_max_results: int = Field(default=100, ge=1)
    # Fetch more candidates than requested so re-ranking, dedup and date
    # filtering still leave enough papers. Capped to keep EFetch requests small.
    search_candidate_multiplier: int = Field(default=3, ge=1, le=10)
    search_max_candidates: int = Field(default=200, ge=1, le=500)

    # Relevance ranking: a title match counts this much more than an abstract match.
    ranking_title_weight: float = Field(default=3.0, ge=0)
    ranking_abstract_weight: float = Field(default=1.0, ge=0)

    # Google Gemini (AI paper analysis). Leave the key unset to disable analysis;
    # search keeps working. SecretStr keeps the key out of logs and reprs.
    gemini_api_key: SecretStr | None = None
    # Stable, free-tier model recommended by Google for cost-effective use
    # (checked against ai.google.dev/gemini-api/docs/models, October 2026).
    gemini_model: str = "gemini-3.5-flash-lite"
    gemini_timeout_seconds: float = Field(default=60.0, gt=0, le=300)
    gemini_max_output_tokens: int = Field(default=8192, ge=1024, le=65536)

    # Browser origins allowed to call this API.
    # Development: any http://localhost:<port> / 127.0.0.1:<port> is allowed, so the
    # frontend works even if Next.js picks another port. Turn this off in production.
    cors_allow_local_origins: bool = True
    # Exact extra origins, e.g. a deployed frontend. In .env, write it as JSON:
    # CORS_ORIGINS=["https://research.example.org"]
    cors_origins: list[str] = []

    # PostgreSQL (accounts, preferences, saved searches). SecretStr because a
    # production URL usually contains a password. Format:
    # postgresql+asyncpg://USER:PASSWORD@HOST:5432/DBNAME
    database_url: SecretStr = SecretStr("postgresql+asyncpg://localhost/healthcare_research")

    # Login sessions (HttpOnly cookie holding a random token; only its hash is stored).
    session_cookie_name: str = "hria_session"
    session_ttl_days: int = Field(default=14, ge=1, le=90)
    # Must be true in production (HTTPS). False locally because http://localhost has no TLS.
    session_cookie_secure: bool = False
    session_cookie_samesite: Literal["lax", "strict", "none"] = "lax"

    # Slow down password guessing: failed logins allowed per email per window.
    login_max_failures: int = Field(default=5, ge=1, le=100)
    login_failure_window_seconds: int = Field(default=900, ge=10)

    # Extra per-IP limits (Step B). These counters live in memory: fine for this
    # single-process development setup, but NOT shared between multiple workers or
    # servers, and reset on restart. Use a shared store (e.g. Redis/PostgreSQL) if
    # the backend is ever run with several workers.
    login_ip_max_failures: int = Field(default=20, ge=1, le=1000)
    login_ip_window_seconds: int = Field(default=900, ge=10)
    register_ip_max_attempts: int = Field(default=5, ge=1, le=1000)
    register_ip_window_seconds: int = Field(default=3600, ge=10)
    # Only read X-Forwarded-For when the app sits behind a proxy you control;
    # otherwise any client could spoof its IP and dodge the limits above.
    trust_proxy_headers: bool = False

    # Gemini usage caps, enforced atomically in PostgreSQL (ai_usage_daily tables).
    # Days are UTC. Only successful analyses count; failures are refunded.
    ai_daily_limit_per_user: int = Field(default=20, ge=1, le=10_000)
    # All users together; protects the project's free-tier quota. 0 = no overall cap.
    ai_daily_limit_total: int = Field(default=200, ge=0, le=1_000_000)
    # Short-term brake against rapid clicking (in memory, per user).
    ai_burst_per_minute: int = Field(default=5, ge=1, le=600)

    # Email (Step C: manual test digests only; nothing is sent automatically).
    # Resend API key; SecretStr keeps it out of logs and reprs.
    resend_api_key: SecretStr | None = None
    resend_api_url: str = "https://api.resend.com"
    # Master switch: no email is ever sent unless this is true.
    email_enabled: bool = False
    # onboarding@resend.dev is Resend's test sender: it only delivers to the address
    # that owns the Resend account. Sending to anyone else needs a verified domain.
    email_from: str = "Healthcare Research Agent <onboarding@resend.dev>"
    # Comma-separated addresses allowed to receive test digests. Accounts aren't
    # email-verified, so the account email alone isn't proof of ownership.
    email_test_recipients: str = ""
    # Test sends per user per hour (in memory, like the login limits above).
    email_test_sends_per_hour: int = Field(default=5, ge=1, le=100)
    email_timeout_seconds: float = Field(default=15.0, gt=0, le=60)

    @model_validator(mode="after")
    def _samesite_none_requires_secure(self) -> "Settings":
        if self.session_cookie_samesite == "none" and not self.session_cookie_secure:
            raise ValueError("SESSION_COOKIE_SAMESITE=none requires SESSION_COOKIE_SECURE=true")
        return self

    @property
    def gemini_key_value(self) -> str | None:
        """The Gemini key, or None if unset or blank. Only pass this to the SDK."""
        if self.gemini_api_key is None:
            return None
        return self.gemini_api_key.get_secret_value().strip() or None

    @property
    def resend_key_value(self) -> str | None:
        """The Resend key, or None if unset or blank. Only pass this to the email service."""
        if self.resend_api_key is None:
            return None
        return self.resend_api_key.get_secret_value().strip() or None

    @property
    def email_test_recipient_set(self) -> frozenset[str]:
        """EMAIL_TEST_RECIPIENTS as lowercased addresses."""
        return frozenset(a.strip().lower() for a in self.email_test_recipients.split(",") if a.strip())

    @property
    def effective_requests_per_second(self) -> float:
        if self.ncbi_requests_per_second is not None:
            return self.ncbi_requests_per_second
        return 10.0 if self.ncbi_api_key else 3.0


@lru_cache
def get_settings() -> Settings:
    """Return one shared Settings instance (read from the environment once)."""
    return Settings()
