// =============================================================================
// FILE: components/chat/ReconciliationTable.tsx
// FEATURE: Feature 5 (chat) surface of BE Feature 26 amendment B10, task R10.
//
// REASON ADDED: an ADVISORY document -- a statement of account or a remittance
//   advice -- is answered by `list_reconcile` (B8), which produces a shape the
//   existing diff table cannot render. The diff table compares TWO documents
//   field by field; this compares one document's LIST OF REFERENCES against the
//   tenant's ledger, and its most valuable row is one the document does not
//   contain at all (an open invoice their statement omits).
//
// WHY ITS OWN COMPONENT rather than a mode of the diff table: the two answer
//   different questions and share no columns. `attachment_comparison` renders
//   field / document value / invoice value / delta; this renders one row per
//   referenced document with a five-way outcome, plus two blocks the diff table
//   has no concept of (deductions, and the reverse-direction findings).
//
// EVERY FIGURE IS THE BACKEND'S. `reconcile_referenced_documents()` computes in
//   Decimal; amounts arrive as Decimal-derived strings and are DISPLAYED AS
//   GIVEN. `Number()` appears nowhere in this file -- D5's exactness would
//   otherwise be undone in the last ten pixels, which is the specific mistake
//   H11 called out for the diff table.
// =============================================================================
"use client";

import { useState } from "react";

import type { AttachmentReconciliation, ReconciliationOutcome } from "@/types/chat";

/**
 * Copy and colour per outcome.
 *
 * `not_found` and `unreferenced_invoice` are the two that matter most and they
 * point in OPPOSITE directions -- one is on their document and missing from our
 * ledger, the other is in our ledger and missing from their document. Rendering
 * them in the same neutral grey would bury exactly the finding a user opened
 * the statement to get, so each has its own label and tone.
 */
const OUTCOME_META: Record<
  ReconciliationOutcome,
  { label: string; className: string }
> = {
  found_matching: {
    label: "Agrees",
    className: "bg-emerald-500/10 text-emerald-300 ring-emerald-500/30",
  },
  amount_mismatch: {
    label: "Amount differs",
    className: "bg-amber-500/10 text-amber-300 ring-amber-500/30",
  },
  status_mismatch: {
    label: "Status differs",
    className: "bg-amber-500/10 text-amber-300 ring-amber-500/30",
  },
  not_found: {
    label: "No matching invoice",
    className: "bg-rose-500/10 text-rose-300 ring-rose-500/30",
  },
};

function OutcomeChip({ outcome }: { outcome: ReconciliationOutcome }) {
  const meta = OUTCOME_META[outcome] ?? {
    label: outcome,
    className: "bg-slate-500/10 text-slate-300 ring-slate-500/30",
  };
  return (
    <span
      data-outcome={outcome}
      className={`inline-flex items-center rounded px-1.5 py-0.5 text-[11px] font-medium ring-1 ring-inset ${meta.className}`}
    >
      {meta.label}
    </span>
  );
}

/** An amount plus its currency, displayed verbatim. Never parsed, never rounded. */
function Amount({ value, currency }: { value?: string | number | null; currency?: string | null }) {
  if (value === null || value === undefined || value === "") {
    // "Not stated" and "zero" are different claims, and the backend is careful
    // to keep them apart (Gap 283). The UI must not collapse them.
    return <span className="text-slate-500">—</span>;
  }
  return (
    <span className="tabular-nums">
      {String(value)}
      {currency ? <span className="ml-1 text-slate-400">{currency}</span> : null}
    </span>
  );
}

export default function ReconciliationTable({
  reconciliation,
}: {
  reconciliation: AttachmentReconciliation;
}) {
  const [showAll, setShowAll] = useState(false);

  const references = reconciliation.references ?? [];
  const deductions = reconciliation.deductions ?? [];
  const unreferenced = reconciliation.unreferenced_invoices ?? [];

  // A statement can list dozens of invoices. The ones that AGREE are the least
  // interesting rows on the page, so they collapse by default -- and the count
  // is still shown, because "12 agree" is itself an answer.
  const interesting = references.filter((r) => r.outcome !== "found_matching");
  const agreeing = references.filter((r) => r.outcome === "found_matching");
  const visible = showAll ? references : interesting;

  return (
    <div id="chat-reconciliation" className="mt-3 space-y-3 text-xs">
      <div className="overflow-x-auto rounded-lg border border-slate-700/60">
        <table className="w-full min-w-[34rem] border-collapse">
          <thead>
            <tr className="bg-slate-800/60 text-left text-[11px] uppercase tracking-wide text-slate-400">
              <th className="px-3 py-2 font-medium">Reference</th>
              <th className="px-3 py-2 font-medium">On their document</th>
              <th className="px-3 py-2 font-medium">In your records</th>
              <th className="px-3 py-2 font-medium">Difference</th>
              <th className="px-3 py-2 font-medium">Outcome</th>
            </tr>
          </thead>
          <tbody>
            {visible.map((row, i) => (
              <tr
                key={`${row.doc_number ?? "ref"}-${i}`}
                data-reference-outcome={row.outcome}
                className="border-t border-slate-700/40"
              >
                <td className="px-3 py-2 font-medium text-slate-200">
                  {row.doc_number ?? <span className="text-slate-500">—</span>}
                </td>
                <td className="px-3 py-2">
                  <Amount value={row.stated_amount} />
                  {row.stated_status ? (
                    <span className="ml-1 text-slate-400">({row.stated_status})</span>
                  ) : null}
                </td>
                <td className="px-3 py-2">
                  <Amount value={row.invoice_amount} />
                  {row.invoice_status ? (
                    <span className="ml-1 text-slate-400">({row.invoice_status})</span>
                  ) : null}
                </td>
                <td className="px-3 py-2">
                  <Amount value={row.delta} />
                </td>
                <td className="px-3 py-2">
                  <OutcomeChip outcome={row.outcome} />
                </td>
              </tr>
            ))}
            {visible.length === 0 && (
              <tr className="border-t border-slate-700/40">
                <td colSpan={5} className="px-3 py-2 text-slate-400">
                  Every reference on that document agrees with your records.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      {agreeing.length > 0 && (
        <button
          type="button"
          onClick={() => setShowAll((v) => !v)}
          className="text-[11px] text-blue-400 hover:text-blue-300"
        >
          {showAll
            ? `Hide the ${agreeing.length} that agree`
            : `Show ${agreeing.length} that agree`}
        </button>
      )}

      {deductions.length > 0 && (
        <div id="chat-reconciliation-deductions">
          <div className="mb-1 font-medium text-slate-300">Deductions</div>
          {/*
            Listed individually and never summed. One unexplained gap is a
            support ticket; "TDS 6,000 + chargeback 2,000" is an answer -- which
            is why the backend refuses to net them and the UI must not either.
          */}
          <ul className="space-y-1">
            {deductions.map((d, i) => (
              <li key={`${d.kind ?? "deduction"}-${i}`} className="flex gap-2 text-slate-300">
                <span className="font-medium">{d.kind ?? "Other"}</span>
                <Amount value={d.amount} currency={d.currency} />
                {d.reference ? <span className="text-slate-500">({d.reference})</span> : null}
              </li>
            ))}
          </ul>
        </div>
      )}

      {unreferenced.length > 0 && (
        <div id="chat-reconciliation-unreferenced">
          {/*
            THE REVERSE DIRECTION, in its own block on purpose. Every other row
            on this page came from their document; these came from ours and are
            absent from theirs. Folding them into the table above would file the
            most actionable finding under a heading that does not describe it.
          */}
          <div className="mb-1 font-medium text-slate-300">
            Open invoices not on this document
          </div>
          <ul className="space-y-1">
            {unreferenced.map((inv) => (
              <li key={inv.invoice_id} className="flex gap-2 text-slate-300">
                <span className="font-medium">{inv.invoice_number}</span>
                <Amount value={inv.grand_total} />
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
