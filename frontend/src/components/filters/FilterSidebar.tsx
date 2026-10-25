"use client";

import { useId } from "react";

import {
  ARTICLE_TYPE_OPTIONS,
  countActiveFilters,
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
    <div className="space-y-6 rounded-2xl border border-navy-200 bg-white p-6 shadow-sm dark:border-navy-800 dark:bg-navy-900">
      <div className="flex items-center justify-between border-b border-navy-100 pb-4 dark:border-navy-800">
        <h2 className="text-base font-semibold text-navy-900 dark:text-navy-50">Filters</h2>
        <button
          type="button"
          onClick={onClearAll}
          disabled={activeCount === 0}
          className="text-sm font-medium text-brand-800 underline-offset-4 hover:underline focus-visible:ring-2 focus-visible:ring-brand-600 focus-visible:outline-none disabled:cursor-not-allowed disabled:text-navy-400 disabled:no-underline dark:text-brand-300 dark:disabled:text-navy-600"
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

      <div>
        <label htmlFor={limitId} className="text-sm font-semibold text-navy-900 dark:text-navy-100">
          Result limit
        </label>
        <select
          id={limitId}
          value={filters.maxResults}
          onChange={(e) => onChange({ maxResults: Number(e.target.value) })}
          className="mt-2 w-full rounded-md border border-navy-300 bg-white px-2 py-1.5 text-sm text-navy-900 focus:border-brand-600 focus:ring-2 focus:ring-brand-600/30 focus:outline-none dark:border-navy-700 dark:bg-navy-950 dark:text-navy-100"
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
