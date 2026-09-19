"use client";

// =============================================================================
// FILE: components/layout/AtlasModeToggle.tsx
// FEATURE: FE Feature 23 — D48, the toggle beside the notification bell.
//
// WHY IT IS ITS OWN COMPONENT AND NOT INLINE IN `Header.tsx`: `Header` pulls
// Clerk's `useUser`/`useClerk`, `useAuth`, `usePathname` and the page-header
// context, so a unit test of the toggle would have to stand all of that up to
// click one switch. The switch is testable on its own; the header renders it.
//
// A PREVIOUS SPEC CLAIMED A HEADER TAB BAR. There is none — `Header.tsx` has
// the needs-attention bell, the dual-theme switch and the profile block, and
// that was verified in the file before this was built. This sits between the
// bell and the theme switch and follows the theme switch's own pattern
// (`role="switch"`, `aria-checked`, a sliding thumb).
//
// THE EXISTING SCREENS ARE UNTOUCHED (D48). Nothing is removed, re-homed or
// redirected. Turning the switch on navigates to `/work`; turning it off
// navigates back to the app's own landing page **only when the user is standing
// on the ATLAS route**, because throwing someone off the invoice they are
// reading would be a navigation change nobody asked for.
// =============================================================================

import { usePathname, useRouter } from "next/navigation";
import { Compass, LayoutGrid } from "lucide-react";

import {
  ATLAS_ROUTE,
  CLASSIC_ROUTE,
  useAtlasMode,
} from "@/hooks/useAtlasMode";

export default function AtlasModeToggle() {
  const { isAtlas, mounted, setMode } = useAtlasMode();
  const router = useRouter();
  const pathname = usePathname();

  const onToggle = () => {
    const next = isAtlas ? "classic" : "atlas";
    setMode(next);
    if (next === "atlas") {
      router.push(ATLAS_ROUTE);
    } else if (pathname?.startsWith(ATLAS_ROUTE)) {
      router.push(CLASSIC_ROUTE);
    }
  };

  const label = isAtlas
    ? "ATLAS mode. Switch to the traditional screens"
    : "Traditional screens. Switch to ATLAS mode";

  return (
    <button
      type="button"
      role="switch"
      aria-checked={isAtlas}
      data-testid="atlas-mode-toggle"
      data-mode={isAtlas ? "atlas" : "classic"}
      data-mounted={mounted ? "yes" : "no"}
      onClick={onToggle}
      aria-label={label}
      title={label}
      className={`relative inline-flex h-7 w-14 items-center rounded-full transition-all duration-300 cursor-pointer focus:outline-none select-none ${
        isAtlas
          ? "bg-gradient-to-r from-[#0F6FC6] to-[#009DD9] border border-[#009DD9]/80 shadow-[0_0_12px_rgba(0,157,217,0.4)]"
          : "bg-[#131B2A] border border-[#222D3D] hover:border-slate-600"
      }`}
    >
      <Compass
        className={`w-3.5 h-3.5 absolute left-1.5 transition-opacity duration-200 pointer-events-none ${
          isAtlas ? "text-white/80 opacity-100" : "opacity-0"
        }`}
      />
      <LayoutGrid
        className={`w-3.5 h-3.5 absolute right-1.5 transition-opacity duration-200 pointer-events-none ${
          isAtlas ? "opacity-0" : "text-slate-400 opacity-100"
        }`}
      />
      <span
        className={`w-5 h-5 rounded-full bg-white shadow-md transform transition-transform duration-300 ease-in-out flex items-center justify-center ${
          isAtlas ? "translate-x-8" : "translate-x-1"
        }`}
      >
        {isAtlas ? (
          <Compass className="w-3 h-3 text-[#0F6FC6]" />
        ) : (
          <LayoutGrid className="w-3 h-3 text-slate-700" />
        )}
      </span>
    </button>
  );
}
