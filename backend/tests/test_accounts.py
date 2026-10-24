"""Accounts: registration, login, sessions, CSRF, throttling, preferences and saved searches.

Runs against the real PostgreSQL test database (see conftest.py).
"""

import hashlib

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import app
from tests.conftest import run_db

PASSWORD = "correct horse battery"
COOKIE = get_settings().session_cookie_name


def register(client: TestClient, email: str = "Ada@Example.org", password: str = PASSWORD):
    return client.post("/api/auth/register", json={"email": email, "password": password})


def login(client: TestClient, email: str = "ada@example.org", password: str = PASSWORD):
    return client.post("/api/auth/login", json={"email": email, "password": password})


def second_client(first: TestClient) -> TestClient:
    """Another browser: same app and database, separate cookies."""
    other = TestClient(app, base_url="http://localhost")
    other.headers.update({"X-Requested-With": "fetch"})
    return other


# ---------- registration ----------


def test_register_creates_account_and_logs_in(db_client):
    response = register(db_client)

    assert response.status_code == 201
    data = response.json()
    assert data["user"]["email"] == "ada@example.org"  # normalised to lowercase
    assert data["preferences"] == {"summary_level": "college", "research_interests": []}
    assert "password" not in response.text and "argon2" not in response.text

    cookie = response.headers["set-cookie"].lower()
    assert f"{COOKIE}=" in cookie
    assert "httponly" in cookie and "samesite=lax" in cookie and "path=/" in cookie
    assert db_client.get("/api/auth/me").json()["user"]["email"] == "ada@example.org"


def test_password_is_stored_as_argon2id_hash_only(db_client):
    register(db_client)
    [(stored,)] = run_db("SELECT password_hash FROM users")
    assert stored.startswith("$argon2id$")
    assert PASSWORD not in stored


def test_session_token_is_stored_hashed(db_client):
    register(db_client)
    token = db_client.cookies.get(COOKIE)
    [(token_hash,)] = run_db("SELECT token_hash FROM user_sessions")
    assert token and token not in token_hash
    assert token_hash == hashlib.sha256(token.encode()).hexdigest()


def test_duplicate_email_is_rejected_case_insensitively(db_client):
    assert register(db_client).status_code == 201
    response = register(second_client(db_client), email="ADA@example.ORG")
    assert response.status_code == 409


@pytest.mark.parametrize(
    "body",
    [
        {"email": "not-an-email", "password": PASSWORD},
        {"email": "a@example.org", "password": "short"},
        {"email": "a@example.org", "password": "x" * 129},
        {"email": "a@example.org"},
        {"email": "a@example.org", "password": PASSWORD, "is_admin": True},
    ],
)
def test_invalid_registration_returns_422(db_client, body):
    assert db_client.post("/api/auth/register", json=body).status_code == 422
    assert run_db("SELECT count(*) FROM users")[0][0] == 0


# ---------- login, logout, sessions ----------


def test_login_and_logout(db_client):
    register(db_client)
    db_client.post("/api/auth/logout")
    assert db_client.get("/api/auth/me").status_code == 401

    response = login(db_client, email="ADA@example.org")
    assert response.status_code == 200
    assert response.json()["user"]["email"] == "ada@example.org"
    assert db_client.get("/api/auth/me").status_code == 200


def test_wrong_password_and_unknown_email_get_the_same_answer(db_client):
    register(db_client)
    other = second_client(db_client)
    wrong_password = login(other, password="wrong password!")
    unknown_email = login(other, email="nobody@example.org")
    assert wrong_password.status_code == unknown_email.status_code == 401
    assert wrong_password.json() == unknown_email.json() == {"detail": "Incorrect email or password."}


def test_logout_deletes_the_session_server_side(db_client):
    register(db_client)
    token = db_client.cookies.get(COOKIE)
    response = db_client.post("/api/auth/logout")
    assert response.status_code == 204
    assert f"{COOKIE}=" in response.headers["set-cookie"] and "max-age=0" in response.headers["set-cookie"].lower()
    assert run_db("SELECT count(*) FROM user_sessions")[0][0] == 0

    # Re-using the old token (e.g. a stolen copy) no longer works.
    replay = second_client(db_client)
    replay.cookies.set(COOKIE, token)
    assert replay.get("/api/auth/me").status_code == 401


def test_logout_when_not_logged_in_is_harmless(db_client):
    assert db_client.post("/api/auth/logout").status_code == 204


def test_expired_session_is_rejected(db_client):
    register(db_client)
    run_db("UPDATE user_sessions SET expires_at = now() - interval '1 minute'")
    assert db_client.get("/api/auth/me").status_code == 401


@pytest.mark.parametrize("token", ["garbage", "", "x" * 500])
def test_unknown_or_malformed_session_cookie_is_rejected(db_client, token):
    db_client.cookies.set(COOKIE, token)
    assert db_client.get("/api/auth/me").status_code == 401


def test_me_without_cookie_returns_401(db_client):
    assert db_client.get("/api/auth/me").status_code == 401


# ---------- throttling ----------


def test_repeated_failures_are_throttled_even_with_the_right_password(db_client):
    register(db_client)
    other = second_client(db_client)
    for _ in range(5):
        assert login(other, password="wrong password!").status_code == 401
    blocked = login(other)  # correct password, but too many recent failures
    assert blocked.status_code == 429
    assert int(blocked.headers["retry-after"]) > 0


def test_successful_login_resets_the_failure_count(db_client):
    register(db_client)
    other = second_client(db_client)
    for _ in range(4):
        login(other, password="wrong password!")
    assert login(other).status_code == 200
    for _ in range(4):
        assert login(other, password="wrong password!").status_code == 401


# ---------- CSRF header ----------


@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        ("post", "/api/auth/register", {"email": "b@example.org", "password": PASSWORD}),
        ("post", "/api/auth/login", {"email": "ada@example.org", "password": PASSWORD}),
        ("post", "/api/auth/logout", None),
        ("put", "/api/me/preferences", {"summary_level": "phd", "research_interests": []}),
        ("post", "/api/saved-searches", {"query": "asthma"}),
    ],
)
def test_state_changing_requests_require_the_csrf_header(db_client, method, path, body):
    register(db_client)
    del db_client.headers["X-Requested-With"]
    response = getattr(db_client, method)(path, json=body) if body is not None else getattr(db_client, method)(path)
    assert response.status_code == 403
    assert "X-Requested-With" in response.json()["detail"]


def test_delete_requires_the_csrf_header(db_client):
    register(db_client)
    search_id = db_client.post("/api/saved-searches", json={"query": "asthma"}).json()["id"]
    del db_client.headers["X-Requested-With"]
    assert db_client.delete(f"/api/saved-searches/{search_id}").status_code == 403
    assert run_db("SELECT count(*) FROM saved_searches")[0][0] == 1


# ---------- preferences ----------


def test_preferences_default_update_and_persist(db_client):
    register(db_client)
    assert db_client.get("/api/me/preferences").json() == {"summary_level": "college", "research_interests": []}

    response = db_client.put(
        "/api/me/preferences",
        json={"summary_level": "phd", "research_interests": ["  Breast   cancer ", "breast cancer", "AML"]},
    )
    assert response.status_code == 200
    assert response.json() == {"summary_level": "phd", "research_interests": ["Breast cancer", "AML"]}

    # Persisted: a fresh login returns the same preferences.
    db_client.post("/api/auth/logout")
    assert login(db_client).json()["preferences"]["summary_level"] == "phd"


@pytest.mark.parametrize(
    "body",
    [
        {"summary_level": "expert", "research_interests": []},
        {"summary_level": "phd", "research_interests": ["x"]},
        {"summary_level": "phd", "research_interests": ["y" * 101]},
        {"summary_level": "phd", "research_interests": [f"topic {i}" for i in range(21)]},
        {"summary_level": "phd", "research_interests": [], "theme": "dark"},
    ],
)
def test_invalid_preferences_return_422(db_client, body):
    register(db_client)
    assert db_client.put("/api/me/preferences", json=body).status_code == 422


def test_database_rejects_invalid_summary_level_directly(db_client):
    register(db_client)
    with pytest.raises(Exception, match="ck_research_preferences_summary_level"):
        run_db("UPDATE research_preferences SET summary_level = 'expert'")


def test_preferences_require_login(db_client):
    assert db_client.get("/api/me/preferences").status_code == 401
    assert db_client.put("/api/me/preferences", json={"summary_level": "phd"}).status_code == 401


# ---------- saved searches ----------

FILTERS = {
    "period": "all",
    "start_date": "2020",
    "end_date": "2023-06",
    "include_undated": False,
    "article_types": ["review", "meta_analysis"],
    "languages": ["english"],
    "max_results": 50,
}


def test_save_list_get_and_delete(db_client):
    register(db_client)
    created = db_client.post(
        "/api/saved-searches", json={"name": "Metformin reviews", "query": "metformin breast cancer", "filters": FILTERS}
    )
    assert created.status_code == 201
    saved = created.json()
    assert saved["name"] == "Metformin reviews"
    assert saved["filters"] == FILTERS

    second = db_client.post("/api/saved-searches", json={"query": "asthma children"}).json()
    assert second["name"] == "asthma children"  # defaults to the query
    assert second["filters"]["period"] == "all" and second["filters"]["max_results"] == 20

    listed = db_client.get("/api/saved-searches").json()
    assert [s["id"] for s in listed] == [second["id"], saved["id"]]  # newest first

    assert db_client.get(f"/api/saved-searches/{saved['id']}").json() == saved
    assert db_client.delete(f"/api/saved-searches/{saved['id']}").status_code == 204
    assert db_client.get(f"/api/saved-searches/{saved['id']}").status_code == 404
    assert len(db_client.get("/api/saved-searches").json()) == 1


@pytest.mark.parametrize(
    "body",
    [
        {"query": "a"},
        {"query": "x" * 501},
        {"query": "asthma", "name": "n" * 121},
        {"query": "asthma", "filters": {"start_date": "2023", "end_date": "2020"}},
        {"query": "asthma", "filters": {"start_date": "2020-13"}},
        {"query": "asthma", "filters": {"article_types": ["opinion"]}},
        {"query": "asthma", "filters": {"max_results": 500}},
        {"query": "asthma", "filters": {"period": "year"}},
        {"query": "asthma", "filters": {"sql": "DROP TABLE users"}},
        {"query": "asthma", "user_id": "00000000-0000-0000-0000-000000000000"},
    ],
)
def test_invalid_saved_searches_return_422(db_client, body):
    register(db_client)
    assert db_client.post("/api/saved-searches", json=body).status_code == 422
    assert run_db("SELECT count(*) FROM saved_searches")[0][0] == 0


def test_users_cannot_see_or_delete_each_others_searches(db_client):
    register(db_client)
    alice_search = db_client.post("/api/saved-searches", json={"query": "metformin"}).json()["id"]

    bob = second_client(db_client)
    register(bob, email="bob@example.org")
    assert bob.get("/api/saved-searches").json() == []
    assert bob.get(f"/api/saved-searches/{alice_search}").status_code == 404  # 404, not 403
    assert bob.delete(f"/api/saved-searches/{alice_search}").status_code == 404
    assert db_client.get(f"/api/saved-searches/{alice_search}").status_code == 200  # still there


def test_malformed_saved_search_id_returns_422(db_client):
    register(db_client)
    assert db_client.get("/api/saved-searches/not-a-uuid").status_code == 422


def test_saved_searches_require_login(db_client):
    assert db_client.get("/api/saved-searches").status_code == 401
    assert db_client.post("/api/saved-searches", json={"query": "asthma"}).status_code == 401


def test_saved_search_limit(db_client):
    register(db_client)
    run_db(
        "INSERT INTO saved_searches (id, user_id, name, query) "
        "SELECT gen_random_uuid(), id, 'q' || n, 'query ' || n FROM users, generate_series(1, 100) AS n"
    )
    response = db_client.post("/api/saved-searches", json={"query": "one too many"})
    assert response.status_code == 409


def test_deleting_a_user_removes_all_their_data(db_client):
    register(db_client)
    db_client.post("/api/saved-searches", json={"query": "metformin"})
    run_db("DELETE FROM users")
    for table in ("user_sessions", "research_preferences", "saved_searches"):
        assert run_db(f"SELECT count(*) FROM {table}")[0][0] == 0


# ---------- failure handling ----------


def test_database_down_returns_503_and_search_still_works(db_client):
    from sqlalchemy.ext.asyncio import create_async_engine
    from sqlalchemy.pool import NullPool

    from app.db import create_sessionmaker
    from app.routers.search import get_pubmed_client
    from tests.conftest import efetch_xml, esearch_json, make_client, pubmed_handler

    app.state.db_sessionmaker = create_sessionmaker(
        create_async_engine("postgresql+asyncpg://localhost:5999/healthcare_research_test", poolclass=NullPool)
    )
    db_client.cookies.set(COOKIE, "some-token")
    response = db_client.get("/api/auth/me")
    assert response.status_code == 503
    assert "database problem" in response.json()["detail"]
    assert "5999" not in response.text and "Traceback" not in response.text

    app.dependency_overrides[get_pubmed_client] = lambda: make_client(pubmed_handler(esearch_json([]), efetch_xml()))
    try:
        assert db_client.get("/api/search", params={"q": "asthma"}).status_code == 200
    finally:
        app.dependency_overrides.clear()


def test_responses_never_expose_hashes_or_tokens(db_client):
    responses = [register(db_client), db_client.get("/api/auth/me"), login(db_client)]
    [(password_hash,)] = run_db("SELECT password_hash FROM users")
    token_hashes = [row[0] for row in run_db("SELECT token_hash FROM user_sessions")]
    for response in responses:
        assert password_hash not in response.text
        assert all(h not in response.text for h in token_hashes)
        assert "password_hash" not in response.text


def test_missing_tables_return_503_not_500(db_client, migrated_test_db):
    """Forgetting `alembic upgrade head` gives a clear 503, not a crash."""
    from alembic import command

    from tests.conftest import alembic_config

    command.downgrade(alembic_config(migrated_test_db), "base")
    try:
        db_client.cookies.set(COOKIE, "some-token")
        response = db_client.get("/api/auth/me")
        assert response.status_code == 503
        assert "UndefinedTable" not in response.text and "relation" not in response.text
    finally:
        command.upgrade(alembic_config(migrated_test_db), "head")
