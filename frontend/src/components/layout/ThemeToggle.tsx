"use client";

import { useEffect } from "react";

import { applyTheme, chooseTheme, currentTheme, storedTheme, systemTheme, THEME_STORAGE_KEY } from "@/lib/theme";

/**
 * Light/dark switch. Which icon and label show is decided by CSS (`dark:`), not
 * React state, so it's correct from the first paint and can't cause a hydration
 * mismatch. Until the user picks a theme, the page follows the system setting,
 * including changes while it's open.
 */
export function ThemeToggle() {
  useEffect(() => {
    const media = window.matchMedia("(prefers-color-scheme: dark)");
    const followSystem = () => {
      if (storedTheme() === null) applyTheme(systemTheme());
    };
    // Another tab chose a theme (or cleared it): match it here too.
    const onStorage = (event: StorageEvent) => {
      if (event.key === THEME_STORAGE_KEY || event.key === null) applyTheme(storedTheme() ?? systemTheme());
    };
    media.addEventListener("change", followSystem);
    window.addEventListener("storage", onStorage);
    return () => {
      media.removeEventListener("change", followSystem);
      window.removeEventListener("storage", onStorage);
    };
  }, []);

  return (
    <button
      type="button"
      onClick={() => chooseTheme(currentTheme() === "dark" ? "light" : "dark")}
      className="grid size-9 shrink-0 place-items-center rounded-lg border border-navy-200 bg-white text-navy-700 transition hover:border-brand-600 hover:text-brand-700 focus-visible:ring-2 focus-visible:ring-brand-600 focus-visible:outline-none dark:border-white/15 dark:bg-white/5 dark:text-navy-100 dark:hover:border-white/40 dark:hover:bg-white/10 dark:hover:text-white dark:focus-visible:ring-brand-400"
    >
      {/* Light theme on: a sun. */}
      <svg aria-hidden="true" viewBox="0 0 24 24" className="size-5 dark:hidden" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
        <circle cx="12" cy="12" r="4" />
        <path d="M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2M4.93 19.07l1.41-1.41M17.66 6.34l1.41-1.41" />
      </svg>
      {/* Dark theme on: a moon. */}
      <svg aria-hidden="true" viewBox="0 0 24 24" className="hidden size-5 dark:block" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z" />
      </svg>
      <span className="sr-only dark:hidden">Light theme is on. Switch to dark theme</span>
      <span className="sr-only hidden dark:inline">Dark theme is on. Switch to light theme</span>
    </button>
  );
}
