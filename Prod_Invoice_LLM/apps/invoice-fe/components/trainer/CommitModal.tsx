"use client";

import React from "react";
import {
  CheckCircle2,
  AlertTriangle,
  X,
  ArrowRight,
  Loader2,
  HelpCircle,
  FileSearch,
  Layers,
  Sparkles,
} from "lucide-react";
import { PreviewResult, RuleDescription, TrainerScope } from "@/lib/trainer-service";

/**
 * Feature 14 Component: CommitModal — the preview-before-commit gate
 *
 * FOR MANAGERS & DEVELOPERS:
 * This used to be a confirmation dialog: it listed the rule sentences about to
 * be saved and warned about the re-audit. It is now the **checkpoint the whole
 * redesign is built around**, and it is the one screen every correction path
 * funnels through — tolerance, confidence threshold, severity/message override,
 * missed alert, and (via the chat lane) a chat-behaviour rule preview rendered
 * by the same component family.
 *
 * Three things, in this order:
 *
 *   1. **Structured interpretation** — field / condition / scope in plain terms,
 *      from `services/rule_impact.py::describe_rule()`. The user approves a
 *      *rule*, not a sentence an LLM happened to generate.
 *   2. **Historical impact** — and this is where the honesty matters:
 *        - `exact`          → a real replay against stored invoices, using the
 *                             same verification functions the pipeline uses.
 *        - `not_computable` → a free-text extraction rule, whose effect depends
 *                             on how a model reads a PDF. **No number is shown.**
 *                             Never a blank, never a fabricated zero.
 *        - `partial`        → some of both, with the uncomputable part named.
 *   3. **An explicit Confirm** — carrying the `previewToken`, so the commit is
 *      provably against the rules the user just saw (the backend 409s on drift).
 *
 * Global scope is gone from this dialog because Global-scope rule *creation* is
 * gone from the product. `outbound` is a real scope here: an outbound invoice
 * has no vendor at all (the counterparty is the customer), so its rules live on
 * the outbound-global template — structural, not an oversight.
 */

interface CommitModalProps {
  isOpen: boolean;
  onClose: () => void;
  onConfirm: () => void;
  /** Session scope — drives the re-audit copy only. */
  scope: TrainerScope;
  vendorName?: string;
  /** Null while the preview call is in flight. */
  preview: PreviewResult | null;
  isLoadingPreview?: boolean;
  isSubmitting?: boolean;
  /** Preview or commit failure text (incl. the guardrail 400 and the 409). */
  errorText?: string | null;
}

const KIND_LABELS: Record<string, string> = {
  extraction: "Extraction rule",
  tolerance_override: "Tolerance",
  confidence_threshold_override: "Confidence threshold",
  alert_override: "Severity / message",
};

function RuleCard({ rule }: { rule: RuleDescription }) {
  return (
    <div className="p-3 bg-[#0B1120] border border-emerald-500/15 rounded-xl space-y-2">
      <div className="flex items-center gap-2 flex-wrap">
        <span className="text-[9px] font-mono uppercase px-1.5 py-0.5 rounded-full bg-emerald-500/10 text-emerald-300 border border-emerald-500/30">
          {KIND_LABELS[rule.kind] || rule.kind}
        </span>
        <span className="text-[9px] font-mono text-slate-500 px-1.5 py-0.5 rounded-full border border-[#1E2D45]">
          field: {rule.field}
        </span>
        {rule.scope && (
          <span className="text-[9px] font-mono text-slate-500 px-1.5 py-0.5 rounded-full border border-[#1E2D45]">
            scope: {rule.scope}
          </span>
        )}
        {rule.sourceAlertType && (
          <span className="text-[9px] font-mono text-slate-500 px-1.5 py-0.5 rounded-full border border-[#1E2D45]">
            {rule.sourceAlertType}
          </span>
        )}
      </div>
      {rule.condition && (
        <div className="text-[10px] font-mono text-slate-500">{rule.condition}</div>
      )}
      <p className="text-[11px] text-emerald-200 leading-relaxed">{rule.text}</p>
    </div>
  );
}

function ImpactBlock({ preview }: { preview: PreviewResult }) {
  const impact = preview.impact;
  if (!impact) return null;

  const isExact = impact.kind === "exact";
  const isPartial = impact.kind === "partial";
  const notComputable = impact.kind === "not_computable";

  return (
    <div className="space-y-2" data-testid="preview-impact">
      <span className="text-slate-300 font-semibold block">Effect on your history</span>

      {notComputable ? (
        /* The honest empty state. This is deliberately NOT a zero: a text rule's
           effect depends on how the model reads a PDF, and a "0 invoices
           affected" here would be a fabricated number that reads as reassurance. */
        <div
          data-testid="impact-not-computable"
          className="flex items-start gap-2.5 p-3.5 rounded-xl bg-blue-500/5 border border-blue-500/25"
        >
          <HelpCircle className="w-4 h-4 text-blue-400 shrink-0 mt-0.5" />
          <div>
            <span className="font-semibold text-blue-200 block mb-1">
              Impact can&apos;t be computed for this rule
            </span>
            <p className="text-slate-400 leading-relaxed text-[11px]">{impact.summary}</p>
          </div>
        </div>
      ) : (
        <div
          className={`p-3.5 rounded-xl border ${
            isPartial
              ? "bg-amber-500/5 border-amber-500/25"
              : "bg-emerald-500/5 border-emerald-500/25"
          }`}
        >
          <div className="flex items-start gap-2.5">
            <FileSearch
              className={`w-4 h-4 shrink-0 mt-0.5 ${isPartial ? "text-amber-400" : "text-emerald-400"}`}
            />
            <div className="min-w-0 flex-1 space-y-2">
              <p className="text-slate-300 leading-relaxed text-[11px]">{impact.summary}</p>

              <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
                {[
                  { label: "Examined", value: impact.invoicesExamined },
                  { label: "Affected", value: impact.invoicesAffected },
                  { label: "Alerts removed", value: impact.alertsRemoved },
                  { label: "Alerts added", value: impact.alertsAdded },
                ].map((stat) => (
                  <div
                    key={stat.label}
                    className="rounded-lg border border-[#1E2D45] bg-[#070D1A] px-2 py-1.5"
                  >
                    <span className="block text-[9px] uppercase tracking-wider text-slate-500">
                      {stat.label}
                    </span>
                    <span className="block text-xs font-mono text-slate-200">
                      {stat.value === null || stat.value === undefined ? "—" : stat.value}
                    </span>
                  </div>
                ))}
              </div>

              {impact.alertsRelabelled !== null && impact.alertsRelabelled !== undefined && (
                <p className="text-[10px] text-slate-500">
                  {impact.alertsRelabelled} existing alert(s) would read differently.
                </p>
              )}
            </div>
          </div>
        </div>
      )}

      {/* The uncomputable part of a partial result, named explicitly rather than
          folded silently into the totals above. */}
      {impact.notComputable?.length > 0 && !notComputable && (
        <div className="space-y-1.5">
          {impact.notComputable.map((nc, i) => (
            <div
              key={i}
              className="flex items-start gap-2 p-2.5 rounded-lg bg-amber-500/5 border border-amber-500/20 text-[10px] text-amber-200/90"
            >
              <AlertTriangle className="w-3 h-3 shrink-0 mt-0.5" />
              <span className="leading-relaxed">
                {nc.reason}
                {Array.isArray(nc.appliesTo) && nc.appliesTo.length > 0
                  ? ` (${nc.appliesTo.join(", ")})`
                  : typeof nc.appliesTo === "string" && nc.appliesTo
                  ? ` (${nc.appliesTo})`
                  : ""}
              </span>
            </div>
          ))}
        </div>
      )}

      {/* The real invoices behind the number — a list, not just a count. */}
      {impact.sample?.length > 0 && (
        <div className="space-y-1" data-testid="impact-sample">
          <span className="text-[10px] uppercase tracking-wider text-slate-500 block">
            Invoices that would change
          </span>
          <div className="max-h-32 overflow-y-auto rounded-xl border border-[#1E2D45] bg-[#070D1A] divide-y divide-[#131E2E]">
            {impact.sample.map((s) => (
              <div key={s.invoiceId} className="px-3 py-1.5 flex items-center gap-2">
                <span className="text-[11px] text-slate-300 font-medium truncate flex-1">
                  {s.invoiceNumber || s.invoiceId.slice(0, 8)}
                  {s.vendorName ? ` · ${s.vendorName}` : ""}
                </span>
                {s.alertsRemoved?.length > 0 && (
                  <span className="text-[9px] font-mono text-emerald-300 shrink-0">
                    −{s.alertsRemoved.length}
                  </span>
                )}
                {s.alertsAdded?.length > 0 && (
                  <span className="text-[9px] font-mono text-amber-300 shrink-0">
                    +{s.alertsAdded.length}
                  </span>
                )}
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

export default function CommitModal({
  isOpen,
  onClose,
  onConfirm,
  scope,
  vendorName,
  preview,
  isLoadingPreview = false,
  isSubmitting = false,
  errorText = null,
}: CommitModalProps) {
  if (!isOpen) return null;

  const isOutbound = scope === "outbound";
  const isNewVendor = scope === "new_vendor";

  const heading = isOutbound
    ? "Commit Outbound Rules"
    : isNewVendor
    ? "Commit Cold-Start Template"
    : "Commit Vendor Template";

  const reauditNotice = isOutbound
    ? // Deviation 5 in the BE spec: an outbound commit deliberately does not
      // enqueue a re-audit, because "every vendor" would fan out across the
      // tenant's whole INBOUND history for a rule that only affects outbound.
      "Applies to new outbound invoices immediately. Existing outbound invoices are not re-audited in this release."
    : isNewVendor
    ? "Saves a new vendor template. Nothing is re-audited, because this vendor has no processed invoices yet."
    : `Queues a background re-audit of stored invoices for ${vendorName || "this vendor"}. New invoices are affected immediately.`;

  const Icon = isNewVendor ? Sparkles : Layers;
  const newRules = preview?.newRules ?? [];
  const hasNothingToCommit = !isLoadingPreview && !!preview && newRules.length === 0;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/75 backdrop-blur-md">
      <div
        data-testid="commit-preview-modal"
        className="w-full max-w-2xl bg-[#070D1A]/95 border border-emerald-500/40 rounded-2xl shadow-2xl shadow-black/50 overflow-hidden flex flex-col max-h-[90vh]"
      >
        {/* ── Header ──────────────────────────────────────────────────── */}
        <div className="px-6 py-4 bg-[#0B1120]/90 border-b border-[#1E2D45] flex items-center justify-between shrink-0">
          <div className="flex items-center gap-3 min-w-0">
            <div className="p-2 rounded-xl border bg-emerald-500/10 text-emerald-400 border-emerald-500/25 shadow-md shrink-0">
              <Icon className="w-5 h-5" />
            </div>
            <div className="min-w-0">
              <h3 className="text-sm font-semibold text-white leading-tight">{heading}</h3>
              <span className="text-[11px] text-slate-400 font-mono truncate block">
                {preview?.vendorName || vendorName || (isOutbound ? "Outbound" : "Vendor")}
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
        <div className="p-6 space-y-4 text-xs overflow-y-auto">
          {isLoadingPreview ? (
            <div className="flex items-center gap-2.5 py-10 justify-center text-slate-400">
              <Loader2 className="w-4 h-4 animate-spin text-emerald-400" />
              <span>Replaying these rules against your stored invoices…</span>
            </div>
          ) : errorText ? (
            <div
              data-testid="preview-error"
              className="flex items-start gap-2.5 p-4 rounded-xl bg-red-500/10 border border-red-500/30 text-red-300"
            >
              <AlertTriangle className="w-4 h-4 shrink-0 mt-0.5" />
              <div>
                <span className="font-semibold block mb-1">Nothing was saved</span>
                <p className="leading-relaxed text-[11px]">{errorText}</p>
              </div>
            </div>
          ) : hasNothingToCommit ? (
            <div className="flex items-start gap-2.5 p-4 rounded-xl bg-slate-500/5 border border-[#1E2D45] text-slate-400">
              <HelpCircle className="w-4 h-4 shrink-0 mt-0.5" />
              <div>
                <span className="font-semibold text-slate-300 block mb-1">
                  No new rules to commit
                </span>
                <p className="leading-relaxed text-[11px]">
                  Everything staged here is already live on this template. Correct an
                  alert on the invoice first.
                </p>
              </div>
            </div>
          ) : (
            preview && (
              <>
                {/* 1. Structured interpretation */}
                <div className="space-y-2">
                  <span className="text-slate-300 font-semibold block">
                    What you&apos;re about to teach ({newRules.length})
                  </span>
                  <div className="space-y-1.5 max-h-56 overflow-y-auto">
                    {newRules.map((rule, i) => (
                      <RuleCard key={i} rule={rule} />
                    ))}
                  </div>
                </div>

                {/* 2. Historical impact */}
                <ImpactBlock preview={preview} />

                {/* Re-audit consequence */}
                <div className="p-3.5 bg-amber-500/8 border border-amber-500/25 rounded-xl flex items-start gap-2.5">
                  <AlertTriangle className="w-4 h-4 text-amber-400 shrink-0 mt-0.5" />
                  <div>
                    <span className="font-semibold text-amber-300 block mb-1">
                      What happens when you confirm
                    </span>
                    <p className="text-slate-400 leading-relaxed text-[11px]">
                      {reauditNotice}
                    </p>
                  </div>
                </div>
              </>
            )
          )}
        </div>

        {/* ── Footer ──────────────────────────────────────────────────── */}
        <div className="px-6 py-4 bg-[#0B1120]/90 border-t border-[#1E2D45] flex items-center justify-end gap-3 shrink-0">
          <button
            type="button"
            onClick={onClose}
            disabled={isSubmitting}
            className="px-4 py-2 rounded-xl border border-[#1E2D45] text-slate-300 hover:text-white hover:bg-[#111827] text-xs font-medium transition-colors cursor-pointer"
          >
            Cancel
          </button>
          <button
            type="button"
            data-testid="confirm-commit"
            onClick={onConfirm}
            disabled={isSubmitting || isLoadingPreview || !preview || newRules.length === 0}
            className="px-5 py-2 rounded-xl bg-emerald-600 hover:bg-emerald-500 text-white text-xs font-semibold shadow-lg shadow-emerald-600/20 transition-all flex items-center gap-2 cursor-pointer disabled:opacity-40 disabled:cursor-not-allowed"
          >
            {isSubmitting ? (
              <>
                <span className="w-3.5 h-3.5 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                <span>Committing…</span>
              </>
            ) : (
              <>
                <CheckCircle2 className="w-4 h-4" />
                <span>Confirm &amp; Commit</span>
                <ArrowRight className="w-3.5 h-3.5" />
              </>
            )}
          </button>
        </div>
      </div>
    </div>
  );
}
