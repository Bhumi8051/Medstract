import type { Paper, SummaryLevel } from "@/lib/api/types";

import { PaperCard } from "./PaperCard";

interface PaperListProps {
  papers: Paper[];
  summaryLevel: SummaryLevel;
}

export function PaperList({ papers, summaryLevel }: PaperListProps) {
  return (
    <ol className="space-y-4" aria-labelledby="results-heading">
      {papers.map((paper, index) => (
        <li key={paper.pmid}>
          <PaperCard paper={paper} rank={index + 1} summaryLevel={summaryLevel} />
        </li>
      ))}
    </ol>
  );
}
