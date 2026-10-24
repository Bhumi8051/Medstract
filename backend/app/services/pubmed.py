"""Client for NCBI PubMed E-utilities (ESearch + EFetch).

ESearch: query -> list of PMIDs (paper IDs).
EFetch:  PMIDs -> full records as XML, which we parse into Paper models.
"""

import asyncio
import calendar
import re
import time
import xml.etree.ElementTree as ET
from datetime import date

import httpx

from app.config import Settings
from app.models import NO_TITLE_PLACEHOLDER, Author, Paper
from app.services.dates import period_bounds, to_ncbi_date

# ESearch needs both mindate and maxdate; these stand in for an open-ended range.
_EARLIEST_NCBI_DATE = date(1800, 1, 1)
_LATEST_NCBI_DATE = date(3000, 12, 31)
# Never wait longer than this for a Retry-After header.
_MAX_RETRY_AFTER_SECONDS = 10.0


class PubMedError(Exception):
    """Base error for anything that goes wrong talking to PubMed."""


class PubMedTimeoutError(PubMedError):
    """PubMed did not respond in time."""


class PubMedRateLimitError(PubMedError):
    """PubMed returned HTTP 429 (too many requests)."""


class PubMedResponseError(PubMedError):
    """PubMed returned an error status or a response we could not parse."""


class RateLimiter:
    """Spaces requests at least 1/rate seconds apart, across all concurrent callers."""

    def __init__(self, requests_per_second: float) -> None:
        self._interval = 1.0 / requests_per_second
        self._lock = asyncio.Lock()
        self._next_allowed = 0.0

    async def wait(self) -> None:
        async with self._lock:
            now = time.monotonic()
            if self._next_allowed > now:
                await asyncio.sleep(self._next_allowed - now)
                now = self._next_allowed
            self._next_allowed = now + self._interval


class PubMedClient:
    def __init__(self, settings: Settings, http_client: httpx.AsyncClient) -> None:
        self._settings = settings
        self._http = http_client
        self._limiter = RateLimiter(settings.effective_requests_per_second)

    def _common_params(self) -> dict[str, str]:
        """Parameters NCBI asks every request to include."""
        params = {"db": "pubmed", "tool": self._settings.ncbi_tool}
        if self._settings.ncbi_email:
            params["email"] = self._settings.ncbi_email
        if self._settings.ncbi_api_key:
            params["api_key"] = self._settings.ncbi_api_key
        return params

    async def _backoff(self, attempt: int, retry_after: str | None = None) -> None:
        delay = self._settings.ncbi_retry_backoff_seconds * (2**attempt)
        if retry_after and retry_after.strip().isdigit():
            delay = min(float(retry_after), _MAX_RETRY_AFTER_SECONDS)
        if delay > 0:
            await asyncio.sleep(delay)

    async def _get(self, endpoint: str, params: dict[str, str]) -> httpx.Response:
        """GET with rate limiting, retrying timeouts, HTTP 429 and HTTP 5xx."""
        url = f"{self._settings.ncbi_base_url}/{endpoint}"
        attempts = self._settings.ncbi_max_retries + 1

        for attempt in range(attempts):
            is_last = attempt == attempts - 1
            await self._limiter.wait()
            try:
                response = await self._http.get(
                    url,
                    params={**self._common_params(), **params},
                    timeout=self._settings.ncbi_timeout_seconds,
                )
            except httpx.TimeoutException as exc:
                if is_last:
                    raise PubMedTimeoutError(f"PubMed {endpoint} timed out") from exc
                await self._backoff(attempt)
                continue
            except httpx.HTTPError as exc:
                if is_last:
                    raise PubMedResponseError(f"Could not reach PubMed {endpoint}: {exc}") from exc
                await self._backoff(attempt)
                continue

            if response.status_code == 429 or response.status_code >= 500:
                if is_last:
                    if response.status_code == 429:
                        raise PubMedRateLimitError("PubMed rate limit exceeded")
                    raise PubMedResponseError(
                        f"PubMed {endpoint} returned HTTP {response.status_code}"
                    )
                await self._backoff(attempt, response.headers.get("Retry-After"))
                continue

            if response.status_code >= 400:
                raise PubMedResponseError(
                    f"PubMed {endpoint} returned HTTP {response.status_code}"
                    f"{_ncbi_error_detail(response)}"
                )
            return response

        raise AssertionError("unreachable")  # the loop always returns or raises

    async def esearch(
        self,
        query: str,
        max_results: int,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> tuple[int, list[str]]:
        """Return (total match count, list of PMIDs) for a query, best match first."""
        params = {
            "term": query,
            "retmax": str(max_results),
            "retmode": "json",
            "sort": "relevance",
        }
        if start_date or end_date:
            # "pdat" = PubMed's Publication Date, the same field as the [dp] tag.
            # It covers both the print issue date and the electronic (epub) date.
            params["datetype"] = "pdat"
            params["mindate"] = to_ncbi_date(start_date or _EARLIEST_NCBI_DATE)
            params["maxdate"] = to_ncbi_date(end_date or _LATEST_NCBI_DATE)

        response = await self._get("esearch.fcgi", params)
        try:
            data = response.json()
        except ValueError as exc:
            raise PubMedResponseError("Malformed ESearch response (not JSON)") from exc
        if not isinstance(data, dict):
            raise PubMedResponseError("Malformed ESearch response")
        if "error" in data:  # e.g. {"error": "API key invalid"}
            raise PubMedResponseError(f"ESearch error: {data['error']}")

        result = data.get("esearchresult")
        if not isinstance(result, dict):
            raise PubMedResponseError("Malformed ESearch response (missing esearchresult)")
        if "ERROR" in result:
            raise PubMedResponseError(f"ESearch error: {result['ERROR']}")

        try:
            count = int(result.get("count", 0))
        except (TypeError, ValueError) as exc:
            raise PubMedResponseError("Malformed ESearch response (bad count)") from exc
        id_list = result.get("idlist", [])
        if not isinstance(id_list, list):
            raise PubMedResponseError("Malformed ESearch response (bad idlist)")

        pmids = [str(i).strip() for i in id_list if str(i).strip().isdigit()]
        return count, list(dict.fromkeys(pmids))  # drop repeats, keep order

    async def efetch(self, pmids: list[str]) -> list[Paper]:
        """Fetch full records for the given PMIDs, in the same order.

        Records that are missing or cannot be parsed are skipped, not fatal.
        """
        if not pmids:
            return []
        response = await self._get(
            "efetch.fcgi",
            {"id": ",".join(pmids), "retmode": "xml", "rettype": "abstract"},
        )
        try:
            root = ET.fromstring(response.content)
        except ET.ParseError as exc:
            raise PubMedResponseError("Malformed EFetch XML") from exc
        if root.tag != "PubmedArticleSet":
            detail = _text(root.find(".//ERROR")) or f"unexpected <{root.tag}> element"
            raise PubMedResponseError(f"EFetch error: {detail}")

        papers_by_id: dict[str, Paper] = {}
        for article in root.findall("PubmedArticle"):
            try:
                paper = parse_article(article)
            except (ValueError, TypeError):  # ValueError includes Pydantic ValidationError
                continue
            if paper is not None:
                papers_by_id.setdefault(paper.pmid, paper)
        # EFetch doesn't promise to keep our order; restore ESearch's relevance order.
        return [papers_by_id[pmid] for pmid in pmids if pmid in papers_by_id]


def _ncbi_error_detail(response: httpx.Response) -> str:
    """NCBI often explains 4xx errors in a JSON body, e.g. {"error": "API key invalid"}."""
    try:
        data = response.json()
    except ValueError:
        return ""
    if isinstance(data, dict) and isinstance(data.get("error"), str):
        return f": {data['error']}"
    return ""


# ---------- XML parsing helpers ----------

_MONTHS = {name.lower(): number for number, name in enumerate(calendar.month_abbr) if name}


def _text(element: ET.Element | None) -> str | None:
    """All text inside an element (including nested tags like <i>), whitespace-collapsed."""
    if element is None:
        return None
    text = " ".join("".join(element.itertext()).split())
    return text or None


def _parse_abstract(article: ET.Element) -> str | None:
    sections = []
    for part in article.findall("Abstract/AbstractText"):
        text = _text(part)
        if not text:
            continue
        label = part.get("Label")
        sections.append(f"{label}: {text}" if label else text)
    return "\n\n".join(sections) or None


def _parse_authors(article: ET.Element) -> list[Author]:
    authors = []
    for author in article.findall("AuthorList/Author"):
        collective = _text(author.find("CollectiveName"))
        last = _text(author.find("LastName"))
        fore = _text(author.find("ForeName")) or _text(author.find("Initials"))
        name = collective or " ".join(p for p in (fore, last) if p)
        if not name:
            continue
        authors.append(
            Author(name=name, affiliation=_text(author.find("AffiliationInfo/Affiliation")))
        )
    return authors


def _month_number(value: str | None) -> int | None:
    """'Jan', 'January', '1' or '01' -> 1. Unknown values -> None."""
    if not value:
        return None
    if value.isdigit():
        number = int(value)
        return number if 1 <= number <= 12 else None
    return _MONTHS.get(value[:3].lower())


def _iso_date(year: int, month: int | None, day: int | None) -> str:
    """Most precise valid ISO date for the parts we have; invalid parts are dropped."""
    if month is not None:
        if day is not None:
            try:
                period_bounds(year, month, day)
                return f"{year:04d}-{month:02d}-{day:02d}"
            except ValueError:
                pass
        return f"{year:04d}-{month:02d}"
    return f"{year:04d}"


def _parse_date_element(element: ET.Element | None) -> tuple[str | None, str | None, int | None]:
    """Parse <PubDate> or <ArticleDate> into (display text, ISO date, year)."""
    if element is None:
        return None, None, None

    # Some records only have a free-text MedlineDate, e.g. "2021 Jan-Feb".
    # Only the year is reliable there, so the ISO date covers the whole year.
    medline_date = _text(element.find("MedlineDate"))
    if medline_date:
        match = re.search(r"\b(\d{4})\b", medline_date)
        year = int(match.group(1)) if match else None
        return medline_date, (f"{year:04d}" if year else None), year

    year_text, month_text, day_text = (
        _text(element.find(tag)) for tag in ("Year", "Month", "Day")
    )
    display = " ".join(p for p in (year_text, month_text, day_text) if p) or None
    if not year_text or not year_text.isdigit() or int(year_text) < 1000:
        return display, None, None

    year = int(year_text)
    month = _month_number(month_text)
    day = int(day_text) if day_text and day_text.isdigit() and month else None
    return display, _iso_date(year, month, day), year


def _parse_doi(pubmed_article: ET.Element) -> str | None:
    for id_el in pubmed_article.findall("PubmedData/ArticleIdList/ArticleId"):
        if id_el.get("IdType") == "doi":
            return _text(id_el)
    for loc in pubmed_article.findall("MedlineCitation/Article/ELocationID"):
        if loc.get("EIdType") == "doi":
            return _text(loc)
    return None


def parse_article(pubmed_article: ET.Element) -> Paper | None:
    """Convert one <PubmedArticle> element into a Paper. Returns None if it has no PMID."""
    citation = pubmed_article.find("MedlineCitation")
    if citation is None:
        return None
    pmid = _text(citation.find("PMID"))
    article = citation.find("Article")
    if not pmid or article is None:
        return None

    display_date, iso_date, year = _parse_date_element(article.find("Journal/JournalIssue/PubDate"))
    _, electronic_iso, electronic_year = _parse_date_element(article.find("ArticleDate"))
    if iso_date is None and electronic_iso is not None:
        # No usable print date: fall back to the electronic publication date.
        iso_date, year = electronic_iso, electronic_year
        display_date = display_date or electronic_iso

    doi = _parse_doi(pubmed_article)
    title = (
        _text(article.find("ArticleTitle"))
        or _text(article.find("VernacularTitle"))
        or NO_TITLE_PLACEHOLDER
    )

    return Paper(
        pmid=pmid,
        title=title,
        abstract=_parse_abstract(article),
        authors=_parse_authors(article),
        journal=_text(article.find("Journal/Title")),
        publication_date=display_date,
        publication_year=year,
        publication_date_iso=iso_date,
        electronic_date_iso=electronic_iso,
        publication_types=[
            t for el in article.findall("PublicationTypeList/PublicationType")
            if (t := _text(el))
        ],
        languages=[code for el in article.findall("Language") if (code := _text(el))],
        doi=doi,
        doi_url=f"https://doi.org/{doi}" if doi else None,
        pubmed_url=f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
    )
