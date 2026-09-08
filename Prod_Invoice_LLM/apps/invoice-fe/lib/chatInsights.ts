// =============================================================================
// FILE: lib/chatInsights.ts
// FEATURE: FE Feature 21 — Business Intelligence (the intelligence bubble),
//          counterpart of BE Feature 30 (§8.3 bubble anatomy, §8.6 runtime).
//
// WHY THIS FILE EXISTS: same reason `lib/chatAttachments.ts` does — the shapes
// and the copy that mirror one backend module live in one place, next to the
// backend symbols they must agree with, and the pure functions are importable
// by both the component and a test without rendering anything.
//
// SHAPES VERIFIED AGAINST THE LIVE BACKEND, NOT THE SPEC. The FE spec's §2 table
// is stale in four ways; the code below follows `apps/invoice-be`:
//
//   1. `AttachmentOut` has NO `insights` field (routers/chat_attachments.py).
//      The block reaches the browser ONLY through `MessageResponse.insights`
//      (routers/chat.py, via `ATTACHMENT_CONTRACT_KEYS`). The spec's
//      `ChatAttachmentSummary.insights?` would never be populated.  -> FE Gap 471
//   2. There is no `GET /chat/attachments/{id}/insights`. The reload path is
//      `GET /chat/insights?attachment_id=...&status=...` returning `InsightOut[]`.
//   3. A finding inside the block carries `finding_key`, NOT the `insight` row
//      id — but `POST /chat/insights/{id}/transition` is keyed by the row id.
//      The bubble therefore resolves finding -> row through `finding_key`
//      (`insightForFinding()` below).  -> FE Gap 472
//   4. The block carries no `insights_version`; only the SSE `insight_update`
//      event and `ChatAttachment.insights_version` do. Staleness is therefore
//      tracked per message on the client (`isStaleInsightUpdate()`).
//
// NO PIN, AND NO INVOICE ACTION (BE Gap 492 / spec §8): nothing in this module
// changes an invoice. `transitionInsight` records the user's own bookkeeping
// about a finding; `discuss` is a read that seeds the composer.
// =============================================================================

import { apiClient } from "@/lib/apiClient";
import { formatCurrency } from "@/lib/utils";

// -----------------------------------------------------------------------------
// Shapes — services/attachment_insights.py
// -----------------------------------------------------------------------------

/** `services/attachment_insights.py::finding()` — one line in the bubble. */
export interface InsightFinding {
  finding_key: string;
  card: string;
  title: string;
  impact_amount?: number | null;
  currency?: string | null;
  /** "high" | "med" | "low" — the backend's own vocabulary, not widened here. */
  confidence: string;
  confidence_reason?: string | null;
  evidence?: Record<string, any> | null;
}

/** `services/attachment_insights.py::InsightCard.as_dict()`. */
export interface InsightCardResult {
  card: string;
  /** "ok" | "skipped" | "blocked" — compute units, not a rendered surface. */
  status: string;
  title?: string;
  figures?: Record<string, number | null>;
  findings?: InsightFinding[];
  evidence?: Record<string, any>;
  reason?: string;
}

/** One entry of `block.checks_not_run`. */
export interface InsightCheckNotRun {
  card: string;
  reason: string;
}

/** `BUBBLE_ACTIONS` — the backend hands the FE the action row as data. */
export interface InsightAction {
  action: string;
  label: string;
  status?: string;
  outcome?: string;
  endpoint?: string;
}

/** `build_insight_block()` — the whole bubble, as `MessageResponse.insights`. */
export interface InsightBlock {
  stage: string;
  doc_type: string;
  doc_type_label?: string;
  attachment_id: string;
  tenant_id?: string;
  currency?: string | null;
  region?: string | null;
  cards: InsightCardResult[];
  findings: InsightFinding[];
  figures?: Record<string, number | null>;
  checks_not_run: InsightCheckNotRun[];
  actions: InsightAction[];
  verdict: string;
  verdict_source?: string;
  generated_at?: string;
}

/** `routers/chat.py::InsightOut` — the lifecycle row behind a finding. */
export interface Insight {
  id: string;
  attachment_id: string;
  session_id?: string | null;
  doc_type: string;
  card: string;
  finding_key: string;
  title: string;
  impact_amount?: number | null;
  currency?: string | null;
  confidence: string;
  confidence_reason?: string | null;
  evidence?: Record<string, any> | null;
  status: string;
  is_open: boolean;
  outcome?: string | null;
  note?: string | null;
  snoozed_until?: string | null;
  created_at: string;
  updated_at: string;
}

/** The SSE payload of `services/insights.py::notify_insight_update()`. */
export interface InsightUpdateEvent {
  session_id?: string | null;
  attachment_id: string;
  insights_version: number;
  message_id?: string | null;
}

// -----------------------------------------------------------------------------
// Rendering rules (§8.3)
// -----------------------------------------------------------------------------

/** §8.3.2: "max 3 shown, rest collapsed". */
export const VISIBLE_FINDING_LIMIT = 3;

/**
 * The block is rendered on its presence alone, exactly as `reconciliation` is —
 * but an EMPTY block (no verdict, no findings, no skipped checks) has nothing to
 * say, and drawing an empty card under a reply is worse than drawing nothing.
 */
export function hasRenderableInsights(block?: InsightBlock | null): boolean {
  if (!block) return false;
  return Boolean(
    (block.verdict || "").trim() ||
      (block.findings || []).length > 0 ||
      (block.checks_not_run || []).length > 0
  );
}

export function splitFindings(block: InsightBlock): {
  shown: InsightFinding[];
  hidden: InsightFinding[];
} {
  const all = block.findings || [];
  return {
    shown: all.slice(0, VISIBLE_FINDING_LIMIT),
    hidden: all.slice(VISIBLE_FINDING_LIMIT),
  };
}

/**
 * Plain-verb confidence copy (§8.2). "med" is the backend's spelling; the user
 * never sees it — and no internal term (tier, delta, 3-way) appears here.
 */
export function confidenceLabel(confidence?: string | null): string {
  switch ((confidence || "").toLowerCase()) {
    case "high":
      return "Sure";
    case "low":
      return "Not sure";
    case "med":
    case "medium":
      return "Fairly sure";
    default:
      return "Fairly sure";
  }
}

export function confidenceTone(confidence?: string | null): "high" | "med" | "low" {
  const value = (confidence || "").toLowerCase();
  if (value === "high") return "high";
  if (value === "low") return "low";
  return "med";
}

/**
 * The impact figure, in the TENANT's currency: the finding's own currency wins,
 * the block's is the fallback, and `formatCurrency` degrades an unknown code
 * rather than throwing. `null` when the finding states no amount — a finding
 * without money is a real finding, not a zero.
 */
export function findingImpact(
  finding: InsightFinding,
  block?: InsightBlock | null
): string | null {
  if (finding.impact_amount === null || finding.impact_amount === undefined) return null;
  return formatCurrency(finding.impact_amount, finding.currency ?? block?.currency ?? null);
}

/**
 * "agreed_vs_billed" -> "agreed vs billed". Card names are internal; this is the
 * only place they become words a user reads.
 */
export function cardLabel(card?: string | null): string {
  return (card || "").replace(/_/g, " ").trim();
}

/**
 * §8.3.3, as ONE line: "Not checked: bank match (no statement on file); ...".
 * Returns null when every check ran, so no line is drawn.
 */
export function checksNotRunLine(block: InsightBlock): string | null {
  const items = block.checks_not_run || [];
  if (items.length === 0) return null;
  const parts = items.map((check) =>
    check.reason ? `${cardLabel(check.card)} (${check.reason})` : cardLabel(check.card)
  );
  return `Not checked: ${parts.join("; ")}`;
}

/**
 * Invoice numbers a finding compared against, for the evidence links. The
 * backend's evidence dicts key these as `invoice_number` (singular, most cards),
 * `invoice_numbers`, or a list of rows under `invoices` / `matched`.
 * De-duplicated and order-preserving.
 */
export function evidenceInvoiceNumbers(finding: InsightFinding): string[] {
  const evidence = (finding.evidence || {}) as Record<string, any>;
  const out: string[] = [];
  const push = (value: any) => {
    const text =
      typeof value === "string" ? value.trim() : value == null ? "" : String(value);
    if (text && !out.includes(text)) out.push(text);
  };
  push(evidence.invoice_number);
  for (const key of ["invoice_numbers", "invoices", "matched"]) {
    const value = evidence[key];
    if (!Array.isArray(value)) continue;
    for (const row of value) {
      if (row && typeof row === "object") push(row.invoice_number);
      else push(row);
    }
  }
  return out;
}

/**
 * Finding -> lifecycle row. Keyed on `finding_key` because the block does not
 * carry the row id (FE Gap 472); `card` is checked too, since `finding_key` is
 * only unique within a card by construction.
 */
export function insightForFinding(
  insights: Insight[] | undefined | null,
  finding: InsightFinding
): Insight | undefined {
  return (insights || []).find(
    (row) => row.finding_key === finding.finding_key && (!row.card || row.card === finding.card)
  );
}

/**
 * SSE ordering guard (§8.6 step 4): an event whose version is not NEWER than the
 * one already drawn is dropped. Redis re-delivery and a reconnect both replay
 * events, and re-fetching on a replay would flash the bubble for no new content.
 */
export function isStaleInsightUpdate(
  event: Pick<InsightUpdateEvent, "insights_version">,
  lastSeenVersion: number | undefined
): boolean {
  if (lastSeenVersion === undefined) return false;
  return Number(event.insights_version) <= Number(lastSeenVersion);
}

// -----------------------------------------------------------------------------
// Endpoints. All same-origin through app/api/**, like every other chat call.
// -----------------------------------------------------------------------------

/**
 * The reload / lifecycle read. NOT `GET /chat/attachments/{id}/insights` — that
 * route does not exist (see the header note). "any status" is expressed by
 * passing `status: null`, which omits the parameter.
 */
export async function fetchAttachmentInsights(
  attachmentId: string,
  options: { status?: string | null } = {}
): Promise<Insight[]> {
  const params: Record<string, string> = { attachment_id: attachmentId };
  if (options.status !== null) params.status = options.status ?? "OPEN";
  const response = await apiClient.get<Insight[]>("/chat/insights", { params });
  return response.data ?? [];
}

/** The History screen's "Open findings" chip (task 21.8). */
export async function fetchOpenInsights(limit = 100): Promise<Insight[]> {
  const response = await apiClient.get<Insight[]>("/chat/insights", {
    params: { status: "OPEN", limit },
  });
  return response.data ?? [];
}

/**
 * Records the user's own bookkeeping about a finding. Information only: the
 * backend docstring for this route states plainly that nothing here reads or
 * writes `Invoice` (Gap 492).
 */
export async function transitionInsight(
  insightId: string,
  payload: { status: string; outcome?: string; note?: string }
): Promise<Insight> {
  const response = await apiClient.post<Insight>(
    `/chat/insights/${insightId}/transition`,
    payload
  );
  return response.data;
}

/** Discuss is a READ. It returns seed text; it never sends a turn. */
export async function fetchInsightDiscussSeed(insightId: string): Promise<string> {
  const response = await apiClient.get<{ seed_text?: string }>(
    `/chat/insights/${insightId}/discuss`
  );
  return response.data?.seed_text ?? "";
}

/** `POST /chat/messages/{id}/insight-feedback` (`InsightFeedbackIn`). */
export async function postInsightFeedback(
  messageId: string,
  payload: {
    vote: "up" | "down";
    card?: string;
    finding_key?: string;
    insight_id?: string;
    reason?: string;
    corrected_text?: string;
  }
): Promise<void> {
  await apiClient.post(`/chat/messages/${messageId}/insight-feedback`, payload);
}
