"use client";

import React, { useState } from "react";
import { X, Wand2, ShieldOff, AlertTriangle, ArrowLeft } from "lucide-react";
import { TrainerAlert } from "@/lib/trainer-service";

/**
 * Feature 14 Component: AlertCorrectionModal — "Train on this"
 *
 * FOR MANAGERS & DEVELOPERS:
 * Opened from one alert on the session's invoice. Two options, then a form
 * whose *shape depends on the alert type*, because the backend's knobs genuinely
 * differ and pretending otherwise would ship controls that silently do nothing:
 *
 *   A. "This alert was unnecessary"
 *      - tolerance-overridable type  -> abs_tol / rel_tol form, showing the
 *        current effective tolerance next to the proposed one.
 *      - `low_confidence_field`      -> a **confidence threshold** form. A
 *        different parameter on a different backend function
 *        (`verify_field_confidence`, default 0.4), so it deliberately does not
 *        reuse the tolerance UI.
 *      - anything else (the five `*_not_verified_in_source` types, duplicates,
 *        failures, timeouts) -> **no form at all**, and the registry's own
 *        explanation instead. Those types ask a verbatim-presence question with
 *        no numeric band to widen; the backend 400s on them by design.
 *   B. "Wrong severity or message" — severity dropdown + editable message.
 *      Never changes whether the alert fires.
 *
 * Nothing here writes to a template. Every submit *stages* a candidate rule on
 * the session, which then has to clear the preview gate.
 */

export type CorrectionKind = "unnecessary" | "severity_message";

interface AlertCorrectionModalProps {
  isOpen: boolean;
  alert: TrainerAlert | null;
  onClose: () => void;
  onSubmitTolerance: (payload: { absTol: number; relTol: number }) => Promise<void>;
  onSubmitThreshold: (payload: { threshold: number }) => Promise<void>;
  onSubmitOverride: (payload: { severity?: string; message?: string }) => Promise<void>;
  isSubmitting?: boolean;
  /** Backend error text from the last attempt, if any. */
  errorText?: string | null;
}

/**
 * Backend defaults, shown as "current" so the numeric forms are a comparison
 * rather than a blank box.
 *
 * These mirror `utils/verification_tools.py::DEFAULT_ABS_TOLERANCE` and
 * `CONFIDENCE_THRESHOLD`. They are labelled "default" rather than "current" in
 * the UI copy on purpose: this tenant may already have committed an override,
 * and the session payload does not carry the resolved effective value, so
 * claiming to show "your current setting" would sometimes be wrong. Stating the
 * shipped default is something we can always say truthfully.
 */
const DEFAULT_ABS_TOLERANCE = 0.02;
const DEFAULT_REL_TOLERANCE = 0;
const DEFAULT_CONFIDENCE_THRESHOLD = 0.4;

export default function AlertCorrectionModal({
  isOpen,
  alert,
  onClose,
  onSubmitTolerance,
  onSubmitThreshold,
  onSubmitOverride,
  isSubmitting = false,
  errorText = null,
}: AlertCorrectionModalProps) {
  const [kind, setKind] = useState<CorrectionKind | null>(null);
  const [absTol, setAbsTol] = useState("0.02");
  const [relTol, setRelTol] = useState("0.01");
  const [threshold, setThreshold] = useState("0.30");
  const [severity, setSeverity] = useState("");
  const [message, setMessage] = useState("");

  // Reset the sub-form whenever a different alert is opened, so a numeric value
  // typed for one alert can't be submitted against another.
  React.useEffect(() => {
    if (!isOpen) return;
    setKind(null);
    setAbsTol("0.02");
    setRelTol("0.01");
    setThreshold("0.30");
    setSeverity("");
    setMessage(alert?.message || "");
  }, [isOpen, alert]);

  if (!isOpen || !alert) return null;

  const form = alert.correctionForm;
  const canTuneNumerically = form === "tolerance" || form === "confidence_threshold";

  const handleSubmit = async () => {
    if (kind === "severity_message") {
      await onSubmitOverride({
        severity: severity || undefined,
        message: message.trim() || undefined,
      });
      return;
    }
    if (form === "tolerance") {
      await onSubmitTolerance({ absTol: Number(absTol), relTol: Number(relTol) });
      return;
    }
    if (form === "confidence_threshold") {
      await onSubmitThreshold({ threshold: Number(threshold) });
    }
  };

  const overrideIsEmpty = !severity && !message.trim();
  const submitDisabled =
    isSubmitting ||
    (kind === "severity_message" && overrideIsEmpty) ||
    (kind === "unnecessary" && !canTuneNumerically);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/75 backdrop-blur-md">
      <div
        data-testid="alert-correction-modal"
        className="w-full max-w-lg bg-[#070D1A]/95 border border-violet-500/40 rounded-2xl shadow-2xl shadow-black/50 overflow-hidden flex flex-col max-h-[90vh]"
      >
        {/* ── Header ──────────────────────────────────────────────────── */}
        <div className="px-5 py-3.5 bg-[#0B1120]/90 border-b border-[#1E2D45] flex items-center justify-between shrink-0">
          <div className="flex items-center gap-3 min-w-0">
            <div className="p-2 rounded-xl border bg-violet-500/10 text-violet-400 border-violet-500/25 shrink-0">
              <Wand2 className="w-4 h-4" />
            </div>
            <div className="min-w-0">
              <h3 className="text-sm font-semibold text-white leading-tight truncate">
                Train on this alert
              </h3>
              <span className="text-[11px] text-slate-400 font-mono truncate block">
                {alert.label}
                {alert.field ? ` · ${alert.field}` : ""}
              </span>
            </div>
          </div>
          <button
            onClick={onClose}
            disabled={isSubmitting}
            className="p-1.5 rounded-xl text-slate-400 hover:text-white hover:bg-[#111827] transition-colors cursor-pointer shrink-0"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* ── Body ────────────────────────────────────────────────────── */}
        <div className="p-5 space-y-4 text-xs overflow-y-auto">
          {kind === null ? (
            <>
              <p className="text-slate-400 leading-relaxed">
                What was wrong with this alert?
              </p>

              <button
                type="button"
                data-testid="correction-option-unnecessary"
                onClick={() => setKind("unnecessary")}
                className="w-full text-left rounded-xl border border-[#1E2D45] bg-[#0B1120]/70 hover:border-violet-500/40 hover:bg-[#111827] p-3.5 transition-all cursor-pointer"
              >
                <span className="text-xs font-semibold text-slate-100 block mb-1">
                  It was unnecessary — it shouldn&apos;t have fired
                </span>
                <span className="text-[11px] text-slate-500 leading-relaxed">
                  {form === "tolerance"
                    ? "Widen the tolerance this check allows before it flags a difference."
                    : form === "confidence_threshold"
                    ? "Lower the confidence threshold at which a field is flagged as uncertain."
                    : "This alert type has no numeric setting to adjust — see why inside."}
                </span>
              </button>

              <button
                type="button"
                data-testid="correction-option-severity"
                onClick={() => setKind("severity_message")}
                className="w-full text-left rounded-xl border border-[#1E2D45] bg-[#0B1120]/70 hover:border-violet-500/40 hover:bg-[#111827] p-3.5 transition-all cursor-pointer"
              >
                <span className="text-xs font-semibold text-slate-100 block mb-1">
                  Wrong severity or message
                </span>
                <span className="text-[11px] text-slate-500 leading-relaxed">
                  It was right to fire, but it&apos;s labelled or worded wrongly. This
                  never changes whether the alert fires.
                </span>
              </button>
            </>
          ) : (
            <>
              <button
                type="button"
                onClick={() => setKind(null)}
                disabled={isSubmitting}
                className="flex items-center gap-1.5 text-[11px] text-slate-400 hover:text-slate-200 transition-colors cursor-pointer"
              >
                <ArrowLeft className="w-3 h-3" />
                Back
              </button>

              {/* ── A. Unnecessary ─────────────────────────────────── */}
              {kind === "unnecessary" && form === "tolerance" && (
                <div className="space-y-3" data-testid="tolerance-form">
                  <p className="text-slate-400 leading-relaxed">
                    This check flags a difference once it exceeds its tolerance. Widen it
                    so a difference this size is treated as acceptable.
                  </p>
                  <div className="grid grid-cols-2 gap-3">
                    <div>
                      <label className="text-[10px] font-semibold uppercase tracking-wider text-slate-400 block mb-1.5">
                        Absolute tolerance
                      </label>
                      <input
                        type="number"
                        step="0.01"
                        min="0"
                        value={absTol}
                        onChange={(e) => setAbsTol(e.target.value)}
                        className="w-full rounded-lg border border-[#1E2D45] bg-[#0B0F19] px-3 py-2 text-xs text-slate-200 focus:outline-none focus:border-violet-500/50"
                      />
                      <span className="text-[10px] text-slate-600 block mt-1">
                        Ships as {DEFAULT_ABS_TOLERANCE.toFixed(2)}
                      </span>
                    </div>
                    <div>
                      <label className="text-[10px] font-semibold uppercase tracking-wider text-slate-400 block mb-1.5">
                        Relative tolerance
                      </label>
                      <input
                        type="number"
                        step="0.005"
                        min="0"
                        max="1"
                        value={relTol}
                        onChange={(e) => setRelTol(e.target.value)}
                        className="w-full rounded-lg border border-[#1E2D45] bg-[#0B0F19] px-3 py-2 text-xs text-slate-200 focus:outline-none focus:border-violet-500/50"
                      />
                      <span className="text-[10px] text-slate-600 block mt-1">
                        Ships as {DEFAULT_REL_TOLERANCE} · 0.01 = 1%
                      </span>
                    </div>
                  </div>
                </div>
              )}

              {kind === "unnecessary" && form === "confidence_threshold" && (
                <div className="space-y-3" data-testid="threshold-form">
                  <p className="text-slate-400 leading-relaxed">
                    A field is flagged when the extraction&apos;s confidence falls below
                    this threshold. Lower it so a read this confident is accepted.
                  </p>
                  <div>
                    <label className="text-[10px] font-semibold uppercase tracking-wider text-slate-400 block mb-1.5">
                      Confidence threshold
                    </label>
                    <input
                      type="number"
                      step="0.05"
                      min="0.05"
                      max="1"
                      value={threshold}
                      onChange={(e) => setThreshold(e.target.value)}
                      className="w-full rounded-lg border border-[#1E2D45] bg-[#0B0F19] px-3 py-2 text-xs text-slate-200 focus:outline-none focus:border-violet-500/50"
                    />
                    <span className="text-[10px] text-slate-600 block mt-1">
                      Ships as {DEFAULT_CONFIDENCE_THRESHOLD}. Must be above 0 — a
                      threshold of 0 would switch the check off entirely, which is
                      suppression rather than tuning, and isn&apos;t offered here.
                    </span>
                  </div>
                </div>
              )}

              {kind === "unnecessary" && !canTuneNumerically && (
                /* The five source-text types and the fact-reporting ones. No form,
                   by design — the backend rejects a tolerance write for them, so
                   rendering one would be a control that silently does nothing. */
                <div
                  data-testid="not-tunable-explainer"
                  className="flex items-start gap-2.5 p-3.5 rounded-xl bg-slate-500/5 border border-[#1E2D45]"
                >
                  <ShieldOff className="w-4 h-4 text-slate-400 shrink-0 mt-0.5" />
                  <div className="space-y-2">
                    <span className="font-semibold text-slate-300 block">
                      There is no numeric setting to adjust for this alert type
                    </span>
                    <p className="text-slate-500 leading-relaxed">
                      {alert.notCorrectableReason ||
                        "This check asks whether a figure appears in the source document at all — a yes/no question, with no tolerance band to widen."}
                    </p>
                    <p className="text-slate-500 leading-relaxed">
                      You can still correct how it reads with{" "}
                      <button
                        type="button"
                        onClick={() => setKind("severity_message")}
                        className="text-violet-300 hover:text-violet-200 underline cursor-pointer"
                      >
                        wrong severity or message
                      </button>
                      .
                    </p>
                  </div>
                </div>
              )}

              {/* ── B. Severity / message ──────────────────────────── */}
              {kind === "severity_message" && (
                <div className="space-y-3" data-testid="severity-form">
                  <p className="text-slate-400 leading-relaxed">
                    Relabel this alert wherever it fires. It will still fire — this only
                    changes how it reads.
                  </p>
                  <div>
                    <label className="text-[10px] font-semibold uppercase tracking-wider text-slate-400 block mb-1.5">
                      Severity
                    </label>
                    <select
                      value={severity}
                      onChange={(e) => setSeverity(e.target.value)}
                      className="w-full rounded-lg border border-[#1E2D45] bg-[#0B0F19] px-3 py-2 text-xs text-slate-200 focus:outline-none focus:border-violet-500/50 cursor-pointer"
                    >
                      <option value="">— Leave unchanged —</option>
                      <option value="error">error</option>
                      <option value="warning">warning</option>
                      <option value="info">info</option>
                    </select>
                  </div>
                  <div>
                    <label className="text-[10px] font-semibold uppercase tracking-wider text-slate-400 block mb-1.5">
                      Message
                    </label>
                    <textarea
                      rows={3}
                      value={message}
                      onChange={(e) => setMessage(e.target.value)}
                      placeholder="How this alert should read"
                      className="w-full rounded-lg border border-[#1E2D45] bg-[#0B0F19] px-3 py-2 text-xs text-slate-200 placeholder:text-slate-600 focus:outline-none focus:border-violet-500/50"
                    />
                    <span className="text-[10px] text-slate-600 block mt-1">
                      The originally computed text is kept alongside yours, not
                      overwritten.
                    </span>
                  </div>
                  {overrideIsEmpty && (
                    <p className="text-[10px] text-amber-300/80">
                      Set a severity, a message, or both — an empty override would do
                      nothing.
                    </p>
                  )}
                </div>
              )}

              {errorText && (
                <div className="flex items-start gap-2 p-3 rounded-xl bg-red-500/10 border border-red-500/30 text-[11px] text-red-300">
                  <AlertTriangle className="w-3.5 h-3.5 shrink-0 mt-0.5" />
                  <span className="leading-relaxed">{errorText}</span>
                </div>
              )}
            </>
          )}
        </div>

        {/* ── Footer ──────────────────────────────────────────────────── */}
        {kind !== null && (
          <div className="px-5 py-3.5 bg-[#0B1120]/90 border-t border-[#1E2D45] flex items-center justify-between gap-3 shrink-0">
            <span className="text-[10px] text-slate-500 leading-tight">
              Staged only — you&apos;ll review the impact before anything is saved.
            </span>
            <div className="flex items-center gap-2 shrink-0">
              <button
                type="button"
                onClick={onClose}
                disabled={isSubmitting}
                className="px-3.5 py-2 rounded-xl border border-[#1E2D45] text-slate-300 hover:text-white hover:bg-[#111827] text-xs font-medium transition-colors cursor-pointer"
              >
                Cancel
              </button>
              <button
                type="button"
                data-testid="stage-correction"
                onClick={handleSubmit}
                disabled={submitDisabled}
                className="px-4 py-2 rounded-xl bg-violet-600 hover:bg-violet-500 text-white text-xs font-semibold shadow-lg transition-all flex items-center gap-2 cursor-pointer disabled:opacity-40 disabled:cursor-not-allowed"
              >
                {isSubmitting ? (
                  <>
                    <span className="w-3.5 h-3.5 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                    <span>Staging…</span>
                  </>
                ) : (
                  <span>Stage this correction</span>
                )}
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
