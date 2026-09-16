"use client";

import React, { useEffect } from "react";
import { usePathname, useRouter } from "next/navigation";
import Sidebar from "./Sidebar";
import Header from "./Header";
import { PageHeaderProvider } from "./PageHeaderContext";
import WorkflowSetupBanner from "@/components/settings/WorkflowSetupBanner";
import PrimaryNav from "@/components/nav/PrimaryNav";
import { fourSurfacesEnabled, legacyRedirectFor } from "@/lib/navigation";
import { LayoutPreferenceProvider, useLayoutPreference } from "./LayoutPreferenceContext";

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

function ShellFrame({ children }: ShellProps) {
  const pathname = usePathname();
  const router = useRouter();
  const isStandalone = STANDALONE_ROUTES.some((r) => pathname === r || pathname?.startsWith(`${r}/`));

  // FE Feature 22 Task 22.1: with the four surfaces on, an old route is sent to
  // its new home here — once, at layout level, not forked per route (spec §1).
  // The page itself is never mounted while the redirect is pending, so the old
  // screen does not flash or fire its API calls. The query string is read from
  // `window.location` inside the effect rather than `useSearchParams()`, which
  // would force a Suspense boundary around the whole root layout.
  //
  // FE Feature 22 Task 22.21: the user's layout preference decides it, read once
  // here. `surfaces` redirects; `classic` renders the old route as it always was.
  // While the preference is still loading, an old route is HELD — neither
  // rendered nor redirected — so a classic user never bounces to /today and a
  // surfaces user never sees the old page flash.
  const fourSurfaces = fourSurfacesEnabled();
  const layout = useLayoutPreference()?.layout ?? null;
  const surfaces = fourSurfaces && layout === "surfaces";
  const classic = fourSurfaces && layout === "classic";
  const legacyRoute = legacyRedirectFor(pathname ?? "") !== null;
  const redirectPending = fourSurfaces && legacyRoute && !classic;
  useEffect(() => {
    if (!surfaces || !legacyRoute) return;
    const target = legacyRedirectFor(pathname ?? "", window.location.search);
    if (target) router.replace(target);
  }, [surfaces, legacyRoute, pathname, router]);

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
        {/* Sidebar Panel -- the four surfaces when switched on (22.1); the
            ten-item Sidebar otherwise, which 22.21's classic layout keeps. */}
        {!fourSurfaces ? (
          <Sidebar />
        ) : surfaces ? (
          <PrimaryNav />
        ) : classic ? (
          <Sidebar showToday />
        ) : (
          // Preference still loading: an empty rail of the same width, so neither
          // nav flashes at a user it is not meant for.
          <aside data-testid="nav-loading" className="w-64 border-r border-[#222D3D] bg-[#0F172A]/40" />
        )}

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
            {redirectPending ? null : children}
          </main>
        </div>
      </div>
    </PageHeaderProvider>
  );
}

/**
 * FE Feature 22 Task 22.21: the layout preference is only read while the four
 * surfaces are switched on, and never on a standalone (public) route.
 */
export default function Shell({ children }: ShellProps) {
  const pathname = usePathname();
  const isStandalone = STANDALONE_ROUTES.some((r) => pathname === r || pathname?.startsWith(`${r}/`));
  if (!fourSurfacesEnabled() || isStandalone) return <ShellFrame>{children}</ShellFrame>;
  return (
    <LayoutPreferenceProvider>
      <ShellFrame>{children}</ShellFrame>
    </LayoutPreferenceProvider>
  );
}
