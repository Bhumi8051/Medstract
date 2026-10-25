/**
 * Labels for scheduled digest runs (backend digest_deliveries). Display only:
 * the server decides what is sent.
 */

import type { DeliveryStatus } from "./api/types";

export type StatusTone = "success" | "neutral" | "info" | "warning" | "danger";

export const DELIVERY_STATUS: Record<DeliveryStatus, { label: string; tone: StatusTone; hint: string }> = {
  pending: { label: "Queued", tone: "info", hint: "Waiting to be sent, or to be retried." },
  sending: { label: "Sending", tone: "info", hint: "Being sent right now." },
  sent: { label: "Sent", tone: "success", hint: "The email service accepted it." },
  dry_run: { label: "Dry run", tone: "neutral", hint: "Built for testing; deliberately not sent." },
  skipped_no_new: { label: "Skipped: nothing new", tone: "neutral", hint: "No new papers, and you chose not to get empty digests." },
  skipped_missed: {
    label: "Skipped: missed",
    tone: "neutral",
    hint: "Not sent: too late to be useful (the server was off, or delivery was paused).",
  },
  skipped_disabled: { label: "Skipped", tone: "neutral", hint: "Email was off, unsubscribed, or not allowed when it was due." },
  failed: { label: "Failed", tone: "danger", hint: "The email could not be sent. It was not delivered." },
  needs_review: {
    label: "Needs review",
    tone: "warning",
    hint: "The outcome is unclear: it may have been delivered. It won't be resent automatically.",
  },
};

const REASONS: Record<string, string> = {
  unsubscribed: "unsubscribed via an email link",
  email_off: "email was turned off",
  schedule_changed: "the schedule was changed",
  not_allowlisted: "this address isn't approved for test sending",
  recipient_changed: "the account email changed",
  mode_changed: "sending was switched to dry run",
  missed: "the server was off at the scheduled time",
  expired: "it was still queued after its grace period (delivery was paused or the server was off), so it wasn't sent",
  subscription_deleted: "the subscription was deleted",
  idempotency_window_expired: "too long passed to retry safely",
  idempotency_conflict: "the email service reports it was already sent",
  lease_expired: "recovered after an interruption",
  pubmed_error: "PubMed was unavailable",
  internal_error: "an unexpected error",
  timeout: "the email service timed out",
  resend_429: "the email service was busy",
};

/** Friendly text for a reason code; unknown codes are shown as-is. */
export function describeReason(code: string | null): string | null {
  if (!code) return null;
  if (REASONS[code]) return REASONS[code];
  if (/^resend_\d{3}$/.test(code)) return `the email service answered ${code.slice(7)}`;
  return code.replace(/_/g, " ");
}

/** "Sun, Nov 1, 12:00 AM EST" in the subscription's own time zone. */
export function formatInZone(iso: string, timeZone: string): string {
  try {
    return new Intl.DateTimeFormat(undefined, {
      weekday: "short",
      month: "short",
      day: "numeric",
      hour: "numeric",
      minute: "2-digit",
      timeZone,
      timeZoneName: "short",
    }).format(new Date(iso));
  } catch {
    return new Date(iso).toLocaleString();
  }
}

export const TONE_CLASSES: Record<StatusTone, string> = {
  success: "bg-teal-100 text-teal-900 dark:bg-teal-950 dark:text-teal-200",
  neutral: "bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-300",
  info: "bg-sky-100 text-sky-900 dark:bg-sky-950 dark:text-sky-200",
  warning: "bg-amber-100 text-amber-900 dark:bg-amber-950 dark:text-amber-200",
  danger: "bg-red-100 text-red-900 dark:bg-red-950 dark:text-red-200",
};
