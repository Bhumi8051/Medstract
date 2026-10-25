"use client";

import Image from "next/image";
import Link from "next/link";
import type { MouseEvent } from "react";

import { requestHome } from "@/lib/homeNavigation";

/**
 * The app logo and name, linking to the home screen ("/", the same for signed-in
 * and signed-out users). A plain click also resets the search page to its initial
 * state, even when you're already on it. Modified clicks (open in a new tab, etc.)
 * are left to the browser and don't reset the current page.
 */
export function HomeLink() {
  function handleClick(event: MouseEvent<HTMLAnchorElement>) {
    if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    requestHome();
  }

  return (
    <Link
      href="/"
      onClick={handleClick}
      aria-label="Medstract, go to home page"
      className="flex min-w-0 items-center gap-2.5 rounded-lg focus-visible:ring-2 focus-visible:ring-brand-600 focus-visible:outline-none dark:focus-visible:ring-brand-400"
    >
      {/* The logo is dark navy on transparent: a white tile keeps it visible in dark mode too. */}
      <span
        aria-hidden="true"
        className="grid size-9 shrink-0 place-items-center rounded-lg bg-white ring-1 ring-navy-200 dark:ring-white/20"
      >
        <Image src="/logo.svg" alt="" width={28} height={28} loading="eager" className="size-7" />
      </span>
      {/* The Medstract wordmark (public/medstract.svg, dark navy). In dark mode the same
          file is turned white with a filter, so it stays readable without a second asset.
          151x20 keeps its 1133:150 aspect ratio; it may shrink (never stretch) on narrow screens. */}
      <Image
        src="/medstract.svg"
        alt=""
        width={151}
        height={20}
        loading="eager"
        className="h-auto w-[151px] max-w-full min-w-0 dark:brightness-0 dark:invert"
      />
    </Link>
  );
}
