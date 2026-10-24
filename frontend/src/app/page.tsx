import { Suspense } from "react";

import { SiteHeader } from "@/components/layout/SiteHeader";
import { ResearchSearch } from "@/components/search/ResearchSearch";

export default function HomePage() {
  return (
    <>
      <SiteHeader />

      <main className="flex-1">
        {/* ResearchSearch reads ?saved=<id>, so it renders on the client (Next.js requires a Suspense boundary). */}
        <Suspense fallback={<SearchFallback />}>
          <ResearchSearch />
        </Suspense>
      </main>

      <footer className="border-t border-slate-200 dark:border-slate-800">
        <p className="mx-auto max-w-6xl px-4 py-5 text-xs text-slate-500 sm:px-6 dark:text-slate-400">
          Literature data from PubMed via NCBI E-utilities. Always check findings against the original record.
        </p>
      </footer>
    </>
  );
}

/** Static placeholder with the same shape as the search hero, shown for a moment while the page hydrates. */
function SearchFallback() {
  return (
    <div className="mx-auto w-full max-w-3xl px-4 py-14 text-center sm:py-24" aria-hidden="true">
      <p className="text-3xl font-bold tracking-tight text-slate-900 sm:text-4xl dark:text-slate-50">
        Discover biomedical research
      </p>
      <div className="mx-auto mt-8 h-16 rounded-2xl border border-slate-300 bg-white shadow-md dark:border-slate-700 dark:bg-slate-900" />
    </div>
  );
}
