"use client";

import { useId, useState, type FormEvent } from "react";

import { validateDateRange, type DateRangeErrors } from "@/lib/validation";

interface DateRangeFilterProps {
  startDate: string;
  endDate: string;
  includeUndated: boolean;
  onApply: (range: { startDate: string; endDate: string }) => void;
  onIncludeUndatedChange: (value: boolean) => void;
}

/**
 * Custom publication-date range. Typing edits a local draft; the range is only
 * applied (and searched) on "Apply", so half-typed dates never hit the API.
 * The parent remounts this component (via `key`) when the applied range changes elsewhere.
 */
export function DateRangeFilter({
  startDate,
  endDate,
  includeUndated,
  onApply,
  onIncludeUndatedChange,
}: DateRangeFilterProps) {
  const [draftStart, setDraftStart] = useState(startDate);
  const [draftEnd, setDraftEnd] = useState(endDate);
  const [errors, setErrors] = useState<DateRangeErrors>({});
  const baseId = useId();
  const ids = { start: `${baseId}-start`, end: `${baseId}-end`, hint: `${baseId}-hint`, undated: `${baseId}-undated` };
  const hasRange = Boolean(startDate || endDate);
  const isDirty = draftStart.trim() !== startDate || draftEnd.trim() !== endDate;

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const nextErrors = validateDateRange(draftStart, draftEnd);
    setErrors(nextErrors);
    if (nextErrors.start || nextErrors.end) {
      document.getElementById(nextErrors.start ? ids.start : ids.end)?.focus();
      return;
    }
    onApply({ startDate: draftStart.trim(), endDate: draftEnd.trim() });
  }

  return (
    <form onSubmit={handleSubmit} noValidate aria-labelledby={`${baseId}-legend`}>
      <p id={`${baseId}-legend`} className="text-sm font-semibold text-navy-900 dark:text-navy-100">
        Publication date
      </p>
      <p id={ids.hint} className="mt-0.5 text-xs text-navy-500 dark:text-navy-400">
        A year (2020), month (2020-03) or day (2020-03-15).
      </p>
      <div className="mt-2 grid grid-cols-2 gap-2">
        {(
          [
            ["start", "From", draftStart, setDraftStart],
            ["end", "To", draftEnd, setDraftEnd],
          ] as const
        ).map(([key, label, value, setValue]) => (
          <div key={key}>
            <label htmlFor={ids[key]} className="block text-xs font-medium text-navy-700 dark:text-navy-300">
              {label}
            </label>
            <input
              id={ids[key]}
              type="text"
              autoComplete="off"
              placeholder={key === "start" ? "2020" : "2024-06"}
              value={value}
              onChange={(e) => {
                setValue(e.target.value);
                if (errors[key]) setErrors((current) => ({ ...current, [key]: undefined }));
              }}
              aria-invalid={Boolean(errors[key])}
              aria-describedby={errors[key] ? `${ids[key]}-error` : ids.hint}
              className="mt-1 w-full rounded-md border border-navy-300 bg-white px-2 py-1.5 text-sm text-navy-900 focus:border-brand-600 focus:ring-2 focus:ring-brand-600/30 focus:outline-none aria-invalid:border-red-500 dark:border-navy-700 dark:bg-navy-950 dark:text-navy-100"
            />
            {errors[key] && (
              <p id={`${ids[key]}-error`} className="mt-1 text-xs text-red-700 dark:text-red-400">
                {errors[key]}
              </p>
            )}
          </div>
        ))}
      </div>
      <button
        type="submit"
        disabled={!isDirty}
        className="mt-2 w-full rounded-md bg-navy-900 px-3 py-1.5 text-sm font-medium text-white transition hover:bg-navy-700 focus-visible:ring-2 focus-visible:ring-brand-600 focus-visible:ring-offset-2 focus-visible:outline-none disabled:cursor-not-allowed disabled:opacity-40 dark:bg-navy-100 dark:text-navy-900 dark:hover:bg-white"
      >
        Apply date range
      </button>

      <div className="mt-3 flex items-start gap-2">
        <input
          id={ids.undated}
          type="checkbox"
          checked={includeUndated}
          disabled={!hasRange}
          onChange={(e) => onIncludeUndatedChange(e.target.checked)}
          className="mt-0.5 size-4 rounded border-navy-300 accent-brand-700 disabled:opacity-50"
        />
        <label
          htmlFor={ids.undated}
          className={`text-xs ${hasRange ? "text-navy-700 dark:text-navy-300" : "text-navy-400 dark:text-navy-500"}`}
        >
          Keep papers whose date is missing or incomplete in PubMed (only with a custom range)
        </label>
      </div>
    </form>
  );
}
