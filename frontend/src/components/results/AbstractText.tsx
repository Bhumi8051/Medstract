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
      <p className="rounded-lg bg-navy-50 px-3 py-2 text-sm italic text-navy-500 dark:bg-navy-800/50 dark:text-navy-400">
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
        className={`space-y-2 text-[0.9375rem] leading-7 text-navy-700 dark:text-navy-300 ${
          collapsible && !expanded ? "line-clamp-4" : ""
        }`}
      >
        {sections.map((section, index) => (
          <p key={index}>
            {section.label && (
              <span className="font-semibold text-navy-900 dark:text-navy-100">{section.label}: </span>
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
          className="mt-2 text-sm font-medium text-brand-800 underline-offset-4 hover:underline focus-visible:ring-2 focus-visible:ring-brand-600 focus-visible:outline-none dark:text-brand-300"
        >
          {expanded ? "Show less" : "Show full abstract"}
        </button>
      )}
    </div>
  );
}
