import {
  ARTICLE_TYPE_OPTIONS,
  DEFAULT_FILTERS,
  LANGUAGE_OPTIONS,
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
  for (const language of filters.languages) {
    chips.push({
      key: `lang-${language}`,
      label: labelFor(LANGUAGE_OPTIONS, language),
      remove: { languages: filters.languages.filter((l) => l !== language) },
    });
  }
  if (filters.maxResults !== DEFAULT_FILTERS.maxResults) {
    chips.push({ key: "limit", label: `${filters.maxResults} results`, remove: { maxResults: DEFAULT_FILTERS.maxResults } });
  }

  if (chips.length === 0) return null;

  return (
    <div className="flex flex-wrap items-center gap-2">
      <span className="text-xs font-semibold tracking-wide text-slate-500 uppercase dark:text-slate-400">
        Active filters
      </span>
      <ul className="flex flex-wrap gap-2">
        {chips.map((chip) => (
          <li key={chip.key}>
            <button
              type="button"
              onClick={() => onChange(chip.remove)}
              className="inline-flex items-center gap-1.5 rounded-full border border-teal-200 bg-teal-50 py-1 pr-2 pl-3 text-xs font-medium text-teal-900 transition hover:border-teal-400 focus-visible:ring-2 focus-visible:ring-teal-600 focus-visible:outline-none dark:border-teal-900 dark:bg-teal-950 dark:text-teal-200"
            >
              {chip.label}
              <span aria-hidden="true" className="text-teal-700 dark:text-teal-400">
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
        className="text-xs font-medium text-slate-600 underline-offset-4 hover:underline focus-visible:ring-2 focus-visible:ring-teal-600 focus-visible:outline-none dark:text-slate-400"
      >
        Clear all
      </button>
    </div>
  );
}
