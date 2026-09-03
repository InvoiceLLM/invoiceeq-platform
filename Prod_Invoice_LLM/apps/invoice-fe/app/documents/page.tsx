"use client";
// =============================================================================
// FILE: app/documents/page.tsx
// FEATURE: FE surface of BE Feature 27 E10 / G14 — task R5(c), FE Gap 378.
//
// THE GAP THIS CLOSES, and why it is a rollout gate rather than a nicety.
//   E10 routes every non-INVOICE-family document to the `documents` table and
//   DELETES the placeholder `invoice` row in the same transaction. So the moment
//   classification succeeds, a delivery challan disappears from the ingestion
//   status table -- correctly, it is not an invoice -- and until this page
//   existed, nothing else listed it. A user uploaded a document and watched it
//   vanish.
//
//   That is precisely why §2A/N1 says ENABLE_GENERIC_EXTRACTION must not be
//   turned on in any deployment a user can see until this exists. `GET
//   /documents` (G14) shipped with Gap 381 and has had no consumer since.
//
// WHAT THIS DELIBERATELY IS NOT. It is a LIST, not an auditor console. A
//   `Document` has no audit lifecycle -- its status vocabulary is
//   EXTRACTED / EXTRACT_FAILED, never approved/sent/paid -- so there is no
//   review action to offer and none is offered. Inventing one would imply a
//   workflow that does not exist.
// =============================================================================

import { useCallback, useEffect, useState } from "react";

import { docTypeBadgeLabel } from "@/lib/chatAttachments";

interface DocumentRow {
  id: string;
  file_path: string;
  doc_type?: string | null;
  doc_type_evidence?: string | null;
  party_name?: string | null;
  counterparty_name?: string | null;
  doc_number?: string | null;
  po_number?: string | null;
  doc_date?: string | null;
  currency?: string | null;
  grand_total?: number | string | null;
  status?: string | null;
  created_at?: string | null;
}

/** Amounts are displayed as the backend gave them. A document in this table
 *  legitimately has NO total at all -- a delivery note prints quantities and no
 *  money, a rate card has no grand total -- and "not stated" must not render as
 *  a zero, which is a different and much stronger claim (Gap 283). */
function Amount({ value, currency }: { value?: number | string | null; currency?: string | null }) {
  if (value === null || value === undefined || value === "") {
    return <span className="text-slate-500">—</span>;
  }
  return (
    <span className="tabular-nums">
      {String(value)}
      {currency ? <span className="ml-1 text-slate-400">{currency}</span> : null}
    </span>
  );
}

export default function DocumentsPage() {
  const [rows, setRows] = useState<DocumentRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [docType, setDocType] = useState<string>("");

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const qs = docType ? `?doc_type=${encodeURIComponent(docType)}` : "";
      const res = await fetch(`/api/documents${qs}`, { cache: "no-store" });
      if (!res.ok) {
        // The backend's own detail, surfaced rather than replaced with a generic
        // message -- a 403 from a missing scope and a 500 need different actions
        // from the reader.
        const body = await res.json().catch(() => ({}));
        throw new Error(body?.detail || `Request failed (${res.status})`);
      }
      setRows(await res.json());
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not load documents.");
    } finally {
      setLoading(false);
    }
  }, [docType]);

  useEffect(() => {
    void load();
  }, [load]);

  return (
    <div id="documents-page" className="space-y-4">
      <header className="flex items-center justify-between gap-4">
        <div>
          <h1 className="text-lg font-semibold text-slate-100">Documents</h1>
          <p className="text-xs text-slate-400">
            Delivery notes, purchase orders, contracts, statements and other
            non-invoice documents. These are deliberately kept out of the invoice
            ledger so they never enter spend, dashboards or billing.
          </p>
        </div>
        <select
          id="documents-doc-type-filter"
          value={docType}
          onChange={(e) => setDocType(e.target.value)}
          className="rounded border border-slate-700 bg-slate-900 px-2 py-1 text-xs text-slate-200"
        >
          <option value="">All types</option>
          {[
            "QUOTATION", "PROFORMA_INVOICE", "PURCHASE_ORDER", "ORDER_CONFIRMATION",
            "CONTRACT", "DELIVERY_NOTE", "GRN", "RECEIPT",
            "REMITTANCE_ADVICE", "STATEMENT_OF_ACCOUNT", "OTHER",
          ].map((t) => (
            <option key={t} value={t}>
              {docTypeBadgeLabel(t)}
            </option>
          ))}
        </select>
      </header>

      {error && (
        <div className="rounded border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-xs text-rose-300">
          {error}
        </div>
      )}

      <div className="overflow-x-auto rounded-lg border border-slate-700/60">
        <table className="w-full min-w-[46rem] border-collapse text-xs">
          <thead>
            <tr className="bg-slate-800/60 text-left text-[11px] uppercase tracking-wide text-slate-400">
              <th className="px-3 py-2 font-medium">Type</th>
              <th className="px-3 py-2 font-medium">Number</th>
              <th className="px-3 py-2 font-medium">Party</th>
              <th className="px-3 py-2 font-medium">Date</th>
              <th className="px-3 py-2 font-medium">Total</th>
              <th className="px-3 py-2 font-medium">Status</th>
            </tr>
          </thead>
          <tbody>
            {loading && (
              <tr>
                <td colSpan={6} className="px-3 py-4 text-slate-400">
                  Loading…
                </td>
              </tr>
            )}
            {!loading && rows.length === 0 && (
              <tr>
                <td colSpan={6} className="px-3 py-4 text-slate-400">
                  {/*
                    Empty is the EXPECTED state today: ENABLE_GENERIC_EXTRACTION
                    defaults False, so nothing is classified and nothing is
                    routed here. Saying so beats an unexplained blank table that
                    reads like a failure.
                  */}
                  No non-invoice documents yet. Documents appear here once
                  generic extraction is enabled and a non-invoice document is
                  uploaded.
                </td>
              </tr>
            )}
            {rows.map((row) => (
              <tr key={row.id} data-doc-type={row.doc_type ?? ""} className="border-t border-slate-700/40">
                <td className="px-3 py-2">
                  <span className="rounded bg-slate-700/60 px-1.5 py-0.5 text-[11px] text-slate-200">
                    {docTypeBadgeLabel(row.doc_type)}
                  </span>
                </td>
                <td className="px-3 py-2 text-slate-200">
                  {row.doc_number ?? <span className="text-slate-500">—</span>}
                  {row.po_number ? (
                    <span className="ml-2 text-slate-500">PO {row.po_number}</span>
                  ) : null}
                </td>
                <td className="px-3 py-2 text-slate-300">
                  {row.party_name ?? <span className="text-slate-500">—</span>}
                </td>
                <td className="px-3 py-2 text-slate-300">
                  {row.doc_date ?? <span className="text-slate-500">—</span>}
                </td>
                <td className="px-3 py-2">
                  <Amount value={row.grand_total} currency={row.currency} />
                </td>
                <td className="px-3 py-2">
                  <span
                    data-status={row.status ?? ""}
                    className={
                      row.status === "EXTRACT_FAILED"
                        ? "text-rose-300"
                        : "text-emerald-300"
                    }
                  >
                    {row.status ?? "—"}
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
