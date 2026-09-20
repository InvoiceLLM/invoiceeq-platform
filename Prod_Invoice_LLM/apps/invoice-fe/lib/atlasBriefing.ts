// =============================================================================
// FILE: lib/atlasBriefing.ts
// FEATURE: FE Feature 24 task 24.1 (spec §2, §3) — the briefing's wire types,
//          its frame parser, and the one deterministic check the FE makes.
//
// **THE CONTRACT IS BE FEATURE 35's, NOT THIS FILE'S.** Event names, payload
// fields and the answer endpoint are defined in
// `apps/invoice-be/docs/feature_35_atlas_intelligence.md` §3.3 and in
// `services/atlas_contract.py`; the types below mirror them and are imported by
// name everywhere else in this app so the shape is written down once on this
// side. Nothing here invents a field, renames one, or defaults one the backend
// did not send — the F33/F22 seam (a field the FE read that the BE never
// emitted) is the defect class both specs exist to prevent.
//
// **THE FE DOES NOT JUDGE THE PROSE (spec §1).** There is exactly one check in
// this file and it is about evidence, not language: a paragraph with no
// citations, or one naming a record this session has not seen, is rejected and
// counted. It is deterministic code rather than a rendering condition
// (CONVENTIONS hard rule 3) so that "withheld" is a number the panel prints,
// never a paragraph that quietly did not appear.
//
// NO ARITHMETIC (FE 23 §2 holds). Nothing here computes over a figure; the only
// number this module produces is a count of rejections.
// =============================================================================

import { apiClient } from "@/lib/apiClient";
import type { AtlasMemoryRule } from "@/lib/atlas";

/** BE 35 §3.3's closed set of event names. */
export type BriefingEventType =
  | "welcome"
  | "paragraph"
  | "question"
  | "truncated"
  | "error"
  | "done";

/**
 * What one sentence rests on (BE `services/atlas_contract.py::Citation`).
 *
 * `record_id` is a string for every kind, including the composed ids the
 * backend mints for things that are not stored rows (`cash-INR`, `area-audit`),
 * so nothing on this side parses it — it is only ever compared and rendered.
 */
export interface Citation {
  tool: string;
  /** `recommendation` | `invoice` | `rule` | `action` | `shortfall` | `recon_row`. */
  record_kind: string;
  record_id: string;
}

export interface BriefingParagraph {
  text: string;
  citations: Citation[];
}

export interface BriefingQuestion {
  text: string;
  citations: Citation[];
  answer_kind: string;
}

export interface BriefingWelcome {
  role: string;
  text: string;
}

export interface BriefingTruncated {
  /** `rounds` | `invocations` | `wall_clock` — printed, never interpreted. */
  reason: string;
}

export interface BriefingError {
  message: string;
}

export interface BriefingDone {
  cached: boolean;
  model: string;
  dropped_paragraphs: number;
}

/** One SSE frame: the `event:` name and its decoded `data:` payload. */
export type BriefingEvent =
  | { type: "welcome"; data: BriefingWelcome }
  | { type: "paragraph"; data: BriefingParagraph }
  | { type: "question"; data: BriefingQuestion }
  | { type: "truncated"; data: BriefingTruncated }
  | { type: "error"; data: BriefingError }
  | { type: "done"; data: BriefingDone };

const EVENT_TYPES: ReadonlySet<string> = new Set<BriefingEventType>([
  "welcome",
  "paragraph",
  "question",
  "truncated",
  "error",
  "done",
]);

/**
 * One decoded event, or `null` for anything this app does not recognise.
 *
 * `null` rather than a throw: an unknown event name is a backend that has moved
 * ahead of this app, and the right behaviour is to keep rendering the frames
 * that are understood rather than to end the stream. An event name inside the
 * closed set whose data is not JSON is a genuine defect and also returns
 * `null` — the panel counts neither as a paragraph, so nothing is silently
 * treated as evidence.
 */
export function parseBriefingEvent(
  type: string,
  rawData: string
): BriefingEvent | null {
  if (!EVENT_TYPES.has(type)) return null;
  let data: unknown;
  try {
    data = JSON.parse(rawData);
  } catch {
    return null;
  }
  if (data === null || typeof data !== "object" || Array.isArray(data)) return null;
  return { type, data } as BriefingEvent;
}

/**
 * One whole SSE frame in BE 35 §3.3's shape — `event: <type>`, `data: <json>`,
 * a blank line — decoded.
 *
 * `EventSource` does this splitting itself, so the component uses
 * `parseBriefingEvent()`; this is the parser for the wire text as the backend
 * writes it, which is what the unit tests script and what any non-EventSource
 * reader would face. Both go through the same decode, so there is one behaviour
 * and not two.
 */
export function parseBriefingFrame(raw: string): BriefingEvent | null {
  let type = "";
  const dataLines: string[] = [];
  for (const line of raw.split("\n")) {
    if (line.startsWith("event:")) type = line.slice("event:".length).trim();
    else if (line.startsWith("data:")) dataLines.push(line.slice("data:".length).trim());
  }
  if (!type || dataLines.length === 0) return null;
  return parseBriefingEvent(type, dataLines.join("\n"));
}

/** Why a paragraph was withheld. Printed only as a count; kept for logs. */
export type CitationRejection =
  | { ok: false; reason: "uncited" }
  | { ok: false; reason: "unknown_record"; recordId: string };

export type CitationCheck = { ok: true } | CitationRejection;

/**
 * The one kind whose id may be outside `knownIds` — spec §7, ruling 2
 * (2026-09-20).
 *
 * An invoice the briefing cites need not have a line on this screen: the
 * backend's guard (`assert_paragraph_cited`) already proved the id came out of a
 * tool result this run, and the FE's job is to render it as a link the reader
 * can follow. Without this exemption the ruling is unreachable in code — the
 * only thing that can widen `knownIds` mid-briefing is a paragraph that already
 * passed, so the *first* citation of an out-of-list invoice would always be
 * withheld and no later one could ever appear. Every other kind
 * (`recommendation`, `rule`, `action`, …) still has to be a record this screen
 * can actually show, because for those the id IS the destination.
 */
export const KINDS_ALLOWED_OUTSIDE_KNOWN_IDS: ReadonlySet<string> = new Set(["invoice"]);

/**
 * **The one deterministic check this app makes on the briefing (spec §1, §3.4).**
 *
 * A paragraph must rest on records this session has actually seen: every
 * citation's `record_id` has to be in `knownIds`, which the panel builds from
 * the `/atlas/lines` payload plus every id the briefing has already cited and
 * had accepted (spec §3 step 4). Two rejections, both silent-proof:
 *
 *   - no citations at all — prose about money with nothing under it;
 *   - a `record_id` this session never saw — a record the reader cannot go and
 *     check, which is the same thing as an unverifiable claim.
 *
 * It does not look at the words, the numbers or the tool name. The backend's
 * guard (`assert_paragraph_cited`) already dropped what the model invented
 * against the ids its own tools emitted; this is the independent check on the
 * consuming side, against what this screen can actually show the reader.
 */
export function validateCitations(
  paragraph: Pick<BriefingParagraph, "citations">,
  knownIds: ReadonlySet<string>
): CitationCheck {
  const citations = paragraph.citations ?? [];
  if (citations.length === 0) return { ok: false, reason: "uncited" };
  for (const citation of citations) {
    const recordId = citation?.record_id ?? "";
    if (!recordId) return { ok: false, reason: "unknown_record", recordId: "" };
    if (KINDS_ALLOWED_OUTSIDE_KNOWN_IDS.has(citation.record_kind)) continue;
    if (!knownIds.has(recordId)) {
      return { ok: false, reason: "unknown_record", recordId };
    }
  }
  return { ok: true };
}

/** Every `record_id` on a paragraph or question, in order. */
export function citedIds(
  item: Pick<BriefingParagraph, "citations">
): string[] {
  return (item.citations ?? []).map((c) => c.record_id).filter(Boolean);
}

/** Where the panel reads its stream from. One place, so the test and the app agree. */
export const BRIEFING_STREAM_PATH = "/api/atlas/briefing";

/**
 * `POST /api/atlas/briefing/answer` → 201 `MemoryRuleOut`.
 *
 * The question text is sent back with the answer because that is what the
 * backend stores as the lesson (BE 35 §3.3, `_interview_rule_text()`): an
 * answer without its question is unjudgeable later. Neither half is edited on
 * the way out — the rule is the user's own words, as `POST /atlas/memory`
 * already promises.
 */
export async function answerBriefingQuestion(
  questionText: string,
  answer: string
): Promise<AtlasMemoryRule> {
  const { data } = await apiClient.post<AtlasMemoryRule>("/atlas/briefing/answer", {
    question_text: questionText,
    answer,
  });
  return data;
}

// ─────────────────────────────────────────────────────────────────────────────
// FE Gap 706 — what a citation is LABELLED
//
// The panel used to print the raw `record_id` under every paragraph, so a
// reader's evidence read `audit-approve-530bd65a-be04-4953-988b-2932f52a6f89`.
// That is the backend's primary key, and it tells a finance person nothing
// about which of their invoices the sentence above rests on.
//
// The label is therefore DERIVED FROM DATA THIS APP WAS SENT, never parsed out
// of the id: the id's shape is the backend's business (`cash-INR`,
// `area-audit`, a bare uuid) and an app that read meaning out of one would
// break the first time an emitter changed its prefix. The id is still on the
// element — in `title` and `aria-label` — so nothing is hidden from anyone
// checking, reporting or automating against it.
//
// These live here rather than in the component because
// `tests/unit/atlas-no-client-arithmetic.test.ts` greps every file in
// `components/atlas/` for operators, and string scanning is not arithmetic but
// is not worth arguing with a grep about either.
// ─────────────────────────────────────────────────────────────────────────────

/** Labels for the kinds whose name IS the label. */
const KIND_LABELS: Record<string, string> = {
  rule: "memory rule",
  action: "action",
};

/** What a citation says when nothing better is available, by kind. */
const KIND_FALLBACKS: Record<string, string> = {
  recommendation: "this line",
  invoice: "invoice",
};

function isDigit(ch: string): boolean {
  return ch >= "0" && ch <= "9";
}

function isUpper(ch: string): boolean {
  return ch >= "A" && ch <= "Z";
}

/**
 * The first invoice-number-shaped word in a string, or `null`.
 *
 * "Shaped" is deliberately crude, and it accepts exactly two forms:
 *
 *   - a word carrying both an upper-case letter and a digit — "RAJ-2009",
 *     "VPI-OUT-2014";
 *   - a word the sentence itself marked with `#` and which contains a digit —
 *     "#1041", which is how `atlas_skills` writes a headline's invoice number.
 *
 * A money figure has no letters and no `#`, a date word has no digits glued to
 * it, and a sentence containing neither form yields `null`, whereupon the
 * caller falls back to a generic word. Nothing is computed and nothing is
 * reformatted — the word is returned exactly as it appeared, minus the
 * punctuation around it.
 */
export function invoiceNumberIn(text: string): string | null {
  for (const raw of (text ?? "").split(/\s+/)) {
    const word = raw.replace(/^[^A-Za-z0-9]+/, "").replace(/[^A-Za-z0-9]+$/, "");
    if (word.length === 0) continue;
    const chars = Array.from(word);
    if (!chars.some(isDigit)) continue;
    if (chars.some(isUpper) && word.length >= 3) return word;
    if (raw.startsWith("#")) return word;
  }
  return null;
}

/**
 * What the reader sees under a paragraph for one citation (spec §3 step 8).
 *
 * `lineLabels` is `WorkScreen`'s map from a recommendation id to the invoice
 * number in that line's own headline — the payload this screen already has, so
 * the label and the line the click scrolls to are the same record by
 * construction. `paragraphText` is used only for an `invoice` citation, whose
 * number the backend does not send separately but whose paragraph names it.
 */
export function citationLabel(
  citation: Citation,
  paragraphText: string,
  lineLabels?: ReadonlyMap<string, string>
): string {
  const kind = citation?.record_kind ?? "";
  const named = KIND_LABELS[kind];
  if (named) return named;

  if (kind === "recommendation") {
    const label = lineLabels?.get(citation.record_id ?? "");
    return label ?? KIND_FALLBACKS.recommendation;
  }
  if (kind === "invoice") {
    return invoiceNumberIn(paragraphText) ?? KIND_FALLBACKS.invoice;
  }
  // `shortfall`, `recon_row`, `cash_position`, `collapsed_area` and anything a
  // later backend adds: the kind word reads as English once its underscores are
  // spaces, and it is still never the id.
  return kind ? kind.split("_").join(" ") : "record";
}
