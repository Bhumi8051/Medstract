"""Shared test helpers. Tests never call the real PubMed: HTTP is mocked with httpx.MockTransport."""

from collections.abc import Callable
from xml.sax.saxutils import escape

import httpx
import pytest

from app.config import Settings
from app.models import Paper
from app.services.pubmed import PubMedClient


@pytest.fixture
def anyio_backend() -> str:
    # Run async tests (marked @pytest.mark.anyio) on asyncio only.
    return "asyncio"


def make_settings(**overrides) -> Settings:
    """Settings that ignore backend/.env, never sleep, and don't throttle."""
    values = {
        "ncbi_api_key": None,
        "ncbi_email": "test@example.edu",
        "ncbi_retry_backoff_seconds": 0.0,
        "ncbi_requests_per_second": 10_000.0,
        **overrides,
    }
    return Settings(_env_file=None, **values)


def make_paper(pmid: str = "1", title: str = "A study of something", **fields) -> Paper:
    return Paper(pmid=pmid, title=title, pubmed_url=f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/", **fields)


def article_xml(
    pmid: str,
    title: str | None = "Untitled",
    *,
    abstract: str | None = None,
    authors: list[tuple[str, str]] | None = None,
    year: str | None = "2022",
    month: str | None = None,
    day: str | None = None,
    medline_date: str | None = None,
    electronic: tuple[str, str, str] | None = None,
    doi: str | None = None,
    languages: list[str] | None = None,
) -> str:
    """Build a minimal <PubmedArticle> like EFetch returns.

    `title` is inserted as raw XML so tests can include inline tags like <i>.
    """
    title_xml = f"<ArticleTitle>{title}</ArticleTitle>" if title else ""
    abstract_xml = (
        f"<Abstract><AbstractText>{escape(abstract)}</AbstractText></Abstract>" if abstract else ""
    )
    authors_xml = ""
    if authors:
        authors_xml = "<AuthorList>" + "".join(
            f"<Author><LastName>{last}</LastName><ForeName>{fore}</ForeName></Author>"
            for fore, last in authors
        ) + "</AuthorList>"

    if medline_date:
        pub_date = f"<MedlineDate>{medline_date}</MedlineDate>"
    else:
        pub_date = "".join(
            f"<{tag}>{value}</{tag}>"
            for tag, value in (("Year", year), ("Month", month), ("Day", day))
            if value
        )
    electronic_xml = ""
    if electronic:
        y, m, d = electronic
        electronic_xml = (
            f'<ArticleDate DateType="Electronic"><Year>{y}</Year><Month>{m}</Month><Day>{d}</Day></ArticleDate>'
        )
    doi_xml = f'<ArticleIdList><ArticleId IdType="doi">{doi}</ArticleId></ArticleIdList>' if doi else ""
    language_xml = "".join(f"<Language>{code}</Language>" for code in languages or [])

    return f"""
    <PubmedArticle>
      <MedlineCitation>
        <PMID>{pmid}</PMID>
        <Article>
          <Journal><Title>Test Journal</Title><JournalIssue><PubDate>{pub_date}</PubDate></JournalIssue></Journal>
          {title_xml}{abstract_xml}{authors_xml}{language_xml}{electronic_xml}
          <PublicationTypeList><PublicationType>Journal Article</PublicationType></PublicationTypeList>
        </Article>
      </MedlineCitation>
      <PubmedData>{doi_xml}</PubmedData>
    </PubmedArticle>"""


def efetch_xml(*articles: str) -> str:
    return f'<?xml version="1.0"?><PubmedArticleSet>{"".join(articles)}</PubmedArticleSet>'


def esearch_json(pmids: list[str], count: int | None = None) -> dict:
    return {
        "header": {"type": "esearch"},
        "esearchresult": {
            "count": str(len(pmids) if count is None else count),
            "idlist": pmids,
        },
    }


Handler = Callable[[httpx.Request], httpx.Response]


def pubmed_handler(esearch: dict, efetch: str) -> Handler:
    """Mock NCBI: answer ESearch with JSON and EFetch with XML."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("esearch.fcgi"):
            return httpx.Response(200, json=esearch)
        if request.url.path.endswith("efetch.fcgi"):
            return httpx.Response(200, text=efetch, headers={"Content-Type": "text/xml"})
        return httpx.Response(404)

    return handler


def make_client(handler: Handler, settings: Settings | None = None) -> PubMedClient:
    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return PubMedClient(settings or make_settings(), http_client)


# ---------- PostgreSQL fixtures (accounts, preferences, saved searches) ----------

import asyncio  # noqa: E402
import os  # noqa: E402

from sqlalchemy import text  # noqa: E402
from sqlalchemy.ext.asyncio import create_async_engine  # noqa: E402
from sqlalchemy.pool import NullPool  # noqa: E402

TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL", "postgresql+asyncpg://localhost/healthcare_research_test"
)
ACCOUNT_TABLES = "users, user_sessions, research_preferences, saved_searches"


def run_db(statement: str, params: dict | None = None, url: str = TEST_DATABASE_URL):
    """Run one SQL statement against the test database and return all rows."""

    async def _run():
        engine = create_async_engine(url, poolclass=NullPool)
        try:
            async with engine.begin() as conn:
                result = await conn.execute(text(statement), params or {})
                return result.fetchall() if result.returns_rows else []
        finally:
            await engine.dispose()

    return asyncio.run(_run())


def alembic_config(url: str):
    from alembic.config import Config

    from app.config import BACKEND_DIR

    config = Config(str(BACKEND_DIR / "alembic.ini"))
    config.attributes["database_url"] = url
    config.attributes["configure_logger"] = False
    return config


@pytest.fixture(scope="session")
def migrated_test_db() -> str:
    """Bring the test database to the latest migration (once per test run)."""
    from alembic import command

    db_name = TEST_DATABASE_URL.rsplit("/", 1)[-1]
    if not db_name.endswith("_test"):
        pytest.fail(f"Refusing to run database tests against '{db_name}': its name must end in _test.")
    try:
        run_db("SELECT 1")
    except Exception as exc:  # noqa: BLE001
        pytest.skip(
            f"PostgreSQL test database not reachable ({type(exc).__name__}). "
            "Start PostgreSQL and run: createdb healthcare_research_test"
        )
    command.upgrade(alembic_config(TEST_DATABASE_URL), "head")
    return TEST_DATABASE_URL


@pytest.fixture
def db_client(migrated_test_db):
    """A TestClient using the real app with the test database. Tables are emptied first."""
    from fastapi.testclient import TestClient

    from app.db import create_sessionmaker
    from app.main import app
    from app.services.auth import LoginThrottle

    run_db(f"TRUNCATE {ACCOUNT_TABLES} RESTART IDENTITY CASCADE")
    engine = create_async_engine(migrated_test_db, poolclass=NullPool)
    saved = {k: getattr(app.state, k, None) for k in ("db_sessionmaker", "login_throttle")}
    app.state.db_sessionmaker = create_sessionmaker(engine)
    app.state.login_throttle = LoginThrottle(max_failures=5, window_seconds=900)

    client = TestClient(app, base_url="http://localhost")
    client.headers.update({"X-Requested-With": "fetch"})  # what the frontend sends
    yield client

    client.close()
    for key, value in saved.items():
        setattr(app.state, key, value)
    asyncio.run(engine.dispose())
