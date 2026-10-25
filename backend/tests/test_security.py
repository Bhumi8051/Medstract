"""Step B security: login for AI, daily Gemini limits, login/registration rate limits, secrets out of logs.

Runs against the real PostgreSQL test database (usage limits are enforced there).
PubMed and Gemini are mocked; no network, no API keys.
"""

import asyncio
import json
import logging
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from app.config import get_settings
from app.db import create_sessionmaker
from app.logging_setup import REDACTED, install_log_redaction, redact
from app.main import app
from app.routers.analysis import get_report_generator
from app.routers.deps import get_utc_now
from app.routers.search import get_pubmed_client
from app.services.auth import SlidingWindowLimiter
from app.services.gemini import AnalysisUnavailableError
from app.services.pubmed import PubMedClient
from app.services.usage import AiUsageGuard, UsageLimitError
from tests.conftest import (
    TEST_DATABASE_URL,
    article_xml,
    efetch_xml,
    esearch_json,
    make_client,
    make_settings,
    pubmed_handler,
    run_db,
)

PASSWORD = "correct horse battery"
PMID = "30903363"
NOW = datetime(2026, 10, 24, 22, 0, tzinfo=UTC)  # 2 hours before the UTC reset
REPORT = {
    "plain_language_overview": "Overview.",
    "research_question": [{"text": "Question?", "basis": "reported"}],
    "background": [{"text": "Background.", "basis": "interpretation"}],
    "methods": [{"text": "Review.", "basis": "reported"}],
    "key_findings": [{"text": "Finding.", "basis": "reported"}],
    "interpretation": [{"text": "Meaning.", "basis": "interpretation"}],
    "limitations": [{"text": "Abstract only.", "basis": "interpretation"}],
    "not_established": [{"text": "Causation.", "basis": "interpretation"}],
    "further_questions": ["Next?"],
}


class CountingGenerator:
    model = "fake-gemini"

    def __init__(self, error: Exception | None = None) -> None:
        self.calls = 0
        self.error = error

    async def generate(self, **_):
        self.calls += 1
        if self.error:
            raise self.error
        return json.dumps(REPORT)


@pytest.fixture
def ai(db_client):
    """db_client + mocked PubMed/Gemini + a pinned clock. Yields a small helper namespace."""
    clock = {"now": NOW}
    generator = CountingGenerator()
    xml = efetch_xml(article_xml(PMID, "Metformin and cancer", abstract="Abstract text."))
    app.dependency_overrides[get_pubmed_client] = lambda: make_client(pubmed_handler(esearch_json([PMID]), xml))
    app.dependency_overrides[get_report_generator] = lambda: generator
    app.dependency_overrides[get_utc_now] = lambda: clock["now"]

    class Helper:
        client = db_client
        gen = generator
        time = clock

        @staticmethod
        def analyze(client: TestClient | None = None, pmid: str = PMID):
            return (client or db_client).post(f"/api/papers/{pmid}/analyze", json={"summary_level": "college"})

        @staticmethod
        def used(email: str = "ada@example.org") -> int:
            rows = run_db(
                "SELECT coalesce(sum(u.used), 0) FROM ai_usage_daily u JOIN users ON users.id = u.user_id "
                "WHERE users.email = :email",
                {"email": email},
            )
            return int(rows[0][0])

    yield Helper
    app.dependency_overrides.clear()


def sign_up(client: TestClient, email: str = "ada@example.org"):
    response = client.post("/api/auth/register", json={"email": email, "password": PASSWORD})
    assert response.status_code == 201, response.text
    return response


def browser(ip: str = "testclient") -> TestClient:
    client = TestClient(app, base_url="http://localhost", client=(ip, 50000))
    client.headers.update({"X-Requested-With": "fetch"})
    return client


def use_settings(**overrides):
    settings = make_settings(**overrides)
    app.dependency_overrides[get_settings] = lambda: settings
    return settings


# ======================================================================
# 1. Login required for AI analysis; public features stay public
# ======================================================================


def test_analysis_requires_login(ai):
    response = ai.analyze()
    assert response.status_code == 401
    assert ai.gen.calls == 0  # Gemini never called
    assert run_db("SELECT count(*) FROM ai_usage_daily")[0][0] == 0


def test_logged_in_analysis_works_and_counts_once(ai):
    sign_up(ai.client)
    assert ai.analyze().status_code == 200
    assert ai.gen.calls == 1
    assert ai.used() == 1


def test_public_search_still_works_without_login(ai):
    assert browser().get("/api/search", params={"q": "metformin"}).status_code == 200


def test_usage_endpoint_requires_login(ai):
    assert browser().get("/api/me/ai-usage").status_code == 401


# ======================================================================
# 2. Daily per-user and overall limits (PostgreSQL, atomic)
# ======================================================================


def test_per_user_daily_limit_and_retry_after(ai):
    use_settings(ai_daily_limit_per_user=3, ai_daily_limit_total=0)
    sign_up(ai.client)
    for _ in range(3):
        assert ai.analyze().status_code == 200
    blocked = ai.analyze()
    assert blocked.status_code == 429
    assert "all 3 AI analyses" in blocked.json()["detail"]
    assert blocked.headers["retry-after"] == str(2 * 3600)  # seconds until midnight UTC
    assert ai.gen.calls == 3  # the blocked request never reached Gemini


def test_default_limit_is_20_per_user(ai):
    sign_up(ai.client)
    run_db("INSERT INTO ai_usage_daily (user_id, usage_date, used) SELECT id, :d, 20 FROM users", {"d": NOW.date()})
    assert ai.analyze().status_code == 429
    assert ai.gen.calls == 0


def test_limit_resets_on_the_next_utc_day(ai):
    use_settings(ai_daily_limit_per_user=1, ai_daily_limit_total=0)
    sign_up(ai.client)
    assert ai.analyze().status_code == 200
    assert ai.analyze().status_code == 429
    ai.time["now"] = NOW + timedelta(hours=3)  # past midnight UTC
    assert ai.analyze().status_code == 200


def test_overall_daily_cap_across_users(ai):
    use_settings(ai_daily_limit_per_user=10, ai_daily_limit_total=2)
    sign_up(ai.client)
    bob = browser()
    sign_up(bob, email="bob@example.org")
    assert ai.analyze().status_code == 200
    assert ai.analyze(bob).status_code == 200
    blocked = ai.analyze(bob)
    assert blocked.status_code == 429
    assert "service" in blocked.json()["detail"]
    # Bob's own count was not increased by the refused request (the transaction rolled back).
    assert ai.used("bob@example.org") == 1
    assert run_db("SELECT used FROM ai_usage_daily_total")[0][0] == 2


def test_usage_endpoint_reports_remaining(ai):
    use_settings(ai_daily_limit_per_user=5, ai_daily_limit_total=0)
    sign_up(ai.client)
    ai.analyze()
    ai.analyze()
    data = ai.client.get("/api/me/ai-usage").json()
    assert (data["used"], data["limit"], data["remaining"]) == (2, 5, 3)
    assert data["resets_at"].startswith("2026-10-25T00:00:00")


def test_usage_endpoint_respects_overall_cap(ai):
    use_settings(ai_daily_limit_per_user=5, ai_daily_limit_total=3)
    sign_up(ai.client)
    run_db("INSERT INTO ai_usage_daily_total (usage_date, used) VALUES (:d, 3)", {"d": NOW.date()})
    assert ai.client.get("/api/me/ai-usage").json()["remaining"] == 0


@pytest.mark.parametrize(
    ("generator_error", "pubmed_xml", "expected_status"),
    [
        (AnalysisUnavailableError("down"), None, 502),  # Gemini failure
        (None, efetch_xml(), 404),  # paper not found
        (RuntimeError("bug"), None, 500),  # unexpected error
    ],
)
def test_failed_analyses_are_refunded(ai, generator_error, pubmed_xml, expected_status):
    sign_up(ai.client)
    ai.gen.error = generator_error
    if pubmed_xml is not None:
        app.dependency_overrides[get_pubmed_client] = lambda: make_client(pubmed_handler(esearch_json([]), pubmed_xml))
    client = TestClient(app, base_url="http://localhost", raise_server_exceptions=False)
    client.cookies = ai.client.cookies
    client.headers.update({"X-Requested-With": "fetch"})
    assert ai.analyze(client).status_code == expected_status
    assert ai.used() == 0
    assert run_db("SELECT coalesce(sum(used), 0) FROM ai_usage_daily_total")[0][0] == 0


def test_pubmed_outage_is_refunded(ai):
    sign_up(ai.client)

    def down(request):
        raise httpx.ConnectError("no route to host")

    app.dependency_overrides[get_pubmed_client] = lambda: make_client(down, make_settings(ncbi_max_retries=0))
    assert ai.analyze().status_code == 502
    assert ai.used() == 0


def test_burst_limit_stops_rapid_clicking_without_using_the_daily_allowance(ai):
    app.state.ai_burst_limiter = SlidingWindowLimiter(2, 60)
    sign_up(ai.client)
    assert ai.analyze().status_code == 200
    assert ai.analyze().status_code == 200
    blocked = ai.analyze()
    assert blocked.status_code == 429
    assert "too quickly" in blocked.json()["detail"]
    assert int(blocked.headers["retry-after"]) > 0
    assert ai.used() == 2


def test_limits_are_per_user(ai):
    use_settings(ai_daily_limit_per_user=1, ai_daily_limit_total=0)
    sign_up(ai.client)
    assert ai.analyze().status_code == 200
    bob = browser()
    sign_up(bob, email="bob@example.org")
    assert ai.analyze(bob).status_code == 200


def test_concurrent_reservations_never_exceed_the_limit(db_client):
    """12 simultaneous reservations against a limit of 5: exactly 5 succeed (row locking in PostgreSQL)."""
    sign_up(db_client)
    [(user_id,)] = run_db("SELECT id FROM users")
    settings = make_settings(ai_daily_limit_per_user=5, ai_daily_limit_total=0)

    async def attempt(sessionmaker):
        async with sessionmaker() as session:
            guard = AiUsageGuard(session, settings, SlidingWindowLimiter(1000, 60), NOW)
            try:
                await guard.reserve(user_id)
                return True
            except UsageLimitError:
                return False

    async def run_all():
        engine = create_async_engine(TEST_DATABASE_URL, pool_size=12, max_overflow=0)
        try:
            sessionmaker = create_sessionmaker(engine)
            return await asyncio.gather(*(attempt(sessionmaker) for _ in range(12)))
        finally:
            await engine.dispose()

    results = asyncio.run(run_all())
    assert results.count(True) == 5
    assert run_db("SELECT used FROM ai_usage_daily")[0][0] == 5


def test_refund_never_goes_below_zero(db_client):
    sign_up(db_client)
    [(user_id,)] = run_db("SELECT id FROM users")
    settings = make_settings(ai_daily_limit_total=0)

    async def go():
        engine = create_async_engine(TEST_DATABASE_URL, poolclass=NullPool)
        try:
            async with create_sessionmaker(engine)() as session:
                guard = AiUsageGuard(session, settings, SlidingWindowLimiter(1000, 60), NOW)
                reservation = await guard.reserve(user_id)
                await guard.refund(reservation)
                await guard.refund(reservation)  # double refund
        finally:
            await engine.dispose()

    asyncio.run(go())
    assert run_db("SELECT used FROM ai_usage_daily")[0][0] == 0


def test_deleting_a_user_removes_their_usage(ai):
    sign_up(ai.client)
    ai.analyze()
    run_db("DELETE FROM users")
    assert run_db("SELECT count(*) FROM ai_usage_daily")[0][0] == 0


# ======================================================================
# 3. Rate limits on login and registration (server-side, per IP)
# ======================================================================


def test_failed_logins_across_many_emails_are_limited_per_ip(db_client):
    sign_up(db_client)  # the real account: ada@example.org
    app.state.login_ip_limiter = SlidingWindowLimiter(3, 900)
    attacker = browser("10.0.0.66")
    for i in range(3):
        response = attacker.post("/api/auth/login", json={"email": f"user{i}@example.org", "password": "guess-123"})
        assert response.status_code == 401
    blocked = attacker.post("/api/auth/login", json={"email": "ada@example.org", "password": PASSWORD})
    assert blocked.status_code == 429  # even the right password, from this IP, for now
    assert int(blocked.headers["retry-after"]) > 0


def test_other_ips_are_not_affected(db_client):
    sign_up(db_client)
    app.state.login_ip_limiter = SlidingWindowLimiter(2, 900)
    attacker = browser("10.0.0.66")
    for i in range(2):
        attacker.post("/api/auth/login", json={"email": f"user{i}@example.org", "password": "guess-123"})
    assert attacker.post("/api/auth/login", json={"email": "x@example.org", "password": "guess-123"}).status_code == 429
    assert browser("10.0.0.7").post("/api/auth/login", json={"email": "ada@example.org", "password": PASSWORD}).status_code == 200


def test_successful_logins_are_never_limited_and_do_not_reset_the_ip_counter(db_client):
    sign_up(db_client)
    app.state.login_ip_limiter = SlidingWindowLimiter(3, 900)
    user = browser("10.0.0.8")
    for _ in range(10):  # many successful logins: never blocked
        assert user.post("/api/auth/login", json={"email": "ada@example.org", "password": PASSWORD}).status_code == 200
    for i in range(2):
        user.post("/api/auth/login", json={"email": f"u{i}@example.org", "password": "guess-123"})
    user.post("/api/auth/login", json={"email": "ada@example.org", "password": PASSWORD})  # success in between
    user.post("/api/auth/login", json={"email": "u9@example.org", "password": "guess-123"})  # 3rd failure
    assert user.post("/api/auth/login", json={"email": "ada@example.org", "password": PASSWORD}).status_code == 429


def test_registration_is_limited_per_ip_including_duplicates(db_client):
    app.state.register_ip_limiter = SlidingWindowLimiter(2, 3600)
    signup = browser("10.0.0.9")
    assert signup.post("/api/auth/register", json={"email": "a1@example.org", "password": PASSWORD}).status_code == 201
    assert signup.post("/api/auth/register", json={"email": "a1@example.org", "password": PASSWORD}).status_code == 409
    blocked = signup.post("/api/auth/register", json={"email": "a2@example.org", "password": PASSWORD})
    assert blocked.status_code == 429
    assert "sign-up" in blocked.json()["detail"]
    assert run_db("SELECT count(*) FROM users")[0][0] == 1
    assert browser("10.0.0.10").post(
        "/api/auth/register", json={"email": "a3@example.org", "password": PASSWORD}
    ).status_code == 201


def test_spoofed_forwarded_for_is_ignored_by_default(db_client):
    app.state.login_ip_limiter = SlidingWindowLimiter(2, 900)
    attacker = browser("10.0.0.66")
    for i in range(3):
        attacker.headers["X-Forwarded-For"] = f"203.0.113.{i}"  # a different fake IP each time
        last = attacker.post("/api/auth/login", json={"email": f"u{i}@example.org", "password": "guess-123"})
    assert last.status_code == 429  # the real client IP was counted


def test_forwarded_for_is_used_only_when_trusted(db_client):
    use_settings(trust_proxy_headers=True)
    app.state.login_ip_limiter = SlidingWindowLimiter(1, 900)
    proxy = browser("10.0.0.1")
    proxy.headers["X-Forwarded-For"] = "198.51.100.1"
    proxy.post("/api/auth/login", json={"email": "u1@example.org", "password": "guess-123"})
    assert proxy.post("/api/auth/login", json={"email": "u2@example.org", "password": "guess-123"}).status_code == 429
    proxy.headers["X-Forwarded-For"] = "198.51.100.2, 10.0.0.1"  # a different end user behind the proxy
    assert proxy.post("/api/auth/login", json={"email": "u3@example.org", "password": "guess-123"}).status_code == 401


def test_limiter_window_expires():
    now = [0.0]
    limiter = SlidingWindowLimiter(2, 60, clock=lambda: now[0])
    assert limiter.hit("k") is None and limiter.hit("k") is None
    assert limiter.hit("k") == 61
    now[0] = 61
    assert limiter.hit("k") is None


# ======================================================================
# 4. Secrets stay out of logs and user-facing errors
# ======================================================================

FAKE_NCBI_KEY = "FAKE-NCBI-KEY-1234567"


def test_ncbi_key_not_logged_even_with_info_logging(caplog):
    caplog.set_level(logging.INFO)  # everything at INFO, including httpx
    caplog.set_level(logging.INFO, logger="httpx")
    client = PubMedClient(
        make_settings(ncbi_api_key=FAKE_NCBI_KEY),
        httpx.AsyncClient(transport=httpx.MockTransport(pubmed_handler(esearch_json([]), efetch_xml()))),
    )
    asyncio.run(client.esearch("asthma", 1))
    assert "esearch.fcgi" in caplog.text  # httpx did log the request…
    assert FAKE_NCBI_KEY not in caplog.text  # …but not the key
    assert f"api_key={REDACTED}" in caplog.text


def test_http_client_loggers_are_quiet_by_default():
    for name in ("httpx", "httpcore", "google_genai"):
        assert logging.getLogger(name).getEffectiveLevel() >= logging.WARNING


@pytest.mark.parametrize(
    ("raw", "must_not_contain"),
    [
        ("GET https://eutils.ncbi.nlm.nih.gov/x?db=pubmed&api_key=abc123secret&tool=t", "abc123secret"),
        ("postgresql+asyncpg://app:Sup3rS3cret@db.example.org:5432/prod", "Sup3rS3cret"),
        ("request failed: key=AIzaSyFAKEFAKE123&alt=json", "AIzaSyFAKEFAKE123"),
        ("password=hunter2-long", "hunter2-long"),
    ],
)
def test_redact_patterns(raw, must_not_contain):
    out = redact(raw, secrets=[])
    assert must_not_contain not in out
    assert REDACTED in out


def test_known_secret_values_are_redacted_everywhere_including_tracebacks(caplog):
    literal = "LITERAL-GEMINI-KEY-VALUE-999"
    install_log_redaction(make_settings(gemini_api_key=literal))
    try:
        logger = logging.getLogger("app.test")
        caplog.set_level(logging.INFO, logger="app.test")
        logger.warning("config dump: %s", {"gemini": literal})
        try:
            raise ValueError(f"provider said: bad key {literal}")
        except ValueError:
            logger.exception("call failed")
        assert literal not in caplog.text
        for record in caplog.records:
            assert literal not in (record.exc_text or "")
    finally:
        install_log_redaction(get_settings())  # restore the real secret list


def test_pubmed_errors_shown_to_users_are_generic(ai):
    def broken(request):
        return httpx.Response(400, json={"error": f"API key invalid: {FAKE_NCBI_KEY}"})

    app.dependency_overrides[get_pubmed_client] = lambda: make_client(broken, make_settings(ncbi_api_key=FAKE_NCBI_KEY))
    response = browser().get("/api/search", params={"q": "asthma"})
    assert response.status_code == 502
    assert response.json()["detail"] == "PubMed returned an unexpected response. Please try again."
    assert FAKE_NCBI_KEY not in response.text


def test_connection_error_message_has_no_url(ai):
    def down(request):
        raise httpx.ConnectError(f"cannot connect to {request.url}")  # message contains the full URL

    client = make_client(down, make_settings(ncbi_api_key=FAKE_NCBI_KEY, ncbi_max_retries=0))
    from app.services.pubmed import PubMedResponseError

    with pytest.raises(PubMedResponseError) as excinfo:
        asyncio.run(client.esearch("asthma", 1))
    assert FAKE_NCBI_KEY not in str(excinfo.value)
    assert "ConnectError" in str(excinfo.value)


def test_analysis_and_usage_responses_never_contain_secrets(ai):
    sign_up(ai.client)
    settings = get_settings()
    secrets = [s for s in (settings.ncbi_api_key, settings.gemini_key_value) if s]
    for response in (ai.analyze(), ai.client.get("/api/me/ai-usage"), browser().get("/api/search", params={"q": "x"})):
        for secret in secrets:
            assert secret not in response.text


def test_retry_after_is_readable_by_the_frontend(ai):
    """Browsers only let cross-origin JavaScript read headers listed in Access-Control-Expose-Headers."""
    use_settings(ai_daily_limit_per_user=1, ai_daily_limit_total=0)
    sign_up(ai.client)
    ai.analyze()
    blocked = ai.client.post(
        f"/api/papers/{PMID}/analyze", json={"summary_level": "college"}, headers={"Origin": "http://localhost:3000"}
    )
    assert blocked.status_code == 429
    assert "retry-after" in blocked.headers.get("access-control-expose-headers", "").lower()


def test_uvicorn_access_log_lines_still_format_and_hide_tokens(capsys):
    """Redaction used to drop record.args, which uvicorn's AccessFormatter unpacks:
    every access-log line became a 'Logging error' traceback. Args are now redacted in place."""
    import sys

    from uvicorn.logging import AccessFormatter

    install_log_redaction(make_settings())
    try:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(AccessFormatter('%(client_addr)s - "%(request_line)s" %(status_code)s', use_colors=False))
        logger = logging.getLogger("uvicorn.access.test")
        logger.handlers, logger.propagate = [handler], False
        token = "Q" * 43
        logger.warning('%s - "%s %s HTTP/%s" %d', "127.0.0.1:5000", "POST", f"/api/unsubscribe/one-click?token={token}", "1.1", 200)
        logger.warning('%s - "%s %s HTTP/%s" %d', "127.0.0.1:5000", "GET", "/health", "1.1", 200)
        out = capsys.readouterr()
        assert "Logging error" not in out.err and "Traceback" not in out.err
        assert f'127.0.0.1:5000 - "POST /api/unsubscribe/one-click?token={REDACTED} HTTP/1.1" 200' in out.out
        assert '127.0.0.1:5000 - "GET /health HTTP/1.1" 200' in out.out
        assert token not in out.out
    finally:
        install_log_redaction(get_settings())
