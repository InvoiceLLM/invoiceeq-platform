"use client";

import { useState } from "react";
import { AlertTriangle, ArrowRight, CheckCircle, Pencil, X, Info } from "lucide-react";
import { apiClient } from "@/lib/apiClient";

interface Alert {
  type: string;
  message: string;
  field?: string;
}

interface AlertCorrectionPreview {
  field: string;
  label: string;
  oldValue: string;
  newValue: string;
}

interface StandingRuleResult {
  applied: boolean;
  reason?: string;
  rules_added?: string[];
}

interface OutboundAlertConsoleProps {
  invoiceId: string;
  alerts: Alert[];
  currentStatus?: string;
  onAlertsChange: (remaining: Alert[]) => void;
  corrections?: Record<string, string>;
  applyAsStandingRule?: boolean;
  onDismissed?: (response: any) => void;
  resolveCorrection?: (alert: Alert) => AlertCorrectionPreview | null;
  onFocusField?: (field: string) => void;
}

export default function OutboundAlertConsole({
  invoiceId,
  alerts,
  currentStatus,
  onAlertsChange,
  corrections,
  applyAsStandingRule,
  onDismissed,
  resolveCorrection,
  onFocusField,
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
    const isNeedsReview = currentStatus === "NEEDS_REVIEW";
    return (
      <div className={`flex items-center gap-2 rounded-lg border px-4 py-3 ${
        isNeedsReview
          ? "border-amber-700/50 bg-amber-950/20 text-amber-300"
          : "border-emerald-700/50 bg-emerald-950/20 text-emerald-300"
      }`}>
        <CheckCircle size={16} className={isNeedsReview ? "text-amber-400" : "text-emerald-400"} />
        <span className="text-sm font-medium">
          {isNeedsReview
            ? "No active discrepancies — previously dismissed, awaiting finalization."
            : "No active alerts."}
        </span>
      </div>
    );
  }

  return (
    <div className="space-y-2">
      {alerts.map((alert, idx) => {
        const pending = resolveCorrection?.(alert) ?? null;
        const otherPending = Math.max(
          0,
          Object.keys(corrections ?? {}).length - (pending ? 1 : 0)
        );
        const busy = dismissing === alert.message;

        const getSeverity = (a: Alert): "information" | "warning" | "error" => {
          const type = a.type?.toLowerCase() || "";
          const msg = a.message?.toLowerCase() || "";
          if (type.includes("mismatch") || type.includes("duplicate") || type.includes("failed") || type.includes("timeout") || type.includes("missing")) {
            return "error";
          }
          if (type.includes("not_verified") || type.includes("confidence")) {
            return "warning";
          }
          return "information";
        };

        const severity = getSeverity(alert);
        const severityStyles = {
          error: {
            container: "border-red-700/50 bg-red-950/20",
            text: "text-red-200",
            iconColor: "text-red-400",
            buttonBorder: "border-red-700/50 bg-red-900/30 text-red-300 hover:bg-red-800/40",
            badge: "border-red-700/40 text-red-400/90 hover:bg-red-800/30 hover:text-red-200"
          },
          warning: {
            container: "border-yellow-700/50 bg-yellow-950/20",
            text: "text-yellow-200",
            iconColor: "text-yellow-400",
            buttonBorder: "border-yellow-700/50 bg-yellow-900/30 text-yellow-300 hover:bg-yellow-800/40",
            badge: "border-yellow-700/40 text-yellow-400/90 hover:bg-yellow-800/30 hover:text-yellow-200"
          },
          information: {
            container: "border-blue-700/50 bg-blue-950/20",
            text: "text-blue-200",
            iconColor: "text-blue-400",
            buttonBorder: "border-blue-700/50 bg-blue-900/30 text-blue-300 hover:bg-blue-800/40",
            badge: "border-blue-700/40 text-blue-400/90 hover:bg-blue-800/30 hover:text-blue-200"
          }
        }[severity];

        return (
          <div
            key={idx}
            data-testid="audit-alert"
            className={`rounded-lg border px-4 py-3 ${severityStyles.container}`}
          >
            <div className="flex items-start gap-3">
              {severity === "information" ? (
                <Info size={16} className={`mt-0.5 shrink-0 ${severityStyles.iconColor}`} />
              ) : (
                <AlertTriangle size={16} className={`mt-0.5 shrink-0 ${severityStyles.iconColor}`} />
              )}
              <div className="min-w-0 flex-1">
                <p className={`text-sm leading-relaxed ${severityStyles.text}`}>{alert.message}</p>
                {alert.field && onFocusField && (
                  <button
                    onClick={() => onFocusField(alert.field as string)}
                    className={`mt-1.5 rounded border px-1.5 py-0.5 font-mono text-[10px] transition ${severityStyles.badge}`}
                    title={`Jump to ${alert.field} in the Fields column`}
                  >
                    {alert.field} →
                  </button>
                )}
              </div>
              <button
                onClick={() => handleDismiss(alert)}
                disabled={busy}
                title={
                  pending
                    ? otherPending > 0
                      ? `Saves this correction and the ${otherPending} other pending correction(s) on this invoice, then dismisses this alert.`
                      : "Saves this correction, then dismisses this alert."
                    : "Dismisses this alert without changing any value."
                }
                className={`shrink-0 rounded-md border px-2 py-1 text-xs transition disabled:opacity-50 ${
                  pending
                    ? "border-blue-500/50 bg-blue-600/20 font-semibold text-blue-200 hover:bg-blue-600/40"
                    : severityStyles.buttonBorder
                }`}
              >
                {busy ? (
                  <X size={12} className="animate-spin" />
                ) : pending ? (
                  "Dismiss & Save"
                ) : (
                  "Dismiss"
                )}
              </button>
            </div>

            {pending && (
              <div
                data-testid="alert-correction-preview"
                className="mt-2.5 rounded-md border border-blue-600/40 bg-blue-950/30 px-3 py-2 text-xs"
              >
                <p className="flex flex-wrap items-center gap-1.5 text-blue-200">
                  <Pencil size={11} className="shrink-0" />
                  <span className="font-medium">{pending.label}</span>
                  <span className="text-slate-500 line-through">
                    {pending.oldValue || "empty"}
                  </span>
                  <ArrowRight size={11} className="shrink-0 text-blue-400" />
                  <span className="font-semibold text-blue-100">
                    {pending.newValue || "empty"}
                  </span>
                </p>
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}

export type { StandingRuleResult };
