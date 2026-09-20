// =============================================================================
// FILE: components/atlas/BriefingQuestion.tsx
// FEATURE: FE Feature 24 task 24.5 (spec §2, §3 step 5) — the one thing the
//          briefing may ask, and the answer becoming something ATLAS remembers.
//
// **THIS IS NOT A CHAT INPUT (spec §1).** One field, one send, and it exists
// only because ATLAS asked a specific question with a record under it. There is
// no free-text box in the panel and there must never be one: chat lives at
// `/chat`, reached from a line's Verify affordance, and a second conversational
// surface on the work screen would be the third surface §1 rules out.
//
// **THE ANSWER IS STORED IN THE USER'S OWN WORDS.** This component sends what
// was typed, with the question that prompted it, and prints the rule the backend
// returned — it does not compose the rule text, because an answer ATLAS
// paraphrased is a belief ATLAS authored (BE 35 §7.2's argument for
// `report_missed()`).
//
// AFTER A SUCCESSFUL ANSWER THE PANEL DOES NOT REFRESH (D38). The answer made
// today's briefing a briefing written without it, which is exactly what the
// note says; re-fetching here would spend a model run the user did not ask for.
// =============================================================================

"use client";

import { useState } from "react";

import BriefingParagraphView from "@/components/atlas/BriefingParagraph";
import { answerBriefingQuestion, type BriefingQuestion } from "@/lib/atlasBriefing";
import type { AtlasMemoryRule } from "@/lib/atlas";

/** Said once, here and in `Briefing`, so the two cannot drift apart. */
export const REFRESH_NOTE = "Briefing will refresh on your next visit.";

export interface BriefingQuestionProps {
  question: BriefingQuestion;
  /** FE Gap 706: the same citation-label map the paragraphs use. */
  lineLabels?: ReadonlyMap<string, string>;
  /** Told after the rule is stored, so the panel can show its own refresh note. */
  onSubmit?: (rule: AtlasMemoryRule) => void;
}

export default function BriefingQuestionView({ question, lineLabels, onSubmit }: BriefingQuestionProps) {
  const [answer, setAnswer] = useState("");
  const [sending, setSending] = useState(false);
  const [stored, setStored] = useState<AtlasMemoryRule | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function send(event: React.FormEvent) {
    event.preventDefault();
    const text = answer.trim();
    if (!text || sending) return;
    setSending(true);
    setError(null);
    try {
      const rule = await answerBriefingQuestion(question.text, text);
      setStored(rule);
      onSubmit?.(rule);
    } catch (err: any) {
      // Said out loud, like every other write on this screen: an answer that
      // silently failed would leave the user believing ATLAS learned something
      // it never heard.
      setError(
        err?.response?.data?.detail ??
          "That answer was not saved, so ATLAS has not learned it."
      );
    } finally {
      setSending(false);
    }
  }

  return (
    <div
      data-testid="briefing-question"
      className="rounded border border-slate-700/60 bg-slate-900/40 px-3 py-2"
    >
      {/* The question carries citations exactly as a paragraph does and was
          validated by the same guard, so it renders through the same component
          rather than through a second copy of the citation rendering. */}
      <BriefingParagraphView
        paragraph={{ text: question.text, citations: question.citations ?? [] }}
        lineLabels={lineLabels}
        testId="briefing-question-text"
      />

      {stored ? (
        <div className="mt-2 space-y-1">
          <p data-testid="briefing-question-stored" className="text-[12px] text-emerald-300">
            {stored.text}
          </p>
          <p data-testid="briefing-question-refresh" className="text-[11px] text-slate-500">
            {REFRESH_NOTE}
          </p>
        </div>
      ) : (
        <form onSubmit={send} className="mt-2 flex items-center gap-2">
          <input
            type="text"
            data-testid="briefing-question-answer"
            value={answer}
            onChange={(e) => setAnswer(e.target.value)}
            placeholder="Your answer"
            maxLength={2000}
            className="flex-1 rounded border border-slate-700 bg-slate-950/60 px-2 py-1 text-[12px] text-slate-100 placeholder:text-slate-600"
          />
          <button
            type="submit"
            data-testid="briefing-question-submit"
            disabled={sending || answer.trim().length === 0}
            className="rounded border border-slate-700 px-2 py-0.5 text-[11px] text-slate-300 hover:bg-slate-800 disabled:opacity-50"
          >
            {sending ? "Saving…" : "Answer"}
          </button>
        </form>
      )}

      {error && (
        <p data-testid="briefing-question-error" className="mt-1 text-[11px] text-amber-300">
          {error}
        </p>
      )}
    </div>
  );
}
