"use client";

import { useId } from "react";

import type { Option } from "@/lib/filters";

interface SegmentedControlProps<T extends string> {
  legend: string;
  options: Option<T>[];
  value: T;
  onChange: (value: T) => void;
  hint?: string;
  disabled?: boolean;
}

/** A row of mutually exclusive choices, built on native radio buttons for keyboard and screen-reader support. */
export function SegmentedControl<T extends string>({
  legend,
  options,
  value,
  onChange,
  hint,
  disabled,
}: SegmentedControlProps<T>) {
  const name = useId();
  const hintId = `${name}-hint`;

  return (
    <fieldset aria-describedby={hint ? hintId : undefined} disabled={disabled} className="min-w-0">
      <legend className="mb-2 text-xs font-semibold tracking-wide text-navy-500 uppercase dark:text-navy-400">
        {legend}
      </legend>
      <div className="inline-flex flex-wrap rounded-lg border border-navy-200 bg-navy-50 p-1 dark:border-navy-700 dark:bg-navy-950">
        {options.map((option) => (
          <label
            key={option.value}
            className="relative cursor-pointer rounded-md px-3 py-1.5 text-sm font-medium text-navy-600 transition hover:text-navy-900 has-checked:bg-brand-600 has-checked:text-white has-checked:shadow-sm has-focus-visible:ring-2 has-focus-visible:ring-brand-600 has-focus-visible:ring-offset-1 dark:text-navy-300 dark:hover:text-white dark:has-checked:bg-brand-100 dark:has-checked:text-navy-950"
          >
            <input
              type="radio"
              name={name}
              value={option.value}
              checked={value === option.value}
              onChange={() => onChange(option.value)}
              className="sr-only"
            />
            {option.label}
          </label>
        ))}
      </div>
      {hint && (
        <p id={hintId} className="mt-1 text-xs text-navy-500 dark:text-navy-400">
          {hint}
        </p>
      )}
    </fieldset>
  );
}
