"use client";

import type { SummaryLevel } from "@/lib/api/types";

import { BellGlyph } from "./SubscriptionDialog";
import { useSubscriptions } from "./SubscriptionsProvider";

interface SubscribeBellProps {
  /** Topic to subscribe to (prefilled in the dialog). */
  topic: string;
  readingLevel?: SummaryLevel;
  /** "hero": square icon button beside the search box. "card": compact text button on a paper card. */
  variant?: "hero" | "card";
  disabled?: boolean;
}

/**
 * Netflix-style bell: outline when not subscribed, filled (with a dot) when
 * subscribed, and a short ring when a subscription is saved. Opens the
 * subscription dialog, which manages the existing subscription if one matches.
 */
export function SubscribeBell({ topic, readingLevel, variant = "hero", disabled }: SubscribeBellProps) {
  const { findByTopic, openSubscriptionDialog, lastSavedId } = useSubscriptions();
  const existing = findByTopic(topic);
  const subscribed = Boolean(existing);
  const trimmed = topic.trim();
  const label = subscribed
    ? `Manage subscription to “${existing!.topic}”`
    : trimmed
      ? `Subscribe to research updates for “${trimmed}”`
      : "Subscribe to research updates";

  const justSaved = Boolean(existing && existing.id === lastSavedId);
  const bell = (
    <span
      // Re-mount on each save so the ring animation replays.
      key={justSaved ? existing!.updatedAt : "idle"}
      className={`bell-swing inline-flex ${justSaved ? "bell-ring-once" : ""}`}
    >
      <BellGlyph ringing={subscribed} className={variant === "hero" ? "size-6" : "size-4"} />
    </span>
  );

  const open = () => openSubscriptionDialog({ topic: trimmed, readingLevel });

  if (variant === "card") {
    return (
      <button
        type="button"
        onClick={open}
        disabled={disabled}
        aria-haspopup="dialog"
        aria-label={label}
        title={label}
        className={`bell-trigger inline-flex items-center gap-1.5 rounded-lg px-2 py-1 font-medium transition focus-visible:ring-2 focus-visible:ring-teal-600 focus-visible:outline-none disabled:opacity-50 ${
          subscribed
            ? "text-teal-800 hover:bg-teal-50 dark:text-teal-300 dark:hover:bg-teal-950"
            : "text-slate-600 hover:bg-slate-100 hover:text-teal-800 dark:text-slate-300 dark:hover:bg-slate-800"
        }`}
      >
        {bell}
        <span aria-hidden="true">{subscribed ? "Following" : "Follow topic"}</span>
      </button>
    );
  }

  return (
    <button
      type="button"
      onClick={open}
      disabled={disabled}
      aria-haspopup="dialog"
      aria-label={label}
      title={label}
      className={`bell-trigger grid size-11 shrink-0 place-items-center rounded-xl border transition focus-visible:ring-2 focus-visible:ring-teal-600 focus-visible:ring-offset-2 focus-visible:outline-none disabled:opacity-50 ${
        subscribed
          ? "border-teal-700 bg-teal-50 text-teal-800 hover:bg-teal-100 dark:border-teal-500 dark:bg-teal-950 dark:text-teal-200 dark:hover:bg-teal-900"
          : "border-slate-300 bg-white text-slate-600 hover:border-teal-600 hover:text-teal-800 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-300 dark:hover:text-teal-300"
      }`}
    >
      {bell}
    </button>
  );
}
