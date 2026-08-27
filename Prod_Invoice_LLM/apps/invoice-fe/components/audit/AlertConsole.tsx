"use client";

import { useState } from "react";
import { AlertTriangle, ArrowRight, CheckCircle, Pencil, X, Info } from "lucide-react";
import { apiClient } from "@/lib/apiClient";

interface Alert {
  type: string;
  message: string;
  /** FE Gap 112 item 4: the schema field this alert was raised against.
   * Already emitted by every producer in `utils/verification_tools.py`
   * (`"field": "tax_amount"`, `"field": "grand_total"`, ...) and carried
   * through untouched because `Invoice.sa_alerts` is a raw JSON column — the
   * FE simply never read it before. Optional because older rows and the
   * duplicate alert in `routers/invoices.py` do not set it. */
  field?: string;
}

/**
 * FE Gap 112 item 4 — a correction the auditor has staged against the field
 * this alert was raised on, resolved by the page (which is what knows the
 * field labels and the pre-correction values) rather than looked up here.
 */
export interface AlertCorrectionPreview {
  field: string;
  label: string;
  /** Value as extracted, rendered struck through. */
  oldValue: string;
  /** Value the auditor typed, which is what will be persisted. */
  newValue: string;
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
  /** Task 4.10 (Gap 67 / BE Gap 62): teach this correction back as a standing
   * rule for the vendor, gated on the backend's safety re-extraction check. */
  applyAsStandingRule?: boolean;
  onDismissed?: (response: any) => void;
  /** FE Gap 112 item 4: returns the staged correction linked to this alert, or
   * null when the auditor hasn't corrected that field (or the alert names a
   * field the backend won't accept a correction for — Gap 112 item 6, still
   * open). Kept as a callback so this component stays presentational and the
   * correctable-field set has exactly one definition, in the page. */
  resolveCorrection?: (alert: Alert) => AlertCorrectionPreview | null;
  /** FE Gap 112 item 4: focus the field an alert refers to, in the Fields
   * column. Renders the alert's field name as a button when provided. */
  onFocusField?: (field: string) => void;
}

export default function AlertConsole({
  invoiceId,
  alerts,
  currentStatus,
  onAlertsChange,
  corrections,
  applyAsStandingRule,
  onDismissed,
  resolveCorrection,
  onFocusField,
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
        apply_as_standing_rule: applyAsStandingRule || undefined,
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
    const isAuditRequired = currentStatus === "AUDIT_REQUIRED";
    return (
      <div className={`flex items-center gap-2 rounded-lg border px-4 py-3 ${
        isAuditRequired
          ? "border-amber-700/50 bg-amber-950/20 text-amber-300"
          : "border-emerald-700/50 bg-emerald-950/20 text-emerald-300"
      }`}>
        <CheckCircle size={16} className={isAuditRequired ? "text-amber-400" : "text-emerald-400"} />
        <span className="text-sm font-medium">
          {isAuditRequired
            ? "No active discrepancies — previously dismissed, awaiting finalization."
            : "No active alerts."}
        </span>
      </div>
    );
  }

  return (
    // FE Gap 112 item 1: the "Discrepancy Warnings / SENTINEL" strip that used
    // to sit here is now the Alerts *panel's* own header in the review page's
    // three-column layout, so this renders only the list -- two stacked titles
    // inside one panel was the alternative.
    <div className="space-y-2">
      {alerts.map((alert, idx) => {
        // FE Gap 112 item 4. `pending` is the correction staged against *this*
        // alert's own field; `otherPending` is everything else the auditor has
        // staged elsewhere on the invoice. Both are shown, because dismissing
        // any single alert flushes the entire `corrections` map, not just the
        // linked one (Gap 112 item 5 — the backend has no per-alert scope, and
        // that stays a product decision; this UI only stops implying
        // otherwise).
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
                {/* The field this alert names, as a jump target into the
                    Fields column. Only rendered when the backend actually
                    tagged the alert with a field. */}
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
                  "Dismiss & Save Correction"
                ) : (
                  "Dismiss"
                )}
              </button>
            </div>

            {/* Staged correction, previewed against the alert it answers. This
                is the `corrections` prop finally becoming visible: it was
                already being posted with every dismiss, with nothing on screen
                to say so. */}
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
                {otherPending > 0 && (
                  <p className="mt-1 text-[11px] text-blue-300/70">
                    {otherPending} other pending correction{otherPending === 1 ? "" : "s"} on this
                    invoice will be saved at the same time.
                  </p>
                )}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}
