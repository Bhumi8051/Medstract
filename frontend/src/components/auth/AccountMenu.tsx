"use client";

import Link from "next/link";
import { useRef } from "react";

import { useAuth } from "./AuthProvider";

const buttonClass =
  "shrink-0 rounded-lg border border-navy-200 bg-white px-4 py-2 text-sm font-semibold whitespace-nowrap text-navy-800 transition hover:border-brand-600 hover:text-brand-700 focus-visible:ring-2 focus-visible:ring-brand-600 focus-visible:outline-none dark:border-white/15 dark:bg-white/5 dark:text-white dark:hover:border-white/40 dark:hover:bg-white/10 dark:focus-visible:ring-brand-400";

/** Top-right account control: "Log in" when signed out, an account menu when signed in. */
export function AccountMenu() {
  const { status, account, logout, openAuthDialog } = useAuth();
  const menuRef = useRef<HTMLDivElement>(null);

  if (status === "loading") {
    return <span aria-hidden="true" className="h-9 w-20 animate-pulse rounded-lg bg-navy-200 dark:bg-white/10" />;
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
          className="grid size-6 place-items-center rounded-full bg-highlight text-xs font-bold text-navy-950 uppercase"
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
        className="fixed inset-auto top-16 right-4 m-0 w-64 rounded-xl border border-navy-200 bg-white p-2 text-sm shadow-lg dark:border-navy-700 dark:bg-navy-900"
      >
        <p className="truncate px-3 py-2 text-xs text-navy-500 dark:text-navy-400">Signed in as {account.user.email}</p>
        <Link
          href="/"
          onClick={closeMenu}
          className="block rounded-lg px-3 py-2 text-navy-800 hover:bg-navy-100 focus-visible:ring-2 focus-visible:ring-brand-600 focus-visible:outline-none dark:text-navy-100 dark:hover:bg-navy-800"
        >
          Search
        </Link>
        <Link
          href="/account"
          onClick={closeMenu}
          className="block rounded-lg px-3 py-2 text-navy-800 hover:bg-navy-100 focus-visible:ring-2 focus-visible:ring-brand-600 focus-visible:outline-none dark:text-navy-100 dark:hover:bg-navy-800"
        >
          Preferences &amp; saved searches
        </Link>
        <button
          type="button"
          onClick={async () => {
            closeMenu();
            await logout().catch(() => undefined);
          }}
          className="block w-full rounded-lg px-3 py-2 text-left text-navy-800 hover:bg-navy-100 focus-visible:ring-2 focus-visible:ring-brand-600 focus-visible:outline-none dark:text-navy-100 dark:hover:bg-navy-800"
        >
          Log out
        </button>
      </div>
    </>
  );
}
