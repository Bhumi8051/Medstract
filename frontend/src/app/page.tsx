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

      <footer className="border-t border-navy-200 dark:border-navy-800">
        <p className="page-container py-6 text-xs text-navy-500 dark:text-navy-400">
          Literature data from PubMed via NCBI E-utilities. Always check findings against the original record.
        </p>
      </footer>
    </>
  );
}

/** Static placeholder with the same shape as the search hero, shown for a moment while the page hydrates. */
function SearchFallback() {
  return (
    <div className="border-b border-navy-200 bg-navy-100 dark:border-navy-800 dark:bg-navy-800" aria-hidden="true">
      <div className="page-container py-16 text-center sm:py-24">
        <p className="text-3xl font-bold tracking-tight text-navy-950 sm:text-5xl dark:text-white">Discover biomedical research</p>
        <div className="mx-auto mt-10 h-16 max-w-3xl rounded-2xl border border-navy-200 bg-white shadow-sm dark:border-navy-700 dark:bg-navy-950" />
      </div>
    </div>
  );
}
