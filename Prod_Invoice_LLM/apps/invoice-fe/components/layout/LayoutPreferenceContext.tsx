"use client";

// =============================================================================
// FILE: components/layout/LayoutPreferenceContext.tsx
// FEATURE: FE Feature 22 Task 22.21 — the per-user "classic layout" preference,
//          read ONCE at layout level (spec §1: "no per-route forks").
//
//   layout "surfaces" (default) -> PrimaryNav, old routes redirect, land on /today
//   layout "classic"            -> the ten-item Sidebar + Today, old routes render,
//                                  land on /dashboard
//
// Persisted per user through `GET/PATCH /auth/me/preferences` (BE 33.39) — never
// localStorage, so it follows the user to another device. Only mounted while the
// four surfaces are switched on (NEXT_PUBLIC_FOUR_SURFACES); with them off there
// is no provider, `useLayoutPreference()` returns null, and the shell is exactly
// what it was. A failed read falls back to the server's default, "surfaces".
// =============================================================================

import React, { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import { getPreferences, todayErrorOf, updatePreferences, type LayoutPreference } from "@/lib/today";

export interface LayoutPreferenceState {
  /** `null` while the preference is still loading. */
  layout: LayoutPreference | null;
  saving: boolean;
  error: string | null;
  setLayout: (next: LayoutPreference) => Promise<void>;
}

const LayoutPreferenceContext = createContext<LayoutPreferenceState | null>(null);

export function LayoutPreferenceProvider({ children }: { children: React.ReactNode }) {
  const [layout, setLayoutState] = useState<LayoutPreference | null>(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    getPreferences()
      .then((prefs) => {
        if (!cancelled) setLayoutState(prefs.layout === "classic" ? "classic" : "surfaces");
      })
      .catch(() => {
        if (!cancelled) setLayoutState("surfaces");
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const setLayout = useCallback(async (next: LayoutPreference) => {
    setSaving(true);
    setError(null);
    try {
      const prefs = await updatePreferences({ layout: next });
      setLayoutState(prefs.layout === "classic" ? "classic" : "surfaces");
    } catch (err) {
      setError(todayErrorOf(err)?.detail ?? "Could not save your layout choice.");
    } finally {
      setSaving(false);
    }
  }, []);

  const value = useMemo(() => ({ layout, saving, error, setLayout }), [layout, saving, error, setLayout]);
  return <LayoutPreferenceContext.Provider value={value}>{children}</LayoutPreferenceContext.Provider>;
}

/** `null` when the four surfaces are off (no provider). */
export function useLayoutPreference(): LayoutPreferenceState | null {
  return useContext(LayoutPreferenceContext);
}
