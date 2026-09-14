"use client";

import Link from "next/link";
import type { ChatProvenanceEntry } from "@/types/chat";

/**
 * FE Gap 470 — which record and which column each figure in the answer came from.
 * One compact line of pills in the citation-pill style; a pill with an invoice id
 * links to that invoice's audit view, the same destination CitationPill uses.
 * Rendered on the key's presence alone.
 */
export default function ProvenanceLine({ entries }: { entries: ChatProvenanceEntry[] }) {
  const rows = entries.filter((e) => e && (e.invoice_id || e.invoice_number || e.column));
  if (rows.length === 0) return null;
  return (
    <div data-testid="chat-provenance" className="mt-1 flex flex-wrap items-center gap-1.5 px-1">
      <span className="text-[10px] uppercase tracking-wide text-slate-500">From</span>
      {rows.map((e, idx) => {
        const label = [e.invoice_number || (e.invoice_id ? e.invoice_id.slice(0, 8) : null), e.column]
          .filter(Boolean)
          .join(" · ");
        const pill = (
          <span
            data-testid="chat-provenance-pill"
            title={e.claim || undefined}
            className="inline-flex items-center rounded-full border border-slate-700/60 bg-slate-800/40 px-1.5 py-0.5 text-[10px] text-slate-300 hover:bg-slate-700/50"
          >
            {label}
          </span>
        );
        return e.invoice_id ? (
          <Link key={`${e.invoice_id}-${idx}`} href={`/audit/${e.invoice_id}`}>{pill}</Link>
        ) : (
          <span key={`p-${idx}`}>{pill}</span>
        );
      })}
    </div>
  );
}
