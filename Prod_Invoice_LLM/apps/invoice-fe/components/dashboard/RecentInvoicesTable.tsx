"use client";

import React, { useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import {
  FileText,
  MoreHorizontal,
  AlertCircle,
  CheckCircle,
  Loader2,
  Eye,
  FileDown,
  Trash2,
  ChevronLeft,
  ChevronRight,
  XCircle
} from "lucide-react";
import { formatCurrency, formatDate } from "../../lib/utils";
import { apiClient } from "../../lib/apiClient";

export interface InvoiceRecord {
  id: string;
  invoice_number?: string;
  vendor_name?: string;
  invoice_date?: string;
  /**
   * Gap 202: Ingest date — when the invoice was uploaded / created in the system.
   */
  created_at?: string;
  /**
   * Gap 202: Payment due date from the extracted invoice data.
   */
  due_date?: string;
  grand_total?: number;
  /**
   * FE Gap 183: ISO-4217 code from Invoice.currency. The backend has always
   * returned it (GET /invoices responds with the full ORM row); this type just
   * never declared it, so every amount rendered as "$".
   */
  currency?: string | null;
  status: string;
  tags?: string[];
}

// FE Gap 5: status-based sub-tabs. "Pending" covers everything not yet
// finalized as Paid/Rejected (Processing, Completed, Audit Required,
// Duplicate) -- matches the AP mental model of "still in the pipeline"
// vs. a closed-out invoice, rather than mapping 1:1 to every raw status enum.
export type StatusTab = "all" | "audit_required" | "paid" | "pending" | "rejected";

interface RecentInvoicesTableProps {
  invoices: InvoiceRecord[];
  isLoading: boolean;
  onDelete?: (id: string) => void;
  onStatusChange?: (id: string, newStatus: string) => void;
  activeTab: StatusTab;
  onTabChange: (tab: StatusTab) => void;
  currentPage: number;
  totalPages: number;
  totalCount: number;
  onPageChange: (page: number) => void;
  isFullPage?: boolean;
}

const STATUS_TABS: { key: StatusTab; label: string }[] = [
  { key: "all", label: "All" },
  { key: "audit_required", label: "Review Required" },
  { key: "paid", label: "Paid" },
  { key: "pending", label: "Pending" },
  { key: "rejected", label: "Rejected" },
];

export default function RecentInvoicesTable({
  invoices = [],
  isLoading,
  onDelete,
  onStatusChange,
  activeTab,
  onTabChange,
  currentPage,
  totalPages,
  totalCount,
  onPageChange,
  isFullPage = false,
}: RecentInvoicesTableProps) {
  const [activeMenuId, setActiveMenuId] = useState<string | null>(null);
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const [markingPaidId, setMarkingPaidId] = useState<string | null>(null);
  const router = useRouter();

  // FE Gap 29: `invoices` is now a single real server-paginated page (already
  // filtered by activeTab and limited/offset by currentPage on the backend),
  // not a client-fetched batch that gets re-sliced/re-filtered here.
  const pageInvoices = invoices;

  const handleMarkPaid = async (inv: InvoiceRecord, e: React.MouseEvent) => {
    e.stopPropagation();
    setActiveMenuId(null);
    const label = inv.invoice_number || inv.id;
    if (!window.confirm(`Mark invoice ${label} as paid? This records payment and updates the status to PAID.`)) {
      return;
    }
    setMarkingPaidId(inv.id);
    try {
      await apiClient.put(`/audit/resolve/${inv.id}`, {
        status: "PAID",
        dismissed_alerts: [],
      });
      onStatusChange?.(inv.id, "PAID");
    } catch (err) {
      console.error("Failed to mark invoice as paid", err);
      window.alert("Failed to mark invoice as paid. Please try again.");
    } finally {
      setMarkingPaidId(null);
    }
  };

  const handleDelete = async (inv: InvoiceRecord, e: React.MouseEvent) => {
    e.stopPropagation();
    setActiveMenuId(null);
    const label = inv.invoice_number || inv.id;
    if (!window.confirm(`Delete invoice ${label}? This permanently removes the PDF, extracted data, and indexed chat content.`)) {
      return;
    }
    setDeletingId(inv.id);
    try {
      await apiClient.delete(`/invoices/${inv.id}`);
      onDelete?.(inv.id);
    } catch (err) {
      console.error("Failed to delete invoice", err);
      window.alert("Failed to delete invoice. Please try again.");
    } finally {
      setDeletingId(null);
    }
  };

  const getStatusBadge = (status: string) => {
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
      case "PROCESSING":
      default:
        return (
          <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-semibold bg-sky-500/10 border border-sky-500/25 text-sky-400">
            <Loader2 className="w-3.5 h-3.5 animate-spin" />
            Processing
          </span>
        );
    }
  };

  const toggleMenu = (id: string, e: React.MouseEvent) => {
    e.stopPropagation();
    setActiveMenuId(activeMenuId === id ? null : id);
  };

  // Close menus on click outside
  React.useEffect(() => {
    const closeMenus = () => setActiveMenuId(null);
    if (typeof window !== "undefined") {
      window.addEventListener("click", closeMenus);
    }
    return () => {
      if (typeof window !== "undefined") {
        window.removeEventListener("click", closeMenus);
      }
    };
  }, []);

  return (
    <div className="glass-panel rounded-xl overflow-hidden flex flex-col h-full border border-[#222D3D]">
      {/* Table Header Section */}
      <div className="p-6 border-b border-[#222D3D] flex items-center justify-between">
        <div>
          <h3 className="text-sm font-semibold text-white tracking-wide">
            Recent Invoices
          </h3>
          <p className="text-xs text-slate-400">
            Audit history status and processing ledger.
          </p>
        </div>

        {/* FE Gap 5: status-based sub-tabs */}
        <div className="flex items-center gap-1 bg-[#0B0F19] border border-[#222D3D] rounded-lg p-1">
          {STATUS_TABS.map((tab) => (
            <button
              key={tab.key}
              onClick={() => onTabChange(tab.key)}
              className={`px-3 py-1.5 text-xs font-medium rounded-md transition-colors ${
                activeTab === tab.key
                  ? "bg-[#3B82F6] text-white"
                  : "text-slate-400 hover:text-slate-200"
              }`}
            >
              {tab.label}
            </button>
          ))}
        </div>
      </div>

      {/* FE Gap 11: scroll-lock container -- fixed-height card with internal scroll */}
      <div className="overflow-x-auto overflow-y-auto" style={isFullPage ? {} : { maxHeight: 320 }}>
        <table className="w-full text-left border-collapse">
          <thead>
            <tr className="sticky top-0 z-10 border-b border-[#222D3D] bg-[#0F172A] text-slate-400 text-[10px] font-bold uppercase tracking-wider select-none">
              <th className={`${isFullPage ? "px-3 lg:px-4" : "px-6"} py-3.5`}>Invoice #</th>
              <th className={`${isFullPage ? "px-3 lg:px-4" : "px-6"} py-3.5`}>Client / Vendor</th>
              <th className={`${isFullPage ? "px-3 lg:px-4" : "px-6"} py-3.5`}>Issue Date</th>
              {/* Gap 202: Ingest Date column */}
              <th className={`${isFullPage ? "px-3 lg:px-4" : "px-6"} py-3.5`}>Ingest Date</th>
              {/* Gap 202: Payment Due Date column */}
              <th className={`${isFullPage ? "px-3 lg:px-4" : "px-6"} py-3.5`}>Due Date</th>
              <th className={`${isFullPage ? "px-3 lg:px-4" : "px-6"} py-3.5`}>Amount</th>
              <th className={`${isFullPage ? "px-3 lg:px-4" : "px-6"} py-3.5`}>AI Status</th>
              <th className={`${isFullPage ? "px-3 lg:px-4" : "px-6"} py-3.5 text-right`}>Actions</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-[#222D3D]/50 text-slate-300 text-xs">
            {isLoading ? (
              [...Array(5)].map((_, idx) => (
                <tr key={idx} className="animate-pulse">
                  <td className="px-6 py-4"><div className="h-4 bg-slate-800 rounded w-16"></div></td>
                  <td className="px-6 py-4"><div className="h-4 bg-slate-800 rounded w-32"></div></td>
                  <td className="px-6 py-4"><div className="h-4 bg-slate-800 rounded w-20"></div></td>
                  <td className="px-6 py-4"><div className="h-4 bg-slate-800 rounded w-20"></div></td>
                  <td className="px-6 py-4"><div className="h-4 bg-slate-800 rounded w-20"></div></td>
                  <td className="px-6 py-4"><div className="h-4 bg-slate-800 rounded w-16"></div></td>
                  <td className="px-6 py-4"><div className="h-6 bg-slate-800 rounded w-24"></div></td>
                  <td className="px-6 py-4 text-right"><div className="h-4 bg-slate-800 rounded w-8 ml-auto"></div></td>
                </tr>
              ))
            ) : pageInvoices.length === 0 ? (
              <tr>
                <td colSpan={8} className="px-6 py-8 text-center text-slate-500">
                  No invoices matched the active filters.
                </td>
              </tr>
            ) : (
              pageInvoices.map((inv) => (
                <tr
                  key={inv.id}
                  // Gap 206: entire row is clickable — navigates to the Auditor Review Console
                  onClick={() => router.push(`/invoices/review/${inv.id}`)}
                  className={`hover:bg-slate-900/30 transition-colors duration-150 group cursor-pointer ${activeMenuId === inv.id ? "relative z-30" : ""}`}
                >
                  {/* Invoice # */}
                  <td className={`${isFullPage ? "px-3 lg:px-4" : "px-6"} py-4 font-mono font-medium text-white group-hover:text-[#3B82F6] transition-colors`}>
                    {inv.invoice_number || "INV-PENDING"}
                  </td>
                  
                  {/* Client / Vendor */}
                  <td className={`${isFullPage ? "px-3 lg:px-4" : "px-6"} py-4`}>
                    <span className="font-semibold text-slate-200">
                      {inv.vendor_name || (inv.status === "PROCESSING" ? "Processing Vendor..." : "Unknown Vendor")}
                    </span>
                    {inv.tags && inv.tags.length > 0 && (
                      <div className="flex flex-wrap gap-1 opacity-0 max-h-0 overflow-hidden group-hover:opacity-100 group-hover:max-h-16 group-hover:mt-1.5 transition-all duration-300 ease-in-out">
                        {inv.tags.map((t) => (
                          <span 
                            key={t}
                            className="text-[9px] bg-slate-800 px-1.5 py-0.5 rounded text-slate-400 border border-[#222D3D]"
                          >
                            #{t.replace(/^#/, "")}
                          </span>
                        ))}
                      </div>
                    )}
                  </td>
                  
                  {/* Issue Date */}
                  <td className={`${isFullPage ? "px-3 lg:px-4" : "px-6"} py-4 font-medium text-slate-400`}>
                    {formatDate(inv.invoice_date)}
                  </td>

                  {/* Gap 202: Ingest Date */}
                  <td className={`${isFullPage ? "px-3 lg:px-4" : "px-6"} py-4 font-medium text-slate-400`}>
                    {inv.created_at ? formatDate(inv.created_at) : "—"}
                  </td>

                  {/* Gap 202: Payment Due Date */}
                  <td className={`${isFullPage ? "px-3 lg:px-4" : "px-6"} py-4 font-medium text-slate-400`}>
                    {inv.due_date ? formatDate(inv.due_date) : "—"}
                  </td>
                  
                  {/* Amount */}
                  <td className={`${isFullPage ? "px-3 lg:px-4" : "px-6"} py-4 font-bold text-slate-200 font-mono`}>
                    {formatCurrency(inv.grand_total, inv.currency)}
                  </td>
                  
                  {/* AI Status */}
                  <td className={`${isFullPage ? "px-3 lg:px-4" : "px-6"} py-4`}>
                    {getStatusBadge(inv.status)}
                  </td>
                  
                  {/* Actions Dropdown — Gap 153: dropdown opens upward only on the last rows;
                      for row 1 (first row visible), we switch to open downward using a
                      data-driven position class so the menu never clips against the sticky header. */}
                  <td
                    className={`${isFullPage ? "px-3 lg:px-4" : "px-6"} py-4 text-right relative`}
                    // prevent row click when interacting with actions
                    onClick={(e) => e.stopPropagation()}
                  >
                    <button
                      onClick={(e) => toggleMenu(inv.id, e)}
                      className="p-1.5 rounded-lg hover:bg-slate-800 text-slate-400 hover:text-white transition-colors"
                    >
                      <MoreHorizontal className="w-4 h-4" />
                    </button>
                    
                    {activeMenuId === inv.id && (
                      <div 
                        className="absolute right-6 w-44 bg-[#0F172A] border border-[#222D3D] rounded-lg shadow-2xl py-1 z-50 animate-in fade-in duration-150 text-left"
                        style={{
                          // Gap 153: calculate whether there is room to open upward.
                          // If the row is one of the first 2 visible rows, open downward (top-full)
                          // to avoid clipping against the sticky header.
                          top: pageInvoices.indexOf(inv) < 2 ? "100%" : "auto",
                          bottom: pageInvoices.indexOf(inv) < 2 ? "auto" : "100%",
                          marginTop: pageInvoices.indexOf(inv) < 2 ? "4px" : undefined,
                          marginBottom: pageInvoices.indexOf(inv) < 2 ? undefined : "4px",
                        }}
                        onClick={(e) => e.stopPropagation()}
                      >
                        <Link
                          href={`/invoices/review/${inv.id}`}
                          className="w-full flex items-center gap-2 px-3 py-1.5 text-xs text-slate-300 hover:bg-[#1E293B] hover:text-white transition-colors"
                        >
                          <Eye className="w-3.5 h-3.5 text-[#3B82F6]" />
                          Auditor Review Console
                        </Link>
                        
                        <a
                          href={`/api/invoices/${inv.id}/pdf`}
                          target="_blank"
                          rel="noreferrer"
                          className="w-full flex items-center gap-2 px-3 py-1.5 text-xs text-slate-300 hover:bg-[#1E293B] hover:text-white transition-colors"
                        >
                          <FileDown className="w-3.5 h-3.5 text-slate-400" />
                          Download Original PDF
                        </a>

                        {inv.status?.toUpperCase() !== "PAID" && inv.status?.toUpperCase() !== "REJECTED" && (
                          <button
                            type="button"
                            disabled={markingPaidId === inv.id}
                            onClick={(e) => handleMarkPaid(inv, e)}
                            className="w-full flex items-center gap-2 px-3 py-1.5 text-xs text-emerald-400 hover:bg-emerald-500/10 hover:text-emerald-300 transition-colors disabled:opacity-50 disabled:cursor-wait"
                          >
                            <CheckCircle className="w-3.5 h-3.5" />
                            {markingPaidId === inv.id ? "Marking Paid..." : "Mark as Paid"}
                          </button>
                        )}

                        <div className="h-px bg-[#222D3D] my-1" />

                        <button
                          type="button"
                          disabled={deletingId === inv.id}
                          onClick={(e) => handleDelete(inv, e)}
                          className="w-full flex items-center gap-2 px-3 py-1.5 text-xs text-rose-400 hover:bg-rose-500/10 hover:text-rose-300 transition-colors disabled:opacity-50 disabled:cursor-wait"
                        >
                          <Trash2 className="w-3.5 h-3.5" />
                          {deletingId === inv.id ? "Deleting..." : "Delete Invoice"}
                        </button>
                      </div>
                    )}
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>

      {/* FE Gap 29: real server-backed pagination -- Previous/Next now fetch the
          next limit/offset page from the backend rather than re-slicing an
          already-fetched fixed batch, so invoices past the first page are
          actually reachable. */}
      {!isLoading && totalPages > 1 && (
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
      )}
    </div>
  );
}
