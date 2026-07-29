"use client";

import React, { useEffect, useState } from "react";
import Link from "next/link";
import { AlertCircle, ArrowDownLeft, ArrowUpRight } from "lucide-react";
import { apiClient } from "../../lib/apiClient";
import { formatCurrency } from "../../lib/utils";

type FlowDirection = "INBOUND" | "OUTBOUND";

interface FlaggedInvoice {
  id: string;
  invoice_number?: string;
  vendor_name?: string;
  customer_name?: string;
  grand_total?: number;
  direction: FlowDirection;
}

interface NeedsAttentionWidgetProps {
  /** Service Flow toggles, passed down from dashboard/page.tsx. Defaults match
   *  the Tenant model's own defaults so existing callers behave unchanged. */
  receiveEnabled?: boolean;
  sendEnabled?: boolean;
}

const WIDGET_LIMIT = 8;

/**
 * Task 2.7 / Task 4.9 (Dashboard/Audit split, 2026-07-29): Dashboard's only
 * remaining invoice-level surface -- a capped teaser linking into the real
 * queue (/invoices), not a working list itself. No pagination on purpose.
 *
 * Feature 2.1, Task 2.1.5: now direction-agnostic. Pulls inbound
 * AUDIT_REQUIRED and outbound NEEDS_REVIEW from their own separate endpoints
 * (the BE keeps them apart under the zero-touch rule) and shows them in one
 * merged list, each row linking to the review screen for its own direction.
 */
export default function NeedsAttentionWidget({
  receiveEnabled = true,
  sendEnabled = false,
}: NeedsAttentionWidgetProps) {
  const [invoices, setInvoices] = useState<FlaggedInvoice[]>([]);
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;

    const load = async () => {
      setIsLoading(true);

      // Only enabled directions are requested -- a receive-only tenant makes
      // no outbound call at all, and vice versa. Settled independently so one
      // side failing still renders the other.
      const inboundPromise = receiveEnabled
        ? apiClient.get("/invoices", { params: { status: "AUDIT_REQUIRED", limit: WIDGET_LIMIT } })
        : null;
      const outboundPromise = sendEnabled
        ? apiClient.get("/outbound-dashboard/invoices", {
            params: { status: "NEEDS_REVIEW", limit: WIDGET_LIMIT },
          })
        : null;

      const [inboundRes, outboundRes] = await Promise.allSettled([
        inboundPromise ?? Promise.resolve({ data: [] }),
        outboundPromise ?? Promise.resolve({ data: [] }),
      ]);

      if (cancelled) return;

      const inboundRows: FlaggedInvoice[] =
        inboundRes.status === "fulfilled"
          ? ((inboundRes.value as any)?.data || []).map((inv: any) => ({
              ...inv,
              direction: "INBOUND" as FlowDirection,
            }))
          : [];

      if (inboundRes.status === "rejected") {
        console.error("Failed to load inbound needs-attention invoices", inboundRes.reason);
      }

      const outboundRows: FlaggedInvoice[] =
        outboundRes.status === "fulfilled"
          ? ((outboundRes.value as any)?.data || []).map((inv: any) => ({
              ...inv,
              direction: "OUTBOUND" as FlowDirection,
            }))
          : [];

      if (outboundRes.status === "rejected") {
        console.error("Failed to load outbound needs-attention invoices", outboundRes.reason);
      }

      // Merged, then capped at the same total the widget always showed --
      // this stays a teaser, so enabling Send must not double its length.
      // Highest value first: if only 8 of them fit, the ones worth chasing
      // are the expensive ones, not whichever endpoint answered first.
      const merged = [...inboundRows, ...outboundRows]
        .sort((a, b) => (b.grand_total ?? 0) - (a.grand_total ?? 0))
        .slice(0, WIDGET_LIMIT);

      setInvoices(merged);
      setIsLoading(false);
    };

    load();
    return () => {
      cancelled = true;
    };
  }, [receiveEnabled, sendEnabled]);

  const reviewHref = (inv: FlaggedInvoice) =>
    inv.direction === "OUTBOUND"
      ? `/invoices/outbound-review/${inv.id}`
      : `/invoices/review/${inv.id}`;

  const counterpartyName = (inv: FlaggedInvoice) =>
    inv.direction === "OUTBOUND"
      ? inv.customer_name || "Unknown Customer"
      : inv.vendor_name || "Unknown Vendor";

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
              key={`${inv.direction}-${inv.id}`}
              href={reviewHref(inv)}
              className="flex items-center justify-between gap-2 p-2.5 rounded-lg border border-amber-500/20 bg-amber-500/5 hover:bg-amber-500/10 transition-colors"
            >
              <div className="flex items-center gap-2.5 min-w-0">
                {/* Direction is only shown when both flows are on -- a
                    single-service tenant has no ambiguity to resolve. */}
                {receiveEnabled && sendEnabled && (
                  <span
                    className={`shrink-0 p-1 rounded-md border ${
                      inv.direction === "OUTBOUND"
                        ? "border-emerald-500/20 bg-emerald-500/10 text-emerald-400"
                        : "border-blue-500/20 bg-blue-500/10 text-accent-blue"
                    }`}
                    title={inv.direction === "OUTBOUND" ? "Outbound (sending)" : "Inbound (receiving)"}
                  >
                    {inv.direction === "OUTBOUND" ? (
                      <ArrowUpRight className="w-3 h-3" aria-hidden="true" />
                    ) : (
                      <ArrowDownLeft className="w-3 h-3" aria-hidden="true" />
                    )}
                    <span className="sr-only">
                      {inv.direction === "OUTBOUND" ? "Outbound invoice" : "Inbound invoice"}
                    </span>
                  </span>
                )}

                <div className="min-w-0">
                  <div className="text-xs font-semibold text-white truncate">
                    {inv.invoice_number || "INV-PENDING"}
                  </div>
                  <div className="text-[11px] text-slate-400 truncate">
                    {counterpartyName(inv)}
                  </div>
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
