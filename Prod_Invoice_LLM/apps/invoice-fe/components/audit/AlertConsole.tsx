"use client";

import { useState } from "react";
import { AlertTriangle, CheckCircle, X } from "lucide-react";
import { apiClient } from "@/lib/apiClient";

interface Alert {
  type: string;
  message: string;
}

interface AlertConsoleProps {
  invoiceId: string;
  alerts: Alert[];
  currentStatus: string;
  onAlertsChange: (remaining: Alert[]) => void;
  /** In-progress field corrections (Task 7.3) to save alongside the dismiss,
   * so an auditor doesn't lose an edit just because they dismissed an alert
   * instead of clicking a finalize button. */
  corrections?: Record<string, string>;
  onDismissed?: (response: any) => void;
}

export default function AlertConsole({
  invoiceId,
  alerts,
  currentStatus,
  onAlertsChange,
  corrections,
  onDismissed,
}: AlertConsoleProps) {
  const [dismissing, setDismissing] = useState<string | null>(null);

  const handleDismiss = async (alert: Alert) => {
    setDismissing(alert.message);
    try {
      // `status` is deliberately omitted here — the backend now treats it as
      // optional (Task 7.3), and forcing PAID/REJECTED just to dismiss one
      // alert on a still-AUDIT_REQUIRED invoice used to fail outright since
      // that endpoint only ever accepted PAID/REJECTED as a target status.
      const res = await apiClient.put(`/audit/resolve/${invoiceId}`, {
        dismissed_alerts: [alert.message],
        corrections: corrections && Object.keys(corrections).length > 0 ? corrections : undefined,
      });
      const remaining = alerts.filter((a) => a.message !== alert.message);
      onAlertsChange(remaining);
      onDismissed?.(res.data);
    } catch (err) {
      console.error("Failed to dismiss alert:", err);
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
        <div
          key={idx}
          className="flex items-start gap-3 rounded-lg border border-yellow-700/50 bg-yellow-950/20 px-4 py-3"
        >
          <AlertTriangle
            size={16}
            className="mt-0.5 shrink-0 text-yellow-400"
          />
          <p className="flex-1 text-sm leading-relaxed text-yellow-200">
            {alert.message}
          </p>
          <button
            onClick={() => handleDismiss(alert)}
            disabled={dismissing === alert.message}
            className="shrink-0 rounded-md border border-yellow-700/50 bg-yellow-900/30 px-2 py-1 text-xs text-yellow-300 transition hover:bg-yellow-800/40 disabled:opacity-50"
          >
            {dismissing === alert.message ? (
              <X size={12} className="animate-spin" />
            ) : (
              "Dismiss"
            )}
          </button>
        </div>
      ))}
    </div>
  );
}
