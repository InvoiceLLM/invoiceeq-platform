// =============================================================================
// FILE: components/insights/OpenFindingsChip.tsx
// FEATURE: FE Feature 21 task 21.8 — the History screen's "Open findings" chip,
//          fed by `GET /chat/insights?status=OPEN` (spec §8, "Dashboard").
//
// WHY A PANEL AND NOT A FILTER. §8 calls this a "filter chip", but the History
// screen it lands on lists ingestion RUNS and the files inside them — it has no
// invoice rows and no finding rows to filter, and its three existing filters
// (source, direction, archived) all narrow that run list. A chip that filtered
// nothing would be a lie about what it does. So it reads as a COUNT that opens
// the findings themselves: "3 open findings", clicked, lists them. That is the
// one thing a user standing on this screen actually wants from the number.
// Recorded as a deviation in the spec body rather than silently reinterpreted.
//
// INFORMATION ONLY (BE Gap 492). This panel reads. It offers no action at all —
// acting on a finding happens in the chat bubble it was born in, and even there
// it changes nothing but the user's own bookkeeping.
//
// The chip renders NOTHING when there are no open findings, and nothing when the
// read fails: an empty or broken panel on a screen about ingestion history is
// noise, and `ENABLE_ATTACHMENT_INSIGHTS` being off is exactly the empty case.
// =============================================================================

"use client";

import { useEffect, useState } from "react";
import { ChevronDown, ChevronRight, Sparkles } from "lucide-react";
import { fetchOpenInsights, type Insight } from "@/lib/chatInsights";
import { formatCurrency, formatDate } from "@/lib/utils";

export default function OpenFindingsChip() {
  const [findings, setFindings] = useState<Insight[]>([]);
  const [open, setOpen] = useState(false);

  useEffect(() => {
    let cancelled = false;
    fetchOpenInsights()
      .then((rows) => {
        if (!cancelled) setFindings(rows);
      })
      .catch(() => {
        // Deliberately silent: the flag being off is indistinguishable from a
        // tenant with nothing open, and neither deserves an error on this page.
        if (!cancelled) setFindings([]);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  if (findings.length === 0) return null;

  return (
    <div data-testid="open-findings" className="rounded-lg border border-purple-800/40 bg-purple-950/10">
      <button
        type="button"
        data-testid="open-findings-chip"
        aria-expanded={open}
        onClick={() => setOpen((value) => !value)}
        className="
          flex w-full items-center gap-2 px-3 py-2 text-left
          text-[12px] font-medium text-purple-200
          hover:bg-purple-950/20 focus:outline-none focus:ring-1 focus:ring-blue-600
        "
      >
        <Sparkles className="h-3.5 w-3.5 shrink-0 text-purple-400" />
        {findings.length} open finding{findings.length === 1 ? "" : "s"}
        <span className="grow" />
        {open ? <ChevronDown className="h-3.5 w-3.5" /> : <ChevronRight className="h-3.5 w-3.5" />}
      </button>

      {open && (
        <ul data-testid="open-findings-list" className="divide-y divide-slate-700/30 px-3 pb-2">
          {findings.map((finding) => (
            <li
              key={finding.id}
              data-testid="open-finding-row"
              className="flex items-start justify-between gap-3 py-1.5"
            >
              <span className="text-[12px] leading-snug text-slate-300">
                {finding.title}
                <span className="ml-1.5 text-[10px] text-slate-500">
                  {formatDate(finding.created_at)}
                </span>
              </span>
              {finding.impact_amount != null && (
                <span className="shrink-0 tabular-nums text-[12px] font-semibold text-slate-100">
                  {formatCurrency(finding.impact_amount, finding.currency)}
                </span>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
