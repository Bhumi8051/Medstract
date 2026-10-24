"use client";

import { useRef, useState } from "react";

import { EmptyState } from "@/components/feedback/EmptyState";
import { ErrorAlert } from "@/components/feedback/ErrorAlert";
import { LoadingResults } from "@/components/feedback/LoadingResults";
import { FilterSidebar } from "@/components/filters/FilterSidebar";
import { ActiveFilterChips } from "@/components/results/ActiveFilterChips";
import { PaperList } from "@/components/results/PaperList";
import { ResultsSummary } from "@/components/results/ResultsSummary";
import { ApiError, searchPapers } from "@/lib/api/client";
import type { SearchResponse } from "@/lib/api/types";
import {
  countActiveFilters,
  DEFAULT_FILTERS,
  DEFAULT_SUMMARY_LEVEL,
  toSearchParams,
  type SearchFilters,
  type SummaryLevel,
} from "@/lib/filters";
import { formatCount } from "@/lib/format";
import { validateQuery } from "@/lib/validation";

import { SearchHero } from "./SearchHero";

type SearchState =
  | { status: "idle" }
  | { status: "loading" }
  | { status: "success"; data: SearchResponse }
  | { status: "error"; message: string; hints: string[] };

/**
 * Owns the search: the typed query, the filters, the summary level and the
 * request lifecycle. Results always reflect `submittedQuery` + `filters`:
 * changing any filter after a search immediately re-runs it.
 */
export function ResearchSearch() {
  const [query, setQuery] = useState("");
  const [queryError, setQueryError] = useState<string | null>(null);
  const [submittedQuery, setSubmittedQuery] = useState<string | null>(null);
  const [filters, setFilters] = useState<SearchFilters>(DEFAULT_FILTERS);
  // Kept across searches; used for explanation depth once Gemini summaries exist.
  const [summaryLevel, setSummaryLevel] = useState<SummaryLevel>(DEFAULT_SUMMARY_LEVEL);
  const [state, setState] = useState<SearchState>({ status: "idle" });
  const [filtersOpen, setFiltersOpen] = useState(false);
  const controllerRef = useRef<AbortController | null>(null);

  async function runSearch(searchQuery: string, searchFilters: SearchFilters) {
    // A new search cancels any request still in flight.
    controllerRef.current?.abort();
    const controller = new AbortController();
    controllerRef.current = controller;

    setState({ status: "loading" });
    try {
      const data = await searchPapers(toSearchParams(searchQuery, searchFilters), controller.signal);
      if (!controller.signal.aborted) setState({ status: "success", data });
    } catch (error) {
      if (controller.signal.aborted) return;
      if (error instanceof ApiError) {
        setState({ status: "error", message: error.message, hints: error.hints });
      } else {
        setState({ status: "error", message: "Something went wrong while searching. Please try again.", hints: [] });
      }
    }
  }

  function handleSubmit() {
    const { query: cleaned, error } = validateQuery(query);
    setQueryError(error);
    if (error) return;
    setSubmittedQuery(cleaned);
    runSearch(cleaned, filters);
  }

  function updateFilters(patch: Partial<SearchFilters>) {
    const next = { ...filters, ...patch };
    // Undated papers only matter with a custom range; drop the flag with the range.
    if (!next.startDate && !next.endDate) next.includeUndated = false;
    setFilters(next);
    if (submittedQuery) runSearch(submittedQuery, next);
  }

  function clearFilters() {
    updateFilters(DEFAULT_FILTERS);
  }

  const hasSearched = submittedQuery !== null;
  const activeCount = countActiveFilters(filters);

  return (
    <div className="mx-auto w-full max-w-6xl px-4 sm:px-6">
      <SearchHero
        query={query}
        onQueryChange={(value) => {
          setQuery(value);
          if (queryError) setQueryError(null);
        }}
        onSubmit={handleSubmit}
        queryError={queryError}
        isLoading={state.status === "loading"}
        summaryLevel={summaryLevel}
        onSummaryLevelChange={setSummaryLevel}
        period={filters.period}
        onPeriodChange={(period) => updateFilters({ period })}
        compact={hasSearched}
      />

      <p className="sr-only" aria-live="polite">
        {statusAnnouncement(state)}
      </p>

      {hasSearched && (
        <div className="grid gap-6 pb-12 lg:grid-cols-[17rem_minmax(0,1fr)]">
          <aside aria-label="Search filters">
            <button
              type="button"
              onClick={() => setFiltersOpen((open) => !open)}
              aria-expanded={filtersOpen}
              aria-controls="filter-sidebar"
              className="mb-3 w-full rounded-lg border border-slate-300 bg-white px-4 py-2 text-sm font-semibold text-slate-800 lg:hidden dark:border-slate-700 dark:bg-slate-900 dark:text-slate-100"
            >
              {filtersOpen ? "Hide filters" : "Show filters"}
              {activeCount > 0 && ` (${activeCount})`}
            </button>
            <div id="filter-sidebar" className={`${filtersOpen ? "block" : "hidden"} lg:sticky lg:top-4 lg:block`}>
              <FilterSidebar filters={filters} onChange={updateFilters} onClearAll={clearFilters} />
            </div>
          </aside>

          <section
            aria-labelledby={state.status === "success" ? "results-heading" : undefined}
            aria-busy={state.status === "loading"}
            className="min-w-0 space-y-5"
          >
            <ActiveFilterChips filters={filters} onChange={updateFilters} onClearAll={clearFilters} />
            {state.status === "loading" && <LoadingResults />}
            {state.status === "error" && (
              <ErrorAlert
                message={state.message}
                hints={state.hints}
                onRetry={submittedQuery ? () => runSearch(submittedQuery, filters) : undefined}
              />
            )}
            {state.status === "success" && state.data.papers.length === 0 && (
              <EmptyState data={state.data} hasFilters={activeCount > 0} onClearFilters={clearFilters} />
            )}
            {state.status === "success" && state.data.papers.length > 0 && (
              <>
                <ResultsSummary data={state.data} />
                <PaperList papers={state.data.papers} />
              </>
            )}
          </section>
        </div>
      )}
    </div>
  );
}

function statusAnnouncement(state: SearchState): string {
  switch (state.status) {
    case "loading":
      return "Searching PubMed…";
    case "success":
      return state.data.papers.length === 0
        ? "No papers found."
        : `Showing ${formatCount(state.data.returned)} of ${formatCount(state.data.total_results)} PubMed matches.`;
    default:
      return ""; // errors are announced by the alert itself
  }
}
