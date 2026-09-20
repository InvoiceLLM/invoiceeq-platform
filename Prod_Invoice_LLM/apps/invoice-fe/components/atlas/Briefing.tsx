// =============================================================================
// FILE: components/atlas/Briefing.tsx
// FEATURE: FE Feature 24 task 24.3 (spec §1, §3) — the panel at the top of the
//          work screen: what ATLAS Intelligence says on open.
//
// **THE LINES COME FIRST, ALWAYS (spec §3 step 1).** This component is mounted
// by `WorkScreen` only once `/atlas/lines` has answered, so the deterministic
// work is on screen before a single model token is asked for. It opens its own
// stream on mount and owns nothing else on the page.
//
// **A WITHHELD PARAGRAPH IS A NUMBER ON THE SCREEN, NEVER A SILENCE (spec §1).**
// `validateCitations()` decides, in `lib/atlasBriefing.ts`, and every rejection
// is counted and printed — the same promise `doubt_checks_skipped` already
// makes on this screen. A panel that quietly dropped a paragraph would look
// exactly like a briefing that had less to say.
//
// **NOTHING RE-FETCHES (D38, spec §1).** One stream per mount. After a dismiss,
// an act or an answer the panel shows "briefing will refresh on your next
// visit" and keeps the text it has: the backend has already marked the stored
// briefing stale, so the next open is where the new one is written. Re-opening
// the stream here would spend a model run the user did not ask for, on a screen
// they are still reading.
//
// THE STREAM IS CLOSED ON `done`. An `EventSource` reconnects by itself when the
// server closes the connection, so a briefing that ended would otherwise be
// re-requested every few seconds — the same never-poll rule as the rest of the
// screen, enforced rather than trusted.
//
// NO ARITHMETIC (FE 23 §2). The only number this file produces is the count of
// paragraphs it withheld.
// =============================================================================

"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import BriefingParagraphView from "@/components/atlas/BriefingParagraph";
import BriefingQuestionView, { REFRESH_NOTE } from "@/components/atlas/BriefingQuestion";
import {
  BRIEFING_STREAM_PATH,
  citedIds,
  parseBriefingEvent,
  validateCitations,
  type BriefingDone,
  type BriefingEvent,
  type BriefingParagraph,
  type BriefingQuestion,
  type BriefingWelcome,
} from "@/lib/atlasBriefing";
import type { AtlasMemoryRule } from "@/lib/atlas";

const BRIEFING_TITLE = "Briefing";

/** §3 step 6's sentence. The reason word is the backend's and is printed as sent. */
function truncatedSentence(reason: string): string {
  return `ATLAS stopped early (${reason}).`; // hardcode-ok: the backend's own reason word, printed as sent
}

/** §3 step 4's count, said out loud. */
function withheldSentence(count: number): string {
  // No arithmetic: `count` is a list length, not a figure about money.
  return `${count} ${count === 1 ? "paragraph" : "paragraphs"} withheld`; // hardcode-ok: a count of rejected paragraphs, not a money figure
}

export interface BriefingProps {
  /**
   * The ids this screen can actually show the reader — `Recommendation.id` and
   * `what.entity_id` from the `/atlas/lines` payload. A paragraph citing
   * anything else is withheld unless the briefing itself already cited it and
   * was accepted (spec §3 step 4).
   */
  knownIds: ReadonlySet<string>;
  /**
   * FE Gap 706: recommendation id → the invoice number in that line's headline,
   * built by `WorkScreen` from the same payload `knownIds` comes from. A
   * citation is rendered as that word; its id stays in `title`/`aria-label`.
   */
  lineLabels?: ReadonlyMap<string, string>;
  /**
   * Set by `WorkScreen`'s dismiss/act handlers once they succeed. The panel then
   * shows the refresh note; it never acts on it.
   */
  needsRefresh?: boolean;
  /** Told when the briefing's question has been answered and stored. */
  onAnswered?: (rule: AtlasMemoryRule) => void;
}

export default function Briefing({
  knownIds,
  lineLabels,
  needsRefresh = false,
  onAnswered,
}: BriefingProps) {
  const [welcome, setWelcome] = useState<BriefingWelcome | null>(null);
  const [paragraphs, setParagraphs] = useState<BriefingParagraph[]>([]);
  const [question, setQuestion] = useState<BriefingQuestion | null>(null);
  /**
   * Why each withheld paragraph was withheld. A LIST, not a counter: FE 23 §2's
   * no-arithmetic rule is asserted grep-shaped over every file in this folder,
   * so the panel counts by collecting rather than by adding one.
   */
  const [rejected, setRejected] = useState<string[]>([]);
  const [truncated, setTruncated] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState<BriefingDone | null>(null);
  const [answered, setAnswered] = useState(false);

  /**
   * Read at event time rather than closed over: the stream is opened once, and a
   * later `/atlas/lines` re-read (a dismiss, an act, the Refresh button) must
   * not re-open it just because the id set changed.
   */
  const knownIdsRef = useRef(knownIds);
  knownIdsRef.current = knownIds;
  /** Ids the briefing itself has cited and had accepted (spec §3 step 4). */
  const citedSoFar = useRef<Set<string>>(new Set());
  /** A question is rendered at most once; a second frame is counted, not shown. */
  const hasQuestion = useRef(false);
  const finished = useRef(false);

  /** `knownIds` plus what the briefing has already cited (spec §3 step 4). */
  const knownNow = (): Set<string> => {
    const out = new Set<string>();
    knownIdsRef.current.forEach((id) => out.add(id));
    citedSoFar.current.forEach((id) => out.add(id));
    return out;
  };

  const handle = useCallback((event: BriefingEvent) => {
    switch (event.type) {
      case "welcome":
        setWelcome(event.data);
        return;
      case "paragraph": {
        const check = validateCitations(event.data, knownNow());
        if (check.ok) {
          for (const id of citedIds(event.data)) citedSoFar.current.add(id);
          setParagraphs((prev) => [...prev, event.data]);
        } else {
          setRejected((prev) => [...prev, check.reason]);
        }
        return;
      }
      case "question": {
        const known = knownNow();
        // The same evidence rule as a paragraph, and the same one-question rule
        // the backend applies (§3.1 step 6): a second question is a defect, so
        // it is counted where the user can see it rather than dropped.
        if (hasQuestion.current || !validateCitations(event.data, known).ok) {
          setRejected((prev) => [...prev, hasQuestion.current ? "second_question" : "uncited"]);
          return;
        }
        hasQuestion.current = true;
        setQuestion(event.data);
        return;
      }
      case "truncated":
        setTruncated(event.data.reason);
        return;
      case "error":
        setError(event.data.message);
        return;
      case "done":
        setDone(event.data);
        return;
    }
  }, []);

  useEffect(() => {
    // Deliberately empty deps: one stream per mount, and no prop change reopens
    // it (D38). `WorkScreen` remounts this component on the next visit, which is
    // the only thing that asks for a new briefing.
    if (typeof window === "undefined" || typeof window.EventSource === "undefined") return;
    const source = new window.EventSource(BRIEFING_STREAM_PATH);
    let live = true;

    const listen = (type: string) =>
      source.addEventListener(type, (raw: MessageEvent) => {
        if (!live) return;
        const event = parseBriefingEvent(type, raw.data);
        if (!event) return;
        handle(event);
        if (event.type === "done") {
          finished.current = true;
          source.close();
        }
      });

    for (const type of ["welcome", "paragraph", "question", "truncated", "error", "done"]) {
      listen(type);
    }

    source.onerror = () => {
      if (!live || finished.current) return;
      // A transport failure, said in the panel's own body. The route handler
      // turns an upstream 4xx into a real `error` frame, so reaching here means
      // the connection itself went — which the user must not read as "ATLAS had
      // nothing to say".
      setError("The briefing stopped before it finished. Your lines below are unaffected.");
      finished.current = true;
      source.close();
    };

    return () => {
      live = false;
      source.close();
    };
  }, [handle]);

  const showRefreshNote = needsRefresh || answered;
  const streaming = done === null && error === null;
  const empty =
    welcome === null && paragraphs.length === 0 && question === null && error === null;

  return (
    <section data-testid="briefing" className="rounded border border-slate-800 bg-slate-900/30 p-3">
      <div className="flex items-center gap-2">
        <h2 className="text-[13px] font-medium text-slate-200">{BRIEFING_TITLE}</h2>
        {streaming && (
          <span data-testid="briefing-streaming" className="text-[11px] text-slate-500">
            …
          </span>
        )}
      </div>

      {/* §3 step 6: an error replaces the body. It is never rendered beside
          paragraphs, because "here is what I found, and also I failed" is the
          sentence that gets a half-briefing read as a whole one. */}
      {error ? (
        <p data-testid="briefing-error" className="mt-2 text-[13px] text-amber-300">
          {error}
        </p>
      ) : (
        <div className="mt-2 space-y-3">
          {welcome && (
            <p data-testid="briefing-welcome" className="text-[13px] leading-relaxed text-slate-200">
              {welcome.text}
            </p>
          )}

          {paragraphs.map((paragraph, index) => (
            <BriefingParagraphView
              key={`p${index}`} // hardcode-ok: a React key from the arrival order, never rendered
              paragraph={paragraph}
              lineLabels={lineLabels}
            />
          ))}

          {question && (
            <BriefingQuestionView
              question={question}
              lineLabels={lineLabels}
              onSubmit={(rule) => {
                setAnswered(true);
                onAnswered?.(rule);
              }}
            />
          )}

          {empty && done !== null && (
            <p data-testid="briefing-empty" className="text-[13px] text-slate-400">
              Nothing to brief you on this morning.
            </p>
          )}
        </div>
      )}

      {truncated && (
        <p data-testid="briefing-truncated" className="mt-2 text-[11px] text-slate-400">
          {truncatedSentence(truncated)}
        </p>
      )}

      {rejected.length > 0 && (
        <p data-testid="briefing-withheld" className="mt-2 text-[11px] text-slate-500">
          {withheldSentence(rejected.length)}
        </p>
      )}

      {showRefreshNote && (
        <p data-testid="briefing-refresh-note" className="mt-2 text-[11px] text-slate-500">
          {REFRESH_NOTE}
        </p>
      )}

      {done && (
        <p data-testid="briefing-footer" className="mt-2 text-[11px] text-slate-600">
          {done.cached ? "from cache" : done.model}
        </p>
      )}
    </section>
  );
}
