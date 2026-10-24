"use client";

import { useId, type FormEvent } from "react";

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
}: SearchHeroProps) {
  const inputId = useId();
  const errorId = `${inputId}-error`;

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    onSubmit();
  }

  return (
    <section
      aria-labelledby={`${inputId}-heading`}
      className={`mx-auto w-full max-w-3xl text-center ${compact ? "py-6" : "py-14 sm:py-24"}`}
    >
      <h1
        id={`${inputId}-heading`}
        className={`font-bold tracking-tight text-slate-900 dark:text-slate-50 ${compact ? "sr-only" : "text-3xl sm:text-4xl"}`}
      >
        Discover biomedical research
      </h1>
      {!compact && (
        <p className="mx-auto mt-3 max-w-xl text-slate-600 dark:text-slate-400">
          Search PubMed, filter by date, article type and language, and rank papers by relevance to your question.
        </p>
      )}

      <form onSubmit={handleSubmit} noValidate role="search" className={compact ? "" : "mt-8"}>
        <label htmlFor={inputId} className="sr-only">
          Search PubMed
        </label>
        <div className="flex items-center gap-2 rounded-2xl border border-slate-300 bg-white p-2 shadow-md transition focus-within:border-teal-600 focus-within:ring-4 focus-within:ring-teal-600/15 dark:border-slate-700 dark:bg-slate-900">
          <svg
            aria-hidden="true"
            viewBox="0 0 24 24"
            className="ml-2 size-5 shrink-0 text-slate-400"
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
            placeholder="Search for a keyword or phrase, or ask a question"
            autoComplete="off"
            aria-invalid={Boolean(queryError)}
            aria-describedby={queryError ? errorId : undefined}
            className="min-w-0 flex-1 bg-transparent px-1 py-2.5 text-base text-slate-900 placeholder:text-slate-400 focus:outline-none sm:text-lg dark:text-slate-100"
          />
          <button
            type="submit"
            disabled={isLoading}
            className="inline-flex shrink-0 items-center gap-2 rounded-xl bg-teal-700 px-4 py-2.5 font-semibold text-white transition hover:bg-teal-800 focus-visible:ring-2 focus-visible:ring-teal-600 focus-visible:ring-offset-2 focus-visible:outline-none disabled:cursor-not-allowed disabled:opacity-70 sm:px-6"
          >
            {isLoading && (
              <span
                aria-hidden="true"
                className="size-4 animate-spin rounded-full border-2 border-white/40 border-t-white"
              />
            )}
            {isLoading ? "Searching…" : "Search"}
          </button>
        </div>
        {queryError && (
          <p id={errorId} className="mt-2 text-left text-sm text-red-700 dark:text-red-400">
            {queryError}
          </p>
        )}
      </form>

      <div className="mt-5 flex flex-wrap items-start justify-center gap-x-8 gap-y-4 text-left">
        <SegmentedControl
          legend="Summary level"
          options={SUMMARY_LEVEL_OPTIONS}
          value={summaryLevel}
          onChange={onSummaryLevelChange}
          hint="For AI summaries, coming in a later update."
        />
        <SegmentedControl
          legend="Publication period"
          options={PERIOD_OPTIONS}
          value={period}
          onChange={onPeriodChange}
          hint="Counted back from today, by PubMed publication date."
        />
      </div>
    </section>
  );
}
