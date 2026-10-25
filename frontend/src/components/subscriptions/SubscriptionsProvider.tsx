"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";

import { useAuth } from "@/components/auth/AuthProvider";
import * as api from "@/lib/api/client";
import { ApiError } from "@/lib/api/client";
import type { SummaryLevel } from "@/lib/api/types";
import { DEFAULT_SUMMARY_LEVEL } from "@/lib/filters";
import {
  fromSubscriptionApi,
  toSubscriptionInput,
  topicKey,
  type Subscription,
  type SubscriptionSettings,
} from "@/lib/subscriptions";

import { SubscriptionDialog } from "./SubscriptionDialog";

interface OpenOptions {
  /** Topic to prefill (e.g. the current search). If it matches an existing subscription, that one opens for editing. */
  topic: string;
  /** Reading level to prefill for a new subscription. */
  readingLevel?: SummaryLevel;
}

/** State of the list loaded from the server. */
export type SubscriptionsStatus = "anonymous" | "loading" | "ready" | "error";

interface SubscriptionsContextValue {
  /** The signed-in user's subscriptions, exactly as last loaded from the server. */
  subscriptions: Subscription[];
  status: SubscriptionsStatus;
  loadError: string | null;
  reload: () => void;
  findByTopic: (topic: string) => Subscription | undefined;
  openSubscriptionDialog: (options: OpenOptions) => void;
  /** Id of the subscription saved most recently (bells ring when it matches). */
  lastSavedId: string | null;
}

const SubscriptionsContext = createContext<SubscriptionsContextValue | null>(null);

export function useSubscriptions(): SubscriptionsContextValue {
  const value = useContext(SubscriptionsContext);
  if (!value) throw new Error("useSubscriptions must be used inside <SubscriptionsProvider>");
  return value;
}

type DialogState =
  | { mode: "create"; topic: string; readingLevel: SummaryLevel }
  | { mode: "edit"; subscription: Subscription };

function errorMessage(error: unknown, fallback: string): string {
  return error instanceof ApiError ? error.message : fallback;
}

/**
 * Research subscriptions for the signed-in user, stored on the server.
 *
 * The server is the source of truth: the list is loaded from /api/subscriptions
 * and re-fetched after every save or delete. Nothing is delivered yet.
 */
export function SubscriptionsProvider({ children }: { children: ReactNode }) {
  const { status: authStatus, account } = useAuth();
  const userId = authStatus === "authenticated" ? (account?.user.id ?? null) : null;
  const [subscriptions, setSubscriptions] = useState<Subscription[]>([]);
  const [listStatus, setListStatus] = useState<Exclude<SubscriptionsStatus, "anonymous">>("loading");
  const [loadError, setLoadError] = useState<string | null>(null);
  const [reloadToken, setReloadToken] = useState(0);
  const [dialog, setDialog] = useState<DialogState | null>(null);
  const [lastSavedId, setLastSavedId] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  // Different user (or logged out): forget the previous user's list right away.
  const [loadedFor, setLoadedFor] = useState<string | null>(userId);
  if (loadedFor !== userId) {
    setLoadedFor(userId);
    setSubscriptions([]);
    setListStatus("loading");
    setLoadError(null);
    setLastSavedId(null);
  }

  // Load the list from the server whenever the signed-in user changes (or on retry).
  useEffect(() => {
    if (!userId) return;
    const controller = new AbortController();
    api
      .listSubscriptions(controller.signal)
      .then((rows) => {
        setSubscriptions(rows.map(fromSubscriptionApi));
        setListStatus("ready");
        setLoadError(null);
      })
      .catch((error) => {
        if (controller.signal.aborted) return;
        setListStatus("error");
        setLoadError(errorMessage(error, "Your subscriptions could not be loaded."));
      });
    return () => controller.abort();
  }, [userId, reloadToken]);

  // Hide the confirmation toast after a few seconds.
  useEffect(() => {
    if (!notice) return;
    const timer = setTimeout(() => setNotice(null), 6000);
    return () => clearTimeout(timer);
  }, [notice]);

  /** Re-read the list from the server (the source of truth). */
  const refresh = useCallback(async () => {
    const rows = await api.listSubscriptions();
    setSubscriptions(rows.map(fromSubscriptionApi));
    setListStatus("ready");
    setLoadError(null);
  }, []);

  const findByTopic = useCallback(
    (topic: string) => {
      const key = topicKey(topic);
      return key ? subscriptions.find((s) => topicKey(s.topic) === key) : undefined;
    },
    [subscriptions],
  );

  const openSubscriptionDialog = useCallback(
    ({ topic, readingLevel }: OpenOptions) => {
      const existing = findByTopic(topic);
      setDialog(
        existing
          ? { mode: "edit", subscription: existing }
          : {
              mode: "create",
              topic,
              readingLevel: readingLevel ?? account?.preferences.summary_level ?? DEFAULT_SUMMARY_LEVEL,
            },
      );
    },
    [findByTopic, account],
  );

  /** Save to the server, then reload the list from it. Throws a user-readable message on failure. */
  async function save(settings: SubscriptionSettings, editingId: string | null): Promise<void> {
    const input = toSubscriptionInput(settings);
    let saved;
    try {
      saved = editingId ? await api.updateSubscription(editingId, input) : await api.createSubscription(input);
    } catch (error) {
      // A duplicate may exist that this page didn't know about: reload so the dialog can offer it.
      if (error instanceof ApiError && error.status === 409) await refresh().catch(() => undefined);
      throw new Error(errorMessage(error, "The subscription could not be saved. Please try again."));
    }
    await refresh().catch(() => setReloadToken((n) => n + 1));
    setLastSavedId(saved.id);
    setDialog(null);
    setNotice(
      `${editingId ? "Updated" : "Subscribed to"} “${saved.topic}”. Saved to your account. Emails aren't being sent yet.`,
    );
  }

  async function remove(id: string): Promise<void> {
    const removed = subscriptions.find((s) => s.id === id);
    try {
      await api.deleteSubscription(id);
    } catch (error) {
      if (error instanceof ApiError && error.status === 404) await refresh().catch(() => undefined);
      throw new Error(errorMessage(error, "The subscription could not be removed. Please try again."));
    }
    await refresh().catch(() => setReloadToken((n) => n + 1));
    setDialog(null);
    if (removed) setNotice(`Unsubscribed from “${removed.topic}”.`);
  }

  const status: SubscriptionsStatus = userId ? listStatus : "anonymous";
  const reload = useCallback(() => {
    setListStatus("loading");
    setReloadToken((n) => n + 1);
  }, []);

  const value = useMemo<SubscriptionsContextValue>(
    () => ({ subscriptions, status, loadError, reload, findByTopic, openSubscriptionDialog, lastSavedId }),
    [subscriptions, status, loadError, reload, findByTopic, openSubscriptionDialog, lastSavedId],
  );

  return (
    <SubscriptionsContext.Provider value={value}>
      {children}
      {dialog && (
        <SubscriptionDialog
          // Remount when switching between subscriptions so the form resets.
          key={dialog.mode === "edit" ? dialog.subscription.id : "new"}
          editing={dialog.mode === "edit" ? dialog.subscription : null}
          initialTopic={dialog.mode === "create" ? dialog.topic : ""}
          initialReadingLevel={dialog.mode === "create" ? dialog.readingLevel : dialog.subscription.readingLevel}
          listStatus={status}
          findByTopic={findByTopic}
          onSwitchToExisting={(subscription) => setDialog({ mode: "edit", subscription })}
          onSave={save}
          onUnsubscribe={remove}
          onClose={() => setDialog(null)}
        />
      )}
      <div aria-live="polite" className="pointer-events-none fixed inset-x-0 bottom-4 z-50 flex justify-center px-4">
        {notice && (
          <p className="pointer-events-auto flex max-w-lg items-start gap-2 rounded-xl bg-navy-900 px-4 py-3 text-sm text-white shadow-lg dark:bg-navy-100 dark:text-navy-900">
            <span aria-hidden="true">🔔</span>
            <span>{notice}</span>
          </p>
        )}
      </div>
    </SubscriptionsContext.Provider>
  );
}
