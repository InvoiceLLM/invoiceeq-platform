"use client";

import React from "react";
import {
  CheckCircle2,
  AlertTriangle,
  ShieldCheck,
  Layers,
  X,
  Sparkles,
  ArrowRight,
} from "lucide-react";
import { TrainerScope } from "@/lib/trainer-service";

/**
 * Feature 6 Component: CommitModal (Task 6.6)
 *
 * FOR MANAGERS & DEVELOPERS:
 * This modal pops up when the user clicks "Commit to Template Registry".
 * It displays a clear, scope-aware notice explaining the background re-audit behavior:
 *
 *   - Global Scope     → warns that committing re-audits ALL tenant vendors.
 *   - Existing Vendor  → warns that committing re-audits ALL invoices for THAT vendor.
 *   - New Vendor       → informs that a new cold-start template is saved (no past invoices).
 *
 * Design: Centered backdrop-blur modal card with gradient border on header,
 * scope-colored icon badge, amber impact banner, and animated Submit spinner.
 *
 * Target Endpoint (Task 10.6): POST /trainer/sessions/{id}/commit
 */

interface CommitModalProps {
  /** Controls modal visibility */
  isOpen: boolean;
  /** Callback fired to dismiss modal */
  onClose: () => void;
  /** Callback fired to confirm registry commit */
  onConfirm: () => void;
  /** Active rule scope */
  scope: TrainerScope;
  /** Active vendor name (Scope 2 or 3) */
  vendorName?: string;
  /** List of rules to be committed */
  activeRules: string[];
  /** Loading state while network request is in flight */
  isSubmitting?: boolean;
}

export default function CommitModal({
  isOpen,
  onClose,
  onConfirm,
  scope,
  vendorName,
  activeRules,
  isSubmitting = false,
}: CommitModalProps) {
  // Guard: do not render when closed
  if (!isOpen) return null;

  // ── Scope-dependent copy, icon, and color tokens ───────────────────────
  const scopeConfig = {
    global: {
      title: "Commit Global Template",
      subtitle: "Tenant-Wide Rule Registry",
      impactNotice:
        "Committing will queue a background re-audit across ALL vendors for this tenant. Proceed only after verifying the rule in the chat.",
      badge: "Tenant-Wide Global",
      Icon: ShieldCheck,
      ringColor: "border-blue-500/50",
      badgeCls: "bg-blue-500/10 text-blue-400 border-blue-500/25",
      confirmBtnCls: "bg-blue-600 hover:bg-blue-500 shadow-blue-600/20",
    },
    existing_vendor: {
      title: `Commit Vendor Template`,
      subtitle: vendorName || "Selected Vendor",
      impactNotice: `Committing will queue a background re-audit of all existing production invoices for ${
        vendorName || "this vendor"
      }. Rules take effect immediately on new invoices.`,
      badge: "Production Vendor Rule",
      Icon: Layers,
      ringColor: "border-emerald-500/50",
      badgeCls: "bg-emerald-500/10 text-emerald-400 border-emerald-500/25",
      confirmBtnCls: "bg-emerald-600 hover:bg-emerald-500 shadow-emerald-600/20",
    },
    new_vendor: {
      title: `Commit Cold-Start Template`,
      subtitle: vendorName || "New Vendor",
      impactNotice:
        "Saves a new vendor template to the production registry. No past invoices will be re-audited since none exist yet for this vendor.",
      badge: "New Vendor Rule",
      Icon: Sparkles,
      ringColor: "border-purple-500/50",
      badgeCls: "bg-purple-500/10 text-purple-400 border-purple-500/25",
      confirmBtnCls: "bg-purple-600 hover:bg-purple-500 shadow-purple-600/20",
    },
  }[scope];

  const { Icon } = scopeConfig;

  return (
    /* Overlay backdrop */
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/75 backdrop-blur-md">
      {/* Modal Card */}
      <div
        className={`w-full max-w-lg bg-[#070D1A]/95 border ${scopeConfig.ringColor} rounded-2xl shadow-2xl shadow-black/50 overflow-hidden flex flex-col`}
      >
        {/* ── Modal Header ───────────────────────────────────────────── */}
        <div className="px-6 py-4 bg-[#0B1120]/90 border-b border-[#1E2D45] flex items-center justify-between">
          <div className="flex items-center gap-3">
            {/* Scope icon badge */}
            <div className={`p-2 rounded-xl border ${scopeConfig.badgeCls} shadow-md`}>
              <Icon className="w-5 h-5" />
            </div>
            <div>
              <h3 className="text-sm font-semibold text-white leading-tight">{scopeConfig.title}</h3>
              <span className="text-[11px] text-slate-400 font-mono">{scopeConfig.subtitle}</span>
            </div>
          </div>

          {/* Close X button */}
          <button
            onClick={onClose}
            disabled={isSubmitting}
            className="p-1.5 rounded-xl text-slate-400 hover:text-white hover:bg-[#111827] transition-colors cursor-pointer"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* ── Modal Body ─────────────────────────────────────────────── */}
        <div className="p-6 space-y-4 text-xs">
          {/* Re-Audit Impact Warning Banner */}
          <div className="p-4 bg-amber-500/8 border border-amber-500/25 rounded-2xl flex items-start gap-3">
            <AlertTriangle className="w-4 h-4 text-amber-400 shrink-0 mt-0.5" />
            <div>
              <span className="font-semibold text-amber-300 block mb-1">
                Background Re-Audit Behavior
              </span>
              <p className="text-slate-400 leading-relaxed">{scopeConfig.impactNotice}</p>
            </div>
          </div>

          {/* Rules to be committed summary list */}
          <div className="space-y-2">
            <span className="text-slate-300 font-semibold block">
              Rules to Commit ({activeRules.length}):
            </span>
            <div className="max-h-40 overflow-y-auto space-y-1.5 p-3 bg-[#050810] border border-[#1E2D45] rounded-xl font-mono text-[11px]">
              {activeRules.length === 0 ? (
                <div className="p-2 text-slate-500 italic text-center">
                  No custom rules added. Default schema template will be saved.
                </div>
              ) : (
                activeRules.map((r, i) => (
                  <div
                    key={i}
                    className="p-2.5 bg-[#0B1120] border border-emerald-500/15 rounded-xl text-emerald-300 flex items-center gap-2"
                  >
                    <CheckCircle2 className="w-3.5 h-3.5 text-emerald-400 shrink-0" />
                    <span className="leading-snug">{r}</span>
                  </div>
                ))
              )}
            </div>
          </div>
        </div>

        {/* ── Modal Footer Actions ───────────────────────────────────── */}
        <div className="px-6 py-4 bg-[#0B1120]/90 border-t border-[#1E2D45] flex items-center justify-end gap-3">
          {/* Cancel */}
          <button
            type="button"
            onClick={onClose}
            disabled={isSubmitting}
            className="px-4 py-2 rounded-xl border border-[#1E2D45] text-slate-300 hover:text-white hover:bg-[#111827] text-xs font-medium transition-colors cursor-pointer"
          >
            Cancel
          </button>

          {/* Confirm Commit (scope-colored) */}
          <button
            type="button"
            onClick={onConfirm}
            disabled={isSubmitting}
            className={`px-5 py-2 rounded-xl text-white text-xs font-semibold shadow-lg transition-all flex items-center gap-2 cursor-pointer disabled:opacity-60 ${scopeConfig.confirmBtnCls}`}
          >
            {isSubmitting ? (
              <>
                {/* Spinner ring */}
                <span className="w-3.5 h-3.5 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                <span>Committing…</span>
              </>
            ) : (
              <>
                <CheckCircle2 className="w-4 h-4" />
                <span>Commit to Registry</span>
                <ArrowRight className="w-3.5 h-3.5" />
              </>
            )}
          </button>
        </div>
      </div>
    </div>
  );
}
