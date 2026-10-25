"""Step D stage 2: the scheduled-delivery engine, against the PostgreSQL test database.

PubMed, Gemini and the email sender are fakes: no network, and no real email is
ever sent. The clock is pinned. Schedule used by most tests: daily at 09:00 UTC.
"""

import asyncio
import json
import logging
import re
import uuid
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from app.db import create_sessionmaker
from app.scheduler import SCHEDULER_LOCK_KEY, run_locked_tick
from app.services.delivery import DeliveryEngine, GlobalAiBudget, effective_mode, search_window
from app.models import SubscriptionFrequency
from app.services.email import (
    EmailError,
    EmailNotConfiguredError,
    EmailRateLimitError,
    EmailRejectedError,
    EmailTimeoutError,
    EmailUnavailableError,
    SentEmail,
)
from app.services.gemini import AnalysisUnavailableError
from app.services.usage import UsageLimitError
from tests.conftest import (
    ACCOUNT_TABLES,
    TEST_DATABASE_URL,
    article_xml,
    efetch_xml,
    esearch_json,
    make_client,
    make_settings,
    run_db,
)

ME = "ada@example.org"
KEY = "re_test_SECRET_key_123456"
MONDAY_0800 = datetime(2026, 10, 26, 8, 0, tzinfo=UTC)
DUE = datetime(2026, 10, 26, 9, 0, tzinfo=UTC)
RECENT = {"year": "2026", "month": "Oct", "day": "22"}
ARTICLES = {
    pmid: article_xml(pmid, f"Paper {pmid} about leg sarcoma", abstract=f"Abstract of paper {pmid}.", **RECENT)
    for pmid in ("101", "102", "103", "104")
}


class Crash(BaseException):
    """Simulates the process dying (not an ordinary error the engine would handle)."""


class FakeSender:
    def __init__(self) -> None:
        self.sent: list[tuple] = []  # (message, idempotency_key) for every attempt
        self.script: list = []  # per attempt: None = success, or an exception to raise
        self.delay = 0.0

    async def send(self, message, *, idempotency_key: str) -> SentEmail:
        self.sent.append((message, idempotency_key))
        if self.delay:
            await asyncio.sleep(self.delay)
        outcome = self.script.pop(0) if self.script else None
        if outcome is not None:
            raise outcome
        return SentEmail(provider_message_id=f"msg_{len(self.sent)}")


class FakeGenerator:
    model = "fake-gemini"

    def __init__(self) -> None:
        self.calls = 0
        self.error: BaseException | None = None
        self.hook = None  # async callable run during generation
        self.prefix = "Summary"

    async def generate(self, *, prompt: str, **_):
        self.calls += 1
        if self.hook:
            await self.hook()
        if self.error:
            raise self.error
        pmids = re.findall(r'"pmid": "(\d+)"', prompt)
        return json.dumps({"summaries": [{"pmid": p, "summary": f"{self.prefix} of paper {p}."} for p in pmids]})


class FakePubMed:
    def __init__(self) -> None:
        self.pmids = ["101", "102"]
        self.searches: list[dict] = []
        self.down = False

    def handler(self, request: httpx.Request) -> httpx.Response:
        if self.down:
            return httpx.Response(500)
        if request.url.path.endswith("esearch.fcgi"):
            self.searches.append(dict(request.url.params))
            return httpx.Response(200, json=esearch_json(self.pmids))
        wanted = request.url.params.get("id", "").split(",")
        return httpx.Response(200, text=efetch_xml(*(ARTICLES[i] for i in wanted if i in ARTICLES)))


async def sql(statement: str, params: dict | None = None):
    """Run SQL from inside a running event loop (run_db can't: it starts its own loop)."""
    engine = create_async_engine(TEST_DATABASE_URL, poolclass=NullPool)
    try:
        async with engine.begin() as conn:
            await conn.execute(text(statement), params or {})
    finally:
        await engine.dispose()


class World:
    def __init__(self, **settings) -> None:
        self.now = MONDAY_0800
        self.sender = FakeSender()
        self.gen = FakeGenerator()
        self.pubmed = FakePubMed()
        self.configure(**settings)

    def configure(self, **overrides) -> None:
        values = {
            "digest_delivery_mode": "allowlist",
            "email_enabled": True,
            "resend_api_key": KEY,
            "email_test_recipients": ME,
            **overrides,
        }
        self.settings = make_settings(**values)

    def engine(self, sessionmaker, **kwargs) -> DeliveryEngine:
        return DeliveryEngine(
            sessionmaker,
            self.settings,
            make_client(self.pubmed.handler, self.settings),
            self.gen,
            self.sender,
            clock=lambda: self.now,
            **kwargs,
        )

    async def _tick(self, **kwargs):
        db_engine = create_async_engine(TEST_DATABASE_URL, poolclass=NullPool)
        try:
            return await self.engine(create_sessionmaker(db_engine), **kwargs).tick()
        finally:
            await db_engine.dispose()

    def tick(self, at: datetime | None = None, **kwargs):
        if at is not None:
            self.now = at
        return asyncio.run(self._tick(**kwargs))

    @staticmethod
    def deliveries() -> list[dict]:
        rows = run_db(
            "SELECT status, attempts, error_code, outcome_uncertain, idempotency_key, email_subject, email_html,"
            " paper_pmids, window_start, window_end, mode, provider_message_id, scheduled_for, email_to"
            " FROM digest_deliveries ORDER BY scheduled_for, created_at"
        )
        keys = ("status", "attempts", "error_code", "uncertain", "key", "subject", "html", "pmids", "start", "end",
                "mode", "message_id", "scheduled_for", "to")
        return [dict(zip(keys, r)) for r in rows]

    @staticmethod
    def sent_pmids(sub: str) -> set[str]:
        return {r[0] for r in run_db("SELECT pmid FROM digest_sent_papers WHERE subscription_id = :s", {"s": sub})}


@pytest.fixture
def world(migrated_test_db):
    run_db(f"TRUNCATE {ACCOUNT_TABLES} RESTART IDENTITY CASCADE")
    return World()


def add_subscription(
    email: str = ME, *, frequency="daily", weekday=None, month_day=None, at="09:00", tz="UTC",
    next_run: datetime | None = DUE, email_enabled=True, nothing_new=False, paper_count=5, topic="leg sarcoma",
) -> str:
    user = run_db("SELECT id FROM users WHERE email = :e", {"e": email})
    if user:
        user_id = str(user[0][0])
    else:
        user_id = str(uuid.uuid4())
        run_db("INSERT INTO users (id, email, password_hash) VALUES (:id, :e, 'x')", {"id": user_id, "e": email})
    sub_id = str(uuid.uuid4())
    run_db(
        "INSERT INTO research_subscriptions (id, user_id, topic, topic_key, frequency, weekday, month_day,"
        " delivery_time, time_zone, paper_count, reading_level, email_enabled, email_when_no_new_papers, next_run_at)"
        " VALUES (:id, :u, :t, :k, :f, :w, :m, :at, :tz, :n, 'college', :e, :nn, :next)",
        {"id": sub_id, "u": user_id, "t": topic, "k": topic + sub_id[:4], "f": frequency, "w": weekday,
         "m": month_day, "at": datetime.strptime(at, "%H:%M").time(), "tz": tz, "n": paper_count, "e": email_enabled,
         "nn": nothing_new, "next": next_run},
    )
    return sub_id


def next_run(sub: str):
    return run_db("SELECT next_run_at FROM research_subscriptions WHERE id = :s", {"s": sub})[0][0]


# ======================================================================
# modes and initialization
# ======================================================================


def test_mode_off_does_nothing(world):
    world.configure(digest_delivery_mode="off")
    sub = add_subscription(next_run=None)
    result = world.tick(at=DUE + timedelta(minutes=1))
    assert result.mode == "off" and result.processed == 0
    assert next_run(sub) is None and world.deliveries() == [] and world.sender.sent == []


def test_off_is_the_default():
    settings = make_settings()
    assert settings.digest_delivery_mode == "off" and settings.digest_scheduler_enabled is False
    assert effective_mode(settings) == "off"


@pytest.mark.parametrize(
    "missing", [{"email_enabled": False}, {"resend_api_key": None}, {"email_test_recipients": ""}]
)
def test_allowlist_without_full_email_setup_runs_as_off(world, missing):
    world.configure(**missing)
    add_subscription()
    assert world.tick(at=DUE + timedelta(minutes=1)).mode == "off"
    assert world.deliveries() == [] and world.sender.sent == []


def test_overrides_can_only_make_a_tick_safer(world):
    with pytest.raises(ValueError):
        world.engine(None, mode_override="allowlist")


def test_existing_subscriptions_get_a_next_run_on_the_first_tick(world):
    sub = add_subscription(next_run=None)
    off = add_subscription("bob@example.org", next_run=None, email_enabled=False)
    result = world.tick(at=MONDAY_0800)
    assert result.initialized == 1
    assert next_run(sub) == DUE and next_run(off) is None
    assert world.deliveries() == []  # nothing was due yet


def test_nothing_happens_before_the_run_is_due(world):
    add_subscription()
    world.tick(at=DUE - timedelta(seconds=1))
    assert world.deliveries() == [] and world.sender.sent == []


# ======================================================================
# a normal delivery
# ======================================================================


def test_allowlisted_delivery_is_sent_once_and_recorded(world):
    sub = add_subscription()
    result = world.tick(at=DUE + timedelta(minutes=1))
    assert result.outcomes["sent"] == 1
    [d] = world.deliveries()
    assert d["status"] == "sent" and d["attempts"] == 1 and d["uncertain"] is False and d["mode"] == "allowlist"
    [(message, key)] = world.sender.sent
    assert message.to == ME and key == d["key"] and key.startswith("digest-")
    assert message.subject == "Medstract Research Digest: leg sarcoma"  # no "(Test)": scheduled
    assert "Summary of paper 101." in message.html and "scheduled research digest" in message.html
    assert world.sent_pmids(sub) == {"101", "102"}
    assert run_db("SELECT last_sent_at FROM research_subscriptions WHERE id = :s", {"s": sub})[0][0] is not None
    assert next_run(sub) == DUE + timedelta(days=1)
    # A second tick doesn't send it again.
    world.tick(at=DUE + timedelta(minutes=30))
    assert len(world.sender.sent) == 1


def test_scheduled_email_links_to_the_configured_app(world):
    world.configure(public_app_url="https://medstract.example", public_api_url="https://api.medstract.example")
    add_subscription()
    world.tick(at=DUE + timedelta(minutes=1))
    [(message, _)] = world.sender.sent
    assert '<a href="https://medstract.example/"' in message.html and "Visit Medstract</a>" in message.html
    assert "Explore more research with Medstract." in message.html
    assert "Visit Medstract: https://medstract.example/" in message.text


def test_scheduled_ai_uses_only_the_overall_cap(world):
    add_subscription()
    world.tick(at=DUE + timedelta(minutes=1))
    assert world.gen.calls == 1
    assert run_db("SELECT coalesce(sum(used), 0) FROM ai_usage_daily")[0][0] == 0  # users' own 20/day untouched
    assert run_db("SELECT used FROM ai_usage_daily_total")[0][0] == 1


def test_not_allowlisted_users_are_skipped_before_any_work(world):
    add_subscription("someone@example.org")
    world.tick(at=DUE + timedelta(minutes=1))
    [d] = world.deliveries()
    assert (d["status"], d["error_code"]) == ("skipped_disabled", "not_allowlisted")
    assert world.sender.sent == [] and world.gen.calls == 0 and world.pubmed.searches == []


# ======================================================================
# dry run
# ======================================================================


def test_dry_run_builds_and_stores_but_never_sends(world):
    world.configure(digest_delivery_mode="dry_run")
    sub = add_subscription("anyone@example.org")  # dry runs cover every active subscription
    world.tick(at=DUE + timedelta(minutes=1))
    [d] = world.deliveries()
    assert d["status"] == "dry_run" and d["mode"] == "dry_run" and d["pmids"] == ["101", "102"]
    assert "Paper 101 about leg sarcoma" in d["html"]
    assert world.sender.sent == []
    assert world.gen.calls == 0  # no Gemini in dry runs by default
    assert "AI summaries are skipped in dry runs." in d["html"]
    assert world.sent_pmids(sub) == set()  # nothing counts as sent
    assert run_db("SELECT last_sent_at FROM research_subscriptions WHERE id = :s", {"s": sub})[0][0] is None


def test_dry_run_can_use_ai_when_asked(world):
    world.configure(digest_delivery_mode="dry_run", digest_dry_run_use_ai=True)
    add_subscription()
    world.tick(at=DUE + timedelta(minutes=1))
    assert world.gen.calls == 1 and world.sender.sent == []


def test_dry_run_override_never_sends_even_in_allowlist_mode(world):
    add_subscription()
    world.tick(at=DUE + timedelta(minutes=1), mode_override="dry_run")
    assert world.deliveries()[0]["status"] == "dry_run" and world.sender.sent == []


def test_switching_to_dry_run_stops_a_queued_real_delivery(world):
    world.sender.script = [EmailRateLimitError("slow down")]
    add_subscription()
    world.tick(at=DUE + timedelta(minutes=1))  # built for sending, then 429 -> waiting to retry
    world.configure(digest_delivery_mode="dry_run")
    world.tick(at=DUE + timedelta(minutes=10))
    d = world.deliveries()[0]
    assert (d["status"], d["error_code"]) == ("skipped_disabled", "mode_changed")
    assert len(world.sender.sent) == 1


# ======================================================================
# duplicates and concurrency (real PostgreSQL)
# ======================================================================


def test_two_schedulers_ticking_at_once_send_exactly_one_email(world):
    add_subscription()
    world.now = DUE + timedelta(minutes=1)
    world.sender.delay = 0.05  # widen the window for interleaving

    async def both():
        engines = [create_async_engine(TEST_DATABASE_URL, poolclass=NullPool) for _ in range(2)]
        try:
            return await asyncio.gather(*(world.engine(create_sessionmaker(e)).tick() for e in engines))
        finally:
            for e in engines:
                await e.dispose()

    asyncio.run(both())
    assert len(world.deliveries()) == 1
    assert len(world.sender.sent) == 1


def test_concurrent_workers_never_claim_the_same_delivery(world):
    emails = [f"user{n}@example.org" for n in range(6)]
    world.configure(email_test_recipients=",".join(emails), digest_max_ai_calls_per_tick=10)
    for e in emails:
        add_subscription(e)
    world.now = DUE + timedelta(minutes=1)
    world.sender.delay = 0.02

    async def workers():
        engines = [create_async_engine(TEST_DATABASE_URL, poolclass=NullPool) for _ in range(3)]
        try:
            return await asyncio.gather(*(world.engine(create_sessionmaker(e)).tick() for e in engines))
        finally:
            for e in engines:
                await e.dispose()

    results = asyncio.run(workers())
    keys = [key for _, key in world.sender.sent]
    assert len(keys) == 6 and len(set(keys)) == 6  # every delivery sent exactly once
    assert sum(r.processed for r in results) == 6
    assert {d["status"] for d in world.deliveries()} == {"sent"}


def test_the_advisory_lock_lets_only_one_scheduler_tick(world):
    add_subscription()

    async def contested():
        holder = create_async_engine(TEST_DATABASE_URL, poolclass=NullPool)
        other = create_async_engine(TEST_DATABASE_URL, poolclass=NullPool)
        try:
            async with holder.connect() as conn:
                await conn.execute(text("SELECT pg_advisory_lock(:k)"), {"k": SCHEDULER_LOCK_KEY})
                busy = await run_locked_tick(other, world.engine(create_sessionmaker(other)))
                await conn.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": SCHEDULER_LOCK_KEY})
            free = await run_locked_tick(other, world.engine(create_sessionmaker(other)))
            return busy, free
        finally:
            await holder.dispose()
            await other.dispose()

    world.now = DUE + timedelta(minutes=1)
    busy, free = asyncio.run(contested())
    assert busy is None and free is not None and free.outcomes["sent"] == 1


def test_per_tick_limit_leaves_the_rest_for_the_next_tick(world):
    emails = ["a@example.org", "b@example.org", "c@example.org"]
    world.configure(email_test_recipients=",".join(emails), digest_max_per_tick=2)
    for e in emails:
        add_subscription(e)
    assert world.tick(at=DUE + timedelta(minutes=1)).processed == 2
    assert [d["status"] for d in world.deliveries()].count("pending") == 1
    assert world.tick(at=DUE + timedelta(minutes=2)).processed == 1
    assert len(world.sender.sent) == 3


# ======================================================================
# global AI cap
# ======================================================================


def test_global_ai_cap_is_atomic_across_concurrent_workers(world):
    world.configure(ai_daily_limit_total=5, digest_max_ai_calls_per_tick=50)

    async def race():
        engine = create_async_engine(TEST_DATABASE_URL, poolclass=NullPool)
        sm = create_sessionmaker(engine)

        async def one():
            try:
                await GlobalAiBudget(sm, world.settings, DUE).reserve(uuid.uuid4())
                return True
            except UsageLimitError:
                return False

        try:
            return await asyncio.gather(*(one() for _ in range(12)))
        finally:
            await engine.dispose()

    assert sum(asyncio.run(race())) == 5
    assert run_db("SELECT used FROM ai_usage_daily_total")[0][0] == 5


def test_global_cap_reached_falls_back_to_excerpts_and_still_sends(world):
    world.configure(ai_daily_limit_total=3)
    run_db("INSERT INTO ai_usage_daily_total (usage_date, used) VALUES ('2026-10-26', 3)")
    add_subscription()
    world.tick(at=DUE + timedelta(minutes=1))
    assert world.gen.calls == 0
    [(message, _)] = world.sender.sent
    assert "daily AI capacity has been reached" in message.html and "From the abstract:" in message.html


def test_ai_calls_per_tick_are_limited(world):
    emails = ["a@example.org", "b@example.org", "c@example.org"]
    world.configure(email_test_recipients=",".join(emails), digest_max_ai_calls_per_tick=1)
    for e in emails:
        add_subscription(e)
    world.tick(at=DUE + timedelta(minutes=1))
    assert world.gen.calls == 1 and len(world.sender.sent) == 3
    with_ai = [m for m, _ in world.sender.sent if "Summary of paper" in m.html]
    assert len(with_ai) == 1


def test_gemini_failure_is_refunded_and_the_digest_still_goes_out(world):
    world.gen.error = AnalysisUnavailableError("The AI service is temporarily unavailable.")
    add_subscription()
    world.tick(at=DUE + timedelta(minutes=1))
    assert run_db("SELECT used FROM ai_usage_daily_total")[0][0] == 0
    assert world.deliveries()[0]["status"] == "sent"


# ======================================================================
# retries and permanent failures
# ======================================================================


def test_temporary_failure_is_retried_with_the_same_key_and_identical_email(world):
    world.sender.script = [EmailRateLimitError("slow down")]
    add_subscription()
    world.tick(at=DUE + timedelta(minutes=1))
    d = world.deliveries()[0]
    assert (d["status"], d["attempts"], d["error_code"], d["uncertain"]) == ("pending", 1, "resend_429", False)

    world.tick(at=DUE + timedelta(minutes=3))  # before the 5-minute backoff
    assert len(world.sender.sent) == 1

    # PubMed and Gemini now return different things; the retry must not change the email.
    world.pubmed.pmids = ["103", "104"]
    world.gen.prefix = "Different"
    world.tick(at=DUE + timedelta(minutes=7))
    first, second = world.sender.sent
    assert second[1] == first[1]  # same Idempotency-Key
    assert (second[0].subject, second[0].html, second[0].text) == (first[0].subject, first[0].html, first[0].text)
    assert world.deliveries()[0]["status"] == "sent"


# Real retry timing: first attempt at 09:01, then backoffs of 5 min, 30 min and 2 h.
RETRY_TICKS = (timedelta(minutes=1), timedelta(minutes=7), timedelta(minutes=38), timedelta(hours=2, minutes=39))


def test_retries_stop_after_the_limit_with_definite_failures(world):
    world.sender.script = [EmailRateLimitError("slow down")] * 10
    add_subscription()
    for offset in (*RETRY_TICKS, timedelta(hours=5)):
        world.tick(at=DUE + offset)
    d = world.deliveries()[0]
    assert (d["status"], d["attempts"]) == ("failed", 4) and len(world.sender.sent) == 4


def test_retries_exhausted_after_unclear_outcomes_need_review_not_failure(world):
    world.sender.script = [EmailTimeoutError("timeout", retryable=True, outcome_unknown=True)] * 10
    add_subscription()
    for offset in (*RETRY_TICKS, timedelta(hours=5)):
        world.tick(at=DUE + offset)
    d = world.deliveries()[0]
    assert (d["status"], d["attempts"], d["uncertain"]) == ("needs_review", 4, True)


@pytest.mark.parametrize(
    ("error", "status", "code"),
    [
        (EmailRejectedError("no", code="resend_403"), "failed", "resend_403"),
        (EmailNotConfiguredError("bad key", code="resend_401"), "failed", "resend_401"),
        (EmailRejectedError("dup", code="idempotency_conflict", outcome_unknown=True), "needs_review",
         "idempotency_conflict"),
    ],
)
def test_permanent_errors_are_not_retried(world, error, status, code):
    world.sender.script = [error]
    add_subscription()
    world.tick(at=DUE + timedelta(minutes=1))
    world.tick(at=DUE + timedelta(hours=3))
    d = world.deliveries()[0]
    assert (d["status"], d["error_code"], d["attempts"]) == (status, code, 1)
    assert len(world.sender.sent) == 1


def test_concurrent_idempotent_request_is_retried(world):
    world.sender.script = [
        EmailUnavailableError("busy", code="idempotency_in_progress", retryable=True, outcome_unknown=True)
    ]
    add_subscription()
    world.tick(at=DUE + timedelta(minutes=1))
    world.tick(at=DUE + timedelta(minutes=7))
    assert world.deliveries()[0]["status"] == "sent" and len(world.sender.sent) == 2


def test_pubmed_outage_while_building_is_retried_later(world):
    world.pubmed.down = True
    add_subscription()
    world.tick(at=DUE + timedelta(minutes=1))
    d = world.deliveries()[0]
    assert (d["status"], d["error_code"]) == ("pending", "pubmed_error") and world.sender.sent == []
    world.pubmed.down = False
    world.tick(at=DUE + timedelta(minutes=7))
    assert world.deliveries()[0]["status"] == "sent"


# ======================================================================
# ambiguous timeouts and the idempotency window
# ======================================================================


def test_ambiguous_timeout_is_retried_within_the_window_and_resolved(world):
    world.sender.script = [EmailTimeoutError("timeout", retryable=True, outcome_unknown=True)]
    add_subscription()
    world.tick(at=DUE + timedelta(minutes=1))
    d = world.deliveries()[0]
    assert (d["status"], d["uncertain"], d["error_code"]) == ("pending", True, "timeout")
    world.tick(at=DUE + timedelta(minutes=7))
    d = world.deliveries()[0]
    assert (d["status"], d["uncertain"]) == ("sent", False)
    assert world.sender.sent[0][1] == world.sender.sent[1][1]


def test_ambiguous_delivery_is_never_resent_after_the_window(world):
    world.configure(digest_safe_retry_hours=1)
    world.sender.script = [EmailTimeoutError("timeout", retryable=True, outcome_unknown=True)]
    add_subscription()
    world.tick(at=DUE + timedelta(minutes=1))
    world.tick(at=DUE + timedelta(hours=2))  # retry due, but the provider may have forgotten the key
    d = world.deliveries()[0]
    assert (d["status"], d["error_code"]) == ("needs_review", "idempotency_window_expired")
    assert len(world.sender.sent) == 1


def test_definite_failure_after_the_window_may_still_be_retried(world):
    world.configure(digest_safe_retry_hours=1)
    world.sender.script = [EmailRateLimitError("slow down")]  # refused: definitely not sent
    add_subscription()
    world.tick(at=DUE + timedelta(minutes=1))
    world.tick(at=DUE + timedelta(hours=2))
    assert world.deliveries()[0]["status"] == "sent"


def test_real_resend_timeouts_are_classified_as_unknown():
    """The real client: read timeouts may have been delivered, connect failures not."""
    from app.services.email import EmailMessage, ResendEmailSender

    def send_with(exc):
        def handler(request):
            raise exc(request=request) if exc is not httpx.ReadTimeout else exc("t", request=request)

        sender = ResendEmailSender(
            make_settings(resend_api_key=KEY), httpx.AsyncClient(transport=httpx.MockTransport(handler))
        )
        with pytest.raises(EmailError) as info:
            asyncio.run(sender.send(EmailMessage(to=ME, subject="s", html="h", text="t"), idempotency_key="k"))
        return info.value

    read = send_with(httpx.ReadTimeout)
    assert read.retryable and read.outcome_unknown
    connect = send_with(lambda request: httpx.ConnectError("refused", request=request))
    assert connect.retryable and not connect.outcome_unknown


@pytest.mark.parametrize(
    ("status", "name", "code", "retryable", "unknown"),
    [
        (409, "invalid_idempotent_request", "idempotency_conflict", False, True),
        (409, "concurrent_idempotent_requests", "idempotency_in_progress", True, True),
        (500, "internal_server_error", "resend_500", True, True),
        (429, "rate_limit_exceeded", "resend_429", True, False),
        (422, "validation_error", "resend_422", False, False),
    ],
)
def test_resend_status_codes_map_to_retry_rules(status, name, code, retryable, unknown):
    from app.services.email import EmailMessage, ResendEmailSender

    sender = ResendEmailSender(
        make_settings(resend_api_key=KEY),
        httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(status, json={"name": name}))),
    )
    with pytest.raises(EmailError) as info:
        asyncio.run(sender.send(EmailMessage(to=ME, subject="s", html="h", text="t"), idempotency_key="k"))
    assert (info.value.code, info.value.retryable, info.value.outcome_unknown) == (code, retryable, unknown)


# ======================================================================
# crash recovery
# ======================================================================


def test_crash_while_building_is_recovered_after_the_lease(world):
    world.gen.error = Crash()
    add_subscription()
    with pytest.raises(Crash):
        world.tick(at=DUE + timedelta(minutes=1))
    d = world.deliveries()[0]
    assert (d["status"], d["uncertain"], d["html"]) == ("sending", False, None)
    world.gen.error = None
    world.tick(at=DUE + timedelta(minutes=5))  # lease (10 min) not expired yet
    assert world.sender.sent == []
    result = world.tick(at=DUE + timedelta(minutes=12))
    assert result.recovered == 1 and world.deliveries()[0]["status"] == "sent" and len(world.sender.sent) == 1


def test_crash_during_send_is_retried_with_the_same_key_inside_the_window(world):
    world.sender.script = [Crash()]
    add_subscription()
    with pytest.raises(Crash):
        world.tick(at=DUE + timedelta(minutes=1))
    d = world.deliveries()[0]
    assert (d["status"], d["uncertain"], d["attempts"]) == ("sending", True, 1)  # committed before the call
    world.tick(at=DUE + timedelta(minutes=12))
    first, second = world.sender.sent
    assert first[1] == second[1] and first[0].html == second[0].html
    assert world.deliveries()[0]["status"] == "sent"


def test_crash_during_send_after_the_window_needs_review(world):
    world.configure(digest_safe_retry_hours=0.1)  # 6 minutes, shorter than the lease
    world.sender.script = [Crash()]
    add_subscription()
    with pytest.raises(Crash):
        world.tick(at=DUE + timedelta(minutes=1))
    world.tick(at=DUE + timedelta(minutes=12))
    d = world.deliveries()[0]
    assert (d["status"], d["error_code"]) == ("needs_review", "idempotency_window_expired")
    assert len(world.sender.sent) == 1


# ======================================================================
# preferences rechecked before sending; queued deliveries
# ======================================================================


@pytest.mark.parametrize(
    ("change", "code"),
    [
        ("email_enabled = false", "email_off"),
        ("email_enabled = false, unsubscribed_at = now()", "unsubscribed"),
    ],
)
def test_queued_delivery_is_skipped_after_unsubscribe_or_email_off(world, change, code):
    world.sender.script = [EmailRateLimitError("slow down")]
    sub = add_subscription()
    world.tick(at=DUE + timedelta(minutes=1))  # queued for retry
    run_db(f"UPDATE research_subscriptions SET {change} WHERE id = :s", {"s": sub})
    world.tick(at=DUE + timedelta(minutes=10))
    d = world.deliveries()[0]
    assert (d["status"], d["error_code"]) == ("skipped_disabled", code)
    assert len(world.sender.sent) == 1 and world.sent_pmids(sub) == set()


def test_queued_uncertain_delivery_after_unsubscribe_needs_review(world):
    world.sender.script = [EmailTimeoutError("timeout", retryable=True, outcome_unknown=True)]
    sub = add_subscription()
    world.tick(at=DUE + timedelta(minutes=1))
    run_db("UPDATE research_subscriptions SET email_enabled = false, unsubscribed_at = now() WHERE id = :s", {"s": sub})
    world.tick(at=DUE + timedelta(minutes=10))
    d = world.deliveries()[0]
    assert (d["status"], d["error_code"]) == ("needs_review", "unsubscribed") and len(world.sender.sent) == 1


def test_preferences_are_rechecked_immediately_before_sending(world):
    sub = add_subscription()

    async def turn_email_off_during_build():
        await sql("UPDATE research_subscriptions SET email_enabled = false WHERE id = :s", {"s": sub})

    world.gen.hook = turn_email_off_during_build
    world.tick(at=DUE + timedelta(minutes=1))
    d = world.deliveries()[0]
    assert (d["status"], d["error_code"]) == ("skipped_disabled", "email_off") and world.sender.sent == []


def test_changed_recipient_is_not_sent_the_old_frozen_email(world):
    world.configure(email_test_recipients=f"{ME},new@example.org")
    world.sender.script = [EmailRateLimitError("slow down")]
    add_subscription()
    world.tick(at=DUE + timedelta(minutes=1))
    run_db("UPDATE users SET email = 'new@example.org' WHERE email = :e", {"e": ME})
    world.tick(at=DUE + timedelta(minutes=10))
    d = world.deliveries()[0]
    assert (d["status"], d["error_code"]) == ("skipped_disabled", "recipient_changed")
    assert len(world.sender.sent) == 1


def test_deleted_subscription_with_a_queued_delivery(world):
    world.sender.script = [EmailRateLimitError("slow down")]
    sub = add_subscription()
    world.tick(at=DUE + timedelta(minutes=1))
    run_db("DELETE FROM research_subscriptions WHERE id = :s", {"s": sub})
    world.tick(at=DUE + timedelta(minutes=10))
    assert world.deliveries() == [] and len(world.sender.sent) == 1


def test_api_changes_cancel_queued_deliveries(world, db_client):
    from app.main import app
    from app.routers.deps import get_utc_now

    app.dependency_overrides[get_utc_now] = lambda: DUE + timedelta(minutes=2)
    try:
        db_client.post("/api/auth/register", json={"email": ME, "password": "correct horse battery"})
        body = {"topic": "leg sarcoma", "frequency": "daily", "delivery_time": "09:00", "time_zone": "UTC",
                "paper_count": 5, "reading_level": "college", "email_enabled": True}
        sub = db_client.post("/api/subscriptions", json=body).json()["id"]
        run_db("UPDATE research_subscriptions SET next_run_at = :d WHERE id = :s", {"d": DUE, "s": sub})
        world.sender.script = [EmailRateLimitError("slow down"), EmailRateLimitError("slow down")]
        world.tick(at=DUE + timedelta(minutes=1))
        assert world.deliveries()[0]["status"] == "pending"

        assert db_client.put(f"/api/subscriptions/{sub}", json={**body, "delivery_time": "10:00"}).status_code == 200
        d = world.deliveries()[0]
        assert (d["status"], d["error_code"]) == ("skipped_disabled", "schedule_changed")
        assert next_run(sub) == datetime(2026, 10, 26, 10, 0, tzinfo=UTC)

        world.tick(at=DUE + timedelta(hours=1, minutes=1))  # the new 10:00 run, again refused once
        assert db_client.put(f"/api/subscriptions/{sub}", json={**body, "delivery_time": "10:00",
                                                                "email_enabled": False}).status_code == 200
        d = world.deliveries()[-1]
        assert (d["status"], d["error_code"]) == ("skipped_disabled", "email_off")
        assert len(world.sender.sent) == 2
    finally:
        app.dependency_overrides.clear()


# ======================================================================
# search windows, sent papers, "nothing new"
# ======================================================================


def test_first_window_looks_back_from_the_scheduled_local_date(world):
    add_subscription(at="23:30", tz="America/Los_Angeles", next_run=datetime(2026, 10, 27, 6, 30, tzinfo=UTC))
    world.tick(at=datetime(2026, 10, 27, 6, 31, tzinfo=UTC))
    search = world.pubmed.searches[0]
    # 06:30 UTC on 27 Oct is 23:30 on 26 Oct in Los Angeles: the window ends on the local date.
    assert (search["mindate"], search["maxdate"]) == ("2026/10/19", "2026/10/26")
    d = world.deliveries()[0]
    assert (str(d["start"]), str(d["end"])) == ("2026-10-19", "2026-10-26")


def test_window_rules():
    daily, weekly = SubscriptionFrequency.DAILY, SubscriptionFrequency.WEEKLY
    d = lambda s: datetime.strptime(s, "%Y-%m-%d").date()  # noqa: E731
    assert search_window(daily, d("2026-10-27"), None) == (d("2026-10-20"), d("2026-10-27"))
    # After a sent digest: overlap by the look-back, so late-indexed papers aren't missed.
    assert search_window(daily, d("2026-10-27"), d("2026-10-26")) == (d("2026-10-19"), d("2026-10-27"))
    # After a long gap: capped, so a digest never digs up months of old papers.
    assert search_window(daily, d("2026-10-27"), d("2026-06-01")) == (d("2026-10-13"), d("2026-10-27"))
    assert search_window(weekly, d("2026-11-01"), d("2026-10-25")) == (d("2026-10-11"), d("2026-11-01"))


def test_papers_already_sent_are_excluded_next_time(world):
    sub = add_subscription()
    world.tick(at=DUE + timedelta(minutes=1))
    world.pubmed.pmids = ["101", "102", "103"]
    world.tick(at=DUE + timedelta(days=1, minutes=1))
    second = world.sender.sent[1][0]
    assert "Paper 103" in second.html and "Paper 101" not in second.html
    assert world.sent_pmids(sub) == {"101", "102", "103"}
    d = world.deliveries()[1]
    assert (str(d["start"]), str(d["end"])) == ("2026-10-19", "2026-10-27")  # 26 Oct (last sent end) - 7 days


def test_nothing_new_is_skipped_by_default(world):
    sub = add_subscription()
    world.tick(at=DUE + timedelta(minutes=1))
    world.tick(at=DUE + timedelta(days=1, minutes=1))  # PubMed returns the same two papers
    d = world.deliveries()[1]
    assert (d["status"], d["pmids"]) == ("skipped_no_new", None)
    assert len(world.sender.sent) == 1 and world.sent_pmids(sub) == {"101", "102"}


def test_nothing_new_email_when_the_user_asked_for_it(world):
    add_subscription(nothing_new=True)
    world.pubmed.pmids = []
    world.tick(at=DUE + timedelta(minutes=1))
    [(message, _)] = world.sender.sent
    assert "No new PubMed papers matched this topic since your last digest." in message.html
    assert world.gen.calls == 0


def test_failed_delivery_records_no_papers_and_does_not_advance_the_window(world):
    world.sender.script = [EmailRejectedError("no", code="resend_403")]
    sub = add_subscription()
    world.tick(at=DUE + timedelta(minutes=1))
    assert world.deliveries()[0]["status"] == "failed" and world.sent_pmids(sub) == set()
    world.tick(at=DUE + timedelta(days=1, minutes=1))
    d = world.deliveries()[1]
    assert d["status"] == "sent" and d["pmids"] == ["101", "102"]  # the same papers are still "new"
    assert (str(d["start"]), str(d["end"])) == ("2026-10-20", "2026-10-27")  # first-digest window again


# ======================================================================
# missed runs
# ======================================================================


def test_runs_missed_beyond_the_grace_period_are_skipped_not_sent_late(world):
    sub = add_subscription()
    world.tick(at=DUE + timedelta(hours=7))  # daily grace is 6 hours
    d = world.deliveries()[0]
    assert (d["status"], d["error_code"]) == ("skipped_missed", "missed") and world.sender.sent == []
    assert next_run(sub) == DUE + timedelta(days=1)


def test_long_downtime_records_one_missed_run_and_skips_ahead(world):
    sub = add_subscription()
    world.tick(at=DUE + timedelta(days=5, hours=1))
    assert [d["status"] for d in world.deliveries()] == ["skipped_missed"]
    assert next_run(sub) == DUE + timedelta(days=6)


def test_slightly_late_runs_are_still_sent(world):
    add_subscription()
    world.tick(at=DUE + timedelta(hours=5))
    assert world.deliveries()[0]["status"] == "sent"


# ======================================================================
# secrets and addresses stay out of logs; app wiring
# ======================================================================


def test_logs_contain_no_addresses_or_keys(world, caplog):
    world.sender.script = [EmailTimeoutError("timeout", retryable=True, outcome_unknown=True)]
    add_subscription()
    with caplog.at_level(logging.DEBUG):
        world.tick(at=DUE + timedelta(minutes=1))
        world.tick(at=DUE + timedelta(minutes=7))
    assert "Digest tick:" in caplog.text
    assert ME not in caplog.text and KEY not in caplog.text


def test_the_backend_does_not_start_a_scheduler_by_default():
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app):
        assert app.state.digest_scheduler is None


def test_an_existing_row_for_the_same_run_is_never_duplicated(world):
    """E.g. the time was changed away and back: the cancelled row for that run
    already exists. The tick must not crash or create a second row; that one run
    is not sent (a documented trade-off: duplicates are worse than a missed run)."""
    sub = add_subscription()
    user = run_db("SELECT user_id FROM research_subscriptions WHERE id = :s", {"s": sub})[0][0]
    run_db(
        "INSERT INTO digest_deliveries (id, subscription_id, user_id, scheduled_for, status, error_code,"
        " next_attempt_at, idempotency_key) VALUES (:id, :s, :u, :at, 'skipped_disabled', 'schedule_changed', :at,"
        " 'digest-earlier')",
        {"id": str(uuid.uuid4()), "s": sub, "u": user, "at": DUE},
    )
    result = world.tick(at=DUE + timedelta(minutes=1))
    assert result.scheduled == 0 and len(world.deliveries()) == 1 and world.sender.sent == []
    assert next_run(sub) == DUE + timedelta(days=1)


# ======================================================================
# Stage 4 fixes: stale queued deliveries are never sent late
# ======================================================================

STORED_TOKEN = re.compile(r"token=[A-Za-z0-9_-]{43}")


def queue_one(world, error) -> str:
    """Due at 09:00, first attempt refused at 09:01, so it's queued for a retry."""
    world.sender.script = [error]
    sub = add_subscription()
    world.tick(at=DUE + timedelta(minutes=1))
    assert world.deliveries()[0]["status"] == "pending"
    return sub


def test_pause_then_resume_within_the_grace_period_still_sends(world):
    queue_one(world, EmailRateLimitError("slow down"))
    world.configure(digest_delivery_mode="off")
    world.tick(at=DUE + timedelta(hours=2))  # paused: housekeeping only
    assert world.deliveries()[0]["status"] == "pending" and len(world.sender.sent) == 1
    world.configure()  # resume (allowlist)
    world.tick(at=DUE + timedelta(hours=5, minutes=59))  # still inside the 6 h daily grace
    assert world.deliveries()[0]["status"] == "sent" and len(world.sender.sent) == 2


def test_paused_delivery_past_the_grace_period_expires_in_off_mode_and_is_never_sent(world):
    sub = queue_one(world, EmailRateLimitError("slow down"))
    assert STORED_TOKEN.search(run_db("SELECT email_html FROM digest_deliveries")[0][0])  # still retryable
    world.configure(digest_delivery_mode="off")
    result = world.tick(at=DUE + timedelta(hours=6, minutes=1))
    assert result.mode == "off" and result.expired == 1 and result.processed == 0
    d = world.deliveries()[0]
    assert (d["status"], d["error_code"], d["uncertain"]) == ("skipped_missed", "expired", False)
    html, text_, headers = run_db("SELECT email_html, email_text, email_headers::text FROM digest_deliveries")[0]
    assert not any(STORED_TOKEN.search(v or "") for v in (html, text_, headers))
    assert world.sent_pmids(sub) == set()
    world.configure()  # resume: the old digest is not sent
    world.tick(at=DUE + timedelta(hours=7))
    assert len(world.sender.sent) == 1


def test_resuming_after_a_long_pause_expires_before_any_send(world):
    """Nothing ticked during the pause: the first tick after resuming expires first."""
    queue_one(world, EmailRateLimitError("slow down"))
    result = world.tick(at=DUE + timedelta(days=3, minutes=5))
    assert result.expired == 1
    statuses = [(d["status"], d["error_code"]) for d in world.deliveries()]
    assert statuses[0] == ("skipped_missed", "expired")
    assert ("skipped_missed", "missed") in statuses  # the runs missed meanwhile, recorded once
    assert len(world.sender.sent) == 1  # only the original refused attempt


def test_expired_papers_stay_eligible_for_the_next_digest(world):
    queue_one(world, EmailRateLimitError("slow down"))
    world.tick(at=DUE + timedelta(hours=7))  # expired
    world.tick(at=DUE + timedelta(days=1, minutes=1))  # next day's run
    sent = world.sender.sent[-1][0]
    assert "Paper 101" in sent.html and world.deliveries()[-1]["status"] == "sent"


def test_uncertain_queued_delivery_past_the_grace_period_needs_review_and_is_not_resent(world):
    queue_one(world, EmailTimeoutError("timeout", retryable=True, outcome_unknown=True))
    world.configure(digest_delivery_mode="off")
    world.tick(at=DUE + timedelta(hours=6, minutes=1))
    d = world.deliveries()[0]
    assert (d["status"], d["error_code"], d["uncertain"]) == ("needs_review", "expired", True)
    assert not STORED_TOKEN.search(run_db("SELECT email_html FROM digest_deliveries")[0][0])
    world.configure()
    world.tick(at=DUE + timedelta(hours=7))
    assert len(world.sender.sent) == 1


@pytest.mark.parametrize(("late", "expected"), [(timedelta(hours=23), "sent"), (timedelta(hours=25), "skipped_missed")])
def test_weekly_and_monthly_deliveries_have_a_24_hour_grace(world, late, expected):
    world.sender.script = [EmailRateLimitError("slow down")]
    add_subscription(frequency="weekly", weekday=1)  # Monday 26 Oct 09:00 UTC
    world.tick(at=DUE + timedelta(minutes=1))
    world.tick(at=DUE + late)
    assert world.deliveries()[0]["status"] == expected


def test_normal_retry_schedule_fits_inside_the_daily_grace(world):
    world.sender.script = [EmailRateLimitError("slow down")] * 3  # 4th attempt succeeds
    add_subscription()
    for offset in RETRY_TICKS:
        world.tick(at=DUE + offset)
    assert world.deliveries()[0]["status"] == "sent" and len(world.sender.sent) == 4


# ======================================================================
# Stage 4 fixes: a worker that lost its claim never freezes or sends
# ======================================================================


def test_worker_whose_claim_was_taken_over_does_not_freeze_or_send(world):
    add_subscription()

    async def another_worker_reclaims():
        await sql("UPDATE digest_deliveries SET lease_until = lease_until + interval '1 second'")

    world.gen.hook = another_worker_reclaims
    result = world.tick(at=DUE + timedelta(minutes=1))
    assert result.outcomes["lease_lost"] == 1
    d = world.deliveries()[0]
    assert (d["status"], d["html"], d["attempts"]) == ("sending", None, 0)  # untouched for the owner
    assert world.sender.sent == []


def test_lease_that_expires_during_a_slow_build_is_recovered_and_sent_once(world):
    add_subscription()

    async def slow_build():
        world.now = world.now + timedelta(minutes=11)  # longer than the 10-minute lease

    world.gen.hook = slow_build
    assert world.tick(at=DUE + timedelta(minutes=1)).outcomes["lease_lost"] == 1
    assert world.sender.sent == [] and world.deliveries()[0]["html"] is None
    world.gen.hook = None
    result = world.tick(at=DUE + timedelta(minutes=13))
    assert result.recovered == 1 and world.deliveries()[0]["status"] == "sent"
    assert len(world.sender.sent) == 1


def test_lease_lost_right_before_sending_does_not_send(world):
    """Payload already frozen (a retry): the clock passes the lease between claim and send."""
    queue_one(world, EmailRateLimitError("slow down"))
    world.now = DUE + timedelta(minutes=7)

    async def run():
        db_engine = create_async_engine(TEST_DATABASE_URL, poolclass=NullPool)
        try:
            engine = world.engine(create_sessionmaker(db_engine))
            original = engine._skip_reason

            def skip_reason_then_time_passes(*args):
                world.now = world.now + timedelta(minutes=11)
                return original(*args)

            engine._skip_reason = skip_reason_then_time_passes
            return await engine.tick()
        finally:
            await db_engine.dispose()

    result = asyncio.run(run())
    assert result.outcomes["lease_lost"] == 1
    d = world.deliveries()[0]
    assert (d["status"], d["attempts"], d["uncertain"]) == ("sending", 1, False)  # no new attempt recorded
    assert len(world.sender.sent) == 1
