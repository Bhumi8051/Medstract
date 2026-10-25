"use client";

import { useEffect, useId, useState } from "react";

import { ErrorAlert } from "@/components/feedback/ErrorAlert";
import { useSubscriptions } from "@/components/subscriptions/SubscriptionsProvider";
import { ApiError, listDeliveries } from "@/lib/api/client";
import type { DigestDelivery } from "@/lib/api/types";
import { DELIVERY_STATUS, describeReason, formatInZone, TONE_CLASSES } from "@/lib/deliveries";

type State =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ready"; deliveries: DigestDelivery[] };

/** The signed-in user's scheduled digest runs (newest first), loaded from the server. */
export function DeliveryHistory() {
  const { subscriptions } = useSubscriptions();
  const headingId = useId();
  const [state, setState] = useState<State>({ status: "loading" });
  const [reloadToken, setReloadToken] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    listDeliveries(controller.signal)
      .then((deliveries) => setState({ status: "ready", deliveries }))
      .catch((err: unknown) => {
        if (controller.signal.aborted) return;
        setState({ status: "error", message: err instanceof ApiError ? err.message : "History could not be loaded." });
      });
    return () => controller.abort();
  }, [reloadToken]);

  // Show times in each subscription's own time zone (falls back to the browser's).
  const zoneOf = new Map(subscriptions.map((s) => [s.id, s.timeZone]));

  return (
    <section
      aria-labelledby={headingId}
      aria-busy={state.status === "loading"}
      id="digest-history"
      className="scroll-mt-6 rounded-2xl border border-navy-200 bg-white p-6 shadow-sm sm:p-8 dark:border-navy-800 dark:bg-navy-900"
    >
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 id={headingId} className="text-lg font-semibold text-navy-900 dark:text-navy-50">
            Scheduled digest history
          </h2>
          <p className="mt-1 text-sm text-navy-600 dark:text-navy-400">
            Every scheduled run of your subscriptions, including dry runs and skipped ones. Manual test emails aren&rsquo;t
            listed here.
          </p>
        </div>
        <button
          type="button"
          onClick={() => {
            setState({ status: "loading" });
            setReloadToken((n) => n + 1);
          }}
          disabled={state.status === "loading"}
          className="inline-flex h-9 items-center rounded-lg border border-navy-300 px-3 text-sm font-medium text-navy-800 hover:border-brand-600 focus-visible:ring-2 focus-visible:ring-brand-600 focus-visible:outline-none disabled:opacity-60 dark:border-navy-700 dark:text-navy-100"
        >
          Refresh
        </button>
      </div>

      {state.status === "loading" && (
        <div className="mt-4 space-y-2" aria-hidden="true">
          {[0, 1].map((i) => (
            <div key={i} className="h-12 animate-pulse rounded-lg bg-navy-100 dark:bg-navy-800" />
          ))}
        </div>
      )}

      {state.status === "error" && (
        <div className="mt-4">
          <ErrorAlert
            title="History could not be loaded"
            message={state.message}
            onRetry={() => {
              setState({ status: "loading" });
              setReloadToken((n) => n + 1);
            }}
          />
        </div>
      )}

      {state.status === "ready" && state.deliveries.length === 0 && (
        <p className="mt-4 rounded-lg border border-dashed border-navy-300 px-4 py-6 text-center text-sm text-navy-600 dark:border-navy-700 dark:text-navy-400">
          No scheduled digests yet.
        </p>
      )}

      {state.status === "ready" && state.deliveries.length > 0 && (
        <ul className="mt-4 divide-y divide-navy-100 dark:divide-navy-800">
          {state.deliveries.map((d) => {
            const meta = DELIVERY_STATUS[d.status];
            const zone = zoneOf.get(d.subscription_id) ?? Intl.DateTimeFormat().resolvedOptions().timeZone;
            const reason = describeReason(d.reason);
            return (
              <li key={d.id} className="flex flex-col gap-1 py-3 sm:flex-row sm:items-start sm:justify-between" data-status={d.status}>
                <div className="min-w-0">
                  <p className="font-medium break-words text-navy-900 dark:text-navy-100">{d.topic}</p>
                  <p className="text-xs text-navy-500 dark:text-navy-400">
                    Scheduled {formatInZone(d.scheduled_for, zone)}
                    {d.papers_count !== null && ` · ${d.papers_count} ${d.papers_count === 1 ? "paper" : "papers"}`}
                    {d.attempts > 1 && ` · ${d.attempts} attempts`}
                  </p>
                  <p className="text-xs text-navy-600 dark:text-navy-400">
                    {meta.hint}
                    {reason && ` Reason: ${reason}.`}
                  </p>
                </div>
                <span
                  className={`shrink-0 self-start rounded-full px-2.5 py-0.5 text-xs font-semibold ${TONE_CLASSES[meta.tone]}`}
                  title={meta.hint}
                >
                  {meta.label}
                </span>
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}
