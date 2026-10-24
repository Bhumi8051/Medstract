interface RelevanceBadgeProps {
  score: number;
}

/** Shows the backend's 0-1 keyword-overlap score as a percentage with a small meter. */
export function RelevanceBadge({ score }: RelevanceBadgeProps) {
  const percent = Math.round(Math.min(Math.max(score, 0), 1) * 100);
  return (
    <div
      className="flex shrink-0 items-center gap-2"
      title="Share of your search terms found in this paper; title matches count 3× more than abstract matches."
    >
      <span className="text-xs font-medium text-slate-500 dark:text-slate-400">Keyword match</span>
      <span
        aria-hidden="true"
        className="relative h-1.5 w-14 overflow-hidden rounded-full bg-slate-200 dark:bg-slate-700"
      >
        <span className="absolute inset-y-0 left-0 rounded-full bg-teal-600" style={{ width: `${percent}%` }} />
      </span>
      <span className="text-sm font-semibold tabular-nums text-slate-900 dark:text-slate-100">
        {percent}%<span className="sr-only"> keyword match</span>
      </span>
    </div>
  );
}
