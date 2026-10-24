"use client";

import { useId } from "react";

import type { Option } from "@/lib/filters";

interface CheckboxGroupProps<T extends string> {
  legend: string;
  options: Option<T>[];
  selected: T[];
  onToggle: (value: T) => void;
}

export function CheckboxGroup<T extends string>({ legend, options, selected, onToggle }: CheckboxGroupProps<T>) {
  const baseId = useId();
  return (
    <fieldset>
      <legend className="text-sm font-semibold text-slate-900 dark:text-slate-100">{legend}</legend>
      <ul className="mt-2 space-y-1.5">
        {options.map((option) => {
          const id = `${baseId}-${option.value}`;
          return (
            <li key={option.value} className="flex items-center gap-2">
              <input
                id={id}
                type="checkbox"
                checked={selected.includes(option.value)}
                onChange={() => onToggle(option.value)}
                className="size-4 rounded border-slate-300 accent-teal-700"
              />
              <label htmlFor={id} className="text-sm text-slate-700 dark:text-slate-300">
                {option.label}
              </label>
            </li>
          );
        })}
      </ul>
    </fieldset>
  );
}
