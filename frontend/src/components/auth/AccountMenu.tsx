"use client";

import Link from "next/link";
import { useRef } from "react";

import { useAuth } from "./AuthProvider";

const buttonClass =
  "shrink-0 rounded-lg border border-slate-300 bg-white px-4 py-2 text-sm font-semibold whitespace-nowrap text-slate-800 shadow-sm transition hover:border-teal-600 hover:text-teal-800 focus-visible:ring-2 focus-visible:ring-teal-600 focus-visible:outline-none dark:border-slate-700 dark:bg-slate-900 dark:text-slate-100 dark:hover:text-teal-300";

/** Top-right account control: "Log in" when signed out, an account menu when signed in. */
export function AccountMenu() {
  const { status, account, logout, openAuthDialog } = useAuth();
  const menuRef = useRef<HTMLDivElement>(null);

  if (status === "loading") {
    return <span aria-hidden="true" className="h-9 w-20 animate-pulse rounded-lg bg-slate-200 dark:bg-slate-800" />;
  }
  if (status !== "authenticated" || !account) {
    return (
      <button type="button" onClick={() => openAuthDialog("login")} className={buttonClass}>
        Log in
      </button>
    );
  }

  const closeMenu = () => menuRef.current?.hidePopover();

  return (
    <>
      <button type="button" popoverTarget="account-menu" className={`${buttonClass} inline-flex items-center gap-2`}>
        <span
          aria-hidden="true"
          className="grid size-6 place-items-center rounded-full bg-teal-700 text-xs font-bold text-white uppercase"
        >
          {account.user.email[0]}
        </span>
        <span className="hidden max-w-40 truncate sm:inline">{account.user.email}</span>
        <span className="sr-only sm:hidden">Account menu</span>
      </button>
      <div
        ref={menuRef}
        id="account-menu"
        popover="auto"
        className="fixed inset-auto top-16 right-4 m-0 w-64 rounded-xl border border-slate-200 bg-white p-2 text-sm shadow-lg dark:border-slate-700 dark:bg-slate-900"
      >
        <p className="truncate px-3 py-2 text-xs text-slate-500 dark:text-slate-400">Signed in as {account.user.email}</p>
        <Link
          href="/"
          onClick={closeMenu}
          className="block rounded-lg px-3 py-2 text-slate-800 hover:bg-slate-100 focus-visible:ring-2 focus-visible:ring-teal-600 focus-visible:outline-none dark:text-slate-100 dark:hover:bg-slate-800"
        >
          Search
        </Link>
        <Link
          href="/account"
          onClick={closeMenu}
          className="block rounded-lg px-3 py-2 text-slate-800 hover:bg-slate-100 focus-visible:ring-2 focus-visible:ring-teal-600 focus-visible:outline-none dark:text-slate-100 dark:hover:bg-slate-800"
        >
          Preferences &amp; saved searches
        </Link>
        <button
          type="button"
          onClick={async () => {
            closeMenu();
            await logout().catch(() => undefined);
          }}
          className="block w-full rounded-lg px-3 py-2 text-left text-slate-800 hover:bg-slate-100 focus-visible:ring-2 focus-visible:ring-teal-600 focus-visible:outline-none dark:text-slate-100 dark:hover:bg-slate-800"
        >
          Log out
        </button>
      </div>
    </>
  );
}
