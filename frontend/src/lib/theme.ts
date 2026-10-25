/**
 * Light/dark theme.
 *
 * The theme is the `data-theme` attribute on <html> ("light" | "dark"). Tailwind's
 * `dark:` variant and `color-scheme` follow it (app/globals.css). An inline script
 * in <head> (app/layout.tsx) sets it before the first paint, so there's no flash:
 * the user's saved choice if any, otherwise their system preference. Without
 * JavaScript the attribute is never set and the CSS falls back to the system theme.
 */

export type Theme = "light" | "dark";

export const THEME_STORAGE_KEY = "theme";

/** Runs in <head> before anything is painted. Keep it tiny and self-contained. */
export const THEME_INIT_SCRIPT = `(function(){try{var t=localStorage.getItem("${THEME_STORAGE_KEY}");if(t!=="light"&&t!=="dark")t=matchMedia("(prefers-color-scheme: dark)").matches?"dark":"light";document.documentElement.setAttribute("data-theme",t)}catch(e){}})()`;

export function systemTheme(): Theme {
  return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

/** The user's explicit choice, or null if they haven't made one (or storage is unavailable). */
export function storedTheme(): Theme | null {
  try {
    const value = window.localStorage.getItem(THEME_STORAGE_KEY);
    return value === "light" || value === "dark" ? value : null;
  } catch {
    return null;
  }
}

export function currentTheme(): Theme {
  const value = document.documentElement.getAttribute("data-theme");
  return value === "light" || value === "dark" ? value : systemTheme();
}

export function applyTheme(theme: Theme): void {
  document.documentElement.setAttribute("data-theme", theme);
}

/** Switch now and remember the choice (if storage is available). */
export function chooseTheme(theme: Theme): void {
  applyTheme(theme);
  try {
    window.localStorage.setItem(THEME_STORAGE_KEY, theme);
  } catch {
    // Private mode or blocked storage: the theme still changes for this page view.
  }
}
