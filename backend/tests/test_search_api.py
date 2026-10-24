"""End-to-end tests of GET /api/search with a mocked PubMed."""

from datetime import date

import httpx
import pytest
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import app, cors_options
from app.routers.search import get_pubmed_client, get_today
from tests.conftest import (
    article_xml,
    efetch_xml,
    esearch_json,
    make_client,
    make_settings,
    pubmed_handler,
)


@pytest.fixture
def api():
    """Yield a function that points the API at a mock PubMed handler and returns a TestClient."""
    settings = make_settings(ncbi_max_retries=0)

    def configure(handler) -> TestClient:
        app.dependency_overrides[get_settings] = lambda: settings
        app.dependency_overrides[get_pubmed_client] = lambda: make_client(handler, settings)
        return TestClient(app)

    yield configure
    app.dependency_overrides.clear()


SAMPLE_XML = efetch_xml(
    article_xml("10", "Unrelated title", abstract="Metformin may lower cancer risk.", year="2021", doi="10.1/a"),
    article_xml("11", "Metformin and cancer risk", abstract="We studied metformin.", year="2022", doi="10.1/b"),
    # Same DOI as PMID 11 -> duplicate.
    article_xml("12", "Metformin &amp; cancer risk (reprint)", year="2022", doi="10.1/B"),
    article_xml("13", "Metformin in cancer: a cohort", year="2015"),
    article_xml("14", "Metformin cancer outcomes with no date given", year=None),
)
SAMPLE_IDS = ["10", "11", "12", "13", "14"]


def test_search_ranks_dedupes_and_reports(api):
    client = api(pubmed_handler(esearch_json(SAMPLE_IDS, count=500), SAMPLE_XML))
    response = client.get("/api/search", params={"q": "metformin cancer"})

    assert response.status_code == 200
    data = response.json()
    assert data["total_results"] == 500
    assert data["duplicates_removed"] == 1
    assert data["returned"] == 4
    pmids = [p["pmid"] for p in data["papers"]]
    assert "12" not in pmids
    assert pmids[-1] == "10"  # only abstract matches -> lowest score
    scores = [p["relevance_score"] for p in data["papers"]]
    assert scores == sorted(scores, reverse=True)
    assert any("no abstract" in w for w in data["warnings"])


def test_max_results_limits_output(api):
    client = api(pubmed_handler(esearch_json(SAMPLE_IDS), SAMPLE_XML))
    data = client.get("/api/search", params={"q": "metformin cancer", "max_results": 2}).json()
    assert data["returned"] == 2
    assert len(data["papers"]) == 2


def test_date_filter_excludes_out_of_range_and_undated(api):
    client = api(pubmed_handler(esearch_json(SAMPLE_IDS), SAMPLE_XML))
    data = client.get(
        "/api/search", params={"q": "metformin cancer", "start_date": "2020", "end_date": "2022-12"}
    ).json()

    assert data["start_date"] == "2020-01-01"
    assert data["end_date"] == "2022-12-31"
    assert sorted(p["pmid"] for p in data["papers"]) == ["10", "11"]
    assert data["excluded_by_date"] == 2  # 2015 paper and the undated paper
    assert any("include_undated=true" in w for w in data["warnings"])


def test_include_undated_keeps_papers_without_dates(api):
    client = api(pubmed_handler(esearch_json(SAMPLE_IDS), SAMPLE_XML))
    data = client.get(
        "/api/search", params={"q": "metformin cancer", "start_date": "2020", "include_undated": True}
    ).json()
    assert "14" in [p["pmid"] for p in data["papers"]]


def test_empty_results(api):
    client = api(pubmed_handler(esearch_json([]), efetch_xml()))
    response = client.get("/api/search", params={"q": "zzqqxx nothing"})
    assert response.status_code == 200
    assert response.json()["papers"] == []
    assert response.json()["returned"] == 0


@pytest.mark.parametrize(
    "params",
    [
        {"q": "a"},
        {"q": "   "},
        {"q": "asthma", "max_results": 0},
        {"q": "asthma", "max_results": 101},
        {"q": "asthma", "max_results": "lots"},
        {"q": "asthma", "start_date": "2020/01/01"},
        {"q": "asthma", "end_date": "2021-02-30"},
        {"q": "asthma", "start_date": "2023", "end_date": "2022"},
    ],
)
def test_invalid_input_returns_422(api, params):
    client = api(pubmed_handler(esearch_json([]), efetch_xml()))
    assert client.get("/api/search", params=params).status_code == 422


def test_missing_query_returns_422(api):
    client = api(pubmed_handler(esearch_json([]), efetch_xml()))
    assert client.get("/api/search").status_code == 422


def _timeout(request: httpx.Request) -> httpx.Response:
    raise httpx.ReadTimeout("slow")


@pytest.mark.parametrize(
    ("handler", "status"),
    [
        (_timeout, 504),
        (lambda request: httpx.Response(429), 429),
        (lambda request: httpx.Response(200, text="not json"), 502),
        (lambda request: httpx.Response(500), 502),
    ],
)
def test_upstream_failures_map_to_clear_status_codes(api, handler, status):
    response = api(handler).get("/api/search", params={"q": "asthma"})
    assert response.status_code == status
    assert "detail" in response.json()


# ---------- period, article type and language filters ----------


def _recording_handler(esearch: dict, efetch: str):
    """Like pubmed_handler, but records ESearch query parameters."""
    seen: list[httpx.QueryParams] = []
    inner = pubmed_handler(esearch, efetch)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("esearch.fcgi"):
            seen.append(request.url.params)
        return inner(request)

    return handler, seen


@pytest.fixture
def pinned_today():
    app.dependency_overrides[get_today] = lambda: date(2026, 10, 23)
    yield date(2026, 10, 23)
    app.dependency_overrides.pop(get_today, None)


def test_default_period_is_all_and_adds_no_dates(api):
    handler, seen = _recording_handler(esearch_json([]), efetch_xml())
    data = api(handler).get("/api/search", params={"q": "asthma"}).json()
    assert data["period"] == "all"
    assert data["start_date"] is None and data["end_date"] is None
    assert "mindate" not in seen[0]
    assert seen[0]["term"] == "(asthma)"


def test_past_week_sends_relative_dates_to_pubmed(api, pinned_today):
    handler, seen = _recording_handler(esearch_json([]), efetch_xml())
    data = api(handler).get("/api/search", params={"q": "asthma", "period": "week"}).json()
    assert (data["start_date"], data["end_date"]) == ("2026-10-16", "2026-10-23")
    assert seen[0]["datetype"] == "pdat"
    assert (seen[0]["mindate"], seen[0]["maxdate"]) == ("2026/10/16", "2026/10/23")


def test_past_month_intersects_custom_range(api, pinned_today):
    handler, seen = _recording_handler(esearch_json([]), efetch_xml())
    data = api(handler).get(
        "/api/search", params={"q": "asthma", "period": "month", "start_date": "2026-10-01"}
    ).json()
    assert (data["start_date"], data["end_date"]) == ("2026-10-01", "2026-10-23")
    assert seen[0]["mindate"] == "2026/10/01"


def test_all_time_respects_custom_range(api, pinned_today):
    handler, seen = _recording_handler(esearch_json([]), efetch_xml())
    data = api(handler).get(
        "/api/search", params={"q": "asthma", "period": "all", "start_date": "2019", "end_date": "2020"}
    ).json()
    assert (data["start_date"], data["end_date"]) == ("2019-01-01", "2020-12-31")
    assert (seen[0]["mindate"], seen[0]["maxdate"]) == ("2019/01/01", "2020/12/31")


def test_period_not_overlapping_range_returns_422(api, pinned_today):
    client = api(pubmed_handler(esearch_json([]), efetch_xml()))
    response = client.get("/api/search", params={"q": "asthma", "period": "week", "end_date": "2020"})
    assert response.status_code == 422
    assert "does not overlap" in response.json()["detail"]


def test_article_type_and_language_filters_reach_pubmed(api):
    handler, seen = _recording_handler(esearch_json([]), efetch_xml())
    response = api(handler).get(
        "/api/search",
        params=[
            ("q", "asthma"),
            ("article_type", "review"),
            ("article_type", "meta_analysis"),
            ("language", "english"),
        ],
    )
    data = response.json()
    expected = '(asthma) AND ("Review"[pt] OR "Meta-Analysis"[pt]) AND (english[la])'
    assert seen[0]["term"] == expected
    assert data["pubmed_query"] == expected
    assert data["article_types"] == ["review", "meta_analysis"]
    assert data["languages"] == ["english"]


def test_filters_do_not_affect_ranking_terms(api):
    xml = efetch_xml(article_xml("1", "Asthma in children", year="2022"))
    data = api(pubmed_handler(esearch_json(["1"]), xml)).get(
        "/api/search", params={"q": "asthma children", "article_type": "review"}
    ).json()
    assert data["papers"][0]["relevance_score"] == 0.75  # title has both terms; "review" not counted


@pytest.mark.parametrize(
    "params",
    [
        {"q": "asthma", "period": "year"},
        {"q": "asthma", "article_type": "opinion"},
        {"q": "asthma", "language": "klingon"},
        {"q": "asthma", "article_type": "Review"},  # values are case-sensitive slugs
    ],
)
def test_unsupported_filter_values_return_422(api, params):
    handler, seen = _recording_handler(esearch_json([]), efetch_xml())
    assert api(handler).get("/api/search", params=params).status_code == 422
    assert seen == []  # never reached PubMed


def _cors_app(**settings_overrides) -> TestClient:
    """A bare app with CORS configured from the given settings."""
    cors_app = FastAPI()
    cors_app.add_middleware(CORSMiddleware, **cors_options(make_settings(**settings_overrides)))

    @cors_app.get("/ping")
    def ping() -> dict[str, str]:
        return {"ok": "yes"}

    return TestClient(cors_app)


def _allowed_origin(client: TestClient, origin: str) -> str | None:
    return client.get("/ping", headers={"Origin": origin}).headers.get("access-control-allow-origin")


@pytest.mark.parametrize(
    "origin",
    ["http://localhost:3000", "http://localhost:3001", "http://127.0.0.1:5173", "http://localhost", "http://[::1]:3000"],
)
def test_cors_dev_allows_local_origins_on_any_port(origin):
    assert _allowed_origin(_cors_app(), origin) == origin


@pytest.mark.parametrize(
    "origin",
    [
        "http://evil.example",
        "http://localhost.evil.example",
        "http://evil.example/?http://localhost:3000",
        "http://192.168.1.5:3000",
        "file://localhost",
    ],
)
def test_cors_dev_rejects_non_local_origins(origin):
    assert _allowed_origin(_cors_app(), origin) is None


def test_cors_production_allows_only_configured_origins():
    client = _cors_app(cors_allow_local_origins=False, cors_origins=["https://research.example.org"])
    assert _allowed_origin(client, "https://research.example.org") == "https://research.example.org"
    assert _allowed_origin(client, "http://localhost:3000") is None
    assert _allowed_origin(client, "https://other.example.org") is None


@pytest.mark.parametrize(("method", "allowed"), [("GET", True), ("POST", True), ("PUT", True), ("DELETE", True), ("PATCH", False)])
def test_cors_allows_only_the_api_methods(method, allowed):
    client = _cors_app()
    preflight = client.options(
        "/ping",
        headers={"Origin": "http://localhost:3000", "Access-Control-Request-Method": method},
    )
    assert (preflight.status_code == 200) is allowed


def test_cors_allows_credentials_for_listed_origins_only():
    client = _cors_app()
    allowed = client.get("/ping", headers={"Origin": "http://localhost:3000"})
    assert allowed.headers.get("access-control-allow-credentials") == "true"
    assert allowed.headers.get("access-control-allow-origin") == "http://localhost:3000"  # never "*"
    assert "access-control-allow-origin" not in client.get("/ping", headers={"Origin": "http://evil.example"}).headers


def test_cors_rejects_unexpected_request_headers():
    preflight = _cors_app().options(
        "/ping",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "x-evil-header",
        },
    )
    assert preflight.status_code == 400


def test_real_app_allows_frontend_dev_origin(api):
    client = api(pubmed_handler(esearch_json([]), efetch_xml()))
    allowed = client.get("/health", headers={"Origin": "http://localhost:3000"})
    assert allowed.headers.get("access-control-allow-origin") == "http://localhost:3000"
    other = client.get("/health", headers={"Origin": "http://evil.example"})
    assert "access-control-allow-origin" not in other.headers


def test_health(api):
    assert api(pubmed_handler(esearch_json([]), efetch_xml())).get("/health").json() == {"status": "ok"}
