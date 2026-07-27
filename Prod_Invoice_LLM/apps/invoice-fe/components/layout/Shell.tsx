"use client";

import React from "react";
import { usePathname } from "next/navigation";
import Sidebar from "./Sidebar";
import Header from "./Header";

interface ShellProps {
  children: React.ReactNode;
}

// Gap 62: /flows is a standalone, no-login public demo page (not a real
// tenant screen), but it was rendered inside the same Sidebar+Header chrome
// as every authenticated in-app screen. An anonymous visitor could click
// Dashboard/Ingest/Chat/etc. straight into real internal screens that mean
// nothing to them (and aren't meant to be reached this way) -- confusing,
// and not the intended "give an end user a feel of the project" experience.
// Routes in this list render full-bleed with no app chrome at all.
const STANDALONE_ROUTES = ["/flows"];

export default function Shell({ children }: ShellProps) {
  const pathname = usePathname();
  const isStandalone = STANDALONE_ROUTES.some((r) => pathname === r || pathname?.startsWith(`${r}/`));

  if (isStandalone) {
    return <>{children}</>;
  }

  return (
    <div className="flex h-screen w-screen overflow-hidden bg-bg-main">
      {/* Sidebar Panel */}
      <Sidebar />

      {/* Main Panel Content Area */}
      <div className="flex flex-col flex-1 h-full overflow-hidden">
        {/* Top Header */}
        <Header />

        {/* Scrollable Children Canvas */}
        <main className="flex-1 overflow-y-auto p-8 bg-gradient-to-b from-[#0B0F19] to-[#080B12]">
          {children}
        </main>
      </div>
    </div>
  );
}
