import type { Paper } from "@/lib/api/types";

import { PaperCard } from "./PaperCard";

interface PaperListProps {
  papers: Paper[];
}

export function PaperList({ papers }: PaperListProps) {
  return (
    <ol className="space-y-4" aria-labelledby="results-heading">
      {papers.map((paper, index) => (
        <li key={paper.pmid}>
          <PaperCard paper={paper} rank={index + 1} />
        </li>
      ))}
    </ol>
  );
}
