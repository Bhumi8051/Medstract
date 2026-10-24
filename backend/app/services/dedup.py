"""Remove duplicate papers: same PMID, else same DOI, else same normalized title."""

from app.models import NO_TITLE_PLACEHOLDER, Paper
from app.services.text import normalize_doi, normalize_title

# Short titles like "Erratum" or "Editorial" are too generic to treat as duplicates.
MIN_TITLE_LENGTH_FOR_DEDUP = 20


def _dedup_keys(paper: Paper) -> list[str]:
    """Identity keys in priority order: PMID, then DOI, then normalized title."""
    keys = [f"pmid:{paper.pmid.strip()}"]
    if doi := normalize_doi(paper.doi):
        keys.append(f"doi:{doi}")
    if paper.title != NO_TITLE_PLACEHOLDER:
        title = normalize_title(paper.title)
        if len(title) >= MIN_TITLE_LENGTH_FOR_DEDUP:
            keys.append(f"title:{title}")
    return keys


def deduplicate_papers(papers: list[Paper]) -> tuple[list[Paper], int]:
    """Return (unique papers in original order, number of duplicates removed).

    When two records collide, the earlier position is kept, but a record with an
    abstract replaces one without, since it is more useful downstream.
    """
    kept: list[Paper] = []
    index_by_key: dict[str, int] = {}

    for paper in papers:
        keys = _dedup_keys(paper)
        existing = next((index_by_key[k] for k in keys if k in index_by_key), None)
        if existing is None:
            position = len(kept)
            kept.append(paper)
        else:
            position = existing
            if kept[position].abstract is None and paper.abstract is not None:
                kept[position] = paper
        for key in keys:
            index_by_key.setdefault(key, position)

    return kept, len(papers) - len(kept)
