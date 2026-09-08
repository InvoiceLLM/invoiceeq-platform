// =============================================================================
// FILE: components/chat/InsightCorrectionDialog.tsx
// FEATURE: FE Feature 21 task 21.4 — what was wrong with a finding.
//
// Opened by the bubble's thumbs-DOWN only. It is deliberately smaller than
// `ThumbsDownTriage` (Feature 14/18), which triages a whole ANSWER and can route
// to a rule or a style change: a finding is one deterministic card's output, so
// the only useful question is which part of it is wrong and what the truth is.
// That goes to `POST /chat/messages/{id}/insight-feedback`, whose backend
// counterpart feeds Feature 30's flywheel (30.13) — a certified example or a
// rule-card review flag, never an edit to an invoice.
//
// The vote is written by THIS dialog rather than before it opens, matching the
// contract of `InsightFeedbackIn` (`vote` + `reason` + `corrected_text` in one
// call). Closing without submitting therefore records nothing, which is the
// honest reading of "the user changed their mind".
// =============================================================================

"use client";

import { useState } from "react";
import { Loader2, X } from "lucide-react";
import { postInsightFeedback, type InsightFinding } from "@/lib/chatInsights";

const REASONS: Array<{ value: string; label: string }> = [
  { value: "wrong_amount", label: "The amount is wrong" },
  { value: "wrong_document", label: "It compared the wrong document" },
  { value: "not_a_problem", label: "This is not a problem" },
  { value: "other", label: "Something else" },
];

export interface InsightCorrectionDialogProps {
  messageId: string;
  finding?: InsightFinding;
  insightId?: string;
  onClose: () => void;
}

export default function InsightCorrectionDialog({
  messageId,
  finding,
  insightId,
  onClose,
}: InsightCorrectionDialogProps) {
  const [reason, setReason] = useState<string>(REASONS[0].value);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async () => {
    if (busy) return;
    setBusy(true);
    setError(null);
    try {
      await postInsightFeedback(messageId, {
        vote: "down",
        reason,
        card: finding?.card,
        finding_key: finding?.finding_key,
        ...(insightId ? { insight_id: insightId } : {}),
        ...(text.trim() ? { corrected_text: text.trim() } : {}),
      });
      onClose();
    } catch (err) {
      console.error("Could not send the correction:", err);
      setError("That did not send. Try again.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div
      data-testid="insight-correction-dialog"
      role="dialog"
      aria-label="What is wrong with this finding?"
      className="mt-2 rounded-lg border border-slate-700/60 bg-slate-900/80 p-2.5"
    >
      <div className="flex items-start justify-between gap-2">
        <p className="text-[11px] font-medium text-slate-200">
          What is wrong with this finding?
        </p>
        <button
          type="button"
          data-testid="insight-correction-close"
          onClick={onClose}
          aria-label="Close"
          className="text-slate-500 hover:text-slate-300 focus:outline-none focus:ring-1 focus:ring-blue-600"
        >
          <X className="h-3.5 w-3.5" />
        </button>
      </div>

      <div className="mt-1.5 flex flex-wrap gap-1.5">
        {REASONS.map((option) => (
          <button
            key={option.value}
            type="button"
            data-testid={`insight-correction-reason-${option.value}`}
            aria-pressed={reason === option.value}
            onClick={() => setReason(option.value)}
            className={`rounded-full border px-2 py-0.5 text-[10px] transition-colors duration-150 focus:outline-none focus:ring-1 focus:ring-blue-600 ${
              reason === option.value
                ? "border-blue-700/60 bg-blue-950/40 text-blue-200"
                : "border-slate-700/60 bg-slate-800/40 text-slate-400 hover:text-slate-200"
            }`}
          >
            {option.label}
          </button>
        ))}
      </div>

      <textarea
        data-testid="insight-correction-text"
        value={text}
        onChange={(event) => setText(event.target.value)}
        rows={2}
        placeholder="What should it have said? (optional)"
        className="
          mt-1.5 w-full resize-none rounded-md border border-slate-700/60 bg-slate-900/60
          px-2 py-1 text-[11px] text-slate-200 placeholder:text-slate-500
          focus:outline-none focus:ring-1 focus:ring-blue-600
        "
      />

      <div className="mt-1.5 flex items-center justify-end gap-2">
        {error && (
          <span data-testid="insight-correction-error" className="mr-auto text-[11px] text-red-300">
            {error}
          </span>
        )}
        <button
          type="button"
          data-testid="insight-correction-submit"
          disabled={busy}
          onClick={submit}
          className="
            inline-flex items-center gap-1.5 rounded-md border border-blue-700/60
            bg-blue-950/40 px-2.5 py-1 text-[11px] font-medium text-blue-200
            hover:bg-blue-900/40 disabled:opacity-40
            focus:outline-none focus:ring-1 focus:ring-blue-600
          "
        >
          {busy && <Loader2 className="h-3 w-3 animate-spin" />}
          Send
        </button>
      </div>
    </div>
  );
}
