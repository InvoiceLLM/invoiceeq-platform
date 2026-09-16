// =============================================================================
// FILE: components/today/ActionLine.tsx
// FEATURE: FE Feature 22 Task 22.19 — ActionLine for Today findings, counterpart
//          of BE Feature 33 (apps/invoice-be/routers/today.py::confirm_action_route,
//          dismiss_item).
//
// WHY THIS FILE EXISTS: renders a finding that includes an actionable capability.
// - Role-gated Confirm: only Admin can confirm; other roles do not see the button.
// - 403 on forced confirm: rendered directly on the line, never as a toast/modal.
// - Dismiss: available on every line, removes the line and feeds ATLAS learn().
//
// SHAPES VERIFIED AGAINST THE LIVE BACKEND, NOT THE SPEC.
// =============================================================================

"use client";

import React, { useState } from "react";
import { AlertCircle, Check, Loader2, X, Zap } from "lucide-react";
import { confirmAction, dismissTodayItem, todayErrorOf, type TodayLineModel } from "@/lib/today";
import { useAuth } from "@/hooks/useAuth";

export default function ActionLine({ line }: { line: TodayLineModel }) {
  const { role } = useAuth();
  const itemId = line.itemId ?? line.key.replace(/^(finding|summary|item|action)-/, "");

  const [dismissed, setDismissed] = useState(false);
  const [confirmed, setConfirmed] = useState(false);
  const [loadingAction, setLoadingAction] = useState<"confirm" | "dismiss" | null>(null);
  const [error, setError] = useState<string | null>(null);

  // Allowed role is Admin per BE capabilities.py
  const canConfirm = role === "Admin";
  const actionLabel = line.meta?.action_label || "Confirm";

  if (dismissed || confirmed) {
    return null;
  }

  const handleConfirm = async () => {
    setLoadingAction("confirm");
    setError(null);
    try {
      await confirmAction(itemId);
      setConfirmed(true);
    } catch (err) {
      setError(todayErrorOf(err)?.detail ?? "Failed to execute action.");
    } finally {
      setLoadingAction(null);
    }
  };

  const handleDismiss = async () => {
    setLoadingAction("dismiss");
    setError(null);
    try {
      await dismissTodayItem(itemId);
      setDismissed(true);
    } catch (err) {
      setError(todayErrorOf(err)?.detail ?? "Failed to dismiss line.");
    } finally {
      setLoadingAction(null);
    }
  };

  return (
    <li
      data-testid="today-line-action"
      className="flex flex-col gap-3 px-5 py-4 transition-colors hover:bg-[#1E293B]/20"
    >
      <div className="flex items-start gap-3">
        <Zap className="mt-0.5 h-4 w-4 shrink-0 text-amber-400" aria-hidden="true" />
        <div className="flex min-w-0 flex-1 flex-col gap-1">
          <p className="text-sm font-medium text-slate-100">{line.text}</p>
          {line.detail && <p className="text-xs text-slate-400">{line.detail}</p>}
        </div>
      </div>

      {error && (
        <div
          role="alert"
          data-testid="action-line-error"
          className="ml-7 flex items-center gap-2 rounded-lg border border-rose-500/30 bg-rose-500/10 px-3 py-2 text-xs text-rose-300"
        >
          <AlertCircle className="h-4 w-4 shrink-0 text-rose-400" aria-hidden="true" />
          <span>{error}</span>
        </div>
      )}

      <div className="ml-7 flex items-center gap-2">
        {canConfirm && (
          <button
            type="button"
            data-testid="action-confirm-btn"
            onClick={handleConfirm}
            disabled={loadingAction !== null}
            className="inline-flex items-center gap-1.5 rounded-md bg-blue-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-blue-500 disabled:opacity-50"
          >
            {loadingAction === "confirm" ? (
              <Loader2 className="h-3 w-3 animate-spin" aria-hidden="true" />
            ) : (
              <Check className="h-3 w-3" aria-hidden="true" />
            )}
            {actionLabel}
          </button>
        )}

        <button
          type="button"
          data-testid="action-dismiss-btn"
          onClick={handleDismiss}
          disabled={loadingAction !== null}
          className="inline-flex items-center gap-1.5 rounded-md border border-[#334155] px-3 py-1.5 text-xs font-medium text-slate-300 hover:bg-slate-800 disabled:opacity-50"
        >
          {loadingAction === "dismiss" ? (
            <Loader2 className="h-3 w-3 animate-spin" aria-hidden="true" />
          ) : (
            <X className="h-3 w-3" aria-hidden="true" />
          )}
          Dismiss
        </button>
      </div>
    </li>
  );
}
