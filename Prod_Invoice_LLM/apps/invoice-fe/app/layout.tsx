import type { Metadata } from "next";
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
    <html lang="en">
      <body className="antialiased">
        <Shell>{children}</Shell>
      </body>
    </html>
  );
}
