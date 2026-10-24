"""PubMedClient against a mocked NCBI: parsing, missing fields, errors and retries."""

from datetime import date

import httpx
import pytest

from app.models import NO_TITLE_PLACEHOLDER
from app.services.pubmed import (
    PubMedRateLimitError,
    PubMedResponseError,
    PubMedTimeoutError,
)
from tests.conftest import (
    article_xml,
    efetch_xml,
    esearch_json,
    make_client,
    make_settings,
    pubmed_handler,
)

pytestmark = pytest.mark.anyio


# ---------- parsing ----------


async def test_parses_complete_article():
    xml = efetch_xml(
        article_xml(
            "111",
            "Metformin and <i>cancer</i>",
            abstract="Background text.",
            authors=[("Jane", "Doe"), ("John", "Smith")],
            year="2023",
            month="Jun",
            day="21",
            doi="10.1000/xyz",
        )
    )
    client = make_client(pubmed_handler(esearch_json([]), xml))
    [paper] = await client.efetch(["111"])

    assert paper.title == "Metformin and cancer"
    assert paper.abstract == "Background text."
    assert [a.name for a in paper.authors] == ["Jane Doe", "John Smith"]
    assert paper.publication_date == "2023 Jun 21"
    assert paper.publication_date_iso == "2023-06-21"
    assert paper.publication_year == 2023
    assert paper.doi_url == "https://doi.org/10.1000/xyz"
    assert paper.languages == []
    assert paper.pubmed_url == "https://pubmed.ncbi.nlm.nih.gov/111/"


async def test_missing_optional_fields_become_none_or_empty():
    xml = efetch_xml(article_xml("222", None, year=None))
    client = make_client(pubmed_handler(esearch_json([]), xml))
    [paper] = await client.efetch(["222"])

    assert paper.title == NO_TITLE_PLACEHOLDER
    assert paper.abstract is None
    assert paper.authors == []
    assert paper.doi is None and paper.doi_url is None
    assert paper.publication_date is None
    assert paper.publication_date_iso is None
    assert paper.publication_year is None


@pytest.mark.parametrize(
    ("kwargs", "expected_iso", "expected_year"),
    [
        ({"medline_date": "2021 Jan-Feb"}, "2021", 2021),
        ({"year": "2020", "month": "12"}, "2020-12", 2020),
        ({"year": "2020", "month": "Spring"}, "2020", 2020),
        ({"year": "2021", "month": "Feb", "day": "30"}, "2021-02", 2021),  # invalid day dropped
        ({"year": "n.d."}, None, None),
    ],
)
async def test_publication_date_normalization(kwargs, expected_iso, expected_year):
    client = make_client(pubmed_handler(esearch_json([]), efetch_xml(article_xml("1", "T", **kwargs))))
    [paper] = await client.efetch(["1"])
    assert paper.publication_date_iso == expected_iso
    assert paper.publication_year == expected_year


async def test_languages_parsed():
    xml = efetch_xml(article_xml("1", "T", languages=["spa", "eng"]))
    [paper] = await make_client(pubmed_handler(esearch_json([]), xml)).efetch(["1"])
    assert paper.languages == ["spa", "eng"]


async def test_electronic_date_used_when_print_date_missing():
    xml = efetch_xml(article_xml("1", "T", year=None, electronic=("2022", "03", "05")))
    [paper] = await make_client(pubmed_handler(esearch_json([]), xml)).efetch(["1"])
    assert paper.electronic_date_iso == "2022-03-05"
    assert paper.publication_date_iso == "2022-03-05"
    assert paper.publication_year == 2022


async def test_records_without_pmid_are_skipped_and_order_follows_esearch():
    broken = "<PubmedArticle><MedlineCitation><Article/></MedlineCitation></PubmedArticle>"
    xml = efetch_xml(article_xml("2", "Second"), broken, article_xml("1", "First"))
    papers = await make_client(pubmed_handler(esearch_json([]), xml)).efetch(["1", "2", "3"])
    assert [p.pmid for p in papers] == ["1", "2"]


async def test_efetch_with_no_ids_makes_no_request():
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(500)

    assert await make_client(handler).efetch([]) == []
    assert calls == []


# ---------- malformed responses ----------


@pytest.mark.parametrize(
    "body",
    ["not xml at all", "", "<eFetchResult><ERROR>Empty id list</ERROR></eFetchResult>"],
)
async def test_malformed_efetch_raises(body):
    with pytest.raises(PubMedResponseError):
        await make_client(pubmed_handler(esearch_json([]), body)).efetch(["1"])


@pytest.mark.parametrize(
    "body",
    [
        {"error": "API key invalid"},
        {"esearchresult": {"ERROR": "Invalid query"}},
        {"esearchresult": {"count": "abc", "idlist": []}},
        {"esearchresult": {"count": "1", "idlist": "123"}},
        {"unexpected": True},
        ["not", "a", "dict"],
    ],
)
async def test_malformed_esearch_raises(body):
    with pytest.raises(PubMedResponseError):
        await make_client(pubmed_handler(body, efetch_xml())).esearch("asthma", 5)


async def test_esearch_non_json_raises():
    client = make_client(lambda request: httpx.Response(200, text="<html>oops</html>"))
    with pytest.raises(PubMedResponseError):
        await client.esearch("asthma", 5)


async def test_esearch_drops_invalid_and_repeated_ids():
    body = esearch_json(["3", "abc", "1", "3", " 2 "], count=99)
    count, pmids = await make_client(pubmed_handler(body, efetch_xml())).esearch("asthma", 5)
    assert count == 99
    assert pmids == ["3", "1", "2"]


# ---------- request parameters ----------


async def test_esearch_sends_identity_and_date_params():
    seen: list[httpx.Request] = []

    def handler(request):
        seen.append(request)
        return httpx.Response(200, json=esearch_json([]))

    client = make_client(handler, make_settings(ncbi_api_key="secret-key"))
    await client.esearch("asthma", 5, start_date=date(2020, 1, 1))

    params = seen[0].url.params
    assert params["api_key"] == "secret-key"
    assert params["email"] == "test@example.edu"
    assert params["tool"] == "healthcare-research-agent"
    assert params["sort"] == "relevance"
    assert params["datetype"] == "pdat"
    assert params["mindate"] == "2020/01/01"
    assert params["maxdate"] == "3000/12/31"


async def test_esearch_without_dates_sends_no_date_params():
    seen: list[httpx.Request] = []

    def handler(request):
        seen.append(request)
        return httpx.Response(200, json=esearch_json([]))

    await make_client(handler).esearch("asthma", 5)
    assert "mindate" not in seen[0].url.params
    assert "api_key" not in seen[0].url.params


# ---------- HTTP errors, timeouts, rate limits, retries ----------


def _counting_handler(responses):
    """Return the given responses in order (repeating the last), counting calls."""
    calls = {"n": 0}

    def handler(request):
        index = min(calls["n"], len(responses) - 1)
        calls["n"] += 1
        result = responses[index]
        if isinstance(result, Exception):
            raise result
        return result

    return handler, calls


async def test_rate_limit_is_retried_then_succeeds():
    handler, calls = _counting_handler(
        [httpx.Response(429), httpx.Response(200, json=esearch_json(["1"]))]
    )
    count, pmids = await make_client(handler).esearch("asthma", 5)
    assert pmids == ["1"]
    assert calls["n"] == 2


async def test_persistent_rate_limit_raises_after_retries():
    handler, calls = _counting_handler([httpx.Response(429, headers={"Retry-After": "0"})])
    with pytest.raises(PubMedRateLimitError):
        await make_client(handler, make_settings(ncbi_max_retries=2)).esearch("asthma", 5)
    assert calls["n"] == 3


async def test_timeout_raises_timeout_error_after_retries():
    handler, calls = _counting_handler([httpx.ReadTimeout("slow")])
    with pytest.raises(PubMedTimeoutError):
        await make_client(handler, make_settings(ncbi_max_retries=1)).esearch("asthma", 5)
    assert calls["n"] == 2


async def test_server_error_is_retried_then_raises():
    handler, calls = _counting_handler([httpx.Response(503)])
    with pytest.raises(PubMedResponseError, match="HTTP 503"):
        await make_client(handler, make_settings(ncbi_max_retries=1)).esearch("asthma", 5)
    assert calls["n"] == 2


async def test_connection_error_raises_response_error():
    handler, _ = _counting_handler([httpx.ConnectError("no network")])
    with pytest.raises(PubMedResponseError, match="Could not reach PubMed"):
        await make_client(handler, make_settings(ncbi_max_retries=0)).esearch("asthma", 5)


async def test_client_error_is_not_retried_and_includes_ncbi_message():
    handler, calls = _counting_handler([httpx.Response(400, json={"error": "API key invalid"})])
    with pytest.raises(PubMedResponseError, match="API key invalid"):
        await make_client(handler).esearch("asthma", 5)
    assert calls["n"] == 1
