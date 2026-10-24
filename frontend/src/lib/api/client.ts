/**
 * The one place the frontend talks to the FastAPI backend.
 *
 * NEXT_PUBLIC_API_URL is inlined into browser code at build time, so it must
 * only ever hold a public URL. API keys stay in backend/.env.
 */

import type { SearchParams, SearchResponse } from "./types";

// This project's backend runs on port 8010 (see README.md); NEXT_PUBLIC_API_URL overrides it.
const DEFAULT_API_URL = "http://localhost:8010";

export const API_BASE_URL = (process.env.NEXT_PUBLIC_API_URL || DEFAULT_API_URL).replace(/\/+$/, "");

// The backend may retry PubMed a few times before giving up, so allow some slack.
const REQUEST_TIMEOUT_MS = 45_000;

export type ApiErrorKind = "network" | "timeout" | "http" | "invalid_response";

export class ApiError extends Error {
  constructor(
    message: string,
    readonly kind: ApiErrorKind,
    readonly status: number | null = null,
    /** Possible causes / next steps to show under the message. */
    readonly hints: string[] = [],
  ) {
    super(message);
    this.name = "ApiError";
  }
}

const STATUS_MESSAGES: Record<number, string> = {
  422: "Some search inputs are invalid. Please check them and try again.",
  429: "PubMed is receiving too many requests right now. Wait a moment and try again.",
  502: "PubMed returned an unexpected response. Please try again.",
  504: "PubMed took too long to respond. Please try again.",
};

/** Turn FastAPI's `detail` (a string, or a list of validation errors) into readable text. */
function detailToMessage(detail: unknown): string | null {
  if (typeof detail === "string" && detail.trim()) {
    return detail;
  }
  if (Array.isArray(detail)) {
    const messages = detail
      .map((item) => {
        if (!item || typeof item !== "object" || !("msg" in item)) return null;
        const loc = "loc" in item && Array.isArray(item.loc) ? item.loc.filter((p: unknown) => p !== "query") : [];
        return loc.length ? `${loc.join(".")}: ${String(item.msg)}` : String(item.msg);
      })
      .filter((m): m is string => Boolean(m));
    return messages.length ? messages.join("; ") : null;
  }
  return null;
}

async function getJson(path: string, query: URLSearchParams, signal?: AbortSignal): Promise<unknown> {
  const url = `${API_BASE_URL}${path}?${query.toString()}`;
  const timeout = AbortSignal.timeout(REQUEST_TIMEOUT_MS);
  const combined = signal ? AbortSignal.any([signal, timeout]) : timeout;

  let response: Response;
  try {
    response = await fetch(url, { signal: combined, headers: { Accept: "application/json" } });
  } catch (error) {
    if (signal?.aborted) throw error; // cancelled by the caller; not a real failure
    if (timeout.aborted) {
      throw new ApiError("The search took too long to complete. Please try again.", "timeout");
    }
    // Browsers deliberately hide why a request failed, so list the usual causes.
    const origin = typeof window === "undefined" ? "this page's origin" : window.location.origin;
    throw new ApiError(`Could not reach the research API at ${API_BASE_URL}.`, "network", null, [
      "The backend is not running. Start it with ./dev.sh, or uvicorn in the backend folder.",
      `NEXT_PUBLIC_API_URL is incorrect. It is currently ${API_BASE_URL}; check frontend/.env.local and restart the frontend after changing it.`,
      `The backend's CORS settings do not allow ${origin}. Check CORS_ORIGINS and CORS_ALLOW_LOCAL_ORIGINS in backend/.env.`,
    ]);
  }

  let body: unknown = null;
  try {
    body = await response.json();
  } catch {
    body = null;
  }

  if (!response.ok) {
    const detail =
      body && typeof body === "object" && "detail" in body ? detailToMessage(body.detail) : null;
    throw new ApiError(
      detail ?? STATUS_MESSAGES[response.status] ?? `The research API returned an error (HTTP ${response.status}).`,
      "http",
      response.status,
    );
  }
  if (body === null) {
    throw new ApiError("The research API returned a response that could not be read.", "invalid_response", response.status);
  }
  return body;
}

function isSearchResponse(value: unknown): value is SearchResponse {
  if (!value || typeof value !== "object") return false;
  const v = value as Record<string, unknown>;
  return (
    typeof v.query === "string" &&
    typeof v.total_results === "number" &&
    Array.isArray(v.papers) &&
    Array.isArray(v.warnings) &&
    v.papers.every(
      (p) =>
        p !== null &&
        typeof p === "object" &&
        typeof (p as Record<string, unknown>).pmid === "string" &&
        typeof (p as Record<string, unknown>).title === "string" &&
        Array.isArray((p as Record<string, unknown>).authors),
    )
  );
}

/** Search PubMed through the backend. Throws ApiError with a user-readable message on failure. */
export async function searchPapers(params: SearchParams, signal?: AbortSignal): Promise<SearchResponse> {
  const query = new URLSearchParams({ q: params.query });
  if (params.maxResults !== undefined) query.set("max_results", String(params.maxResults));
  if (params.startDate) query.set("start_date", params.startDate);
  if (params.endDate) query.set("end_date", params.endDate);
  if (params.includeUndated) query.set("include_undated", "true");
  if (params.period && params.period !== "all") query.set("period", params.period);
  // Repeated keys (?article_type=a&article_type=b) are how FastAPI reads lists.
  for (const type of params.articleTypes ?? []) query.append("article_type", type);
  for (const language of params.languages ?? []) query.append("language", language);

  const data = await getJson("/api/search", query, signal);
  if (!isSearchResponse(data)) {
    throw new ApiError("The research API returned results in an unexpected format.", "invalid_response", 200);
  }
  return data;
}
