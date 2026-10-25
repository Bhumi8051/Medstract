/**
 * "Go home" requests from the logo link (HomeLink).
 *
 * The home screen is "/" for everyone (signed in or not). Clicking the logo
 * while already on "/" wouldn't change the URL, and Next.js keeps the "/" page's
 * state alive while you visit other pages, so a plain link could leave old
 * results on screen. Each logo click bumps this counter; the search page
 * (ResearchSearch) resets to its initial state when it sees a new value.
 */

let requests = 0;
const listeners = new Set<() => void>();

export function requestHome(): void {
  requests += 1;
  for (const listener of listeners) listener();
}

export function subscribeHomeRequests(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

export function getHomeRequests(): number {
  return requests;
}
