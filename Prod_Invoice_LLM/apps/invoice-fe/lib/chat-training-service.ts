/**
 * Chat-correction lane service layer — Feature 14 (FE) / Feature 18 (BE).
 *
 * FOR MANAGERS & DEVELOPERS:
 * A thumbs-down on a chat answer used to be signal-only (Gap 54): recorded in
 * `ChatFeedback`, never acted on. It is now the entry point to a triage flow
 * whose defining property is that **the system does the comparison a human
 * shouldn't have to** — if the complaint is "the number is wrong", the backend
 * diffs what the reply said against what is stored, and only asks the human the
 * question a human is actually needed for ("does the PDF agree?").
 *
 * Structurally separate from the extraction lane, on purpose: nothing in this
 * file can touch `ExtractionTemplate.rules["constraints"]`. A chat rule is about
 * how the *answering* agent scopes and filters a question; letting the two share
 * storage is how "the trainer taught chat something odd" and "the trainer taught
 * extraction something odd" became one undiagnosable class of bug.
 *
 * Every call goes through this app's same-origin `/api/chat/*` proxy routes.
 */

import { apiClient } from "./apiClient";

/** The three things a thumbs-down can mean. Backend: `TRIAGE_REASONS`. */
export type TriageReason = "wrong_data" | "wrong_interpretation" | "bad_tone";

/**
 * Which step the flow should open next. The backend decides this — the FE never
 * infers it, because the decision depends on data the FE doesn't have (how many
 * invoices fed the reply, and whether the claimed value matches the stored one).
 *
 *   chat_settings        -> bad tone; goes to the tenant's chat style, not a rule
 *   diff_invoice         -> exactly one invoice fed the reply; diff it directly
 *   pick_invoice         -> several did; ask which one, or "it's the total"
 *   confirm_against_pdf  -> chat matched the DB; only the document can settle it
 *   category_pick        -> a genuine chat-behaviour correction
 *   extraction_flag_missed -> not a chat problem at all; hand off to the Trainer
 */
export type TriageNext =
  | "chat_settings"
  | "diff_invoice"
  | "pick_invoice"
  | "confirm_against_pdf"
  | "category_pick"
  | "extraction_flag_missed";

/**
 * One invoice from the reply's `result_invoice_ids` snapshot (BE Gap 231).
 *
 * An **empty list means "we could not determine the row set"**, never "no
 * invoices were involved" — the backend is explicit about that, and the UI must
 * not present an empty picker as if the answer came from nothing.
 */
export interface TriageInvoice {
  invoiceId: string;
  invoiceNumber?: string | null;
  vendorName?: string | null;
  grandTotal?: number | null;
  currency?: string | null;
  pdfUrl: string;
}

/** One category from the closed chat-rule vocabulary (`services/chat_rules.py`). */
export interface ChatRuleCategory {
  key: string;
  label: string;
  patternLabel: string;
  requiresPattern: boolean;
}

/** The `triage` block a thumbs-down response carries. */
export interface TriageEntryPoint {
  next: TriageNext;
  explanation: string;
  invoices?: TriageInvoice[];
  diffableFields?: string[];
  categories?: ChatRuleCategory[];
  settingsEndpoint?: string;
}

/** The auto-diff result from `POST /chat/messages/{id}/triage`. */
export interface TriageDiff {
  invoiceId: string;
  field: string;
  storedValue: string | null;
  claimedValue: string | null;
  outcome: "match" | "mismatch";
  /**
   * "exact" when the FE supplied what the user saw; "reply_contains_stored_value"
   * when it didn't and the backend fell back to a containment check. Reported
   * distinctly so nothing mistakes the weaker basis for an exact comparison.
   */
  basis: "exact" | "reply_contains_stored_value";
}

export interface TriageDiffResponse {
  diff: TriageDiff;
  next: TriageNext;
  explanation: string;
  categories?: ChatRuleCategory[];
  pdfUrl?: string;
  verdictEndpoint?: string;
}

/**
 * The response to "does the PDF agree with what we stored?".
 *
 * When it doesn't, `redirect` carries everything needed to open the Trainer's
 * extraction flow pre-filled — this is the one place a chat complaint becomes an
 * extraction one, and it is deliberately not treated as a chat correction at
 * all: teaching the answering agent here would paper over bad extracted data
 * with a rule about how to talk about it.
 */
export interface SourceVerdictResponse {
  next: TriageNext;
  explanation: string;
  categories?: ChatRuleCategory[];
  redirect?: {
    invoiceId: string;
    field: string;
    flowDirection: string;
    vendorName: string | null;
    sessionEndpoint: string;
    correctionEndpoint: string;
    alertTypesEndpoint: string;
  };
}

/** `POST /chat/rules/preview` — the literal final rule text, not a paraphrase. */
export interface ChatRulePreview {
  previewToken: string;
  category: string;
  pattern: string;
  ruleText: string;
  explanation: string;
}

/** A committed chat-behaviour rule (`TenantChatRule`). */
export interface ChatRule {
  id: string;
  category: string;
  pattern: string;
  contextText?: string;
  ruleText: string;
  enabled: boolean;
  createdBy?: string;
  createdAt?: string | null;
}

/** Thumbs-down response envelope from `PUT /chat/messages/{id}/feedback`. */
export interface FeedbackResponse {
  success: boolean;
  vote: "up" | "down";
  reason?: TriageReason | null;
  triage?: TriageEntryPoint;
}

export const chatTrainingService = {
  /**
   * Records the vote and, for a thumbs-down, returns the triage entry point in
   * the same round-trip — so the UI never has to make a second call just to
   * discover which question to ask next.
   *
   * `reason` is optional: omitting it preserves the original Gap 54 signal-only
   * contract byte-for-byte, which is what the thumbs-**up** path still does.
   */
  async submitFeedback(
    messageId: string,
    vote: "up" | "down",
    reason?: TriageReason,
    note?: string
  ): Promise<FeedbackResponse> {
    const { data } = await apiClient.put(`/chat/messages/${messageId}/feedback`, {
      vote,
      ...(reason ? { reason } : {}),
      ...(note ? { note } : {}),
    });
    return data;
  },

  /** Clears a previously cast vote. */
  async clearFeedback(messageId: string): Promise<void> {
    await apiClient.delete(`/chat/messages/${messageId}/feedback`);
  },

  /**
   * Step 2 of the wrong-data path: the backend diffs what chat claimed against
   * the stored column. `claimedValue` is what the user saw in the reply — send
   * it when it can be captured, because the fallback (does the stored value
   * appear anywhere in the reply text?) is a strictly weaker basis.
   */
  async triageMessage(
    messageId: string,
    payload: { invoiceId: string; field: string; claimedValue?: string }
  ): Promise<TriageDiffResponse> {
    const { data } = await apiClient.post(`/chat/messages/${messageId}/triage`, {
      invoice_id: payload.invoiceId,
      field: payload.field,
      claimed_value: payload.claimedValue ?? null,
    });
    return data;
  },

  /**
   * Step 3, only reached when chat matched the DB: the human's answer to "does
   * the source document agree?".
   */
  async submitSourceVerdict(
    messageId: string,
    payload: { invoiceId: string; field: string; pdfAgrees: boolean }
  ): Promise<SourceVerdictResponse> {
    const { data } = await apiClient.post(`/chat/messages/${messageId}/triage/source-verdict`, {
      invoice_id: payload.invoiceId,
      field: payload.field,
      pdf_agrees: payload.pdfAgrees,
    });
    return data;
  },

  /** The closed category vocabulary a chat correction is picked from. */
  async getCategories(): Promise<ChatRuleCategory[]> {
    const { data } = await apiClient.get("/chat/rules/categories");
    return Array.isArray(data?.categories) ? data.categories : [];
  },

  /**
   * Preview the proposed chat rule. No LLM is involved on the backend — the
   * rendered text here is literally what will be stored and injected.
   */
  async previewRule(payload: {
    category: string;
    pattern?: string;
    contextText?: string;
  }): Promise<ChatRulePreview> {
    const { data } = await apiClient.post("/chat/rules/preview", {
      category: payload.category,
      pattern: payload.pattern || "",
      context_text: payload.contextText || "",
    });
    return data;
  },

  /**
   * Commit the previewed rule. The token is **required** by the backend (a
   * commit without one is a 400): no silent save straight off a thumbs-down.
   * Requires `can_train`, because a chat rule changes how every future answer
   * for the whole workspace is scoped.
   */
  async commitRule(payload: {
    category: string;
    pattern?: string;
    contextText?: string;
    previewToken: string;
  }): Promise<ChatRule> {
    const { data } = await apiClient.post("/chat/rules/commit", {
      category: payload.category,
      pattern: payload.pattern || "",
      context_text: payload.contextText || "",
      preview_token: payload.previewToken,
    });
    return data;
  },

  /** The tenant's committed chat-behaviour rules. */
  async listRules(): Promise<ChatRule[]> {
    const { data } = await apiClient.get("/chat/rules");
    return Array.isArray(data) ? data : [];
  },

  /** Remove a chat-behaviour rule. Same `can_train` permission as creating one. */
  async deleteRule(ruleId: string): Promise<void> {
    await apiClient.delete(`/chat/rules/${ruleId}`);
  },
};
