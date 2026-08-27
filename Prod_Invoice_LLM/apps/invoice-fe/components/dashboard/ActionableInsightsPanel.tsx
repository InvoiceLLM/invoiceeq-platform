"use client";

import React, { useEffect, useState } from "react";
import { Sparkles, AlertTriangle, Info, AlertOctagon, X } from "lucide-react";
import { apiClient } from "../../lib/apiClient";

type InsightKind = "spend_concentration" | "at_risk_amount" | "audit_rate" | "vendor_rules_gap" | "other";

interface DashboardInsight {
  title: string;
  detail: string;
  severity: "info" | "warning" | "critical";
  /** Gap 317: stable category, distinct from title/detail which the LLM
   *  rewords each regeneration. Dismiss keys off this, not the free text. */
  kind: InsightKind;
}

interface DashboardInsightsData {
  insights: DashboardInsight[];
}

const EMPTY: DashboardInsightsData = { insights: [] };

const SEVERITY_STYLE: Record<string, { icon: React.ReactNode; border: string; bg: string }> = {
  critical: { icon: <AlertOctagon className="w-3.5 h-3.5 text-rose-400" />, border: "border-rose-500/20", bg: "bg-rose-500/5" },
  warning: { icon: <AlertTriangle className="w-3.5 h-3.5 text-amber-400" />, border: "border-amber-500/20", bg: "bg-amber-500/5" },
  info: { icon: <Info className="w-3.5 h-3.5 text-accent-blue" />, border: "border-[#222D3D]", bg: "bg-[#0B0F19]" },
};

/**
 * Gap 30 / FE Gap 4: AI-generated strategic recommendations, fetched from its
 * own endpoint (GET /dashboard/insights) separately from the main metrics
 * call, matching the same pattern as TrainerImpactPanel. The backend grounds
 * every recommendation in real aggregates (spend concentration, at-risk
 * amount, audit rate) and is cached for an hour there, so this component
 * doesn't need its own polling/refresh logic beyond a normal page load.
 */
export default function ActionableInsightsPanel() {
  const [data, setData] = useState<DashboardInsightsData>(EMPTY);
  const [isLoading, setIsLoading] = useState(true);
  const [dismissing, setDismissing] = useState<InsightKind | null>(null);

  const handleDismiss = async (kind: InsightKind) => {
    setDismissing(kind);
    try {
      await apiClient.post("/dashboard/insights/dismiss", { kind });
      // Optimistic removal -- matches Part C's design: dismiss only
      // suppresses this cache generation's instance of the kind, so a fresh
      // regeneration (real cache invalidation, Gap 317 Part B) can bring the
      // same category back if it's still a live concern.
      setData((prev) => ({ insights: prev.insights.filter((i) => i.kind !== kind) }));
    } catch (err) {
      console.error("Failed to dismiss insight", err);
    } finally {
      setDismissing(null);
    }
  };

  useEffect(() => {
    let cancelled = false;
    apiClient
      .get("/dashboard/insights")
      .then((res) => {
        if (!cancelled) setData(res.data || EMPTY);
      })
      .catch((err) => console.error("Failed to load actionable insights", err))
      .finally(() => {
        if (!cancelled) setIsLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <div className="glass-panel rounded-xl border border-[#222D3D] p-5 space-y-4">
      <div className="flex items-center gap-2">
        <Sparkles className="w-4 h-4 text-accent-blue" />
        <h3 className="text-sm font-semibold text-white tracking-wide">Actionable Insights</h3>
      </div>

      {isLoading ? (
        <p className="text-[11px] text-slate-600">Generating recommendations from current data...</p>
      ) : data.insights.length === 0 ? (
        <p className="text-[11px] text-slate-600">Not enough invoice data yet to generate recommendations.</p>
      ) : (
        <div className="space-y-2">
          {data.insights.map((insight, idx) => {
            const style = SEVERITY_STYLE[insight.severity] || SEVERITY_STYLE.info;
            return (
              <div key={idx} className={`flex gap-2 p-3 rounded-lg border ${style.border} ${style.bg}`}>
                <div className="pt-0.5">{style.icon}</div>
                <div className="space-y-0.5 flex-1 min-w-0">
                  <div className="text-xs font-semibold text-white">{insight.title}</div>
                  <div className="text-[11px] text-slate-400 leading-relaxed">{insight.detail}</div>
                </div>
                <button
                  type="button"
                  onClick={() => handleDismiss(insight.kind)}
                  disabled={dismissing === insight.kind}
                  title="Dismiss -- reappears if this is still a live concern next time the data changes"
                  className="shrink-0 p-1 rounded text-slate-500 hover:text-slate-300 hover:bg-white/5 disabled:opacity-50 transition-colors"
                >
                  <X className="w-3 h-3" />
                  <span className="sr-only">Dismiss</span>
                </button>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
