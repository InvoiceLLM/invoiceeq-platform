import type { Metadata } from "next";
import { ClerkProvider } from "@clerk/nextjs";
import "./globals.css";
import { Header } from "@/components/marketing/Header";
import { Footer } from "@/components/marketing/Footer";
import { MouseSpotlight } from "@/components/marketing/MouseSpotlight";

export const metadata: Metadata = {
  title: "Invoice AI — Enterprise AI-Powered Invoice Processing Platform",
  description:
    "Enterprise AI-powered invoice extraction, 3-way PO matching, and automated document processing built on Azure AI & multi-LLM consensus.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <ClerkProvider publishableKey={process.env.NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY}>
      <html lang="en" className="dark">
        <body className="antialiased min-h-screen flex flex-col selection:bg-blue-500/30 selection:text-cyan-300 relative">
          {/* Subtle Cursor Spotlight */}
          <MouseSpotlight />

          {/* Global Grid Overlay Pattern */}
          <div className="pointer-events-none fixed inset-0 bg-[linear-gradient(to_right,#ffffff05_1px,transparent_1px),linear-gradient(to_bottom,#ffffff05_1px,transparent_1px)] bg-[size:4rem_4rem] -z-20" />

          {/* Global Aurora Lights Background */}
          <div className="pointer-events-none fixed top-0 left-1/2 -translate-x-1/2 w-[1200px] h-[600px] bg-gradient-to-b from-[#3B82F6]/15 via-[#8B5CF6]/10 to-transparent blur-[160px] rounded-full -z-10 animate-aurora" />

          {children}
          <Footer />
        </body>
      </html>
    </ClerkProvider>
  );
}
