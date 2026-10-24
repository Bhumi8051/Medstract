import type { SearchResponse } from "@/lib/api/types";

interface EmptyStateProps {
  data: SearchResponse;
  hasFilters: boolean;
  onClearFilters: () => void;
}

/** Shown when a search succeeds but returns no papers. */
export function EmptyState({ data, hasFilters, onClearFilters }: EmptyStateProps) {
  return (
    <div className="rounded-2xl border border-dashed border-slate-300 bg-white p-8 text-center dark:border-slate-700 dark:bg-slate-900">
      <h2 id="results-heading" className="text-lg font-semibold text-slate-900 dark:text-slate-50">
        No papers found for “{data.query}”
      </h2>
      <ul className="mx-auto mt-3 max-w-md space-y-1 text-left text-sm text-slate-600 dark:text-slate-400">
        <li>• Try fewer or broader keywords, or check the spelling.</li>
        {data.period !== "all" && <li>• A longer publication period may help; recent papers can take days to appear.</li>}
        {(data.article_types.length > 0 || data.languages.length > 0) && (
          <li>• Remove some article type or language filters.</li>
        )}
        {data.excluded_by_date > 0 && (
          <li>• Some papers had no usable date; tick &ldquo;Keep papers whose date is missing&rdquo; in the filters.</li>
        )}
      </ul>
      {data.warnings.length > 0 && (
        <ul className="mx-auto mt-3 max-w-md text-left text-sm text-amber-800 dark:text-amber-300">
          {data.warnings.map((warning) => (
            <li key={warning}>{warning}</li>
          ))}
        </ul>
      )}
      {hasFilters && (
        <button
          type="button"
          onClick={onClearFilters}
          className="mt-5 rounded-lg bg-teal-700 px-4 py-2 text-sm font-semibold text-white hover:bg-teal-800 focus-visible:ring-2 focus-visible:ring-teal-600 focus-visible:ring-offset-2 focus-visible:outline-none"
        >
          Clear all filters
        </button>
      )}
    </div>
  );
}
