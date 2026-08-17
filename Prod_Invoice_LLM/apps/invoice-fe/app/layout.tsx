import type { Metadata } from "next";
import { ClerkProvider } from "@clerk/nextjs";
import "../styles/globals.css";
import Shell from "../components/layout/Shell";
import AppInsightsProvider from "../components/monitoring/AppInsightsProvider";

export const metadata: Metadata = {
  title: "Invoice AI Dashboard",
  description: "Enterprise SaaS multi-tenant AI invoice processing platform.",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <ClerkProvider
      publishableKey={process.env.NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY}
      // Gap 151: second layer behind Header.tsx's explicit signOut(redirectUrl)
      // -- covers any sign-out path that isn't that one button (e.g. a
      // Clerk-initiated session-expiry sign-out) so it doesn't fall through
      // to Clerk's hosted Account Portal either.
      afterSignOutUrl={`${process.env.NEXT_PUBLIC_WEBSITE_URL || "http://localhost:3000"}/login`}
    >
      <html lang="en">
        <body className="antialiased">
          <AppInsightsProvider>
            <Shell>{children}</Shell>
          </AppInsightsProvider>
        </body>
      </html>
    </ClerkProvider>
  );
}
