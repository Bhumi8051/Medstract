"use client";

import { useEffect, useId, useRef, useState } from "react";

import { useAiUsage } from "@/components/analysis/AiUsageProvider";
import { ErrorAlert } from "@/components/feedback/ErrorAlert";
import { useSubscriptions } from "@/components/subscriptions/SubscriptionsProvider";
import { ApiError, getEmailStatus, previewDigest, sendTestDigest } from "@/lib/api/client";
import type { Digest, EmailStatus } from "@/lib/api/types";
import { labelFor } from "@/lib/filters";
import { READING_LEVEL_OPTIONS } from "@/lib/subscriptions";

const MAX_TOPICS = 3;

type Phase = "idle" | "previewing" | "sending";

interface Outcome {
  kind: "preview" | "sent";
  digest: Digest;
  sentTo?: string;
  messageId?: string;
}

/**
 * Step C: build a digest from chosen subscriptions, preview it, or send ONE test
 * email to the signed-in account's own address. The server decides the recipient
 * and enforces every safety check; this panel only explains what it will do.
 */
export function TestDigestPanel() {
  const { subscriptions, status: subsStatus } = useSubscriptions();
  const { refresh: refreshUsage } = useAiUsage();
  const headingId = useId();

  const [emailStatus, setEmailStatus] = useState<EmailStatus | null>(null);
  const [statusError, setStatusError] = useState<string | null>(null);
  const [statusToken, setStatusToken] = useState(0);
  // null = nothing chosen yet, so default to the first subscription.
  const [selected, setSelected] = useState<string[] | null>(null);
  const [phase, setPhase] = useState<Phase>("idle");
  const [outcome, setOutcome] = useState<Outcome | null>(null);
  const [error, setError] = useState<string | null>(null);
  const controllerRef = useRef<AbortController | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    getEmailStatus(controller.signal)
      .then((value) => {
        setEmailStatus(value);
        setStatusError(null);
      })
      .catch((err: unknown) => {
        if (controller.signal.aborted) return;
        setStatusError(err instanceof ApiError ? err.message : "Email settings could not be loaded.");
      });
    return () => controller.abort();
  }, [statusToken]);

  useEffect(() => () => controllerRef.current?.abort(), []);

  const known = new Set(subscriptions.map((s) => s.id));
  const chosen = (selected ?? (subscriptions[0] ? [subscriptions[0].id] : [])).filter((id) => known.has(id));
  const ready = !!emailStatus && emailStatus.enabled && emailStatus.configured && emailStatus.recipient_allowed;
  const busy = phase !== "idle";

  function toggle(id: string) {
    setSelected(chosen.includes(id) ? chosen.filter((x) => x !== id) : [...chosen, id].slice(0, MAX_TOPICS));
  }

  async function run(kind: "preview" | "send") {
    if (busy || chosen.length === 0) return;
    const controller = new AbortController();
    controllerRef.current = controller;
    setPhase(kind === "preview" ? "previewing" : "sending");
    setError(null);
    setOutcome(null);
    try {
      if (kind === "preview") {
        const digest = await previewDigest(chosen, controller.signal);
        if (!controller.signal.aborted) setOutcome({ kind: "preview", digest });
      } else {
        const result = await sendTestDigest(chosen, controller.signal);
        if (!controller.signal.aborted) {
          setOutcome({ kind: "sent", digest: result.digest, sentTo: result.sent_to, messageId: result.provider_message_id });
        }
      }
    } catch (err) {
      if (controller.signal.aborted) return;
      setError(err instanceof ApiError ? err.message : "Something went wrong. Please try again.");
    } finally {
      if (!controller.signal.aborted) setPhase("idle");
      refreshUsage(); // AI summaries use (or refund) the daily allowance
    }
  }

  return (
    <section
      aria-labelledby={headingId}
      className="rounded-2xl border border-slate-200 bg-white p-5 sm:p-6 dark:border-slate-800 dark:bg-slate-900"
    >
      <h2 id={headingId} className="text-lg font-semibold text-slate-900 dark:text-slate-50">
        Test email digest
      </h2>
      <p className="mt-1 text-sm text-slate-600 dark:text-slate-400">
        Build a digest from your subscriptions and send one test email to yourself.{" "}
        <span className="rounded-full bg-amber-100 px-2 py-0.5 text-xs font-medium text-amber-900 dark:bg-amber-950 dark:text-amber-200">
          Manual test · automatic delivery not active yet
        </span>
      </p>

      <EmailReadiness status={emailStatus} error={statusError} onRetry={() => setStatusToken((n) => n + 1)} />

      <fieldset className="mt-5" disabled={busy}>
        <legend className="text-sm font-medium text-slate-800 dark:text-slate-200">
          Topics to include <span className="font-normal text-slate-500 dark:text-slate-400">(up to {MAX_TOPICS})</span>
        </legend>
        {subsStatus === "loading" && <p className="mt-2 text-sm text-slate-500">Loading your subscriptions…</p>}
        {subsStatus === "ready" && subscriptions.length === 0 && (
          <p className="mt-2 text-sm text-slate-600 dark:text-slate-400">
            Create a research subscription first (the bell beside the search box, or &ldquo;New subscription&rdquo; above).
          </p>
        )}
        {subscriptions.length > 0 && (
          <ul className="mt-2 space-y-1.5">
            {subscriptions.map((s) => {
              const checked = chosen.includes(s.id);
              return (
                <li key={s.id}>
                  <label className="flex min-h-11 cursor-pointer items-center gap-3 rounded-lg border border-slate-200 px-3 py-2 text-sm hover:border-teal-600 has-[:disabled]:cursor-not-allowed has-[:disabled]:opacity-60 dark:border-slate-700">
                    <input
                      type="checkbox"
                      checked={checked}
                      disabled={!checked && chosen.length >= MAX_TOPICS}
                      onChange={() => toggle(s.id)}
                      className="size-4 accent-teal-700"
                    />
                    <span className="min-w-0 flex-1 break-words font-medium text-slate-900 dark:text-slate-100">{s.topic}</span>
                    <span className="shrink-0 text-xs text-slate-500 dark:text-slate-400">
                      {s.paperCount} papers · {labelFor(READING_LEVEL_OPTIONS, s.readingLevel)}
                    </span>
                  </label>
                </li>
              );
            })}
          </ul>
        )}
      </fieldset>

      <div className="mt-4 flex flex-wrap items-center gap-3">
        <button
          type="button"
          onClick={() => run("preview")}
          disabled={busy || chosen.length === 0}
          className="inline-flex h-11 items-center rounded-lg border border-slate-300 px-4 text-sm font-semibold text-slate-800 hover:border-teal-600 focus-visible:ring-2 focus-visible:ring-teal-600 focus-visible:outline-none disabled:cursor-not-allowed disabled:opacity-60 dark:border-slate-700 dark:text-slate-100"
        >
          {phase === "previewing" ? "Building preview…" : "Preview digest"}
        </button>
        <button
          type="button"
          onClick={() => run("send")}
          disabled={busy || chosen.length === 0 || !ready}
          className="inline-flex h-11 items-center rounded-lg bg-teal-700 px-4 text-sm font-semibold text-white hover:bg-teal-800 focus-visible:ring-2 focus-visible:ring-teal-600 focus-visible:ring-offset-2 focus-visible:outline-none disabled:cursor-not-allowed disabled:opacity-60"
        >
          {phase === "sending" ? "Sending…" : "Send test email"}
        </button>
      </div>
      <p className="mt-2 text-xs text-slate-500 dark:text-slate-400" aria-live="polite">
        {busy
          ? "Searching PubMed and writing AI summaries. This can take up to a minute per topic."
          : "AI summaries use 1 of your daily AI analyses per topic, each time you preview or send."}
      </p>

      {error && (
        <div className="mt-4">
          <ErrorAlert title="The digest could not be completed" message={error} />
        </div>
      )}

      {outcome?.kind === "sent" && (
        <div role="status" className="mt-4 rounded-xl border border-teal-200 bg-teal-50 p-4 text-sm text-teal-950 dark:border-teal-900 dark:bg-teal-950/40 dark:text-teal-100">
          <p className="font-semibold">Handed to the email service for {outcome.sentTo}.</p>
          <p className="mt-1">
            Check your inbox, and your spam folder. Resend message ID:{" "}
            <code className="rounded bg-white/70 px-1 break-all dark:bg-black/30">{outcome.messageId}</code> (it matches
            the entry in your Resend dashboard under Emails).
          </p>
        </div>
      )}

      {outcome && <DigestView digest={outcome.digest} heading={outcome.kind === "sent" ? "What was sent" : "Preview"} />}
    </section>
  );
}

function EmailReadiness({ status, error, onRetry }: { status: EmailStatus | null; error: string | null; onRetry: () => void }) {
  if (error) {
    return (
      <div className="mt-4">
        <ErrorAlert title="Email settings could not be loaded" message={error} onRetry={onRetry} />
      </div>
    );
  }
  if (!status) return <p className="mt-4 text-sm text-slate-500">Checking email settings…</p>;

  const checks = [
    { ok: status.enabled, label: "Email sending is switched on", fix: "Set EMAIL_ENABLED=true in backend/.env" },
    { ok: status.configured, label: "Resend API key is set", fix: "Add RESEND_API_KEY to backend/.env" },
    {
      ok: status.recipient_allowed,
      label: "Your address may receive test emails",
      fix: `Add ${status.recipient} to EMAIL_TEST_RECIPIENTS in backend/.env`,
    },
  ];
  const allOk = checks.every((c) => c.ok);
  return (
    <div className="mt-4 rounded-xl border border-slate-200 p-4 text-sm dark:border-slate-700">
      <p className="text-slate-700 dark:text-slate-300">
        Sends to <span className="font-medium text-slate-900 dark:text-slate-100">{status.recipient}</span> (your account email; it can&rsquo;t be changed here).
      </p>
      <ul className="mt-2 space-y-1">
        {checks.map((c) => (
          <li key={c.label} className={c.ok ? "text-teal-800 dark:text-teal-300" : "text-amber-900 dark:text-amber-200"}>
            <span aria-hidden="true">{c.ok ? "✓" : "✗"}</span> {c.label}
            {!c.ok && <span className="text-slate-600 dark:text-slate-400">: {c.fix}</span>}
          </li>
        ))}
      </ul>
      {!allOk && (
        <p className="mt-2 text-xs text-slate-500 dark:text-slate-400">Restart the backend after editing backend/.env.</p>
      )}
      {status.test_sender && (
        <p className="mt-2 text-xs text-slate-500 dark:text-slate-400">
          Using Resend&rsquo;s test sender: it only delivers to the email address you signed up to Resend with.
        </p>
      )}
    </div>
  );
}

function DigestView({ digest, heading }: { digest: Digest; heading: string }) {
  return (
    <div className="mt-5 rounded-xl border border-slate-200 p-4 dark:border-slate-700">
      <p className="text-xs font-semibold tracking-wide text-slate-500 uppercase dark:text-slate-400">{heading}</p>
      <h3 className="mt-1 font-semibold text-slate-900 dark:text-slate-50">{digest.subject}</h3>
      {digest.sections.map((section) => (
        <div key={section.subscription_id} className="mt-4">
          <h4 className="font-medium text-slate-900 dark:text-slate-100">{section.topic}</h4>
          <p className="text-xs text-slate-500 dark:text-slate-400">
            {section.window} · {labelFor(READING_LEVEL_OPTIONS, section.reading_level)} · {section.papers.length} papers
          </p>
          {section.ai_note && section.ai_status !== "generated" && (
            <p className="mt-2 rounded-lg bg-amber-50 px-3 py-2 text-xs text-amber-900 dark:bg-amber-950/40 dark:text-amber-200">
              {section.ai_note}
            </p>
          )}
          {section.papers.length === 0 && <p className="mt-2 text-sm text-slate-500">No PubMed papers matched this topic.</p>}
          <ol className="mt-2 space-y-3">
            {section.papers.map((paper) => (
              <li key={paper.pmid} className="text-sm">
                <a
                  href={paper.pubmed_url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="font-medium text-teal-800 underline-offset-4 hover:underline dark:text-teal-300"
                >
                  {paper.title}
                </a>
                <p className="text-xs text-slate-500 dark:text-slate-400">
                  {[paper.authors.join(", "), paper.journal, paper.publication_date].filter(Boolean).join(" · ")} · PMID {paper.pmid}
                </p>
                {paper.ai_summary ? (
                  <p className="mt-1 text-slate-700 dark:text-slate-300">
                    <span className="font-medium">AI summary:</span> {paper.ai_summary}
                  </p>
                ) : (
                  <>
                    {paper.summary_note && <p className="mt-1 text-xs text-slate-500 italic">{paper.summary_note}</p>}
                    {paper.abstract_excerpt && (
                      <p className="mt-1 text-slate-700 dark:text-slate-300">
                        <span className="font-medium">From the abstract:</span> {paper.abstract_excerpt}
                      </p>
                    )}
                  </>
                )}
              </li>
            ))}
          </ol>
        </div>
      ))}
      <p className="mt-4 text-xs text-slate-500 dark:text-slate-400">{digest.disclaimer}</p>
    </div>
  );
}
