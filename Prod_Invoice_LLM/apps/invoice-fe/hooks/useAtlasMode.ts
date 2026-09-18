"use client";

// =============================================================================
// FILE: hooks/useAtlasMode.ts
// FEATURE: FE Feature 23 — D48, the ATLAS / traditional toggle.
//
// D48 (2026-09-18) PARTIALLY REVERSES D10. D10 deleted the classic-layout
// toggle on the grounds that the four-surfaces project was superseded and there
// was "no duality to toggle between". There is one again: ATLAS is an **added**
// surface (`/work`) and the existing tabbed screens stay exactly as they are —
// not removed, not re-homed, not redirected.
//
// THE CHOICE LIVES IN THE BROWSER AND NOWHERE ELSE. There is no per-user
// preference store in this backend: FE Feature 22 specced one (`user.ui_prefs`
// + `PATCH /me/preferences`, BE 33.39) and Feature 33 was never built. Building
// one for a toggle was ruled out. Two consequences, stated here rather than
// discovered later:
//   1. the choice does not follow a user to another device or another browser;
//   2. **nobody can see which mode people actually use** — which is the evidence
//      that would eventually justify retiring either surface.
//
// SSR SAFETY. `localStorage` does not exist on the server, and reading it during
// the first client render would make the markup disagree with the server's.
// So the first render is always `classic` and the stored value lands in an
// effect, exactly like `useTheme`. `mounted` is exported so a caller can avoid
// rendering a switch in the wrong position for one frame.
// =============================================================================

import { useCallback, useEffect, useState } from "react";

export type AtlasMode = "classic" | "atlas";

/** The one localStorage key. Namespaced like `app_theme`, the neighbouring one. */
export const ATLAS_MODE_STORAGE_KEY = "app_atlas_mode";

/** Fired so every mounted copy of the toggle agrees within the same tab. */
export const ATLAS_MODE_EVENT = "atlas-mode-change";

/** The route ATLAS mode means. Already built (FE Feature 23 task 3). */
export const ATLAS_ROUTE = "/work";

/**
 * Where "traditional" lands when leaving ATLAS. `app/page.tsx` redirects `/` to
 * `/dashboard`, so this is the app's own landing page and not a new one.
 */
export const CLASSIC_ROUTE = "/dashboard";

function readStored(): AtlasMode {
  try {
    return window.localStorage.getItem(ATLAS_MODE_STORAGE_KEY) === "atlas"
      ? "atlas"
      : "classic";
  } catch {
    // Private browsing and blocked storage throw on access rather than
    // returning null. A toggle that cannot remember still has to work.
    return "classic";
  }
}

export function useAtlasMode() {
  const [mode, setMode] = useState<AtlasMode>("classic");
  const [mounted, setMounted] = useState(false);

  useEffect(() => {
    setMounted(true);
    setMode(readStored());

    const onChange = (event: Event) => {
      const detail = (event as CustomEvent<AtlasMode>).detail;
      if (detail) setMode(detail);
    };
    window.addEventListener(ATLAS_MODE_EVENT, onChange);
    return () => window.removeEventListener(ATLAS_MODE_EVENT, onChange);
  }, []);

  const applyMode = useCallback((next: AtlasMode) => {
    setMode(next);
    try {
      window.localStorage.setItem(ATLAS_MODE_STORAGE_KEY, next);
    } catch {
      // Same reason as above: the mode still changes for this session.
    }
    window.dispatchEvent(new CustomEvent(ATLAS_MODE_EVENT, { detail: next }));
  }, []);

  return {
    mode,
    mounted,
    isAtlas: mode === "atlas",
    setMode: applyMode,
    toggleMode: useCallback(
      () => applyMode(readStored() === "atlas" ? "classic" : "atlas"),
      [applyMode]
    ),
  };
}
