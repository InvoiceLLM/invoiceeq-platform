"use client";

// =============================================================================
// FILE: components/today/PositionLine.tsx
// FEATURE: FE Feature 22 Task 22.5 — one cash-position sentence, for ONE currency.
//
// The sentence is the forecast's certain tier, written by the backend. Two
// currencies are two lines; nothing here converts, sums or blends them, and the
// line is not clickable — it is information, not a finding to discuss.
// =============================================================================

import React from "react";
import { Wallet } from "lucide-react";
import type { TodayLineModel } from "@/lib/today";

export default function PositionLine({ line }: { line: TodayLineModel }) {
  return (
    <li data-testid="today-line-position" className="flex items-start gap-3 px-5 py-3.5">
      <Wallet className="mt-0.5 h-4 w-4 shrink-0 text-emerald-400" aria-hidden="true" />
      <p className="text-sm text-slate-100">{line.text}</p>
    </li>
  );
}
