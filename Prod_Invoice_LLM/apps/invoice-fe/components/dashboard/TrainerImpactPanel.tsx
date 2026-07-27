"use client";

import React, { useEffect, useState } from "react";
import { GraduationCap, ArrowRight, ShieldCheck } from "lucide-react";
import Link from "next/link";
import { apiClient } from "../../lib/apiClient";

interface RulesTrained {
  global: number;
  vendor_specific: number;
  total: number;
}

interface VendorNeedingRule {
  vendor_name: string;
  flagged_invoice_count: number;
}

interface AuditRateWeek {
  week: string;
  audit_rate: number;
  total_processed: number;
}

interface TrainerImpactData {
  rules_trained: RulesTrained;
  vendors_needing_rules: VendorNeedingRule[];
  audit_rate_trend: AuditRateWeek[];
}

const EMPTY: TrainerImpactData = {
  rules_trained: { global: 0, vendor_specific: 0, total: 0 },
  vendors_needing_rules: [],
  audit_rate_trend: [],
};

/**
 * Gap 28 / FE Gap 21: makes the Trainer's payoff visible on the Dashboard.
 * Fetches its own endpoint (GET /dashboard/trainer-impact) separately from
 * the main metrics call, since it's a distinct concern (training ROI, not
 * spend/status aggregates). Reports a real weekly audit-rate trend rather
 * than a single "% improvement" figure — the backend deliberately avoids
 * claiming the rules *caused* a specific improvement from this data.
 */
export default function TrainerImpactPanel() {
  const [data, setData] = useState<TrainerImpactData>(EMPTY);
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    apiClient
      .get("/dashboard/trainer-impact")
      .then((res) => {
        if (!cancelled) setData(res.data || EMPTY);
      })
      .catch((err) => console.error("Failed to load trainer impact metrics", err))
      .finally(() => {
        if (!cancelled) setIsLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const maxRate = Math.max(1, ...data.audit_rate_trend.map((w) => w.audit_rate));

  return (
    <div className="glass-panel rounded-xl border border-[#222D3D] p-5 space-y-4">
      <div className="flex items-center gap-2">
        <GraduationCap className="w-4 h-4 text-purple-400" />
        <h3 className="text-sm font-semibold text-white tracking-wide">Trainer Impact</h3>
      </div>

      {/* Rules trained stat tiles */}
      <div className="grid grid-cols-3 gap-3">
        <div className="bg-[#0B0F19] border border-[#222D3D] rounded-lg p-3 text-center">
          <div className="text-lg font-bold text-white">{isLoading ? "-" : data.rules_trained.global}</div>
          <div className="text-[10px] text-slate-500 uppercase tracking-wide">Global Rules</div>
        </div>
        <div className="bg-[#0B0F19] border border-[#222D3D] rounded-lg p-3 text-center">
          <div className="text-lg font-bold text-white">{isLoading ? "-" : data.rules_trained.vendor_specific}</div>
          <div className="text-[10px] text-slate-500 uppercase tracking-wide">Vendor Rules</div>
        </div>
        <div className="bg-[#0B0F19] border border-[#222D3D] rounded-lg p-3 text-center">
          <div className="text-lg font-bold text-emerald-400">{isLoading ? "-" : data.rules_trained.total}</div>
          <div className="text-[10px] text-slate-500 uppercase tracking-wide">Total Rules</div>
        </div>
      </div>

      {/* Weekly audit-rate trend — hand-built bars, no chart library, matching the rest of this dashboard */}
      <div>
        <div className="text-[10px] text-slate-500 uppercase tracking-wide mb-2">
          Weekly Audit Rate
        </div>
        {data.audit_rate_trend.length === 0 ? (
          <p className="text-[11px] text-slate-600">Not enough processed invoices yet to show a trend.</p>
        ) : (
          <div className="flex items-end gap-1.5 h-16">
            {data.audit_rate_trend.map((w) => (
              <div key={w.week} className="flex-1 flex flex-col items-center gap-1" title={`Week of ${w.week}: ${w.audit_rate}% (${w.total_processed} processed)`}>
                <div
                  className="w-full bg-amber-500/60 rounded-t"
                  style={{ height: `${Math.max(4, (w.audit_rate / maxRate) * 56)}px` }}
                />
                <span className="text-[8px] text-slate-600">{w.week.slice(5)}</span>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Vendors still needing a rule */}
      <div>
        <div className="text-[10px] text-slate-500 uppercase tracking-wide mb-2">
          Vendors Needing a Rule
        </div>
        {data.vendors_needing_rules.length === 0 ? (
          <p className="text-[11px] flex items-center gap-1.5 text-emerald-400">
            <ShieldCheck className="w-3.5 h-3.5" /> No vendors with a recurring, unaddressed pattern.
          </p>
        ) : (
          <div className="space-y-1.5">
            {data.vendors_needing_rules.slice(0, 5).map((v) => (
              <Link
                key={v.vendor_name}
                href={`/trainer?from=audit&scope=existing_vendor&vendor_name=${encodeURIComponent(v.vendor_name)}`}
                className="flex items-center justify-between px-3 py-2 rounded-lg bg-amber-500/5 border border-amber-500/20 text-xs text-slate-300 hover:bg-amber-500/10 transition-colors group"
              >
                <span>
                  {v.vendor_name} <span className="text-slate-500">({v.flagged_invoice_count} flagged)</span>
                </span>
                <ArrowRight className="w-3.5 h-3.5 text-amber-400 opacity-0 group-hover:opacity-100 transition-opacity" />
              </Link>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
