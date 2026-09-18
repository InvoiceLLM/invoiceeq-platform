// =============================================================================
// FILE: lib/atlas.ts
// FEATURE: FE Feature 23 — the work screen. Counterpart of BE Feature 34
//          (ATLAS), which OWNS every shape below.
//
// WHY THIS FILE EXISTS: `lib/apiClient.ts` is a 7-line bare axios instance, not
// a method surface, so a feature's calls live in their own module beside the
// types they must agree with — the `lib/chatInsights.ts` / `lib/chatAttachments.ts`
// pattern.
//
// THESE TYPES ARE TRANSCRIBED, NOT DESIGNED. Every name here comes from
// `apps/invoice-be/services/atlas_contract.py` (§12.2) and
// `apps/invoice-be/routers/atlas.py` (§15.2). Nothing is added, widened or
// renamed on this side. The F33/F22 seam — a field the FE read that the BE
// never emitted — is the defect class both specs exist to prevent, so the rule
// for this file is blunt: if it is not in the BE spec, it is not here.
//
// NO ARITHMETIC, ANYWHERE IN THIS FEATURE (spec §2). Every figure is printed
// exactly as the server sent it. `Figure.rendered` is the string a user reads;
// `Figure.value` exists on the wire and is deliberately typed `never`-adjacent
// here — see the comment on it — because a number the client can add up is a
// number the client eventually adds up.
// =============================================================================

import { apiClient } from "@/lib/apiClient";

// -----------------------------------------------------------------------------
// The contract — services/atlas_contract.py
// -----------------------------------------------------------------------------

/** `AtlasCapability` — a closed set of four, never a rank (BE §12.3). */
export type AtlasCapability = "audit" | "train" | "load" | "admin";

/** `Certainty` — plain words, never a number or a bar (BE §5.1). */
export type Certainty = "certain" | "uncertain";

/** `Reversibility` (BE §5.3). `leaves_company` never batches, even when certain. */
export type Reversibility = "reversible" | "irreversible" | "leaves_company";

/**
 * `Figure` — one number with the witness that makes it real.
 *
 * `rendered` is the ONLY form that may appear on screen. `value` is on the wire
 * (the backend needs it for its own arithmetic) and is typed here as `unknown`
 * on purpose: TypeScript then refuses `figure.value + other.value` at compile
 * time, which is a cheaper version of the grep-shaped test in
 * `tests/unit/atlas-no-client-arithmetic.test.ts`.
 */
export interface AtlasFigure {
  rendered: string;
  value: unknown;
  currency: string;
  source: "document" | "computed";
  document_id?: string | null;
  quote?: string | null;
  computation?: string | null;
}

/** `What` — the subject, one sentence, as sent. Never recomposed client-side. */
export interface AtlasWhat {
  headline: string;
  entity_kind: string;
  entity_id: string;
}

/** `Why` — the server's reason, verbatim, with every number it used declared. */
export interface AtlasWhy {
  text: string;
  figures: AtlasFigure[];
  references: string[];
  /** Present iff `certainty === "uncertain"` (BE enforces both directions). */
  doubt?: string | null;
}

/**
 * `Action` — one click.
 *
 * **There is no URL here, deliberately** (BE §12.2). `kind` is what the FE
 * dispatches on, and the endpoints that perform these kinds are BE Slice C and
 * do not exist yet (BE §15.2). `ACTION_IS_PERFORMABLE` below is how this app
 * says so out loud instead of shipping a button that 404s.
 */
export interface AtlasAction {
  kind: string;
  label: string;
  target_id: string;
  params: Record<string, unknown>;
}

/** `Verify` — how the user checks ATLAS themselves. The question is never optional. */
export interface AtlasVerify {
  question: string;
  document_id?: string | null;
}

/** `Correction` — the invoice before and after the fix (D45, BE §14.6). */
export interface AtlasCorrection {
  field_label: string;
  field_name: string;
  before_rendered?: string | null;
  after_rendered: string;
}

/** `Recommendation` — one line on the work screen. */
export interface AtlasRecommendation {
  id: string;
  capability: AtlasCapability;
  skill: string;
  what: AtlasWhat;
  why: AtlasWhy;
  action: AtlasAction;
  verify: AtlasVerify;
  correction?: AtlasCorrection | null;
  certainty: Certainty;
  reversibility: Reversibility;
  currency: string;
  /** Computed by the backend, never supplied. Read-only here, and in v1 unused
   *  for rendering: D42 ships no batch control at all. */
  batchable: boolean;
}

// -----------------------------------------------------------------------------
// The envelopes — routers/atlas.py (BE §15.2)
// -----------------------------------------------------------------------------

export interface AtlasLinesResponse {
  /** D3. A field, not `lines.length === 0`: "No tasks assigned" and "nothing
   *  needs you right now" are different sentences. */
  ungranted: boolean;
  capabilities: AtlasCapability[];
  lines: AtlasRecommendation[];
  doubt_checks_run: number;
  doubt_checks_skipped: number;
}

/** One row of one recon group. Every amount is a string the server formatted. */
export interface AtlasReconRow {
  invoice_number?: string | null;
  invoice_id?: string | null;
  amount_rendered: string;
  theirs_rendered?: string | null;
  ours_rendered?: string | null;
  difference_rendered?: string | null;
}

export interface AtlasReconGroups {
  matched: AtlasReconRow[];
  they_show_we_do_not: AtlasReconRow[];
  we_show_they_do_not: AtlasReconRow[];
  amount_differs: AtlasReconRow[];
  unmatchable: AtlasReconRow[];
}

export interface AtlasReconResponse {
  vendor_name: string;
  currency: string;
  document_id: string;
  agrees: boolean;
  groups: AtlasReconGroups;
  unreadable_rows: number;
  lines: AtlasRecommendation[];
}

// -----------------------------------------------------------------------------
// Completeness — asserted, not assumed (spec §2)
// -----------------------------------------------------------------------------

/**
 * Why a line can be rejected before it renders.
 *
 * Spec §2: "A line missing any of them is a defect, and the FE asserts this
 * rather than tolerating it." Rendering a line with an empty `why` or no
 * `verify` would turn a backend defect into a slightly worse-looking screen,
 * which is how it survives to production.
 */
export function lineDefect(line: AtlasRecommendation): string | null {
  if (!line?.id) return "the line has no id";
  if (!line.what?.headline?.trim()) return "what.headline is missing";
  if (!line.why?.text?.trim()) return "why.text is missing";
  if (!line.action?.kind?.trim() || !line.action?.label?.trim())
    return "action is missing its kind or label";
  if (!line.verify?.question?.trim()) return "verify.question is missing";
  if (line.certainty === "uncertain" && !line.why?.doubt?.trim())
    return "an uncertain line must state its doubt in words";
  return null;
}

/**
 * The action kinds this app can actually perform today.
 *
 * **Empty, and that is the honest value** (BE §15.2): `routers/atlas.py` reads
 * and writes nothing, and every kind in §14.6's vocabulary — `resolve_invoice`,
 * `apply_field_correction`, `retry_ingestion_source`, … — is BE Slice C. A line
 * therefore renders its action label with the click disabled and says why, in
 * words, on the line. That is a visible, testable state; a button that 404s is
 * not.
 *
 * When a Slice C endpoint lands, its `kind` is added here and nowhere else.
 */
export const PERFORMABLE_ACTION_KINDS: ReadonlySet<string> = new Set<string>();

export function isActionPerformable(kind: string): boolean {
  return PERFORMABLE_ACTION_KINDS.has(kind);
}

/** The one action kind the FE *does* serve today, in place, without an endpoint. */
export const ATTACH_ACTION_KINDS: ReadonlySet<string> = new Set([
  // services/atlas_doubt.py::doubt_recommendations — "attach the quotation /
  // contract / delivery note and I will compare it".
  "attach_witness_document",
  // services/atlas_recon.py — "open this invoice against their statement".
  "open_invoice_against_statement",
]);

/**
 * What the Verify affordance tells the user to do (D47, 2026-09-18).
 *
 * **FE Gap 640 closed by changing the promise, not the plumbing.** The gap
 * recorded that Verify seeds its question but cannot attach the document,
 * because `POST /chat/sessions/{id}/attachments` takes an uploaded file and has
 * no by-id path for a document the tenant already holds. The founder ruled that
 * the line stops implying ATLAS attaches anything and says plainly that the
 * user attaches it in chat and compares there. **Neither endpoint proposed in
 * that gap entry was built**, and re-uploading a second copy of the customer's
 * own document to make the promise look kept was rejected outright.
 *
 * The backend holds the same rule as code, not as phrasing: a question naming a
 * `document_id` must tell the user to attach it, and no question may claim the
 * document is already attached — `assert_verify_does_not_promise_attachment()`
 * in `services/atlas_contract.py`, run by `validate_recommendation()` on every
 * line before it reaches the wire.
 */
export const VERIFY_ATTACH_HINT =
  "Attach the document in chat and compare it there — I do not attach it for you.";

/**
 * The deep link the Verify affordance follows (spec §2, D24, D47).
 *
 * `/chat?seed=…` opens chat with the question already in the composer, and the
 * question itself now begins with the attach instruction (BE §16). The document
 * reference still rides along as `verify_document_id` so the line can name
 * *which* document; nothing attaches it, and nothing pretends to.
 */
export function verifyChatHref(line: AtlasRecommendation): string {
  const params = new URLSearchParams({ seed: line.verify.question });
  if (line.verify.document_id) params.set("verify_document_id", line.verify.document_id);
  return `/chat?${params.toString()}`; // hardcode-ok: this app's own route and its query string, not a rendered figure — no number passes through here
}

// -----------------------------------------------------------------------------
// Calls
// -----------------------------------------------------------------------------

/** `GET /api/atlas/lines` → the work screen's whole payload. */
export async function fetchAtlasLines(): Promise<AtlasLinesResponse> {
  const { data } = await apiClient.get<AtlasLinesResponse>("/atlas/lines");
  return data;
}

/**
 * `POST /api/atlas/lines/{id}/dismiss` → this line is handled, for good (D49).
 *
 * **The FE does no dismissal filtering.** The dismissal store is consulted
 * server-side, in `routers/atlas.py`, before the response is assembled — a
 * dismissed line is absent from the payload, not flagged in it. So the only
 * correct thing to do after this resolves is re-read `GET /atlas/lines` and
 * render what comes back. Hiding the row client-side would be a second, weaker
 * copy of the backend's rule, which is the copy that eventually disagrees
 * (the same reasoning as `visible_to()` in the capability filter above).
 *
 * Idempotent on the backend: a repeat click from a stale screen writes no
 * second row. `created` says which happened and is not rendered anywhere today.
 */
export async function dismissAtlasLine(
  recommendationId: string
): Promise<{ recommendation_id: string; dismissed: boolean; created: boolean }> {
  const { data } = await apiClient.post(
    `/atlas/lines/${encodeURIComponent(recommendationId)}/dismiss`
  );
  return data;
}

/** `POST /api/atlas/recon` → §6's four groups for one attached statement. */
export async function reconcileStatement(
  documentId: string,
  vendorName?: string
): Promise<AtlasReconResponse> {
  const { data } = await apiClient.post<AtlasReconResponse>("/atlas/recon", {
    document_id: documentId,
    ...(vendorName ? { vendor_name: vendorName } : {}),
  });
  return data;
}

/** The four groups in the order §6 names them, with the copy the screen shows. */
export const RECON_GROUP_ORDER: ReadonlyArray<{
  key: keyof AtlasReconGroups;
  title: string;
}> = [
  { key: "matched", title: "Matched" },
  { key: "they_show_we_do_not", title: "They show, we do not" },
  { key: "we_show_they_do_not", title: "We show, they do not" },
  { key: "amount_differs", title: "Amount differs" },
  { key: "unmatchable", title: "Could not be read" },
];
