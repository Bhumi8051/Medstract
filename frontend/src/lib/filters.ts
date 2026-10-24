/**
 * Search filter state and the option lists shown in the UI.
 *
 * Option values must match the backend enums (backend/app/models.py); the
 * backend rejects anything else with a 422. `SearchFilters` is plain JSON so a
 * future "saved searches" feature can store it as-is.
 */

import type { ArticleType, Language, Period, SearchParams } from "./api/types";

export interface Option<T extends string | number> {
  value: T;
  label: string;
}

export const PERIOD_OPTIONS: Option<Period>[] = [
  { value: "week", label: "Past Week" },
  { value: "month", label: "Past Month" },
  { value: "all", label: "All Time" },
];

export const ARTICLE_TYPE_OPTIONS: Option<ArticleType>[] = [
  { value: "review", label: "Review" },
  { value: "systematic_review", label: "Systematic Review" },
  { value: "meta_analysis", label: "Meta-Analysis" },
  { value: "randomized_controlled_trial", label: "Randomized Controlled Trial" },
  { value: "clinical_trial", label: "Clinical Trial" },
  { value: "observational_study", label: "Observational Study" },
  { value: "case_reports", label: "Case Reports" },
  { value: "comparative_study", label: "Comparative Study" },
  { value: "guideline", label: "Guideline" },
  { value: "practice_guideline", label: "Practice Guideline" },
];

export const LANGUAGE_OPTIONS: Option<Language>[] = [
  { value: "english", label: "English" },
  { value: "spanish", label: "Spanish" },
  { value: "french", label: "French" },
  { value: "german", label: "German" },
  { value: "chinese", label: "Chinese" },
  { value: "japanese", label: "Japanese" },
  { value: "italian", label: "Italian" },
  { value: "portuguese", label: "Portuguese" },
  { value: "russian", label: "Russian" },
];

/** Allowed by the backend's default limits (1-100). */
export const RESULT_LIMIT_OPTIONS: Option<number>[] = [10, 20, 50, 100].map((n) => ({
  value: n,
  label: `${n} results`,
}));

export interface SearchFilters {
  period: Period;
  /** "" or YYYY / YYYY-MM / YYYY-MM-DD */
  startDate: string;
  endDate: string;
  includeUndated: boolean;
  articleTypes: ArticleType[];
  languages: Language[];
  maxResults: number;
}

export const DEFAULT_FILTERS: SearchFilters = {
  period: "all",
  startDate: "",
  endDate: "",
  includeUndated: false,
  articleTypes: [],
  languages: [],
  maxResults: 20,
};

export function toSearchParams(query: string, filters: SearchFilters): SearchParams {
  return {
    query,
    period: filters.period,
    startDate: filters.startDate || undefined,
    endDate: filters.endDate || undefined,
    includeUndated: filters.includeUndated || undefined,
    articleTypes: filters.articleTypes,
    languages: filters.languages,
    maxResults: filters.maxResults,
  };
}

/** Number of filters that differ from the defaults (for the "Filters (n)" badge). */
export function countActiveFilters(filters: SearchFilters): number {
  return (
    (filters.period !== DEFAULT_FILTERS.period ? 1 : 0) +
    (filters.startDate || filters.endDate ? 1 : 0) +
    filters.articleTypes.length +
    filters.languages.length +
    (filters.maxResults !== DEFAULT_FILTERS.maxResults ? 1 : 0)
  );
}

export function labelFor<T extends string | number>(options: Option<T>[], value: T): string {
  return options.find((option) => option.value === value)?.label ?? String(value);
}

/** Toggle a value in a list, keeping the options' display order. */
export function toggleValue<T extends string>(list: T[], value: T, options: Option<T>[]): T[] {
  const next = list.includes(value) ? list.filter((v) => v !== value) : [...list, value];
  return options.map((o) => o.value).filter((v) => next.includes(v));
}

// ---------- summary level (UI only until the Gemini milestone) ----------

export type SummaryLevel = "high_school" | "college" | "phd";

export const SUMMARY_LEVEL_OPTIONS: Option<SummaryLevel>[] = [
  { value: "high_school", label: "High School" },
  { value: "college", label: "College" },
  { value: "phd", label: "PhD" },
];

export const DEFAULT_SUMMARY_LEVEL: SummaryLevel = "college";
