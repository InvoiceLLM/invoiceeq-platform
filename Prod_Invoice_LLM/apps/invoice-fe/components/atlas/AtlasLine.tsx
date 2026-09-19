// =============================================================================
// FILE: components/atlas/AtlasLine.tsx
// FEATURE: FE Feature 23 task 2 (spec §2) — the line: what, why, action, verify.
//
// ONE RULE ABOVE ALL OTHERS: THIS FILE DOES NO ARITHMETIC, EVER (spec §2).
// Every figure is printed exactly as the server sent it. There is no numeric
// operator anywhere in this file, no `Math.`, no `toFixed`, no `Number(`, no
// `reduce` — asserted grep-shaped by
// `tests/unit/atlas-no-client-arithmetic.test.ts`, because the moment a client
// can compute a total it will eventually compute a wrong one, and BE §5.2 says
// trust in numbers is binary and does not come back.
//
// EVERYTHING ON THIS LINE CAME OVER THE WIRE. `what.headline` is printed as
// sent and never recomposed; `why.text` is printed verbatim; the figures are
// `Figure.rendered` strings, shown beside the working the backend declared for
// them (D40: "4x their usual …, across 14 invoices" is the line showing its
// own basis). Uncertainty renders as the server's words, never as a number or
// a percentage bar (BE §5.1).
//
// A LINE MISSING A PART IS A DEFECT, NOT A LAYOUT CASE (spec §2). `lineDefect()`
// decides; a failing line renders as a named defect rather than a tidy card
// with a hole in it, so a backend regression is visible on the screen it broke.
//
// NO BATCH CONTROL EXISTS HERE — no checkbox, no multi-select, and no way to
// accept several lines on one click. D42 ruled nothing batchable in v1.
// `Recommendation.batchable` is still on the wire and is deliberately not
// rendered.
// =============================================================================

"use client";

import Link from "next/link";

import MissedThis from "@/components/atlas/MissedThis";
import { AlertTriangle, ArrowRight, Check, HelpCircle, Paperclip } from "lucide-react";

import {
  actionDestination,
  ATTACH_ACTION_KINDS,
  isActionPerformable,
  lineDefect,
  PERFORMABLE_ACTION_KINDS,
  VERIFY_ATTACH_HINT,
  verifyChatHref,
  type AtlasRecommendation,
} from "@/lib/atlas";

/** Why a click cannot be performed, said on the line rather than on a 404. */
const NOT_YET_PERFORMABLE =
  "I can see this and explain it, but I cannot do it for you yet.";

/**
 * What a suggest-only line says instead (D50, BE 34.7e).
 *
 * **Not "not yet".** These two kinds are ruled never to become writes, and the
 * difference matters to the reader: a wrong correction teaches a rule that
 * misfires on every future invoice from that vendor, and a wrong requeue spends
 * pipeline work nobody asked for. So the line takes the user to the place where
 * they decide, and says that is on purpose.
 */
const SUGGESTION_ONLY = "I will take you there — this one is yours to decide.";

const CAPABILITY_LABEL: Record<string, string> = {
  audit: "Decision",
  train: "Correction",
  load: "Document",
  admin: "Position",
};

export interface AtlasLineProps {
  line: AtlasRecommendation;
  /** Supplied only where §6's attach flow is available on the page. */
  onAttach?: (line: AtlasRecommendation) => void;
  /**
   * D49 — mark this line handled. Every line gets the control; the page owns
   * what happens next, which is a re-read, because the dismissal is filtered
   * server-side and this component must not hide a row it was sent.
   */
  onDismiss?: (line: AtlasRecommendation) => void;
  /** True while the dismissal is in flight, so the click cannot be repeated. */
  dismissing?: boolean;
  /**
   * BE 34.7 — perform this line's action. The page owns what happens next,
   * which is a re-read: D38 recomputes every line on open, so whether the line
   * survives its own action is the server's answer, not this component's.
   */
  onAct?: (line: AtlasRecommendation) => void;
  /** True while this line's action is in flight. */
  acting?: boolean;
  /**
   * The kinds the **backend** says it can perform right now (BE 34.7d), read
   * from `GET /atlas/actions/kinds` by the page above.
   *
   * Defaulted to the empty set on purpose: a line rendered before that read
   * lands, or after it failed, shows a disabled button. "I do not know whether
   * I can do this" and "I can do this" must not render the same, and the safe
   * one is the one that does nothing.
   */
  performableKinds?: ReadonlySet<string>;
}

export default function AtlasLine({
  line,
  onAttach,
  onDismiss,
  dismissing = false,
  onAct,
  acting = false,
  performableKinds = PERFORMABLE_ACTION_KINDS,
}: AtlasLineProps) {
  const defect = lineDefect(line);
  if (defect) {
    return (
      <li
        data-testid="atlas-line-defect"
        className="rounded-lg border border-red-800/50 bg-red-950/20 px-4 py-3 text-[13px] text-red-200"
      >
        <span className="font-medium">This line could not be rendered: </span>
        {defect}. Reported, not patched: the line is a backend defect.
      </li>
    );
  }

  const uncertain = line.certainty === "uncertain";
  const attachable = ATTACH_ACTION_KINDS.has(line.action.kind);
  const performable = isActionPerformable(line.action.kind, performableKinds);
  // A destination is only offered for a kind that is NOT performable. A kind
  // that is both would be two affordances for one line, and the user would have
  // to guess which one the label meant.
  const destination = performable ? null : actionDestination(line);

  return (
    <li
      data-testid="atlas-line"
      data-line-id={line.id}
      data-capability={line.capability}
      data-certainty={line.certainty}
      className="rounded-lg border border-slate-700/60 bg-slate-900/40 px-4 py-3"
    >
      <div className="flex items-center gap-2 text-[11px] uppercase tracking-wide text-slate-400">
        <span data-testid="atlas-line-capability">
          {CAPABILITY_LABEL[line.capability] ?? line.capability}
        </span>
        <span className="text-slate-600">·</span>
        <span>{line.skill}</span>
      </div>

      {/* WHAT — one sentence, as sent. */}
      <p
        data-testid="atlas-line-what"
        className="mt-1 text-[14px] font-medium text-slate-100"
      >
        {line.what.headline}
      </p>

      {/* WHY — the server's reason, verbatim. */}
      <p data-testid="atlas-line-why" className="mt-1 text-[13px] text-slate-300">
        {line.why.text}
      </p>

      {/* The working behind each number, as the backend declared it (D40). */}
      {line.why.figures.length > 0 && (
        <ul
          data-testid="atlas-line-figures"
          className="mt-2 flex flex-wrap gap-2 text-[11px] text-slate-400"
        >
          {line.why.figures.map((figure, index) => {
            const key = `${line.id}:figure:${index}`; // hardcode-ok: a React key built from an id and an index; it is never rendered, and the figure itself is printed below as Figure.rendered, which the server formatted
            return (
            <li
              key={key}
              data-testid="atlas-figure"
              title={figure.computation ?? figure.quote ?? undefined}
              className="rounded border border-slate-700/60 px-2 py-0.5"
            >
              <span className="text-slate-200">{figure.rendered}</span>
              <span className="ml-1 text-slate-500">{figure.currency}</span>
            </li>
            );
          })}
        </ul>
      )}

      {/* Uncertainty, in the server's words. Never a number, never a bar. */}
      {uncertain && (
        <p
          data-testid="atlas-line-doubt"
          className="mt-2 flex items-start gap-1.5 text-[12px] text-amber-300"
        >
          <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
          {line.why.doubt}
        </p>
      )}

      {/* The Trainer's before and after (D45), laid out as the typed pair the
          backend sends. Neither half is recomposed here. */}
      {line.correction && (
        <p
          data-testid="atlas-line-correction"
          className="mt-2 flex items-center gap-2 text-[12px] text-slate-300"
        >
          <span className="text-slate-500">{line.correction.field_label}</span>
          <span data-testid="atlas-correction-before" className="text-slate-400">
            {line.correction.before_rendered ?? "not extracted"}
          </span>
          <ArrowRight className="h-3.5 w-3.5 text-slate-500" />
          <span data-testid="atlas-correction-after" className="text-slate-100">
            {line.correction.after_rendered}
          </span>
        </p>
      )}

      {/* THE FORECAST (BE §7.5, D15 · task 34.9) — a date, a number, and the
          levers. Never a chart: §7.5 says so in those words, and there is no
          graph, no sparkline and no trend line anywhere in this block.

          THE ASSUMPTION IS RENDERED UNCONDITIONALLY. It is required on the
          contract and it is the half of the answer that is easy to drop —
          "deterministic and honest are separate properties" (§7.5), and a
          shortfall date shown without what it assumed is the deterministic half
          on its own.

          A LEVER IS NOT A BUTTON. BE §5.3: ATLAS never moves money and never
          sends outside the company unseen. Chasing a customer and deferring a
          payment are both things the person does; printing them as clickable
          would be this screen quietly claiming an authority the whole feature
          is built to refuse. */}
      {line.forecast && (
        <div data-testid="atlas-line-forecast" className="mt-2 rounded border border-amber-800/40 bg-amber-950/10 px-3 py-2">
          <p className="text-[12px] text-amber-200">
            <span data-testid="atlas-forecast-date">{line.forecast.on_date}</span>
            {" · "}
            <span data-testid="atlas-forecast-shortfall">
              {line.forecast.shortfall_rendered}
            </span>{" "}
            {line.currency}
          </p>
          <p data-testid="atlas-forecast-assumption" className="mt-1 text-[11px] text-slate-400">
            {line.forecast.assumption}
          </p>
          {line.forecast.levers.length > 0 && (
            <ul data-testid="atlas-forecast-levers" className="mt-2 space-y-1">
              {line.forecast.levers.map((lever, index) => (
                <li
                  key={`${line.id}:lever:${index}`} // hardcode-ok: a React key from an id and an index; never rendered, and the amount beside it is the server's own string
                  data-testid="atlas-forecast-lever"
                  data-lever-kind={lever.kind}
                  className="flex items-center gap-2 text-[12px] text-slate-300"
                >
                  <span className="text-slate-500">·</span>
                  <span>{lever.label}</span>
                  <span className="text-slate-200">{lever.amount_rendered}</span>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}

      {line.why.references.length > 0 && (
        <p data-testid="atlas-line-references" className="mt-2 text-[11px] text-slate-500">
          {line.why.references.join(", ")}
        </p>
      )}

      <div className="mt-3 flex flex-wrap items-center gap-2">
        {/* ACTION — one click, one kind. No batch control, by ruling (D42). */}
        {attachable && onAttach ? (
          <button
            type="button"
            data-testid="atlas-line-attach"
            data-action-kind={line.action.kind}
            onClick={() => onAttach(line)}
            className="inline-flex items-center gap-1.5 rounded border border-blue-700/60 bg-blue-950/30 px-2.5 py-1 text-[12px] text-blue-200 hover:bg-blue-950/60"
          >
            <Paperclip className="h-3.5 w-3.5" />
            {line.action.label}
          </button>
        ) : destination ? (
          /* SUGGEST ONLY (D50) — resolves to a destination and opens it. It is
             a link, not a button that posts: the backend refuses this kind as a
             write (409), and rendering it as something clickable that then fails
             would teach the user the product is broken rather than that the
             decision is theirs. */
          <Link
            href={destination}
            data-testid="atlas-line-destination"
            data-action-kind={line.action.kind}
            data-performable="no"
            title={SUGGESTION_ONLY}
            className="inline-flex items-center gap-1.5 rounded border border-slate-700 px-2.5 py-1 text-[12px] text-slate-200 hover:bg-slate-800"
          >
            {line.action.label}
            <ArrowRight className="h-3.5 w-3.5" />
          </Link>
        ) : (
          <button
            type="button"
            data-testid="atlas-line-action"
            data-action-kind={line.action.kind}
            data-performable={performable ? "yes" : "no"}
            disabled={!performable || acting || !onAct}
            onClick={performable && onAct ? () => onAct(line) : undefined}
            title={performable ? line.action.label : NOT_YET_PERFORMABLE}
            className="inline-flex items-center gap-1.5 rounded border border-slate-700 px-2.5 py-1 text-[12px] text-slate-200 hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {acting ? "Working…" : line.action.label}
          </button>
        )}

        {/* DISMISS — D49. On EVERY line, whatever its capability, certainty or
            action, because the reason a line needs to go away ("I did this in
            chat already") is independent of all three.

            NOT A SNOOZE and not an undo of the underlying problem: it records
            that this person has handled it, nothing more. The backend keys it
            on the deterministic recommendation id, so the same line stays gone
            across D38's recompute-on-open.

            It does not hide the row itself — the page re-reads and the server
            omits it. See `dismissAtlasLine()` in `lib/atlas.ts`. */}
        {onDismiss && (
          <button
            type="button"
            data-testid="atlas-line-dismiss"
            disabled={dismissing}
            onClick={() => onDismiss(line)}
            title="I have handled this. Do not show it to me again."
            className="inline-flex items-center gap-1.5 rounded border border-slate-700 px-2.5 py-1 text-[12px] text-slate-400 hover:bg-slate-800 hover:text-slate-200 disabled:cursor-not-allowed disabled:opacity-50"
          >
            <Check className="h-3.5 w-3.5" />
            {dismissing ? "Dismissing…" : "Dismiss"}
          </button>
        )}

        {/* VERIFY — chat, on this line, with the question already written.
            D47: the question is the whole affordance. It opens chat seeded; it
            does not attach anything, and the hint below says so when the line
            names a document. */}
        <Link
          href={verifyChatHref(line)}
          data-testid="atlas-line-verify"
          className="inline-flex items-center gap-1.5 text-[12px] text-slate-400 hover:text-slate-200"
        >
          <HelpCircle className="h-3.5 w-3.5" />
          {line.verify.question}
        </Link>
      </div>

      {/* D47 — FE Gap 640 closed by dropping the promise. This app never
          attaches a document to a chat session, so the line says who does.
          Shown only where a document is actually named: a cash-position line
          has nothing to attach and would read as a nag. */}
      {line.verify.document_id && (
        <p
          data-testid="atlas-line-verify-hint"
          className="mt-1 text-[11px] text-slate-500"
        >
          {VERIFY_ATTACH_HINT}
        </p>
      )}

      {/* Said on the line, in the right one of two sentences. "I cannot do this
          for you yet" is a state that will change when an endpoint lands; "this
          one is yours to decide" is a ruling (D50) that will not. Printing the
          first where the second is true would promise a feature nobody intends
          to build. */}
      {/* "YOU MISSED THIS" (BE task 34.14, D34) — on every line, because the
          thing ATLAS failed to notice is usually noticed while looking at
          something adjacent to it. It reports against this line's own entity, so
          the lesson that comes out of it names a real record. */}
      <MissedThis entityKind={line.what.entity_kind} entityId={line.what.entity_id} />

      {!performable && !attachable && (
        <p data-testid="atlas-line-not-performable" className="mt-1 text-[11px] text-slate-500">
          {destination ? SUGGESTION_ONLY : NOT_YET_PERFORMABLE}
        </p>
      )}
    </li>
  );
}
