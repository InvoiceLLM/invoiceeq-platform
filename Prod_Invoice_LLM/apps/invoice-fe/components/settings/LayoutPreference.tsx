"use client";

// =============================================================================
// FILE: components/settings/LayoutPreference.tsx
// FEATURE: FE Feature 22 Task 22.21 — the classic-layout switch.
//
// `variant="header"`: a compact switch in Header.tsx, beside the theme toggle
// (which stays independent — hooks/useTheme.ts is untouched).
// `variant="settings"`: the same preference as a labelled row on the Settings page.
// Both read and write the one LayoutPreferenceContext; neither renders anything
// when the four surfaces are switched off.
// =============================================================================

import React from "react";
import { LayoutGrid, Loader2 } from "lucide-react";
import { useLayoutPreference } from "@/components/layout/LayoutPreferenceContext";

export default function LayoutPreference({ variant = "header" }: { variant?: "header" | "settings" }) {
  const pref = useLayoutPreference();
  if (!pref || pref.layout === null) return null;

  const classic = pref.layout === "classic";
  const toggle = () => void pref.setLayout(classic ? "surfaces" : "classic");

  const control = (
    <button
      type="button"
      role="switch"
      aria-checked={classic}
      aria-label="Classic layout"
      data-testid={`layout-switch-${variant}`}
      onClick={toggle}
      disabled={pref.saving}
      title={classic ? "Classic layout is on — switch to Today / Ask / Records / Settings" : "Switch to the classic layout"}
      className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-[11px] font-medium transition-colors disabled:opacity-60 ${
        classic
          ? "border-amber-500/40 bg-amber-500/10 text-amber-300"
          : "border-[#222D3D] bg-[#131B2A] text-slate-400 hover:border-slate-600 hover:text-slate-200"
      }`}
    >
      {pref.saving ? <Loader2 className="h-3 w-3 animate-spin" aria-hidden="true" /> : <LayoutGrid className="h-3 w-3" aria-hidden="true" />}
      Classic
    </button>
  );

  if (variant === "header") {
    return (
      <span className="inline-flex items-center gap-2">
        {control}
        {pref.error && (
          <span role="alert" className="text-[11px] text-rose-300">
            {pref.error}
          </span>
        )}
      </span>
    );
  }

  return (
    <div data-testid="layout-preference-row" className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-[#1E293B] bg-[#0B0F19] px-5 py-3">
      <div className="min-w-0">
        <p className="text-sm font-semibold text-white">Classic layout</p>
        <p className="text-xs text-slate-500">
          {classic
            ? "On: the full sidebar, starting on the Dashboard."
            : "Off: Today, Ask, Records and Settings, starting on Today."}{" "}
          Saved for your account on every device.
        </p>
      </div>
      <div className="flex items-center gap-2">
        {pref.error && (
          <span role="alert" className="text-xs text-rose-300">
            {pref.error}
          </span>
        )}
        {control}
      </div>
    </div>
  );
}
