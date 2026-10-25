"use client";

import { useId } from "react";

import { ErrorAlert } from "@/components/feedback/ErrorAlert";
import { formatInZone } from "@/lib/deliveries";
import { labelFor } from "@/lib/filters";
import { describeSchedule, READING_LEVEL_OPTIONS, type Subscription } from "@/lib/subscriptions";

import { BellGlyph } from "./SubscriptionDialog";
import { useSubscriptions } from "./SubscriptionsProvider";

/** Account-page list of the user's research subscriptions, loaded from the server. */
export function SubscriptionList() {
  const { subscriptions, status, loadError, reload, openSubscriptionDialog } = useSubscriptions();
  const headingId = useId();
  const anyActive = subscriptions.some((s) => s.deliveryActive);

  return (
    <section
      aria-labelledby={headingId}
      aria-busy={status === "loading"}
      className="rounded-2xl border border-slate-200 bg-white p-5 sm:p-6 dark:border-slate-800 dark:bg-slate-900"
    >
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 id={headingId} className="text-lg font-semibold text-slate-900 dark:text-slate-50">
            Research subscriptions
            {status === "ready" && (
              <span className="ml-2 text-sm font-normal text-slate-500 dark:text-slate-400">
                ({subscriptions.length})
              </span>
            )}
          </h2>
          <p className="mt-1 text-sm text-slate-600 dark:text-slate-400">
            Saved to your account.{" "}
            {anyActive ? (
              <span className="rounded-full bg-teal-100 px-2 py-0.5 text-xs font-medium text-teal-900 dark:bg-teal-950 dark:text-teal-200">
                Automatic emails on (test mode: approved addresses only)
              </span>
            ) : (
              <span className="rounded-full bg-amber-100 px-2 py-0.5 text-xs font-medium text-amber-900 dark:bg-amber-950 dark:text-amber-200">
                Automatic emails not active yet
              </span>
            )}
          </p>
        </div>
        <button
          type="button"
          onClick={() => openSubscriptionDialog({ topic: "" })}
          disabled={status === "loading"}
          className="inline-flex items-center gap-1.5 rounded-lg bg-teal-700 px-3 py-1.5 text-sm font-semibold text-white hover:bg-teal-800 focus-visible:ring-2 focus-visible:ring-teal-600 focus-visible:ring-offset-2 focus-visible:outline-none disabled:opacity-60"
        >
          <BellGlyph className="size-4" /> New subscription
        </button>
      </div>

      {status === "loading" && (
        <div className="mt-4 space-y-3" aria-hidden="true">
          {[0, 1].map((i) => (
            <div key={i} className="h-16 animate-pulse rounded-lg bg-slate-100 dark:bg-slate-800" />
          ))}
        </div>
      )}

      {status === "error" && (
        <div className="mt-4">
          <ErrorAlert
            title="Subscriptions could not be loaded"
            message={loadError ?? "Please try again."}
            onRetry={reload}
          />
        </div>
      )}

      {status === "ready" && subscriptions.length === 0 && (
        <p className="mt-4 rounded-lg border border-dashed border-slate-300 px-4 py-6 text-center text-sm text-slate-600 dark:border-slate-700 dark:text-slate-400">
          No subscriptions yet. Click the bell beside the search box, or <span className="font-medium">Follow topic</span>{" "}
          on a paper, to set one up.
        </p>
      )}

      {status === "ready" && subscriptions.length > 0 && (
        <ul className="mt-4 divide-y divide-slate-100 dark:divide-slate-800">
          {subscriptions.map((subscription) => (
            <li key={subscription.id} className="flex flex-col gap-3 py-4 sm:flex-row sm:items-start sm:justify-between">
              <div className="min-w-0">
                <h3 className="flex items-center gap-2 font-medium break-words text-slate-900 dark:text-slate-100">
                  <BellGlyph ringing className="size-4 shrink-0 text-teal-700 dark:text-teal-400" />
                  {subscription.topic}
                </h3>
                <p className="mt-1 text-sm text-slate-600 dark:text-slate-400">{describeSchedule(subscription)}</p>
                <DeliveryStatusLine subscription={subscription} />
                <ul className="mt-1.5 flex flex-wrap gap-1.5 text-xs">
                  {[
                    `${subscription.paperCount} papers`,
                    labelFor(READING_LEVEL_OPTIONS, subscription.readingLevel),
                    subscription.autoEmail
                      ? subscription.deliveryActive
                        ? "Email on"
                        : "Email on (not active yet)"
                      : "Email off",
                    ...(subscription.autoEmail && subscription.emailWhenNoNewPapers ? ["Email even if nothing new"] : []),
                  ].map((label) => (
                    <li key={label} className="rounded-full bg-slate-100 px-2 py-0.5 text-slate-700 dark:bg-slate-800 dark:text-slate-300">
                      {label}
                    </li>
                  ))}
                </ul>
              </div>
              <button
                type="button"
                onClick={() => openSubscriptionDialog({ topic: subscription.topic })}
                className="shrink-0 rounded-lg border border-slate-300 px-3 py-1.5 text-sm font-medium text-slate-800 hover:border-teal-600 focus-visible:ring-2 focus-visible:ring-teal-600 focus-visible:outline-none dark:border-slate-700 dark:text-slate-100"
              >
                Manage<span className="sr-only">: {subscription.topic}</span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

/** Status, next scheduled run and last successful delivery for one subscription. */
function DeliveryStatusLine({ subscription }: { subscription: Subscription }) {
  const { unsubscribedAt, autoEmail, nextRunAt, lastSentAt, timeZone, deliveryActive } = subscription;
  let status: string;
  if (unsubscribedAt) {
    status = `Unsubscribed from an email link on ${formatInZone(unsubscribedAt, timeZone)}. Turn email back on with Manage.`;
  } else if (!autoEmail) {
    status = "Email is off for this topic.";
  } else if (nextRunAt) {
    status = `${deliveryActive ? "Next digest" : "Next scheduled run (not emailed yet)"}: ${formatInZone(nextRunAt, timeZone)}`;
  } else {
    status = "Next run: scheduled when the digest scheduler next runs.";
  }
  return (
    <p className="mt-1 text-xs text-slate-500 dark:text-slate-400" data-testid="delivery-status">
      {status}
      {lastSentAt && <> · Last sent {formatInZone(lastSentAt, timeZone)}</>}
    </p>
  );
}
