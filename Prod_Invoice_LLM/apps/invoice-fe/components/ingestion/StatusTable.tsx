"use client";

import React, { useState, useEffect, useRef } from "react";
import { 
  CheckCircle2, 
  AlertTriangle, 
  Loader2, 
  ChevronDown, 
  ChevronUp, 
  FileText, 
  ExternalLink,
  Info
} from "lucide-react";
import Link from "next/link";
import { apiClient } from "../../lib/apiClient";
import { formatCurrency } from "../../lib/utils";

export interface StatusItem {
  id: string;
  name: string;
  size: number;
  status: "UPLOADED" | "PROCESSING" | "COMPLETED" | "AUDIT_REQUIRED" | "DUPLICATE" | "FAILED" | "PAID" | "REJECTED";
  progress: number;
  alerts?: string[];
  vendorName?: string;
  total?: number;
  /**
   * FE Gap 183: ISO-4217 code for `total`. The two places this row renders a
   * total used `$${total.toFixed(2)}`, hardcoding USD on the live ingestion
   * ledger. GET /invoices/status/{id} now returns currency alongside
   * grand_total so the real one can be threaded through.
   */
  currency?: string | null;
}

interface StatusTableProps {
  batchId: string | null;
  jobIds: string[];
  initialFiles: Array<{ name: string; size: number }>;
}

export default function StatusTable({
  batchId,
  jobIds = [],
  initialFiles = [],
}: StatusTableProps) {
  const [items, setItems] = useState<StatusItem[]>([]);
  const [expandedRowId, setExpandedRowId] = useState<string | null>(null);
  const eventSourceRef = useRef<EventSource | null>(null);
  const activePollsRef = useRef<{ [key: string]: boolean }>({});

  const formatFileSize = (bytes: number) => {
    if (bytes === 0) return "0 Bytes";
    const k = 1024;
    const sizes = ["Bytes", "KB", "MB"];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + " " + sizes[i];
  };

  // Initialize status ledger items from input
  useEffect(() => {
    if (jobIds.length === 0) {
      setItems([]);
      return;
    }

    const initialItems = jobIds.map((id, index) => {
      const fileInfo = initialFiles[index] || { name: `Invoice-${index + 1}.pdf`, size: 0 };
      return {
        id,
        name: fileInfo.name,
        size: fileInfo.size,
        status: "PROCESSING" as const,
        progress: 25,
        alerts: [],
      };
    });

    setItems(initialItems);
    setExpandedRowId(null);
  }, [batchId, jobIds]);

  // Handle Hybrid tracking: Polling (1-5 files) or SSE (6+ files)
  useEffect(() => {
    if (jobIds.length === 0 || !batchId) return;

    // Cleanup function
    const cleanup = () => {
      if (eventSourceRef.current) {
        eventSourceRef.current.close();
        eventSourceRef.current = null;
      }
      activePollsRef.current = {};
    };

    cleanup();

    const isSSE = jobIds.length >= 6;

    if (isSSE) {
      // --- SSE Connection for 6+ files ---
      const sseUrl = `/api/invoices/stream/${batchId}`;

      const es = new EventSource(sseUrl);
      eventSourceRef.current = es;

      es.onmessage = (event) => {
        try {
          const payload = JSON.parse(event.data);
          if (payload && payload.invoice_id) {
            updateItemStatus(
              payload.invoice_id,
              payload.status,
              payload.status === "COMPLETED" ? 100 : 60,
              payload.alerts || []
            );
          }
        } catch (e) {
          console.error("Failed to parse SSE payload", e);
        }
      };

      es.onerror = (err) => {
        console.error("SSE connection error", err);
        es.close();
      };
    } else {
      // --- Polling connection for 1-5 files ---
      jobIds.forEach((jobId) => {
        activePollsRef.current[jobId] = true;
        pollJobStatus(jobId);
      });
    }

    return cleanup;
  }, [batchId, jobIds]);

  // Status updates in local array
  const updateItemStatus = (
    id: string,
    status: StatusItem["status"],
    progress: number,
    alerts: string[] = [],
    vendorName?: string,
    total?: number,
    currency?: string | null
  ) => {
    setItems((prev) =>
      prev.map((item) =>
        item.id === id
          ? {
              ...item,
              status,
              progress,
              alerts: alerts || [],
              vendorName,
              total,
              currency,
            }
          : item
      )
    );
  };

  // Poll single job status every 2 seconds
  const pollJobStatus = async (jobId: string) => {
    if (!activePollsRef.current[jobId]) return;

    try {
      const res = await apiClient.get(`/invoices/status/${jobId}`);
      const data = res.data;

      const rawStatus = (data.status || "PROCESSING").toUpperCase();
      let statusVal: StatusItem["status"] = "PROCESSING";
      let progressVal = 40;

      if (rawStatus === "COMPLETED" || rawStatus === "PAID") {
        statusVal = "COMPLETED";
        progressVal = 100;
        activePollsRef.current[jobId] = false; // Stop polling
      } else if (rawStatus === "AUDIT_REQUIRED") {
        statusVal = "AUDIT_REQUIRED";
        progressVal = 100;
        activePollsRef.current[jobId] = false; // Stop polling
      } else if (rawStatus === "DUPLICATE") {
        // FE Gap 14: this branch was missing entirely -- a duplicate upload
        // (batches under 6 files, which use this polling path rather than
        // SSE) silently stayed on "PROCESSING" forever since none of the
        // other branches matched, and polling never stopped for it either.
        statusVal = "DUPLICATE";
        progressVal = 100;
        activePollsRef.current[jobId] = false; // Stop polling
      } else if (rawStatus === "FAILED") {
        statusVal = "FAILED";
        progressVal = 100;
        activePollsRef.current[jobId] = false; // Stop polling
      }

      // Format alerts nicely from JSON details if present
      const alertsList = Array.isArray(data.alerts)
        ? data.alerts.map((a: any) => typeof a === "string" ? a : a.message || "Extraction alert detected")
        : [];

      updateItemStatus(
        jobId,
        statusVal,
        progressVal,
        alertsList,
        data.vendor_name,
        data.grand_total,
        data.currency
      );
      
      // Increment progress on active polling slightly to simulate loading state
      if (statusVal === "PROCESSING") {
        setItems((prev) =>
          prev.map((item) =>
            item.id === jobId
              ? { ...item, progress: Math.min(85, item.progress + 15) }
              : item
          )
        );
      }
    } catch (e) {
      console.error(`Failed to poll job status for ${jobId}`, e);
    }

    // Schedule next poll if active
    if (activePollsRef.current[jobId]) {
      setTimeout(() => pollJobStatus(jobId), 2000);
    }
  };

  const getStatusBadge = (status: StatusItem["status"]) => {
    switch (status) {
      case "PAID":
        return (
          <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-semibold bg-emerald-500/10 border border-emerald-500/20 text-emerald-400">
            <CheckCircle2 className="w-3 h-3" />
            Paid
          </span>
        );
      case "COMPLETED":
        return (
          <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-semibold bg-teal-500/10 border border-teal-500/20 text-teal-400">
            <CheckCircle2 className="w-3 h-3" />
            Completed
          </span>
        );
      case "AUDIT_REQUIRED":
        return (
          <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-semibold bg-amber-500/10 border border-amber-500/20 text-amber-400">
            <AlertTriangle className="w-3 h-3" />
            Audit Required
          </span>
        );
      case "FAILED":
        return (
          <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-semibold bg-rose-500/10 border border-rose-500/20 text-rose-400">
            <AlertTriangle className="w-3 h-3" />
            Failed
          </span>
        );
      case "REJECTED":
        return (
          <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-semibold bg-rose-500/10 border border-rose-500/20 text-rose-400">
            <AlertTriangle className="w-3 h-3" />
            Rejected
          </span>
        );
      case "DUPLICATE":
        return (
          <span
            title="Duplicate file content detected. Copied details from previous upload."
            className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-semibold bg-amber-500/10 border border-amber-500/20 text-amber-400 cursor-help"
          >
            <AlertTriangle className="w-3 h-3" />
            Duplicate
          </span>
        );
      case "PROCESSING":
      default:
        return (
          <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-semibold bg-sky-500/10 border border-sky-500/20 text-sky-400">
            <Loader2 className="w-3 h-3 animate-spin" />
            Processing
          </span>
        );
    }
  };

  const toggleRowExpansion = (id: string) => {
    setExpandedRowId(expandedRowId === id ? null : id);
  };

  if (items.length === 0) return null;

  // FE Gap 14: live header counters. "Processed" means the pipeline reached
  // a terminal state for that file, regardless of outcome -- Completed,
  // Audit Required, Duplicate, and Failed are all "done", only Processing/
  // Uploaded are still in flight.
  const totalFound = items.length;
  const processedCount = items.filter((i) =>
    ["COMPLETED", "AUDIT_REQUIRED", "DUPLICATE", "FAILED"].includes(i.status)
  ).length;
  const duplicateCount = items.filter((i) => i.status === "DUPLICATE").length;
  const failedCount = items.filter((i) => i.status === "FAILED").length;

  return (
    <div className="glass-panel rounded-xl overflow-hidden border border-[#222D3D]">
      {/* Component Title.
          FE Gap 113 item 6: the title block and the counters used to sit on one
          wide row, which only worked while this panel spanned two-thirds of the
          screen. They now stack, so the panel reads correctly at the narrower
          width the ledger column actually needs. */}
      <div className="p-4 border-b border-[#222D3D] space-y-3">
        <div>
          <h3 className="text-sm font-semibold text-white tracking-wide">
            Ingestion Progress Queue
          </h3>
          <p className="text-[11px] text-slate-500">
            Live extraction ledger pipeline ({jobIds.length >= 6 ? "SSE Connection" : "Polling Mode"}).
          </p>
        </div>

        {/* FE Gap 14: live statistics counters */}
        <div className="flex items-center gap-4 flex-wrap">
          <div>
            <div className="text-sm font-bold text-white">{totalFound}</div>
            <div className="text-[9px] text-slate-500 uppercase tracking-wide">Found</div>
          </div>
          <div>
            <div className="text-sm font-bold text-emerald-400">{processedCount}</div>
            <div className="text-[9px] text-slate-500 uppercase tracking-wide">Processed</div>
          </div>
          <div>
            <div className="text-sm font-bold text-amber-400">{duplicateCount}</div>
            <div className="text-[9px] text-slate-500 uppercase tracking-wide">Duplicates</div>
          </div>
          <div>
            <div className="text-sm font-bold text-rose-400">{failedCount}</div>
            <div className="text-[9px] text-slate-500 uppercase tracking-wide">Failed</div>
          </div>
        </div>
      </div>

      {/* Table view.
          FE Gap 113 item 6: six columns (File Name / Size / Type / Status /
          Progress / Details) collapsed to the three this ledger is actually
          about -- File, Stage, Status. Nothing was dropped except the "Type"
          column, which was the constant string "PDF" on every row (the drop
          zone only accepts PDFs): Size moved under the filename, Progress
          became the Stage cell, and the Details chevron moved into the Status
          cell next to the badge it expands. Row behavior -- polling/SSE
          updates, badges, expansion -- is untouched. */}
      <div className="overflow-x-auto">
        <table className="w-full text-left border-collapse table-fixed">
          <thead>
            <tr className="border-b border-[#222D3D] bg-slate-900/20 text-slate-400 text-[10px] font-bold uppercase tracking-wider select-none">
              <th className="px-4 py-3 w-[44%]">File</th>
              <th className="px-4 py-3 w-[26%]">Stage</th>
              <th className="px-4 py-3 w-[30%]">Status</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-[#222D3D]/30 text-slate-300 text-xs">
            {items.map((item) => {
              const isExpanded = expandedRowId === item.id;
              const hasAlerts = item.status === "AUDIT_REQUIRED";

              return (
                <React.Fragment key={item.id}>
                  {/* Ledger Data Row */}
                  <tr className="hover:bg-slate-900/20 transition-colors align-top">
                    <td className="px-4 py-3">
                      <div className="flex items-start gap-2 min-w-0">
                        <FileText className="w-4 h-4 text-slate-400 flex-shrink-0 mt-0.5" />
                        <div className="min-w-0">
                          <div className="truncate font-semibold text-slate-200" title={item.name}>
                            {item.name}
                          </div>
                          <div className="text-[10px] text-slate-500 font-mono">
                            PDF &middot; {formatFileSize(item.size)}
                          </div>
                        </div>
                      </div>
                    </td>
                    <td className="px-4 py-3">
                      <div className="flex items-center gap-2">
                        {/* Progress ring track */}
                        <div className="flex-1 bg-slate-800 rounded-full h-1.5 overflow-hidden">
                          <div
                            className={`h-full rounded-full transition-all duration-500 ${
                              item.status === "COMPLETED"
                                ? "bg-emerald-500"
                                : item.status === "AUDIT_REQUIRED"
                                ? "bg-amber-500"
                                : item.status === "FAILED"
                                ? "bg-rose-500"
                                : "bg-accent-blue animate-pulse"
                            }`}
                            style={{ width: `${item.progress}%` }}
                          />
                        </div>
                        <span className="text-[10px] font-semibold font-mono text-slate-400 shrink-0">
                          {item.progress}%
                        </span>
                      </div>
                    </td>
                    <td className="px-4 py-3">
                      <div className="flex items-center justify-between gap-1">
                        {getStatusBadge(item.status)}
                        {(hasAlerts || item.status === "COMPLETED") && (
                          <button
                            onClick={() => toggleRowExpansion(item.id)}
                            aria-label={isExpanded ? "Hide details" : "Show details"}
                            className="p-1 rounded hover:bg-slate-800 text-slate-400 hover:text-white transition-colors shrink-0"
                          >
                            {isExpanded ? (
                              <ChevronUp className="w-4 h-4" />
                            ) : (
                              <ChevronDown className="w-4 h-4" />
                            )}
                          </button>
                        )}
                      </div>
                    </td>
                  </tr>

                  {/* Expandable audit alert warnings */}
                  {isExpanded && (
                    <tr>
                      <td colSpan={3} className="bg-amber-500/5 px-4 py-4 border-l-2 border-amber-500">
                        {item.status === "AUDIT_REQUIRED" ? (
                          <div className="space-y-2 text-xs text-amber-300">
                            <div className="flex items-center gap-2 font-semibold">
                              <Info className="w-4 h-4 text-amber-500 flex-shrink-0" />
                              <span>Extraction Integrity Warnings Detected</span>
                            </div>
                            
                            {item.alerts && item.alerts.length > 0 ? (
                              <ul className="list-disc pl-5 space-y-1 text-slate-300">
                                {item.alerts.map((alert, idx) => (
                                  <li key={idx}>{alert}</li>
                                ))}
                              </ul>
                            ) : (
                              <p className="text-slate-300">
                                Values parsed from invoice (e.g. totals or dates) flagged verification alerts.
                              </p>
                            )}

                            <div className="pt-2 flex items-center justify-between gap-2 flex-wrap">
                              <span className="text-[10px] text-slate-400 font-mono">
                                Vendor: {item.vendorName || "Unknown"} | Total: {item.total ? formatCurrency(item.total, item.currency) : "Pending"}
                              </span>
                              <Link
                                href={`/invoices/review/${item.id}`}
                                className="inline-flex items-center gap-1 text-xs text-[#3B82F6] hover:text-[#3B82F6]/80 font-bold transition-colors"
                              >
                                Open Auditor Console
                                <ExternalLink className="w-3 h-3" />
                              </Link>
                            </div>
                          </div>
                        ) : (
                          <div className="flex items-center justify-between gap-2 flex-wrap text-xs text-slate-300">
                            <span className="text-emerald-400 font-semibold flex items-center gap-2">
                              <CheckCircle2 className="w-4 h-4 text-emerald-500" />
                              Invoice parsed successfully with zero warnings.
                            </span>
                            <span className="text-[10px] text-slate-400 font-mono">
                              Vendor: {item.vendorName || "Unknown"} | Total: {item.total ? formatCurrency(item.total, item.currency) : "Pending"}
                            </span>
                          </div>
                        )}
                      </td>
                    </tr>
                  )}
                </React.Fragment>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
