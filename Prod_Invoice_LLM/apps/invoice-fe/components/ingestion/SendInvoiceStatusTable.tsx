"use client";

import React, { useState, useEffect, useRef } from "react";
import { CheckCircle2, AlertTriangle, Loader2, FileText, Send, XCircle } from "lucide-react";
import Link from "next/link";
import { apiClient } from "../../lib/apiClient";
import LogTerminal from "./LogTerminal";

// Feature 2.1's outbound status lifecycle -- distinct from inbound's
// PROCESSING/COMPLETED/AUDIT_REQUIRED since the semantics differ (pre-send
// validation, not post-receipt audit).
// Gap 84 added FAILED: the outbound worker's except block now persists it to
// the invoice row instead of only broadcasting it over the ephemeral SSE
// channel, so this poll can finally see a real processing failure at all.
export type OutboundStatus =
  | "UPLOADED"
  | "PROCESSING_OCR"
  | "EXTRACTING_DATA"
  | "VERIFIED"
  | "NEEDS_REVIEW"
  | "SENT"
  | "FAILED";

// Statuses the pipeline will never move on from. Anything not listed here means
// work is still owed, so polling continues.
const TERMINAL_STATUSES: OutboundStatus[] = ["VERIFIED", "NEEDS_REVIEW", "SENT", "FAILED"];

interface SendInvoiceStatusTableProps {
  invoiceId: string | null;
  fileName: string;
}

/**
 * Task 3.1.2: single-invoice outbound status ledger. Feature 2.1's upload
 * endpoint is one file at a time (unlike inbound's batch upload), so this is
 * a simpler single-row view, not a full ledger table -- polls the existing
 * GET /api/invoices/{id} proxy (flow-direction-agnostic, already returns
 * customer_name/status/alerts for any invoice) rather than a new endpoint.
 */
export default function SendInvoiceStatusTable({ invoiceId, fileName }: SendInvoiceStatusTableProps) {
  const [status, setStatus] = useState<OutboundStatus>("UPLOADED");
  const [customerName, setCustomerName] = useState<string | null>(null);
  const [grandTotal, setGrandTotal] = useState<number | null>(null);
  const [alerts, setAlerts] = useState<{ type: string; message: string }[]>([]);
  const [isConfirming, setIsConfirming] = useState(false);
  const activeRef = useRef(true);

  useEffect(() => {
    activeRef.current = true;
    return () => {
      activeRef.current = false;
    };
  }, [invoiceId]);

  useEffect(() => {
    if (!invoiceId) return;

    const poll = async () => {
      if (!activeRef.current) return;
      // Read the terminal check off the value this pass actually fetched, not
      // off the `status` state variable. This effect only re-runs on invoiceId,
      // so the closure's `status` was pinned to "UPLOADED" forever and the loop
      // never stopped even once the invoice reached VERIFIED/SENT. Fixed here
      // rather than left alone because Gap 84's whole point is that a terminal
      // state has to actually be recognised as terminal.
      let latest: OutboundStatus = "UPLOADED";
      try {
        const res = await apiClient.get(`/invoices/${invoiceId}`);
        const data = res.data;
        latest = (data.status || "UPLOADED") as OutboundStatus;
        setStatus(latest);
        setCustomerName(data.customer_name ?? null);
        setGrandTotal(data.grand_total ?? null);
        setAlerts(Array.isArray(data.sa_alerts) ? data.sa_alerts : []);
      } catch (e) {
        console.error("Failed to poll outbound invoice status", e);
      }
      if (activeRef.current && !TERMINAL_STATUSES.includes(latest)) {
        setTimeout(poll, 2000);
      }
    };
    poll();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [invoiceId]);

  const handleConfirmSend = async () => {
    if (!invoiceId) return;
    setIsConfirming(true);
    try {
      await apiClient.put(`/outbound-invoices/${invoiceId}/confirm-send`);
      setStatus("SENT");
    } catch (e) {
      console.error("Confirm-send failed", e);
    } finally {
      setIsConfirming(false);
    }
  };

  if (!invoiceId) return null;

  const getStatusBadge = () => {
    switch (status) {
      case "VERIFIED":
        return (
          <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-semibold bg-emerald-500/10 border border-emerald-500/20 text-emerald-400">
            <CheckCircle2 className="w-3 h-3" /> Verified
          </span>
        );
      case "NEEDS_REVIEW":
        return (
          <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-semibold bg-amber-500/10 border border-amber-500/20 text-amber-400">
            <AlertTriangle className="w-3 h-3" /> Needs Review
          </span>
        );
      case "SENT":
        return (
          <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-semibold bg-sky-500/10 border border-sky-500/20 text-sky-400">
            <Send className="w-3 h-3" /> Sent
          </span>
        );
      case "FAILED":
        // Matches StatusTable.tsx's existing inbound Failed badge (red/XCircle)
        // rather than inventing a second visual language for the same outcome.
        return (
          <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-semibold bg-red-500/10 border border-red-500/20 text-red-400">
            <XCircle className="w-3 h-3" /> Failed
          </span>
        );
      default:
        return (
          <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-semibold bg-sky-500/10 border border-sky-500/20 text-sky-400">
            <Loader2 className="w-3 h-3 animate-spin" /> {status.replace("_", " ")}
          </span>
        );
    }
  };

  const canConfirm = status === "VERIFIED" || status === "NEEDS_REVIEW";

  return (
    <div className="space-y-4">
      <div className="glass-panel rounded-xl overflow-hidden border border-[#222D3D] space-y-4 p-5">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2 max-w-xs truncate">
            <FileText className="w-4 h-4 text-slate-400 flex-shrink-0" />
            <span className="truncate font-semibold text-slate-200 text-xs">{fileName}</span>
          </div>
          {getStatusBadge()}
        </div>

        {(customerName || grandTotal) && (
          <div className="text-[11px] text-slate-400 font-mono">
            Customer: {customerName || "Pending"} | Total: {grandTotal ? `$${grandTotal.toFixed(2)}` : "Pending"}
          </div>
        )}

        {status === "FAILED" && (
          <div className="space-y-1 text-xs text-red-300 bg-red-500/5 border border-red-500/20 rounded-lg p-3">
            <div className="font-semibold">Processing failed.</div>
            {alerts.length > 0 ? (
              alerts.map((a, idx) => <div key={idx}>{a.message}</div>)
            ) : (
              <div>The document could not be processed. Try re-uploading the file.</div>
            )}
          </div>
        )}

        {status === "NEEDS_REVIEW" && alerts.length > 0 && (
          <div className="space-y-1 text-xs text-amber-300 bg-amber-500/5 border border-amber-500/20 rounded-lg p-3">
            {alerts.map((a, idx) => (
              <div key={idx}>{a.message}</div>
            ))}
            <Link
              href={`/invoices/outbound-review/${invoiceId}`}
              className="inline-block mt-1 text-[#3B82F6] hover:text-[#3B82F6]/80 font-bold"
            >
              Open Outbound Auditor Console &rarr;
            </Link>
          </div>
        )}

        {canConfirm && (
          <button
            onClick={handleConfirmSend}
            disabled={isConfirming}
            className="w-full flex items-center justify-center gap-2 py-2.5 px-4 rounded-lg text-xs font-semibold border border-emerald-500/50 bg-emerald-600/20 text-emerald-300 hover:bg-emerald-600/40 transition-colors disabled:opacity-50"
          >
            {isConfirming ? <Loader2 className="w-4 h-4 animate-spin" /> : <Send className="w-4 h-4" />}
            Confirm &amp; Send
          </button>
        )}
      </div>

      {/* Gap 134: Live per-stage scrolling log terminal for outbound processing */}
      <LogTerminal batchId={invoiceId} />
    </div>
  );
}
