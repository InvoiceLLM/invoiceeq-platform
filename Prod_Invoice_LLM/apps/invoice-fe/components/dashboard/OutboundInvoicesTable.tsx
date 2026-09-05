"use client";

import React, { useState } from "react";
import { CheckCircle, AlertCircle, Loader2, Send, Eye, Trash2, FilePlus2, GitBranch } from "lucide-react";
import Link from "next/link";
import { formatCurrency, formatDate } from "../../lib/utils";
import { apiClient } from "../../lib/apiClient";
import { canCloneSource } from "../../types/invoice";

export interface OutboundInvoiceRecord {
  id: string;
  invoice_number?: string;
  customer_name?: string;
  invoice_date?: string;
  grand_total?: number;
  /**
   * FE Gap 183: ISO-4217 code from Invoice.currency, now returned by
   * GET /outbound-dashboard/invoices (that endpoint hand-builds its response
   * dict, so the field had to be added there explicitly).
   */
  currency?: string | null;
  status: string;
  is_overdue?: boolean;
  /**
   * Feature 20 lineage pointer, added to this endpoint's hand-built response
   * dict by BE task 17.7. Present only on rows the Invoice Builder created;
   * `null`/absent on every uploaded row, including every row that predates the
   * builder.
   */
  source_invoice_id?: string | null;
}

// Task 4.1.5: 4-tab shape mirroring inbound's All/Paid/Pending/Rejected --
// "Pending" bundles every in-flight status (not yet closed out), "Overdue"
// plays the role inbound's "Rejected" plays (a closed-out-ish exception tab),
// per the tab-grouping decision in feature_4.1_vendor_flow_auditor.md.
export type OutboundStatusTab = "all" | "pending" | "paid" | "overdue";

const STATUS_TABS: { key: OutboundStatusTab; label: string }[] = [
  { key: "all", label: "All" },
  { key: "pending", label: "Pending" },
  { key: "paid", label: "Paid" },
  { key: "overdue", label: "Overdue" },
];

interface OutboundInvoicesTableProps {
  invoices: OutboundInvoiceRecord[];
  isLoading: boolean;
  /**
   * Gap 282: called after a successful soft-delete so the owning page can
   * refetch the current page. Same contract as RecentInvoicesTable's `onDelete`.
   */
  onDelete?: (id: string) => void;
  activeTab: OutboundStatusTab;
  onTabChange: (tab: OutboundStatusTab) => void;
  currentPage: number;
  totalPages: number;
  totalCount: number;
  onPageChange: (page: number) => void;
}

export default function OutboundInvoicesTable({
  invoices = [],
  isLoading,
  onDelete,
  activeTab,
  onTabChange,
  currentPage,
  totalPages,
  totalCount,
  onPageChange,
}: OutboundInvoicesTableProps) {
  const [deletingId, setDeletingId] = useState<string | null>(null);

  /**
   * Gap 282: the outbound table had no delete affordance at all.
   *
   * No new backend endpoint was needed and none was added: outbound invoices
   * are rows in the *same* `Invoice` table as inbound ones, distinguished only
   * by `flow_direction == "OUTBOUND"`, and `routers/invoices.py::delete_invoice`
   * (Gap 192's soft delete — stamps `deleted_at`, keeps the row, the blob and
   * the AuditLog history, appends a DELETE_INVOICE entry) filters on id +
   * tenant only. `app/api/invoices/[id]/route.ts` already proxies DELETE.
   * So this reuses inbound's exact call, deliberately rather than inventing an
   * `/outbound-invoices/{id}` delete that would duplicate it.
   */
  const handleDelete = async (inv: OutboundInvoiceRecord) => {
    const label = inv.invoice_number || inv.id;
    if (
      !window.confirm(
        `Delete outbound invoice ${label}? It will be removed from your outbound ledger, dashboards and reports. The record and its audit history are retained.`
      )
    ) {
      return;
    }
    setDeletingId(inv.id);
    try {
      await apiClient.delete(`/invoices/${inv.id}`);
      onDelete?.(inv.id);
    } catch (err) {
      console.error("Failed to delete outbound invoice", err);
      window.alert("Failed to delete invoice. Please try again.");
    } finally {
      setDeletingId(null);
    }
  };

  const getStatusBadge = (inv: OutboundInvoiceRecord) => {
    if (inv.is_overdue) {
      return (
        <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-semibold bg-rose-500/10 border border-rose-500/25 text-rose-400">
          <AlertCircle className="w-3.5 h-3.5" />
          Overdue
        </span>
      );
    }
    switch (inv.status) {
      case "PAID":
        return (
          <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-semibold bg-emerald-500/10 border border-emerald-500/25 text-emerald-400">
            <CheckCircle className="w-3.5 h-3.5" />
            Paid
          </span>
        );
      case "SENT":
        return (
          <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-semibold bg-sky-500/10 border border-sky-500/25 text-sky-400">
            <Send className="w-3.5 h-3.5" />
            Sent
          </span>
        );
      case "NEEDS_REVIEW":
        return (
          <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-semibold bg-amber-500/10 border border-amber-500/25 text-amber-400">
            <AlertCircle className="w-3.5 h-3.5" />
            Needs Review
          </span>
        );
      case "VERIFIED":
        return (
          <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-semibold bg-emerald-500/10 border border-emerald-500/25 text-emerald-400">
            <CheckCircle className="w-3.5 h-3.5" />
            Verified
          </span>
        );
      default:
        return (
          <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-semibold bg-sky-500/10 border border-sky-500/25 text-sky-400">
            <Loader2 className="w-3.5 h-3.5 animate-spin" />
            {inv.status.replace("_", " ")}
          </span>
        );
    }
  };

  return (
    <div className="glass-panel rounded-xl overflow-hidden flex flex-col h-full border border-[#222D3D]">
      <div className="p-6 border-b border-[#222D3D] flex items-center justify-between">
        <div>
          <h3 className="text-sm font-semibold text-white tracking-wide">Outbound Invoices</h3>
          <p className="text-xs text-slate-400">Invoices sent to customers, pre-send validation ledger.</p>
        </div>
        <div className="flex items-center gap-1 bg-[#0B0F19] border border-[#222D3D] rounded-lg p-1">
          {STATUS_TABS.map((tab) => (
            <button
              key={tab.key}
              onClick={() => onTabChange(tab.key)}
              className={`px-3 py-1.5 text-xs font-medium rounded-md transition-colors ${
                activeTab === tab.key ? "bg-[#3B82F6] text-white" : "text-slate-400 hover:text-slate-200"
              }`}
            >
              {tab.label}
            </button>
          ))}
        </div>
      </div>

      <div className="overflow-x-auto overflow-y-auto" style={{ maxHeight: 320 }}>
        <table className="w-full text-left border-collapse">
          <thead>
            <tr className="sticky top-0 z-10 border-b border-[#222D3D] bg-[#0F172A] text-slate-400 text-[10px] font-bold uppercase tracking-wider select-none">
              <th className="px-6 py-3.5">Invoice #</th>
              <th className="px-6 py-3.5">Customer</th>
              <th className="px-6 py-3.5">Issue Date</th>
              <th className="px-6 py-3.5">Amount</th>
              <th className="px-6 py-3.5">Status</th>
              <th className="px-6 py-3.5 text-right">Actions</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-[#222D3D]/50 text-slate-300 text-xs">
            {isLoading ? (
              [...Array(3)].map((_, idx) => (
                <tr key={idx} className="animate-pulse">
                  <td className="px-6 py-4"><div className="h-4 bg-slate-800 rounded w-16"></div></td>
                  <td className="px-6 py-4"><div className="h-4 bg-slate-800 rounded w-32"></div></td>
                  <td className="px-6 py-4"><div className="h-4 bg-slate-800 rounded w-20"></div></td>
                  <td className="px-6 py-4"><div className="h-4 bg-slate-800 rounded w-16"></div></td>
                  <td className="px-6 py-4"><div className="h-6 bg-slate-800 rounded w-24"></div></td>
                  <td className="px-6 py-4 text-right"><div className="h-4 bg-slate-800 rounded w-8 ml-auto"></div></td>
                </tr>
              ))
            ) : invoices.length === 0 ? (
              <tr>
                <td colSpan={6} className="px-6 py-8 text-center text-slate-500">
                  No outbound invoices matched the active filters.
                </td>
              </tr>
            ) : (
              invoices.map((inv) => (
                <tr key={inv.id} className="hover:bg-slate-900/30 transition-colors duration-150 group">
                  <td className="px-6 py-4 font-mono font-medium text-white group-hover:text-[#3B82F6] transition-colors">
                    {inv.invoice_number || "INV-PENDING"}
                    {/* Feature 20: lineage. Shown under the number rather than
                        in its own column because it is present on a minority
                        of rows and a mostly-empty column costs every row. */}
                    {inv.source_invoice_id && (
                      <Link
                        href={`/invoices/outbound-review/${inv.source_invoice_id}`}
                        data-testid={`cloned-from-${inv.id}`}
                        title="Open the invoice this one was created from"
                        className="mt-1 flex items-center gap-1 font-sans text-[10px] font-medium text-slate-500 transition-colors hover:text-[#3B82F6]"
                      >
                        <GitBranch className="w-3 h-3" />
                        Cloned from
                      </Link>
                    )}
                  </td>
                  <td className="px-6 py-4">
                    <span className="font-semibold text-slate-200">
                      {inv.customer_name || (inv.status === "PROCESSING_OCR" || inv.status === "EXTRACTING_DATA" ? "Processing..." : "Unknown Customer")}
                    </span>
                  </td>
                  <td className="px-6 py-4 font-medium text-slate-400">{formatDate(inv.invoice_date)}</td>
                  <td className="px-6 py-4 font-bold text-slate-200 font-mono">{formatCurrency(inv.grand_total, inv.currency)}</td>
                  <td className="px-6 py-4">{getStatusBadge(inv)}</td>
                  <td className="px-6 py-4 text-right">
                    <div className="inline-flex items-center justify-end gap-1">
                      <Link
                        href={`/invoices/outbound-review/${inv.id}`}
                        title="Open Outbound Auditor Console"
                        aria-label={`Review outbound invoice ${inv.invoice_number || inv.id}`}
                        className="inline-flex items-center gap-1 rounded-lg p-1.5 text-xs font-semibold text-[#3B82F6] transition-colors hover:bg-slate-800 hover:text-[#3B82F6]/80"
                      >
                        <Eye className="w-3.5 h-3.5" />
                      </Link>
                      {/* Feature 20: clone. Eligibility mirrors BE decision D4
                          (VERIFIED/SENT/PAID/OVERDUE) so the action is not
                          offered on a row the builder would 409 on. */}
                      {canCloneSource(inv.status, inv.is_overdue) && (
                        <Link
                          href={`/invoices/outbound-builder?source=${inv.id}`}
                          data-testid={`clone-invoice-${inv.id}`}
                          title="New invoice from this"
                          aria-label={`New invoice from outbound invoice ${inv.invoice_number || inv.id}`}
                          className="inline-flex items-center rounded-lg p-1.5 text-xs font-semibold text-blue-400 transition-colors hover:bg-slate-800 hover:text-blue-300"
                        >
                          <FilePlus2 className="w-3.5 h-3.5" />
                        </Link>
                      )}
                      {/* Gap 282: delete action, previously absent from this table. */}
                      <button
                        type="button"
                        disabled={deletingId === inv.id}
                        onClick={() => handleDelete(inv)}
                        title="Delete invoice"
                        aria-label={`Delete outbound invoice ${inv.invoice_number || inv.id}`}
                        className="inline-flex items-center rounded-lg p-1.5 text-rose-400 transition-colors hover:bg-rose-500/10 hover:text-rose-300 disabled:cursor-wait disabled:opacity-50"
                      >
                        {deletingId === inv.id ? (
                          <Loader2 className="w-3.5 h-3.5 animate-spin" />
                        ) : (
                          <Trash2 className="w-3.5 h-3.5" />
                        )}
                      </button>
                    </div>
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>

      <div className="p-4 border-t border-[#222D3D] flex items-center justify-between text-xs text-slate-400">
        <span>{totalCount} total</span>
        <div className="flex items-center gap-2">
          <button
            onClick={() => onPageChange(Math.max(1, currentPage - 1))}
            disabled={currentPage <= 1}
            className="px-2.5 py-1 rounded-md border border-[#222D3D] hover:bg-slate-800 disabled:opacity-40 disabled:cursor-not-allowed"
          >
            Previous
          </button>
          <span>Page {currentPage} of {totalPages}</span>
          <button
            onClick={() => onPageChange(Math.min(totalPages, currentPage + 1))}
            disabled={currentPage >= totalPages}
            className="px-2.5 py-1 rounded-md border border-[#222D3D] hover:bg-slate-800 disabled:opacity-40 disabled:cursor-not-allowed"
          >
            Next
          </button>
        </div>
      </div>
    </div>
  );
}
