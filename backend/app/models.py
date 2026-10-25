"""Pydantic models describing the data our API accepts and returns."""

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, EmailStr, Field, StringConstraints, field_validator, model_validator

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


# ---------- Accounts, preferences and saved searches (Milestone 5) ----------

PASSWORD_MIN_LENGTH = 10
PASSWORD_MAX_LENGTH = 128  # bounds hashing cost; long passphrases are still welcome
MAX_RESEARCH_INTERESTS = 20
MAX_SAVED_SEARCHES_PER_USER = 100


class RegisterRequest(BaseModel):
    model_config = {"extra": "forbid"}

    email: EmailStr
    password: str = Field(min_length=PASSWORD_MIN_LENGTH, max_length=PASSWORD_MAX_LENGTH)


class LoginRequest(BaseModel):
    model_config = {"extra": "forbid"}

    email: EmailStr
    password: str = Field(min_length=1, max_length=PASSWORD_MAX_LENGTH)


class UserOut(BaseModel):
    id: uuid.UUID
    email: str
    created_at: datetime


ResearchInterest = Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=100)]


class PreferencesIn(BaseModel):
    model_config = {"extra": "forbid"}

    summary_level: SummaryLevel
    research_interests: list[ResearchInterest] = Field(default_factory=list, max_length=MAX_RESEARCH_INTERESTS)

    @field_validator("research_interests")
    @classmethod
    def _dedupe_interests(cls, interests: list[str]) -> list[str]:
        """Collapse inner whitespace and drop case-insensitive duplicates, keeping order."""
        seen: set[str] = set()
        unique = []
        for interest in (" ".join(i.split()) for i in interests):
            if interest.lower() not in seen:
                seen.add(interest.lower())
                unique.append(interest)
        return unique


class PreferencesOut(BaseModel):
    summary_level: SummaryLevel
    research_interests: list[str]


class AccountOut(BaseModel):
    user: UserOut
    preferences: PreferencesOut


class SavedSearchFilters(BaseModel):
    """The search filters stored with a saved search; same values /api/search accepts."""

    model_config = {"extra": "forbid"}

    period: Period = Period.ALL
    start_date: str | None = Field(default=None, max_length=10)
    end_date: str | None = Field(default=None, max_length=10)
    include_undated: bool = False
    article_types: list[ArticleType] = Field(default_factory=list, max_length=len(ArticleType))
    languages: list[Language] = Field(default_factory=list, max_length=len(Language))
    max_results: int = Field(default=20, ge=1, le=100)

    @model_validator(mode="after")
    def _check_dates(self) -> "SavedSearchFilters":
        from app.services.dates import parse_date_bound  # local import: dates.py imports this module

        self.start_date = self.start_date.strip() if self.start_date and self.start_date.strip() else None
        self.end_date = self.end_date.strip() if self.end_date and self.end_date.strip() else None
        start = parse_date_bound(self.start_date, is_end=False) if self.start_date else None
        end = parse_date_bound(self.end_date, is_end=True) if self.end_date else None
        if start and end and start > end:
            raise ValueError("start_date must be on or before end_date.")
        self.article_types = list(dict.fromkeys(self.article_types))
        self.languages = list(dict.fromkeys(self.languages))
        return self


class SavedSearchCreate(BaseModel):
    model_config = {"extra": "forbid"}

    name: Annotated[str, StringConstraints(strip_whitespace=True, max_length=120)] = ""
    query: Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=500)]
    filters: SavedSearchFilters = Field(default_factory=SavedSearchFilters)


class SavedSearchOut(BaseModel):
    id: uuid.UUID
    name: str
    query: str
    filters: SavedSearchFilters
    created_at: datetime


# ---------- Research subscriptions (Step A: stored settings, no delivery yet) ----------

MAX_SUBSCRIPTIONS_PER_USER = 50
SUBSCRIPTION_TOPIC_MAX_LENGTH = 200


class SubscriptionFrequency(StrEnum):
    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"


class SubscriptionIn(BaseModel):
    """Create/replace body for /api/subscriptions. Validated fully on the server."""

    model_config = {"extra": "forbid"}

    topic: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=2, max_length=SUBSCRIPTION_TOPIC_MAX_LENGTH)
    ]
    frequency: SubscriptionFrequency
    weekday: int | None = Field(default=None, ge=0, le=6, description="0 = Sunday … 6 = Saturday; weekly only.")
    month_day: int | None = Field(default=None, ge=1, le=28, description="1-28; monthly only.")
    delivery_time: str = Field(pattern=r"^([01]\d|2[0-3]):[0-5]\d$", description='24-hour "HH:MM".')
    time_zone: str = Field(max_length=64, description='IANA time zone, e.g. "America/New_York".')
    paper_count: Literal[5, 10, 15, 20]
    reading_level: SummaryLevel
    email_enabled: bool = True
    email_when_no_new_papers: bool = False

    @field_validator("topic")
    @classmethod
    def _topic_has_words(cls, topic: str) -> str:
        from app.services.text import normalize_title  # local import keeps models.py dependency-free

        topic = " ".join(topic.split())
        if not normalize_title(topic):
            raise ValueError("Topic must contain letters or numbers.")
        return topic

    @field_validator("time_zone")
    @classmethod
    def _known_time_zone(cls, time_zone: str) -> str:
        import zoneinfo

        if time_zone not in zoneinfo.available_timezones():
            raise ValueError("Unknown time zone.")
        return time_zone

    @model_validator(mode="after")
    def _schedule_fields(self) -> "SubscriptionIn":
        """Require the day the frequency needs; clear the one it doesn't."""
        if self.frequency is SubscriptionFrequency.WEEKLY:
            if self.weekday is None:
                raise ValueError("weekday is required for weekly subscriptions.")
            self.month_day = None
        elif self.frequency is SubscriptionFrequency.MONTHLY:
            if self.month_day is None:
                raise ValueError("month_day is required for monthly subscriptions.")
            self.weekday = None
        else:
            self.weekday = None
            self.month_day = None
        return self


class SubscriptionOut(BaseModel):
    id: uuid.UUID
    topic: str
    frequency: SubscriptionFrequency
    weekday: int | None
    month_day: int | None
    delivery_time: str
    time_zone: str
    paper_count: int
    reading_level: SummaryLevel
    email_enabled: bool
    email_when_no_new_papers: bool
    delivery_active: bool = Field(
        default=False,
        description="Always false for now: there is no scheduler, so nothing is sent automatically "
        "(Step D). email_enabled is only a stored preference. Manual test emails are separate "
        "(/api/digests/test-send).",
    )
    created_at: datetime
    updated_at: datetime


# ---------- AI usage (Step B) ----------


class AiUsageOut(BaseModel):
    used: int = Field(description="Successful AI analyses today (UTC).")
    limit: int = Field(description="Per-user daily limit.")
    remaining: int = Field(description="Analyses still available today (also respects the overall daily cap).")
    resets_at: datetime = Field(description="Next reset (midnight UTC).")


# ---------- Research digests (Step C: manual test emails only) ----------

MAX_DIGEST_SUBSCRIPTIONS = 3


class DigestRequest(BaseModel):
    """Which subscriptions to include. The recipient is never part of the request."""

    model_config = {"extra": "forbid"}

    subscription_ids: list[uuid.UUID] = Field(min_length=1, max_length=MAX_DIGEST_SUBSCRIPTIONS)

    @field_validator("subscription_ids")
    @classmethod
    def _unique(cls, ids: list[uuid.UUID]) -> list[uuid.UUID]:
        return list(dict.fromkeys(ids))


class DigestAiStatus(StrEnum):
    GENERATED = "generated"  # Gemini summaries included (some may be withheld, see summary_note)
    LIMIT_REACHED = "limit_reached"  # daily AI allowance used up: abstract excerpts instead
    FAILED = "failed"  # Gemini error or unusable output (refunded): abstract excerpts instead
    NOT_NEEDED = "not_needed"  # no paper had an abstract to summarize


class DigestPaper(BaseModel):
    pmid: str
    title: str
    authors: list[str]
    journal: str | None
    publication_date: str | None
    doi: str | None
    doi_url: str | None
    pubmed_url: str
    ai_summary: str | None = Field(description="Gemini summary of the abstract, if available.")
    abstract_excerpt: str | None = Field(description="Start of the abstract, shown when there is no AI summary.")
    summary_note: str | None = Field(description="Why there is no AI summary, if there isn't one.")


class DigestSection(BaseModel):
    subscription_id: uuid.UUID
    topic: str
    frequency: SubscriptionFrequency
    reading_level: SummaryLevel
    window: str = Field(description='Publication window searched, e.g. "Past week".')
    used_fallback: bool = Field(description="True if the window had no papers and any date was used instead.")
    total_results: int
    papers: list[DigestPaper]
    ai_status: DigestAiStatus
    ai_note: str | None = None


class DigestOut(BaseModel):
    subject: str
    generated_at: datetime
    model: str | None = Field(description="Gemini model used for summaries, if any.")
    sections: list[DigestSection]
    disclaimer: str


class EmailStatusOut(BaseModel):
    enabled: bool = Field(description="EMAIL_ENABLED on the server.")
    configured: bool = Field(description="RESEND_API_KEY is set (its value is never returned).")
    recipient: str = Field(description="Test digests go only to the signed-in account's email.")
    recipient_allowed: bool = Field(description="The account email is listed in EMAIL_TEST_RECIPIENTS.")
    sender: str
    test_sender: bool = Field(description="Using Resend's onboarding@resend.dev test sender.")
    sends_per_hour: int
    automatic_delivery_active: bool = Field(default=False, description="Always false: scheduling is Step D.")


class TestSendOut(BaseModel):
    sent_to: str
    provider_message_id: str
    digest: DigestOut
