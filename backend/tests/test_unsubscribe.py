"""Step D stage 3: unsubscribe links and headers, delivery history, delivery_active.

Uses the stage 2 fake world (fake PubMed, Gemini and email sender; no real email)
plus the HTTP API on the PostgreSQL test database.
"""

import hashlib
import logging
import re
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import app
from app.services.auth import SlidingWindowLimiter
from app.services.email import EmailRateLimitError, EmailTimeoutError
from tests.conftest import run_db
from tests.test_delivery import DUE, KEY, ME, World, add_subscription, next_run

TOKEN_RE = re.compile(r"token=([A-Za-z0-9_-]{43})")
INVALID = "This unsubscribe link is invalid or no longer exists."


@pytest.fixture
def web(db_client):
    """db_client + a fresh stage 2 world (db_client already emptied the tables)."""
    world = World()
    yield world, db_client
    app.dependency_overrides.clear()


def token_of(message) -> str:
    return TOKEN_RE.search(message.html).group(1)


def send_one(world: World, sub_email: str = ME, at=DUE + timedelta(minutes=1), **sub_fields) -> tuple[str, str]:
    sub = add_subscription(sub_email, **sub_fields)
    world.tick(at=at)
    return sub, token_of(world.sender.sent[-1][0])


def anonymous() -> TestClient:
    """A browser or mail server with no session cookie and no CSRF header."""
    return TestClient(app, base_url="http://localhost")


def sub_state(sub: str):
    return run_db(
        "SELECT email_enabled, unsubscribed_at IS NOT NULL, next_run_at FROM research_subscriptions WHERE id = :s",
        {"s": sub},
    )[0]


# ======================================================================
# the link and headers in scheduled emails
# ======================================================================


def test_scheduled_email_has_a_link_and_headers_and_only_the_hash_is_stored(web):
    world, _ = web
    sub, token = send_one(world)
    message = world.sender.sent[0][0]
    assert f"http://localhost:3000/unsubscribe?token={token}" in message.html
    assert f"Unsubscribe from this topic: http://localhost:3000/unsubscribe?token={token}" in message.text
    assert "http://localhost:3000/account" in message.html
    assert message.headers == {"List-Unsubscribe": f"<http://localhost:8010/api/unsubscribe/one-click?token={token}>"}

    stored_hash, html, text_, headers = run_db(
        "SELECT unsubscribe_token_hash, email_html, email_text, email_headers::text FROM digest_deliveries"
    )[0]
    assert stored_hash == hashlib.sha256(token.encode()).hexdigest()
    # The delivery is final, so the stored copy no longer contains the token.
    assert token not in html and token not in text_ and token not in headers
    assert "token=removed" in html


def test_one_click_header_is_added_only_for_https(web):
    world, _ = web
    world.configure(public_api_url="https://api.research.example", public_app_url="https://research.example")
    _, token = send_one(world)
    assert world.sender.sent[0][0].headers == {
        "List-Unsubscribe": f"<https://api.research.example/api/unsubscribe/one-click?token={token}>",
        "List-Unsubscribe-Post": "List-Unsubscribe=One-Click",
    }


def test_retries_resend_the_same_link_and_headers_then_scrub_them(web):
    world, _ = web
    world.sender.script = [EmailRateLimitError("slow down")]
    add_subscription()
    world.tick(at=DUE + timedelta(minutes=1))
    first = world.sender.sent[0][0]
    token = token_of(first)
    # While a retry is possible, the frozen email must keep the token (identical payload).
    assert token in run_db("SELECT email_html FROM digest_deliveries")[0][0]
    world.tick(at=DUE + timedelta(minutes=7))
    second = world.sender.sent[1][0]
    assert (second.html, second.headers) == (first.html, first.headers)
    assert token not in run_db("SELECT email_html FROM digest_deliveries")[0][0]


def test_every_email_gets_its_own_token_and_old_links_keep_working(web):
    world, _ = web
    sub, first_token = send_one(world)
    world.pubmed.pmids = ["103"]
    world.tick(at=DUE + timedelta(days=1, minutes=1))
    second_token = token_of(world.sender.sent[1][0])
    assert first_token != second_token
    response = anonymous().post("/api/unsubscribe", json={"token": first_token})
    assert response.status_code == 200 and response.json()["status"] == "unsubscribed"


def test_dry_runs_store_no_token(web):
    world, _ = web
    world.configure(digest_delivery_mode="dry_run")
    add_subscription()
    world.tick(at=DUE + timedelta(minutes=1))
    token_hash, headers, html = run_db("SELECT unsubscribe_token_hash, email_headers, email_html FROM digest_deliveries")[0]
    assert token_hash is None and headers is None
    assert "unsubscribe?token=dry-run-preview" in html


# ======================================================================
# the endpoints
# ======================================================================


def test_opening_the_link_changes_nothing(web):
    world, _ = web
    sub, token = send_one(world)
    response = anonymous().get("/api/unsubscribe", params={"token": token})
    assert response.json() == {"status": "subscribed", "topic": "leg sarcoma"}
    assert sub_state(sub)[:2] == (True, False)


def test_confirming_unsubscribes_without_login_and_is_idempotent(web):
    world, _ = web
    sub, token = send_one(world)
    browser = anonymous()
    first = browser.post("/api/unsubscribe", json={"token": token})
    assert first.status_code == 200 and first.json() == {"status": "unsubscribed", "topic": "leg sarcoma"}
    assert sub_state(sub) == (False, True, None)
    when = run_db("SELECT unsubscribed_at FROM research_subscriptions WHERE id = :s", {"s": sub})[0][0]

    again = browser.post("/api/unsubscribe", json={"token": token})
    assert again.json()["status"] == "already_unsubscribed"
    assert run_db("SELECT unsubscribed_at FROM research_subscriptions WHERE id = :s", {"s": sub})[0][0] == when
    assert browser.get("/api/unsubscribe", params={"token": token}).json()["status"] == "unsubscribed"


@pytest.mark.parametrize(
    "content",
    [
        {"data": {"List-Unsubscribe": "One-Click"}},  # application/x-www-form-urlencoded
        {"files": {"List-Unsubscribe": (None, "One-Click")}},  # multipart/form-data (RFC 8058's choice)
        {},
    ],
)
def test_one_click_post_works_without_cookies_or_csrf_and_returns_an_empty_200(web, content):
    world, _ = web
    sub, token = send_one(world)
    mail_server = anonymous()
    response = mail_server.post(
        "/api/unsubscribe/one-click", params={"token": token}, follow_redirects=False, **content
    )
    assert response.status_code == 200 and response.content == b""
    assert sub_state(sub)[:2] == (False, True)
    assert mail_server.post("/api/unsubscribe/one-click", params={"token": token}).status_code == 200


@pytest.mark.parametrize(
    "token",
    ["", "short", "x" * 42, "x" * 44, "!" * 43, "A" * 43],  # the last is well-formed but unknown
)
def test_invalid_tokens_get_one_generic_answer(web, token):
    browser = anonymous()
    assert browser.get("/api/unsubscribe", params={"token": token}).json() == {"detail": INVALID}
    assert browser.post("/api/unsubscribe", json={"token": token}).status_code == 404
    assert browser.post("/api/unsubscribe/one-click", params={"token": token}).status_code == 404


def test_missing_or_oversized_tokens_are_rejected(web):
    browser = anonymous()
    assert browser.get("/api/unsubscribe").status_code == 422
    assert browser.post("/api/unsubscribe", json={}).status_code == 422
    assert browser.post("/api/unsubscribe", json={"token": "a" * 101}).status_code == 422
    assert browser.post("/api/unsubscribe", json={"token": "a" * 43, "extra": 1}).status_code == 422


def test_a_token_only_affects_its_own_subscription(web):
    world, _ = web
    world.configure(digest_max_ai_calls_per_tick=10)
    mine, token = send_one(world, topic="leg sarcoma")
    other = add_subscription(topic="bone tumours", next_run=DUE + timedelta(days=5))
    anonymous().post("/api/unsubscribe", json={"token": token})
    assert sub_state(mine)[:2] == (False, True)
    assert sub_state(other)[:2] == (True, False)


def test_token_of_a_deleted_subscription_is_invalid(web):
    world, _ = web
    sub, token = send_one(world)
    run_db("DELETE FROM research_subscriptions WHERE id = :s", {"s": sub})
    assert anonymous().post("/api/unsubscribe", json={"token": token}).status_code == 404


def test_repeated_invalid_tokens_are_rate_limited_per_ip(web):
    world, _ = web
    _, token = send_one(world)
    app.state.unsubscribe_ip_limiter = SlidingWindowLimiter(3, 600)
    browser = anonymous()
    assert browser.get("/api/unsubscribe", params={"token": token}).status_code == 200  # real links don't count
    for _ in range(3):
        assert browser.post("/api/unsubscribe", json={"token": "B" * 43}).status_code == 404
    blocked = browser.post("/api/unsubscribe", json={"token": "B" * 43})
    assert blocked.status_code == 429 and int(blocked.headers["Retry-After"]) > 0


# ======================================================================
# after unsubscribing: queued deliveries and future runs
# ======================================================================


def test_unsubscribe_cancels_a_queued_delivery(web):
    world, _ = web
    sub, token = send_one(world)
    world.sender.script = [EmailRateLimitError("slow down")]
    world.pubmed.pmids = ["103"]
    world.tick(at=DUE + timedelta(days=1, minutes=1))  # day 2: refused once, queued for retry
    assert world.deliveries()[1]["status"] == "pending"

    anonymous().post("/api/unsubscribe", json={"token": token})
    day2 = world.deliveries()[1]
    assert (day2["status"], day2["error_code"]) == ("skipped_disabled", "unsubscribed")
    world.tick(at=DUE + timedelta(days=1, minutes=10))
    assert len(world.sender.sent) == 2  # the day-2 retry never happened


def test_unsubscribe_keeps_a_possibly_sent_delivery_as_needs_review(web):
    world, _ = web
    sub, token = send_one(world)
    world.sender.script = [EmailTimeoutError("timeout", retryable=True, outcome_unknown=True)]
    world.pubmed.pmids = ["103"]
    world.tick(at=DUE + timedelta(days=1, minutes=1))
    anonymous().post("/api/unsubscribe/one-click", params={"token": token})
    day2 = world.deliveries()[1]
    assert (day2["status"], day2["error_code"]) == ("needs_review", "unsubscribed")


def test_unsubscribed_subscriptions_never_send_again(web):
    world, _ = web
    sub, token = send_one(world)
    anonymous().post("/api/unsubscribe", json={"token": token})
    for day in range(1, 5):
        world.pubmed.pmids = [str(200 + day)]
        world.tick(at=DUE + timedelta(days=day, minutes=1))
    assert len(world.sender.sent) == 1 and len(world.deliveries()) == 1
    assert next_run(sub) is None


def test_turning_email_back_on_in_the_account_resubscribes(web):
    world, client = web
    client.post("/api/auth/register", json={"email": ME, "password": "correct horse battery"})
    body = {"topic": "leg sarcoma", "frequency": "daily", "delivery_time": "09:00", "time_zone": "UTC",
            "paper_count": 5, "reading_level": "college", "email_enabled": True}
    sub = client.post("/api/subscriptions", json=body).json()["id"]
    run_db("UPDATE research_subscriptions SET next_run_at = :d WHERE id = :s", {"d": DUE, "s": sub})
    world.tick(at=DUE + timedelta(minutes=1))
    token = token_of(world.sender.sent[0][0])
    anonymous().post("/api/unsubscribe", json={"token": token})
    listed = client.get("/api/subscriptions").json()[0]
    assert listed["unsubscribed_at"] is not None and listed["email_enabled"] is False and listed["next_run_at"] is None

    client.put(f"/api/subscriptions/{sub}", json=body)
    listed = client.get("/api/subscriptions").json()[0]
    assert listed["unsubscribed_at"] is None and listed["next_run_at"] is not None


def test_tokens_never_reach_the_logs(web, caplog):
    world, _ = web
    with caplog.at_level(logging.DEBUG):
        sub, token = send_one(world)
        anonymous().post("/api/unsubscribe", json={"token": token})
        anonymous().post("/api/unsubscribe/one-click", params={"token": token})
    assert token not in caplog.text and ME not in caplog.text and KEY not in caplog.text


# ======================================================================
# history and delivery_active in the API
# ======================================================================


def signed_in(client, email: str = ME):
    response = client.post("/api/auth/register", json={"email": email, "password": "correct horse battery"})
    assert response.status_code == 201


def test_history_requires_login_and_shows_only_your_own_runs(web):
    world, client = web
    world.configure(email_test_recipients=f"{ME},other@example.org", digest_max_ai_calls_per_tick=10)
    assert client.get("/api/digests/deliveries").status_code == 401
    signed_in(client)
    mine = add_subscription(ME)
    add_subscription("other@example.org")
    world.tick(at=DUE + timedelta(minutes=1))

    rows = client.get("/api/digests/deliveries").json()
    assert len(rows) == 1
    row = rows[0]
    assert (row["subscription_id"], row["topic"], row["status"], row["papers_count"]) == (mine, "leg sarcoma", "sent", 2)
    assert row["sent_at"] and row["mode"] == "allowlist" and row["reason"] is None
    # No email content, addresses or tokens in the history.
    assert not {"email_html", "email_to", "email_headers", "unsubscribe_token_hash"} & set(row)


def test_history_shows_skips_failures_and_reviews_newest_first(web):
    world, client = web
    signed_in(client)
    add_subscription(ME)
    world.sender.script = [EmailTimeoutError("timeout", retryable=True, outcome_unknown=True)] * 10
    world.configure(digest_safe_retry_hours=1)
    world.tick(at=DUE + timedelta(minutes=1))
    world.tick(at=DUE + timedelta(hours=2))  # -> needs_review
    world.tick(at=DUE + timedelta(days=1, hours=8))  # day 2 overdue beyond the grace period -> skipped_missed
    statuses = [(r["status"], r["reason"]) for r in client.get("/api/digests/deliveries").json()]
    assert statuses == [("skipped_missed", "missed"), ("needs_review", "idempotency_window_expired")]


def test_history_can_be_filtered_by_subscription(web):
    world, client = web
    world.configure(digest_max_ai_calls_per_tick=10)
    signed_in(client)
    first = add_subscription(ME, topic="leg sarcoma")
    add_subscription(ME, topic="bone tumours")
    world.tick(at=DUE + timedelta(minutes=1))
    assert len(client.get("/api/digests/deliveries").json()) == 2
    only = client.get("/api/digests/deliveries", params={"subscription_id": first}).json()
    assert [r["topic"] for r in only] == ["leg sarcoma"]


@pytest.mark.parametrize(
    ("overrides", "active"),
    [
        ({}, False),  # defaults: mode off, scheduler off
        ({"digest_delivery_mode": "allowlist"}, False),  # scheduler not running
        ({"digest_scheduler_enabled": True, "digest_delivery_mode": "dry_run"}, False),
        ({"digest_scheduler_enabled": True, "digest_delivery_mode": "allowlist"}, True),
        ({"digest_scheduler_enabled": True, "digest_delivery_mode": "allowlist", "email_test_recipients": "x@y.org"},
         False),  # not allowlisted
    ],
)
def test_delivery_active_reflects_what_the_scheduler_would_really_do(web, overrides, active):
    _, client = web
    from tests.conftest import make_settings

    values = {"email_enabled": True, "resend_api_key": KEY, "email_test_recipients": ME, **overrides}
    settings = make_settings(**values)
    app.dependency_overrides[get_settings] = lambda: settings
    signed_in(client)
    body = {"topic": "leg sarcoma", "frequency": "daily", "delivery_time": "09:00", "time_zone": "UTC",
            "paper_count": 5, "reading_level": "college", "email_enabled": True}
    created = client.post("/api/subscriptions", json=body).json()
    assert created["delivery_active"] is active
    status = client.get("/api/digests/email-status").json()
    assert status["automatic_delivery_active"] is active
    assert status["delivery_mode"] == settings.digest_delivery_mode
    # Email off for this subscription -> never active.
    off = client.put(f"/api/subscriptions/{created['id']}", json={**body, "email_enabled": False}).json()
    assert off["delivery_active"] is False


# ======================================================================
# Stage 4 review: no final delivery keeps a token, however it ended
# ======================================================================

TOKEN_IN_STORED = (
    "SELECT status, error_code FROM digest_deliveries WHERE status NOT IN ('pending', 'sending') AND ("
    " email_html ~ 'token=[A-Za-z0-9_-]{43}' OR email_text ~ 'token=[A-Za-z0-9_-]{43}'"
    " OR email_headers::text ~ 'token=[A-Za-z0-9_-]{43}')"
)


def _build_then_fail_once(world, error):
    """Day 1 sent (gives us a link), day 2 built with its own token and left queued."""
    sub, token = send_one(world)
    world.sender.script = [error]
    world.pubmed.pmids = ["103"]
    world.tick(at=DUE + timedelta(days=1, minutes=1))
    assert world.deliveries()[1]["status"] == "pending"
    assert TOKEN_RE.search(run_db("SELECT email_html FROM digest_deliveries ORDER BY scheduled_for")[1][0])
    return sub, token


@pytest.mark.parametrize(
    ("scenario", "expected"),
    [
        ("unsubscribe_link", ("skipped_disabled", "unsubscribed")),
        ("unsubscribe_link_uncertain", ("needs_review", "unsubscribed")),
        ("api_email_off", ("skipped_disabled", "email_off")),
        ("api_schedule_change", ("skipped_disabled", "schedule_changed")),
        ("recheck_email_off", ("skipped_disabled", "email_off")),
        ("switched_to_dry_run", ("skipped_disabled", "mode_changed")),
        ("permanent_failure", ("failed", "resend_403")),
        ("retries_exhausted_uncertain", ("needs_review", "timeout")),
        ("window_expired", ("needs_review", "idempotency_window_expired")),
        ("idempotency_conflict", ("needs_review", "idempotency_conflict")),
    ],
)
def test_every_final_state_scrubs_the_stored_token(web, scenario, expected):
    from app.services.email import EmailRejectedError

    world, client = web
    timeout = EmailTimeoutError("timeout", retryable=True, outcome_unknown=True)
    later = DUE + timedelta(days=1, minutes=10)
    if scenario == "unsubscribe_link":
        _, token = _build_then_fail_once(world, EmailRateLimitError("slow"))
        anonymous().post("/api/unsubscribe", json={"token": token})
    elif scenario == "unsubscribe_link_uncertain":
        _, token = _build_then_fail_once(world, timeout)
        anonymous().post("/api/unsubscribe/one-click", params={"token": token})
    elif scenario in ("api_email_off", "api_schedule_change"):
        from app.routers.deps import get_utc_now

        app.dependency_overrides[get_utc_now] = lambda: later
        signed_in(client)
        body = {"topic": "leg sarcoma", "frequency": "daily", "delivery_time": "09:00", "time_zone": "UTC",
                "paper_count": 5, "reading_level": "college", "email_enabled": True}
        sub = client.post("/api/subscriptions", json=body).json()["id"]
        run_db("UPDATE research_subscriptions SET next_run_at = :d WHERE id = :s", {"d": DUE, "s": sub})
        world.sender.script = [EmailRateLimitError("slow")]
        world.tick(at=DUE + timedelta(minutes=1))
        change = {"email_enabled": False} if scenario == "api_email_off" else {"delivery_time": "10:00"}
        client.put(f"/api/subscriptions/{sub}", json={**body, **change})
    elif scenario == "recheck_email_off":
        sub, _ = _build_then_fail_once(world, EmailRateLimitError("slow"))
        run_db("UPDATE research_subscriptions SET email_enabled = false WHERE id = :s", {"s": sub})
        world.tick(at=later)
    elif scenario == "switched_to_dry_run":
        _build_then_fail_once(world, EmailRateLimitError("slow"))
        world.configure(digest_delivery_mode="dry_run")
        world.tick(at=later)
    elif scenario == "permanent_failure":
        send_one(world)
        world.sender.script = [EmailRejectedError("no", code="resend_403")]
        world.pubmed.pmids = ["103"]
        world.tick(at=DUE + timedelta(days=1, minutes=1))
    elif scenario == "retries_exhausted_uncertain":
        send_one(world)
        world.sender.script = [timeout] * 10
        world.pubmed.pmids = ["103"]
        for minutes in (1, 7, 38, 159):  # real backoff: 5 min, 30 min, 2 h
            world.tick(at=DUE + timedelta(days=1, minutes=minutes))
    elif scenario == "window_expired":
        world.configure(digest_safe_retry_hours=1)
        _build_then_fail_once(world, timeout)
        world.tick(at=DUE + timedelta(days=1, hours=2))
    elif scenario == "idempotency_conflict":
        send_one(world)
        world.sender.script = [EmailRejectedError("dup", code="idempotency_conflict", outcome_unknown=True)]
        world.pubmed.pmids = ["103"]
        world.tick(at=DUE + timedelta(days=1, minutes=1))

    final = [(d["status"], d["error_code"]) for d in world.deliveries()]
    assert expected in final, final
    assert run_db(TOKEN_IN_STORED) == []  # no final row anywhere still holds a usable token
