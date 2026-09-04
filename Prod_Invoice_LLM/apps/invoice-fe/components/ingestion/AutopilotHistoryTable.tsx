"use client";

/**
 * Feature 13: Autopilot — Sync History component
 *
 * FE Gap 428: this used to render one flat table row per *file*, keyed on the
 * raw Drive file id, which read as noise rather than as history. It now renders
 * one row per sync *run* — a sentence ("Today 09:12 · Manual · Google Drive ·
 * 14 files: 11 imported, 2 skipped, 1 failed") — with the per-file detail moved
 * behind a lazily fetched inline expansion.
 *
 * Backend contract (BE Gap 427):
 *   GET /api/autopilot/history?page=&page_size=  -> { items: AutopilotRun[], total, page, page_size }
 *   GET /api/autopilot/history/{batchId}/files   -> { items: AutopilotRunFile[] }
 * A run with `batch_id === null` is the single legacy bucket holding every
 * pre-Gap-427 row; its files are fetched from the `legacy` path.
 *
 * Used inside the Autopilot tab of the /ingestion page.
 */

import React, { useEffect, useState, useCallback } from "react";
import {
  RefreshCw,
  CheckCircle,
  AlertCircle,
  SkipForward,
  Clock,
  ChevronRight,
  Loader2,
} from "lucide-react";
import { apiClient } from "../../lib/apiClient";

// ---------------------------------------------------------------------------
// Types — mirror BE Gap 427's response shapes
// ---------------------------------------------------------------------------

type RunStatus = "SUCCESS" | "PARTIAL" | "FAILED" | "NO_NEW_FILES";
type FileStatus = "SUCCESS" | "SKIPPED_DUPLICATE" | "FAILED" | "NO_NEW_FILES";

interface AutopilotRun {
  batch_id: string | null;
  trigger: "manual" | "scheduled" | null;
  source_type: string;
  started_at: string;
  finished_at: string;
  files_seen: number;
  imported: number;
  skipped: number;
  failed: number;
  status: RunStatus;
}

interface AutopilotRunFile {
  id: string;
  source_file_id: string;
  source_file_name: string | null;
  content_hash: string;
  ingested_at: string;
  status: FileStatus;
  error_detail: string | null;
}

interface AutopilotHistoryResponse {
  items: AutopilotRun[];
  total: number;
  page: number;
  page_size: number;
}

interface AutopilotRunFilesResponse {
  items: AutopilotRunFile[];
}

/** Stable key for a run — the legacy bucket has no batch_id of its own. */
function runKey(run: AutopilotRun): string {
  return run.batch_id ?? "legacy";
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/** Per-file badge — unchanged visual language from the pre-Gap-428 table. */
function StatusBadge({ status }: { status: FileStatus }) {
  if (status === "SUCCESS") {
    return (
      <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full bg-emerald-500/10 border border-emerald-500/20 text-emerald-400 text-[10px] font-semibold uppercase tracking-wider">
        <CheckCircle className="w-3 h-3" />
        Imported
      </span>
    );
  }
  if (status === "SKIPPED_DUPLICATE") {
    return (
      <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full bg-amber-500/10 border border-amber-500/20 text-amber-400 text-[10px] font-semibold uppercase tracking-wider">
        <SkipForward className="w-3 h-3" />
        Skipped
      </span>
    );
  }
  if (status === "NO_NEW_FILES") {
    return (
      <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full bg-slate-500/10 border border-slate-500/20 text-slate-400 text-[10px] font-semibold uppercase tracking-wider">
        <Clock className="w-3 h-3" />
        Nothing New
      </span>
    );
  }
  return (
    <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full bg-rose-500/10 border border-rose-500/20 text-rose-400 text-[10px] font-semibold uppercase tracking-wider">
      <AlertCircle className="w-3 h-3" />
      Failed
    </span>
  );
}

const RUN_STATUS_STYLE: Record<RunStatus, { label: string; className: string }> = {
  SUCCESS: {
    label: "Success",
    className:
      "bg-emerald-500/10 border-emerald-500/20 text-emerald-400",
  },
  PARTIAL: {
    label: "Partial",
    className: "bg-amber-500/10 border-amber-500/20 text-amber-400",
  },
  FAILED: {
    label: "Failed",
    className: "bg-rose-500/10 border-rose-500/20 text-rose-400",
  },
  NO_NEW_FILES: {
    label: "Nothing new",
    className: "bg-slate-500/10 border-slate-500/20 text-slate-400",
  },
};

/** Run-level chip. Same pill geometry as StatusBadge, colour keyed by run status. */
function RunStatusChip({ status }: { status: RunStatus }) {
  const style =
    RUN_STATUS_STYLE[status] ?? RUN_STATUS_STYLE.NO_NEW_FILES;
  return (
    <span
      className={`inline-flex items-center px-2 py-0.5 rounded-full border text-[10px] font-semibold uppercase tracking-wider whitespace-nowrap ${style.className}`}
    >
      {style.label}
    </span>
  );
}

function sourceLabel(sourceType: string): string {
  // FE Gap 322 removed the "salesforce" arm. Historical rows may still carry
  // that source_type; they fall through to "Manual" rather than being labelled
  // with a connector that no longer exists.
  return sourceType === "gdrive" ? "Google Drive" : "Manual";
}

function triggerLabel(trigger: AutopilotRun["trigger"]): string {
  if (trigger === "scheduled") return "Scheduled";
  if (trigger === "manual") return "Manual";
  return "Autopilot";
}

function formatDate(iso: string): string {
  try {
    return new Date(iso).toLocaleString(undefined, {
      dateStyle: "medium",
      timeStyle: "short",
    });
  } catch {
    return iso;
  }
}

/** "Today 09:12" / "Yesterday 17:40" / "12 Aug 09:12" — the run row's lead-in. */
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
  const dayMs = 86_400_000;
  const ts = d.getTime();
  if (ts >= startOfToday) return `Today ${time}`;
  if (ts >= startOfToday - dayMs) return `Yesterday ${time}`;
  return `${d.toLocaleDateString(undefined, { day: "numeric", month: "short" })} ${time}`;
}

/** Coarse relative age for the "Last run" tile. */
function relativeTime(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  const mins = Math.floor((Date.now() - d.getTime()) / 60_000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  const days = Math.floor(hrs / 24);
  if (days < 30) return `${days}d ago`;
  return formatDate(iso);
}

/**
 * "14 files: 11 imported, 2 skipped, 1 failed" — zero-count clauses are
 * dropped so a clean run reads as "14 files: 14 imported".
 */
function runSummarySentence(run: AutopilotRun): string {
  if (run.status === "NO_NEW_FILES" && run.files_seen === 0) {
    return "No new files";
  }
  const parts: string[] = [];
  if (run.imported > 0) parts.push(`${run.imported} imported`);
  if (run.skipped > 0) parts.push(`${run.skipped} skipped`);
  if (run.failed > 0) parts.push(`${run.failed} failed`);
  const noun = run.files_seen === 1 ? "file" : "files";
  if (parts.length === 0) return `${run.files_seen} ${noun}`;
  return `${run.files_seen} ${noun}: ${parts.join(", ")}`;
}

/** Thin proportional imported/skipped/failed bar. Renders nothing for an empty run. */
function RunProportionBar({ run }: { run: AutopilotRun }) {
  const total = run.imported + run.skipped + run.failed;
  if (total <= 0) return null;
  const pct = (n: number) => `${(n / total) * 100}%`;
  return (
    <div className="flex h-1 w-full max-w-[180px] overflow-hidden rounded-full bg-slate-800">
      {run.imported > 0 && (
        <div className="bg-emerald-500/70" style={{ width: pct(run.imported) }} />
      )}
      {run.skipped > 0 && (
        <div className="bg-amber-500/70" style={{ width: pct(run.skipped) }} />
      )}
      {run.failed > 0 && (
        <div className="bg-rose-500/70" style={{ width: pct(run.failed) }} />
      )}
    </div>
  );
}

/** One header tile. */
function SummaryTile({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <div className="flex-1 min-w-0 rounded-lg border border-[#222D3D] bg-slate-900/40 px-3 py-2">
      <p className="text-[9px] font-semibold uppercase tracking-wider text-slate-500">
        {label}
      </p>
      <div className="mt-1 flex items-center gap-1.5 text-xs text-slate-200">
        {children}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Run detail — lazily fetched per-file list
// ---------------------------------------------------------------------------

interface RunFilesState {
  loading: boolean;
  error: string | null;
  items: AutopilotRunFile[] | null;
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
      <div className="flex items-center gap-2 px-4 py-3 text-[11px] text-rose-400">
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
    <table className="w-full text-xs">
      <thead>
        <tr className="text-slate-500 uppercase tracking-wider text-[10px]">
          <th className="text-left px-4 py-2 font-medium">File</th>
          <th className="text-left px-4 py-2 font-medium">Status</th>
          <th className="text-left px-4 py-2 font-medium">Detail</th>
        </tr>
      </thead>
      <tbody>
        {state.items.map((file) => {
          const hasName = Boolean(file.source_file_name);
          const display = file.source_file_name ?? file.source_file_id;
          return (
            <tr key={file.id} className="border-t border-[#222D3D]/50">
              <td
                className={`px-4 py-2 max-w-[220px] truncate ${
                  hasName ? "text-slate-300" : "font-mono text-slate-400"
                }`}
                title={
                  hasName
                    ? `${file.source_file_name} (${file.source_file_id})`
                    : file.source_file_id
                }
              >
                {display}
              </td>
              <td className="px-4 py-2">
                <StatusBadge status={file.status} />
              </td>
              <td
                className="px-4 py-2 text-slate-500 max-w-[220px] truncate"
                title={file.error_detail ?? ""}
              >
                {file.error_detail ?? "—"}
              </td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}

// ---------------------------------------------------------------------------
// Main Component
// ---------------------------------------------------------------------------

interface AutopilotHistoryTableProps {
  /** Set to true to auto-refresh every 30 seconds (e.g. during an active sync). */
  autoRefresh?: boolean;
}

export default function AutopilotHistoryTable({
  autoRefresh = false,
}: AutopilotHistoryTableProps) {
  const [data, setData] = useState<AutopilotHistoryResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [page, setPage] = useState(1);
  const [expanded, setExpanded] = useState<string | null>(null);
  // Per-batch file cache: fetched once per run key, kept for the component's life.
  const [filesByRun, setFilesByRun] = useState<Record<string, RunFilesState>>({});
  const pageSize = 20;

  const fetchHistory = useCallback(async () => {
    try {
      setError(null);
      const res = await apiClient.get<AutopilotHistoryResponse>(
        `/autopilot/history?page=${page}&page_size=${pageSize}`
      );
      setData(res.data);
    } catch (err: any) {
      setError(err?.response?.data?.detail || "Failed to load sync history.");
    } finally {
      setLoading(false);
    }
  }, [page]);

  /** Lazily loads one run's files; a cached run (or one in flight) is a no-op. */
  const loadRunFiles = useCallback(
    async (key: string) => {
      let alreadyLoaded = false;
      setFilesByRun((prev) => {
        if (prev[key]) {
          alreadyLoaded = true;
          return prev;
        }
        return { ...prev, [key]: { loading: true, error: null, items: null } };
      });
      if (alreadyLoaded) return;
      try {
        const res = await apiClient.get<AutopilotRunFilesResponse>(
          `/autopilot/history/${encodeURIComponent(key)}/files`
        );
        setFilesByRun((prev) => ({
          ...prev,
          [key]: { loading: false, error: null, items: res.data.items ?? [] },
        }));
      } catch (err: any) {
        setFilesByRun((prev) => ({
          ...prev,
          [key]: {
            loading: false,
            error:
              err?.response?.data?.detail || "Failed to load files for this run.",
            items: null,
          },
        }));
      }
    },
    []
  );

  const toggleRun = useCallback(
    (run: AutopilotRun) => {
      const key = runKey(run);
      setExpanded((cur) => (cur === key ? null : key));
      void loadRunFiles(key);
    },
    [loadRunFiles]
  );

  // Initial load + page change
  useEffect(() => {
    setLoading(true);
    fetchHistory();
  }, [fetchHistory]);

  // Auto-refresh polling
  useEffect(() => {
    if (!autoRefresh) return;
    const timer = setInterval(fetchHistory, 30_000);
    return () => clearInterval(timer);
  }, [autoRefresh, fetchHistory]);

  const runs = data?.items ?? [];
  const totalPages = data ? Math.max(1, Math.ceil(data.total / pageSize)) : 1;

  // Header tile values. `importedLast7Days` sums the *loaded* page only — the
  // label says so; this component never sees runs outside the current page.
  const lastRun = runs.length > 0 ? runs[0] : null;
  const sevenDaysAgo = Date.now() - 7 * 86_400_000;
  const importedLast7Days = runs.reduce((sum, run) => {
    const ts = new Date(run.started_at).getTime();
    return !Number.isNaN(ts) && ts >= sevenDaysAgo ? sum + run.imported : sum;
  }, 0);

  // ---- Error State ----
  if (error) {
    return (
      <div className="flex items-center gap-2 p-3 bg-rose-500/10 border border-rose-500/20 text-rose-400 rounded-lg text-xs">
        <AlertCircle className="w-4 h-4 flex-shrink-0" />
        <span>{error}</span>
      </div>
    );
  }

  // ---- Empty State ----
  if (!loading && runs.length === 0) {
    return (
      <div className="glass-panel rounded-xl border border-[#222D3D] p-10 flex flex-col items-center justify-center gap-3 text-center">
        <div className="p-3 rounded-full bg-slate-900/50 border border-[#222D3D] text-slate-500">
          <Clock className="w-6 h-6" />
        </div>
        <div>
          <p className="text-xs font-bold text-white uppercase tracking-wider">
            No Sync Runs Yet
          </p>
          <p className="text-[11px] text-slate-500 mt-1">
            Sync history will appear here after your first run.
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="glass-panel rounded-xl border border-[#222D3D] overflow-hidden">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-[#222D3D]">
        <span className="text-xs font-semibold text-slate-300 uppercase tracking-wider">
          Sync History
          {data && (
            <span className="ml-2 text-slate-500 font-normal normal-case">
              ({data.total} {data.total === 1 ? "run" : "runs"})
            </span>
          )}
        </span>
        <button
          onClick={fetchHistory}
          className="flex items-center gap-1.5 text-[11px] text-slate-400 hover:text-white transition-colors"
          title="Refresh history"
        >
          <RefreshCw className={`w-3 h-3 ${loading ? "animate-spin" : ""}`} />
          Refresh
        </button>
      </div>

      {/* Summary tiles */}
      <div className="flex gap-2 px-4 py-3 border-b border-[#222D3D]">
        <SummaryTile label="Last run">
          {lastRun ? (
            <>
              <span className="truncate">{relativeTime(lastRun.started_at)}</span>
              <RunStatusChip status={lastRun.status} />
            </>
          ) : (
            <span className="text-slate-500">—</span>
          )}
        </SummaryTile>
        <SummaryTile label="Imported (last 7 days, loaded runs)">
          <span className="font-semibold text-white">{importedLast7Days}</span>
        </SummaryTile>
        <SummaryTile label="Sync">
          {autoRefresh ? (
            <>
              <Loader2 className="w-3 h-3 animate-spin text-sky-400" />
              <span className="text-sky-400">In progress…</span>
            </>
          ) : (
            <span className="text-slate-500">Idle</span>
          )}
        </SummaryTile>
      </div>

      {/* Run list */}
      <div>
        {loading ? (
          <div className="px-4 py-8 text-center text-slate-500 text-xs">
            <RefreshCw className="w-4 h-4 animate-spin inline-block mr-2" />
            Loading…
          </div>
        ) : (
          runs.map((run) => {
            const key = runKey(run);
            const isOpen = expanded === key;
            const isLegacy = run.batch_id === null;
            return (
              <div key={key} className="border-b border-[#222D3D]/50 last:border-b-0">
                <button
                  type="button"
                  onClick={() => toggleRun(run)}
                  aria-expanded={isOpen}
                  className="w-full flex items-center gap-3 px-4 py-3 text-left hover:bg-slate-900/30 transition-colors"
                >
                  <ChevronRight
                    className={`w-3.5 h-3.5 flex-shrink-0 text-slate-500 transition-transform ${
                      isOpen ? "rotate-90" : ""
                    }`}
                  />
                  <div className="min-w-0 flex-1">
                    <p className="text-xs text-slate-300 truncate">
                      {isLegacy ? (
                        <span className="font-medium text-slate-200">
                          Earlier activity
                        </span>
                      ) : (
                        <>
                          <span className="font-medium text-slate-200">
                            {formatRunTime(run.started_at)}
                          </span>
                          <span className="text-slate-600"> · </span>
                          {triggerLabel(run.trigger)}
                        </>
                      )}
                      <span className="text-slate-600"> · </span>
                      {sourceLabel(run.source_type)}
                      <span className="text-slate-600"> · </span>
                      <span className="text-slate-400">
                        {runSummarySentence(run)}
                      </span>
                    </p>
                    <div className="mt-1.5">
                      <RunProportionBar run={run} />
                    </div>
                  </div>
                  <RunStatusChip status={run.status} />
                </button>

                {isOpen && (
                  <div className="bg-slate-950/40 border-t border-[#222D3D]/50">
                    <RunFileList state={filesByRun[key]} />
                  </div>
                )}
              </div>
            );
          })
        )}
      </div>

      {/* Pagination */}
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
