"use client";

import { useState } from "react";
import { AlertTriangle, CheckCircle, X, ShieldCheck } from "lucide-react";
import { apiClient } from "@/lib/apiClient";

interface Alert {
  type: string;
  message: string;
}

interface StandingRuleResult {
  applied: boolean;
  reason?: string;
  rules_added?: string[];
}

interface OutboundAlertConsoleProps {
  invoiceId: string;
  alerts: Alert[];
  onAlertsChange: (remaining: Alert[]) => void;
  corrections?: Record<string, string>;
  applyAsStandingRule?: boolean;
  onDismissed?: (response: any) => void;
}

/**
 * Feature 4.1: same visual language as AlertConsole.tsx (Theme & Styling
 * Specifications in feature_4_auditor.md carry over unchanged), not a fork
 * of that file -- calls PUT /outbound-audit/resolve/{id} instead, and the
 * standing-rule result here always resolves immediately (Task 7.1.3 has no
 * safety gate, unlike inbound's Gap 62 mechanism).
 */
export default function OutboundAlertConsole({
  invoiceId,
  alerts,
  onAlertsChange,
  corrections,
  applyAsStandingRule,
  onDismissed,
}: OutboundAlertConsoleProps) {
  const [dismissing, setDismissing] = useState<string | null>(null);

  const handleDismiss = async (alert: Alert) => {
    setDismissing(alert.message);
    try {
      const res = await apiClient.put(`/outbound-audit/resolve/${invoiceId}`, {
        dismissed_alerts: [alert.message],
        corrections: corrections && Object.keys(corrections).length > 0 ? corrections : undefined,
        apply_as_standing_rule: applyAsStandingRule || undefined,
      });
      const remaining = alerts.filter((a) => a.message !== alert.message);
      onAlertsChange(remaining);
      onDismissed?.(res.data);
    } catch (err) {
      console.error("Failed to dismiss outbound alert:", err);
    } finally {
      setDismissing(null);
    }
  };

  if (alerts.length === 0) {
    return (
      <div className="flex items-center gap-2 rounded-lg border border-emerald-700/50 bg-emerald-950/20 px-4 py-3 text-emerald-300">
        <CheckCircle size={16} />
        <span className="text-sm font-medium">No active discrepancy warnings.</span>
      </div>
    );
  }

  return (
    <div className="space-y-2">
      <div className="rounded-lg border border-yellow-700/50 bg-yellow-950/20 px-4 py-2">
        <p className="mb-1 text-xs font-semibold uppercase tracking-widest text-yellow-500 flex items-center gap-2">
          Discrepancy Warnings
          <span className="text-[10px] px-2 py-0.5 rounded-full bg-[#10B981]/10 text-[#10B981] border border-[#10B981]/30 font-mono font-semibold normal-case tracking-normal">SENTINEL</span>
        </p>
      </div>

      {alerts.map((alert, idx) => (
        <div key={idx} className="flex items-start gap-3 rounded-lg border border-yellow-700/50 bg-yellow-950/20 px-4 py-3">
          <AlertTriangle size={16} className="mt-0.5 shrink-0 text-yellow-400" />
          <p className="flex-1 text-sm leading-relaxed text-yellow-200">{alert.message}</p>
          <button
            onClick={() => handleDismiss(alert)}
            disabled={dismissing === alert.message}
            className="shrink-0 rounded-md border border-yellow-700/50 bg-yellow-900/30 px-2 py-1 text-xs text-yellow-300 transition hover:bg-yellow-800/40 disabled:opacity-50"
          >
            {dismissing === alert.message ? <X size={12} className="animate-spin" /> : "Dismiss"}
          </button>
        </div>
      ))}
    </div>
  );
}

export type { StandingRuleResult };
