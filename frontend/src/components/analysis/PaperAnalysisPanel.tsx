"use client";

import { useEffect, useId, useRef, useState } from "react";

import { ErrorAlert } from "@/components/feedback/ErrorAlert";
import { analyzePaper, ApiError } from "@/lib/api/client";
import type { PaperAnalysis, SummaryLevel } from "@/lib/api/types";
import { labelFor, SUMMARY_LEVEL_OPTIONS } from "@/lib/filters";

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

/** On-demand AI analysis for one paper. Nothing is requested until the user clicks. */
export function PaperAnalysisPanel({ pmid, summaryLevel }: PaperAnalysisPanelProps) {
  const [state, setState] = useState<PanelState>({ status: "idle" });
  const [expanded, setExpanded] = useState(true);
  const controllerRef = useRef<AbortController | null>(null);
  const inFlightRef = useRef(false);
  const baseId = useId();
  const reportId = `${baseId}-report`;
  const levelLabel = labelFor(SUMMARY_LEVEL_OPTIONS, summaryLevel);

  // Cancel a running request if the card disappears (e.g. a new search).
  useEffect(() => () => controllerRef.current?.abort(), []);

  async function run() {
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
    }
  }

  const isLoading = state.status === "loading";
  const levelChanged = state.status === "success" && state.analysis.summary_level !== summaryLevel;

  return (
    <div className="mt-4 border-t border-slate-100 pt-4 dark:border-slate-800">
      <div className="flex flex-wrap items-center gap-3">
        {/* The error alert below has its own retry button. */}
        {(state.status === "idle" || isLoading || levelChanged) && (
          <button
            type="button"
            onClick={run}
            disabled={isLoading}
            aria-describedby={`${baseId}-hint`}
            className="inline-flex items-center gap-2 rounded-lg bg-violet-700 px-4 py-2 text-sm font-semibold text-white shadow-sm transition hover:bg-violet-800 focus-visible:ring-2 focus-visible:ring-violet-600 focus-visible:ring-offset-2 focus-visible:outline-none disabled:cursor-not-allowed disabled:opacity-70"
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
            className="rounded-lg border border-slate-300 px-4 py-2 text-sm font-medium text-slate-800 transition hover:border-violet-600 hover:text-violet-800 focus-visible:ring-2 focus-visible:ring-violet-600 focus-visible:outline-none dark:border-slate-700 dark:text-slate-200 dark:hover:text-violet-300"
          >
            {expanded ? "Hide AI analysis" : "Show AI analysis"}
          </button>
        )}
        <p id={`${baseId}-hint`} className="text-xs text-slate-500 dark:text-slate-400">
          {isLoading
            ? `Gemini is reading the abstract at ${labelFor(SUMMARY_LEVEL_OPTIONS, state.level)} level. This can take up to a minute.`
            : `AI summary from the PubMed abstract · ${levelLabel} level`}
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
          className="mt-4 rounded-xl border border-violet-100 bg-violet-50/40 p-4 sm:p-5 dark:border-violet-950 dark:bg-violet-950/20"
        >
          <AnalysisReport analysis={state.analysis} headingId={`${baseId}-heading`} />
        </div>
      )}
    </div>
  );
}
