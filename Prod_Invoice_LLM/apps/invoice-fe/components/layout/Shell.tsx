"use client";

import React from "react";
import { usePathname } from "next/navigation";
import Sidebar from "./Sidebar";
import Header from "./Header";
import { PageHeaderProvider } from "./PageHeaderContext";
import WorkflowSetupBanner from "@/components/settings/WorkflowSetupBanner";
import { RouteGuard } from "./RouteGuard";

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
    // FE Gap 110: the provider has to wrap both <Header /> and {children},
    // because the header is what renders each page's title and the pages are
    // what declare it -- the state has to sit above their nearest common
    // ancestor, which is this element.
    <PageHeaderProvider>
      <div className="flex h-screen w-screen overflow-hidden bg-bg-main">
        {/* Sidebar Panel */}
        <Sidebar />

        {/* Main Panel Content Area */}
        <div className="flex flex-col flex-1 h-full overflow-hidden">
          {/* Top Header -- the app's only page header, for every route */}
          <Header />

          {/* Feature 17 / FE Gap 323: first-run prompt for an Admin whose
              tenant has never completed the Plug & Play wizard. Renders null
              for everyone else, on any fetch failure, and once the wizard has
              been completed -- see the component for why it is a banner rather
              than a redirect. Deliberately outside <main> so it is not part of
              the scrollable page canvas. */}
          <WorkflowSetupBanner />

          {/* Scrollable Children Canvas.
              FE Gap 270: was overflow-y-auto only. At non-100% browser zoom,
              a data-dense page (the Audit Queue table was the first report)
              can end up wider than the computed viewport, and with no
              horizontal scroll here the outer shell's overflow-hidden (above)
              had nowhere to let that overflow go -- it clipped/forced content
              to overlap instead of scrolling. overflow-auto lets it scroll
              horizontally too, same as it already does vertically. */}
          <main className="flex-1 overflow-auto p-8 bg-gradient-to-b from-[#0B0F19] to-[#080B12]">
            {/* Gap 431: permissions filtered nav links but nothing guarded the
                routes -- middleware.ts only calls auth().protect(), which checks
                that a session exists and nothing about what it may do. Typing a
                URL reached any screen. Wrapped here rather than per-page so a
                new route cannot be added without inheriting the guard. */}
            <RouteGuard>{children}</RouteGuard>
          </main>
        </div>
      </div>
    </PageHeaderProvider>
  );
}
