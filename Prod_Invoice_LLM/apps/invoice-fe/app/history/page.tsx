"use client";
// =============================================================================
// FILE: app/history/page.tsx
// FEATURE: FE Gap 464 — the durable ingestion History screen.
//
// WHAT IT REPLACES. `app/documents/page.tsx` (Feature 27 task R5(c)) was a
//   separate sidebar page listing only the `documents` table. It answered
//   "where did my delivery note go?" and nothing else: an upload that failed,
//   an inbound email that was rejected, and a connector import had no durable
//   surface anywhere in the product. The Ingest status table is client state
//   that clears on navigation, and a rejected inbound mail was visible only in
//   the Admin console — the wrong audience entirely.
//
//   The founder's decision (2026-09-05) was ONE History screen, a net-zero
//   sidebar swap: "Documents" out, "History" in, and the Documents page
//   deleted. This is that screen.
//
// WHAT THIS PAGE IS NOT. It is not an auditor console and offers no review
//   action. A run is a historical fact; acting on an invoice happens on the
//   Audit Queue, where the consequence is visible. The only action here is
//   Archive, which hides a log entry and deletes nothing.
//
// The screen is a thin shell on purpose — every behaviour lives in
//   `components/ingestion/IngestionHistoryTable.tsx`, mirroring how /ingestion
//   hosts `AutopilotHistoryTable`.
// =============================================================================

import IngestionHistoryTable from "@/components/ingestion/IngestionHistoryTable";

export default function HistoryPage() {
  return (
    <div id="history-page" className="space-y-4">
      <header>
        <h1 className="text-lg font-semibold text-slate-100">History</h1>
        <p className="text-xs text-slate-400">
          Every file this workspace has ingested — uploads, inbound email,
          connector imports and Autopilot runs — and what happened to each one.
          Files that turned out not to be invoices are listed here as explained
          entries rather than disappearing.
        </p>
      </header>

      <IngestionHistoryTable />
    </div>
  );
}
