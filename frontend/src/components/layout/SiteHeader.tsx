import { AccountMenu } from "@/components/auth/AccountMenu";

import { HomeLink } from "./HomeLink";
import { ThemeToggle } from "./ThemeToggle";

export function SiteHeader() {
  return (
    // Ivory in the light theme, the darkest navy in the dark theme.
    <header className="border-b border-navy-200 bg-navy-50 dark:border-navy-800 dark:bg-navy-950">
      <div className="page-container flex items-center justify-between gap-4 py-3.5">
        <HomeLink />
        <div className="flex shrink-0 items-center gap-2">
          <ThemeToggle />
          <AccountMenu />
        </div>
      </div>
    </header>
  );
}
