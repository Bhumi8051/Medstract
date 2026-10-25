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
  max_results: number;
}

export interface SavedSearch {
  id: string;
  name: string;
  query: string;
  filters: SavedSearchFilters;
  created_at: string;
}

// ---------- Research subscriptions (backend /api/subscriptions) ----------

/** A stored research subscription (backend `SubscriptionOut`, snake_case). */
export interface SubscriptionApi {
  id: string;
  topic: string;
  frequency: "daily" | "weekly" | "monthly";
  /** 0 = Sunday … 6 = Saturday; null unless weekly. */
  weekday: number | null;
  /** 1-28; null unless monthly. */
  month_day: number | null;
  /** 24-hour "HH:MM". */
  delivery_time: string;
  time_zone: string;
  paper_count: 5 | 10 | 15 | 20;
  reading_level: SummaryLevel;
  email_enabled: boolean;
  email_when_no_new_papers: boolean;
  /**
   * True only if the scheduler would really email this subscription now (allowlist test mode, scheduler on,
   * address allowlisted, email on, not unsubscribed). Manual test emails are separate.
   */
  delivery_active: boolean;
  /** Next scheduled digest (ISO, UTC); null while email is off or unsubscribed. */
  next_run_at: string | null;
  /** Last scheduled digest the email service accepted. */
  last_sent_at: string | null;
  /** Set when an unsubscribe link in an email was used. */
  unsubscribed_at: string | null;
  created_at: string;
  updated_at: string;
}

/** Create/replace body (backend `SubscriptionIn`). */
export type SubscriptionInput = Omit<
  SubscriptionApi,
  "id" | "delivery_active" | "next_run_at" | "last_sent_at" | "unsubscribed_at" | "created_at" | "updated_at"
>;

/** Today's AI analysis allowance (backend `AiUsageOut`). Enforced on the server. */
export interface AiUsage {
  used: number;
  limit: number;
  remaining: number;
  /** Next reset, ISO 8601 (midnight UTC). */
  resets_at: string;
}

// ---------- Research digests (backend /api/digests, Step C: manual test emails) ----------

/** "skipped": AI was deliberately not requested (scheduled dry runs); abstract excerpts are shown. */
export type DigestAiStatus = "generated" | "limit_reached" | "failed" | "not_needed" | "skipped";

export interface DigestPaper {
  pmid: string;
  title: string;
  authors: string[];
  journal: string | null;
  publication_date: string | null;
  doi: string | null;
  doi_url: string | null;
  pubmed_url: string;
  ai_summary: string | null;
  abstract_excerpt: string | null;
  summary_note: string | null;
}

export interface DigestSection {
  subscription_id: string;
  topic: string;
  frequency: "daily" | "weekly" | "monthly";
  reading_level: SummaryLevel;
  window: string;
  used_fallback: boolean;
  total_results: number;
  papers: DigestPaper[];
  ai_status: DigestAiStatus;
  ai_note: string | null;
}

export interface Digest {
  subject: string;
  generated_at: string;
  model: string | null;
  sections: DigestSection[];
  disclaimer: string;
}

/** What a test send would do for the signed-in account (never includes the API key). */
export interface EmailStatus {
  enabled: boolean;
  configured: boolean;
  recipient: string;
  recipient_allowed: boolean;
  sender: string;
  test_sender: boolean;
  sends_per_hour: number;
  /** DIGEST_DELIVERY_MODE on the server. */
  delivery_mode: "off" | "dry_run" | "allowlist";
  /** DIGEST_SCHEDULER_ENABLED: the scheduler runs inside the backend. */
  scheduler_enabled: boolean;
  /** Scheduled digests would be emailed to this account now. */
  automatic_delivery_active: boolean;
}

export interface TestSendResult {
  sent_to: string;
  /** Resend accepted the email. Not a delivery confirmation. */
  delivery_status: "accepted";
  provider_message_id: string;
  digest: Digest;
}

// ---------- Scheduled digest history and unsubscribe (backend /api/digests/deliveries, /api/unsubscribe) ----------

export type DeliveryStatus =
  | "pending"
  | "sending"
  | "sent"
  | "dry_run"
  | "skipped_no_new"
  | "skipped_missed"
  | "skipped_disabled"
  | "failed"
  | "needs_review";

/** One scheduled run. Contains no email content or addresses. */
export interface DigestDelivery {
  id: string;
  subscription_id: string;
  topic: string;
  scheduled_for: string;
  status: DeliveryStatus;
  /** Short fixed code such as "unsubscribed" or "resend_429". */
  reason: string | null;
  attempts: number;
  papers_count: number | null;
  window_start: string | null;
  window_end: string | null;
  sent_at: string | null;
  mode: "dry_run" | "allowlist" | null;
}

export interface UnsubscribeResult {
  status: "subscribed" | "unsubscribed" | "already_unsubscribed";
  topic: string;
}
