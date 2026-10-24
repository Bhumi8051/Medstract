"use client";

import Link from "next/link";
import { useEffect, useId, useState } from "react";

import { ErrorAlert } from "@/components/feedback/ErrorAlert";
import { ApiError, deleteSavedSearch, listSavedSearches } from "@/lib/api/client";
import type { SavedSearch } from "@/lib/api/types";
import { describeFilters, fromSavedFilters } from "@/lib/filters";

type ListState =
  | { status: "loading" }
  | { status: "ready"; searches: SavedSearch[] }
  | { status: "error"; message: string };

export function SavedSearchList() {
  const [state, setState] = useState<ListState>({ status: "loading" });
  const [reloadKey, setReloadKey] = useState(0);
  const [confirmingId, setConfirmingId] = useState<string | null>(null);
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const headingId = useId();

  useEffect(() => {
    const controller = new AbortController();
    listSavedSearches(controller.signal)
      .then((searches) => setState({ status: "ready", searches }))
      .catch((error) => {
        if (controller.signal.aborted) return;
        setState({
          status: "error",
          message: error instanceof ApiError ? error.message : "Saved searches could not be loaded.",
        });
      });
    return () => controller.abort();
  }, [reloadKey]);

  async function remove(id: string) {
    setDeletingId(id);
    setDeleteError(null);
    try {
      await deleteSavedSearch(id);
      setState((current) =>
        current.status === "ready" ? { status: "ready", searches: current.searches.filter((s) => s.id !== id) } : current,
      );
    } catch (error) {
      setDeleteError(error instanceof ApiError ? error.message : "The search could not be deleted.");
    } finally {
      setDeletingId(null);
      setConfirmingId(null);
    }
  }

  return (
    <section
      aria-labelledby={headingId}
      aria-busy={state.status === "loading"}
      className="rounded-2xl border border-slate-200 bg-white p-5 sm:p-6 dark:border-slate-800 dark:bg-slate-900"
    >
      <h2 id={headingId} className="text-lg font-semibold text-slate-900 dark:text-slate-50">
        Saved searches
        {state.status === "ready" && (
          <span className="ml-2 text-sm font-normal text-slate-500 dark:text-slate-400">({state.searches.length})</span>
        )}
      </h2>

      {state.status === "loading" && (
        <div className="mt-4 space-y-3" aria-hidden="true">
          {[0, 1].map((i) => (
            <div key={i} className="h-16 animate-pulse rounded-lg bg-slate-100 dark:bg-slate-800" />
          ))}
        </div>
      )}

      {state.status === "error" && (
        <div className="mt-4">
          <ErrorAlert
            title="Saved searches could not be loaded"
            message={state.message}
            onRetry={() => {
              setState({ status: "loading" });
              setReloadKey((k) => k + 1);
            }}
          />
        </div>
      )}

      {deleteError && (
        <p role="alert" className="mt-3 text-sm text-red-700 dark:text-red-400">
          {deleteError}
        </p>
      )}

      {state.status === "ready" && state.searches.length === 0 && (
        <p className="mt-4 text-sm text-slate-600 dark:text-slate-400">
          No saved searches yet. Run a search, then click <span className="font-medium">Save search</span> above the
          results.{" "}
          <Link href="/" className="font-medium text-teal-800 underline-offset-4 hover:underline dark:text-teal-300">
            Start searching
          </Link>
        </p>
      )}

      {state.status === "ready" && state.searches.length > 0 && (
        <ul className="mt-4 divide-y divide-slate-100 dark:divide-slate-800">
          {state.searches.map((search) => {
            const labels = describeFilters(fromSavedFilters(search.filters));
            const confirming = confirmingId === search.id;
            return (
              <li key={search.id} className="flex flex-col gap-3 py-4 sm:flex-row sm:items-start sm:justify-between">
                <div className="min-w-0">
                  <h3 className="font-medium break-words text-slate-900 dark:text-slate-100">{search.name}</h3>
                  {search.name !== search.query && (
                    <p className="text-sm break-words text-slate-600 dark:text-slate-400">“{search.query}”</p>
                  )}
                  <ul className="mt-1.5 flex flex-wrap gap-1.5 text-xs">
                    {labels.length === 0 ? (
                      <li className="text-slate-500 dark:text-slate-400">No filters</li>
                    ) : (
                      labels.map((label) => (
                        <li key={label} className="rounded-full bg-slate-100 px-2 py-0.5 text-slate-700 dark:bg-slate-800 dark:text-slate-300">
                          {label}
                        </li>
                      ))
                    )}
                  </ul>
                  <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">
                    Saved {new Date(search.created_at).toLocaleDateString()}
                  </p>
                </div>
                <div className="flex shrink-0 items-center gap-2">
                  {confirming ? (
                    <>
                      <span className="text-sm text-slate-700 dark:text-slate-300">Delete?</span>
                      <button
                        type="button"
                        onClick={() => remove(search.id)}
                        disabled={deletingId === search.id}
                        className="rounded-lg bg-red-700 px-3 py-1.5 text-sm font-medium text-white hover:bg-red-800 focus-visible:ring-2 focus-visible:ring-red-600 focus-visible:outline-none disabled:opacity-70"
                      >
                        {deletingId === search.id ? "Deleting…" : "Yes, delete"}
                      </button>
                      <button
                        type="button"
                        onClick={() => setConfirmingId(null)}
                        className="rounded-lg px-3 py-1.5 text-sm font-medium text-slate-700 hover:bg-slate-100 focus-visible:ring-2 focus-visible:ring-teal-600 focus-visible:outline-none dark:text-slate-300 dark:hover:bg-slate-800"
                      >
                        Cancel
                      </button>
                    </>
                  ) : (
                    <>
                      <Link
                        href={`/?saved=${encodeURIComponent(search.id)}`}
                        className="rounded-lg bg-teal-700 px-3 py-1.5 text-sm font-semibold text-white hover:bg-teal-800 focus-visible:ring-2 focus-visible:ring-teal-600 focus-visible:ring-offset-2 focus-visible:outline-none"
                      >
                        Run search
                        <span className="sr-only">: {search.name}</span>
                      </Link>
                      <button
                        type="button"
                        onClick={() => setConfirmingId(search.id)}
                        className="rounded-lg border border-slate-300 px-3 py-1.5 text-sm font-medium text-slate-700 hover:border-red-500 hover:text-red-700 focus-visible:ring-2 focus-visible:ring-red-600 focus-visible:outline-none dark:border-slate-700 dark:text-slate-300"
                      >
                        Delete<span className="sr-only">: {search.name}</span>
                      </button>
                    </>
                  )}
                </div>
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}
