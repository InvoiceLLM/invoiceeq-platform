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
import { AlertTriangle, ArrowRight, Check, HelpCircle, Paperclip } from "lucide-react";

import {
  ATTACH_ACTION_KINDS,
  isActionPerformable,
  lineDefect,
  VERIFY_ATTACH_HINT,
  verifyChatHref,
  type AtlasRecommendation,
} from "@/lib/atlas";

/** Why a click cannot be performed yet, said on the line rather than on a 404. */
const NOT_YET_PERFORMABLE =
  "I can see this and explain it, but I cannot do it for you yet.";

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
}

export default function AtlasLine({
  line,
  onAttach,
  onDismiss,
  dismissing = false,
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
  const performable = isActionPerformable(line.action.kind);

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
        ) : (
          <button
            type="button"
            data-testid="atlas-line-action"
            data-action-kind={line.action.kind}
            data-performable={performable ? "yes" : "no"}
            disabled={!performable}
            title={performable ? undefined : NOT_YET_PERFORMABLE}
            className="inline-flex items-center gap-1.5 rounded border border-slate-700 px-2.5 py-1 text-[12px] text-slate-200 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {line.action.label}
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

      {!performable && !attachable && (
        <p data-testid="atlas-line-not-performable" className="mt-1 text-[11px] text-slate-500">
          {NOT_YET_PERFORMABLE}
        </p>
      )}
    </li>
  );
}
