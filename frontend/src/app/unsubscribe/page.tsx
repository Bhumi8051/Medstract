import type { Metadata } from "next";
import { Suspense } from "react";

import { SiteHeader } from "@/components/layout/SiteHeader";
import { UnsubscribeConfirm } from "@/components/unsubscribe/UnsubscribeConfirm";

export const metadata: Metadata = {
  title: "Unsubscribe · Healthcare Research Intelligence Agent",
  // The page URL contains the unsubscribe token: keep it out of Referer headers and search engines.
  referrer: "no-referrer",
  robots: { index: false, follow: false },
};

export default function UnsubscribeRoute() {
  return (
    <>
      <SiteHeader />
      <main className="mx-auto w-full max-w-xl flex-1 px-4 py-12 sm:px-6">
        {/* Reads ?token=, so it renders on the client (Next.js requires a Suspense boundary). */}
        <Suspense fallback={<div aria-hidden="true" className="h-40 animate-pulse rounded-2xl bg-slate-100 dark:bg-slate-900" />}>
          <UnsubscribeConfirm />
        </Suspense>
      </main>
    </>
  );
}
