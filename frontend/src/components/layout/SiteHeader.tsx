import Link from "next/link";

import { AccountMenu } from "@/components/auth/AccountMenu";

export function SiteHeader() {
  return (
    <header className="border-b border-slate-200 bg-white/80 backdrop-blur dark:border-slate-800 dark:bg-slate-900/80">
      <div className="mx-auto flex max-w-6xl items-center justify-between gap-4 px-4 py-3 sm:px-6">
        <Link
          href="/"
          className="flex min-w-0 items-center gap-2.5 rounded-lg focus-visible:ring-2 focus-visible:ring-teal-600 focus-visible:outline-none"
        >
          <span
            aria-hidden="true"
            className="grid size-9 shrink-0 place-items-center rounded-lg bg-teal-700 text-sm font-bold text-white"
          >
            Rx
          </span>
          <span className="truncate text-base font-semibold tracking-tight text-slate-900 dark:text-slate-50">
            Healthcare Research Intelligence
          </span>
        </Link>
        <AccountMenu />
      </div>
    </header>
  );
}
