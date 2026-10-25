/**
 * The one place the frontend talks to the FastAPI backend.
 *
 * NEXT_PUBLIC_API_URL is inlined into browser code at build time, so it must
 * only ever hold a public URL. API keys (NCBI, Gemini) stay in backend/.env.
 */

import type {
  Account,
  AiUsage,
  Digest,
  DigestDelivery,
  EmailStatus,
  PaperAnalysis,
  Preferences,
  SavedSearch,
  SavedSearchFilters,
  SearchParams,
  SearchResponse,
  SubscriptionApi,
  SubscriptionInput,
  SummaryLevel,
  TestSendResult,
  UnsubscribeResult,
} from "./types";

// This project's backend runs on port 8010 (see README.md); NEXT_PUBLIC_API_URL overrides it.
const DEFAULT_API_URL = "http://localhost:8010";

export const API_BASE_URL = (process.env.NEXT_PUBLIC_API_URL || DEFAULT_API_URL).replace(/\/+$/, "");

// The backend may retry PubMed a few times before giving up, so allow some slack.
const SEARCH_TIMEOUT_MS = 45_000;
// The backend waits up to ~65 s for Gemini; allow for that plus the PubMed fetch.
const ANALYSIS_TIMEOUT_MS = 90_000;
const ACCOUNT_TIMEOUT_MS = 15_000;
// A digest runs a PubMed search and a Gemini request per subscription (up to 3), plus the email.
const DIGEST_TIMEOUT_MS = 240_000;

// The backend rejects cookie-authenticated changes without this header (CSRF defence).
const CSRF_HEADERS = { "X-Requested-With": "fetch" };

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

const SEARCH_STATUS_MESSAGES: Record<number, string> = {
  422: "Some search inputs are invalid. Please check them and try again.",
  429: "PubMed is receiving too many requests right now. Wait a moment and try again.",
  502: "PubMed returned an unexpected response. Please try again.",
  504: "PubMed took too long to respond. Please try again.",
};

const ANALYSIS_STATUS_MESSAGES: Record<number, string> = {
  404: "This paper could not be found in PubMed.",
  429: "The AI service is rate limited right now. Wait a minute and try again.",
  502: "The AI analysis could not be completed. Please try again.",
  503: "AI analysis is not available on the server right now.",
  504: "The AI analysis took too long. Please try again.",
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

const ACCOUNT_STATUS_MESSAGES: Record<number, string> = {
  401: "Please log in to continue.",
  403: "This request was blocked for security reasons. Please reload the page and try again.",
  404: "That item no longer exists.",
  409: "That conflicts with existing data.",
  422: "Some details are invalid. Please check them and try again.",
  429: "Too many attempts. Please wait a few minutes and try again.",
  503: "Accounts are temporarily unavailable. Search and paper analysis still work.",
};

interface RequestOptions {
  method?: "GET" | "POST" | "PUT" | "DELETE";
  query?: URLSearchParams;
  body?: unknown;
  timeoutMs: number;
  timeoutMessage: string;
  statusMessages: Record<number, string>;
}

async function requestJson(path: string, options: RequestOptions, signal?: AbortSignal): Promise<unknown> {
  const url = `${API_BASE_URL}${path}${options.query ? `?${options.query.toString()}` : ""}`;
  const timeout = AbortSignal.timeout(options.timeoutMs);
  const combined = signal ? AbortSignal.any([signal, timeout]) : timeout;
  const method = options.method ?? "GET";
  const headers: Record<string, string> = { Accept: "application/json" };
  if (options.body !== undefined) headers["Content-Type"] = "application/json";
  if (method !== "GET") Object.assign(headers, CSRF_HEADERS);

  let response: Response;
  try {
    response = await fetch(url, {
      method,
      headers,
      // Send and receive the HttpOnly session cookie. JavaScript never sees its value.
      credentials: "include",
      body: options.body === undefined ? undefined : JSON.stringify(options.body),
      signal: combined,
    });
  } catch (error) {
    if (signal?.aborted) throw error; // cancelled by the caller; not a real failure
    if (timeout.aborted) {
      throw new ApiError(options.timeoutMessage, "timeout");
    }
    // Browsers deliberately hide why a request failed, so list the usual causes.
    const origin = typeof window === "undefined" ? "this page's origin" : window.location.origin;
    throw new ApiError(`Could not reach the research API at ${API_BASE_URL}.`, "network", null, [
      "The backend is not running. Start it with ./dev.sh, or uvicorn in the backend folder.",
      `NEXT_PUBLIC_API_URL is incorrect. It is currently ${API_BASE_URL}; check frontend/.env.local and restart the frontend after changing it.`,
      `The backend's CORS settings do not allow ${origin}. Check CORS_ORIGINS and CORS_ALLOW_LOCAL_ORIGINS in backend/.env.`,
    ]);
  }

  if (response.status === 204) return null;

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
      detail ?? options.statusMessages[response.status] ?? `The research API returned an error (HTTP ${response.status}).`,
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

const REPORT_POINT_SECTIONS = [
  "research_question",
  "background",
  "methods",
  "key_findings",
  "interpretation",
  "limitations",
  "not_established",
] as const;

function isPaperAnalysis(value: unknown): value is PaperAnalysis {
  if (!value || typeof value !== "object") return false;
  const v = value as Record<string, unknown>;
  const report = v.report as Record<string, unknown> | undefined;
  return (
    typeof v.pmid === "string" &&
    typeof v.pubmed_url === "string" &&
    typeof v.source_note === "string" &&
    Array.isArray(v.grounding_warnings) &&
    !!report &&
    typeof report.plain_language_overview === "string" &&
    Array.isArray(report.further_questions) &&
    REPORT_POINT_SECTIONS.every(
      (section) =>
        Array.isArray(report[section]) &&
        (report[section] as unknown[]).every(
          (point) =>
            !!point &&
            typeof (point as Record<string, unknown>).text === "string" &&
            typeof (point as Record<string, unknown>).basis === "string",
        ),
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

  const data = await requestJson(
    "/api/search",
    {
      query,
      timeoutMs: SEARCH_TIMEOUT_MS,
      timeoutMessage: "The search took too long to complete. Please try again.",
      statusMessages: SEARCH_STATUS_MESSAGES,
    },
    signal,
  );
  if (!isSearchResponse(data)) {
    throw new ApiError("The research API returned results in an unexpected format.", "invalid_response", 200);
  }
  return data;
}

/**
 * Ask the backend to analyze one paper with Gemini. Only the PMID and reading
 * level are sent; the backend fetches the paper itself from PubMed.
 */
export async function analyzePaper(
  pmid: string,
  summaryLevel: SummaryLevel,
  signal?: AbortSignal,
): Promise<PaperAnalysis> {
  const data = await requestJson(
    `/api/papers/${encodeURIComponent(pmid)}/analyze`,
    {
      method: "POST",
      body: { summary_level: summaryLevel },
      timeoutMs: ANALYSIS_TIMEOUT_MS,
      timeoutMessage: "The AI analysis took too long. Please try again.",
      statusMessages: ANALYSIS_STATUS_MESSAGES,
    },
    signal,
  );
  if (!isPaperAnalysis(data)) {
    throw new ApiError("The AI analysis came back in an unexpected format.", "invalid_response", 200);
  }
  return data;
}

// ---------- accounts ----------

const accountOptions = (method: RequestOptions["method"], body?: unknown): RequestOptions => ({
  method,
  body,
  timeoutMs: ACCOUNT_TIMEOUT_MS,
  timeoutMessage: "The server took too long to respond. Please try again.",
  statusMessages: ACCOUNT_STATUS_MESSAGES,
});

/** The logged-in account, or null when not logged in. */
export async function getCurrentAccount(signal?: AbortSignal): Promise<Account | null> {
  try {
    return (await requestJson("/api/auth/me", accountOptions("GET"), signal)) as Account;
  } catch (error) {
    if (error instanceof ApiError && error.status === 401) return null;
    throw error;
  }
}

export async function register(email: string, password: string): Promise<Account> {
  return (await requestJson("/api/auth/register", accountOptions("POST", { email, password }))) as Account;
}

export async function login(email: string, password: string): Promise<Account> {
  return (await requestJson("/api/auth/login", accountOptions("POST", { email, password }))) as Account;
}

export async function logout(): Promise<void> {
  await requestJson("/api/auth/logout", accountOptions("POST"));
}

export async function updatePreferences(preferences: Preferences): Promise<Preferences> {
  return (await requestJson("/api/me/preferences", accountOptions("PUT", preferences))) as Preferences;
}

export async function listSavedSearches(signal?: AbortSignal): Promise<SavedSearch[]> {
  return (await requestJson("/api/saved-searches", accountOptions("GET"), signal)) as SavedSearch[];
}

export async function getSavedSearch(id: string, signal?: AbortSignal): Promise<SavedSearch> {
  return (await requestJson(
    `/api/saved-searches/${encodeURIComponent(id)}`,
    accountOptions("GET"),
    signal,
  )) as SavedSearch;
}

export async function createSavedSearch(input: {
  name: string;
  query: string;
  filters: SavedSearchFilters;
}): Promise<SavedSearch> {
  return (await requestJson("/api/saved-searches", accountOptions("POST", input))) as SavedSearch;
}

export async function deleteSavedSearch(id: string): Promise<void> {
  await requestJson(`/api/saved-searches/${encodeURIComponent(id)}`, accountOptions("DELETE"));
}

// ---------- research subscriptions ----------

export async function listSubscriptions(signal?: AbortSignal): Promise<SubscriptionApi[]> {
  return (await requestJson("/api/subscriptions", accountOptions("GET"), signal)) as SubscriptionApi[];
}

export async function createSubscription(input: SubscriptionInput): Promise<SubscriptionApi> {
  return (await requestJson("/api/subscriptions", accountOptions("POST", input))) as SubscriptionApi;
}

export async function updateSubscription(id: string, input: SubscriptionInput): Promise<SubscriptionApi> {
  return (await requestJson(
    `/api/subscriptions/${encodeURIComponent(id)}`,
    accountOptions("PUT", input),
  )) as SubscriptionApi;
}

export async function deleteSubscription(id: string): Promise<void> {
  await requestJson(`/api/subscriptions/${encodeURIComponent(id)}`, accountOptions("DELETE"));
}

/** Today's AI analysis allowance for the signed-in user. */
export async function getAiUsage(signal?: AbortSignal): Promise<AiUsage> {
  return (await requestJson("/api/me/ai-usage", accountOptions("GET"), signal)) as AiUsage;
}

// ---------- research digests (Step C: manual test emails) ----------

const DIGEST_STATUS_MESSAGES: Record<number, string> = {
  ...ACCOUNT_STATUS_MESSAGES,
  403: "This email can't be sent to your address.",
  429: "Too many test emails. Please wait and try again.",
  502: "The digest could not be sent. Please try again.",
  503: "Email is not available on the server right now.",
  504: "The email service took too long. Please try again.",
};

const digestOptions = (body: unknown): RequestOptions => ({
  method: "POST",
  body,
  timeoutMs: DIGEST_TIMEOUT_MS,
  timeoutMessage: "Building the digest took too long. Please try again.",
  statusMessages: DIGEST_STATUS_MESSAGES,
});

export async function getEmailStatus(signal?: AbortSignal): Promise<EmailStatus> {
  return (await requestJson("/api/digests/email-status", accountOptions("GET"), signal)) as EmailStatus;
}

/** Build a digest without sending it. AI summaries use the daily allowance. */
export async function previewDigest(subscriptionIds: string[], signal?: AbortSignal): Promise<Digest> {
  return (await requestJson(
    "/api/digests/preview",
    digestOptions({ subscription_ids: subscriptionIds }),
    signal,
  )) as Digest;
}

/** Send ONE test digest. The server always sends it to the signed-in account's own email. */
export async function sendTestDigest(subscriptionIds: string[], signal?: AbortSignal): Promise<TestSendResult> {
  return (await requestJson(
    "/api/digests/test-send",
    digestOptions({ subscription_ids: subscriptionIds }),
    signal,
  )) as TestSendResult;
}

/** The signed-in user's scheduled digest runs, newest first. */
export async function listDeliveries(signal?: AbortSignal): Promise<DigestDelivery[]> {
  return (await requestJson("/api/digests/deliveries", accountOptions("GET"), signal)) as DigestDelivery[];
}

// ---------- unsubscribe links (no login: the token in the link is the only credential) ----------

const UNSUBSCRIBE_STATUS_MESSAGES: Record<number, string> = {
  404: "This unsubscribe link is invalid or no longer exists.",
  422: "This unsubscribe link is incomplete. Open it again from the email.",
  429: "Too many attempts. Please wait a few minutes and try again.",
};

const unsubscribeOptions = (method: RequestOptions["method"], body?: unknown): RequestOptions => ({
  method,
  body,
  timeoutMs: ACCOUNT_TIMEOUT_MS,
  timeoutMessage: "The server took too long to respond. Please try again.",
  statusMessages: UNSUBSCRIBE_STATUS_MESSAGES,
});

/** What a link is for. Changes nothing. */
export async function getUnsubscribeInfo(token: string, signal?: AbortSignal): Promise<UnsubscribeResult> {
  return (await requestJson(
    "/api/unsubscribe",
    { ...unsubscribeOptions("GET"), query: new URLSearchParams({ token }) },
    signal,
  )) as UnsubscribeResult;
}

/** Unsubscribe. Safe to repeat. */
export async function confirmUnsubscribe(token: string): Promise<UnsubscribeResult> {
  return (await requestJson("/api/unsubscribe", unsubscribeOptions("POST", { token }))) as UnsubscribeResult;
}
