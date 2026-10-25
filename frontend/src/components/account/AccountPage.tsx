"use client";

import Link from "next/link";

import { useAuth } from "@/components/auth/AuthProvider";
import { SubscriptionList } from "@/components/subscriptions/SubscriptionList";

import { DeliveryHistory } from "./DeliveryHistory";
import { PreferencesForm } from "./PreferencesForm";
import { SavedSearchList } from "./SavedSearchList";
import { TestDigestPanel } from "./TestDigestPanel";

export function AccountPage() {
  const { status, account, openAuthDialog } = useAuth();

  if (status === "loading") {
    return (
      <div aria-busy="true" className="space-y-4">
        <div className="h-8 w-48 animate-pulse rounded bg-slate-200 dark:bg-slate-800" />
        <div className="h-48 animate-pulse rounded-2xl bg-slate-100 dark:bg-slate-900" />
      </div>
    );
  }

  if (status === "unavailable") {
    return (
      <div role="alert" className="rounded-2xl border border-amber-200 bg-amber-50 p-6 text-amber-950 dark:border-amber-900 dark:bg-amber-950/40 dark:text-amber-100">
        <h1 className="text-lg font-semibold">Accounts are temporarily unavailable</h1>
        <p className="mt-1 text-sm">The account service can&rsquo;t be reached right now. Search and paper analysis still work.</p>
        <Link href="/" className="mt-3 inline-block text-sm font-medium underline underline-offset-4">
          Back to search
        </Link>
      </div>
    );
  }

  if (status !== "authenticated" || !account) {
    return (
      <div className="rounded-2xl border border-slate-200 bg-white p-8 text-center dark:border-slate-800 dark:bg-slate-900">
        <h1 className="text-xl font-semibold text-slate-900 dark:text-slate-50">Your account</h1>
        <p className="mx-auto mt-2 max-w-md text-sm text-slate-600 dark:text-slate-400">
          Log in to set your preferred summary level and research interests, and to see your saved searches.
        </p>
        <div className="mt-5 flex justify-center gap-3">
          <button
            type="button"
            onClick={() => openAuthDialog("login")}
            className="rounded-lg bg-teal-700 px-5 py-2 font-semibold text-white hover:bg-teal-800 focus-visible:ring-2 focus-visible:ring-teal-600 focus-visible:ring-offset-2 focus-visible:outline-none"
          >
            Log in
          </button>
          <button
            type="button"
            onClick={() => openAuthDialog("register")}
            className="rounded-lg border border-slate-300 px-5 py-2 font-semibold text-slate-800 hover:border-teal-600 focus-visible:ring-2 focus-visible:ring-teal-600 focus-visible:outline-none dark:border-slate-700 dark:text-slate-100"
          >
            Create account
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-2xl font-bold tracking-tight text-slate-900 dark:text-slate-50">Your account</h1>
        <p className="mt-1 text-sm text-slate-600 dark:text-slate-400">
          Signed in as <span className="font-medium text-slate-800 dark:text-slate-200">{account.user.email}</span> ·{" "}
          <Link href="/" className="font-medium text-teal-800 underline-offset-4 hover:underline dark:text-teal-300">
            Back to search
          </Link>
        </p>
      </div>
      {/* key: reset the form if a different user signs in */}
      <PreferencesForm key={account.user.id} />
      <SavedSearchList key={`saved-${account.user.id}`} />
      <SubscriptionList />
      <DeliveryHistory key={`history-${account.user.id}`} />
      <TestDigestPanel key={`digest-${account.user.id}`} />
    </div>
  );
}
