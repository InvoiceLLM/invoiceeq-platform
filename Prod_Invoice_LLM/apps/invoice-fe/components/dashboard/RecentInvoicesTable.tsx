"use client";

import React, { useState } from "react";
import Link from "next/link";
import { 
  FileText, 
  ExternalLink, 
  MoreHorizontal, 
  AlertCircle, 
  CheckCircle, 
  Loader2, 
  Eye, 
  FileDown 
} from "lucide-react";
import { formatCurrency, formatDate } from "../../lib/utils";

export interface InvoiceRecord {
  id: string;
  invoice_number?: string;
  vendor_name?: string;
  invoice_date?: string;
  grand_total?: number;
  status: string;
  tags?: string[];
}

interface RecentInvoicesTableProps {
  invoices: InvoiceRecord[];
  isLoading: boolean;
}

export default function RecentInvoicesTable({
  invoices = [],
  isLoading,
}: RecentInvoicesTableProps) {
  const [activeMenuId, setActiveMenuId] = useState<string | null>(null);

  const getStatusBadge = (status: string) => {
    const rawStatus = (status || "PROCESSING").toUpperCase();
    
    switch (rawStatus) {
      case "PAID":
      case "COMPLETED":
        return (
          <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-semibold bg-emerald-500/10 border border-emerald-500/25 text-emerald-400">
            <CheckCircle className="w-3.5 h-3.5" />
            Verified
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
        
        <Link 
          href="/audit"
          className="text-xs text-[#3B82F6] hover:text-[#3B82F6]/80 flex items-center gap-1 font-semibold transition-colors"
        >
          View all ledger
          <ExternalLink className="w-3.5 h-3.5" />
        </Link>
      </div>

      {/* Responsive Table Grid */}
      <div className="overflow-x-auto">
        <table className="w-full text-left border-collapse">
          <thead>
            <tr className="border-b border-[#222D3D] bg-slate-900/20 text-slate-400 text-[10px] font-bold uppercase tracking-wider select-none">
              <th className="px-6 py-3.5">Invoice #</th>
              <th className="px-6 py-3.5">Client / Vendor</th>
              <th className="px-6 py-3.5">Issue Date</th>
              <th className="px-6 py-3.5">Amount</th>
              <th className="px-6 py-3.5">AI Status</th>
              <th className="px-6 py-3.5 text-right">Actions</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-[#222D3D]/50 text-slate-300 text-xs">
            {isLoading ? (
              [...Array(5)].map((_, idx) => (
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
                  No invoices matched the active filters.
                </td>
              </tr>
            ) : (
              invoices.map((inv) => (
                <tr 
                  key={inv.id}
                  className="hover:bg-slate-900/30 transition-colors duration-150 group"
                >
                  {/* Invoice # */}
                  <td className="px-6 py-4 font-mono font-medium text-white group-hover:text-[#3B82F6] transition-colors">
                    {inv.invoice_number || "INV-PENDING"}
                  </td>
                  
                  {/* Client / Vendor */}
                  <td className="px-6 py-4">
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
                  <td className="px-6 py-4 font-medium text-slate-400">
                    {formatDate(inv.invoice_date)}
                  </td>
                  
                  {/* Amount */}
                  <td className="px-6 py-4 font-bold text-slate-200 font-mono">
                    {formatCurrency(inv.grand_total)}
                  </td>
                  
                  {/* AI Status */}
                  <td className="px-6 py-4">
                    {getStatusBadge(inv.status)}
                  </td>
                  
                  {/* Actions Dropdown */}
                  <td className="px-6 py-4 text-right relative">
                    <button
                      onClick={(e) => toggleMenu(inv.id, e)}
                      className="p-1.5 rounded-lg hover:bg-slate-800 text-slate-400 hover:text-white transition-colors"
                    >
                      <MoreHorizontal className="w-4 h-4" />
                    </button>
                    
                    {activeMenuId === inv.id && (
                      <div 
                        className="absolute right-6 mt-1 w-44 bg-[#0F172A] border border-[#222D3D] rounded-lg shadow-xl py-1 z-20 animate-in fade-in slide-in-from-top-1 duration-150 text-left"
                        onClick={(e) => e.stopPropagation()}
                      >
                        <Link
                          href={`/audit?id=${inv.id}`}
                          className="w-full flex items-center gap-2 px-3 py-1.5 text-xs text-slate-300 hover:bg-[#1E293B] hover:text-white transition-colors"
                        >
                          <Eye className="w-3.5 h-3.5 text-[#3B82F6]" />
                          Auditor Review Console
                        </Link>
                        
                        <a
                          href={`http://localhost:8000/invoices/${inv.id}/pdf`}
                          target="_blank"
                          rel="noreferrer"
                          className="w-full flex items-center gap-2 px-3 py-1.5 text-xs text-slate-300 hover:bg-[#1E293B] hover:text-white transition-colors"
                        >
                          <FileDown className="w-3.5 h-3.5 text-slate-400" />
                          Download Original PDF
                        </a>
                      </div>
                    )}
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
