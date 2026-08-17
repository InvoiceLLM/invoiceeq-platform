"use client";

import React, { useEffect, useState } from "react";
import { X, Flag, AlertTriangle, Loader2 } from "lucide-react";
import { AlertTypeSpec, ExtractedVariable, trainerService } from "@/lib/trainer-service";

/**
 * Feature 14 Component: FlagMissedAlertModal — "I expected an alert here"
 *
 * FOR MANAGERS & DEVELOPERS:
 * The correction for something that *didn't* happen: a field or line item the
 * system read without complaint, where the user expected a check to fire.
 *
 * THE STRUCTURE/PROSE INVERSION IS THE POINT.
 * The flow this replaces took a free-text sentence and had an LLM decide what
 * rule it meant. Here the two primary inputs are both structured picks:
 *
 *   * **which alert type** you expected — from the backend's registry
 *     (`GET /trainer/alert-types?flaggable_only=true`), never free text;
 *   * **which field** it should have fired on — from this invoice's own
 *     extracted fields, so it is a real field with a real stored value.
 *
 * The free-text box is explicitly **optional and secondary**, and the UI says
 * so. The backend prompt is anchored on the registry pick plus the real stored
 * value of that field on this specific invoice, so an empty context box still
 * produces a grounded rule and a rambling one cannot become the whole input.
 *
 * This is the one correction path that uses an LLM at all, and it fails closed:
 * on a drafting failure the backend 502s and stages nothing rather than
 * promoting the raw text into a rule (the Gap 212 contract).
 */

interface FlagMissedAlertModalProps {
  isOpen: boolean;
  onClose: () => void;
  onSubmit: (payload: { alertType: string; field: string; context: string }) => Promise<void>;
  /** This invoice's extracted fields, for the field picker. */
  variables: ExtractedVariable[];
  isSubmitting?: boolean;
  errorText?: string | null;
  /**
   * Pre-selected field, used when this modal is opened from the chat lane's
   * "the PDF disagrees with what we stored" redirect — the backend hands back
   * the invoice and field, so the user shouldn't have to re-pick them.
   */
  prefillField?: string | null;
}

export default function FlagMissedAlertModal({
  isOpen,
  onClose,
  onSubmit,
  variables,
  isSubmitting = false,
  errorText = null,
  prefillField = null,
}: FlagMissedAlertModalProps) {
  const [types, setTypes] = useState<AlertTypeSpec[]>([]);
  const [loadingTypes, setLoadingTypes] = useState(false);
  const [alertType, setAlertType] = useState("");
  const [field, setField] = useState("");
  const [context, setContext] = useState("");

  // Registry fetch is lazy — it only happens when this modal is actually opened,
  // rather than on every Trainer page load for a flow most sessions never use.
  useEffect(() => {
    if (!isOpen) return;
    setAlertType("");
    setContext("");
    setField(prefillField || "");
    let cancelled = false;
    setLoadingTypes(true);
    trainerService
      .getAlertTypes(true)
      .then((registry) => {
        if (!cancelled) setTypes(registry.alertTypes);
      })
      .catch(() => {
        if (!cancelled) setTypes([]);
      })
      .finally(() => {
        if (!cancelled) setLoadingTypes(false);
      });
    return () => {
      cancelled = true;
    };
  }, [isOpen, prefillField]);

  if (!isOpen) return null;

  const selectedSpec = types.find((t) => t.type === alertType);

  // When the picked alert type names a default field and the user hasn't chosen
  // one, offer it — but never silently submit it, since the field is a primary
  // input and has to be a deliberate choice.
  const effectiveField = field || "";
  const canSubmit = !isSubmitting && !!alertType && !!effectiveField;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/75 backdrop-blur-md">
      <div
        data-testid="flag-missed-modal"
        className="w-full max-w-lg bg-[#070D1A]/95 border border-amber-500/40 rounded-2xl shadow-2xl shadow-black/50 overflow-hidden flex flex-col max-h-[90vh]"
      >
        {/* ── Header ──────────────────────────────────────────────────── */}
        <div className="px-5 py-3.5 bg-[#0B1120]/90 border-b border-[#1E2D45] flex items-center justify-between shrink-0">
          <div className="flex items-center gap-3 min-w-0">
            <div className="p-2 rounded-xl border bg-amber-500/10 text-amber-400 border-amber-500/25 shrink-0">
              <Flag className="w-4 h-4" />
            </div>
            <div className="min-w-0">
              <h3 className="text-sm font-semibold text-white leading-tight">
                Flag a missed alert
              </h3>
              <span className="text-[11px] text-slate-400 truncate block">
                Something the system should have caught on this invoice
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
          {/* 1. Which alert type — a registry pick, the primary input */}
          <div>
            <label
              htmlFor="missed-alert-type"
              className="text-[10px] font-semibold uppercase tracking-wider text-slate-400 block mb-1.5"
            >
              Which alert did you expect? <span className="text-amber-400">*</span>
            </label>
            {loadingTypes ? (
              <div className="flex items-center gap-2 text-[11px] text-slate-500 py-2">
                <Loader2 className="w-3.5 h-3.5 animate-spin text-blue-400" />
                Loading alert types…
              </div>
            ) : (
              <select
                id="missed-alert-type"
                data-testid="missed-alert-type"
                value={alertType}
                onChange={(e) => {
                  const next = e.target.value;
                  setAlertType(next);
                  // Offer the type's default field as a starting point when the
                  // user hasn't already picked one.
                  const spec = types.find((t) => t.type === next);
                  if (!field && spec?.defaultField) setField(spec.defaultField);
                }}
                className="w-full rounded-lg border border-[#1E2D45] bg-[#0B0F19] px-3 py-2 text-xs text-slate-200 focus:outline-none focus:border-amber-500/50 cursor-pointer"
              >
                <option value="">— Choose the check you expected to fire —</option>
                {types.map((t) => (
                  <option key={t.type} value={t.type}>
                    {t.label}
                  </option>
                ))}
              </select>
            )}
            {selectedSpec && (
              <span className="text-[10px] text-slate-600 block mt-1">
                Produced by {selectedSpec.producer}
              </span>
            )}
          </div>

          {/* 2. Which field — the other primary input */}
          <div>
            <label
              htmlFor="missed-alert-field"
              className="text-[10px] font-semibold uppercase tracking-wider text-slate-400 block mb-1.5"
            >
              On which field or line item? <span className="text-amber-400">*</span>
            </label>
            {variables.length > 0 ? (
              <select
                id="missed-alert-field"
                data-testid="missed-alert-field"
                value={field}
                onChange={(e) => setField(e.target.value)}
                className="w-full rounded-lg border border-[#1E2D45] bg-[#0B0F19] px-3 py-2 text-xs text-slate-200 focus:outline-none focus:border-amber-500/50 cursor-pointer"
              >
                <option value="">— Choose a field —</option>
                {variables.map((v) => (
                  <option key={v.id} value={v.key}>
                    {v.label} ({v.key}){v.value ? ` — ${v.value}` : ""}
                  </option>
                ))}
                {/* The picked alert type's default field, when this invoice's
                    extraction didn't produce it as a variable — e.g. a check on
                    a field that failed to extract at all, which is precisely a
                    case worth flagging. */}
                {selectedSpec?.defaultField &&
                  !variables.some((v) => v.key === selectedSpec.defaultField) && (
                    <option value={selectedSpec.defaultField}>
                      {selectedSpec.defaultField} (not extracted on this invoice)
                    </option>
                  )}
              </select>
            ) : (
              <input
                id="missed-alert-field"
                data-testid="missed-alert-field"
                type="text"
                value={field}
                onChange={(e) => setField(e.target.value)}
                placeholder="e.g. tax_amount"
                className="w-full rounded-lg border border-[#1E2D45] bg-[#0B0F19] px-3 py-2 text-xs text-slate-200 placeholder:text-slate-600 focus:outline-none focus:border-amber-500/50"
              />
            )}
          </div>

          {/* 3. Optional prose — explicitly secondary */}
          <div>
            <label
              htmlFor="missed-alert-context"
              className="text-[10px] font-semibold uppercase tracking-wider text-slate-400 block mb-1.5"
            >
              Anything else worth knowing?{" "}
              <span className="text-slate-600 normal-case font-normal tracking-normal">
                (optional)
              </span>
            </label>
            <textarea
              id="missed-alert-context"
              data-testid="missed-alert-context"
              rows={3}
              value={context}
              onChange={(e) => setContext(e.target.value)}
              placeholder="e.g. this vendor prints tax inclusive of freight"
              className="w-full rounded-lg border border-[#1E2D45] bg-[#0B0F19] px-3 py-2 text-xs text-slate-200 placeholder:text-slate-600 focus:outline-none focus:border-amber-500/50"
            />
            <span className="text-[10px] text-slate-600 block mt-1 leading-relaxed">
              Background only. The rule is built from your two picks above plus this
              invoice&apos;s real stored value for that field — leaving this empty is
              perfectly fine.
            </span>
          </div>

          {errorText && (
            <div className="flex items-start gap-2 p-3 rounded-xl bg-red-500/10 border border-red-500/30 text-[11px] text-red-300">
              <AlertTriangle className="w-3.5 h-3.5 shrink-0 mt-0.5" />
              <span className="leading-relaxed">{errorText}</span>
            </div>
          )}
        </div>

        {/* ── Footer ──────────────────────────────────────────────────── */}
        <div className="px-5 py-3.5 bg-[#0B1120]/90 border-t border-[#1E2D45] flex items-center justify-between gap-3 shrink-0">
          <span className="text-[10px] text-slate-500 leading-tight">
            Staged only — you&apos;ll review it before anything is saved.
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
              data-testid="stage-missed-alert"
              onClick={() => onSubmit({ alertType, field: effectiveField, context })}
              disabled={!canSubmit}
              className="px-4 py-2 rounded-xl bg-amber-600 hover:bg-amber-500 text-white text-xs font-semibold shadow-lg transition-all flex items-center gap-2 cursor-pointer disabled:opacity-40 disabled:cursor-not-allowed"
            >
              {isSubmitting ? (
                <>
                  <span className="w-3.5 h-3.5 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                  <span>Drafting…</span>
                </>
              ) : (
                <span>Stage this correction</span>
              )}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
