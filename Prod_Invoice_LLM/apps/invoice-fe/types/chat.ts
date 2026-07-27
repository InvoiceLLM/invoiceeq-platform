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
}

/** POST /chat/sessions/{id}/message — response: the backend returns the
 *  assistant ChatMessage directly (MessageResponse), not wrapped in an envelope. */
export type SendMessageResponse = ChatMessage;
