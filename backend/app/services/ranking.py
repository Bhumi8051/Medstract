"""Keyword-overlap relevance ranking.

score = (title_weight * title_overlap + abstract_weight * abstract_overlap)
        / (title_weight + abstract_weight)

where *_overlap is the fraction of distinct query terms found in that field.
The result is always between 0 and 1.
"""

from app.models import NO_TITLE_PLACEHOLDER, Paper
from app.services.text import tokenize, tokenize_query


def score_paper(
    query_terms: set[str],
    paper: Paper,
    *,
    title_weight: float = 3.0,
    abstract_weight: float = 1.0,
) -> float:
    total_weight = title_weight + abstract_weight
    if not query_terms or total_weight <= 0:
        return 0.0

    title = "" if paper.title == NO_TITLE_PLACEHOLDER else paper.title
    title_terms = set(tokenize(title))
    abstract_terms = set(tokenize(paper.abstract))

    title_overlap = len(query_terms & title_terms) / len(query_terms)
    abstract_overlap = len(query_terms & abstract_terms) / len(query_terms)
    score = (title_weight * title_overlap + abstract_weight * abstract_overlap) / total_weight
    return round(score, 4)


def rank_papers(
    query: str,
    papers: list[Paper],
    *,
    title_weight: float = 3.0,
    abstract_weight: float = 1.0,
) -> list[Paper]:
    """Return copies of the papers with relevance_score set, best first.

    Python's sort is stable, so ties keep PubMed's own relevance order.
    """
    query_terms = set(tokenize_query(query))
    scored = [
        paper.model_copy(
            update={
                "relevance_score": score_paper(
                    query_terms,
                    paper,
                    title_weight=title_weight,
                    abstract_weight=abstract_weight,
                )
            }
        )
        for paper in papers
    ]
    return sorted(scored, key=lambda p: p.relevance_score or 0.0, reverse=True)
