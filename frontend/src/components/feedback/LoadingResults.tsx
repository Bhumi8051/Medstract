const PLACEHOLDER_CARDS = 3;

/** Skeleton cards shown while a search is running. Hidden from screen readers; the live region announces progress. */
export function LoadingResults() {
  return (
    <div aria-hidden="true" className="space-y-4">
      <div className="h-6 w-64 animate-pulse rounded bg-navy-200 dark:bg-navy-800" />
      {Array.from({ length: PLACEHOLDER_CARDS }, (_, index) => (
        <div
          key={index}
          className="rounded-2xl border border-navy-200 bg-white p-6 dark:border-navy-800 dark:bg-navy-900"
        >
          <div className="animate-pulse space-y-3">
            <div className="h-4 w-24 rounded bg-navy-200 dark:bg-navy-800" />
            <div className="h-5 w-4/5 rounded bg-navy-200 dark:bg-navy-800" />
            <div className="h-4 w-3/5 rounded bg-navy-100 dark:bg-navy-800/70" />
            <div className="space-y-2 pt-2">
              <div className="h-3 rounded bg-navy-100 dark:bg-navy-800/70" />
              <div className="h-3 rounded bg-navy-100 dark:bg-navy-800/70" />
              <div className="h-3 w-2/3 rounded bg-navy-100 dark:bg-navy-800/70" />
            </div>
          </div>
        </div>
      ))}
    </div>
  );
}
