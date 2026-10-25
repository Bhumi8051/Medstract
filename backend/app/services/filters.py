"""Turn API filter values into PubMed query syntax.

Only allowlisted values reach PubMed: an unknown publication type would
silently return zero results instead of an error.
"""

from app.models import ArticleType

# PubMed publication type names, used with the [pt] field tag.
ARTICLE_TYPE_TERMS: dict[ArticleType, str] = {
    ArticleType.REVIEW: "Review",
    ArticleType.SYSTEMATIC_REVIEW: "Systematic Review",
    ArticleType.META_ANALYSIS: "Meta-Analysis",
    ArticleType.RANDOMIZED_CONTROLLED_TRIAL: "Randomized Controlled Trial",
    ArticleType.CLINICAL_TRIAL: "Clinical Trial",
    ArticleType.OBSERVATIONAL_STUDY: "Observational Study",
    ArticleType.CASE_REPORTS: "Case Reports",
    ArticleType.COMPARATIVE_STUDY: "Comparative Study",
    ArticleType.GUIDELINE: "Guideline",
    ArticleType.PRACTICE_GUIDELINE: "Practice Guideline",
}

def _or_group(terms: list[str]) -> str:
    return "(" + " OR ".join(terms) + ")"


def build_pubmed_term(query: str, article_types: list[ArticleType] | None = None) -> str:
    """Combine the user's query with the article-type filter.

    The query is wrapped in parentheses so any PubMed syntax inside it
    (e.g. "a OR b") can't swallow the filter. Several types are OR'ed:

        (asthma) AND ("Review"[pt] OR "Meta-Analysis"[pt])
    """
    parts = [f"({query})"]
    if article_types:
        unique = list(dict.fromkeys(article_types))
        parts.append(_or_group([f'"{ARTICLE_TYPE_TERMS[t]}"[pt]' for t in unique]))
    return parts[0] if len(parts) == 1 else " AND ".join(parts)
