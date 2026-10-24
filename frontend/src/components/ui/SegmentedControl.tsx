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
      <legend className="mb-1.5 text-xs font-semibold tracking-wide text-slate-500 uppercase dark:text-slate-400">
        {legend}
      </legend>
      <div className="inline-flex flex-wrap rounded-lg border border-slate-200 bg-slate-100 p-1 dark:border-slate-700 dark:bg-slate-800">
        {options.map((option) => (
          <label
            key={option.value}
            className="relative cursor-pointer rounded-md px-3 py-1.5 text-sm font-medium text-slate-600 transition has-checked:bg-white has-checked:text-teal-800 has-checked:shadow-sm has-focus-visible:ring-2 has-focus-visible:ring-teal-600 hover:text-slate-900 dark:text-slate-300 dark:has-checked:bg-slate-950 dark:has-checked:text-teal-300 dark:hover:text-white"
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
        <p id={hintId} className="mt-1 text-xs text-slate-500 dark:text-slate-400">
          {hint}
        </p>
      )}
    </fieldset>
  );
}
