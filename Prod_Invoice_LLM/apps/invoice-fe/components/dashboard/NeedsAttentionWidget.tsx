"use client";

import React, { useEffect, useState } from "react";
import Link from "next/link";
import { AlertCircle } from "lucide-react";
import { apiClient } from "../../lib/apiClient";
import { formatCurrency } from "../../lib/utils";

interface FlaggedInvoice {
  id: string;
  invoice_number?: string;
  vendor_name?: string;
  grand_total?: number;
}

const WIDGET_LIMIT = 8;

/**
 * Task 2.7 / Task 4.9 (Dashboard/Audit split, 2026-07-29): Dashboard's only
 * remaining invoice-level surface -- a capped teaser linking into the real
 * queue (/invoices), not a working list itself. No pagination on purpose.
 */
export default function NeedsAttentionWidget() {
  const [invoices, setInvoices] = useState<FlaggedInvoice[]>([]);
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    apiClient
      .get("/invoices", { params: { status: "AUDIT_REQUIRED", limit: WIDGET_LIMIT } })
      .then((res) => {
        if (!cancelled) setInvoices(res.data || []);
      })
      .catch((err) => console.error("Failed to load needs-attention invoices", err))
      .finally(() => {
        if (!cancelled) setIsLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <div className="glass-panel rounded-xl border border-[#222D3D] p-5 space-y-4">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <AlertCircle className="w-4 h-4 text-amber-400" />
          <h3 className="text-sm font-semibold text-white tracking-wide">Needs Attention</h3>
        </div>
        <Link href="/invoices" className="text-[11px] text-accent-blue hover:underline">
          View all &rarr;
        </Link>
      </div>

      {isLoading ? (
        <p className="text-[11px] text-slate-600">Checking for flagged invoices...</p>
      ) : invoices.length === 0 ? (
        <p className="text-[11px] text-slate-600">Nothing needs review right now.</p>
      ) : (
        <div className="space-y-2">
          {invoices.map((inv) => (
            <Link
              key={inv.id}
              href={`/invoices/review/${inv.id}`}
              className="flex items-center justify-between gap-2 p-2.5 rounded-lg border border-amber-500/20 bg-amber-500/5 hover:bg-amber-500/10 transition-colors"
            >
              <div className="min-w-0">
                <div className="text-xs font-semibold text-white truncate">
                  {inv.invoice_number || "INV-PENDING"}
                </div>
                <div className="text-[11px] text-slate-400 truncate">
                  {inv.vendor_name || "Unknown Vendor"}
                </div>
              </div>
              <div className="text-xs font-mono text-slate-300 shrink-0">
                {formatCurrency(inv.grand_total)}
              </div>
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}
