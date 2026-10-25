"use client";

import Link from "next/link";

import { useAuth } from "@/components/auth/AuthProvider";
import { SubscriptionList } from "@/components/subscriptions/SubscriptionList";

import { DeliveryHistory } from "./DeliveryHistory";
import { PreferencesForm } from "./PreferencesForm";
import { SavedSearchList } from "./SavedSearchList";
import { TestDigestPanel } from "./TestDigestPanel";

// The sections below, in page order, for the sidebar's jump links (ids are set on each section).
const SECTIONS = [
  { id: "preferences", label: "Research preferences" },
  { id: "saved-searches", label: "Saved searches" },
  { id: "subscriptions", label: "Research subscriptions" },
  { id: "digest-history", label: "Scheduled digest history" },
  { id: "test-digest", label: "Test email digest" },
];

export function AccountPage() {
  const { status, account, openAuthDialog } = useAuth();

  if (status === "loading") {
    return (
      <div aria-busy="true" className="page-container max-w-4xl space-y-4 py-12">
        <div className="h-8 w-48 animate-pulse rounded bg-navy-200 dark:bg-navy-800" />
        <div className="h-48 animate-pulse rounded-2xl bg-navy-100 dark:bg-navy-900" />
      </div>
    );
  }

  if (status === "unavailable") {
    return (
      <div className="page-container max-w-4xl py-12">
        <div role="alert" className="rounded-2xl border border-amber-200 bg-amber-50 p-6 text-amber-950 dark:border-amber-900 dark:bg-amber-950/40 dark:text-amber-100">
          <h1 className="text-lg font-semibold">Accounts are temporarily unavailable</h1>
          <p className="mt-1 text-sm">The account service can&rsquo;t be reached right now. Search and paper analysis still work.</p>
          <Link href="/" className="mt-3 inline-block text-sm font-medium underline underline-offset-4">
            Back to search
          </Link>
        </div>
      </div>
    );
  }

  if (status !== "authenticated" || !account) {
    return (
      <div className="page-container max-w-2xl py-12">
        <div className="rounded-2xl border border-navy-200 bg-white p-8 text-center shadow-sm sm:p-10 dark:border-navy-800 dark:bg-navy-900">
          <h1 className="text-xl font-semibold text-navy-900 dark:text-navy-50">Your account</h1>
          <p className="mx-auto mt-2 max-w-md text-sm text-navy-600 dark:text-navy-400">
            Log in to set your preferred summary level and research interests, and to see your saved searches.
          </p>
          <div className="mt-5 flex justify-center gap-3">
            <button
              type="button"
              onClick={() => openAuthDialog("login")}
              className="rounded-lg bg-brand-700 px-5 py-2 font-semibold text-white hover:bg-brand-800 focus-visible:ring-2 focus-visible:ring-brand-600 focus-visible:ring-offset-2 focus-visible:outline-none"
            >
              Log in
            </button>
            <button
              type="button"
              onClick={() => openAuthDialog("register")}
              className="rounded-lg border border-navy-300 px-5 py-2 font-semibold text-navy-800 hover:border-brand-600 focus-visible:ring-2 focus-visible:ring-brand-600 focus-visible:outline-none dark:border-navy-700 dark:text-navy-100"
            >
              Create account
            </button>
          </div>
        </div>
      </div>
    );
  }

  return (
    <>
      {/* Band matching the search page: a cream section in the light theme, deep navy in the dark. */}
      <div className="border-b border-navy-200 bg-navy-100 text-navy-900 dark:border-navy-800 dark:bg-navy-800 dark:text-navy-50">
        <div className="page-container py-10 sm:py-14">
          <h1 className="text-3xl font-bold tracking-tight sm:text-4xl">Your account</h1>
        </div>
      </div>

      <div className="page-container grid items-start gap-8 py-8 sm:py-10 lg:grid-cols-[16rem_minmax(0,1fr)]">
        <aside className="space-y-4 lg:sticky lg:top-6">
          <div className="rounded-2xl bg-white p-6 shadow-sm ring-1 ring-navy-200 dark:bg-navy-900 dark:ring-navy-800">
            <span
              aria-hidden="true"
              className="grid size-12 place-items-center rounded-xl bg-highlight text-xl font-bold text-navy-950 uppercase"
            >
              {account.user.email[0]}
            </span>
            <p className="mt-4 text-sm text-navy-500 dark:text-navy-300">
              Signed in as <span className="mt-0.5 block font-medium break-all text-navy-900 dark:text-navy-50">{account.user.email}</span>
            </p>
          </div>
          {/* Jump links; on small screens the sections simply follow each other. */}
          <nav aria-label="Account sections" className="hidden lg:block">
            <ul className="space-y-1">
              {SECTIONS.map((section) => (
                <li key={section.id}>
                  <a
                    href={`#${section.id}`}
                    className="block rounded-lg px-3 py-2 text-sm font-medium text-navy-700 transition hover:bg-white hover:text-navy-950 hover:shadow-sm focus-visible:ring-2 focus-visible:ring-brand-600 focus-visible:outline-none dark:text-navy-300 dark:hover:bg-navy-900 dark:hover:text-white"
                  >
                    {section.label}
                  </a>
                </li>
              ))}
            </ul>
          </nav>
          <Link
            href="/"
            className="inline-block px-3 text-sm font-medium text-brand-700 underline-offset-4 hover:underline focus-visible:ring-2 focus-visible:ring-brand-600 focus-visible:outline-none dark:text-brand-300"
          >
            Back to search
          </Link>
        </aside>

        <div className="min-w-0 space-y-8">
          {/* key: reset the form if a different user signs in */}
          <PreferencesForm key={account.user.id} />
          <SavedSearchList key={`saved-${account.user.id}`} />
          <SubscriptionList />
          <DeliveryHistory key={`history-${account.user.id}`} />
          <TestDigestPanel key={`digest-${account.user.id}`} />
        </div>
      </div>
    </>
  );
}
