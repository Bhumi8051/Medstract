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
