import type { Metadata } from "next";

import { AccountPage } from "@/components/account/AccountPage";
import { SiteHeader } from "@/components/layout/SiteHeader";

export const metadata: Metadata = {
  title: "Your account",
};

export default function AccountRoute() {
  return (
    <>
      <SiteHeader />
      {/* AccountPage lays out its own full-width band and columns. */}
      <main className="flex-1">
        <AccountPage />
      </main>
    </>
  );
}
