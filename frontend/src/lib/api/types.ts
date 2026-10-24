/**
 * Types mirroring the FastAPI models in backend/app/models.py, checked against
 * the backend's GET /openapi.json. Keep them in sync.
 */

/** Relative publication period ending today (backend `Period`). */
export type Period = "all" | "week" | "month";

/** Supported PubMed publication types (backend `ArticleType`). */
export type ArticleType =
  | "review"
  | "systematic_review"
  | "meta_analysis"
  | "randomized_controlled_trial"
  | "clinical_trial"
  | "observational_study"
  | "case_reports"
  | "comparative_study"
  | "guideline"
  | "practice_guideline";

/** Supported article languages (backend `Language`). */
export type Language =
  | "english"
  | "spanish"
  | "french"
  | "german"
  | "chinese"
  | "japanese"
  | "italian"
  | "portuguese"
  | "russian";

export interface Author {
  name: string;
  affiliation: string | null;
}

export interface Paper {
  pmid: string;
  title: string;
  /** null when PubMed has no abstract for this paper. */
  abstract: string | null;
  authors: Author[];
  journal: string | null;
  /** Date as PubMed reports it, e.g. "2023 Jun 21" or "2021 Jan-Feb". */
  publication_date: string | null;
  publication_year: number | null;
  /** "YYYY", "YYYY-MM" or "YYYY-MM-DD". */
  publication_date_iso: string | null;
  electronic_date_iso: string | null;
  publication_types: string[];
  /** PubMed language codes, e.g. ["eng"]. */
  languages: string[];
  doi: string | null;
  doi_url: string | null;
  pubmed_url: string;
  /** 0-1 keyword-overlap score; title matches weigh more than abstract matches. */
  relevance_score: number | null;
}

export interface SearchResponse {
  query: string;
  /** Total PubMed matches for the query (with all filters applied). */
  total_results: number;
  returned: number;
  /** Effective date range as YYYY-MM-DD (period combined with custom range), or null. */
  start_date: string | null;
  end_date: string | null;
  period: Period;
  article_types: ArticleType[];
  languages: Language[];
  /** The exact term sent to PubMed ESearch, including filter tags. */
  pubmed_query: string;
  duplicates_removed: number;
  excluded_by_date: number;
  warnings: string[];
  papers: Paper[];
}

/** Inputs for GET /api/search. Dates are YYYY, YYYY-MM or YYYY-MM-DD. */
export interface SearchParams {
  query: string;
  maxResults?: number;
  startDate?: string;
  endDate?: string;
  includeUndated?: boolean;
  period?: Period;
  articleTypes?: ArticleType[];
  languages?: Language[];
}

// ---------- AI paper analysis (backend PaperAnalysis) ----------

/** Reading level for AI analyses (backend `SummaryLevel`). */
export type SummaryLevel = "high_school" | "college" | "phd";

/** Where a statement in the report comes from (backend `EvidenceBasis`). */
export type EvidenceBasis = "reported" | "interpretation" | "not_reported";

export interface ReportPoint {
  text: string;
  basis: EvidenceBasis;
}

export interface PaperReport {
  plain_language_overview: string;
  research_question: ReportPoint[];
  background: ReportPoint[];
  methods: ReportPoint[];
  key_findings: ReportPoint[];
  interpretation: ReportPoint[];
  limitations: ReportPoint[];
  not_established: ReportPoint[];
  further_questions: string[];
}

export interface PaperAnalysis {
  pmid: string;
  pubmed_url: string;
  title: string;
  summary_level: SummaryLevel;
  /** Gemini model that produced the report. */
  model: string;
  /** UTC ISO 8601 timestamp. */
  generated_at: string;
  abstract_available: boolean;
  /** What the analysis was (and was not) based on; written by the server, not the AI. */
  source_note: string;
  disclaimer: string;
  /** Automatic checks that flagged numbers or links not found in the PubMed record. */
  grounding_warnings: string[];
  report: PaperReport;
}

// ---------- Accounts, preferences and saved searches (backend Milestone 5) ----------

export interface User {
  id: string;
  email: string;
  created_at: string;
}

export interface Preferences {
  summary_level: SummaryLevel;
  research_interests: string[];
}

export interface Account {
  user: User;
  preferences: Preferences;
}

/** Filters stored with a saved search (backend `SavedSearchFilters`, snake_case). */
export interface SavedSearchFilters {
  period: Period;
  start_date: string | null;
  end_date: string | null;
  include_undated: boolean;
  article_types: ArticleType[];
  languages: Language[];
  max_results: number;
}

export interface SavedSearch {
  id: string;
  name: string;
  query: string;
  filters: SavedSearchFilters;
  created_at: string;
}
