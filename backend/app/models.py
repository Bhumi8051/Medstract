"""Pydantic models describing the data our API accepts and returns."""

from enum import StrEnum

from pydantic import BaseModel, Field

# Used when a PubMed record has no title; ranking and dedup ignore it.
NO_TITLE_PLACEHOLDER = "[No title available]"


class Period(StrEnum):
    """Relative publication period, counted back from today."""

    ALL = "all"
    WEEK = "week"
    MONTH = "month"


class ArticleType(StrEnum):
    """Supported PubMed publication types (see services/filters.py for the [pt] terms)."""

    REVIEW = "review"
    SYSTEMATIC_REVIEW = "systematic_review"
    META_ANALYSIS = "meta_analysis"
    RANDOMIZED_CONTROLLED_TRIAL = "randomized_controlled_trial"
    CLINICAL_TRIAL = "clinical_trial"
    OBSERVATIONAL_STUDY = "observational_study"
    CASE_REPORTS = "case_reports"
    COMPARATIVE_STUDY = "comparative_study"
    GUIDELINE = "guideline"
    PRACTICE_GUIDELINE = "practice_guideline"


class Language(StrEnum):
    """Supported PubMed article languages (see services/filters.py for the [la] terms)."""

    ENGLISH = "english"
    SPANISH = "spanish"
    FRENCH = "french"
    GERMAN = "german"
    CHINESE = "chinese"
    JAPANESE = "japanese"
    ITALIAN = "italian"
    PORTUGUESE = "portuguese"
    RUSSIAN = "russian"


class Author(BaseModel):
    name: str
    affiliation: str | None = None


class Paper(BaseModel):
    pmid: str
    title: str
    abstract: str | None = Field(
        default=None, description="None when PubMed has no abstract for this paper."
    )
    authors: list[Author] = Field(default_factory=list)
    journal: str | None = None
    publication_date: str | None = Field(
        default=None, description="Date as PubMed reports it, e.g. '2023 Mar 15'."
    )
    publication_year: int | None = None
    publication_date_iso: str | None = Field(
        default=None,
        description="Normalized date at the precision known: 'YYYY', 'YYYY-MM' or 'YYYY-MM-DD'.",
    )
    electronic_date_iso: str | None = Field(
        default=None, description="Electronic (epub) date, same format as publication_date_iso."
    )
    publication_types: list[str] = Field(default_factory=list)
    languages: list[str] = Field(
        default_factory=list, description="PubMed language codes, e.g. ['eng'] or ['spa']."
    )
    doi: str | None = None
    doi_url: str | None = None
    pubmed_url: str
    relevance_score: float | None = Field(
        default=None,
        ge=0,
        le=1,
        description="0-1 keyword-overlap score; title matches weigh more than abstract matches.",
    )


class SearchResponse(BaseModel):
    query: str
    total_results: int = Field(
        description="Total matches in PubMed for this query (with the date range applied)."
    )
    returned: int = Field(description="Number of papers included in this response.")
    start_date: str | None = Field(
        default=None, description="Effective start date (YYYY-MM-DD), after combining period and range."
    )
    end_date: str | None = Field(
        default=None, description="Effective end date (YYYY-MM-DD), after combining period and range."
    )
    period: Period = Period.ALL
    article_types: list[ArticleType] = Field(default_factory=list)
    languages: list[Language] = Field(default_factory=list)
    pubmed_query: str = Field(
        default="", description="The exact term sent to PubMed ESearch, including filter tags."
    )
    duplicates_removed: int = 0
    excluded_by_date: int = Field(
        default=0, description="Candidates dropped because their date was outside the range or unknown."
    )
    warnings: list[str] = Field(default_factory=list)
    papers: list[Paper]


# ---------- AI paper analysis (Milestone 4) ----------


class SummaryLevel(StrEnum):
    """Reading level for AI analyses (matches the frontend selector)."""

    HIGH_SCHOOL = "high_school"
    COLLEGE = "college"
    PHD = "phd"


class EvidenceBasis(StrEnum):
    """Where a statement in the report comes from."""

    REPORTED = "reported"  # stated in the PubMed record (title, metadata or abstract)
    INTERPRETATION = "interpretation"  # the AI's own reading, not stated by the authors
    NOT_REPORTED = "not_reported"  # the PubMed record does not contain this information


class ReportPoint(BaseModel):
    text: str = Field(description="One concise statement.")
    basis: EvidenceBasis = Field(
        description=(
            "'reported' only if the statement is directly stated in the provided PubMed record; "
            "'interpretation' for your own explanation or inference; "
            "'not_reported' when the record does not contain the information."
        )
    )


# Gemini enforces minItems/maxItems (unlike string lengths), and Pydantic re-checks them.
MAX_POINTS = 8


class GeneratedReport(BaseModel):
    """The structured report Gemini must return (also sent to Gemini as the JSON schema)."""

    plain_language_overview: str = Field(description="2-4 sentence overview at the requested reading level.")
    research_question: list[ReportPoint] = Field(description="Research question or objective.", min_length=1, max_length=MAX_POINTS)
    background: list[ReportPoint] = Field(description="Background and motivation.", min_length=1, max_length=MAX_POINTS)
    methods: list[ReportPoint] = Field(description="Methods and study design.", min_length=1, max_length=MAX_POINTS)
    key_findings: list[ReportPoint] = Field(description="Key findings, exactly as reported.", min_length=1, max_length=MAX_POINTS)
    interpretation: list[ReportPoint] = Field(description="Interpretation and significance.", min_length=1, max_length=MAX_POINTS)
    limitations: list[ReportPoint] = Field(description="Limitations and caveats.", min_length=1, max_length=MAX_POINTS)
    not_established: list[ReportPoint] = Field(description="What the paper does not establish.", min_length=1, max_length=MAX_POINTS)
    further_questions: list[str] = Field(
        description="Questions for further investigation.", min_length=1, max_length=6
    )


class AnalyzeRequest(BaseModel):
    """Body of POST /api/papers/{pmid}/analyze. Paper content is fetched from PubMed, never sent by the browser."""

    model_config = {"extra": "forbid"}

    summary_level: SummaryLevel


class PaperAnalysis(BaseModel):
    pmid: str
    pubmed_url: str
    title: str
    summary_level: SummaryLevel
    model: str = Field(description="Gemini model that produced the report.")
    generated_at: str = Field(description="UTC timestamp (ISO 8601).")
    abstract_available: bool
    source_note: str = Field(description="What the analysis was (and was not) based on. Set by the server.")
    disclaimer: str
    grounding_warnings: list[str] = Field(
        default_factory=list,
        description="Automatic checks that flagged content not found in the PubMed record.",
    )
    report: GeneratedReport
