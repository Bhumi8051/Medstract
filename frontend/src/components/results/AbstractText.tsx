"use client";

import { useId, useState } from "react";

import { splitAbstract } from "@/lib/format";

// Abstracts shorter than this are shown in full without a toggle.
const COLLAPSE_THRESHOLD = 450;

interface AbstractTextProps {
  abstract: string | null;
}

export function AbstractText({ abstract }: AbstractTextProps) {
  const [expanded, setExpanded] = useState(false);
  const contentId = useId();

  if (!abstract) {
    return (
      <p className="rounded-lg bg-slate-50 px-3 py-2 text-sm italic text-slate-500 dark:bg-slate-800/50 dark:text-slate-400">
        No abstract available in PubMed for this paper.
      </p>
    );
  }

  const collapsible = abstract.length > COLLAPSE_THRESHOLD;
  const sections = splitAbstract(abstract);

  return (
    <div>
      <div
        id={contentId}
        className={`space-y-2 text-sm leading-relaxed text-slate-700 dark:text-slate-300 ${
          collapsible && !expanded ? "line-clamp-4" : ""
        }`}
      >
        {sections.map((section, index) => (
          <p key={index}>
            {section.label && (
              <span className="font-semibold text-slate-900 dark:text-slate-100">{section.label}: </span>
            )}
            {section.text}
          </p>
        ))}
      </div>
      {collapsible && (
        <button
          type="button"
          onClick={() => setExpanded((value) => !value)}
          aria-expanded={expanded}
          aria-controls={contentId}
          className="mt-2 text-sm font-medium text-teal-800 underline-offset-4 hover:underline focus-visible:ring-2 focus-visible:ring-teal-600 focus-visible:outline-none dark:text-teal-300"
        >
          {expanded ? "Show less" : "Show full abstract"}
        </button>
      )}
    </div>
  );
}
