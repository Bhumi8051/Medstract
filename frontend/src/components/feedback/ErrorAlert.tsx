interface ErrorAlertProps {
  message: string;
  /** Possible causes to list under the message. */
  hints?: string[];
  onRetry?: () => void;
}

export function ErrorAlert({ message, hints = [], onRetry }: ErrorAlertProps) {
  return (
    <div
      role="alert"
      className="rounded-2xl border border-red-200 bg-red-50 p-5 text-red-900 dark:border-red-900 dark:bg-red-950/50 dark:text-red-200"
    >
      <h2 className="font-semibold">The search could not be completed</h2>
      <p className="mt-1 text-sm">{message}</p>
      {hints.length > 0 && (
        <>
          <p className="mt-3 text-sm font-medium">Likely causes:</p>
          <ol className="mt-1 list-decimal space-y-1 pl-5 text-sm">
            {hints.map((hint) => (
              <li key={hint}>{hint}</li>
            ))}
          </ol>
        </>
      )}
      {onRetry && (
        <button
          type="button"
          onClick={onRetry}
          className="mt-3 rounded-lg border border-red-300 bg-white px-4 py-2 text-sm font-medium text-red-900 hover:bg-red-100 focus-visible:ring-2 focus-visible:ring-red-600 focus-visible:outline-none dark:border-red-800 dark:bg-transparent dark:text-red-200 dark:hover:bg-red-900/40"
        >
          Try again
        </button>
      )}
    </div>
  );
}
