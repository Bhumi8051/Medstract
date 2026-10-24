import type { Metadata } from "next";

import { AccountPage } from "@/components/account/AccountPage";
import { SiteHeader } from "@/components/layout/SiteHeader";

export const metadata: Metadata = {
  title: "Your account · Healthcare Research Intelligence Agent",
};

export default function AccountRoute() {
  return (
    <>
      <SiteHeader />
      <main className="mx-auto w-full max-w-4xl flex-1 px-4 py-8 sm:px-6">
        <AccountPage />
      </main>
    </>
  );
}
