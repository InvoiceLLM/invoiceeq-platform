// =============================================================================
// FILE: types/chat.ts
// FEATURE: Feature 5 — Semantic Chat Assistant & SQL Audit Drawer
// REASON ADDED: The chat feature introduces a new set of API shapes that are
//   shared across the proxy route handlers, the useChatSession hook, and every
//   UI component.  Centralising them here means a single source of truth — if
//   the backend payload changes, only this file needs updating.
//   All interfaces mirror the FastAPI response bodies documented in
//   be_features/feature_6_rag.md (run_query_agent response schema).
// =============================================================================

// -----------------------------------------------------------------------------
// Citation
// REASON: The RAG query path returns a list of source chunks used to build the
//   assistant answer.  Each chunk maps back to a specific page of a specific
//   invoice.  CitationPill.tsx consumes this to render clickable source pills.
// -----------------------------------------------------------------------------
export interface Citation {
  invoice_id: string;    // UUID — used to navigate to the audit detail view
  vendor_name: string;   // Displayed as the pill label
  page: number;          // Page within the PDF where the chunk was found — matches backend's CitationResponse.page
  invoice_number?: string; // Optional — used as a human-friendly fallback label
}

// -----------------------------------------------------------------------------
// Attached-document contract (BE Feature 26 Part 2, §P2.6.5 — task H11)
//
// The shapes themselves live in lib/chatAttachments.ts and are re-exported here
// rather than moved. §P2.6.5 asks for them in this file and H10's build note
// says "H11 may re-home them"; re-exporting keeps ONE definition sitting next to
// the caps and copy that mirror the same backend module, while still making
// `@/types/chat` the import everything else uses. The dependency runs one way
// (types/chat.ts → lib/chatAttachments.ts) and is type-only, so there is no
// runtime cycle.
// -----------------------------------------------------------------------------
export type {
  AttachmentCandidate,
  AttachmentClarification,
  AttachmentClarificationIntent,
  AttachmentClarificationOption,
  AttachmentComparison,
  AttachmentComparisonEntry,
  AttachmentConfirmation,
  AttachmentEvidenceSpan,
  AttachmentState,
  ChatAttachmentSummary,
  ComparisonFieldRow,
  SuggestedAction,
} from "@/lib/chatAttachments";

import type {
  AttachmentClarification,
  AttachmentComparison,
  AttachmentConfirmation,
  AttachmentEvidenceSpan,
  SuggestedAction,
} from "@/lib/chatAttachments";

export type ChatJobStatus = "queued" | "processing" | "completed" | "failed";

export interface ChatJobResponse {
  job_id: string;
  message_id: string;
  status: ChatJobStatus;
  created_at?: string;
}

export interface ChatStreamEvent {
  job_id: string;
  status: ChatJobStatus;
  step?: string;
  details?: string | { message?: string; [key: string]: any };
  result?: ChatMessage;
  error?: string;
  timestamp?: string;
}

// -----------------------------------------------------------------------------
// ChatMessage
// REASON: Represents a single turn in the conversation.  The `role` field
//   controls which bubble style is rendered (user = right-aligned dark blue,
//   assistant = left-aligned gradient).  `generated_sql` and `citations` are
//   optional because they are only populated when the backend query agent
//   routes to the SQL or RAG execution paths respectively.
// -----------------------------------------------------------------------------
export interface ChatMessage {
  id: string;
  session_id: string;
  role: "user" | "assistant";
  content: string;

  // Present only when the backend classifier chose the SQL execution path.
  // Rendered inside SqlAuditDrawer.tsx so auditors can verify the query.
  generated_sql?: string | null;

  // Present only when the backend classifier chose the RAG execution path.
  // Rendered as CitationPill buttons below the assistant bubble.
  citations?: Citation[];

  created_at: string; // ISO-8601 — formatted to HH:MM for display

  // Gap 54: this turn's recorded vote, if any. "up" | "down" | null — null
  // (not just absent) is a real, meaningful state: no vote cast yet.
  feedback?: "up" | "down" | null;

  // Gap 280: Asynchronous job queue status & error tracking
  status?: ChatJobStatus;
  job_id?: string;
  error_message?: string;

  // ---------------------------------------------------------------------------
  // Feature 26 Part 2 (§P2.6.4/§P2.6.5, task H11) — the attached-document answer
  // contract. EVERY field is optional, so every message shape that renders today
  // stays valid and nothing about the SQL/RAG/CHAT routes changes.
  //
  // Which turn emits which (verified in agents/query_agent.py, not taken from
  // §P2.8's sketch):
  //   confirmation turn  → attachment_confirmation           (L3257)
  //   comparison answer  → attachment_comparison + suggested_actions (L3327-8)
  //   content branch     → evidence + needs_confirmation      (L3518, L3526)
  //   clarifying turn    → attachment_clarification           (L3199)
  // and never more than one of those groups on the same turn.
  //
  // NOT REACHABLE END TO END YET, and that is a backend gap rather than a
  // frontend one: `routers/chat.py::MessageResponse` (L173) has no field for any
  // of these and the assistant `ChatMessage` row persists only content /
  // generated_sql / citations / result_invoice_ids (L630), so the agent's extra
  // keys are dropped before the HTTP response is built. H12 wires the hook; it
  // does not fix that. See the Gap 379 entry in fe_features_tracker.md.
  // ---------------------------------------------------------------------------

  /** The match-confirmation gate (D4). Its presence is what renders the card. */
  attachment_confirmation?: AttachmentConfirmation;

  /** The deterministic diff table from `compare_reference_to_invoices()` (D5). */
  attachment_comparison?: AttachmentComparison;

  /** 0-3 deep-links (D6). Rendered as links; chat never invokes them. */
  suggested_actions?: SuggestedAction[];

  /** Content branch: verbatim spans from the attached document's own pages. */
  evidence?: AttachmentEvidenceSpan[];

  /**
   * Emitted by the content branch only, and only ever `false` in the live
   * backend today. Treated as "this turn deliberately produced no figures",
   * never as the confirmation card's render condition.
   */
  needs_confirmation?: boolean;
  /**
   * B10/R10. Present only on a `list_reconcile` turn (an advisory document);
   * ABSENT on every other branch, per §P2.8's rule that a key's presence is
   * itself a claim about what ran.
   */
  reconciliation?: AttachmentReconciliation;

  /** The clarifying turn (B2): two choices, no answer, no LLM call behind it. */
  attachment_clarification?: AttachmentClarification;
}

// -----------------------------------------------------------------------------
// ChatSession
// REASON: Represents a conversation thread shown in the left sidebar panel.
//   `title` is auto-derived by the backend from the first user message and
//   is also set optimistically on the frontend after the first send.
//   `message_count` is shown as a secondary label in the thread list.
// -----------------------------------------------------------------------------
export interface ChatSession {
  id: string;
  tenant_id: string;    // Multi-tenant isolation — scoped by the backend automatically
  user_id: string;
  title: string;        // Human-readable thread label (max ~48 chars in the UI)
  message_count: number;
  created_at: string;
  updated_at: string;   // Used to sort sessions (most recently active first)
}

// -----------------------------------------------------------------------------
// Request / Response shapes
// REASON: Explicit request bodies prevent accidental field mismatches when
//   calling apiClient.post().  Response wrappers match the backend envelope
//   structure so the hook can destructure without guessing field names.
// -----------------------------------------------------------------------------

/** POST /chat/sessions — body */
export interface CreateSessionRequest {
  title?: string; // Optional; backend defaults to "New Chat"
}

/** GET /chat/sessions — response: the backend returns a bare array, no wrapper */
export type ListSessionsResponse = ChatSession[];

/** GET /chat/sessions/{id} — response: the backend returns a bare array of
 *  messages (no session object) — routers/chat.py::get_session_messages()
 *  has response_model=list[MessageResponse] */
export type GetSessionResponse = ChatMessage[];

/** POST /chat/sessions/{id}/message — body: backend's MessageCreate requires `content` */
export interface SendMessageRequest {
  content: string; // Raw user text; the backend handles classification

  // Feature 26 (§P2.6.5): when present, `post_chat_message()` hands it to
  // `run_query_agent()` and the deterministic pre-route gate (D4) takes the
  // attached-document branch — `classify_query()` is never called. Optional, so
  // every ordinary turn is byte-identical to what it sends today. H12 is what
  // actually populates it; the field is declared here so the hook has a type to
  // fill rather than widening the request shape ad hoc.
  attachment_id?: string;
}

/** POST /chat/sessions/{id}/message — response: returns either ChatJobResponse (202 async) or ChatMessage (sync) */
export type SendMessageResponse = ChatMessage | ChatJobResponse;

/**
 * B10/R10 — the `list_reconcile` answer shape (BE amendment B8).
 *
 * An ADVISORY document (statement of account, remittance advice) is a list of
 * pointers at other documents, so it is answered by reconciliation rather than
 * by the field-by-field diff `AttachmentComparison` carries. Mirrors
 * `services/document_comparison.py::reconcile_referenced_documents()`.
 *
 * Amounts are Decimal-derived STRINGS from the backend and must be rendered as
 * given -- never `Number()`-parsed, which would reintroduce the float error the
 * backend went to some trouble to avoid.
 */
export type ReconciliationOutcome =
  | "found_matching"
  | "amount_mismatch"
  | "status_mismatch"
  | "not_found";

export interface ReconciliationReference {
  doc_number?: string | null;
  invoice_id?: string | null;
  outcome: ReconciliationOutcome;
  /** Decimal-derived string. Null when either side did not state an amount. */
  delta?: string | null;
  stated_amount?: string | number | null;
  invoice_amount?: string | number | null;
  /** What THEIR document claims -- never our finding. */
  stated_status?: string | null;
  invoice_status?: string | null;
}

export interface ReconciliationDeduction {
  kind?: string | null;
  amount?: string | number | null;
  currency?: string | null;
  reference?: string | null;
}

export interface UnreferencedInvoice {
  invoice_id: string;
  invoice_number?: string | null;
  grand_total?: string | number | null;
}

export interface AttachmentReconciliation {
  mode: "list_reconcile";
  party_name?: string | null;
  references: ReconciliationReference[];
  /** Reported per kind and NEVER netted into one figure. */
  deductions: ReconciliationDeduction[];
  /** The reverse direction: open invoices of ours their document omits. */
  unreferenced_invoices: UnreferencedInvoice[];
}
