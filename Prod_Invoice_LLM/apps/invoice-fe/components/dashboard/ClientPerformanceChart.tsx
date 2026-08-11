"use client";

import React, { useState } from "react";
import { Users, BarChart3 } from "lucide-react";
import { formatCurrency, normalizeCurrencyCode } from "../../lib/utils";

interface VendorSpend {
  vendor_name: string;
  /**
   * FE Gap 183: the backend now returns one row per (vendor, currency). Null
   * means the invoices behind this row had no extracted currency -- rendered
   * as USD, the display default, never written back.
   */
  currency?: string | null;
  amount: number;
}

interface ClientPerformanceChartProps {
  vendors: VendorSpend[];
  isLoading: boolean;
  /**
   * Feature 2.1, Task 2.1.4: optional heading override so the outbound half of
   * the Dashboard split can label its own top_customers ranking. Additive and
   * defaulted -- every existing caller renders exactly as before. The doc
   * listed this component as imported-not-edited on the assumption it carried
   * no vendor-specific wording, but the heading below is hardcoded, and two
   * identically-titled ranking panels side by side would be ambiguous (and
   * indistinguishable to a screen reader), so this is the smaller evil.
   */
  title?: string;
  subtitle?: string;
}

export default function ClientPerformanceChart({
  vendors = [],
  isLoading,
  title = "Top Clients & Vendors",
  subtitle = "Ranking by aggregated billing volumes.",
}: ClientPerformanceChartProps) {
  const [hoveredKey, setHoveredKey] = useState<string | null>(null);

  /**
   * FE Gap 183: grouped by currency, and each group's bars scaled against that
   * group's own maximum.
   *
   * Before this, a single `maxAmount = Math.max(...all amounts)` scaled every
   * bar on one axis, so a ₹40,000 vendor drew a full-width bar and a $500
   * vendor drew the 5% minimum stub next to it -- an 80x visual difference
   * that is purely the INR/USD exchange rate, not a difference in spend. The
   * amounts were never comparable, so they are no longer drawn as if they
   * were: separate section per currency, top 5 within each.
   */
  const groups = (() => {
    const byCurrency = new Map<string, VendorSpend[]>();
    for (const v of vendors || []) {
      const code = normalizeCurrencyCode(v.currency);
      const bucket = byCurrency.get(code);
      if (bucket) bucket.push(v);
      else byCurrency.set(code, [v]);
    }
    return Array.from(byCurrency.entries())
      .map(([currency, rows]) => {
        const top = [...rows].sort((a, b) => b.amount - a.amount).slice(0, 5);
        return {
          currency,
          vendors: top,
          // Scale within the group only.
          maxAmount: top.length > 0 ? Math.max(...top.map((v) => v.amount)) || 1 : 1,
          groupTotal: rows.reduce((sum, v) => sum + (v.amount || 0), 0),
        };
      })
      // Biggest currency block first. Ordering by each group's own total is a
      // presentation choice, not a comparison -- no amounts are added across
      // currencies to produce it.
      .sort((a, b) => b.groupTotal - a.groupTotal);
  })();

  const hasData = groups.some((g) => g.vendors.length > 0);
  const isMultiCurrency = groups.length > 1;

  return (
    <div className="glass-panel p-6 rounded-xl flex flex-col gap-6 h-full min-h-[340px]">
      {/* Component Title Header */}
      <div className="flex items-center justify-between border-b border-[#222D3D] pb-4">
        <div className="flex items-center gap-2">
          <BarChart3 className="w-5 h-5 text-accent-blue" />
          <div>
            <h3 className="text-sm font-semibold text-white tracking-wide">
              {title}
            </h3>
            <p className="text-xs text-slate-400">
              {subtitle}
            </p>
          </div>
        </div>
        <Users className="w-5 h-5 text-slate-500" />
      </div>

      {/* Vendors Ranking Bars */}
      <div className="flex-1 flex flex-col justify-center gap-4">
        {isLoading ? (
          <div className="flex flex-col gap-4">
            {[...Array(5)].map((_, i) => (
              <div key={i} className="space-y-2 animate-pulse">
                <div className="flex justify-between text-xs">
                  <div className="h-3 w-24 bg-slate-800 rounded"></div>
                  <div className="h-3 w-12 bg-slate-800 rounded"></div>
                </div>
                <div className="h-2 w-full bg-slate-800 rounded-full"></div>
              </div>
            ))}
          </div>
        ) : !hasData ? (
          <div className="text-center text-slate-500 text-xs py-8">
            No client data found for this range.
          </div>
        ) : (
          <div className="space-y-5">
            {groups.map((group) => (
              <div key={group.currency} className="space-y-4">
                {/* Only labelled when there is more than one currency to tell
                    apart -- a single-currency tenant sees the same panel it
                    always did. */}
                {isMultiCurrency && (
                  <div className="flex items-center gap-2 text-[10px] font-semibold uppercase tracking-wider text-slate-400 border-b border-[#222D3D] pb-1">
                    <span>{group.currency}</span>
                    <span className="font-normal normal-case tracking-normal text-slate-500">
                      ranked and scaled within this currency
                    </span>
                  </div>
                )}

                {group.vendors.map((vendor, index) => {
                  const percentage = Math.max(5, (vendor.amount / group.maxAmount) * 100);
                  const key = `${group.currency}-${vendor.vendor_name}`;
                  const isHovered = hoveredKey === key;

                  return (
                    <div
                      key={key}
                      className="space-y-1.5 cursor-pointer group"
                      onMouseEnter={() => setHoveredKey(key)}
                      onMouseLeave={() => setHoveredKey(null)}
                    >
                      {/* Vendor Details Text Row */}
                      <div className="flex justify-between text-xs font-semibold select-none">
                        <span className="text-slate-300 group-hover:text-white transition-colors duration-150 truncate max-w-[200px]">
                          {index + 1}. {vendor.vendor_name}
                        </span>
                        <span className="text-slate-400 group-hover:text-[#3B82F6] transition-colors duration-150 font-mono">
                          {formatCurrency(vendor.amount, vendor.currency)}
                        </span>
                      </div>

                      {/* Horizontal Bar Graphic */}
                      <div className="relative w-full h-2.5 bg-slate-800/40 border border-[#222D3D] rounded-full overflow-hidden">
                        <div
                          className="absolute top-0 left-0 bottom-0 rounded-full transition-all duration-500 ease-out"
                          style={{
                            width: `${percentage}%`,
                            backgroundColor: isHovered ? "#3B82F6" : "#94A3B8",
                            boxShadow: isHovered
                              ? "0 0 8px rgba(59, 130, 246, 0.4)"
                              : "none",
                          }}
                        />
                      </div>
                    </div>
                  );
                })}
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
