import type { Paper } from "@/lib/api/types";
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
}

export function PaperCard({ paper, rank }: PaperCardProps) {
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
      className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm transition hover:shadow-md sm:p-6 dark:border-slate-800 dark:bg-slate-900"
    >
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-xs font-semibold text-slate-400 tabular-nums dark:text-slate-500">#{rank}</span>
          {retracted && (
            <span className="rounded-full bg-red-100 px-2.5 py-0.5 text-xs font-semibold text-red-800 dark:bg-red-950 dark:text-red-300">
              Retracted publication
            </span>
          )}
          {types.map((type) => (
            <span
              key={type}
              className="rounded-full bg-slate-100 px-2.5 py-0.5 text-xs font-medium text-slate-700 dark:bg-slate-800 dark:text-slate-300"
            >
              {type}
            </span>
          ))}
        </div>
        {paper.relevance_score !== null && <RelevanceBadge score={paper.relevance_score} />}
      </div>

      <h3 id={titleId} className="mt-3 text-lg leading-snug font-semibold text-slate-900 dark:text-slate-50">
        <a
          href={paper.pubmed_url}
          target="_blank"
          rel="noopener noreferrer"
          className="hover:text-teal-800 hover:underline focus-visible:ring-2 focus-visible:ring-teal-600 focus-visible:outline-none dark:hover:text-teal-300"
        >
          {paper.title}
          <span className="sr-only"> (opens PubMed in a new tab)</span>
        </a>
      </h3>

      <div className="mt-2 space-y-1">
        <AuthorList authors={paper.authors} />
        <p className="text-sm text-slate-500 dark:text-slate-400">
          <span className="font-medium text-slate-700 italic dark:text-slate-300">
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

      <div className="mt-4">
        <AbstractText abstract={paper.abstract} />
      </div>

      <div className="mt-4 flex flex-wrap items-center gap-x-6 gap-y-2 border-t border-slate-100 pt-4 text-sm dark:border-slate-800">
        <dl className="flex min-w-0 flex-wrap items-center gap-x-6 gap-y-2">
        <div className="flex gap-1.5">
          <dt className="text-slate-500 dark:text-slate-400">PMID</dt>
          <dd className="font-mono text-slate-800 dark:text-slate-200">{paper.pmid}</dd>
        </div>
        <div className="flex min-w-0 gap-1.5">
          <dt className="text-slate-500 dark:text-slate-400">DOI</dt>
          <dd className="min-w-0 break-all">
            {paper.doi && paper.doi_url ? (
              <a
                href={paper.doi_url}
                target="_blank"
                rel="noopener noreferrer"
                className="font-mono text-teal-800 underline-offset-4 hover:underline focus-visible:ring-2 focus-visible:ring-teal-600 focus-visible:outline-none dark:text-teal-300"
              >
                {paper.doi}
                <span className="sr-only"> (opens in a new tab)</span>
              </a>
            ) : (
              <span className="text-slate-500 italic dark:text-slate-400">Not available</span>
            )}
          </dd>
        </div>
        </dl>
        <a
          href={paper.pubmed_url}
          target="_blank"
          rel="noopener noreferrer"
          className="ml-auto inline-flex items-center gap-1 font-medium text-teal-800 underline-offset-4 hover:underline focus-visible:ring-2 focus-visible:ring-teal-600 focus-visible:outline-none dark:text-teal-300"
        >
          View on PubMed
          <span aria-hidden="true">↗</span>
          <span className="sr-only"> (opens in a new tab)</span>
        </a>
      </div>
    </article>
  );
}
