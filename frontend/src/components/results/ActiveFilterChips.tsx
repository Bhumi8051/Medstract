import {
  ARTICLE_TYPE_OPTIONS,
  DEFAULT_FILTERS,
  labelFor,
  PERIOD_OPTIONS,
  type SearchFilters,
} from "@/lib/filters";

interface ActiveFilterChipsProps {
  filters: SearchFilters;
  onChange: (patch: Partial<SearchFilters>) => void;
  onClearAll: () => void;
}

interface Chip {
  key: string;
  label: string;
  remove: Partial<SearchFilters>;
}

/** One removable chip per active filter, so clearing a single filter is one click. */
export function ActiveFilterChips({ filters, onChange, onClearAll }: ActiveFilterChipsProps) {
  const chips: Chip[] = [];
  if (filters.period !== "all") {
    chips.push({ key: "period", label: labelFor(PERIOD_OPTIONS, filters.period), remove: { period: "all" } });
  }
  if (filters.startDate || filters.endDate) {
    chips.push({
      key: "dates",
      label: `${filters.startDate || "Any"} – ${filters.endDate || "Today"}`,
      remove: { startDate: "", endDate: "", includeUndated: false },
    });
  }
  for (const type of filters.articleTypes) {
    chips.push({
      key: `type-${type}`,
      label: labelFor(ARTICLE_TYPE_OPTIONS, type),
      remove: { articleTypes: filters.articleTypes.filter((t) => t !== type) },
    });
  }
  if (filters.maxResults !== DEFAULT_FILTERS.maxResults) {
    chips.push({ key: "limit", label: `${filters.maxResults} results`, remove: { maxResults: DEFAULT_FILTERS.maxResults } });
  }

  if (chips.length === 0) return null;

  return (
    <div className="flex flex-wrap items-center gap-2">
      <span className="text-xs font-semibold tracking-wide text-navy-500 uppercase dark:text-navy-400">
        Active filters
      </span>
      <ul className="flex flex-wrap gap-2">
        {chips.map((chip) => (
          <li key={chip.key}>
            <button
              type="button"
              onClick={() => onChange(chip.remove)}
              className="inline-flex items-center gap-1.5 rounded-full border border-brand-200 bg-brand-50 py-1 pr-2 pl-3 text-xs font-medium text-brand-900 transition hover:border-brand-400 focus-visible:ring-2 focus-visible:ring-brand-600 focus-visible:outline-none dark:border-brand-900 dark:bg-brand-950 dark:text-brand-200"
            >
              {chip.label}
              <span aria-hidden="true" className="text-brand-700 dark:text-brand-400">
                ×
              </span>
              <span className="sr-only">(remove filter)</span>
            </button>
          </li>
        ))}
      </ul>
      <button
        type="button"
        onClick={onClearAll}
        className="text-xs font-medium text-navy-600 underline-offset-4 hover:underline focus-visible:ring-2 focus-visible:ring-brand-600 focus-visible:outline-none dark:text-navy-400"
      >
        Clear all
      </button>
    </div>
  );
}
