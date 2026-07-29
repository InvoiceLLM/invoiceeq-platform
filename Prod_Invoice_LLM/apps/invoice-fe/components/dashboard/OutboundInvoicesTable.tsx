"use client";

import React from "react";
import { CheckCircle, AlertCircle, Loader2, Send, Eye } from "lucide-react";
import Link from "next/link";
import { formatCurrency, formatDate } from "../../lib/utils";

export interface OutboundInvoiceRecord {
  id: string;
  invoice_number?: string;
  customer_name?: string;
  invoice_date?: string;
  grand_total?: number;
  status: string;
  is_overdue?: boolean;
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
  activeTab,
  onTabChange,
  currentPage,
  totalPages,
  totalCount,
  onPageChange,
}: OutboundInvoicesTableProps) {
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
                  </td>
                  <td className="px-6 py-4">
                    <span className="font-semibold text-slate-200">
                      {inv.customer_name || (inv.status === "PROCESSING_OCR" || inv.status === "EXTRACTING_DATA" ? "Processing..." : "Unknown Customer")}
                    </span>
                  </td>
                  <td className="px-6 py-4 font-medium text-slate-400">{formatDate(inv.invoice_date)}</td>
                  <td className="px-6 py-4 font-bold text-slate-200 font-mono">{formatCurrency(inv.grand_total)}</td>
                  <td className="px-6 py-4">{getStatusBadge(inv)}</td>
                  <td className="px-6 py-4 text-right">
                    <Link
                      href={`/invoices/outbound-review/${inv.id}`}
                      className="inline-flex items-center gap-1 text-xs text-[#3B82F6] hover:text-[#3B82F6]/80 font-semibold"
                    >
                      <Eye className="w-3.5 h-3.5" />
                    </Link>
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
