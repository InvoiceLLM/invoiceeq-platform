// =============================================================================
// FILE: components/today/ConventionLine.tsx
// FEATURE: FE Feature 22 Task 22.18 — ConventionLine for Decide section, counterpart
//          of BE Feature 33 (apps/invoice-be/routers/today.py::accept_convention_route,
//          edit_convention_route, reject_convention_route).
//
// WHY THIS FILE EXISTS: renders a proposal entry on Today. The user can Accept,
// Edit, or Reject on the spot. No navigation to Ask or Trainer occurs (spec §1:
// "a convention is settled where it is surfaced").
//
// SHAPES VERIFIED AGAINST THE LIVE BACKEND, NOT THE SPEC.
// =============================================================================

"use client";

import React, { useState } from "react";
import { Check, CheckCircle2, Loader2, Pencil, Sparkles, X } from "lucide-react";
import {
  acceptConvention,
  editConvention,
  rejectConvention,
  todayErrorOf,
  type TodayLineModel,
} from "@/lib/today";

export default function ConventionLine({ line }: { line: TodayLineModel }) {
  const proposal = line.proposal;
  const proposalId = proposal?.id ?? line.key.replace(/^proposal-/, "");
  const defaultRule = proposal?.suggested_rule ?? line.detail ?? line.text;

  const [mode, setMode] = useState<"idle" | "editing" | "accepted" | "rejected">("idle");
  const [activeRule, setActiveRule] = useState<string>(defaultRule);
  const [ruleDraft, setRuleDraft] = useState<string>(defaultRule);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (mode === "rejected") {
    return null;
  }

  const handleAccept = async () => {
    setLoading(true);
    setError(null);
    try {
      await acceptConvention(proposalId);
      setMode("accepted");
    } catch (err) {
      setError(todayErrorOf(err)?.detail ?? "Could not accept convention.");
    } finally {
      setLoading(false);
    }
  };

  const handleEditSubmit = async (e?: React.FormEvent) => {
    if (e) e.preventDefault();
    if (!ruleDraft.trim()) return;
    setLoading(true);
    setError(null);
    try {
      await editConvention(proposalId, ruleDraft.trim(), "tenant_chat_rule");
      setActiveRule(ruleDraft.trim());
      setMode("accepted");
    } catch (err) {
      setError(todayErrorOf(err)?.detail ?? "Could not save edited convention.");
    } finally {
      setLoading(false);
    }
  };

  const handleReject = async () => {
    setLoading(true);
    setError(null);
    try {
      await rejectConvention(proposalId);
      setMode("rejected");
    } catch (err) {
      setError(todayErrorOf(err)?.detail ?? "Could not reject convention.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <li data-testid="today-line-proposal" className="flex flex-col gap-3 px-5 py-4 transition-colors hover:bg-[#1E293B]/20">
      <div className="flex items-start gap-3">
        <Sparkles className="mt-0.5 h-4 w-4 shrink-0 text-amber-400" aria-hidden="true" />
        <div className="flex min-w-0 flex-1 flex-col gap-1">
          <p className="text-sm font-medium text-slate-100">{line.text}</p>
          {line.detail && <p className="text-xs text-slate-400">{line.detail}</p>}
        </div>
      </div>

      {mode === "accepted" ? (
        <div
          data-testid="convention-accepted-banner"
          className="ml-7 flex items-center gap-2 rounded-lg border border-emerald-500/30 bg-emerald-500/10 px-3.5 py-2 text-xs text-emerald-300"
        >
          <CheckCircle2 className="h-4 w-4 shrink-0 text-emerald-400" aria-hidden="true" />
          <span>
            <strong className="font-semibold">Convention rule active:</strong> {activeRule}
          </span>
        </div>
      ) : mode === "editing" ? (
        <form onSubmit={handleEditSubmit} className="ml-7 flex flex-col gap-2">
          <label htmlFor={`edit-rule-${proposalId}`} className="text-xs font-medium text-slate-300">
            Edit convention rule:
          </label>
          <textarea
            id={`edit-rule-${proposalId}`}
            data-testid="convention-rule-input"
            value={ruleDraft}
            onChange={(e) => setRuleDraft(e.target.value)}
            disabled={loading}
            rows={2}
            className="w-full rounded-lg border border-[#334155] bg-[#0B0F19] p-2.5 text-xs text-slate-200 placeholder-slate-500 focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500 disabled:opacity-60"
          />
          {error && (
            <p role="alert" className="text-xs text-rose-300">
              {error}
            </p>
          )}
          <div className="flex items-center gap-2">
            <button
              type="submit"
              data-testid="convention-save-btn"
              disabled={loading || !ruleDraft.trim()}
              className="inline-flex items-center gap-1.5 rounded-md bg-blue-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-blue-500 disabled:opacity-50"
            >
              {loading ? <Loader2 className="h-3 w-3 animate-spin" aria-hidden="true" /> : <Check className="h-3 w-3" aria-hidden="true" />}
              Save &amp; Activate
            </button>
            <button
              type="button"
              data-testid="convention-cancel-btn"
              onClick={() => {
                setRuleDraft(activeRule);
                setError(null);
                setMode("idle");
              }}
              disabled={loading}
              className="inline-flex items-center gap-1.5 rounded-md border border-[#334155] px-3 py-1.5 text-xs font-medium text-slate-300 hover:bg-slate-800 disabled:opacity-50"
            >
              Cancel
            </button>
          </div>
        </form>
      ) : (
        <div className="ml-7 flex flex-col gap-2.5">
          <div
            data-testid="convention-suggested-rule"
            className="rounded-lg border border-[#334155]/60 bg-[#0B0F19]/80 px-3 py-2 text-xs font-mono text-slate-300"
          >
            <span className="font-sans font-semibold text-slate-400">Suggested rule: </span>
            {defaultRule}
          </div>

          {error && (
            <p role="alert" className="text-xs text-rose-300">
              {error}
            </p>
          )}

          <div className="flex items-center gap-2">
            <button
              type="button"
              data-testid="convention-accept-btn"
              onClick={handleAccept}
              disabled={loading}
              className="inline-flex items-center gap-1.5 rounded-md bg-emerald-600/90 px-3 py-1 text-xs font-medium text-white hover:bg-emerald-500 disabled:opacity-50"
            >
              {loading ? <Loader2 className="h-3 w-3 animate-spin" aria-hidden="true" /> : <Check className="h-3 w-3" aria-hidden="true" />}
              Accept
            </button>
            <button
              type="button"
              data-testid="convention-edit-btn"
              onClick={() => setMode("editing")}
              disabled={loading}
              className="inline-flex items-center gap-1.5 rounded-md border border-[#334155] px-3 py-1 text-xs font-medium text-slate-300 hover:bg-slate-800 disabled:opacity-50"
            >
              <Pencil className="h-3 w-3" aria-hidden="true" />
              Edit
            </button>
            <button
              type="button"
              data-testid="convention-reject-btn"
              onClick={handleReject}
              disabled={loading}
              className="inline-flex items-center gap-1.5 rounded-md border border-rose-500/30 bg-rose-500/10 px-3 py-1 text-xs font-medium text-rose-300 hover:bg-rose-500/20 disabled:opacity-50"
            >
              {loading ? <Loader2 className="h-3 w-3 animate-spin" aria-hidden="true" /> : <X className="h-3 w-3" aria-hidden="true" />}
              Reject
            </button>
          </div>
        </div>
      )}
    </li>
  );
}
