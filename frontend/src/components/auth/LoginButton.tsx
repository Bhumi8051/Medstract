/**
 * Placeholder only: there is no authentication yet. Uses the native HTML
 * popover, which handles Escape, outside clicks and focus without extra code.
 */
export function LoginButton() {
  return (
    <>
      <button
        type="button"
        popoverTarget="login-coming-soon"
        className="shrink-0 rounded-lg border border-slate-300 bg-white px-4 py-2 text-sm whitespace-nowrap font-semibold text-slate-800 shadow-sm transition hover:border-teal-600 hover:text-teal-800 focus-visible:ring-2 focus-visible:ring-teal-600 focus-visible:outline-none dark:border-slate-700 dark:bg-slate-900 dark:text-slate-100 dark:hover:text-teal-300"
      >
        Log in
      </button>
      <div
        id="login-coming-soon"
        popover="auto"
        role="dialog"
        aria-label="Accounts coming soon"
        className="fixed inset-auto top-16 right-4 m-0 w-72 rounded-xl border border-slate-200 bg-white p-4 text-sm text-slate-700 shadow-lg dark:border-slate-700 dark:bg-slate-900 dark:text-slate-300"
      >
        <p className="flex items-center gap-2 font-semibold text-slate-900 dark:text-slate-50">
          Accounts are coming soon
          <span className="rounded-full bg-amber-100 px-2 py-0.5 text-xs font-medium text-amber-900 dark:bg-amber-950 dark:text-amber-200">
            Not available yet
          </span>
        </p>
        <p className="mt-2">
          Signing in isn&rsquo;t available yet. Accounts will later let you save searches and get weekly research
          summaries. Searching works without an account.
        </p>
        <button
          type="button"
          popoverTarget="login-coming-soon"
          popoverTargetAction="hide"
          className="mt-3 text-sm font-medium text-teal-800 underline-offset-4 hover:underline focus-visible:ring-2 focus-visible:ring-teal-600 focus-visible:outline-none dark:text-teal-300"
        >
          Close
        </button>
      </div>
    </>
  );
}
