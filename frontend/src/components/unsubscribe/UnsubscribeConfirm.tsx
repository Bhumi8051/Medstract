"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useEffect, useState } from "react";

import { ApiError, confirmUnsubscribe, getUnsubscribeInfo } from "@/lib/api/client";

type State =
  | { status: "checking" }
  | { status: "invalid"; message: string }
  | { status: "ready"; topic: string }
  | { status: "working"; topic: string }
  | { status: "done"; topic: string; already: boolean }
  | { status: "error"; topic: string; message: string };

const INVALID = "This unsubscribe link is invalid or no longer exists.";

/**
 * Confirmation step for an email unsubscribe link. Opening the page changes
 * nothing (link scanners and previews open links); only the button unsubscribes.
 * No login needed: the token in the link is the credential.
 */
export function UnsubscribeConfirm() {
  const token = useSearchParams().get("token") ?? "";
  const [state, setState] = useState<State>(token ? { status: "checking" } : { status: "invalid", message: INVALID });

  useEffect(() => {
    if (!token) return;
    const controller = new AbortController();
    getUnsubscribeInfo(token, controller.signal)
      .then((info) =>
        setState(
          info.status === "subscribed"
            ? { status: "ready", topic: info.topic }
            : { status: "done", topic: info.topic, already: true },
        ),
      )
      .catch((err: unknown) => {
        if (controller.signal.aborted) return;
        setState({ status: "invalid", message: err instanceof ApiError ? err.message : INVALID });
      });
    return () => controller.abort();
  }, [token]);

  async function unsubscribe(topic: string) {
    setState({ status: "working", topic });
    try {
      const result = await confirmUnsubscribe(token);
      setState({ status: "done", topic: result.topic, already: result.status === "already_unsubscribed" });
    } catch (err) {
      setState({ status: "error", topic, message: err instanceof ApiError ? err.message : "Please try again." });
    }
  }

  return (
    <div className="rounded-2xl border border-slate-200 bg-white p-6 text-center sm:p-8 dark:border-slate-800 dark:bg-slate-900">
      <h1 className="text-xl font-semibold text-slate-900 dark:text-slate-50">Unsubscribe from research digests</h1>

      {state.status === "checking" && (
        <p className="mt-3 text-sm text-slate-600 dark:text-slate-400" aria-live="polite">
          Checking your link…
        </p>
      )}

      {state.status === "invalid" && (
        <div role="alert" className="mt-4 space-y-2 text-sm">
          <p className="text-red-800 dark:text-red-300">{state.message}</p>
          <p className="text-slate-600 dark:text-slate-400">
            You can manage your subscriptions from{" "}
            <Link href="/account" className="font-medium text-teal-800 underline underline-offset-4 dark:text-teal-300">
              your account
            </Link>
            .
          </p>
        </div>
      )}

      {(state.status === "ready" || state.status === "working" || state.status === "error") && (
        <>
          <p className="mt-3 text-sm text-slate-700 dark:text-slate-300">
            Stop scheduled digest emails about{" "}
            <span className="font-semibold text-slate-900 dark:text-slate-100">&ldquo;{state.topic}&rdquo;</span>?
            Your other subscriptions aren&rsquo;t affected.
          </p>
          {state.status === "error" && (
            <p role="alert" className="mt-3 text-sm text-red-800 dark:text-red-300">
              {state.message}
            </p>
          )}
          <button
            type="button"
            onClick={() => unsubscribe(state.topic)}
            disabled={state.status === "working"}
            className="mt-5 inline-flex h-11 items-center rounded-lg bg-teal-700 px-5 text-sm font-semibold text-white hover:bg-teal-800 focus-visible:ring-2 focus-visible:ring-teal-600 focus-visible:ring-offset-2 focus-visible:outline-none disabled:opacity-60"
          >
            {state.status === "working" ? "Unsubscribing…" : "Unsubscribe"}
          </button>
        </>
      )}

      {state.status === "done" && (
        <div role="status" className="mt-4 space-y-2 text-sm">
          <p className="font-medium text-teal-900 dark:text-teal-200">
            {state.already ? "You were already unsubscribed from" : "You're unsubscribed from"} digests about
            &ldquo;{state.topic}&rdquo;.
          </p>
          <p className="text-slate-600 dark:text-slate-400">
            No more scheduled emails will be sent for this topic. To get them again, turn email back on for it in{" "}
            <Link href="/account" className="font-medium text-teal-800 underline underline-offset-4 dark:text-teal-300">
              your account
            </Link>
            .
          </p>
        </div>
      )}
    </div>
  );
}
