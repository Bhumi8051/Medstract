import type { Metadata } from "next";
import { Geist } from "next/font/google";

import { AiUsageProvider } from "@/components/analysis/AiUsageProvider";
import { AuthProvider } from "@/components/auth/AuthProvider";
import { SubscriptionsProvider } from "@/components/subscriptions/SubscriptionsProvider";
import { THEME_INIT_SCRIPT } from "@/lib/theme";

import "./globals.css";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  // Page titles read "Your account · Medstract"; the home page is just "Medstract".
  title: { default: "Medstract", template: "%s · Medstract" },
  applicationName: "Medstract",
  appleWebApp: { title: "Medstract" },
  description: "Medstract: search, filter and rank biomedical research papers from PubMed.",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html
      lang="en"
      className={`${geistSans.variable} h-full antialiased`}
      // The inline script below sets data-theme before React hydrates.
      suppressHydrationWarning
    >
      <head>
        {/* Sets the light/dark theme before the first paint (no flash). See src/lib/theme.ts. */}
        <script dangerouslySetInnerHTML={{ __html: THEME_INIT_SCRIPT }} />
      </head>
      <body className="flex min-h-full flex-col bg-navy-50 text-navy-900 dark:bg-navy-950 dark:text-navy-100">
        <AuthProvider>
          <AiUsageProvider>
            <SubscriptionsProvider>{children}</SubscriptionsProvider>
          </AiUsageProvider>
        </AuthProvider>
      </body>
    </html>
  );
}
