"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { useEffect, useRef, useState, useSyncExternalStore } from "react";

import { useAuth } from "@/components/auth/AuthProvider";
import { EmptyState } from "@/components/feedback/EmptyState";
import { ErrorAlert } from "@/components/feedback/ErrorAlert";
import { LoadingResults } from "@/components/feedback/LoadingResults";
import { FilterSidebar } from "@/components/filters/FilterSidebar";
import { ActiveFilterChips } from "@/components/results/ActiveFilterChips";
import { PaperList } from "@/components/results/PaperList";
import { ResultsSummary } from "@/components/results/ResultsSummary";
import { SaveSearchButton } from "@/components/saved/SaveSearchButton";
import { ApiError, getSavedSearch, searchPapers } from "@/lib/api/client";
import type { SearchResponse } from "@/lib/api/types";
import {
  countActiveFilters,
  DEFAULT_FILTERS,
  DEFAULT_SUMMARY_LEVEL,
  fromSavedFilters,
  toSearchParams,
  type SearchFilters,
  type SummaryLevel,
} from "@/lib/filters";
import { formatCount } from "@/lib/format";
import { getHomeRequests, subscribeHomeRequests } from "@/lib/homeNavigation";
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
 *
 * Signed-in extras: the preferred summary level is applied on login, saved
 * searches open via `/?saved=<id>`, and research interests become quick searches.
 *
 * Clicking the logo (HomeLink) returns this page to its initial home screen.
 */
export function ResearchSearch() {
  const [query, setQuery] = useState("");
  const [queryError, setQueryError] = useState<string | null>(null);
  const [submittedQuery, setSubmittedQuery] = useState<string | null>(null);
  const [filters, setFilters] = useState<SearchFilters>(DEFAULT_FILTERS);
  // Kept across searches; sent with each "Analyze paper" request.
  const [summaryLevel, setSummaryLevel] = useState<SummaryLevel>(DEFAULT_SUMMARY_LEVEL);
  const [state, setState] = useState<SearchState>({ status: "idle" });
  const [filtersOpen, setFiltersOpen] = useState(false);
  const controllerRef = useRef<AbortController | null>(null);
  const { status: authStatus, account, openAuthDialog } = useAuth();
  const searchParams = useSearchParams();
  const router = useRouter();
  const savedId = searchParams.get("saved");
  const handledSavedIdRef = useRef<string | null>(null);

  // Apply the account's preferred summary level on login and whenever the saved
  // preference changes. (Next.js keeps this page's state while you visit /account,
  // so keying on the user alone would keep a stale level.) Adjusting state during
  // render is React's recommended way to respond to a changed context value.
  const preferredLevelKey = account ? `${account.user.id}:${account.preferences.summary_level}` : null;
  const [levelAppliedFor, setLevelAppliedFor] = useState<string | null>(null);
  if (account && preferredLevelKey !== levelAppliedFor) {
    setLevelAppliedFor(preferredLevelKey);
    setSummaryLevel(account.preferences.summary_level);
  }

  // Logo clicked: back to the initial home screen (same pattern as above, so it also
  // applies while Next.js keeps this page hidden during a visit to another page).
  // The summary level is kept: it's a preference, not part of a search.
  const homeRequests = useSyncExternalStore(subscribeHomeRequests, getHomeRequests, () => 0);
  const [homeRequestsSeen, setHomeRequestsSeen] = useState(homeRequests);
  if (homeRequests !== homeRequestsSeen) {
    setHomeRequestsSeen(homeRequests);
    setQuery("");
    setQueryError(null);
    setSubmittedQuery(null);
    setFilters(DEFAULT_FILTERS);
    setState({ status: "idle" });
    setFiltersOpen(false);
  }
  // ...and cancel a search that was still running.
  useEffect(() => {
    controllerRef.current?.abort();
  }, [homeRequests]);

  async function runSearch(searchQuery: string, searchFilters: SearchFilters) {
    // A new search cancels any request still in flight.
    controllerRef.current?.abort();
    const controller = new AbortController();
    controllerRef.current = controller;
    // A logo click while this runs means "go home": drop the result even if it
    // arrives before the request is cancelled.
    const homeRequestsAtStart = getHomeRequests();
    const stale = () => controller.signal.aborted || getHomeRequests() !== homeRequestsAtStart;

    setState({ status: "loading" });
    try {
      const data = await searchPapers(toSearchParams(searchQuery, searchFilters), controller.signal);
      if (!stale()) setState({ status: "success", data });
    } catch (error) {
      if (stale()) return;
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

  function searchFor(text: string) {
    setQuery(text);
    setQueryError(null);
    setSubmittedQuery(text);
    runSearch(text, filters);
  }

  // Open a saved search from /?saved=<id> (linked from the account page).
  useEffect(() => {
    if (!savedId) {
      // URL is back to "/": allow the same saved search to be opened again later.
      handledSavedIdRef.current = null;
      return;
    }
    if (handledSavedIdRef.current === savedId || authStatus === "loading") return;
    handledSavedIdRef.current = savedId;
    if (authStatus !== "authenticated") {
      openAuthDialog("login", "Log in to open your saved search.");
      handledSavedIdRef.current = null; // try again after logging in
      return;
    }
    const controller = new AbortController();
    getSavedSearch(savedId, controller.signal)
      .then((saved) => {
        const savedFilters = fromSavedFilters(saved.filters);
        setQuery(saved.query);
        setFilters(savedFilters);
        setSubmittedQuery(saved.query);
        runSearch(saved.query, savedFilters);
      })
      .catch((error) => {
        if (controller.signal.aborted) return;
        setSubmittedQuery("");
        setState({
          status: "error",
          message: error instanceof ApiError ? error.message : "The saved search could not be opened.",
          hints: [],
        });
      })
      .finally(() => {
        // Drop ?saved= from the address bar: from here on the page shows live, editable state.
        // Skipped if this load was cancelled (another run of this effect takes over).
        if (!controller.signal.aborted) router.replace("/", { scroll: false });
      });
    return () => {
      // Cancelled before it finished (e.g. React's development double-run): let the next run load it.
      controller.abort();
      if (handledSavedIdRef.current === savedId) handledSavedIdRef.current = null;
    };
    // runSearch is recreated each render; we only want to react to the URL and login state.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [savedId, authStatus]);

  const hasSearched = submittedQuery !== null;
  const activeCount = countActiveFilters(filters);

  return (
    <div>
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
        interests={account?.preferences.research_interests ?? []}
        onInterestSelect={searchFor}
      />

      <p className="sr-only" aria-live="polite">
        {statusAnnouncement(state)}
      </p>

      {hasSearched && (
        <div className="page-container grid gap-8 pt-8 pb-16 lg:grid-cols-[17rem_minmax(0,1fr)]">
          <aside aria-label="Search filters">
            <button
              type="button"
              onClick={() => setFiltersOpen((open) => !open)}
              aria-expanded={filtersOpen}
              aria-controls="filter-sidebar"
              className="mb-3 w-full rounded-lg border border-navy-300 bg-white px-4 py-2 text-sm font-semibold text-navy-800 lg:hidden dark:border-navy-700 dark:bg-navy-900 dark:text-navy-100"
            >
              {filtersOpen ? "Hide filters" : "Show filters"}
              {activeCount > 0 && ` (${activeCount})`}
            </button>
            <div id="filter-sidebar" className={`${filtersOpen ? "block" : "hidden"} lg:sticky lg:top-6 lg:block`}>
              <FilterSidebar filters={filters} onChange={updateFilters} onClearAll={clearFilters} />
            </div>
          </aside>

          <section
            aria-labelledby={state.status === "success" ? "results-heading" : undefined}
            aria-busy={state.status === "loading"}
            className="min-w-0 space-y-6"
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
            {state.status === "success" && submittedQuery && (
              <SaveSearchButton
                // New results -> fresh button (so "Saved" never refers to an older search).
                key={`${submittedQuery}|${JSON.stringify(filters)}`}
                query={submittedQuery}
                filters={filters}
              />
            )}
            {state.status === "success" && state.data.papers.length > 0 && (
              <>
                <ResultsSummary data={state.data} />
                <PaperList papers={state.data.papers} summaryLevel={summaryLevel} />
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
