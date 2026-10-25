"""Research subscriptions API against the real PostgreSQL test database (see conftest.py)."""

import pytest
from fastapi.testclient import TestClient

from app.main import app
from tests.conftest import run_db

PASSWORD = "correct horse battery"

VALID = {
    "topic": "Metformin breast cancer",
    "frequency": "weekly",
    "weekday": 1,
    "delivery_time": "08:00",
    "time_zone": "America/New_York",
    "paper_count": 10,
    "reading_level": "college",
    "email_enabled": True,
    "email_when_no_new_papers": False,
}


def sign_up(client: TestClient, email: str = "ada@example.org") -> None:
    assert client.post("/api/auth/register", json={"email": email, "password": PASSWORD}).status_code == 201


def other_browser() -> TestClient:
    client = TestClient(app, base_url="http://localhost")
    client.headers.update({"X-Requested-With": "fetch"})
    return client


def create(client: TestClient, **overrides):
    return client.post("/api/subscriptions", json={**VALID, **overrides})


# ---------- create / read / update / delete ----------


def test_create_returns_stored_settings(db_client):
    sign_up(db_client)
    response = create(db_client)
    assert response.status_code == 201
    data = response.json()
    assert {k: data[k] for k in VALID} == {**VALID}
    assert data["month_day"] is None
    assert data["delivery_active"] is False  # never claims delivery is running
    assert data["created_at"] and data["updated_at"]


def test_subscription_persists_across_sessions(db_client):
    sign_up(db_client)
    created = create(db_client).json()
    # A brand-new browser session (log in again) sees the same stored subscription.
    later = other_browser()
    assert later.post("/api/auth/login", json={"email": "ada@example.org", "password": PASSWORD}).status_code == 200
    assert later.get("/api/subscriptions").json() == [created]
    [(topic, topic_key, time_zone)] = run_db("SELECT topic, topic_key, time_zone FROM research_subscriptions")
    assert (topic, topic_key, time_zone) == ("Metformin breast cancer", "metformin breast cancer", "America/New_York")


def test_list_newest_first_and_get_one(db_client):
    sign_up(db_client)
    first = create(db_client, topic="asthma").json()
    second = create(db_client, topic="gut microbiome").json()
    assert [s["id"] for s in db_client.get("/api/subscriptions").json()] == [second["id"], first["id"]]
    assert db_client.get(f"/api/subscriptions/{first['id']}").json() == first


def test_update_replaces_settings(db_client):
    sign_up(db_client)
    created = create(db_client).json()
    changed = {**VALID, "frequency": "monthly", "month_day": 15, "weekday": 3, "delivery_time": "07:30",
               "time_zone": "Europe/London", "paper_count": 20, "reading_level": "phd",
               "email_enabled": False, "email_when_no_new_papers": True}
    response = db_client.put(f"/api/subscriptions/{created['id']}", json=changed)
    assert response.status_code == 200
    data = response.json()
    assert data["month_day"] == 15 and data["weekday"] is None  # irrelevant day cleared
    assert (data["frequency"], data["delivery_time"], data["time_zone"]) == ("monthly", "07:30", "Europe/London")
    assert (data["paper_count"], data["reading_level"], data["email_enabled"]) == (20, "phd", False)
    assert db_client.get(f"/api/subscriptions/{created['id']}").json()["month_day"] == 15


def test_update_can_keep_own_topic_with_different_formatting(db_client):
    sign_up(db_client)
    created = create(db_client).json()
    response = db_client.put(f"/api/subscriptions/{created['id']}", json={**VALID, "topic": "METFORMIN, breast cancer!"})
    assert response.status_code == 200
    assert response.json()["topic"] == "METFORMIN, breast cancer!"


def test_delete(db_client):
    sign_up(db_client)
    created = create(db_client).json()
    assert db_client.delete(f"/api/subscriptions/{created['id']}").status_code == 204
    assert db_client.get(f"/api/subscriptions/{created['id']}").status_code == 404
    assert db_client.get("/api/subscriptions").json() == []


def test_daily_clears_both_days(db_client):
    sign_up(db_client)
    data = create(db_client, frequency="daily", weekday=4, month_day=9).json()
    assert data["weekday"] is None and data["month_day"] is None


# ---------- duplicates ----------


@pytest.mark.parametrize("variant", ["metformin breast cancer", "METFORMIN, Breast-Cancer!", "  Metformin   breast cancer  "])
def test_duplicate_topic_is_rejected(db_client, variant):
    sign_up(db_client)
    assert create(db_client).status_code == 201
    response = create(db_client, topic=variant)
    assert response.status_code == 409
    assert "already" in response.json()["detail"]
    assert run_db("SELECT count(*) FROM research_subscriptions")[0][0] == 1


def test_accents_count_as_the_same_topic(db_client):
    sign_up(db_client)
    assert create(db_client, topic="Sjögren syndrome").status_code == 201
    assert create(db_client, topic="sjogren syndrome").status_code == 409


def test_update_to_another_subscriptions_topic_is_rejected(db_client):
    sign_up(db_client)
    create(db_client, topic="asthma")
    other = create(db_client, topic="copd").json()
    response = db_client.put(f"/api/subscriptions/{other['id']}", json={**VALID, "topic": "Asthma"})
    assert response.status_code == 409
    assert db_client.get(f"/api/subscriptions/{other['id']}").json()["topic"] == "copd"  # unchanged


def test_two_users_may_follow_the_same_topic(db_client):
    sign_up(db_client)
    assert create(db_client).status_code == 201
    bob = other_browser()
    sign_up(bob, email="bob@example.org")
    assert create(bob).status_code == 201


def test_database_enforces_uniqueness_directly(db_client):
    sign_up(db_client)
    create(db_client)
    with pytest.raises(Exception, match="uq_research_subscriptions_user_topic"):
        run_db(
            "INSERT INTO research_subscriptions (id, user_id, topic, topic_key, frequency, weekday, delivery_time,"
            " time_zone, paper_count, reading_level) SELECT gen_random_uuid(), user_id, 'x', topic_key, 'weekly', 1,"
            " '08:00', 'UTC', 10, 'college' FROM research_subscriptions"
        )


@pytest.mark.parametrize(
    ("column_sql", "constraint"),
    [
        ("paper_count = 7", "ck_research_subscriptions_paper_count"),
        ("reading_level = 'expert'", "ck_research_subscriptions_reading_level"),
        ("frequency = 'hourly'", "ck_research_subscriptions_frequency"),
        ("weekday = NULL", "ck_research_subscriptions_schedule"),
        ("month_day = 15", "ck_research_subscriptions_schedule"),
        ("topic_key = ''", "ck_research_subscriptions_topic_key"),
    ],
)
def test_database_check_constraints(db_client, column_sql, constraint):
    sign_up(db_client)
    create(db_client)  # weekly
    with pytest.raises(Exception, match=constraint):
        run_db(f"UPDATE research_subscriptions SET {column_sql}")


# ---------- validation ----------


@pytest.mark.parametrize(
    "overrides",
    [
        {"topic": "a"},
        {"topic": "x" * 201},
        {"topic": "!!! ???"},
        {"frequency": "hourly"},
        {"frequency": "weekly", "weekday": None},
        {"weekday": 7},
        {"frequency": "monthly", "month_day": None},
        {"frequency": "monthly", "month_day": 29},
        {"frequency": "monthly", "month_day": 0},
        {"delivery_time": "25:00"},
        {"delivery_time": "8:00"},
        {"delivery_time": "08:60"},
        {"time_zone": "Mars/Olympus_Mons"},
        {"time_zone": ""},
        {"paper_count": 7},
        {"paper_count": "10"},
        {"reading_level": "expert"},
        {"email_enabled": "maybe"},
        {"user_id": "00000000-0000-0000-0000-000000000000"},
        {"delivery_active": True},
    ],
)
def test_invalid_input_returns_422(db_client, overrides):
    sign_up(db_client)
    assert create(db_client, **overrides).status_code == 422
    assert run_db("SELECT count(*) FROM research_subscriptions")[0][0] == 0


def test_missing_required_fields_return_422(db_client):
    sign_up(db_client)
    assert db_client.post("/api/subscriptions", json={"topic": "asthma"}).status_code == 422


def test_malformed_id_returns_422(db_client):
    sign_up(db_client)
    assert db_client.get("/api/subscriptions/not-a-uuid").status_code == 422


def test_subscription_limit(db_client):
    sign_up(db_client)
    run_db(
        "INSERT INTO research_subscriptions (id, user_id, topic, topic_key, frequency, delivery_time, time_zone,"
        " paper_count, reading_level) SELECT gen_random_uuid(), id, 'topic ' || n, 'topic ' || n, 'daily', '08:00',"
        " 'UTC', 10, 'college' FROM users, generate_series(1, 50) AS n"
    )
    response = create(db_client, topic="one too many")
    assert response.status_code == 409
    assert "50" in response.json()["detail"]


# ---------- authentication, CSRF, ownership ----------


def test_unauthenticated_requests_are_rejected(db_client):
    sign_up(db_client)
    created = create(db_client).json()
    anonymous = other_browser()
    assert anonymous.get("/api/subscriptions").status_code == 401
    assert anonymous.post("/api/subscriptions", json=VALID).status_code == 401
    assert anonymous.get(f"/api/subscriptions/{created['id']}").status_code == 401
    assert anonymous.put(f"/api/subscriptions/{created['id']}", json=VALID).status_code == 401
    assert anonymous.delete(f"/api/subscriptions/{created['id']}").status_code == 401


@pytest.mark.parametrize("method", ["post", "put", "delete"])
def test_changes_require_the_csrf_header(db_client, method):
    sign_up(db_client)
    created = create(db_client).json()
    del db_client.headers["X-Requested-With"]
    if method == "post":
        response = db_client.post("/api/subscriptions", json={**VALID, "topic": "asthma"})
    elif method == "put":
        response = db_client.put(f"/api/subscriptions/{created['id']}", json=VALID)
    else:
        response = db_client.delete(f"/api/subscriptions/{created['id']}")
    assert response.status_code == 403
    assert run_db("SELECT count(*) FROM research_subscriptions")[0][0] == 1


def test_users_cannot_see_change_or_delete_others_subscriptions(db_client):
    sign_up(db_client)
    alice_sub = create(db_client).json()["id"]
    bob = other_browser()
    sign_up(bob, email="bob@example.org")

    assert bob.get("/api/subscriptions").json() == []
    assert bob.get(f"/api/subscriptions/{alice_sub}").status_code == 404  # 404, not 403
    assert bob.put(f"/api/subscriptions/{alice_sub}", json={**VALID, "topic": "hijacked"}).status_code == 404
    assert bob.delete(f"/api/subscriptions/{alice_sub}").status_code == 404
    assert db_client.get(f"/api/subscriptions/{alice_sub}").json()["topic"] == "Metformin breast cancer"


def test_deleting_a_user_removes_their_subscriptions(db_client):
    sign_up(db_client)
    create(db_client)
    run_db("DELETE FROM users")
    assert run_db("SELECT count(*) FROM research_subscriptions")[0][0] == 0


def test_database_down_returns_503(db_client):
    from sqlalchemy.ext.asyncio import create_async_engine
    from sqlalchemy.pool import NullPool

    from app.db import create_sessionmaker

    sign_up(db_client)
    app.state.db_sessionmaker = create_sessionmaker(
        create_async_engine("postgresql+asyncpg://localhost:5999/healthcare_research_test", poolclass=NullPool)
    )
    assert db_client.get("/api/subscriptions").status_code == 503
