import type { Metadata } from "next";
import { ClerkProvider } from "@clerk/nextjs";
import "../styles/globals.css";
import Shell from "../components/layout/Shell";

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
    <ClerkProvider publishableKey={process.env.NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY}>
      <html lang="en">
        <body className="antialiased">
          <Shell>{children}</Shell>
        </body>
      </html>
    </ClerkProvider>
  );
}
