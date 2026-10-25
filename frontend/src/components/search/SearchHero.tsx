"use client";

import { useId, type FormEvent } from "react";

import { SubscribeBell } from "@/components/subscriptions/SubscribeBell";
import { SegmentedControl } from "@/components/ui/SegmentedControl";
import type { Period } from "@/lib/api/types";
import { PERIOD_OPTIONS, SUMMARY_LEVEL_OPTIONS, type SummaryLevel } from "@/lib/filters";
import { QUERY_MAX_LENGTH } from "@/lib/validation";

interface SearchHeroProps {
  query: string;
  onQueryChange: (value: string) => void;
  onSubmit: () => void;
  queryError: string | null;
  isLoading: boolean;
  summaryLevel: SummaryLevel;
  onSummaryLevelChange: (level: SummaryLevel) => void;
  period: Period;
  onPeriodChange: (period: Period) => void;
  /** Smaller layout once results are showing. */
  compact: boolean;
  /** The signed-in user's research interests, offered as one-click searches. */
  interests?: string[];
  onInterestSelect?: (interest: string) => void;
}

export function SearchHero({
  query,
  onQueryChange,
  onSubmit,
  queryError,
  isLoading,
  summaryLevel,
  onSummaryLevelChange,
  period,
  onPeriodChange,
  compact,
  interests = [],
  onInterestSelect,
}: SearchHeroProps) {
  const inputId = useId();
  const errorId = `${inputId}-error`;

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    onSubmit();
  }

  return (
    <section aria-labelledby={`${inputId}-heading`}>
      {/* Band with the heading, search box and interests: a cream section in the light theme, deep navy in the dark. */}
      <div className="border-b border-navy-200 bg-navy-100 dark:border-navy-800 dark:bg-navy-800">
        <div className={`page-container ${compact ? "py-6 sm:py-8" : "py-16 sm:py-24"}`}>
          <div className="mx-auto max-w-3xl text-center">
            <h1
              id={`${inputId}-heading`}
              className={`font-bold tracking-tight text-navy-950 dark:text-white ${compact ? "sr-only" : "text-3xl sm:text-5xl"}`}
            >
              Discover biomedical research
            </h1>
            {!compact && (
              <p className="mx-auto mt-4 max-w-xl text-base text-navy-600 sm:text-lg dark:text-navy-200">
                Search PubMed, filter by date and article type, and rank papers by relevance to your question.
              </p>
            )}

            <form onSubmit={handleSubmit} noValidate role="search" className={compact ? "" : "mt-10"}>
              <label htmlFor={inputId} className="sr-only">
                Search PubMed
              </label>
              <div className="flex items-center gap-2 rounded-2xl border border-navy-200 bg-white p-2 shadow-sm transition focus-within:border-brand-600 focus-within:ring-4 focus-within:ring-brand-600/15 dark:border-navy-700 dark:bg-navy-950 dark:focus-within:border-brand-300 dark:focus-within:ring-brand-100/25">
                <svg
                  aria-hidden="true"
                  viewBox="0 0 24 24"
                  className="ml-2 size-5 shrink-0 text-navy-400"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="2"
                >
                  <circle cx="11" cy="11" r="7" />
                  <path d="m20 20-3.5-3.5" strokeLinecap="round" />
                </svg>
                <input
                  id={inputId}
                  type="search"
                  value={query}
                  onChange={(e) => onQueryChange(e.target.value)}
                  maxLength={QUERY_MAX_LENGTH}
                  placeholder="Enter keywords or key phrases (e.g., acute myeloid leukemia)"
                  autoComplete="off"
                  aria-invalid={Boolean(queryError)}
                  aria-describedby={queryError ? errorId : undefined}
                  className="min-w-0 flex-1 bg-transparent px-1 py-2.5 text-base text-navy-900 placeholder:text-navy-400 focus:outline-none sm:text-lg dark:text-navy-100"
                />
                <button
                  type="submit"
                  disabled={isLoading}
                  className="inline-flex shrink-0 items-center gap-2 rounded-xl bg-brand-600 px-4 py-2.5 font-semibold text-white transition hover:bg-brand-700 focus-visible:ring-2 focus-visible:ring-brand-600 focus-visible:ring-offset-2 focus-visible:outline-none disabled:cursor-not-allowed disabled:opacity-70 sm:px-6"
                >
                  {isLoading && (
                    <span
                      aria-hidden="true"
                      className="size-4 animate-spin rounded-full border-2 border-white/40 border-t-white"
                    />
                  )}
                  {isLoading ? "Searching…" : "Search"}
                </button>
                {/* Subscribe to this topic (prefilled from the search box). */}
                <SubscribeBell topic={query} readingLevel={summaryLevel} />
              </div>
              {queryError && (
                <p id={errorId} className="mt-2 text-left text-sm font-medium text-red-700 dark:text-red-300">
                  {queryError}
                </p>
              )}
            </form>

            {interests.length > 0 && onInterestSelect && (
              <div className="mt-4 flex flex-wrap items-center justify-center gap-2 text-sm">
                <span className="text-navy-600 dark:text-navy-300">Your interests:</span>
                {interests.map((interest) => (
                  <button
                    key={interest}
                    type="button"
                    disabled={isLoading}
                    onClick={() => onInterestSelect(interest)}
                    className="rounded-full border border-brand-200 bg-white px-3 py-1 text-brand-800 transition hover:border-brand-500 focus-visible:ring-2 focus-visible:ring-brand-600 focus-visible:outline-none disabled:opacity-60 dark:border-white/20 dark:bg-white/5 dark:text-navy-50 dark:hover:border-brand-100 dark:hover:text-white dark:focus-visible:ring-brand-100"
                  >
                    {interest}
                  </button>
                ))}
              </div>
            )}
          </div>
        </div>
      </div>

      {/* Search settings strip, below the band. */}
      <div className="border-b border-navy-200 bg-white dark:border-navy-800 dark:bg-navy-900">
        <div
          className={`page-container flex flex-wrap items-start gap-x-10 gap-y-5 py-5 ${compact ? "justify-start" : "justify-center"}`}
        >
          <SegmentedControl
            legend="Summary level"
            options={SUMMARY_LEVEL_OPTIONS}
            value={summaryLevel}
            onChange={onSummaryLevelChange}
            hint="Used when you click “Analyze paper” on a result."
          />
          <SegmentedControl
            legend="Publication period"
            options={PERIOD_OPTIONS}
            value={period}
            onChange={onPeriodChange}
            hint="Counted back from today, by PubMed publication date."
          />
        </div>
      </div>
    </section>
  );
}
