"use client";

import { useEffect, useId, useRef, useState } from "react";

import { useAuth } from "@/components/auth/AuthProvider";
import { ErrorAlert } from "@/components/feedback/ErrorAlert";
import { analyzePaper, ApiError } from "@/lib/api/client";
import type { PaperAnalysis, SummaryLevel } from "@/lib/api/types";
import { labelFor, SUMMARY_LEVEL_OPTIONS } from "@/lib/filters";

import { useAiUsage } from "./AiUsageProvider";
import { AnalysisReport } from "./AnalysisReport";

type PanelState =
  | { status: "idle" }
  | { status: "loading"; level: SummaryLevel }
  | { status: "success"; analysis: PaperAnalysis }
  | { status: "error"; message: string; hints: string[] };

interface PaperAnalysisPanelProps {
  pmid: string;
  /** The summary level currently selected in the search header. */
  summaryLevel: SummaryLevel;
}

/**
 * On-demand AI analysis for one paper. Nothing is requested until the user clicks.
 * Requires login; each successful analysis uses one of the user's daily analyses.
 * The server enforces both rules; this component only explains them.
 */
export function PaperAnalysisPanel({ pmid, summaryLevel }: PaperAnalysisPanelProps) {
  const [state, setState] = useState<PanelState>({ status: "idle" });
  const [expanded, setExpanded] = useState(true);
  const controllerRef = useRef<AbortController | null>(null);
  const inFlightRef = useRef(false);
  const baseId = useId();
  const reportId = `${baseId}-report`;
  const levelLabel = labelFor(SUMMARY_LEVEL_OPTIONS, summaryLevel);
  const { status: authStatus, openAuthDialog } = useAuth();
  const { usage, refresh: refreshUsage } = useAiUsage();
  const signedIn = authStatus === "authenticated";
  const outOfAnalyses = signedIn && usage !== null && usage.remaining <= 0;

  // Cancel a running request if the card disappears (e.g. a new search).
  useEffect(() => () => controllerRef.current?.abort(), []);

  async function run() {
    if (!signedIn) {
      openAuthDialog("login", "Log in or create a free account to use AI paper analysis.");
      return;
    }
    if (inFlightRef.current) return; // ignore double clicks while a request is running
    inFlightRef.current = true;
    const controller = new AbortController();
    controllerRef.current = controller;
    const level = summaryLevel;

    setState({ status: "loading", level });
    try {
      const analysis = await analyzePaper(pmid, level, controller.signal);
      if (!controller.signal.aborted) {
        setState({ status: "success", analysis });
        setExpanded(true);
      }
    } catch (error) {
      if (controller.signal.aborted) return;
      setState(
        error instanceof ApiError
          ? { status: "error", message: error.message, hints: error.hints }
          : { status: "error", message: "The analysis could not be completed. Please try again.", hints: [] },
      );
    } finally {
      inFlightRef.current = false;
      refreshUsage(); // the server's count changed (or a failure was refunded)
    }
  }

  const isLoading = state.status === "loading";
  const levelChanged = state.status === "success" && state.analysis.summary_level !== summaryLevel;

  return (
    <div className="mt-4 border-t border-navy-100 pt-4 dark:border-navy-800">
      <div className="flex flex-wrap items-center gap-3">
        {/* The error alert below has its own retry button. */}
        {(state.status === "idle" || isLoading || levelChanged) && (
          <button
            type="button"
            onClick={run}
            disabled={isLoading || outOfAnalyses}
            aria-describedby={`${baseId}-hint`}
            className="inline-flex items-center gap-2 rounded-lg bg-brand-700 px-4 py-2 text-sm font-semibold text-white shadow-sm transition hover:bg-brand-800 focus-visible:ring-2 focus-visible:ring-brand-600 focus-visible:ring-offset-2 focus-visible:outline-none disabled:cursor-not-allowed disabled:opacity-70"
          >
            {isLoading ? (
              <span
                aria-hidden="true"
                className="size-4 animate-spin rounded-full border-2 border-white/40 border-t-white"
              />
            ) : (
              <span aria-hidden="true">✦</span>
            )}
            {isLoading
              ? "Analyzing…"
              : !signedIn
                ? "Log in to analyze"
                : levelChanged
                  ? `Re-analyze at ${levelLabel} level`
                  : "Analyze paper"}
          </button>
        )}
        {state.status === "success" && (
          <button
            type="button"
            onClick={() => setExpanded((value) => !value)}
            aria-expanded={expanded}
            aria-controls={reportId}
            className="rounded-lg border border-navy-300 px-4 py-2 text-sm font-medium text-navy-800 transition hover:border-brand-600 hover:text-brand-800 focus-visible:ring-2 focus-visible:ring-brand-600 focus-visible:outline-none dark:border-navy-700 dark:text-navy-200 dark:hover:text-brand-300"
          >
            {expanded ? "Hide AI analysis" : "Show AI analysis"}
          </button>
        )}
        <p id={`${baseId}-hint`} className="text-xs text-navy-500 dark:text-navy-400">
          {isLoading
            ? `Gemini is reading the abstract at ${labelFor(SUMMARY_LEVEL_OPTIONS, state.level)} level. This can take up to a minute.`
            : !signedIn
              ? "AI paper analysis is available to signed-in users."
              : outOfAnalyses
                ? `You've used all ${usage.limit} AI analyses for today. They reset at ${formatReset(usage.resets_at)}.`
                : `AI summary from the PubMed abstract · ${levelLabel} level${
                    usage ? ` · ${usage.remaining} of ${usage.limit} left today` : ""
                  }`}
        </p>
      </div>

      <p className="sr-only" aria-live="polite">
        {isLoading ? "Analyzing paper…" : state.status === "success" ? "AI analysis ready." : ""}
      </p>

      {state.status === "error" && (
        <div className="mt-3">
          <ErrorAlert
            title="The AI analysis could not be completed"
            message={state.message}
            hints={state.hints}
            onRetry={run}
          />
        </div>
      )}

      {state.status === "success" && (
        <div
          id={reportId}
          hidden={!expanded}
          className="mt-4 rounded-xl border border-brand-100 bg-brand-50/40 p-4 sm:p-5 dark:border-brand-950 dark:bg-brand-950/20"
        >
          <AnalysisReport analysis={state.analysis} headingId={`${baseId}-heading`} />
        </div>
      )}
    </div>
  );
}

/** "2026-10-25T00:00:00Z" -> local time, e.g. "8:00 PM" (with the date if it isn't today). */
function formatReset(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "midnight UTC";
  const sameDay = date.toDateString() === new Date().toDateString();
  return date.toLocaleString(undefined, sameDay ? { hour: "numeric", minute: "2-digit" } : {
    weekday: "short",
    hour: "numeric",
    minute: "2-digit",
  });
}
