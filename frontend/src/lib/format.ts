import type { Paper } from "./api/types";

const numberFormat = new Intl.NumberFormat("en-US");

export function formatCount(value: number): string {
  return numberFormat.format(value);
}

/** PubMed's own date text when present, else the normalized ISO date. */
export function formatPublicationDate(paper: Paper): string | null {
  return paper.publication_date ?? paper.publication_date_iso;
}

/** "2023-01-01" -> "Jan 1, 2023" (UTC, so the day never shifts by time zone). */
export function formatIsoDay(iso: string): string {
  const [year, month, day] = iso.split("-").map(Number);
  return new Date(Date.UTC(year, month - 1, day)).toLocaleDateString("en-US", {
    year: "numeric",
    month: "short",
    day: "numeric",
    timeZone: "UTC",
  });
}

const LANGUAGE_CODES: Record<string, string> = {
  eng: "English",
  spa: "Spanish",
  fre: "French",
  ger: "German",
  chi: "Chinese",
  jpn: "Japanese",
  ita: "Italian",
  por: "Portuguese",
  rus: "Russian",
};

/** PubMed language code -> display name, e.g. "spa" -> "Spanish". Unknown codes are shown uppercase. */
export function languageName(code: string): string {
  return LANGUAGE_CODES[code.toLowerCase()] ?? code.toUpperCase();
}

export function isRetracted(paper: Paper): boolean {
  return paper.publication_types.some((type) => type.toLowerCase() === "retracted publication");
}

/**
 * The backend joins structured-abstract sections with blank lines and prefixes
 * each with its label ("BACKGROUND: ..."). Split them back out for display.
 */
export function splitAbstract(abstract: string): { label: string | null; text: string }[] {
  return abstract
    .split(/\n{2,}/)
    .map((section) => section.trim())
    .filter(Boolean)
    .map((section) => {
      const match = /^([A-Z][A-Z0-9 ,&/()-]{1,60}):\s+([\s\S]+)$/.exec(section);
      return match ? { label: match[1], text: match[2] } : { label: null, text: section };
    });
}
