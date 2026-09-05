"use client";

/**
 * FE Gap 464 — the durable ingestion History log.
 *
 * WHAT THIS REPLACES AND WHY. Feature 27 decision E10 routes a classified
 * non-invoice to the `documents` table and DELETES the placeholder `invoice`
 * row in the same transaction, so a user uploaded a delivery note and watched
 * it vanish from the Ingest status table with no message. The surface built for
 * that (`app/documents/page.tsx`, task R5(c)) was a separate sidebar page
 * listing only `documents`; the Ingest status table is client state that clears
 * on navigation. Email-in and connector imports had no home at all. This is the
 * one durable place where every ingestion run is visible, whatever door it came
 * through and whatever it turned out to be.
 *
 * IT IS A LOG, NOT A DATA TABLE (founder, 2026-09-05). One lightweight row per
 * run — when, how it arrived, how many files, what happened. Nothing heavy is
 * fetched to render the list. Expanding a row is the ONLY thing that fetches
 * the full records (extracted fields, alerts, line items, doc attributes), from
 * `/api/ingestion-history/{runId}/files`. Modelled closely on
 * `AutopilotHistoryTable.tsx`, which already does expand, optimistic dismiss,
 * clear-all and inline action errors.
 *
 * BOTH OUTCOMES ARE ROWS. A non-invoice is a normal, explained line — never a
 * disappearance. `outcome_label` ("Loaded — VERIFIED", "Not loaded — Delivery
 * note", "Rejected — no invoice content") is computed by the BACKEND, in
 * deterministic code, and rendered verbatim here. This component never decides
 * whether a file loaded.
 *
 * ARCHIVE IS THE ONLY WORD. Not "hide", not "delete". Archiving writes
 * `archived_at` on the log row and changes nothing about the invoice; real
 * invoice deletion stays on the Audit Queue where the consequence is visible.
 * Two words for one behaviour is what makes users think one of them removes the
 * invoice.
 *
 * Backend contract (BE Gap 464):
 *   GET  /api/ingestion-history?page=&page_size=&trigger=&flow_direction=&archived=
 *          -> { items: IngestionRun[], total, page, page_size }
 *   GET  /api/ingestion-history/{runId}/files  -> { items: IngestionRunFile[] }
 *   POST /api/ingestion-history/{runId}/archive | /unarchive -> { archived }
 *   POST /api/ingestion-history/archive-all                  -> { archived }
 */

import React, { useCallback, useEffect, useState } from "react";
import {
  AlertCircle,
  Archive,
  ArchiveRestore,
  CheckCircle,
  ChevronRight,
  Clock,
  FileQuestion,
  Loader2,
  RefreshCw,
} from "lucide-react";

import { apiClient } from "../../lib/apiClient";

// ---------------------------------------------------------------------------
// Types — mirror BE Gap 464's response shapes
// ---------------------------------------------------------------------------

type RunStatus =
  | "LOADED"
  | "PARTIAL"
  | "NOT_LOADED"
  | "REJECTED"
  | "IN_PROGRESS"
  | "EMPTY";

type FileOutcome = "LOADED" | "NOT_LOADED" | "REJECTED" | "IN_PROGRESS";

export type IngestionTrigger = "manual" | "email" | "connector" | "autopilot";

interface IngestionRun {
  run_id: string;
  source: IngestionTrigger;
  flow_direction: "INBOUND" | "OUTBOUND" | null;
  started_at: string;
  file_count: number;
  loaded: number;
  not_loaded: number;
  rejected: number;
  in_progress: number;
  status: RunStatus;
  summary: string;
  archived_at: string | null;
}

interface IngestionRunFile {
  id: string;
  kind: "invoice" | "document" | "autopilot_file" | "rejected_email";
  file_name: string;
  outcome: FileOutcome;
  outcome_label: string;
  status: string | null;
  doc_type: string | null;
  created_at: string | null;
  record: Record<string, unknown>;
}

interface IngestionHistoryResponse {
  items: IngestionRun[];
  total: number;
  page: number;
  page_size: number;
}

interface IngestionRunFilesResponse {
  items: IngestionRunFile[];
}

// ---------------------------------------------------------------------------
// Presentation helpers
// ---------------------------------------------------------------------------

const RUN_STATUS_STYLE: Record<RunStatus, { label: string; className: string }> = {
  LOADED: {
    label: "Loaded",
    className: "bg-emerald-500/10 border-emerald-500/20 text-emerald-400",
  },
  PARTIAL: {
    label: "Partial",
    className: "bg-amber-500/10 border-amber-500/20 text-amber-400",
  },
  // Deliberately slate, not red. A delivery note that did not load is the
  // system working correctly, and colouring it as a failure is the thing that
  // makes a user open a support ticket about a document that is perfectly fine.
  NOT_LOADED: {
    label: "Not loaded",
    className: "bg-sky-500/10 border-sky-500/20 text-sky-300",
  },
  REJECTED: {
    label: "Rejected",
    className: "bg-rose-500/10 border-rose-500/20 text-rose-400",
  },
  IN_PROGRESS: {
    label: "In progress",
    className: "bg-slate-500/10 border-slate-500/20 text-slate-300",
  },
  EMPTY: {
    label: "Nothing to do",
    className: "bg-slate-500/10 border-slate-500/20 text-slate-400",
  },
};

const OUTCOME_STYLE: Record<FileOutcome, string> = {
  LOADED: "bg-emerald-500/10 border-emerald-500/20 text-emerald-400",
  NOT_LOADED: "bg-sky-500/10 border-sky-500/20 text-sky-300",
  REJECTED: "bg-rose-500/10 border-rose-500/20 text-rose-400",
  IN_PROGRESS: "bg-slate-500/10 border-slate-500/20 text-slate-300",
};

const SOURCE_LABEL: Record<IngestionTrigger, string> = {
  manual: "Upload",
  email: "Email",
  connector: "Connector",
  autopilot: "Autopilot",
};

function RunStatusChip({ status }: { status: RunStatus }) {
  const style = RUN_STATUS_STYLE[status] ?? RUN_STATUS_STYLE.IN_PROGRESS;
  return (
    <span
      data-run-status={status}
      className={`inline-flex items-center px-2 py-0.5 rounded-full border text-[10px] font-semibold uppercase tracking-wider whitespace-nowrap ${style.className}`}
    >
      {style.label}
    </span>
  );
}

/** The per-file chip. Its TEXT is the backend's `outcome_label`, verbatim. */
function OutcomeBadge({ file }: { file: IngestionRunFile }) {
  return (
    <span
      data-outcome={file.outcome}
      className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full border text-[10px] font-semibold tracking-wide whitespace-nowrap ${
        OUTCOME_STYLE[file.outcome] ?? OUTCOME_STYLE.IN_PROGRESS
      }`}
    >
      {file.outcome === "LOADED" && <CheckCircle className="w-3 h-3" />}
      {file.outcome === "NOT_LOADED" && <FileQuestion className="w-3 h-3" />}
      {file.outcome === "REJECTED" && <AlertCircle className="w-3 h-3" />}
      {file.outcome === "IN_PROGRESS" && <Clock className="w-3 h-3" />}
      {file.outcome_label}
    </span>
  );
}

/** "Today 09:12" / "Yesterday 17:40" / "12 Aug 09:12" — same as Sync History. */
function formatRunTime(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  const time = d.toLocaleTimeString(undefined, {
    hour: "2-digit",
    minute: "2-digit",
  });
  const now = new Date();
  const startOfToday = new Date(
    now.getFullYear(),
    now.getMonth(),
    now.getDate()
  ).getTime();
  const ts = d.getTime();
  if (ts >= startOfToday) return `Today ${time}`;
  if (ts >= startOfToday - 86_400_000) return `Yesterday ${time}`;
  return `${d.toLocaleDateString(undefined, { day: "numeric", month: "short" })} ${time}`;
}

function directionLabel(direction: IngestionRun["flow_direction"]): string | null {
  if (direction === "INBOUND") return "Receiving";
  if (direction === "OUTBOUND") return "Sending";
  return null;
}

/**
 * A handful of the most useful fields off an expanded record, chosen per kind.
 *
 * NOT a full field dump: the point of the expansion is "what is this document
 * and what did we read off it", and a 40-row property list answers that worse
 * than six labelled values. The whole record is on the wire either way, so a
 * future addition here is a rendering change, not an API change.
 */
function recordSummary(file: IngestionRunFile): Array<[string, string]> {
  const r = file.record ?? {};
  const text = (key: string): string | null => {
    const value = r[key];
    if (value === null || value === undefined || value === "") return null;
    return String(value);
  };
  const pairs: Array<[string, string | null]> =
    file.kind === "invoice"
      ? [
          ["Vendor", text("vendor_name")],
          ["Invoice no.", text("invoice_number")],
          ["Date", text("invoice_date")],
          ["Total", text("grand_total")],
          ["Currency", text("currency")],
          ["PO", text("po_number")],
        ]
      : file.kind === "document"
      ? [
          ["Evidence", text("doc_type_evidence")],
          ["Issued by", text("party_name")],
          ["Addressed to", text("counterparty_name")],
          ["Number", text("doc_number")],
          ["Date", text("doc_date")],
          ["Total", text("grand_total")],
        ]
      : file.kind === "rejected_email"
      ? [
          ["From", text("from_email")],
          ["To", text("to_email")],
          ["Reason", text("reason")],
          ["Detail", text("detail")],
        ]
      : [
          ["Source", text("source_type")],
          ["File id", text("source_file_id")],
          ["Error", text("error_detail")],
        ];
  return pairs.filter((p): p is [string, string] => p[1] !== null);
}

/** Line items / alerts counts, shown only when non-zero. */
function recordCounts(file: IngestionRunFile): string | null {
  const r = file.record ?? {};
  const items = Array.isArray(r.items) ? r.items.length : 0;
  const alerts = Array.isArray(r.sa_alerts) ? r.sa_alerts.length : 0;
  const attributes =
    r.doc_attributes && typeof r.doc_attributes === "object"
      ? Object.keys(r.doc_attributes as object).length
      : 0;
  const parts: string[] = [];
  if (items) parts.push(`${items} line item${items === 1 ? "" : "s"}`);
  if (alerts) parts.push(`${alerts} alert${alerts === 1 ? "" : "s"}`);
  if (attributes) parts.push(`${attributes} attribute${attributes === 1 ? "" : "s"}`);
  return parts.length ? parts.join(" · ") : null;
}

// ---------------------------------------------------------------------------
// Run detail — lazily fetched per-file list
// ---------------------------------------------------------------------------

interface RunFilesState {
  loading: boolean;
  error: string | null;
  items: IngestionRunFile[] | null;
}

function RunFileList({ state }: { state: RunFilesState | undefined }) {
  if (!state || state.loading) {
    return (
      <div className="flex items-center gap-2 px-4 py-3 text-[11px] text-slate-500">
        <Loader2 className="w-3 h-3 animate-spin" />
        Loading files…
      </div>
    );
  }
  if (state.error) {
    return (
      <div
        data-testid="run-files-error"
        className="flex items-center gap-2 px-4 py-3 text-[11px] text-rose-400"
      >
        <AlertCircle className="w-3 h-3 flex-shrink-0" />
        {state.error}
      </div>
    );
  }
  if (!state.items || state.items.length === 0) {
    return (
      <div className="px-4 py-3 text-[11px] text-slate-500">
        No files recorded for this run.
      </div>
    );
  }
  return (
    <div className="divide-y divide-[#222D3D]/50">
      {state.items.map((file) => {
        const pairs = recordSummary(file);
        const counts = recordCounts(file);
        return (
          <div key={file.id} data-testid="run-file" className="px-4 py-3">
            <div className="flex items-start justify-between gap-3">
              <p
                className="min-w-0 flex-1 truncate text-xs text-slate-300"
                title={file.file_name}
              >
                {file.file_name}
              </p>
              <OutcomeBadge file={file} />
            </div>
            {pairs.length > 0 && (
              <dl className="mt-2 grid grid-cols-2 gap-x-4 gap-y-1 sm:grid-cols-3">
                {pairs.map(([label, value]) => (
                  <div key={label} className="min-w-0">
                    <dt className="text-[9px] font-semibold uppercase tracking-wider text-slate-500">
                      {label}
                    </dt>
                    <dd className="truncate text-[11px] text-slate-300" title={value}>
                      {value}
                    </dd>
                  </div>
                ))}
              </dl>
            )}
            {counts && (
              <p className="mt-1.5 text-[10px] text-slate-500">{counts}</p>
            )}
          </div>
        );
      })}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Filters
// ---------------------------------------------------------------------------

const TRIGGER_FILTERS: Array<{ value: IngestionTrigger | ""; label: string }> = [
  { value: "", label: "All sources" },
  { value: "manual", label: "Manual" },
  { value: "email", label: "Email" },
  { value: "connector", label: "Connector" },
  { value: "autopilot", label: "Autopilot" },
];

const DIRECTION_FILTERS: Array<{ value: "" | "INBOUND" | "OUTBOUND"; label: string }> = [
  { value: "", label: "All" },
  { value: "INBOUND", label: "Receiving" },
  { value: "OUTBOUND", label: "Sending" },
];

function FilterChip({
  active,
  onClick,
  children,
  testId,
}: {
  active: boolean;
  onClick: () => void;
  children: React.ReactNode;
  testId: string;
}) {
  return (
    <button
      type="button"
      data-testid={testId}
      data-active={active}
      onClick={onClick}
      className={`rounded-full border px-2.5 py-1 text-[11px] transition-colors ${
        active
          ? "border-sky-500/40 bg-sky-500/10 text-sky-300"
          : "border-[#222D3D] text-slate-400 hover:border-slate-500 hover:text-white"
      }`}
    >
      {children}
    </button>
  );
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

const PAGE_SIZE = 25;

export default function IngestionHistoryTable() {
  const [data, setData] = useState<IngestionHistoryResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [page, setPage] = useState(1);
  const [trigger, setTrigger] = useState<IngestionTrigger | "">("");
  const [direction, setDirection] = useState<"" | "INBOUND" | "OUTBOUND">("");
  const [archivedView, setArchivedView] = useState(false);
  const [expanded, setExpanded] = useState<string | null>(null);
  const [filesByRun, setFilesByRun] = useState<Record<string, RunFilesState>>({});
  // Action state. `actionError` renders inline in the header rather than
  // replacing the list, so a failed archive never hides the history the user is
  // looking at (same rule as AutopilotHistoryTable).
  const [busyRun, setBusyRun] = useState<string | null>(null);
  const [confirmingArchiveAll, setConfirmingArchiveAll] = useState(false);
  const [archivingAll, setArchivingAll] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);

  const fetchHistory = useCallback(async () => {
    try {
      setError(null);
      const params = new URLSearchParams({
        page: String(page),
        page_size: String(PAGE_SIZE),
      });
      if (trigger) params.set("trigger", trigger);
      if (direction) params.set("flow_direction", direction);
      if (archivedView) params.set("archived", "true");
      const res = await apiClient.get<IngestionHistoryResponse>(
        `/ingestion-history?${params.toString()}`
      );
      setData(res.data);
    } catch (err: any) {
      setError(
        err?.response?.data?.detail || "Failed to load ingestion history."
      );
    } finally {
      setLoading(false);
    }
  }, [page, trigger, direction, archivedView]);

  /** Lazily loads one run's files; a cached run (or one in flight) is a no-op. */
  const loadRunFiles = useCallback(async (runId: string) => {
    let alreadyLoaded = false;
    setFilesByRun((prev) => {
      if (prev[runId]) {
        alreadyLoaded = true;
        return prev;
      }
      return { ...prev, [runId]: { loading: true, error: null, items: null } };
    });
    if (alreadyLoaded) return;
    try {
      const res = await apiClient.get<IngestionRunFilesResponse>(
        `/ingestion-history/${encodeURIComponent(runId)}/files`
      );
      setFilesByRun((prev) => ({
        ...prev,
        [runId]: { loading: false, error: null, items: res.data.items ?? [] },
      }));
    } catch (err: any) {
      setFilesByRun((prev) => ({
        ...prev,
        [runId]: {
          loading: false,
          error:
            err?.response?.data?.detail || "Failed to load files for this run.",
          items: null,
        },
      }));
    }
  }, []);

  const toggleRun = useCallback(
    (runId: string) => {
      setExpanded((cur) => (cur === runId ? null : runId));
      void loadRunFiles(runId);
    },
    [loadRunFiles]
  );

  /**
   * Archive or restore one run. Optimistic — the row leaves the current view
   * immediately; any failure restores the list by refetching, so the UI can
   * never claim an archive the backend rejected.
   */
  const setArchived = useCallback(
    async (runId: string, archive: boolean) => {
      setActionError(null);
      setBusyRun(runId);
      const snapshot = data;
      setData((prev) =>
        prev
          ? {
              ...prev,
              items: prev.items.filter((r) => r.run_id !== runId),
              total: Math.max(0, prev.total - 1),
            }
          : prev
      );
      setExpanded((cur) => (cur === runId ? null : cur));
      try {
        await apiClient.post(
          `/ingestion-history/${encodeURIComponent(runId)}/${
            archive ? "archive" : "unarchive"
          }`
        );
        void fetchHistory();
      } catch (err: any) {
        setData(snapshot);
        setActionError(
          err?.response?.data?.detail ||
            (archive ? "Failed to archive this run." : "Failed to restore this run.")
        );
        void fetchHistory();
      } finally {
        setBusyRun(null);
      }
    },
    [data, fetchHistory]
  );

  /** Archives every visible run. Confirmed inline, then refetched (not optimistic). */
  const archiveAll = useCallback(async () => {
    setActionError(null);
    setArchivingAll(true);
    try {
      await apiClient.post("/ingestion-history/archive-all");
      setConfirmingArchiveAll(false);
      setExpanded(null);
      setFilesByRun({});
      setPage(1);
      await fetchHistory();
    } catch (err: any) {
      setActionError(
        err?.response?.data?.detail || "Failed to archive the history."
      );
    } finally {
      setArchivingAll(false);
    }
  }, [fetchHistory]);

  useEffect(() => {
    setLoading(true);
    void fetchHistory();
  }, [fetchHistory]);

  const runs = data?.items ?? [];
  const totalPages = data ? Math.max(1, Math.ceil(data.total / PAGE_SIZE)) : 1;

  /** Any filter change resets to page 1 — page 3 of a different filter is not
   *  a place the user asked to be. */
  const applyTrigger = (value: IngestionTrigger | "") => {
    setTrigger(value);
    setPage(1);
  };
  const applyDirection = (value: "" | "INBOUND" | "OUTBOUND") => {
    setDirection(value);
    setPage(1);
  };
  const applyArchivedView = (value: boolean) => {
    setArchivedView(value);
    setPage(1);
    setExpanded(null);
  };

  return (
    <div
      id="ingestion-history"
      className="glass-panel rounded-xl border border-[#222D3D] overflow-hidden"
    >
      {/* Header */}
      <div className="flex flex-wrap items-center justify-between gap-3 px-4 py-3 border-b border-[#222D3D]">
        <span className="text-xs font-semibold text-slate-300 uppercase tracking-wider">
          {archivedView ? "Archived" : "History"}
          {data && (
            <span className="ml-2 text-slate-500 font-normal normal-case">
              ({data.total} {data.total === 1 ? "run" : "runs"})
            </span>
          )}
        </span>
        <div className="flex items-center gap-3">
          <button
            onClick={() => void fetchHistory()}
            data-testid="history-refresh"
            className="flex items-center gap-1.5 text-[11px] text-slate-400 hover:text-white transition-colors"
            title="Refresh history"
          >
            <RefreshCw className={`w-3 h-3 ${loading ? "animate-spin" : ""}`} />
            Refresh
          </button>
          {!archivedView && (
            <button
              onClick={() => setConfirmingArchiveAll(true)}
              disabled={runs.length === 0 || archivingAll}
              data-testid="history-archive-all"
              className="flex items-center gap-1.5 text-[11px] text-slate-400 hover:text-sky-300 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
              title="Archive every run in this list"
            >
              <Archive className="w-3 h-3" />
              Archive all
            </button>
          )}
        </div>
      </div>

      {/* Filters */}
      <div className="flex flex-wrap items-center gap-3 px-4 py-3 border-b border-[#222D3D]">
        <div className="flex flex-wrap items-center gap-1.5">
          {TRIGGER_FILTERS.map((f) => (
            <FilterChip
              key={f.value || "all"}
              testId={`history-filter-source-${f.value || "all"}`}
              active={trigger === f.value}
              onClick={() => applyTrigger(f.value)}
            >
              {f.label}
            </FilterChip>
          ))}
        </div>
        <span className="text-slate-700">|</span>
        <div className="flex flex-wrap items-center gap-1.5">
          {DIRECTION_FILTERS.map((f) => (
            <FilterChip
              key={f.value || "all"}
              testId={`history-filter-direction-${f.value || "all"}`}
              active={direction === f.value}
              onClick={() => applyDirection(f.value)}
            >
              {f.label}
            </FilterChip>
          ))}
        </div>
        <span className="text-slate-700">|</span>
        <FilterChip
          testId="history-filter-archived"
          active={archivedView}
          onClick={() => applyArchivedView(!archivedView)}
        >
          Archived
        </FilterChip>
      </div>

      {confirmingArchiveAll && (
        <div className="flex items-center justify-between gap-3 px-4 py-2.5 border-b border-[#222D3D] bg-slate-900/40">
          <span className="text-[11px] text-slate-300">
            Archive all {data?.total ?? runs.length}{" "}
            {(data?.total ?? runs.length) === 1 ? "run" : "runs"}? This hides the
            log entries only — no invoice or document is deleted.
          </span>
          <div className="flex gap-2 flex-shrink-0">
            <button
              onClick={() => setConfirmingArchiveAll(false)}
              disabled={archivingAll}
              className="px-3 py-1 text-[11px] rounded border border-[#222D3D] text-slate-400 hover:text-white hover:border-slate-500 disabled:opacity-40 transition-all"
            >
              Cancel
            </button>
            <button
              onClick={() => void archiveAll()}
              disabled={archivingAll}
              data-testid="history-archive-all-confirm"
              className="px-3 py-1 text-[11px] rounded border border-sky-500/40 bg-sky-600/20 text-sky-200 hover:bg-sky-600/30 disabled:opacity-40 disabled:cursor-wait transition-all"
            >
              {archivingAll ? "Archiving…" : "Archive all"}
            </button>
          </div>
        </div>
      )}
      {actionError && (
        <div
          data-testid="history-action-error"
          className="flex items-center gap-2 px-4 py-2.5 border-b border-[#222D3D] bg-rose-500/10 text-rose-400 text-[11px]"
        >
          <AlertCircle className="w-3.5 h-3.5 flex-shrink-0" />
          <span>{actionError}</span>
        </div>
      )}

      {/* List */}
      <div>
        {error ? (
          <div
            data-testid="history-error"
            className="flex items-center gap-2 px-4 py-4 text-rose-400 text-xs"
          >
            <AlertCircle className="w-4 h-4 flex-shrink-0" />
            <span>{error}</span>
          </div>
        ) : loading ? (
          <div className="px-4 py-8 text-center text-slate-500 text-xs">
            <RefreshCw className="w-4 h-4 animate-spin inline-block mr-2" />
            Loading…
          </div>
        ) : runs.length === 0 ? (
          <div
            data-testid="history-empty"
            className="px-4 py-10 flex flex-col items-center justify-center gap-3 text-center"
          >
            <div className="p-3 rounded-full bg-slate-900/50 border border-[#222D3D] text-slate-500">
              <Clock className="w-6 h-6" />
            </div>
            <div>
              <p className="text-xs font-bold text-white uppercase tracking-wider">
                {archivedView ? "Nothing archived" : "No ingestion yet"}
              </p>
              <p className="text-[11px] text-slate-500 mt-1">
                {archivedView
                  ? "Runs you archive from the history list appear here."
                  : "Every upload, inbound email, connector import and Autopilot run shows up here — including files that turned out not to be invoices."}
              </p>
            </div>
          </div>
        ) : (
          runs.map((run) => {
            const isOpen = expanded === run.run_id;
            const isArchived = run.archived_at !== null;
            const direction = directionLabel(run.flow_direction);
            return (
              <div
                key={run.run_id}
                data-testid="history-run"
                data-run-id={run.run_id}
                data-source={run.source}
                className="group border-b border-[#222D3D]/50 last:border-b-0 hover:bg-slate-900/30 transition-colors"
              >
                {/* The expand toggle and the archive action are siblings, not
                    nested buttons -- a <button> inside a <button> is invalid
                    HTML and React will not render it reliably. */}
                <div className="flex items-center">
                  <button
                    type="button"
                    onClick={() => toggleRun(run.run_id)}
                    aria-expanded={isOpen}
                    className="min-w-0 flex-1 flex items-center gap-3 px-4 py-3 text-left"
                  >
                    <ChevronRight
                      className={`w-3.5 h-3.5 flex-shrink-0 text-slate-500 transition-transform ${
                        isOpen ? "rotate-90" : ""
                      }`}
                    />
                    <div className="min-w-0 flex-1">
                      <p className="text-xs text-slate-300 truncate">
                        <span className="font-medium text-slate-200">
                          {formatRunTime(run.started_at)}
                        </span>
                        <span className="text-slate-600"> · </span>
                        {SOURCE_LABEL[run.source] ?? run.source}
                        {direction && (
                          <>
                            <span className="text-slate-600"> · </span>
                            {direction}
                          </>
                        )}
                        <span className="text-slate-600"> · </span>
                        <span className="text-slate-400">{run.summary}</span>
                      </p>
                    </div>
                    <RunStatusChip status={run.status} />
                  </button>
                  <button
                    type="button"
                    onClick={(e) => {
                      e.stopPropagation();
                      void setArchived(run.run_id, !isArchived);
                    }}
                    disabled={busyRun === run.run_id}
                    data-testid={isArchived ? "history-unarchive" : "history-archive"}
                    aria-label={isArchived ? "Restore this run" : "Archive this run"}
                    title={
                      isArchived
                        ? "Restore this run to the history list"
                        : "Archive this run. The invoice is not deleted."
                    }
                    className="mr-3 ml-1 flex-shrink-0 rounded p-1 text-slate-600 opacity-0 group-hover:opacity-100 focus:opacity-100 hover:bg-slate-800 hover:text-sky-300 disabled:cursor-wait transition-all"
                  >
                    {busyRun === run.run_id ? (
                      <Loader2 className="w-3.5 h-3.5 animate-spin" />
                    ) : isArchived ? (
                      <ArchiveRestore className="w-3.5 h-3.5" />
                    ) : (
                      <Archive className="w-3.5 h-3.5" />
                    )}
                  </button>
                </div>

                {isOpen && (
                  <div className="bg-slate-950/40 border-t border-[#222D3D]/50">
                    <RunFileList state={filesByRun[run.run_id]} />
                  </div>
                )}
              </div>
            );
          })
        )}
      </div>

      {/* States plainly what Archive does — the one thing a user could get
          wrong here is believing it deletes the invoice. */}
      <div className="px-4 py-2.5 border-t border-[#222D3D] text-[10px] text-slate-500">
        Archiving hides a log entry. Invoices and documents are never deleted
        here — delete an invoice from the Audit Queue.
      </div>

      {totalPages > 1 && (
        <div className="flex items-center justify-between px-4 py-3 border-t border-[#222D3D]">
          <span className="text-[11px] text-slate-500">
            Page {page} of {totalPages}
          </span>
          <div className="flex gap-2">
            <button
              onClick={() => setPage((p) => Math.max(1, p - 1))}
              disabled={page === 1}
              className="px-3 py-1 text-[11px] rounded border border-[#222D3D] text-slate-400 hover:text-white hover:border-slate-500 disabled:opacity-40 disabled:cursor-not-allowed transition-all"
            >
              Previous
            </button>
            <button
              onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
              disabled={page === totalPages}
              className="px-3 py-1 text-[11px] rounded border border-[#222D3D] text-slate-400 hover:text-white hover:border-slate-500 disabled:opacity-40 disabled:cursor-not-allowed transition-all"
            >
              Next
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
