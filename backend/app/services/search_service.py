"""Search pipeline: ESearch -> EFetch -> dedupe -> date filter -> rank -> limit."""

from datetime import date

from app.config import Settings
from app.models import ArticleType, Language, Period, SearchResponse
from app.services.dates import has_known_date, paper_matches_date_range
from app.services.dedup import deduplicate_papers
from app.services.filters import build_pubmed_term
from app.services.pubmed import PubMedClient
from app.services.ranking import rank_papers


def candidate_pool_size(max_results: int, settings: Settings) -> int:
    """How many PMIDs to request from ESearch before re-ranking and filtering."""
    pool = max_results * settings.search_candidate_multiplier
    return max(max_results, min(pool, settings.search_max_candidates))


async def search_papers(
    client: PubMedClient,
    settings: Settings,
    query: str,
    *,
    max_results: int,
    start_date: date | None = None,
    end_date: date | None = None,
    include_undated: bool = False,
    period: Period = Period.ALL,
    article_types: list[ArticleType] | None = None,
    languages: list[Language] | None = None,
) -> SearchResponse:
    """Run a search. start_date/end_date are the effective range (period already applied)."""
    warnings: list[str] = []
    article_types = list(dict.fromkeys(article_types or []))
    languages = list(dict.fromkeys(languages or []))
    pubmed_term = build_pubmed_term(query, article_types, languages)

    total, pmids = await client.esearch(
        pubmed_term, candidate_pool_size(max_results, settings), start_date, end_date
    )
    papers = await client.efetch(pmids)
    if skipped := len(pmids) - len(papers):
        warnings.append(f"{skipped} PubMed record(s) could not be retrieved or parsed and were skipped.")

    papers, duplicates_removed = deduplicate_papers(papers)

    in_range = [
        p
        for p in papers
        if paper_matches_date_range(p, start_date, end_date, include_undated=include_undated)
    ]
    excluded_by_date = len(papers) - len(in_range)
    if excluded_by_date and not include_undated:
        undated = sum(1 for p in papers if not has_known_date(p))
        if undated:
            warnings.append(
                f"{undated} paper(s) without a usable publication date were excluded; "
                "set include_undated=true to keep them."
            )

    # Rank by the user's own words only, not the filter tags added for PubMed.
    ranked = rank_papers(
        query,
        in_range,
        title_weight=settings.ranking_title_weight,
        abstract_weight=settings.ranking_abstract_weight,
    )[:max_results]

    if missing := sum(1 for p in ranked if p.abstract is None):
        warnings.append(f"{missing} returned paper(s) have no abstract in PubMed.")

    return SearchResponse(
        query=query,
        total_results=total,
        returned=len(ranked),
        start_date=start_date.isoformat() if start_date else None,
        end_date=end_date.isoformat() if end_date else None,
        period=period,
        article_types=article_types,
        languages=languages,
        pubmed_query=pubmed_term,
        duplicates_removed=duplicates_removed,
        excluded_by_date=excluded_by_date,
        warnings=warnings,
        papers=ranked,
    )
