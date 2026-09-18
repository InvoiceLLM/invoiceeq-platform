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

/**
 * `Lever` — one thing a person could do that closes the forecast gap (BE §7.5,
 * D15, task 34.9).
 *
 * `amount_rendered` is a string the server formatted, like every other number
 * here. There is no `value` on purpose: the sum of three levers is not a
 * meaningful figure, and a number a client can add up is one it adds up.
 *
 * `target_id` is nullable because one lever names nothing — "it resolves itself
 * if they pay on time" is a statement about money already expected, not an
 * action. **None of these is a button.** BE §5.3: ATLAS never moves money, so a
 * lever is something the user goes and does.
 */
export interface AtlasLever {
  kind: string;
  label: string;
  target_id?: string | null;
  amount_rendered: string;
}

/**
 * `Forecast` — a date, a number, and the actions that close the gap (BE §7.5).
 *
 * **`assumption` is required, not optional**, and this app always renders it.
 * "On-time payment and historical behaviour are different numbers, and a user
 * making a decision needs to know which they are looking at." A forecast shown
 * without its assumption is the half of the promise that is easy to drop.
 */
export interface AtlasForecast {
  /** ISO date. Formatted for display, never compared or arithmetic'd. */
  on_date: string;
  shortfall_rendered: string;
  assumption: string;
  levers: AtlasLever[];
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
  /** Present only on a shortfall warning (BE task 34.9, §7.5). */
  forecast?: AtlasForecast | null;
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
  /** Ranked by the server since BE 34.7f — money at stake x how soon it stops
   *  being fixable (BE §7.3, D30). **This app never re-sorts it.** A client-side
   *  sort would be a second ranking, and the second one is the one that
   *  disagrees; it would also be arithmetic, which §2 forbids outright. */
  lines: AtlasRecommendation[];
  doubt_checks_run: number;
  doubt_checks_skipped: number;
  /** How many lines sit above the fold (D30). **A display hint, not a
   *  truncation** — `lines` is complete, and everything below the cut is one
   *  click away under "show everything". ATLAS ranks; it does not hide. */
  rank_cut: number;
  /** BE §2.2 / D20: the Admin's view of work other grant-holders are handling,
   *  one row per area. Empty for everybody else. The lines these rows stand for
   *  are **in `lines`**, which is why expanding one needs no second request. */
  areas: AtlasAreaRow[];
}

/** One collapsed area row (BE §2.2, D20) — "Corrections — 34 pending, …". */
export interface AtlasAreaRow {
  capability: AtlasCapability;
  label: string;
  count: number;
  untouched: number;
  age_unknown: number;
  reason: string;
  /** The server's sentence, printed as sent. This app composes none of it —
   *  the counts in it are the server's, for the same reason every figure is. */
  headline: string;
  line_ids: string[];
}

/** `GET /api/atlas/actions/kinds` — what the backend can actually perform. */
export interface AtlasActionKinds {
  performable: string[];
  suggest_only: string[];
  dispositions: Record<string, string>;
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
 * What this app can perform **before the backend has told it anything**.
 *
 * **Still empty, and still the honest value.** BE 34.7 made two kinds real
 * (`resolve_invoice`, `retry_ingestion_source`, D50/D51) — and this app learns
 * that from `GET /atlas/actions/kinds` at runtime, not from a constant edited to
 * match. The rule Slice B encoded survives: a button is never enabled ahead of
 * its endpoint, and the strongest form of that rule is that this side holds no
 * opinion at all until the server states one.
 *
 * So this set is the **fallback while the read is in flight or has failed**. A
 * screen that cannot reach the backend renders every action disabled, which is
 * the correct answer to "can I do this right now?" when the answer is unknown.
 */
export const PERFORMABLE_ACTION_KINDS: ReadonlySet<string> = new Set<string>();

/**
 * Whether `kind` can be performed, given what the backend said it can do.
 *
 * `known` is the server's list. Omitting it is the pre-read state and answers
 * `false` for everything — see `PERFORMABLE_ACTION_KINDS` above on why that is
 * the right failure direction.
 */
export function isActionPerformable(
  kind: string,
  known: ReadonlySet<string> = PERFORMABLE_ACTION_KINDS
): boolean {
  return known.has(kind);
}

/**
 * Where a suggest-only or navigation kind goes (BE D50, task 34.7e).
 *
 * **These are destinations, never writes, and the backend refuses them as
 * writes** (409 from `POST /atlas/lines/{id}/act`). D50's reasoning is that the
 * blast radius of being wrong does not stay local: a wrong correction teaches a
 * rule that misfires on every future invoice from that vendor, and a wrong
 * requeue spends pipeline work nobody asked for. So ATLAS resolves the line to
 * the place where a person decides, and the person decides.
 *
 * `null` means the kind has no destination — it is an instruction to the user
 * (`attach_witness_document` since D47, `request_missing_invoices`) and the line
 * already says what to do.
 *
 * **The destinations now FILTER (FE Gap 702, 2026-09-18).** They previously did
 * not, and the reason recorded then still governs how this was fixed: a query
 * string this app appends and no page reads is the F33/F22 seam in miniature.
 * So `app/invoices/page.tsx` was changed to read `status` and `vendor` off the
 * URL **in the same change** that started sending them, and
 * `tests/unit/atlas-destinations.test.tsx` asserts the two halves against each
 * other rather than each against its own idea of the parameter name.
 *
 * Which parameter each kind sends is decided by **what its emitter actually
 * selected**, not by what reads well:
 *
 * - `requeue_invoices` — `services/atlas_skills.py::_stuck_in_processing` selects
 *   `inv.status == "PROCESSING"` past a cutoff, so the stuck list is
 *   `?status=PROCESSING`. The hours-since-enqueue half is **not** expressible as
 *   a list filter and is deliberately not faked: the destination is a superset of
 *   the line's invoices, and the line already says how many of them are stuck.
 * - `review_unlisted_invoices` — `services/atlas_recon.py` sets `target_id` to the
 *   **vendor**, and the invoices in question are that vendor's, so `?vendor=`.
 *   `GET /invoices` filters on `vendor_name` already.
 *
 * **What is NOT sent, and why:** both kinds carry `params.invoice_ids`, an exact
 * set. `GET /invoices` has no id-set filter, so passing one would be inventing a
 * parameter the backend never reads — the same defect this function was flagged
 * for in the first place. The filter is therefore the narrowest one both ends
 * genuinely support, and no narrower.
 */
export function actionDestination(line: AtlasRecommendation): string | null {
  const id = encodeURIComponent(line.action.target_id);
  switch (line.action.kind) {
    // The field the correction is about lives on the invoice's review screen,
    // which is where a Trainer applies it — with the document beside it.
    case "apply_field_correction":
    case "open_field_review":
      return `/invoices/review/${id}`; // hardcode-ok: this app's own route, no figure in it
    case "requeue_invoices":
      // hardcode-ok: this app's own route and a status literal from the
      // emitter's own filter — no figure passes through here
      return `/invoices?${INVOICE_STATUS_PARAM}=${STUCK_INVOICE_STATUS}`;
    case "review_unlisted_invoices":
      // hardcode-ok: this app's own route; `id` is the vendor name the recon
      // emitter put in `target_id`, never a figure
      return `/invoices?${INVOICE_VENDOR_PARAM}=${id}`;
    case "open_upcoming_payments":
      return "/dashboard"; // hardcode-ok: this app's own route, no figure in it
    default:
      return null;
  }
}

/**
 * The two query parameters `/invoices` reads (FE Gap 702).
 *
 * **Exported so both ends of the seam name the same string.** The whole defect
 * class filed as FE Gap 702 is a parameter one side sends and the other does not
 * read, and two string literals that happen to match today are how that starts.
 * `app/invoices/page.tsx` imports these; so does the test that checks them.
 */
export const INVOICE_STATUS_PARAM = "status";
export const INVOICE_VENDOR_PARAM = "vendor";

/**
 * What "stuck" means, as the backend's own emitter defines it.
 *
 * `services/atlas_skills.py::_stuck_in_processing` filters `status ==
 * "PROCESSING"`. This constant exists so that if the backend ever changes what
 * stuck means, the grep that finds this line finds the FE half too.
 */
export const STUCK_INVOICE_STATUS = "PROCESSING";

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

/**
 * `Orientation` — what a workspace with no history is told (BE §7.1, task 34.12).
 *
 * **Day one is comprehension, not findings.** Almost everything ATLAS does needs
 * history, so its first month is its weakest — and that is the month a customer
 * decides whether it was worth buying. The answer is not to fake findings; it is
 * to teach the working relationship and **state plainly what ATLAS cannot do
 * yet and when it will be able to** (part 3, the one that matters).
 *
 * `needed` is the server's answer to "has this workspace seen an invoice yet".
 * It is not an onboarding flag and there is nothing to dismiss: D25 is "teach
 * once, then keep teaching in place", so this disappears when there is real work
 * to show instead.
 */
export interface AtlasOrientationPart {
  key: string;
  title: string;
  body: string;
}

export interface AtlasOrientation {
  needed: boolean;
  capabilities: AtlasCapability[];
  parts: AtlasOrientationPart[];
  /** Real work that needs no history at all, so "comprehension, not findings"
   *  does not read as "nothing until next month". */
  day_one_finds: string[];
  /** An offer, never a gate — everything works without it. */
  historical_import_offer: string;
}

/** `GET /api/atlas/orientation` → the cold-start content for this caller. */
export async function fetchAtlasOrientation(): Promise<AtlasOrientation> {
  const { data } = await apiClient.get<AtlasOrientation>("/atlas/orientation");
  return data;
}

/**
 * `POST /api/atlas/missed` → "you missed this" (BE task 34.14, D34).
 *
 * **The only false-negative detector there is.** A false positive is cheap and
 * visible; a false negative is real money and invisible — no feedback, no
 * correction, no signal. D34 ruled that the user reports it, and that
 * under-reporting is accepted rather than solved.
 *
 * The description is sent exactly as typed. The backend stores it unedited and
 * turns it into a memory rule the workspace can read — paraphrasing it anywhere
 * along that path would be the product editing its own report card.
 */
export async function reportMissed(input: {
  entityKind: string;
  entityId: string;
  description: string;
}): Promise<{ id: string; rule: { id: string; text: string } }> {
  const { data } = await apiClient.post("/atlas/missed", {
    entity_kind: input.entityKind,
    entity_id: input.entityId,
    description: input.description,
  });
  return data;
}

/**
 * `GET /api/atlas/actions/kinds` → what the backend can actually perform.
 *
 * **Read at runtime rather than transcribed as a constant** (BE 34.7d). The
 * empty `PERFORMABLE_ACTION_KINDS` that shipped in Slice B was an honesty
 * mechanism: a button must never be enabled ahead of its endpoint. A hand-edited
 * list on this side would be a second copy of a backend fact, and a copy is
 * exactly what lets the two drift the day a kind is removed or an endpoint is
 * turned off. So the server says, every time the screen opens.
 */
export async function fetchActionKinds(): Promise<AtlasActionKinds> {
  const { data } = await apiClient.get<AtlasActionKinds>("/atlas/actions/kinds");
  return data;
}

/** What one `POST /api/atlas/lines/{id}/act` answered. */
export interface AtlasActResult {
  recommendation_id: string;
  kind: string;
  target_id: string;
  performed: boolean;
  /** The outcome sentence, or the refusal. Printed as sent. */
  summary: string;
  detail: Record<string, unknown>;
}

/**
 * `POST /api/atlas/lines/{id}/act` → perform this line's action (BE 34.7).
 *
 * **Two kinds only** (D50/D51). Anything else is refused 409 by the backend
 * with the reason, and this app does not try: `isActionPerformable()` gates the
 * button on the server's own list, and a suggest-only line renders a link to
 * `actionDestination()` instead. The 409 is the backstop for the case where this
 * screen is stale, not the normal path.
 *
 * **The caller re-reads afterwards**, exactly as the dismiss click does: the
 * line that was just acted on is recomputed on the next open (D38) and the
 * server decides whether it is still work. Splicing it out locally would be this
 * app holding an opinion about a record it did not write.
 */
export async function actOnAtlasLine(
  line: AtlasRecommendation
): Promise<AtlasActResult> {
  const { data } = await apiClient.post<AtlasActResult>(
    `/atlas/lines/${encodeURIComponent(line.id)}/act`,
    {
      kind: line.action.kind,
      target_id: line.action.target_id,
      params: line.action.params,
    }
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

// -----------------------------------------------------------------------------
// What ATLAS remembers — BE 34.10 (§7.2, D31, D40, D12) · FE Gap 700
// -----------------------------------------------------------------------------

/**
 * One lesson ATLAS holds, in the words it was given in (BE §7.2).
 *
 * **D40 bounds what can ever appear here, and the bound is the point.** A vendor
 * baseline — "4× their usual ₹40–60k across 14 invoices" — is derived at check
 * time and thrown away (D39); it is NOT a memory rule and must never be listed
 * as one. Offering to "edit" a figure recomputed from the customer's own
 * invoices would invite a user to correct something that will be correct again
 * the moment the invoices are. This list is only what ATLAS was **told**
 * (`source: "told"`, `"missed"`) or what a user **agreed** it should remember,
 * which is the only part that can be silently wrong for months.
 *
 * `source` and `origin_ref` are the server's provenance and are read-only here:
 * a client that could name its own provenance could label a lesson it invented
 * as one the user gave.
 */
export interface AtlasMemoryRule {
  id: string;
  text: string;
  source: string;
  origin_ref?: string | null;
  /** `false` is a rule kept and switched off — a different act from deleting it. */
  active: boolean;
  created_by: string;
  created_at: string;
  updated_at: string;
}

/**
 * D12's noise pruning, as a **suggestion that never wrote itself**.
 *
 * "This alert has fired 40 times and you dismissed it 40 times — remove it?"
 * The backend counts and offers; accepting is the user calling `addMemoryRule()`
 * with `text`. Writing it automatically would be the silent write BE §5.3
 * forbids, arriving through the door marked "learning".
 *
 * `count` is the server's number and is printed, never compared or totalled.
 */
export interface AtlasNoiseSuggestion {
  family: string;
  description: string;
  count: number;
  text: string;
}

/**
 * `GET /api/atlas/memory` — the two lists, deliberately not flattened.
 *
 * A rule is something a person put there; a suggestion is arithmetic over
 * dismissals nobody has agreed to yet. Merging them would make the second look
 * like the first, which is exactly the confusion §5.3's "never writes silently"
 * exists to prevent.
 */
export interface AtlasMemoryResponse {
  rules: AtlasMemoryRule[];
  noise_suggestions: AtlasNoiseSuggestion[];
}

/** `GET /api/atlas/memory` → every rule (including switched-off ones) and D12's offers. */
export async function fetchAtlasMemory(): Promise<AtlasMemoryResponse> {
  const { data } = await apiClient.get<AtlasMemoryResponse>("/atlas/memory");
  return data;
}

/**
 * `POST /api/atlas/memory` → tell ATLAS something, in your own words.
 *
 * The source is the backend's to set (`told`) and is deliberately not a field on
 * this call. Accepting a D12 suggestion is this same call with the suggestion's
 * own sentence — the user agreeing is what turns an offer into a rule.
 */
export async function addMemoryRule(text: string): Promise<AtlasMemoryRule> {
  const { data } = await apiClient.post<AtlasMemoryRule>("/atlas/memory", { text });
  return data;
}

/**
 * `PATCH /api/atlas/memory/{id}` → correct a lesson, or switch it off.
 *
 * Both fields are optional and they are different acts: `text` rewrites what the
 * rule says, `active: false` keeps what it said and stops it counting.
 */
export async function editMemoryRule(
  ruleId: string,
  patch: { text?: string; active?: boolean }
): Promise<AtlasMemoryRule> {
  const { data } = await apiClient.patch<AtlasMemoryRule>(
    `/atlas/memory/${encodeURIComponent(ruleId)}`,
    patch
  );
  return data;
}

/**
 * `DELETE /api/atlas/memory/{id}` → **the row goes.**
 *
 * Not a soft delete, not a `deleted_at`, not an archive, and nothing here hides
 * a row the server still holds. §7.2's own argument is the reason: a wrong
 * lesson that cannot be found haunts the system forever, and a retained-but-
 * hidden rule is the definition of one that cannot be found. The caller re-reads
 * afterwards rather than splicing, so what the list shows is what Postgres has.
 *
 * Answers 204 with no body.
 */
export async function deleteMemoryRule(ruleId: string): Promise<void> {
  await apiClient.delete(`/atlas/memory/${encodeURIComponent(ruleId)}`);
}

// -----------------------------------------------------------------------------
// What ATLAS did — BE 34.7c (§5.3) · FE Gap 701
// -----------------------------------------------------------------------------

/**
 * One row of "what ATLAS did", attributed and timestamped (BE §5.3).
 *
 * **`succeeded: false` is a first-class row, not an error.** A refusal — the
 * 409 a suggest-only kind gets, carrying D50's reasoning, or a 403, or the
 * underlying endpoint's own 422 — is written to this log before the caller is
 * answered. A list holding only successes would answer "did ATLAS touch this
 * invoice?" with a confident no on exactly the occasions somebody is asking
 * because something looks wrong.
 *
 * `summary` is the server's sentence — the outcome, or the refusal in the words
 * the ruling is stated in. Printed as sent, like every other string here.
 */
export interface AtlasActionLogEntry {
  id: string;
  recommendation_id: string;
  kind: string;
  target_id: string;
  succeeded: boolean;
  summary: string;
  /** Who clicked. BE §2.2: the log is tenant-wide, and this is what makes that readable. */
  user_id: string;
  /** ISO timestamp. Displayed, never compared or differenced. */
  performed_at: string;
}

export interface AtlasActionLogResponse {
  /** Newest first, ordered by the server. **This app never re-sorts it.** */
  entries: AtlasActionLogEntry[];
}

/**
 * `GET /api/atlas/actions` → what ATLAS did in this workspace.
 *
 * **Tenant-wide and not capability-filtered**, both by the backend's decision
 * (BE §17, `get_atlas_actions`): this is a record of writes, not a work queue,
 * and a record with rows missing is not a record.
 */
export async function fetchAtlasActions(): Promise<AtlasActionLogResponse> {
  const { data } = await apiClient.get<AtlasActionLogResponse>("/atlas/actions");
  return data;
}
