// =============================================================================
// FILE: components/chat/InsightActions.tsx
// FEATURE: FE Feature 21 — the intelligence bubble's action row (spec §8, task
//          21.6 / 21.8), counterpart of BE Feature 30 ruling R4 as corrected by
//          Gap 492.
//
// INFORMATION ONLY. This is the hard rule of the whole feature and it is worth
// stating where the buttons are, not only in the spec: NOTHING here changes an
// invoice. There is no hold, no dispute, no mark-paid, and no pin. The backend
// route these call (`POST /chat/insights/{id}/transition`) does not read or
// write an `Invoice` row at all — it records the USER's own bookkeeping about a
// finding they will act on offline:
//
//   Add a note → status ACTED,     outcome "note"      (+ the note text)
//   Dismiss    → status DISMISSED, outcome "dismissed"
//   Discuss    → a READ (`GET …/discuss`) that seeds the composer and focuses
//                it. It deliberately does not SEND: sending would put words in
//                the user's mouth and bill them for a turn they did not write.
//
// The labels are not hard-coded here — `block.actions` is `BUBBLE_ACTIONS` from
// the backend, handed over as data, so the row cannot drift from what the
// endpoint accepts. An action the FE has no handler for is skipped rather than
// rendered dead.
// =============================================================================

"use client";

import { useState } from "react";
import { Loader2, MessageSquareQuote, StickyNote, ThumbsDown, ThumbsUp, X } from "lucide-react";
import type { InsightAction, InsightFinding } from "@/lib/chatInsights";

export interface InsightActionsProps {
  /** `BUBBLE_ACTIONS`, verbatim from the block. */
  actions: InsightAction[];
  /**
   * The finding the row acts on — the top-ranked one, which is also the finding
   * the verdict line is written from. Shown in the note field's label so it is
   * never ambiguous which finding is being noted or dismissed.
   */
  finding?: InsightFinding;
  /** False while the lifecycle row behind `finding` has not been resolved yet. */
  actionable: boolean;
  /** Records ACTED + the note text. */
  onAddNote: (note: string) => Promise<void> | void;
  /** Records DISMISSED. */
  onDismiss: () => Promise<void> | void;
  /** Seeds the composer. Never sends. */
  onDiscuss: () => Promise<void> | void;
  onVote: (vote: "up" | "down") => Promise<void> | void;
  /** The vote already cast on this bubble, if any. */
  vote?: "up" | "down" | null;
  /** Set once a transition has been recorded — the row locks and says so. */
  outcome?: string | null;
}

const ICONS: Record<string, typeof StickyNote> = {
  note: StickyNote,
  discuss: MessageSquareQuote,
  dismiss: X,
};

/** Past-tense copy for a finding the user has already filed away. */
function outcomeLine(outcome: string): string {
  if (outcome === "note") return "You added a note to this finding.";
  if (outcome === "dismissed") return "You dismissed this finding.";
  return "This finding is closed.";
}

export default function InsightActions({
  actions,
  finding,
  actionable,
  onAddNote,
  onDismiss,
  onDiscuss,
  onVote,
  vote,
  outcome,
}: InsightActionsProps) {
  const [noteOpen, setNoteOpen] = useState(false);
  const [noteText, setNoteText] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const run = async (name: string, fn: () => Promise<void> | void) => {
    if (busy) return;
    setBusy(name);
    setError(null);
    try {
      await fn();
    } catch (err) {
      console.error(`Insight action "${name}" failed:`, err);
      setError("That did not save. Try again.");
    } finally {
      setBusy(null);
    }
  };

  const handle = (action: InsightAction) => {
    if (action.action === "discuss") return run("discuss", () => onDiscuss());
    if (action.action === "note") {
      setError(null);
      setNoteOpen((open) => !open);
      return undefined;
    }
    if (action.action === "dismiss") return run("dismiss", () => onDismiss());
    return undefined;
  };

  // An action with no handler is dropped rather than drawn dead. `discuss` is
  // always available (it needs no lifecycle row); the two writes need one.
  const usable = (actions || []).filter((a) => ["note", "discuss", "dismiss"].includes(a.action));

  if (outcome) {
    return (
      <p data-testid="insight-outcome" className="mt-2 px-1 text-[11px] text-slate-400">
        {outcomeLine(outcome)}
      </p>
    );
  }

  return (
    <div className="mt-2.5 border-t border-slate-700/40 pt-2">
      <div className="flex flex-wrap items-center gap-1.5">
        {usable.map((action) => {
          const Icon = ICONS[action.action] ?? StickyNote;
          const disabled = action.action !== "discuss" && !actionable;
          return (
            <button
              key={action.action}
              type="button"
              data-testid={`insight-action-${action.action}`}
              disabled={disabled || busy !== null}
              onClick={() => handle(action)}
              title={
                disabled
                  ? "This finding is still being recorded — try again in a moment."
                  : action.label
              }
              className="
                inline-flex items-center gap-1.5 rounded-full px-2.5 py-1
                text-[11px] font-medium
                border border-slate-700/60 bg-slate-800/40 text-slate-300
                hover:text-white hover:border-blue-700/60 hover:bg-[#1e2d45]
                disabled:opacity-40 disabled:cursor-not-allowed
                focus:outline-none focus:ring-1 focus:ring-blue-600
                transition-colors duration-150
              "
            >
              {busy === action.action ? (
                <Loader2 className="w-3 h-3 animate-spin" />
              ) : (
                <Icon className="w-3 h-3" />
              )}
              {action.label}
            </button>
          );
        })}

        <span className="grow" />

        {/* Thumbs on the bubble itself. Separate from the answer-level vote in
            MessageBubble (Gap 54): this one says the FINDING was wrong. */}
        <button
          type="button"
          data-testid="insight-thumbs-up"
          onClick={() => run("up", () => onVote("up"))}
          title="This finding is right"
          className={`p-1 rounded transition-colors duration-150 focus:outline-none focus:ring-1 focus:ring-blue-600 ${
            vote === "up" ? "text-emerald-400" : "text-slate-500 hover:text-slate-300"
          }`}
        >
          <ThumbsUp className="w-3.5 h-3.5" />
        </button>
        <button
          type="button"
          data-testid="insight-thumbs-down"
          onClick={() => run("down", () => onVote("down"))}
          title="This finding is wrong"
          className={`p-1 rounded transition-colors duration-150 focus:outline-none focus:ring-1 focus:ring-blue-600 ${
            vote === "down" ? "text-red-400" : "text-slate-500 hover:text-slate-300"
          }`}
        >
          <ThumbsDown className="w-3.5 h-3.5" />
        </button>
      </div>

      {noteOpen && (
        <div className="mt-2 flex flex-col gap-1.5 sm:flex-row sm:items-center">
          <label className="sr-only" htmlFor="insight-note-input">
            {finding ? `Your note about: ${finding.title}` : "Your note about this finding"}
          </label>
          <input
            id="insight-note-input"
            data-testid="insight-note-input"
            value={noteText}
            onChange={(event) => setNoteText(event.target.value)}
            placeholder="What did you do about it?"
            className="
              grow min-w-0 rounded-md border border-slate-700/60 bg-slate-900/60
              px-2 py-1 text-[11px] text-slate-200 placeholder:text-slate-500
              focus:outline-none focus:ring-1 focus:ring-blue-600
            "
          />
          <button
            type="button"
            data-testid="insight-note-save"
            disabled={!noteText.trim() || !actionable || busy !== null}
            onClick={() =>
              run("note", async () => {
                await onAddNote(noteText.trim());
                setNoteOpen(false);
                setNoteText("");
              })
            }
            className="
              shrink-0 rounded-md border border-blue-700/60 bg-blue-950/40 px-2.5 py-1
              text-[11px] font-medium text-blue-200 hover:bg-blue-900/40
              disabled:opacity-40 disabled:cursor-not-allowed
              focus:outline-none focus:ring-1 focus:ring-blue-600
            "
          >
            Save note
          </button>
        </div>
      )}

      {error && (
        <p data-testid="insight-action-error" className="mt-1.5 px-1 text-[11px] text-red-300">
          {error}
        </p>
      )}
    </div>
  );
}
