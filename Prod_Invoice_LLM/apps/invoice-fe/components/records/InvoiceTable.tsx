// =============================================================================
// FILE: components/records/InvoiceTable.tsx
// FEATURE: FE Feature 22 Task 22.2 — one invoice table for both directions,
//          replacing components/dashboard/RecentInvoicesTable.tsx (inbound) and
//          components/dashboard/OutboundInvoicesTable.tsx (outbound).
//
// WHY ONE COMPONENT: Records' "Invoices in" and "Invoices out" tabs are the same
// ledger seen from two sides. Both old tables already shared the frame — panel,
// header, status-tab strip, sticky header row, skeleton, empty row — and
// differed only in columns, row content, badge vocabulary and footer. The shared
// frame is written once here; what genuinely differs per direction lives in
// `DIRECTIONS` and the two row renderers.
//
// PARITY IS PROVEN, NOT CLAIMED: tests/unit/invoice-table-parity.test.tsx
// compares this component's markup against snapshots recorded from the two OLD
// components before they were removed. Change the markup deliberately, and
// re-record deliberately.
//
// Everything each old table documented still holds and is kept beside the code
// it explains: FE Gap 29 (server pagination), FE Gap 5 / Task 4.1.5 (status
// tabs), Gap 202 (ingest + due date), Gap 206 (row click), FE Gap 318 (inline
// row actions), Gap 282 (outbound delete reuses inbound's endpoint), Feature 20
// (lineage + clone eligibility), FE Gap 183 (per-row currency).
// =============================================================================
"use client";

import React, { useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import {
  AlertCircle,
  CheckCircle,
  Loader2,
  Eye,
  Trash2,
  ChevronLeft,
  ChevronRight,
  XCircle,
  Clock,
  RotateCcw,
  Send,
  FilePlus2,
  GitBranch,
} from "lucide-react";
import { formatCurrency, formatDate } from "@/lib/utils";
import { apiClient } from "@/lib/apiClient";
import { canCloneSource } from "@/types/invoice";

// -----------------------------------------------------------------------------
// Shapes
// -----------------------------------------------------------------------------

/** A row of `GET /invoices` (inbound). */
export interface InvoiceRecord {
  id: string;
  invoice_number?: string;
  vendor_name?: string;
  invoice_date?: string;
  /** Gap 202: Ingest date — when the invoice was uploaded / created in the system. */
  created_at?: string;
  /** Gap 202: Payment due date from the extracted invoice data. */
  due_date?: string;
  grand_total?: number;
  /**
   * FE Gap 183: ISO-4217 code from Invoice.currency. The backend has always
   * returned it (GET /invoices responds with the full ORM row); the old type
   * never declared it, so every amount rendered as "$".
   */
  currency?: string | null;
  status: string;
  tags?: string[];
}

/** A row of `GET /outbound-dashboard/invoices`. */
export interface OutboundInvoiceRecord {
  id: string;
  invoice_number?: string;
  customer_name?: string;
  invoice_date?: string;
  grand_total?: number;
  /** FE Gap 183: added explicitly to that endpoint's hand-built response dict. */
  currency?: string | null;
  status: string;
  is_overdue?: boolean;
  /**
   * Feature 20 lineage pointer (BE task 17.7). Present only on rows the Invoice
   * Builder created; `null`/absent on every uploaded row.
   */
  source_invoice_id?: string | null;
}

// FE Gap 5: "Pending" covers everything not yet finalized as Paid/Rejected
// (Processing, Completed, Audit Required, Duplicate) — the AP mental model of
// "still in the pipeline" vs. a closed-out invoice.
export type StatusTab = "all" | "audit_required" | "paid" | "pending" | "rejected";

// Task 4.1.5: mirrors inbound's shape — "Pending" bundles every in-flight
// status, "Overdue" plays the exception-tab role inbound's "Rejected" plays.
export type OutboundStatusTab = "all" | "pending" | "paid" | "overdue";

interface CommonProps {
  isLoading: boolean;
  /** Called after a successful delete so the owning ledger can refetch its page. */
  onDelete?: (id: string) => void;
  currentPage: number;
  totalPages: number;
  totalCount: number;
  onPageChange: (page: number) => void;
}

export type InvoiceTableProps =
  | (CommonProps & {
      direction: "in";
      invoices: InvoiceRecord[];
      activeTab: StatusTab;
      onTabChange: (tab: StatusTab) => void;
      onStatusChange?: (id: string, newStatus: string) => void;
      /** The Audit Queue / Records page: tighter cell padding, no height cap. */
      isFullPage?: boolean;
    })
  | (CommonProps & {
      direction: "out";
      invoices: OutboundInvoiceRecord[];
      activeTab: OutboundStatusTab;
      onTabChange: (tab: OutboundStatusTab) => void;
      /**
       * Opens the Invoice Builder in place (Records' drawer). When absent the
       * clone action is a link to `/invoices/outbound-builder`, as it always was.
       */
      onCloneInvoice?: (sourceId: string) => void;
    });

// -----------------------------------------------------------------------------
// What differs per direction, as data
// -----------------------------------------------------------------------------

const DIRECTIONS = {
  in: {
    title: "Recent Invoices",
    subtitle: "Audit history status and processing ledger.",
    tabs: [
      { key: "all", label: "All" },
      { key: "audit_required", label: "Review Required" },
      { key: "paid", label: "Paid" },
      { key: "pending", label: "Pending" },
      { key: "rejected", label: "Rejected" },
    ],
    // Gap 202 added Ingest Date and Due Date.
    columns: ["Invoice #", "Client / Vendor", "Issue Date", "Ingest Date", "Due Date", "Amount", "AI Status"],
    skeletonRows: 5,
    skeletonWidths: ["w-16", "w-32", "w-20", "w-20", "w-20", "w-16"],
    emptyText: "No invoices matched the active filters.",
    deleteConfirm: (label: string) =>
      `Delete invoice ${label}? This permanently removes the PDF, extracted data, and indexed chat content.`,
    deleteLog: "Failed to delete invoice",
  },
  out: {
    title: "Outbound Invoices",
    subtitle: "Invoices sent to customers, pre-send validation ledger.",
    tabs: [
      { key: "all", label: "All" },
      { key: "pending", label: "Pending" },
      { key: "paid", label: "Paid" },
      { key: "overdue", label: "Overdue" },
    ],
    columns: ["Invoice #", "Customer", "Issue Date", "Amount", "Status"],
    skeletonRows: 3,
    skeletonWidths: ["w-16", "w-32", "w-20", "w-16"],
    emptyText: "No outbound invoices matched the active filters.",
    // Gap 282: outbound invoices are rows in the same `Invoice` table, so delete
    // reuses inbound's soft-delete endpoint rather than a duplicate one.
    deleteConfirm: (label: string) =>
      `Delete outbound invoice ${label}? It will be removed from your outbound ledger, dashboards and reports. The record and its audit history are retained.`,
    deleteLog: "Failed to delete outbound invoice",
  },
} as const;

// -----------------------------------------------------------------------------
// Status badges — each direction's own vocabulary
// -----------------------------------------------------------------------------

function inboundStatusBadge(status: string) {
  const rawStatus = (status || "PROCESSING").toUpperCase();

  switch (rawStatus) {
    case "PAID":
      return (
        <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-semibold bg-emerald-500/10 border border-emerald-500/25 text-emerald-400">
          <CheckCircle className="w-3.5 h-3.5" />
          Paid
        </span>
      );
    case "COMPLETED":
      return (
        <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-semibold bg-teal-500/10 border border-teal-500/25 text-teal-400">
          <CheckCircle className="w-3.5 h-3.5" />
          Completed
        </span>
      );
    case "AUDIT_REQUIRED":
      return (
        <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-semibold bg-amber-500/10 border border-amber-500/25 text-amber-400">
          <AlertCircle className="w-3.5 h-3.5" />
          Review Required
        </span>
      );
    case "DUPLICATE":
      return (
        <span
          title="Duplicate file content detected. Copied details from previous upload."
          className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-semibold bg-amber-500/10 border border-amber-500/25 text-amber-400 cursor-help"
        >
          <AlertCircle className="w-3.5 h-3.5" />
          Duplicate
        </span>
      );
    case "FAILED":
      return (
        <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-semibold bg-rose-500/10 border border-rose-500/25 text-rose-400">
          <AlertCircle className="w-3.5 h-3.5" />
          Failed
        </span>
      );
    case "REJECTED":
      return (
        <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-semibold bg-rose-500/10 border border-rose-500/25 text-rose-400">
          <XCircle className="w-3.5 h-3.5" />
          Rejected
        </span>
      );
    case "REVIEW_LATER":
      return (
        <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-semibold bg-sky-500/10 border border-sky-500/25 text-sky-400">
          <Clock className="w-3.5 h-3.5" />
          Review Later
        </span>
      );
    case "NEEDS_RESUBMISSION":
      return (
        <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-semibold bg-orange-500/10 border border-orange-500/25 text-orange-400">
          <RotateCcw className="w-3.5 h-3.5" />
          Needs Resubmission
        </span>
      );
    case "PROCESSING":
    default:
      return (
        <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-semibold bg-sky-500/10 border border-sky-500/25 text-sky-400">
          <Loader2 className="w-3.5 h-3.5 animate-spin" />
          Processing
        </span>
      );
  }
}

function outboundStatusBadge(inv: OutboundInvoiceRecord) {
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
}

// -----------------------------------------------------------------------------
// The table
// -----------------------------------------------------------------------------

export default function InvoiceTable(props: InvoiceTableProps) {
  const { direction, isLoading, onDelete, currentPage, totalPages, totalCount, onPageChange } = props;
  const spec = DIRECTIONS[direction];
  const isFullPage = props.direction === "in" && Boolean(props.isFullPage);
  // Full-page inbound tightens cell padding; every other variant keeps px-6.
  const pad = isFullPage ? "px-3 lg:px-4" : "px-6";

  const [deletingId, setDeletingId] = useState<string | null>(null);
  const router = useRouter();

  const handleDelete = async (inv: { id: string; invoice_number?: string }) => {
    const label = inv.invoice_number || inv.id;
    if (!window.confirm(spec.deleteConfirm(label))) {
      return;
    }
    setDeletingId(inv.id);
    try {
      await apiClient.delete(`/invoices/${inv.id}`);
      onDelete?.(inv.id);
    } catch (err) {
      console.error(spec.deleteLog, err);
      window.alert("Failed to delete invoice. Please try again.");
    } finally {
      setDeletingId(null);
    }
  };

  const deleteButton = (inv: { id: string; invoice_number?: string }, ariaLabel: string, onClick: (e: React.MouseEvent) => void) => (
    <button
      type="button"
      disabled={deletingId === inv.id}
      onClick={onClick}
      title="Delete invoice"
      aria-label={ariaLabel}
      className="inline-flex items-center rounded-lg p-1.5 text-rose-400 transition-colors hover:bg-rose-500/10 hover:text-rose-300 disabled:cursor-wait disabled:opacity-50"
    >
      {deletingId === inv.id ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Trash2 className="w-3.5 h-3.5" />}
    </button>
  );

  // Gap 206: the whole inbound row opens the Auditor Review Console.
  const inboundRow = (inv: InvoiceRecord) => (
    <tr
      key={inv.id}
      onClick={() => router.push(`/invoices/review/${inv.id}`)}
      className="hover:bg-slate-900/30 transition-colors duration-150 group cursor-pointer"
    >
      <td className={`${pad} py-4 font-mono font-medium text-white group-hover:text-[#3B82F6] transition-colors`}>
        {inv.invoice_number || "INV-PENDING"}
      </td>

      <td className={`${pad} py-4`}>
        <span className="font-semibold text-slate-200">
          {inv.vendor_name || (inv.status === "PROCESSING" ? "Processing Vendor..." : "Unknown Vendor")}
        </span>
        {inv.tags && inv.tags.length > 0 && (
          <div className="flex flex-wrap gap-1 opacity-0 max-h-0 overflow-hidden group-hover:opacity-100 group-hover:max-h-16 group-hover:mt-1.5 transition-all duration-300 ease-in-out">
            {inv.tags.map((t) => (
              <span key={t} className="text-[9px] bg-slate-800 px-1.5 py-0.5 rounded text-slate-400 border border-[#222D3D]">
                #{t.replace(/^#/, "")}
              </span>
            ))}
          </div>
        )}
      </td>

      <td className={`${pad} py-4 font-medium text-slate-400`}>{formatDate(inv.invoice_date)}</td>
      <td className={`${pad} py-4 font-medium text-slate-400`}>{inv.created_at ? formatDate(inv.created_at) : "—"}</td>
      <td className={`${pad} py-4 font-medium text-slate-400`}>{inv.due_date ? formatDate(inv.due_date) : "—"}</td>
      <td className={`${pad} py-4 font-bold text-slate-200 font-mono`}>{formatCurrency(inv.grand_total, inv.currency)}</td>
      <td className={`${pad} py-4`}>{inboundStatusBadge(inv.status)}</td>

      {/* FE Gap 318: inline View/Delete icons. Mark as Paid and Download
          Original PDF stay inside the Auditor Review Console itself. */}
      <td className={`${pad} py-4 text-right`} onClick={(e) => e.stopPropagation()}>
        <div className="inline-flex items-center justify-end gap-1">
          <Link
            href={`/invoices/review/${inv.id}`}
            title="Open Auditor Review Console"
            aria-label={`Review invoice ${inv.invoice_number || inv.id}`}
            className="inline-flex items-center gap-1 rounded-lg p-1.5 text-xs font-semibold text-[#3B82F6] transition-colors hover:bg-slate-800 hover:text-[#3B82F6]/80"
          >
            <Eye className="w-3.5 h-3.5" />
          </Link>
          {deleteButton(inv, `Delete invoice ${inv.invoice_number || inv.id}`, (e) => {
            e.stopPropagation();
            handleDelete(inv);
          })}
        </div>
      </td>
    </tr>
  );

  const onCloneInvoice = props.direction === "out" ? props.onCloneInvoice : undefined;
  const cloneClass =
    "inline-flex items-center rounded-lg p-1.5 text-xs font-semibold text-blue-400 transition-colors hover:bg-slate-800 hover:text-blue-300";

  const outboundRow = (inv: OutboundInvoiceRecord) => (
    <tr key={inv.id} className="hover:bg-slate-900/30 transition-colors duration-150 group">
      <td className="px-6 py-4 font-mono font-medium text-white group-hover:text-[#3B82F6] transition-colors">
        {inv.invoice_number || "INV-PENDING"}
        {/* Feature 20: lineage, under the number — a mostly-empty column would cost every row. */}
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
          {inv.customer_name ||
            (inv.status === "PROCESSING_OCR" || inv.status === "EXTRACTING_DATA" ? "Processing..." : "Unknown Customer")}
        </span>
      </td>
      <td className="px-6 py-4 font-medium text-slate-400">{formatDate(inv.invoice_date)}</td>
      <td className="px-6 py-4 font-bold text-slate-200 font-mono">{formatCurrency(inv.grand_total, inv.currency)}</td>
      <td className="px-6 py-4">{outboundStatusBadge(inv)}</td>
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
              (VERIFIED/SENT/PAID/OVERDUE) so the action is not offered on a
              row the builder would 409 on. */}
          {canCloneSource(inv.status, inv.is_overdue) &&
            (onCloneInvoice ? (
              <button
                type="button"
                onClick={() => onCloneInvoice(inv.id)}
                data-testid={`clone-invoice-${inv.id}`}
                title="New invoice from this"
                aria-label={`New invoice from outbound invoice ${inv.invoice_number || inv.id}`}
                className={cloneClass}
              >
                <FilePlus2 className="w-3.5 h-3.5" />
              </button>
            ) : (
              <Link
                href={`/invoices/outbound-builder?source=${inv.id}`}
                data-testid={`clone-invoice-${inv.id}`}
                title="New invoice from this"
                aria-label={`New invoice from outbound invoice ${inv.invoice_number || inv.id}`}
                className={cloneClass}
              >
                <FilePlus2 className="w-3.5 h-3.5" />
              </Link>
            ))}
          {deleteButton(inv, `Delete outbound invoice ${inv.invoice_number || inv.id}`, () => handleDelete(inv))}
        </div>
      </td>
    </tr>
  );

  const columnCount = spec.columns.length + 1;

  return (
    <div className="glass-panel rounded-xl overflow-hidden flex flex-col h-full border border-[#222D3D]">
      <div className="p-6 border-b border-[#222D3D] flex items-center justify-between">
        <div>
          <h3 className="text-sm font-semibold text-white tracking-wide">{spec.title}</h3>
          <p className="text-xs text-slate-400">{spec.subtitle}</p>
        </div>

        <div className="flex items-center gap-1 bg-[#0B0F19] border border-[#222D3D] rounded-lg p-1">
          {spec.tabs.map((tab) => (
            <button
              key={tab.key}
              onClick={() => (props.onTabChange as (tab: string) => void)(tab.key)}
              className={`px-3 py-1.5 text-xs font-medium rounded-md transition-colors ${
                props.activeTab === tab.key ? "bg-[#3B82F6] text-white" : "text-slate-400 hover:text-slate-200"
              }`}
            >
              {tab.label}
            </button>
          ))}
        </div>
      </div>

      {/* FE Gap 11: scroll-lock container — a capped card with internal scroll, except on the full page. */}
      <div className="overflow-x-auto overflow-y-auto" style={isFullPage ? {} : { maxHeight: 320 }}>
        <table className="w-full text-left border-collapse">
          <thead>
            <tr className="sticky top-0 z-10 border-b border-[#222D3D] bg-[#0F172A] text-slate-400 text-[10px] font-bold uppercase tracking-wider select-none">
              {spec.columns.map((column) => (
                <th key={column} className={`${pad} py-3.5`}>
                  {column}
                </th>
              ))}
              <th className={`${pad} py-3.5 text-right`}>Actions</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-[#222D3D]/50 text-slate-300 text-xs">
            {isLoading ? (
              [...Array(spec.skeletonRows)].map((_, idx) => (
                <tr key={idx} className="animate-pulse">
                  {spec.skeletonWidths.map((width, cell) => (
                    <td key={cell} className="px-6 py-4">
                      <div className={`h-4 bg-slate-800 rounded ${width}`}></div>
                    </td>
                  ))}
                  <td className="px-6 py-4">
                    <div className="h-6 bg-slate-800 rounded w-24"></div>
                  </td>
                  <td className="px-6 py-4 text-right">
                    <div className="h-4 bg-slate-800 rounded w-8 ml-auto"></div>
                  </td>
                </tr>
              ))
            ) : props.invoices.length === 0 ? (
              <tr>
                <td colSpan={columnCount} className="px-6 py-8 text-center text-slate-500">
                  {spec.emptyText}
                </td>
              </tr>
            ) : props.direction === "in" ? (
              // FE Gap 29: already one server-paginated, server-filtered page.
              props.invoices.map(inboundRow)
            ) : (
              props.invoices.map(outboundRow)
            )}
          </tbody>
        </table>
      </div>

      {direction === "in"
        ? // FE Gap 29: real server-backed pagination, shown only when there is a second page.
          !isLoading &&
          totalPages > 1 && (
            <div className="flex items-center justify-between px-6 py-3 border-t border-[#222D3D] text-xs text-slate-400">
              <span>
                Page {currentPage} of {totalPages} ({totalCount} invoices)
              </span>
              <div className="flex items-center gap-2">
                <button
                  onClick={() => onPageChange(Math.max(1, currentPage - 1))}
                  disabled={currentPage === 1}
                  className="flex items-center gap-1 px-2.5 py-1.5 rounded-lg border border-[#222D3D] text-slate-300 hover:bg-slate-800 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
                >
                  <ChevronLeft className="w-3.5 h-3.5" /> Previous
                </button>
                <button
                  onClick={() => onPageChange(Math.min(totalPages, currentPage + 1))}
                  disabled={currentPage === totalPages}
                  className="flex items-center gap-1 px-2.5 py-1.5 rounded-lg border border-[#222D3D] text-slate-300 hover:bg-slate-800 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
                >
                  Next <ChevronRight className="w-3.5 h-3.5" />
                </button>
              </div>
            </div>
          )
        : (
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
              <span>
                Page {currentPage} of {totalPages}
              </span>
              <button
                onClick={() => onPageChange(Math.min(totalPages, currentPage + 1))}
                disabled={currentPage >= totalPages}
                className="px-2.5 py-1 rounded-md border border-[#222D3D] hover:bg-slate-800 disabled:opacity-40 disabled:cursor-not-allowed"
              >
                Next
              </button>
            </div>
          </div>
        )}
    </div>
  );
}
