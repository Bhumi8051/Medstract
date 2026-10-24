import { SiteHeader } from "@/components/layout/SiteHeader";
import { ResearchSearch } from "@/components/search/ResearchSearch";

export default function HomePage() {
  return (
    <>
      <SiteHeader />

      <main className="flex-1">
        <ResearchSearch />
      </main>

      <footer className="border-t border-slate-200 dark:border-slate-800">
        <p className="mx-auto max-w-6xl px-4 py-5 text-xs text-slate-500 sm:px-6 dark:text-slate-400">
          Literature data from PubMed via NCBI E-utilities. Always check findings against the original record.
        </p>
      </footer>
    </>
  );
}
