"use client";

import React from "react";
import {
  AlertTriangle,
  AlertCircle,
  Info,
  ShieldOff,
  Wand2,
  Flag,
  CheckCircle2,
} from "lucide-react";
import { TrainerAlert } from "@/lib/trainer-service";

/**
 * Feature 14 Component: AlertListPanel
 *
 * FOR MANAGERS & DEVELOPERS:
 * The centre of the redesigned Trainer. A session opens on one specific
 * invoice's real alerts, and this panel is where a correction starts. Two entry
 * points, deliberately distinct:
 *
 *   1. **Train on this** (per alert) — the alert fired and shouldn't have, or it
 *      fired correctly but reads wrong.
 *   2. **Flag as missed** (panel-level) — an alert the user *expected* and did
 *      not get. Available even when the list is empty, which is the case that
 *      matters most: an invoice with no alerts is exactly where a missing check
 *      is invisible.
 *
 * WHY EACH ROW RENDERS ITS OWN CORRECTABILITY:
 * `correctionForm` comes from the backend's alert-type registry, per alert. The
 * FE does not keep a second copy of that mapping. Where a type has no numeric
 * knob — the five `*_not_verified_in_source` types, duplicates, failures,
 * timeouts — the row says so, in the registry's own words, instead of offering a
 * button that would do nothing. An unexplained missing control reads as a bug;
 * a stated reason reads as a decision.
 */

interface AlertListPanelProps {
  alerts: TrainerAlert[];
  /** Opens the correction picker for one alert. */
  onTrainOnAlert: (alert: TrainerAlert) => void;
  /** Opens the "I expected an alert here" flow. */
  onFlagMissed: () => void;
  /** Number of rules staged in this session but not yet committed. */
  stagedRuleCount: number;
  disabled?: boolean;
}

function severityVisual(severity?: string | null) {
  const s = (severity || "").toLowerCase();
  if (s === "error") {
    return { Icon: AlertCircle, cls: "text-red-400", chip: "bg-red-500/10 text-red-300 border-red-500/30" };
  }
  if (s === "info") {
    return { Icon: Info, cls: "text-blue-400", chip: "bg-blue-500/10 text-blue-300 border-blue-500/30" };
  }
  // Unset severity is treated as a warning: that is how the audit consoles
  // already render an alert with no explicit severity, and inventing a fourth
  // "unknown" visual here would make the same alert look different in two places.
  return { Icon: AlertTriangle, cls: "text-amber-400", chip: "bg-amber-500/10 text-amber-300 border-amber-500/30" };
}

export default function AlertListPanel({
  alerts,
  onTrainOnAlert,
  onFlagMissed,
  stagedRuleCount,
  disabled = false,
}: AlertListPanelProps) {
  return (
    <div
      data-testid="trainer-alert-list"
      className="h-full flex flex-col bg-[#070D1A]/90 border border-[#1E2D45] rounded-2xl overflow-hidden shadow-2xl shadow-black/30"
    >
      {/* ── Header ──────────────────────────────────────────────────────── */}
      <div className="h-12 px-4 bg-[#0B1120]/90 border-b border-[#1E2D45] flex items-center gap-2 shrink-0">
        <AlertTriangle className="w-4 h-4 text-amber-400 shrink-0" />
        <h2 className="text-xs font-semibold text-white truncate">
          Alerts on this invoice
        </h2>
        <span className="px-1.5 py-0.5 rounded-full bg-slate-700/30 text-slate-300 border border-slate-600/40 text-[10px] font-mono font-semibold leading-none shrink-0">
          {alerts.length}
        </span>
        {stagedRuleCount > 0 && (
          <span
            data-testid="trainer-staged-count"
            className="ml-auto px-2 py-0.5 rounded-full bg-emerald-500/10 text-emerald-300 border border-emerald-500/30 text-[10px] font-mono font-semibold leading-none shrink-0"
          >
            {stagedRuleCount} staged
          </span>
        )}
      </div>

      {/* ── Alert rows ──────────────────────────────────────────────────── */}
      <div className="flex-1 min-h-0 overflow-y-auto p-3 space-y-2">
        {alerts.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-full min-h-[180px] text-center gap-3 py-10 px-4">
            <div className="w-11 h-11 rounded-2xl bg-emerald-500/10 border border-emerald-500/20 flex items-center justify-center text-emerald-400">
              <CheckCircle2 className="w-5 h-5" />
            </div>
            <div>
              <p className="text-sm font-medium text-slate-300">No alerts on this invoice</p>
              <p className="text-xs text-slate-500 mt-1 max-w-xs leading-relaxed">
                If you expected one — a tax mismatch, a total that doesn&apos;t
                reconcile, a field read with low confidence — flag it below and say
                which check you expected to fire.
              </p>
            </div>
          </div>
        ) : (
          alerts.map((alert) => {
            const { Icon, cls, chip } = severityVisual(alert.severity);
            const correctable = alert.correctionForm !== "none";
            return (
              <div
                key={alert.id}
                data-testid="trainer-alert-row"
                className="rounded-xl border border-[#1E2D45] bg-[#0B1120]/70 p-3 space-y-2"
              >
                <div className="flex items-start gap-2.5">
                  <Icon className={`w-4 h-4 shrink-0 mt-0.5 ${cls}`} />
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2 flex-wrap">
                      <span className="text-xs font-semibold text-slate-100">{alert.label}</span>
                      {alert.severity && (
                        <span className={`text-[9px] font-mono uppercase px-1.5 py-0.5 rounded-full border ${chip}`}>
                          {alert.severity}
                        </span>
                      )}
                      {alert.field && (
                        <span className="text-[9px] font-mono text-slate-500 px-1.5 py-0.5 rounded-full border border-[#1E2D45]">
                          {alert.field}
                        </span>
                      )}
                    </div>
                    {alert.message && (
                      <p className="text-[11px] text-slate-400 leading-relaxed mt-1">
                        {alert.message}
                      </p>
                    )}
                  </div>
                </div>

                {correctable ? (
                  <button
                    type="button"
                    disabled={disabled}
                    onClick={() => onTrainOnAlert(alert)}
                    className="w-full flex items-center justify-center gap-1.5 px-3 py-1.5 rounded-lg bg-[#111827] hover:bg-[#1E293B] border border-[#1E2D45] hover:border-violet-500/40 text-[11px] font-semibold text-slate-200 transition-all disabled:opacity-40 disabled:cursor-not-allowed cursor-pointer"
                  >
                    <Wand2 className="w-3 h-3 text-violet-400" />
                    Train on this
                  </button>
                ) : (
                  /* Not correctable — say why, in the registry's own words. This
                     is a decision, not an oversight, so it is stated rather than
                     left as an unexplained missing button. */
                  <div className="flex items-start gap-2 text-[10px] text-slate-500 bg-[#070D1A] border border-[#1E2D45] rounded-lg px-2.5 py-2">
                    <ShieldOff className="w-3 h-3 shrink-0 mt-0.5" />
                    <span className="leading-relaxed">
                      {alert.notCorrectableReason ||
                        "This alert reports a processing fact, not a thresholded judgement — there is no setting to tune."}
                    </span>
                  </div>
                )}
              </div>
            );
          })
        )}
      </div>

      {/* ── Flag-as-missed footer ───────────────────────────────────────── */}
      {/* Panel-level, not per-row: a missed alert is by definition not attached
          to any row that exists. */}
      <div className="p-3 bg-[#0B1120]/90 border-t border-[#1E2D45] shrink-0">
        <button
          type="button"
          data-testid="trainer-flag-missed"
          disabled={disabled}
          onClick={onFlagMissed}
          className="w-full flex items-center justify-center gap-1.5 px-3 py-2 rounded-lg bg-amber-600/15 hover:bg-amber-600/25 border border-amber-500/30 text-[11px] font-semibold text-amber-200 transition-all disabled:opacity-40 disabled:cursor-not-allowed cursor-pointer"
        >
          <Flag className="w-3.5 h-3.5" />
          Flag an alert you expected but didn&apos;t get
        </button>
      </div>
    </div>
  );
}
