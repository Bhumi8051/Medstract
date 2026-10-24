"use client";

import { useId, useState, type FormEvent, type KeyboardEvent } from "react";

import { useAuth } from "@/components/auth/AuthProvider";
import { SegmentedControl } from "@/components/ui/SegmentedControl";
import { ApiError } from "@/lib/api/client";
import { SUMMARY_LEVEL_OPTIONS, type SummaryLevel } from "@/lib/filters";

// Match the backend limits (backend/app/models.py).
const MAX_INTERESTS = 20;
const INTEREST_MIN = 2;
const INTEREST_MAX = 100;

type SaveStatus = { kind: "idle" | "saving" | "saved" } | { kind: "error"; message: string };

export function PreferencesForm() {
  const { account, savePreferences } = useAuth();
  const [level, setLevel] = useState<SummaryLevel>(account?.preferences.summary_level ?? "college");
  const [interests, setInterests] = useState<string[]>(account?.preferences.research_interests ?? []);
  const [draft, setDraft] = useState("");
  const [draftError, setDraftError] = useState<string | null>(null);
  const [status, setStatus] = useState<SaveStatus>({ kind: "idle" });
  const baseId = useId();

  function addInterest() {
    const value = draft.split(/\s+/).filter(Boolean).join(" ");
    if (value.length < INTEREST_MIN || value.length > INTEREST_MAX) {
      setDraftError(`Use ${INTEREST_MIN} to ${INTEREST_MAX} characters.`);
      return;
    }
    if (interests.some((i) => i.toLowerCase() === value.toLowerCase())) {
      setDraftError("Already in your list.");
      return;
    }
    if (interests.length >= MAX_INTERESTS) {
      setDraftError(`You can keep up to ${MAX_INTERESTS} interests.`);
      return;
    }
    setInterests([...interests, value]);
    setDraft("");
    setDraftError(null);
    setStatus({ kind: "idle" });
  }

  function handleDraftKey(event: KeyboardEvent<HTMLInputElement>) {
    if (event.key === "Enter") {
      event.preventDefault(); // add the interest instead of submitting the whole form
      addInterest();
    }
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setStatus({ kind: "saving" });
    try {
      await savePreferences({ summary_level: level, research_interests: interests });
      setStatus({ kind: "saved" });
    } catch (error) {
      setStatus({
        kind: "error",
        message: error instanceof ApiError ? error.message : "Preferences could not be saved. Please try again.",
      });
    }
  }

  return (
    <section
      aria-labelledby={`${baseId}-title`}
      className="rounded-2xl border border-slate-200 bg-white p-5 sm:p-6 dark:border-slate-800 dark:bg-slate-900"
    >
      <h2 id={`${baseId}-title`} className="text-lg font-semibold text-slate-900 dark:text-slate-50">
        Research preferences
      </h2>
      <form onSubmit={handleSubmit} className="mt-4 space-y-6">
        <SegmentedControl
          legend="Default summary level"
          options={SUMMARY_LEVEL_OPTIONS}
          value={level}
          onChange={(value) => {
            setLevel(value);
            setStatus({ kind: "idle" });
          }}
          hint="Applied when you log in; you can still change it for each search."
        />

        <div>
          <label htmlFor={`${baseId}-interest`} className="text-xs font-semibold tracking-wide text-slate-500 uppercase dark:text-slate-400">
            Research interests
          </label>
          <p className="mt-0.5 text-xs text-slate-500 dark:text-slate-400">
            Shown as one-click searches on the home page ({interests.length}/{MAX_INTERESTS}).
          </p>
          <div className="mt-2 flex gap-2">
            <input
              id={`${baseId}-interest`}
              value={draft}
              maxLength={INTEREST_MAX}
              placeholder="e.g. acute myeloid leukemia"
              onChange={(e) => {
                setDraft(e.target.value);
                setDraftError(null);
              }}
              onKeyDown={handleDraftKey}
              aria-invalid={Boolean(draftError)}
              aria-describedby={draftError ? `${baseId}-interest-error` : undefined}
              className="min-w-0 flex-1 rounded-md border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900 focus:border-teal-600 focus:ring-2 focus:ring-teal-600/30 focus:outline-none aria-invalid:border-red-500 dark:border-slate-700 dark:bg-slate-950 dark:text-slate-100"
            />
            <button
              type="button"
              onClick={addInterest}
              className="rounded-md border border-slate-300 px-3 py-2 text-sm font-medium text-slate-800 hover:border-teal-600 focus-visible:ring-2 focus-visible:ring-teal-600 focus-visible:outline-none dark:border-slate-700 dark:text-slate-100"
            >
              Add
            </button>
          </div>
          {draftError && (
            <p id={`${baseId}-interest-error`} className="mt-1 text-sm text-red-700 dark:text-red-400">
              {draftError}
            </p>
          )}
          {interests.length > 0 ? (
            <ul className="mt-3 flex flex-wrap gap-2">
              {interests.map((interest) => (
                <li key={interest}>
                  <button
                    type="button"
                    onClick={() => {
                      setInterests(interests.filter((i) => i !== interest));
                      setStatus({ kind: "idle" });
                    }}
                    className="inline-flex items-center gap-1.5 rounded-full border border-teal-200 bg-teal-50 py-1 pr-2 pl-3 text-sm text-teal-900 hover:border-teal-400 focus-visible:ring-2 focus-visible:ring-teal-600 focus-visible:outline-none dark:border-teal-900 dark:bg-teal-950 dark:text-teal-200"
                  >
                    {interest}
                    <span aria-hidden="true">×</span>
                    <span className="sr-only">(remove)</span>
                  </button>
                </li>
              ))}
            </ul>
          ) : (
            <p className="mt-3 text-sm text-slate-500 italic dark:text-slate-400">No interests yet.</p>
          )}
        </div>

        <div className="flex flex-wrap items-center gap-3">
          <button
            type="submit"
            disabled={status.kind === "saving"}
            className="rounded-lg bg-teal-700 px-5 py-2 font-semibold text-white hover:bg-teal-800 focus-visible:ring-2 focus-visible:ring-teal-600 focus-visible:ring-offset-2 focus-visible:outline-none disabled:opacity-70"
          >
            {status.kind === "saving" ? "Saving…" : "Save preferences"}
          </button>
          <p role="status" className="text-sm">
            {status.kind === "saved" && <span className="text-teal-800 dark:text-teal-300">Preferences saved.</span>}
            {status.kind === "error" && <span className="text-red-700 dark:text-red-400">{status.message}</span>}
          </p>
        </div>
      </form>
    </section>
  );
}
