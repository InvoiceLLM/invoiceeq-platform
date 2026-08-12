"use client";

/**
 * Feature 13: Autopilot — Sync History Table component
 *
 * Renders a paginated table of Autopilot sync run log entries fetched from
 * GET /api/v1/autopilot/history. Each row represents one file that was
 * processed, skipped (duplicate), or failed during a sync run.
 *
 * Used inside the Autopilot tab of the /ingestion page.
 */

import React, { useEffect, useState, useCallback } from "react";
import { RefreshCw, CheckCircle, AlertCircle, SkipForward, Clock } from "lucide-react";
import { apiClient } from "../../lib/apiClient";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface AutopilotLogEntry {
  id: string;
  source_type: string;
  source_file_id: string;
  content_hash: string;
  ingested_at: string;
  status: "SUCCESS" | "SKIPPED_DUPLICATE" | "FAILED";
  error_detail: string | null;
}

interface AutopilotHistoryResponse {
  items: AutopilotLogEntry[];
  total: number;
  page: number;
  page_size: number;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function StatusBadge({ status }: { status: AutopilotLogEntry["status"] }) {
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
  return (
    <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full bg-rose-500/10 border border-rose-500/20 text-rose-400 text-[10px] font-semibold uppercase tracking-wider">
      <AlertCircle className="w-3 h-3" />
      Failed
    </span>
  );
}

function SourceLabel({ sourceType }: { sourceType: string }) {
  const label =
    sourceType === "gdrive"
      ? "Google Drive"
      : sourceType === "salesforce"
      ? "Salesforce"
      : "Manual";

  return (
    <span className="text-slate-400 text-xs font-medium">{label}</span>
  );
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
  const pageSize = 20;

  const fetchHistory = useCallback(async () => {
    try {
      setError(null);
      const res = await apiClient.get<AutopilotHistoryResponse>(
        `/autopilot/history?page=${page}&page_size=${pageSize}`
      );
      setData(res.data);
    } catch (err: any) {
      setError(
        err?.response?.data?.detail || "Failed to load sync history."
      );
    } finally {
      setLoading(false);
    }
  }, [page]);

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

  const totalPages = data ? Math.ceil(data.total / pageSize) : 1;

  // ---- Empty State ----
  if (!loading && !error && data?.items.length === 0) {
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

  // ---- Error State ----
  if (error) {
    return (
      <div className="flex items-center gap-2 p-3 bg-rose-500/10 border border-rose-500/20 text-rose-400 rounded-lg text-xs">
        <AlertCircle className="w-4 h-4 flex-shrink-0" />
        <span>{error}</span>
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
              ({data.total} total entries)
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

      {/* Table */}
      <div className="overflow-x-auto">
        <table className="w-full text-xs">
          <thead>
            <tr className="border-b border-[#222D3D] text-slate-500 uppercase tracking-wider text-[10px]">
              <th className="text-left px-4 py-2.5 font-medium">Date / Time</th>
              <th className="text-left px-4 py-2.5 font-medium">Source</th>
              <th className="text-left px-4 py-2.5 font-medium">File ID</th>
              <th className="text-left px-4 py-2.5 font-medium">Status</th>
              <th className="text-left px-4 py-2.5 font-medium">Detail</th>
            </tr>
          </thead>
          <tbody>
            {loading ? (
              <tr>
                <td colSpan={5} className="px-4 py-8 text-center text-slate-500">
                  <RefreshCw className="w-4 h-4 animate-spin inline-block mr-2" />
                  Loading…
                </td>
              </tr>
            ) : (
              data?.items.map((entry) => (
                <tr
                  key={entry.id}
                  className="border-b border-[#222D3D]/50 hover:bg-slate-900/30 transition-colors"
                >
                  <td className="px-4 py-2.5 text-slate-300 whitespace-nowrap">
                    {formatDate(entry.ingested_at)}
                  </td>
                  <td className="px-4 py-2.5">
                    <SourceLabel sourceType={entry.source_type} />
                  </td>
                  <td className="px-4 py-2.5 font-mono text-slate-400 max-w-[160px] truncate" title={entry.source_file_id}>
                    {entry.source_file_id}
                  </td>
                  <td className="px-4 py-2.5">
                    <StatusBadge status={entry.status} />
                  </td>
                  <td className="px-4 py-2.5 text-slate-500 max-w-[200px] truncate" title={entry.error_detail ?? ""}>
                    {entry.error_detail ?? "—"}
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
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
