"use client";

import { useId } from "react";

import {
  ARTICLE_TYPE_OPTIONS,
  countActiveFilters,
  LANGUAGE_OPTIONS,
  RESULT_LIMIT_OPTIONS,
  toggleValue,
  type SearchFilters,
} from "@/lib/filters";

import { CheckboxGroup } from "./CheckboxGroup";
import { DateRangeFilter } from "./DateRangeFilter";

interface FilterSidebarProps {
  filters: SearchFilters;
  onChange: (patch: Partial<SearchFilters>) => void;
  onClearAll: () => void;
}

/** PubMed-style filters. Every control maps to a backend parameter; changes re-run the search. */
export function FilterSidebar({ filters, onChange, onClearAll }: FilterSidebarProps) {
  const limitId = useId();
  const activeCount = countActiveFilters(filters);

  return (
    <div className="space-y-6 rounded-2xl border border-slate-200 bg-white p-5 dark:border-slate-800 dark:bg-slate-900">
      <div className="flex items-center justify-between">
        <h2 className="text-base font-semibold text-slate-900 dark:text-slate-50">Filters</h2>
        <button
          type="button"
          onClick={onClearAll}
          disabled={activeCount === 0}
          className="text-sm font-medium text-teal-800 underline-offset-4 hover:underline focus-visible:ring-2 focus-visible:ring-teal-600 focus-visible:outline-none disabled:cursor-not-allowed disabled:text-slate-400 disabled:no-underline dark:text-teal-300 dark:disabled:text-slate-600"
        >
          Clear all{activeCount > 0 ? ` (${activeCount})` : ""}
        </button>
      </div>

      <DateRangeFilter
        // Remount when the applied range changes from outside (chips, "Clear all"), resetting the draft.
        key={`${filters.startDate}|${filters.endDate}`}
        startDate={filters.startDate}
        endDate={filters.endDate}
        includeUndated={filters.includeUndated}
        onApply={(range) => onChange(range)}
        onIncludeUndatedChange={(includeUndated) => onChange({ includeUndated })}
      />

      <CheckboxGroup
        legend="Article type"
        options={ARTICLE_TYPE_OPTIONS}
        selected={filters.articleTypes}
        onToggle={(value) => onChange({ articleTypes: toggleValue(filters.articleTypes, value, ARTICLE_TYPE_OPTIONS) })}
      />

      <CheckboxGroup
        legend="Language"
        options={LANGUAGE_OPTIONS}
        selected={filters.languages}
        onToggle={(value) => onChange({ languages: toggleValue(filters.languages, value, LANGUAGE_OPTIONS) })}
      />

      <div>
        <label htmlFor={limitId} className="text-sm font-semibold text-slate-900 dark:text-slate-100">
          Result limit
        </label>
        <select
          id={limitId}
          value={filters.maxResults}
          onChange={(e) => onChange({ maxResults: Number(e.target.value) })}
          className="mt-2 w-full rounded-md border border-slate-300 bg-white px-2 py-1.5 text-sm text-slate-900 focus:border-teal-600 focus:ring-2 focus:ring-teal-600/30 focus:outline-none dark:border-slate-700 dark:bg-slate-950 dark:text-slate-100"
        >
          {RESULT_LIMIT_OPTIONS.map((option) => (
            <option key={option.value} value={option.value}>
              {option.label}
            </option>
          ))}
        </select>
      </div>
    </div>
  );
}
