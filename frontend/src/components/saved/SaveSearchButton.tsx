"use client";

import Link from "next/link";
import { useId, useState, type FormEvent } from "react";

import { useAuth } from "@/components/auth/AuthProvider";
import { ApiError, createSavedSearch } from "@/lib/api/client";
import { toSavedFilters, type SearchFilters } from "@/lib/filters";

interface SaveSearchButtonProps {
  query: string;
  filters: SearchFilters;
}

type SaveState = { status: "idle" | "editing" | "saving" | "saved" } | { status: "error"; message: string };

/**
 * Saves the search that produced the current results (query + filters).
 * The parent remounts it (via `key`) whenever the query or filters change.
 */
export function SaveSearchButton({ query, filters }: SaveSearchButtonProps) {
  const { status: authStatus, openAuthDialog } = useAuth();
  const [state, setState] = useState<SaveState>({ status: "idle" });
  const [name, setName] = useState(query.slice(0, 120));
  const inputId = useId();

  const linkClass =
    "font-medium text-teal-800 underline-offset-4 hover:underline focus-visible:ring-2 focus-visible:ring-teal-600 focus-visible:outline-none dark:text-teal-300";
  const buttonClass =
    "inline-flex items-center gap-1.5 rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-sm font-medium text-slate-800 transition hover:border-teal-600 hover:text-teal-800 focus-visible:ring-2 focus-visible:ring-teal-600 focus-visible:outline-none disabled:opacity-60 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-100 dark:hover:text-teal-300";

  if (authStatus === "unavailable") return null;
  if (authStatus !== "authenticated") {
    return (
      <button
        type="button"
        disabled={authStatus === "loading"}
        onClick={() => openAuthDialog("login", "Log in or create a free account to save searches.")}
        className={buttonClass}
      >
        <span aria-hidden="true">☆</span> Log in to save this search
      </button>
    );
  }

  if (state.status === "saved") {
    return (
      <p role="status" className="text-sm text-teal-900 dark:text-teal-200">
        <span aria-hidden="true">★</span> Saved.{" "}
        <Link href="/account" className={linkClass}>
          View saved searches
        </Link>
      </p>
    );
  }

  if (state.status === "idle") {
    return (
      <button type="button" onClick={() => setState({ status: "editing" })} className={buttonClass}>
        <span aria-hidden="true">☆</span> Save search
      </button>
    );
  }

  async function handleSave(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (state.status === "saving") return;
    setState({ status: "saving" });
    try {
      await createSavedSearch({ name: name.trim(), query, filters: toSavedFilters(filters) });
      setState({ status: "saved" });
    } catch (error) {
      setState({
        status: "error",
        message: error instanceof ApiError ? error.message : "The search could not be saved. Please try again.",
      });
    }
  }

  return (
    <form onSubmit={handleSave} className="flex flex-wrap items-end gap-2">
      <div>
        <label htmlFor={inputId} className="block text-xs font-medium text-slate-600 dark:text-slate-400">
          Name this search
        </label>
        <input
          id={inputId}
          value={name}
          maxLength={120}
          autoFocus
          onChange={(e) => setName(e.target.value)}
          className="mt-1 w-64 max-w-full rounded-md border border-slate-300 bg-white px-2 py-1.5 text-sm text-slate-900 focus:border-teal-600 focus:ring-2 focus:ring-teal-600/30 focus:outline-none dark:border-slate-700 dark:bg-slate-950 dark:text-slate-100"
        />
      </div>
      <button type="submit" disabled={state.status === "saving"} className={buttonClass}>
        {state.status === "saving" ? "Saving…" : "Save"}
      </button>
      <button type="button" onClick={() => setState({ status: "idle" })} className={`${linkClass} px-1 py-1.5 text-sm`}>
        Cancel
      </button>
      {state.status === "error" && (
        <p role="alert" className="w-full text-sm text-red-700 dark:text-red-400">
          {state.message}
        </p>
      )}
    </form>
  );
}
