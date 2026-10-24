/**
 * Client-side checks that mirror the backend's rules (backend/app/routers/search.py)
 * so users get instant feedback. The backend still validates everything.
 */

export const QUERY_MIN_LENGTH = 2;
export const QUERY_MAX_LENGTH = 500;

export function validateQuery(raw: string): { query: string; error: string | null } {
  const query = raw.trim();
  if (query.length < QUERY_MIN_LENGTH) {
    return { query, error: `Enter at least ${QUERY_MIN_LENGTH} characters.` };
  }
  if (query.length > QUERY_MAX_LENGTH) {
    return { query, error: `Keep the search under ${QUERY_MAX_LENGTH} characters.` };
  }
  return { query, error: null };
}

const PARTIAL_DATE = /^(\d{4})(?:-(\d{1,2})(?:-(\d{1,2}))?)?$/;

/**
 * Period covered by a partial date: "2020" -> Jan 1 to Dec 31, 2020.
 * Returns null if the value is not a real YYYY, YYYY-MM or YYYY-MM-DD date.
 */
export function partialDateBounds(value: string): { first: Date; last: Date } | null {
  const match = PARTIAL_DATE.exec(value.trim());
  if (!match) return null;
  const year = Number(match[1]);
  const month = match[2] ? Number(match[2]) : null;
  const day = match[3] ? Number(match[3]) : null;
  if (year < 1000) return null;
  if (month === null) {
    return { first: new Date(Date.UTC(year, 0, 1)), last: new Date(Date.UTC(year, 11, 31)) };
  }
  if (month < 1 || month > 12) return null;
  if (day === null) {
    return { first: new Date(Date.UTC(year, month - 1, 1)), last: new Date(Date.UTC(year, month, 0)) };
  }
  const exact = new Date(Date.UTC(year, month - 1, day));
  if (exact.getUTCMonth() !== month - 1 || exact.getUTCDate() !== day) return null;
  return { first: exact, last: exact };
}

export interface DateRangeErrors {
  start?: string;
  end?: string;
}

export function validateDateRange(start: string, end: string): DateRangeErrors {
  const errors: DateRangeErrors = {};
  const startBounds = start.trim() ? partialDateBounds(start) : null;
  const endBounds = end.trim() ? partialDateBounds(end) : null;
  const hint = "Use YYYY, YYYY-MM or YYYY-MM-DD.";

  if (start.trim() && !startBounds) errors.start = `Not a valid date. ${hint}`;
  if (end.trim() && !endBounds) errors.end = `Not a valid date. ${hint}`;
  if (startBounds && endBounds && startBounds.first > endBounds.last) {
    errors.end = "End must be on or after the start.";
  }
  return errors;
}
