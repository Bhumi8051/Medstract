import { PaperAnalysisPanel } from "@/components/analysis/PaperAnalysisPanel";
import { SubscribeBell } from "@/components/subscriptions/SubscribeBell";
import type { Paper, SummaryLevel } from "@/lib/api/types";
import { formatPublicationDate, isRetracted, languageName } from "@/lib/format";

import { AbstractText } from "./AbstractText";
import { AuthorList } from "./AuthorList";
import { RelevanceBadge } from "./RelevanceBadge";

// PubMed tags almost every record "Journal Article"; it adds no information.
const HIDDEN_TYPES = new Set(["journal article"]);
const MAX_TYPE_BADGES = 3;

interface PaperCardProps {
  paper: Paper;
  rank: number;
  summaryLevel: SummaryLevel;
}

export function PaperCard({ paper, rank, summaryLevel }: PaperCardProps) {
  const date = formatPublicationDate(paper);
  const retracted = isRetracted(paper);
  // Most results are English; only call out the language when it's something else.
  const nonEnglish = paper.languages.some((code) => code.toLowerCase() !== "eng");
  const types = paper.publication_types
    .filter((type) => !HIDDEN_TYPES.has(type.toLowerCase()) && type.toLowerCase() !== "retracted publication")
    .slice(0, MAX_TYPE_BADGES);
  const titleId = `paper-${paper.pmid}-title`;

  return (
    <article
      aria-labelledby={titleId}
      className="overflow-hidden rounded-2xl border border-navy-200 bg-white shadow-sm transition hover:border-navy-300 dark:border-navy-800 dark:bg-navy-900 dark:hover:border-navy-700"
    >
      {/* Rank, type badges and relevance on a tinted strip, apart from the paper itself. */}
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-navy-100 bg-navy-50 px-5 py-3 sm:px-7 dark:border-navy-800 dark:bg-navy-950/50">
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-sm font-bold text-brand-700 tabular-nums dark:text-brand-300">#{rank}</span>
          {retracted && (
            <span className="rounded-full bg-red-100 px-2.5 py-0.5 text-xs font-semibold text-red-800 dark:bg-red-950 dark:text-red-300">
              Retracted publication
            </span>
          )}
          {types.map((type) => (
            <span
              key={type}
              className="rounded-full bg-navy-100 px-2.5 py-0.5 text-xs font-medium text-navy-700 dark:bg-navy-800 dark:text-navy-300"
            >
              {type}
            </span>
          ))}
        </div>
        {paper.relevance_score !== null && <RelevanceBadge score={paper.relevance_score} />}
      </div>

      <div className="p-5 sm:p-7">
        <h3 id={titleId} className="text-xl leading-snug font-semibold tracking-tight text-navy-900 dark:text-navy-50">
          <a
            href={paper.pubmed_url}
            target="_blank"
            rel="noopener noreferrer"
            className="hover:text-brand-800 hover:underline focus-visible:ring-2 focus-visible:ring-brand-600 focus-visible:outline-none dark:hover:text-brand-300"
          >
            {paper.title}
            <span className="sr-only"> (opens PubMed in a new tab)</span>
          </a>
        </h3>

        <div className="mt-3 space-y-1">
          <AuthorList authors={paper.authors} />
          <p className="text-sm text-navy-500 dark:text-navy-400">
            <span className="font-medium text-navy-700 italic dark:text-navy-300">
              {paper.journal ?? "Journal not reported"}
            </span>
            <span aria-hidden="true"> · </span>
            <span>{date ? <time dateTime={paper.publication_date_iso ?? undefined}>{date}</time> : "Date not reported"}</span>
            {nonEnglish && (
              <>
                <span aria-hidden="true"> · </span>
                <span>{paper.languages.map(languageName).join(", ")}</span>
              </>
            )}
          </p>
        </div>

        <div className="mt-5">
          <AbstractText abstract={paper.abstract} />
        </div>

        <div className="mt-5 flex flex-wrap items-center gap-x-6 gap-y-2 border-t border-navy-100 pt-4 text-sm dark:border-navy-800">
          <dl className="flex min-w-0 flex-wrap items-center gap-x-6 gap-y-2">
          <div className="flex gap-1.5">
            <dt className="text-navy-500 dark:text-navy-400">PMID</dt>
            <dd className="text-navy-800 tabular-nums dark:text-navy-200">{paper.pmid}</dd>
          </div>
          <div className="flex min-w-0 gap-1.5">
            <dt className="text-navy-500 dark:text-navy-400">DOI</dt>
            <dd className="min-w-0 break-all">
              {paper.doi && paper.doi_url ? (
                <a
                  href={paper.doi_url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-brand-800 underline-offset-4 hover:underline focus-visible:ring-2 focus-visible:ring-brand-600 focus-visible:outline-none dark:text-brand-300"
                >
                  {paper.doi}
                  <span className="sr-only"> (opens in a new tab)</span>
                </a>
              ) : (
                <span className="text-navy-500 italic dark:text-navy-400">Not available</span>
              )}
            </dd>
          </div>
          </dl>
          {/* Follow this paper's topic: prefilled with its title, which the user can broaden. */}
          <span className="ml-auto">
            <SubscribeBell topic={paper.title.replace(/\.$/, "")} readingLevel={summaryLevel} variant="card" />
          </span>
          <a
            href={paper.pubmed_url}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center gap-1 font-medium text-brand-800 underline-offset-4 hover:underline focus-visible:ring-2 focus-visible:ring-brand-600 focus-visible:outline-none dark:text-brand-300"
          >
            View on PubMed
            <span aria-hidden="true">↗</span>
            <span className="sr-only"> (opens in a new tab)</span>
          </a>
        </div>

        <PaperAnalysisPanel pmid={paper.pmid} summaryLevel={summaryLevel} />
      </div>
    </article>
  );
}
