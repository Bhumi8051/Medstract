import type { SearchResponse } from "@/lib/api/types";
import { formatCount, formatIsoDay } from "@/lib/format";

interface ResultsSummaryProps {
  data: SearchResponse;
}

export function ResultsSummary({ data }: ResultsSummaryProps) {
  const details: string[] = [];
  if (data.start_date || data.end_date) {
    const from = data.start_date ? formatIsoDay(data.start_date) : "any date";
    const to = data.end_date ? formatIsoDay(data.end_date) : "present";
    details.push(`Published ${from} – ${to}`);
  }
  if (data.duplicates_removed > 0) {
    details.push(`${formatCount(data.duplicates_removed)} duplicate${data.duplicates_removed === 1 ? "" : "s"} removed`);
  }
  if (data.excluded_by_date > 0) {
    details.push(`${formatCount(data.excluded_by_date)} excluded by date`);
  }

  return (
    <div className="space-y-3">
      <div>
        <h2 id="results-heading" className="text-lg font-semibold text-slate-900 dark:text-slate-50">
          Showing {formatCount(data.returned)} of {formatCount(data.total_results)} PubMed matches
        </h2>
        <p className="mt-1 text-sm text-slate-600 dark:text-slate-400">
          for <span className="font-medium text-slate-800 dark:text-slate-200">“{data.query}”</span>, ranked by
          keyword match with PubMed&rsquo;s order breaking ties.
        </p>
        {details.length > 0 && (
          <ul className="mt-2 flex flex-wrap gap-2 text-xs">
            {details.map((detail) => (
              <li
                key={detail}
                className="rounded-full bg-slate-100 px-2.5 py-1 font-medium text-slate-700 dark:bg-slate-800 dark:text-slate-300"
              >
                {detail}
              </li>
            ))}
          </ul>
        )}
        <details className="mt-2 text-xs text-slate-500 dark:text-slate-400">
          <summary className="cursor-pointer select-none hover:text-slate-700 dark:hover:text-slate-200">
            PubMed query used
          </summary>
          <code className="mt-1 block rounded bg-slate-100 px-2 py-1.5 font-mono break-words text-slate-800 dark:bg-slate-800 dark:text-slate-200">
            {data.pubmed_query}
          </code>
          {(data.start_date || data.end_date) && (
            <p className="mt-1">Date filter applied to PubMed&rsquo;s Publication Date field ([dp]).</p>
          )}
        </details>
      </div>

      {data.warnings.length > 0 && (
        <div className="rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900 dark:border-amber-900 dark:bg-amber-950/50 dark:text-amber-200">
          <p className="font-semibold">Notes about these results</p>
          <ul className="mt-1 list-disc space-y-0.5 pl-5">
            {data.warnings.map((warning) => (
              <li key={warning}>{warning}</li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
