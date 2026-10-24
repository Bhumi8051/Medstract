"use client";

import { useState } from "react";

import type { Author } from "@/lib/api/types";

const VISIBLE_AUTHORS = 6;

interface AuthorListProps {
  authors: Author[];
}

export function AuthorList({ authors }: AuthorListProps) {
  const [expanded, setExpanded] = useState(false);

  if (authors.length === 0) {
    return <p className="text-sm italic text-slate-500 dark:text-slate-400">Authors not listed in PubMed</p>;
  }

  const hidden = authors.length - VISIBLE_AUTHORS;
  const shown = expanded || hidden <= 0 ? authors : authors.slice(0, VISIBLE_AUTHORS);

  return (
    <p className="text-sm text-slate-700 dark:text-slate-300">
      <span className="sr-only">Authors: </span>
      {shown.map((author) => author.name).join(", ")}
      {hidden > 0 && (
        <>
          {!expanded && ", "}
          <button
            type="button"
            onClick={() => setExpanded((value) => !value)}
            aria-expanded={expanded}
            className="ml-1 font-medium text-teal-800 underline-offset-4 hover:underline focus-visible:ring-2 focus-visible:ring-teal-600 focus-visible:outline-none dark:text-teal-300"
          >
            {expanded ? "show fewer" : `+${hidden} more`}
          </button>
        </>
      )}
    </p>
  );
}
