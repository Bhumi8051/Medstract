import { LoginButton } from "@/components/auth/LoginButton";

export function SiteHeader() {
  return (
    <header className="border-b border-slate-200 bg-white/80 backdrop-blur dark:border-slate-800 dark:bg-slate-900/80">
      <div className="mx-auto flex max-w-6xl items-center justify-between gap-4 px-4 py-3 sm:px-6">
        <div className="flex min-w-0 items-center gap-2.5">
          <span
            aria-hidden="true"
            className="grid size-9 shrink-0 place-items-center rounded-lg bg-teal-700 text-sm font-bold text-white"
          >
            Rx
          </span>
          <span className="truncate text-base font-semibold tracking-tight text-slate-900 dark:text-slate-50">
            Healthcare Research Intelligence
          </span>
        </div>
        <LoginButton />
      </div>
    </header>
  );
}
