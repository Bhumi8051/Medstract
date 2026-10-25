"""Step D stage 4: operations - the digests CLI (status, review, resolve) and the
scheduler heartbeat in GET /health. Uses the PostgreSQL test database; nothing is sent.
"""

import asyncio
import logging
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

import app.jobs.digests as cli
from app.main import app
from app.scheduler import DigestScheduler
from app.services.delivery import TickResult
from tests.conftest import ACCOUNT_TABLES, TEST_DATABASE_URL, make_settings, run_db
from tests.test_delivery import add_subscription

TOKEN = "T" * 43


@pytest.fixture
def ops(migrated_test_db, monkeypatch):
    """The CLI pointed at the test database (never the app database in backend/.env)."""
    run_db(f"TRUNCATE {ACCOUNT_TABLES} RESTART IDENTITY CASCADE")
    state = {"settings": make_settings(database_url=TEST_DATABASE_URL)}
    monkeypatch.setattr(cli, "get_settings", lambda: state["settings"])

    def use(**overrides):
        state["settings"] = make_settings(database_url=TEST_DATABASE_URL, **overrides)

    return use


def delivery(sub: str, status: str, *, when=None, **fields) -> str:
    user = run_db("SELECT user_id FROM research_subscriptions WHERE id = :s", {"s": sub})[0][0]
    delivery_id = str(uuid.uuid4())
    cols = "".join(f", {k}" for k in fields)
    vals = "".join(f", :{k}" for k in fields)
    run_db(
        f"INSERT INTO digest_deliveries (id, subscription_id, user_id, scheduled_for, status, next_attempt_at,"
        f" idempotency_key{cols}) VALUES (:id, :s, :u, :at, :st, :at, :k{vals})",
        {"id": delivery_id, "s": sub, "u": user, "at": when or datetime.now(UTC) - timedelta(hours=1), "st": status,
         "k": f"digest-{delivery_id}", **fields},
    )
    return delivery_id


def needs_review(sub: str) -> str:
    return delivery(
        sub, "needs_review", attempts=2, outcome_uncertain=True, error_code="idempotency_window_expired",
        first_attempt_at=datetime(2026, 10, 26, 9, 1, tzinfo=UTC), email_to="ada@example.org",
        email_subject="Research digest: leg sarcoma", email_html=f"<a href='x?token={TOKEN}'>u</a>",
        paper_pmids=["101", "102"],
    )


# ---------------------------------------------------------------- status


def test_status_reports_configuration_without_secrets(ops, capsys):
    ops(resend_api_key="re_test_SECRET_key_123456", email_enabled=True, email_test_recipients="ada@example.org")
    assert asyncio.run(cli.status()) == 0
    out = capsys.readouterr().out
    assert "DIGEST_DELIVERY_MODE=off (effective: off) | DIGEST_SCHEDULER_ENABLED=false" in out
    assert "RESEND_API_KEY set" in out and "re_test_SECRET" not in out
    assert "1 address(es)" in out and "ada@example.org" not in out
    assert "one-click unsubscribe header: off, needs https" in out
    assert "No problems found." in out


def test_status_diagnoses_problems_with_actions(ops, capsys):
    ops(digest_delivery_mode="allowlist")  # but email isn't set up
    sub = add_subscription(next_run=datetime.now(UTC) - timedelta(hours=2))
    needs_review(sub)
    delivery(sub, "failed", error_code="resend_403", when=datetime.now(UTC) - timedelta(days=2))
    delivery(sub, "sending", lease_until=datetime.now(UTC) - timedelta(minutes=5), when=datetime.now(UTC) - timedelta(days=3))
    asyncio.run(cli.status())
    out = capsys.readouterr().out
    assert "Mode is allowlist but email isn't fully set up" in out
    assert "1 delivery(ies) need review" in out and "app.jobs.digests review" in out
    assert "1 failed in the last 7 days (resend_403)" in out and "onboarding@resend.dev" in out
    assert "stuck in 'sending'" in out
    assert "overdue, but the effective mode is off" in out
    assert TOKEN not in out


def test_status_says_when_no_scheduler_is_ticking(ops, capsys):
    ops(digest_delivery_mode="dry_run")
    add_subscription(next_run=datetime.now(UTC) - timedelta(hours=1))
    asyncio.run(cli.status())
    assert "no scheduler seems to be ticking" in capsys.readouterr().out


# ---------------------------------------------------------------- review


def test_review_lists_details_with_a_masked_address_and_no_token(ops, capsys):
    sub = add_subscription()
    review_id = needs_review(sub)
    asyncio.run(cli.review(show_all=False))
    out = capsys.readouterr().out
    assert review_id in out and "Research digest: leg sarcoma" in out
    assert "a***@example.org" in out and "ada@example.org" not in out
    assert TOKEN not in out
    assert "NEVER resent automatically" in out and "resend.com/emails" in out


def test_review_with_nothing_to_review(ops, capsys):
    asyncio.run(cli.review(show_all=False))
    assert "No deliveries need review." in capsys.readouterr().out


# ---------------------------------------------------------------- resolve


def test_resolve_not_delivered_marks_failed_and_keeps_papers_eligible(ops, capsys):
    sub = add_subscription()
    review_id = needs_review(sub)
    assert asyncio.run(cli.resolve(review_id, delivered=False, message_id=None, assume_yes=True)) == 0
    status, code, uncertain, html = run_db(
        "SELECT status, error_code, outcome_uncertain, email_html FROM digest_deliveries WHERE id = :d", {"d": review_id}
    )[0]
    assert (status, code, uncertain) == ("failed", "review_not_delivered", False)
    assert TOKEN not in html
    assert run_db("SELECT count(*) FROM digest_sent_papers")[0][0] == 0  # papers can appear in the next digest
    assert "No email was sent" in capsys.readouterr().out


def test_resolve_delivered_records_it_as_sent(ops):
    sub = add_subscription()
    review_id = needs_review(sub)
    assert asyncio.run(cli.resolve(review_id, delivered=True, message_id="re_msg_123", assume_yes=True)) == 0
    status, message, sent_at = run_db(
        "SELECT status, provider_message_id, sent_at FROM digest_deliveries WHERE id = :d", {"d": review_id}
    )[0]
    assert (status, message, sent_at) == ("sent", "re_msg_123", datetime(2026, 10, 26, 9, 1, tzinfo=UTC))
    assert {r[0] for r in run_db("SELECT pmid FROM digest_sent_papers")} == {"101", "102"}
    assert run_db("SELECT last_sent_at FROM research_subscriptions WHERE id = :s", {"s": sub})[0][0] == sent_at


def test_resolve_refuses_anything_but_needs_review(ops, capsys):
    sub = add_subscription()
    sent = delivery(sub, "pending")
    assert asyncio.run(cli.resolve(sent, delivered=False, message_id=None, assume_yes=True)) == 1
    assert run_db("SELECT status FROM digest_deliveries WHERE id = :d", {"d": sent})[0][0] == "pending"
    assert "not 'needs_review'; nothing changed" in capsys.readouterr().out


def test_resolve_input_checks(ops, capsys, monkeypatch):
    sub = add_subscription()
    review_id = needs_review(sub)
    assert asyncio.run(cli.resolve("nope", delivered=False, message_id=None, assume_yes=True)) == 2
    assert asyncio.run(cli.resolve(review_id, delivered=True, message_id=None, assume_yes=True)) == 2
    monkeypatch.setattr("builtins.input", lambda _: "no")
    assert asyncio.run(cli.resolve(review_id, delivered=False, message_id=None, assume_yes=False)) == 1
    assert run_db("SELECT status FROM digest_deliveries WHERE id = :d", {"d": review_id})[0][0] == "needs_review"


def test_cli_argument_parsing_requires_a_verdict():
    with pytest.raises(SystemExit):
        cli.main(["resolve", str(uuid.uuid4())])
    with pytest.raises(SystemExit):
        cli.main(["resolve", str(uuid.uuid4()), "--delivered", "--not-delivered"])


# ---------------------------------------------------------------- scheduler heartbeat


class FakeEngine:
    """Stands in for the database engine: run_locked_tick is patched below."""


def make_scheduler(monkeypatch, outcome):
    async def fake_tick(engine, delivery):
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome

    monkeypatch.setattr("app.scheduler.run_locked_tick", fake_tick)
    scheduler = DigestScheduler(FakeEngine(), None, interval_seconds=60)
    scheduler.started_at = datetime.now(UTC)
    return scheduler


def test_heartbeat_after_a_good_tick(monkeypatch):
    result = TickResult(mode="dry_run", processed=1)
    result.outcomes["dry_run"] = 1
    scheduler = make_scheduler(monkeypatch, result)
    asyncio.run(scheduler.run_once())
    health = scheduler.health()
    assert health["last_success_at"] == health["last_tick_at"] and health["last_error"] is None
    assert "dry_run=1" in health["last_summary"] and health["consecutive_failures"] == 0


def test_heartbeat_counts_failures_and_logs_them(monkeypatch, caplog):
    scheduler = make_scheduler(monkeypatch, ConnectionRefusedError("db down at postgresql://u:pw@h/db"))
    with caplog.at_level(logging.WARNING):
        asyncio.run(scheduler.run_once())
        asyncio.run(scheduler.run_once())
    health = scheduler.health()
    assert health["consecutive_failures"] == 2 and health["last_error"] == "ConnectionRefusedError"
    assert health["last_success_at"] is None
    assert "Digest scheduler tick failed (ConnectionRefusedError); 2 in a row" in caplog.text
    assert "pw@" not in caplog.text  # only the type name is recorded


def test_ticks_that_need_attention_are_logged_as_warnings(monkeypatch, caplog):
    result = TickResult(mode="allowlist", processed=1)
    result.outcomes["needs_review"] = 1
    scheduler = make_scheduler(monkeypatch, result)
    with caplog.at_level(logging.WARNING):
        asyncio.run(scheduler.run_once())
    assert "Digest tick needs attention" in caplog.text and "needs_review=1" in caplog.text


def test_heartbeat_goes_stale_when_ticks_stop(monkeypatch):
    scheduler = make_scheduler(monkeypatch, TickResult(mode="dry_run"))

    async def started():
        scheduler.start()
        await asyncio.sleep(0.05)
        health_now = scheduler.health()
        health_later = scheduler.health(now=datetime.now(UTC) + timedelta(minutes=10))
        await scheduler.stop()
        return health_now, health_later

    fresh, later = asyncio.run(started())
    assert fresh["running"] is True and fresh["stale"] is False
    assert later["stale"] is True


def test_health_reports_the_scheduler_off_by_default():
    with TestClient(app) as client:
        body = client.get("/health").json()
    assert body["status"] == "ok"
    assert body["digest_scheduler"] == {"enabled": False, "mode": "off", "running": False, "stale": False}
