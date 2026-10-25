"""Step D stage 1 against PostgreSQL: next_run_at upkeep, delivery-table constraints,
concurrency on the per-run unique constraint, and migration rollback/re-upgrade.

Nothing here schedules or sends anything; there is no scheduler yet.
"""

import asyncio
import uuid
from datetime import UTC, datetime

import pytest
from alembic import command
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from app.main import app
from app.routers.deps import get_utc_now
from tests.conftest import ACCOUNT_TABLES, TEST_DATABASE_URL, alembic_config, run_db

PASSWORD = "correct horse battery"
STAGE3_REVISION = "1e29bb4ebd5b"  # unsubscribe tokens per delivery (head)
STAGE2_REVISION = "b4bb321bb07f"  # digest delivery payload
STAGE1_REVISION = "96d41bf41bda"
PREVIOUS_REVISION = "bd806695a174"
PAYLOAD_COLUMNS = {"outcome_uncertain", "mode", "email_to", "email_subject", "email_html", "email_text", "paper_pmids"}
# Saturday 24 Oct 2026, 12:00 UTC (08:00 EDT).
NOW = datetime(2026, 10, 24, 12, 0, tzinfo=UTC)
BODY = {
    "topic": "breast cancer",
    "frequency": "weekly",
    "weekday": 0,  # Sunday
    "delivery_time": "00:00",
    "time_zone": "America/New_York",
    "paper_count": 10,
    "reading_level": "college",
    "email_enabled": True,
}


@pytest.fixture
def api(db_client):
    clock = {"now": NOW}
    app.dependency_overrides[get_utc_now] = lambda: clock["now"]
    response = db_client.post("/api/auth/register", json={"email": "ada@example.org", "password": PASSWORD})
    assert response.status_code == 201

    class Api:
        client = db_client
        time = clock

        @staticmethod
        def create(**fields) -> str:
            r = db_client.post("/api/subscriptions", json={**BODY, **fields})
            assert r.status_code == 201, r.text
            return r.json()["id"]

        @staticmethod
        def update(sub_id: str, **fields):
            r = db_client.put(f"/api/subscriptions/{sub_id}", json={**BODY, **fields})
            assert r.status_code == 200, r.text
            return r

        @staticmethod
        def next_run(sub_id: str) -> datetime | None:
            return run_db("SELECT next_run_at FROM research_subscriptions WHERE id = :id", {"id": sub_id})[0][0]

    yield Api
    app.dependency_overrides.clear()


# ---------------------------------------------------------------- next_run_at upkeep


def test_creating_a_subscription_computes_the_next_run(api):
    sub = api.create()
    # Next Sunday 00:00 EDT after Sat 08:00 EDT = Sun 25 Oct 04:00 UTC.
    assert api.next_run(sub) == datetime(2026, 10, 25, 4, 0, tzinfo=UTC)


def test_email_off_means_no_next_run(api):
    assert api.next_run(api.create(email_enabled=False)) is None


def test_turning_email_off_and_on_again(api):
    sub = api.create()
    api.update(sub, email_enabled=False)
    assert api.next_run(sub) is None
    api.time["now"] = datetime(2026, 10, 26, 12, 0, tzinfo=UTC)  # Monday
    api.update(sub, email_enabled=True)
    assert api.next_run(sub) == datetime(2026, 11, 1, 4, 0, tzinfo=UTC)  # computed from the new "now"


@pytest.mark.parametrize(
    ("change", "expected"),
    [
        ({"weekday": 1}, datetime(2026, 10, 26, 4, 0, tzinfo=UTC)),  # Monday 00:00 EDT
        ({"delivery_time": "09:30"}, datetime(2026, 10, 25, 13, 30, tzinfo=UTC)),  # Sunday 09:30 EDT
        ({"time_zone": "Asia/Kolkata"}, datetime(2026, 10, 24, 18, 30, tzinfo=UTC)),  # Sunday 00:00 IST
        ({"frequency": "daily", "weekday": None}, datetime(2026, 10, 25, 4, 0, tzinfo=UTC)),  # tonight 00:00 EDT
        ({"frequency": "monthly", "weekday": None, "month_day": 3}, datetime(2026, 11, 3, 5, 0, tzinfo=UTC)),  # EST
    ],
)
def test_schedule_changes_recompute_the_next_run(api, change, expected):
    sub = api.create()
    api.update(sub, **change)
    assert api.next_run(sub) == expected


@pytest.mark.parametrize(
    "change", [{"topic": "breast cancer screening"}, {"paper_count": 5}, {"reading_level": "phd"}, {}]
)
def test_other_edits_keep_the_next_run(api, change):
    sub = api.create()
    before = api.next_run(sub)
    api.time["now"] = datetime(2026, 10, 24, 20, 0, tzinfo=UTC)  # later the same day
    api.update(sub, **change)
    assert api.next_run(sub) == before


def test_unsubscribed_subscriptions_have_no_next_run_until_re_enabled(api):
    sub = api.create()
    # What stage 3's unsubscribe link will do:
    run_db(
        "UPDATE research_subscriptions SET email_enabled = false, unsubscribed_at = now(), next_run_at = NULL "
        "WHERE id = :id",
        {"id": sub},
    )
    api.update(sub, email_enabled=False, paper_count=5)
    assert api.next_run(sub) is None
    # Turning email back on in the app re-subscribes.
    api.update(sub, email_enabled=True)
    row = run_db("SELECT next_run_at, unsubscribed_at FROM research_subscriptions WHERE id = :id", {"id": sub})[0]
    assert row == (datetime(2026, 10, 25, 4, 0, tzinfo=UTC), None)


def test_api_shows_the_schedule_but_delivery_is_inactive_by_default(api):
    sub = api.create()
    data = api.client.get(f"/api/subscriptions/{sub}").json()
    assert data["next_run_at"] == "2026-10-25T04:00:00Z"
    assert (data["last_sent_at"], data["unsubscribed_at"], data["delivery_active"]) == (None, None, False)


# ---------------------------------------------------------------- delivery table constraints


def make_subscription() -> tuple[str, str]:
    """A user and a subscription inserted directly (no API), for constraint tests."""
    user_id, sub_id = str(uuid.uuid4()), str(uuid.uuid4())
    run_db(
        "INSERT INTO users (id, email, password_hash) VALUES (:id, :email, 'x')",
        {"id": user_id, "email": f"{user_id}@example.org"},
    )
    run_db(
        "INSERT INTO research_subscriptions (id, user_id, topic, topic_key, frequency, delivery_time, time_zone,"
        " paper_count, reading_level) VALUES (:id, :user, 'topic', 'topic', 'daily', '09:00', 'UTC', 5, 'college')",
        {"id": sub_id, "user": user_id},
    )
    return user_id, sub_id


INSERT_DELIVERY = (
    "INSERT INTO digest_deliveries (id, subscription_id, user_id, scheduled_for, next_attempt_at, idempotency_key{cols})"
    " VALUES (:id, :sub, :user, :at, :at, :key{vals}){suffix}"
)


def insert_delivery(sub: str, user: str, at: datetime, *, suffix: str = "", **extra):
    cols = "".join(f", {k}" for k in extra)
    vals = "".join(f", :{k}" for k in extra)
    delivery_id = str(uuid.uuid4())
    run_db(
        INSERT_DELIVERY.format(cols=cols, vals=vals, suffix=suffix),
        {"id": delivery_id, "sub": sub, "user": user, "at": at, "key": f"digest-{delivery_id}", **extra},
    )
    return delivery_id


@pytest.fixture
def clean_db(migrated_test_db):
    run_db(f"TRUNCATE {ACCOUNT_TABLES} RESTART IDENTITY CASCADE")
    yield


def test_a_scheduled_run_can_only_exist_once(clean_db):
    user, sub = make_subscription()
    insert_delivery(sub, user, NOW)
    with pytest.raises(IntegrityError, match="uq_digest_deliveries_subscription_run"):
        insert_delivery(sub, user, NOW)
    insert_delivery(sub, user, datetime(2026, 10, 25, 12, 0, tzinfo=UTC))  # a different run is fine


def test_concurrent_schedulers_create_exactly_one_delivery(clean_db):
    """Twelve simultaneous INSERT ... ON CONFLICT DO NOTHING for the same run -> one row."""
    user, sub = make_subscription()

    async def race():
        engine = create_async_engine(TEST_DATABASE_URL, poolclass=NullPool)
        start = asyncio.Event()

        async def one():
            delivery_id = str(uuid.uuid4())
            async with engine.begin() as conn:
                await start.wait()
                result = await conn.execute(
                    text(
                        INSERT_DELIVERY.format(cols="", vals="", suffix=" ON CONFLICT DO NOTHING RETURNING id")
                    ),
                    {"id": delivery_id, "sub": sub, "user": user, "at": NOW, "key": f"digest-{delivery_id}"},
                )
                return result.first() is not None

        try:
            tasks = [asyncio.create_task(one()) for _ in range(12)]
            await asyncio.sleep(0.05)
            start.set()
            return await asyncio.gather(*tasks)
        finally:
            await engine.dispose()

    created = asyncio.run(race())
    assert sum(created) == 1
    assert run_db("SELECT count(*) FROM digest_deliveries")[0][0] == 1


@pytest.mark.parametrize(
    ("extra", "constraint"),
    [
        ({"status": "bogus"}, "ck_digest_deliveries_status"),
        ({"status": "sent"}, "ck_digest_deliveries_sent"),  # no provider id / sent_at
        ({"attempts": -1}, "ck_digest_deliveries_attempts"),
        ({"window_start": datetime(2026, 10, 25).date(), "window_end": datetime(2026, 10, 1).date()},
         "ck_digest_deliveries_window"),
    ],
)
def test_delivery_check_constraints(clean_db, extra, constraint):
    user, sub = make_subscription()
    with pytest.raises(IntegrityError, match=constraint):
        insert_delivery(sub, user, NOW, **extra)


def test_a_sent_delivery_needs_the_provider_id_and_time(clean_db):
    user, sub = make_subscription()
    insert_delivery(sub, user, NOW, status="sent", provider_message_id="msg_1", sent_at=NOW)


def test_sent_papers_are_unique_per_subscription_and_validated(clean_db):
    user, sub = make_subscription()
    delivery = insert_delivery(sub, user, NOW)
    insert = (
        "INSERT INTO digest_sent_papers (subscription_id, pmid, delivery_id, first_sent_at)"
        " VALUES (:sub, :pmid, :d, now())"
    )
    run_db(insert, {"sub": sub, "pmid": "12345", "d": delivery})
    with pytest.raises(IntegrityError, match="digest_sent_papers_pkey"):
        run_db(insert, {"sub": sub, "pmid": "12345", "d": delivery})
    with pytest.raises(IntegrityError, match="ck_digest_sent_papers_pmid"):
        run_db(insert, {"sub": sub, "pmid": "abc", "d": delivery})


def test_unsubscribe_token_hashes_are_unique(clean_db):
    user, sub = make_subscription()
    insert_delivery(sub, user, NOW, unsubscribe_token_hash="h1")
    with pytest.raises(IntegrityError, match="uq_digest_deliveries_unsubscribe_token"):
        insert_delivery(sub, user, datetime(2026, 10, 25, tzinfo=UTC), unsubscribe_token_hash="h1")


@pytest.mark.parametrize("delete", ["subscription", "user"])
def test_deleting_a_subscription_or_user_removes_its_history(clean_db, delete):
    user, sub = make_subscription()
    delivery = insert_delivery(sub, user, NOW)
    run_db(
        "INSERT INTO digest_sent_papers (subscription_id, pmid, delivery_id, first_sent_at) VALUES (:s, '1', :d, now())",
        {"s": sub, "d": delivery},
    )
    if delete == "subscription":
        run_db("DELETE FROM research_subscriptions WHERE id = :id", {"id": sub})
    else:
        run_db("DELETE FROM users WHERE id = :id", {"id": user})
    assert run_db("SELECT count(*) FROM digest_deliveries")[0][0] == 0
    assert run_db("SELECT count(*) FROM digest_sent_papers")[0][0] == 0


# ---------------------------------------------------------------- migration


def columns(table: str) -> set[str]:
    rows = run_db("SELECT column_name FROM information_schema.columns WHERE table_name = :t", {"t": table})
    return {r[0] for r in rows}


def test_step_d_migrations_roll_back_one_at_a_time_and_re_apply(clean_db, migrated_test_db):
    user, sub = make_subscription()
    run_db("UPDATE research_subscriptions SET next_run_at = now() WHERE id = :id", {"id": sub})
    delivery = insert_delivery(sub, user, NOW, status="dry_run", mode="dry_run", email_html="<p>x</p>")
    config = alembic_config(migrated_test_db)
    try:
        # Stage 3 rollback: the token column moves back to subscriptions (empty); history stays.
        command.downgrade(config, STAGE2_REVISION)
        assert not {"email_headers", "unsubscribe_token_hash"} & columns("digest_deliveries")
        assert "unsubscribe_token_hash" in columns("research_subscriptions")
        assert run_db("SELECT status FROM digest_deliveries WHERE id = :id", {"id": delivery}) == [("dry_run",)]

        # Stage 2 rollback: only the payload columns go; delivery history stays.
        command.downgrade(config, STAGE1_REVISION)
        assert run_db("SELECT version_num FROM alembic_version")[0][0] == STAGE1_REVISION
        assert not PAYLOAD_COLUMNS & columns("digest_deliveries")
        assert run_db("SELECT status FROM digest_deliveries WHERE id = :id", {"id": delivery}) == [("dry_run",)]

        # Stage 1 rollback: the Step D tables and columns go; Step A data stays.
        command.downgrade(config, PREVIOUS_REVISION)
        assert run_db("SELECT version_num FROM alembic_version")[0][0] == PREVIOUS_REVISION
        tables = {r[0] for r in run_db("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")}
        assert "digest_deliveries" not in tables and "digest_sent_papers" not in tables
        assert not {"next_run_at", "last_sent_at", "unsubscribed_at", "unsubscribe_token_hash"} & columns(
            "research_subscriptions"
        )
        # The subscription itself (Step A data) is untouched.
        assert run_db("SELECT topic, frequency FROM research_subscriptions WHERE id = :id", {"id": sub}) == [
            ("topic", "daily")
        ]

        command.upgrade(config, "head")
        assert run_db("SELECT version_num FROM alembic_version")[0][0] == STAGE3_REVISION
        assert PAYLOAD_COLUMNS | {"email_headers", "unsubscribe_token_hash"} <= columns("digest_deliveries")
        assert "unsubscribe_token_hash" not in columns("research_subscriptions")
        # New columns come back empty: existing rows are never back-filled by the migration.
        assert run_db(
            "SELECT next_run_at, last_sent_at, unsubscribed_at FROM research_subscriptions WHERE id = :id",
            {"id": sub},
        ) == [(None, None, None)]
        assert run_db("SELECT count(*) FROM digest_deliveries")[0][0] == 0
    finally:
        command.upgrade(config, "head")  # leave the test database at head for other tests


def test_stage3_migration_refuses_to_drop_a_used_token_column(clean_db, migrated_test_db):
    """The guard: if the old per-subscription column ever held a value, the upgrade stops."""
    config = alembic_config(migrated_test_db)
    _, sub = make_subscription()
    try:
        command.downgrade(config, STAGE2_REVISION)
        run_db("UPDATE research_subscriptions SET unsubscribe_token_hash = 'in-use' WHERE id = :id", {"id": sub})
        with pytest.raises(RuntimeError, match="refusing to drop"):
            command.upgrade(config, "head")
        assert run_db("SELECT version_num FROM alembic_version")[0][0] == STAGE2_REVISION  # nothing applied
        run_db("UPDATE research_subscriptions SET unsubscribe_token_hash = NULL WHERE id = :id", {"id": sub})
    finally:
        command.upgrade(config, "head")
