// =============================================================================
// FILE: lib/chatAttachments.ts
// FEATURE: Feature 5 (chat) surface of BE Feature 26 — Chat Attached Documents,
//          Part 2 task H10 (spec §P2.6.1–P2.6.3).
//
// WHY THIS FILE EXISTS (and why the guards are not inline in ChatWindow.tsx):
//   Three call sites need the same values and the same copy — the composer's
//   file-picker guards (ChatWindow.tsx), the attached-document chip
//   (AttachmentChip.tsx) and the match-confirmation card
//   (AttachmentMatchConfirm.tsx). Keeping them here means the 10 MB cap and the
//   5-per-session cap are stated once, next to the backend constants they must
//   agree with, instead of drifting apart across three components.
//   It is also the only shape of this feature that this app can actually test:
//   invoice-fe has no Jest/RTL/vitest harness (package.json has @playwright/test
//   and nothing else), and Playwright's own babel transform rewrites JSX into
//   its component-test object, so a .tsx component cannot be rendered inside a
//   spec via react-dom/server. Pure TS in a .ts module can be imported and
//   asserted on for real — see e2e/chat-attachment-guards.spec.ts.
//
// THE CAPS MUST AGREE WITH THE BACKEND. Their source of truth is
//   apps/invoice-be/routers/chat_attachments.py:
//     MAX_ATTACHMENT_BYTES        = 10 * 1024 * 1024   (rejects with 413)
//     MAX_ATTACHMENTS_PER_SESSION = 5                  (rejects with 409)
//     ALLOWED_CONTENT_TYPES       = {"application/pdf"} (rejects with 415)
//   Decision D3 of docs/feature_26_chat_attached_documents.md. Deliberately NOT
//   DropZone.tsx's MAX_FILE_SIZE (25 MB) — a client cap of 25 MB here would let
//   a user wait through an upload the backend was always going to 413.
// =============================================================================

/** 10 MB. Backend `MAX_ATTACHMENT_BYTES`; over this the upload 413s. */
export const MAX_CHAT_ATTACHMENT_BYTES = 10 * 1024 * 1024;

/** 5. Backend `MAX_ATTACHMENTS_PER_SESSION`; at this count the upload 409s. */
export const MAX_CHAT_ATTACHMENTS_PER_SESSION = 5;

/**
 * PDF only (D1). Image upload is Feature 27's `ENABLE_GENERIC_EXTRACTION`
 * territory and is deliberately NOT widened here: the backend's
 * `ALLOWED_CONTENT_TYPES` is still `{"application/pdf"}`, so accepting an image
 * in the picker would produce a 415 after the user had already chosen a file.
 * Widening this is gated on that flag being surfaced through the config
 * endpoint AND the backend accepting the type — both out of H10's scope.
 */
export const CHAT_ATTACHMENT_ACCEPT = ".pdf";

// -----------------------------------------------------------------------------
// Shapes mirrored from the backend. VERIFIED against the live source rather than
// against the spec's summary — §P2.8's contract sketch is stale in two places
// (it names the candidate field `vendor_name`, and omits `kind` /
// `requires_manual_entry` / `flow_direction`); these follow the code.
// -----------------------------------------------------------------------------

/** `routers/chat_attachments.py::AttachmentOut` (`_to_out`). */
export interface ChatAttachmentSummary {
  id: string;
  session_id: string;
  filename: string;
  doc_type: string;
  /** "PENDING" | "EXTRACTED" | "EXTRACT_FAILED" — the REFERENCE profile's own vocabulary. */
  extraction_status: string;
  doc_number?: string | null;
  party_name?: string | null;
  doc_date?: string | null;
  currency?: string | null;
  grand_total?: number | null;
  file_size_bytes?: number;
  candidate_invoice_ids?: string[];
  confirmed_invoice_ids?: string[];
  // Feature 26 Phase 4 (Gap 444/445). Everything below arrives with the upload
  // response, so the chip can say what was read and what it matched BEFORE the
  // user asks anything -- which is the only moment an extraction mistake is
  // cheap to correct.
  line_count?: number;
  /** 1 = document number, 2 = party + date window, 3 = content similarity, 0 = none. */
  match_tier?: number | null;
  match_summary?: string | null;
  attachment_count?: number;
  attachment_limit?: number;
  extraction_preview?: AttachmentExtractionPreview | null;
  /** Fields the extractor was unsure of, worth confirming before a match. */
  low_confidence_fields?: string[];
  /**
   * Feature 26 Phase 3.3 (Gap 452). Present when extraction was queued on the
   * worker: subscribe to `/api/chat/jobs/{id}/stream` for the stages. Absent
   * when the backend extracted inline (Redis down), in which case the summary
   * is already final.
   */
  extraction_job_id?: string | null;
}

/** Gap 452: the worker's stage names, and what the chip says for each. */
export const ATTACHMENT_STAGE_LABELS: Record<string, string> = {
  queued: "Queued",
  reading_document: "Reading the document",
  extracting_fields: "Extracting the fields",
  indexing_text: "Indexing the text",
  matching_invoices: "Looking for matching invoices",
  attachment_ready: "Ready",
  attachment_failed: "Could not read this document",
};

/** What the "here is what I read" panel renders (`_extraction_preview()`). */
export interface AttachmentExtractionPreview {
  doc_type?: string | null;
  doc_number?: string | null;
  party_name?: string | null;
  doc_date?: string | null;
  currency?: string | null;
  subtotal?: number | null;
  tax_amount?: number | null;
  grand_total?: number | null;
  payment_terms?: string | null;
  delivery_terms?: string | null;
  line_count?: number;
  lines?: Array<{
    description?: string | null;
    quantity?: number | null;
    unit_price?: number | null;
    amount?: number | null;
  }>;
  referenced_document_count?: number;
}

/**
 * Gap 444: the match proposal as one short phrase for the chip.
 *
 * The backend already composes `match_summary`; this exists for the case where
 * an older row has none, so the chip still says something true rather than
 * falling silent about whether a match was found.
 */
export function matchStatusLabel(a: ChatAttachmentSummary): string {
  if (a.match_summary) return a.match_summary;
  const count = a.candidate_invoice_ids?.length ?? 0;
  if (!count) return "no matching invoice found yet";
  return count === 1 ? "1 possible match" : `${count} possible matches`;
}

/** Gap 445: which fields to query before trusting a match, in plain words. */
export const CONFIDENCE_FIELD_LABELS: Record<string, string> = {
  doc_number: "document number",
  grand_total: "total",
  party_name: "party name",
  doc_date: "document date",
};

/**
 * The four states of one attachment in the composer (§P2.6.2).
 *
 * `uploading` and `extracting` are two states, not one, because they are two
 * genuinely different waits: the first has real byte progress (which is why the
 * uploader must be XMLHttpRequest — `fetch` exposes no upload progress), the
 * second is a synchronous Document Intelligence round trip inside the same
 * request with no progress to report. Collapsing them would either fake a
 * progress bar or throw away a real one.
 */
export type AttachmentState =
  | { status: "uploading"; filename: string; progress: number }
  | {
      status: "extracting";
      filename: string;
      /**
       * Feature 26 Phase 3.3 (Gap 452): which stage the worker is on. Absent
       * while the upload request is still in flight (nothing has been reported
       * yet); set from the job stream once extraction is queued.
       */
      stage?: string;
    }
  | { status: "ready"; filename: string; attachment: ChatAttachmentSummary }
  | {
      status: "failed";
      filename: string;
      /**
       * Which of the two failures this is. They are distinguishable on purpose:
       * `upload_rejected` means nothing was stored (413/415/409), while
       * `extraction_failed` means the file IS stored and we could not read it
       * (`extraction_status === "EXTRACT_FAILED"`). Presenting the second as
       * "nothing was uploaded" would be a lie about server state.
       */
      failure: "upload_rejected" | "extraction_failed";
      /** The backend's own `detail` string where there is one. */
      message: string;
    };

/** One row of `build_confirmation_payload()`'s `candidates` list. */
export interface AttachmentCandidate {
  invoice_id: string;
  invoice_number?: string | null;
  /** `party_name`, not `vendor_name` — the backend emits `vendor_name or customer_name`. */
  party_name?: string | null;
  invoice_date?: string | null;
  grand_total?: number | null;
  currency?: string | null;
  status?: string | null;
  flow_direction?: string | null;
}

/**
 * `services/document_comparison.py::build_confirmation_payload()`, surfaced on
 * the turn as `attachment_confirmation` (`agents/query_agent.py` L3008).
 *
 * `truncated` is optional because the zero-candidate branch does not emit it at
 * all — only the populated branch does.
 */
export interface AttachmentConfirmation {
  kind: "attachment_match_confirmation";
  attachment_id: string;
  /** 1 = PO-number join, 2 = supplier+date, 0 = nothing found. 3 is Tier 3 (E-4), not built yet. */
  tier: number;
  candidates: AttachmentCandidate[];
  requires_manual_entry: boolean;
  message: string;
  truncated?: boolean;
}

// -----------------------------------------------------------------------------
// Guards — the client half of D3's caps
// -----------------------------------------------------------------------------

export type AttachmentRejectionCode = "wrong_type" | "too_large" | "too_many";

export interface AttachmentRejection {
  code: AttachmentRejectionCode;
  message: string;
}

/** Just enough of `File` to be constructible in a test without a DOM. */
export interface PickedFile {
  name: string;
  size: number;
}

/**
 * Returns the reason this file cannot be attached, or `null` if it can.
 *
 * Order matters: the count check runs first, because "you already have 5" is
 * true regardless of which file was picked and it would be perverse to complain
 * about the file's type when no sixth file of any type is allowed.
 *
 * The suffix check is the same one DropZone.tsx does at L58
 * (`name.toLowerCase().endsWith(".pdf")`) and the same one the backend does at
 * chat_attachments.py L160. The browser supplies the content type on the
 * multipart part itself, so it is not re-checked here — the backend is the
 * authority on it and rejects with 415, which lands as `upload_rejected`.
 */
export function validateChatAttachment(
  file: PickedFile,
  opts: { attachmentCount: number }
): AttachmentRejection | null {
  if (opts.attachmentCount >= MAX_CHAT_ATTACHMENTS_PER_SESSION) {
    return {
      code: "too_many",
      message: `This conversation already has ${MAX_CHAT_ATTACHMENTS_PER_SESSION} attachments, which is the limit. Start a new conversation to attach more.`,
    };
  }
  if (!file.name.toLowerCase().endsWith(".pdf")) {
    return {
      code: "wrong_type",
      message: "Only PDF files can be attached to a conversation.",
    };
  }
  if (file.size > MAX_CHAT_ATTACHMENT_BYTES) {
    return {
      code: "too_large",
      message: `Attachments are limited to ${MAX_CHAT_ATTACHMENT_BYTES / (1024 * 1024)} MB.`,
    };
  }
  return null;
}

/** True once the session is full, i.e. the paperclip must be disabled. */
export function isAttachmentLimitReached(attachmentCount: number): boolean {
  return attachmentCount >= MAX_CHAT_ATTACHMENTS_PER_SESSION;
}

// -----------------------------------------------------------------------------
// Copy
// -----------------------------------------------------------------------------

/**
 * How the candidate set was arrived at (§P2.6.3). A Tier-3 guess must never
 * read like a Tier-1 join, which is the entire reason this is a visible label
 * and not just a different border colour.
 *
 * Tier 3 is FORWARD-COMPATIBLE ONLY: `find_candidate_invoices()` returns 1, 2
 * or 0 today — the vector-discovery tier is E-4 / task H6 and is not built, so
 * the tier-3 string here has never been rendered against a real payload.
 */
export function attachmentTierLabel(tier: number): string {
  switch (tier) {
    case 1:
      return "Matched on PO number";
    case 2:
      return "Matched on supplier and date";
    case 3:
      return "Found by similarity — please confirm";
    default:
      return "No match found";
  }
}

/**
 * Only a Tier-1 exact PO-number join is confident enough to pre-check. Tier 2
 * (supplier substring + a ±90 day window) and Tier 3 (similarity) are
 * heuristics, and confirming a heuristic must be a deliberate act — that is
 * what D4's gate is for.
 */
export function candidatesArePreChecked(tier: number): boolean {
  return tier === 1;
}

/**
 * The truncation notice, or null when nothing was dropped. The count comes from
 * the payload rather than being hardcoded to 20, so the Tier-3 cap of 10 (E-4,
 * unbuilt) needs no change here.
 */
export function attachmentTruncationNotice(
  candidateCount: number,
  truncated?: boolean
): string | null {
  if (!truncated) return null;
  return `Showing the closest ${candidateCount} by date — there were more. Refine the document or enter the invoice number if the right one isn't here.`;
}

/** `PURCHASE_ORDER` → `PURCHASE ORDER`. Unknown/empty falls back to `DOCUMENT`. */
export function docTypeBadgeLabel(docType?: string | null): string {
  const raw = (docType ?? "").trim();
  if (!raw) return "DOCUMENT";
  return raw.toUpperCase().replace(/_/g, " ");
}

/** Headline for the two failure variants — they must not read the same. */
export function attachmentFailureHeadline(
  failure: "upload_rejected" | "extraction_failed"
): string {
  return failure === "upload_rejected"
    ? "Couldn't attach that file"
    : "Couldn't read that document";
}

/**
 * Only the extraction failure gets a retry hint: the file is stored, so the
 * useful next step is a better scan of the same document. An upload rejection
 * already carries the backend's own reason (too large / wrong type / too many),
 * and "try a clearer PDF" would be nonsense advice for any of them.
 */
export const EXTRACTION_FAILED_HINT =
  "The file was saved but the text couldn't be read. Try a clearer PDF.";

/** Middle-truncates a long filename so the extension stays visible. */
export function truncateFilenameMiddle(filename: string, max = 34): string {
  if (filename.length <= max) return filename;
  const head = Math.ceil((max - 1) / 2);
  const tail = Math.floor((max - 1) / 2);
  return `${filename.slice(0, head)}…${filename.slice(filename.length - tail)}`;
}

// =============================================================================
// TASK H11 (§P2.6.4) — the rest of the answer contract
//
// Everything below mirrors what `agents/query_agent.py` ACTUALLY returns from
// `_run_attached_document_turn()` / `_run_attachment_content_branch()` and what
// `services/document_comparison.py` actually computes. It was written against
// those two files, not against §P2.8's contract sketch, which H10 already found
// stale for `attachment_confirmation` and which is stale again here:
//
//   * `suggested_actions` — §P2.8 says `{label, href, reason}`. The real
//     `build_suggested_actions()` (document_comparison.py L380) emits
//     `{label, endpoint, method, href, precondition}`. There is no `reason`
//     key at all; `precondition` is the nearest thing and says something
//     different (it names the rule the endpoint enforces, not why the link is
//     being offered).
//   * `attachment_comparison` — §P2.8 writes it as `{ "comparisons": [...] }`.
//     The real `compare_reference_to_invoices()` also returns `reference`,
//     `compared_count` and `blocked_count`, and each comparison carries
//     `invoice_status` / `flow_direction` / `reference_currency` /
//     `invoice_currency` / `reference_line_count` / `invoice_line_count` /
//     `line_count_delta` / `blocked_reason`, none of which §P2.8 lists. The
//     per-field rows are `{field, reference_value, invoice_value, delta,
//     status}` — `reference_value`, not "document value".
//   * `needs_confirmation` — §P2.6.4 describes it as the flag that pins the
//     confirmation card. In the live code it is emitted ONLY by the content
//     branch and ONLY as `false` (query_agent.py L3437, L3526). The
//     confirmation turn does not set it; it emits `attachment_confirmation`
//     instead. So the card is driven off the payload's presence, and
//     `needs_confirmation` is treated as an additional "we produced no figures"
//     note — never as the card's own render condition, which would have made
//     the safety gate invisible.
//
// MONEY IS NEVER PARSED. Every amount on this path arrives as a Decimal-derived
// STRING ("1250.00"), because the backend stringifies `Decimal` deliberately.
// Running it through `Number()` to format it would re-introduce binary float
// error into figures the whole feature exists to keep exact (D5, hard rule 3),
// so the helpers below concatenate the currency code onto the string as given.
// =============================================================================

/** One row of a comparison's `fields[]` (`_compare_one`, document_comparison.py L262/L284). */
export interface ComparisonFieldRow {
  /** `subtotal` | `tax_amount` | `grand_total` (`_COMPARED_AMOUNT_FIELDS`). */
  field: string;
  /** Decimal-as-string, or null when the document did not state it. */
  reference_value?: string | null;
  invoice_value?: string | null;
  /** invoice − document, Decimal-as-string. Null on a `missing` row. */
  delta?: string | null;
  /** `match` | `invoice_higher` | `invoice_lower` | `missing`. */
  status?: string | null;
}

/** One invoice's comparison (`_compare_one`). */
export interface AttachmentComparisonEntry {
  invoice_id: string;
  invoice_number?: string | null;
  invoice_status?: string | null;
  flow_direction?: string | null;
  /** `match` | `variance` | `incomplete` | `currency_mismatch`. */
  outcome: string;
  reference_currency?: string | null;
  invoice_currency?: string | null;
  /** Empty on a `currency_mismatch` — nothing was compared. */
  fields?: ComparisonFieldRow[];
  reference_line_count?: number | null;
  invoice_line_count?: number | null;
  line_count_delta?: number | null;
  /** Set only on `currency_mismatch`; the backend's own refusal wording. */
  blocked_reason?: string | null;
}

/** `compare_reference_to_invoices()`, surfaced as `attachment_comparison`. */
export interface AttachmentComparison {
  reference?: {
    doc_type?: string | null;
    doc_number?: string | null;
    party_name?: string | null;
    doc_date?: string | null;
    currency?: string | null;
    grand_total?: string | null;
  };
  comparisons: AttachmentComparisonEntry[];
  compared_count?: number;
  /** How many comparisons were refused outright for a currency mismatch. */
  blocked_count?: number;
}

/** One entry of `build_suggested_actions()`. `href` is an in-app route. */
export interface SuggestedAction {
  label: string;
  href: string;
  /** The rule the target endpoint enforces, e.g. "status is AUDIT_REQUIRED". */
  precondition?: string;
  /** Present but unused by the UI: chat never calls these (D6). */
  endpoint?: string;
  method?: string;
}

/** One retrieved span from `search_attachment_chunks()`, content branch only. */
export interface AttachmentEvidenceSpan {
  page?: number | null;
  text?: string | null;
  /** Cosine distance. Lower is closer. Not shown as a score — see DocumentEvidence.tsx. */
  distance?: number | null;
}

/**
 * "resend" (Feature 6.1 item C3): the SQL route's zero-row proposal -- "Did you
 * mean Apex Consulting Group?" -- rides this same contract. Its options carry
 * `text`, the user's question with the typo corrected, and the button sends that
 * verbatim as a normal turn. The backend never auto-corrects; the click is the
 * confirmation.
 */
export type AttachmentClarificationIntent = "read" | "compare" | "resend";
export interface AttachmentClarificationOption {
  intent: string;
  label: string;
  /** Present on "resend" options only: the exact message to send when chosen. */
  text?: string;
}

/** The clarifying turn (E-1 as amended by B2), `query_agent.py` L3199. */
export interface AttachmentClarification {
  message: string;
  options?: AttachmentClarificationOption[];
}

/** D6 caps suggestions at 3 server-side; the UI does not trust that silently. */
export const MAX_SUGGESTED_ACTIONS = 3;

/**
 * The backend's canonical option pair, in the order `_INTENT_CLARIFICATION_MESSAGE`
 * asks the question in ("read the document, or compare it to your invoices?").
 * Used only as a fallback when a clarifying turn arrives with no `options`.
 */
export const DEFAULT_CLARIFICATION_OPTIONS: AttachmentClarificationOption[] = [
  { intent: "read", label: "Read the document" },
  { intent: "compare", label: "Compare to my invoices" },
];

/**
 * What "re-send with an explicit intent" ACTUALLY means against the live
 * backend — checked rather than assumed.
 *
 * There is no structured intent field anywhere on the request path:
 * `MessageCreate` (routers/chat.py) carries `content` and `attachment_id` and
 * nothing else, and `_classify_attachment_intent(user_message, doc_type)`
 * (query_agent.py L3076) is a pure keyword match over the message TEXT. So an
 * "explicit intent" can only be a phrase in the re-sent message that the
 * classifier's boundary-anchored alternations resolve to exactly one branch.
 *
 * These two phrases are chosen against `_CONTENT_INTENT_KEYWORDS` and
 * `_COMPARISON_INTENT_KEYWORDS` so that each hits its own family and NEITHER
 * hits the other ("read the document" and "tell me what it says" are content
 * keywords; "compare" is a comparison keyword) — asserted cross-language in
 * e2e/chat-attachment-contract.spec.ts, which reads the Python lists.
 */
export const ATTACHMENT_INTENT_PHRASE: Record<AttachmentClarificationIntent, string> = {
  read: "Read the document and tell me what it says.",
  compare: "Compare it to my invoices.",
  // Not used to compose: a "resend" option carries its own `text`. Kept so the
  // Record stays exhaustive and a resend option with no text still sends something
  // that reads as a confirmation rather than an empty message.
  resend: "Yes, use that.",
};

/**
 * The follow-up message text for a clarification choice: the user's original
 * question, plus the disambiguating phrase.
 *
 * KNOWN LIMIT, stated rather than discovered later. Because the classifier sees
 * only text, appending a comparison phrase to a question that already contains
 * a content keyword (or vice versa) produces the BOTH-match case, which
 * `_INTENT_BIAS_BY_DOC_TYPE` resolves by document family — and for `OTHER` or a
 * null `doc_type` that biases to "clarify" again. Closing that would need a
 * real intent field on `MessageCreate`, i.e. a backend change, which is not
 * H11's scope. The common path (the clarifying turn fires because NEITHER
 * family matched) is unaffected: one phrase then decides it outright.
 */
export function composeClarificationReply(
  originalQuestion: string | null | undefined,
  intent: AttachmentClarificationIntent,
  text?: string | null
): string {
  // C3: a "resend" option IS the message. Nothing to compose.
  if (intent === "resend" && text && text.trim()) return text.trim();
  const phrase = ATTACHMENT_INTENT_PHRASE[intent];
  const question = (originalQuestion ?? "").trim();
  if (!question) return phrase;
  return `${question} — ${phrase}`;
}

/**
 * The options to render for a clarifying turn: whatever the payload sent, with
 * the canonical pair as a fallback. Options whose `intent` this build has no
 * phrase for are dropped rather than rendered — a button that cannot compose a
 * re-send is a dead control, and silently sending the raw question back would
 * loop the user through the same clarifying turn again.
 */
export function clarificationOptions(
  clarification: AttachmentClarification | null | undefined
): AttachmentClarificationOption[] {
  const raw = clarification?.options?.length
    ? clarification.options
    : DEFAULT_CLARIFICATION_OPTIONS;
  return raw.filter((o) => isKnownClarificationIntent(o.intent));
}

export function isKnownClarificationIntent(
  intent: string
): intent is AttachmentClarificationIntent {
  return intent === "read" || intent === "compare" || intent === "resend";
}

// -----------------------------------------------------------------------------
// The diff table (§P2.6.4)
// -----------------------------------------------------------------------------

/**
 * A currency mismatch is a REFUSAL, not a row of numbers. `_compare_one()`
 * returns `fields: []` and a `blocked_reason` for it, so there is nothing to
 * put in the value columns — and rendering the delta column as `0.00` (which a
 * naive `delta ?? 0` would do) would state that a EUR document and an INR
 * invoice agree. That is the single wrong answer this feature exists to
 * prevent, so the two row kinds are separate types rather than one type with
 * empty fields.
 */
export type ComparisonTableRow =
  | {
      kind: "field";
      label: string;
      referenceValue: string;
      invoiceValue: string;
      delta: string;
      outcome: string;
      status: string;
    }
  | { kind: "refusal"; label: string; reason: string };

const COMPARISON_FIELD_LABELS: Record<string, string> = {
  subtotal: "Subtotal",
  tax_amount: "Tax",
  grand_total: "Grand total",
};

const COMPARISON_STATUS_LABELS: Record<string, string> = {
  match: "Match",
  invoice_higher: "Invoice higher",
  invoice_lower: "Invoice lower",
  // Not "zero" and not "0.00": `_compare_one` records `missing` when either
  // side did not state the figure, and the narration prompt is explicitly told
  // not to treat a missing value as zero. The table must not either.
  missing: "Not stated",
};

export function comparisonFieldLabel(field: string): string {
  return COMPARISON_FIELD_LABELS[field] ?? field.replace(/_/g, " ");
}

export function comparisonStatusLabel(status?: string | null): string {
  if (!status) return "—";
  return COMPARISON_STATUS_LABELS[status] ?? status.replace(/_/g, " ");
}

const COMPARISON_OUTCOME_LABELS: Record<string, string> = {
  match: "Matches",
  variance: "Variance",
  incomplete: "Incomplete",
  currency_mismatch: "Not compared",
};

export function comparisonOutcomeLabel(outcome?: string | null): string {
  if (!outcome) return "—";
  return COMPARISON_OUTCOME_LABELS[outcome] ?? outcome.replace(/_/g, " ");
}

/**
 * A money cell. The value is a Decimal-as-string and stays one — see the header
 * note. `null` means the side did not state it, which renders as an em dash,
 * never as 0.
 */
export function formatComparisonAmount(
  value: string | null | undefined,
  currency?: string | null
): string {
  if (value == null || value === "") return "—";
  const code = (currency ?? "").trim();
  return code ? `${code} ${value}` : value;
}

/**
 * The delta cell. Signed, so "the invoice asks for more" is readable at a
 * glance. `Number()` is used ONLY to decide whether to prefix a `+`; the string
 * that gets displayed is always the backend's own.
 */
export function formatComparisonDelta(delta: string | null | undefined): string {
  if (delta == null || delta === "") return "—";
  const value = delta.trim();
  if (value.startsWith("-")) return value;
  const numeric = Number(value);
  if (!Number.isFinite(numeric) || numeric === 0) return value;
  return `+${value}`;
}

/**
 * Flattens one comparison into the rows §P2.6.4's table renders.
 *
 * The line-count row is included because `_compare_one()` computes it
 * (`reference_line_count` / `invoice_line_count` / `line_count_delta`) and
 * dropping it would hide a real, already-computed difference — a PO with 5
 * lines billed as 7 is exactly the thing a user is looking for. It is labelled
 * as a count, not as money, and carries no currency.
 */
export function buildComparisonRows(
  entry: AttachmentComparisonEntry
): ComparisonTableRow[] {
  if (entry.outcome === "currency_mismatch") {
    return [
      {
        kind: "refusal",
        label: "Currency mismatch",
        reason:
          entry.blocked_reason ??
          `The attached document is in ${entry.reference_currency ?? "another currency"} and this invoice is in ${entry.invoice_currency ?? "a different one"}. No amounts were compared.`,
      },
    ];
  }

  const rows: ComparisonTableRow[] = (entry.fields ?? []).map((field) => ({
    kind: "field" as const,
    label: comparisonFieldLabel(field.field),
    referenceValue: formatComparisonAmount(field.reference_value, entry.reference_currency),
    invoiceValue: formatComparisonAmount(field.invoice_value, entry.invoice_currency),
    delta: formatComparisonDelta(field.delta),
    outcome: comparisonStatusLabel(field.status),
    status: field.status ?? "",
  }));

  if (entry.reference_line_count != null && entry.invoice_line_count != null) {
    const lineDelta = entry.line_count_delta ?? 0;
    rows.push({
      kind: "field",
      label: "Line items",
      referenceValue: String(entry.reference_line_count),
      invoiceValue: String(entry.invoice_line_count),
      delta: lineDelta === 0 ? "0" : `${lineDelta > 0 ? "+" : ""}${lineDelta}`,
      outcome: lineDelta === 0 ? "Match" : "Counts differ",
      status: lineDelta === 0 ? "match" : "line_count_differs",
    });
  }

  return rows;
}

/**
 * D6's cap, applied client-side too. `build_suggested_actions()` already slices
 * to 3 per comparison and `_run_attached_document_turn()` slices the combined
 * list to 3 again, but a cap that only exists on the far side of an HTTP
 * boundary is not a cap this component can rely on.
 */
export function capSuggestedActions(
  actions: SuggestedAction[] | null | undefined
): SuggestedAction[] {
  return (actions ?? []).filter((a) => a && a.href && a.label).slice(0, MAX_SUGGESTED_ACTIONS);
}

// -----------------------------------------------------------------------------
// Evidence (§P2.6.4, content branch)
// -----------------------------------------------------------------------------

/**
 * The page label on an evidence block. `page` can be null — H3 stores one chunk
 * per page but a span whose metadata did not carry one must still render, and
 * "Page ?" is honest where silently printing "p.0" is not.
 */
export function evidencePageLabel(span: AttachmentEvidenceSpan): string {
  return span.page == null ? "Page ?" : `p.${span.page}`;
}

/** The collapsed preview. Full text is behind the expander. */
export function evidencePreview(text: string | null | undefined, max = 140): string {
  const value = (text ?? "").replace(/\s+/g, " ").trim();
  if (!value) return "(no text)";
  return value.length <= max ? value : `${value.slice(0, max - 1)}…`;
}
