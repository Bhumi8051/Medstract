import type { EvidenceBasis, PaperAnalysis, ReportPoint } from "@/lib/api/types";
import { labelFor, SUMMARY_LEVEL_OPTIONS } from "@/lib/filters";

const BASIS_STYLES: Record<EvidenceBasis, { label: string; title: string; className: string }> = {
  reported: {
    label: "Reported",
    title: "Stated in the PubMed record (title, metadata or abstract)",
    className: "bg-teal-50 text-teal-900 ring-teal-200 dark:bg-teal-950 dark:text-teal-200 dark:ring-teal-900",
  },
  interpretation: {
    label: "AI interpretation",
    title: "The AI's explanation or inference; not stated by the authors",
    className: "bg-violet-50 text-violet-900 ring-violet-200 dark:bg-violet-950 dark:text-violet-200 dark:ring-violet-900",
  },
  not_reported: {
    label: "Not reported",
    title: "This information is not in the PubMed record",
    className: "bg-slate-100 text-slate-700 ring-slate-200 dark:bg-slate-800 dark:text-slate-300 dark:ring-slate-700",
  },
};

const SECTIONS: { key: keyof Omit<PaperAnalysis["report"], "plain_language_overview" | "further_questions">; title: string }[] = [
  { key: "research_question", title: "Research question or objective" },
  { key: "background", title: "Background and motivation" },
  { key: "methods", title: "Methods and study design" },
  { key: "key_findings", title: "Key findings" },
  { key: "interpretation", title: "Interpretation and significance" },
  { key: "limitations", title: "Limitations and caveats" },
  { key: "not_established", title: "What the paper does not establish" },
];

function BasisBadge({ basis }: { basis: EvidenceBasis }) {
  const style = BASIS_STYLES[basis] ?? BASIS_STYLES.interpretation;
  return (
    <span
      title={style.title}
      className={`inline-block shrink-0 rounded-full px-2 py-0.5 text-[11px] font-semibold whitespace-nowrap ring-1 ring-inset ${style.className}`}
    >
      {style.label}
    </span>
  );
}

function PointList({ points }: { points: ReportPoint[] }) {
  return (
    <ul className="mt-2 space-y-2">
      {points.map((point, index) => (
        <li key={index} className="flex flex-col gap-1 sm:flex-row sm:items-start sm:gap-3">
          <BasisBadge basis={point.basis} />
          <span
            className={`text-sm leading-relaxed ${
              point.basis === "not_reported" ? "text-slate-500 italic dark:text-slate-400" : "text-slate-700 dark:text-slate-300"
            }`}
          >
            {point.text}
          </span>
        </li>
      ))}
    </ul>
  );
}

interface AnalysisReportProps {
  analysis: PaperAnalysis;
  headingId: string;
}

/** Renders a validated PaperAnalysis. Server-written notes are shown separately from AI-generated content. */
export function AnalysisReport({ analysis, headingId }: AnalysisReportProps) {
  const { report } = analysis;
  const generated = new Date(analysis.generated_at);

  return (
    <section aria-labelledby={headingId} className="space-y-5">
      <header>
        <h4 id={headingId} className="text-base font-semibold text-slate-900 dark:text-slate-50">
          AI research report
        </h4>
        <p className="mt-0.5 text-xs text-slate-500 dark:text-slate-400">
          {labelFor(SUMMARY_LEVEL_OPTIONS, analysis.summary_level)} level · {analysis.model}
          {!Number.isNaN(generated.getTime()) && <> · generated {generated.toLocaleString()}</>}
        </p>
      </header>

      <div className="rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-950 dark:border-amber-900 dark:bg-amber-950/40 dark:text-amber-100">
        <p className="font-medium">{analysis.source_note}</p>
        <p className="mt-1">{analysis.disclaimer}</p>
      </div>

      {analysis.grounding_warnings.length > 0 && (
        <div
          role="note"
          className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-900 dark:border-red-900 dark:bg-red-950/40 dark:text-red-200"
        >
          <p className="font-semibold">Automatic check: verify these against the paper</p>
          <ul className="mt-1 list-disc space-y-0.5 pl-5">
            {analysis.grounding_warnings.map((warning) => (
              <li key={warning}>{warning}</li>
            ))}
          </ul>
        </div>
      )}

      <div className="flex flex-wrap items-center gap-2 text-xs text-slate-500 dark:text-slate-400">
        <span>Labels:</span>
        <BasisBadge basis="reported" />
        <BasisBadge basis="interpretation" />
        <BasisBadge basis="not_reported" />
      </div>

      <div>
        <h5 className="text-sm font-semibold text-slate-900 dark:text-slate-100">Plain-language overview</h5>
        <p className="mt-1 text-sm leading-relaxed text-slate-700 dark:text-slate-300">{report.plain_language_overview}</p>
      </div>

      {SECTIONS.map((section) => (
        <div key={section.key}>
          <h5 className="text-sm font-semibold text-slate-900 dark:text-slate-100">{section.title}</h5>
          <PointList points={report[section.key]} />
        </div>
      ))}

      <div>
        <h5 className="text-sm font-semibold text-slate-900 dark:text-slate-100">Questions for further investigation</h5>
        <ul className="mt-2 list-disc space-y-1 pl-5 text-sm text-slate-700 dark:text-slate-300">
          {report.further_questions.map((question, index) => (
            <li key={index}>{question}</li>
          ))}
        </ul>
      </div>

      <p className="border-t border-slate-200 pt-3 text-xs text-slate-500 dark:border-slate-700 dark:text-slate-400">
        Source: PMID {analysis.pmid} ·{" "}
        <a
          href={analysis.pubmed_url}
          target="_blank"
          rel="noopener noreferrer"
          className="font-medium text-teal-800 underline-offset-4 hover:underline dark:text-teal-300"
        >
          {analysis.pubmed_url}
          <span className="sr-only"> (opens in a new tab)</span>
        </a>
      </p>
    </section>
  );
}
