"use client";

// =============================================================================
// FILE: components/chat/cards/ChecksDisclosure.tsx
// FEATURE: FE Feature 22 Task 22.11 — "what did it actually check?" on the insight
//          bubble (FE Feature 21's InsightBubble is the spec's `InsightCard`).
//
// One collapsed line per bubble listing each card's own sentence
// ("3 invoices checked, 1 not checked" — `CheckLog.title()`), and on expand the
// subjects that could NOT be checked, grouped by reason. Nothing is counted here.
//
// NOT_CHECKED is information about a missing input, not a failure: it is styled
// neutral (slate/amber), never red, and never merged into the checked count.
//
// ⚠️ The spec also asks for the "evidence thread from the investigate step". The
// backend's `investigate()` (agents/analyst_agent.py) is still a stub that
// returns cards unchanged (BE task 33.5), so there is no thread to render —
// plan open item #22.
// =============================================================================

import React, { useState } from "react";
import { ChevronDown, ChevronRight, ListChecks } from "lucide-react";
import type { CheckSummary } from "@/lib/chatInsights";

export default function ChecksDisclosure({ summaries }: { summaries: CheckSummary[] }) {
  const [open, setOpen] = useState(false);
  if (summaries.length === 0) return null;

  const hasUnchecked = summaries.some((summary) => summary.notChecked.length > 0);

  return (
    <div data-testid="insight-checks" className="mt-1.5">
      <button
        type="button"
        aria-expanded={open}
        onClick={() => setOpen((value) => !value)}
        disabled={!hasUnchecked}
        className="inline-flex items-start gap-1.5 text-left text-[11px] text-slate-400 hover:text-slate-200 disabled:cursor-default disabled:hover:text-slate-400 focus:outline-none focus:ring-1 focus:ring-blue-600"
      >
        <ListChecks className="mt-px h-3 w-3 shrink-0" aria-hidden="true" />
        <span data-testid="insight-checks-summary">{summaries.map((summary) => summary.title).join(" · ")}</span>
        {hasUnchecked &&
          (open ? (
            <ChevronDown className="mt-px h-3 w-3 shrink-0" aria-hidden="true" />
          ) : (
            <ChevronRight className="mt-px h-3 w-3 shrink-0" aria-hidden="true" />
          ))}
      </button>

      {open && hasUnchecked && (
        <ul data-testid="insight-checks-unchecked" className="mt-1 space-y-1 pl-4.5">
          {summaries.flatMap((summary) =>
            summary.notChecked.map((group, index) => (
              <li key={`${summary.card}-${index}`} className="text-[11px] text-amber-200/80">
                <span className="text-slate-300">Not checked — {group.reason}:</span> {group.subjects.join(", ")}
              </li>
            ))
          )}
        </ul>
      )}
    </div>
  );
}
