// =============================================================================
// FILE: components/atlas/ReconPanel.tsx
// FEATURE: FE Feature 23 task 6 (spec §6) — attach a vendor statement, and the
//          four groups that come back. Backed by BE task 34.4 (`reconcile()`)
//          through `POST /api/atlas/recon` (BE §15.2).
//
// THE FOUR GROUPS ARE PRINTED FROM THE SERVER'S OWN ROWS. Each row arrives with
// its amount already rendered (`amount_rendered`), and this file does no
// arithmetic of any kind — same rule, same grep-shaped test, as
// `AtlasLine.tsx`. `ReconRow` carries no numeric `value` at all, so there is
// nothing here to add up even by accident.
//
// THE AFFORDANCE APPEARS ONLY WHEN THE SERVER SENDS IT (spec §6). This panel is
// opened by a line whose `action.kind` is one of `ATTACH_ACTION_KINDS` —
// `attach_witness_document` or `open_invoice_against_statement`, both emitted by
// `services/atlas_doubt.py` and `services/atlas_recon.py`. The FE never decides
// a document is needed; that judgement is BE §3.3's decision rule.
//
// WHY A DOCUMENT PICKER AND NOT AN UPLOAD: the statement is compared as
// EXTRACTED rows, so it has to have been through ingestion already. `GET
// /documents` is the list of exactly those rows (Feature 27 G14). Uploading
// here would mean comparing a file nothing had read yet.
// =============================================================================

"use client";

import { useEffect, useState } from "react";

import AtlasLine from "@/components/atlas/AtlasLine";
import {
  RECON_GROUP_ORDER,
  reconcileStatement,
  type AtlasReconResponse,
  type AtlasReconRow,
  type AtlasRecommendation,
} from "@/lib/atlas";
import { apiClient } from "@/lib/apiClient";

/** The shape `GET /documents` returns, narrowed to what the picker needs. */
interface PickableDocument {
  id: string;
  doc_type?: string | null;
  counterparty_name?: string | null;
  party_name?: string | null;
  file_path?: string | null;
}

export interface ReconPanelProps {
  /** The line that asked for the document, when the panel was opened by one. */
  openedBy?: AtlasRecommendation | null;
}

function documentLabel(doc: PickableDocument): string {
  const who = doc.counterparty_name ?? doc.party_name ?? "unnamed party";
  const name = (doc.file_path ?? "").split("\\").pop()?.split("/").pop() ?? doc.id;
  return `${who} — ${name}`; // hardcode-ok: a party name and a file name, neither of them a figure — no number is formatted here
}

/** A stable React key for a recon row. Never rendered, so it prints no figure. */
function rowKey(group: string, row: AtlasReconRow, index: number): string {
  return [group, row.invoice_id ?? row.invoice_number ?? String(index)].join(":");
}

export default function ReconPanel({ openedBy }: ReconPanelProps) {
  const [documents, setDocuments] = useState<PickableDocument[]>([]);
  const [selected, setSelected] = useState("");
  const [result, setResult] = useState<AtlasReconResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let cancelled = false;
    apiClient
      .get<PickableDocument[]>("/documents")
      .then(({ data }) => {
        if (!cancelled) setDocuments(Array.isArray(data) ? data : []);
      })
      .catch(() => {
        // A tenant with no documents and a documents read that failed look the
        // same from here; neither is an error worth shouting about on a screen
        // about work. The compare button then has nothing to select, which is
        // the honest state.
        if (!cancelled) setDocuments([]);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  async function compare() {
    if (!selected) return;
    setBusy(true);
    setError(null);
    setResult(null);
    try {
      setResult(await reconcileStatement(selected));
    } catch (err: any) {
      // The backend's refusals are sentences meant for a user (BE §15.3) —
      // "tell me whose statement it is", "no row carried an amount I could
      // read". Shown as sent, never replaced with a generic failure.
      setError(
        err?.response?.data?.detail ??
          "That statement could not be compared, and the backend did not say why."
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <section
      data-testid="atlas-recon"
      className="rounded-lg border border-slate-700/60 bg-slate-900/30 px-4 py-3"
    >
      <h2 className="text-[13px] font-medium text-slate-200">
        Compare a vendor statement
      </h2>
      {openedBy && (
        <p data-testid="atlas-recon-reason" className="mt-1 text-[12px] text-slate-400">
          {openedBy.why.text}
        </p>
      )}

      <div className="mt-2 flex flex-wrap items-center gap-2">
        <select
          data-testid="atlas-recon-document"
          value={selected}
          onChange={(event) => setSelected(event.target.value)}
          className="rounded border border-slate-700 bg-slate-950 px-2 py-1 text-[12px] text-slate-200"
        >
          <option value="">Choose a statement…</option>
          {documents.map((doc) => (
            <option key={doc.id} value={doc.id}>
              {documentLabel(doc)}
            </option>
          ))}
        </select>
        <button
          type="button"
          data-testid="atlas-recon-compare"
          disabled={!selected || busy}
          onClick={compare}
          className="rounded border border-blue-700/60 bg-blue-950/30 px-2.5 py-1 text-[12px] text-blue-200 disabled:cursor-not-allowed disabled:opacity-50"
        >
          {busy ? "Comparing…" : "Attach and compare"}
        </button>
      </div>

      {error && (
        <p data-testid="atlas-recon-error" className="mt-2 text-[12px] text-amber-300">
          {error}
        </p>
      )}

      {result && (
        <div data-testid="atlas-recon-result" className="mt-3">
          <p className="text-[12px] text-slate-400">
            <span data-testid="atlas-recon-vendor">{result.vendor_name}</span>
            <span className="mx-1 text-slate-600">·</span>
            <span>{result.currency}</span>
            {result.unreadable_rows > 0 && (
              <span data-testid="atlas-recon-unreadable" className="ml-2 text-amber-300">
                Rows I could not read: {result.unreadable_rows}
              </span>
            )}
          </p>

          {RECON_GROUP_ORDER.map((group) => {
            const rows = result.groups[group.key];
            const groupTestId = ["recon-group", group.key].join("-"); // hardcode-ok: a test id built from a bucket name, not a figure — nothing numeric is formatted here
            return (
              <div key={group.key} data-testid={groupTestId} className="mt-2">
                <h3 className="text-[11px] uppercase tracking-wide text-slate-500">
                  {group.title}
                  <span className="ml-1 text-slate-400">{rows.length}</span>
                </h3>
                <ul className="mt-1 space-y-0.5">
                  {rows.map((row, index) => (
                    <li
                      key={rowKey(group.key, row, index)}
                      data-testid="recon-row"
                      className="flex flex-wrap items-center gap-2 text-[12px] text-slate-300"
                    >
                      <span className="text-slate-400">
                        {row.invoice_number ?? "no invoice number on this row"}
                      </span>
                      {row.theirs_rendered ? (
                        <>
                          <span data-testid="recon-theirs">They: {row.theirs_rendered}</span>
                          <span data-testid="recon-ours">We: {row.ours_rendered}</span>
                          <span data-testid="recon-difference" className="text-amber-300">
                            Difference: {row.difference_rendered}
                          </span>
                        </>
                      ) : (
                        <span data-testid="recon-amount">{row.amount_rendered}</span>
                      )}
                    </li>
                  ))}
                </ul>
              </div>
            );
          })}

          {result.lines.length > 0 && (
            <ul data-testid="atlas-recon-lines" className="mt-3 space-y-2">
              {result.lines.map((line) => (
                <AtlasLine key={line.id} line={line} />
              ))}
            </ul>
          )}
        </div>
      )}
    </section>
  );
}
