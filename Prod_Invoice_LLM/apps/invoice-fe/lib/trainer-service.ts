/**
 * AI Trainer Sandbox Service Layer & Data Models (Feature 6)
 *
 * FOR MANAGERS & DEVELOPERS:
 * This module defines the core data contracts and the API service layer for the AI Trainer
 * Interactive Sandbox. It talks to the live FastAPI backend through this app's own
 * same-origin proxy routes under `/api/trainer/*` (see app/api/trainer/**), which forward
 * server-side to the backend `/trainer/*` endpoints.
 *
 * It supports all three rule scopes from feature_6_trainer.md & feature_10_trainer.md:
 *   1. "global": Tenant-wide, vendor-agnostic rules (e.g. VAT handling)
 *   2. "existing_vendor": Refine rules for a vendor with production history (seeds from a production invoice)
 *   3. "new_vendor": Cold-start rules for a brand new vendor (seeds from an uploaded sample PDF)
 */

import { apiClient } from "./apiClient";

/**
 * 3-Way Rule Scope Selector Types
 * - 'global': Applies tenant-wide to all vendors
 * - 'existing_vendor': Applies to a specific vendor with past invoices
 * - 'new_vendor': Cold-start setup for a brand new vendor
 */
export type TrainerScope = "global" | "existing_vendor" | "new_vendor";

/**
 * Production Vendor selection option for Scope #2 (Existing Vendor)
 */
export interface VendorOption {
  id: string;
  name: string;
  invoiceCount: number;
  sampleInvoiceId: string;
  sampleFileName: string;
  samplePdfUrl: string;
}

/**
 * Coordinate bounding box for visual grounding highlights on the PDF viewer canvas
 */
export interface BoundingBox {
  page: number;
  x: number;
  y: number;
  width: number;
  height: number;
}

/**
 * Extracted invoice variable schema representation (e.g. invoice_number, subtotal, tax_amount)
 */
export interface ExtractedVariable {
  id: string;
  key: string;
  label: string;
  value: string;
  confidence: number; // Confidence score between 0.0 and 1.0
  isCorrected?: boolean; // Flagged true when updated via user chat rule correction
  boundingBox?: BoundingBox;
}

/**
 * Conversational message bubble in the Trainer chat panel
 */
export interface ChatMessage {
  id: string;
  sender: "user" | "assistant";
  text: string;
  timestamp: string;
  suggestedRule?: string; // Highlighting newly registered rule candidate
  updatedVariables?: Partial<Record<string, string>>;
}

/**
 * Historical rule template version record for auditability & rollback (Task 6.7)
 */
export interface RuleVersion {
  id: string;
  version: number;
  scope: TrainerScope;
  vendorName?: string;
  rules: string[];
  changedBy: string;
  changedAt: string;
  isCurrent?: boolean;
  templateId?: string; // Parent template id — needed to target the rollback endpoint
}

/**
 * Full state representation of an active Trainer sandbox session
 */
export interface TrainerSession {
  sessionId: string;
  scope: TrainerScope;
  vendorName?: string;
  fileName?: string;
  pdfUrl?: string;
  createdAt: string;
  variables: ExtractedVariable[];
  activeRules: string[];
  chatHistory: ChatMessage[];
  sessionMode?: "qa_test" | "rule_creation";
}

/**
 * Result of committing a session's rules to the template registry (Task 6.6 / 10.6)
 */
export interface CommitResult {
  scope: TrainerScope;
  vendorName?: string;
  version: number;
  rules: string[];
  reauditQueued: boolean;
}

/**
 * Normalises a raw backend session payload into a well-formed TrainerSession.
 * The backend already returns the camelCase `TrainerSession` shape; this just guards
 * against missing arrays / nulls so the UI never crashes on a partial response.
 */
function normalizeSession(raw: any): TrainerSession {
  return {
    sessionId: raw?.sessionId,
    scope: raw?.scope,
    vendorName: raw?.vendorName ?? undefined,
    fileName: raw?.fileName ?? undefined,
    pdfUrl: raw?.pdfUrl ?? undefined,
    createdAt: raw?.createdAt,
    variables: Array.isArray(raw?.variables) ? raw.variables : [],
    activeRules: Array.isArray(raw?.activeRules) ? raw.activeRules : [],
    chatHistory: Array.isArray(raw?.chatHistory) ? raw.chatHistory : [],
    sessionMode: raw?.sessionMode === "qa_test" ? "qa_test" : "rule_creation",
  };
}

/**
 * Service API abstraction layer — connects to the backend FastAPI trainer router
 * through this app's `/api/trainer/*` proxy routes.
 */
export const trainerService = {
  /**
   * Fetches tenant vendors for the Scope #2 (Existing Vendor) dropdown picker.
   * GET /api/trainer/vendors
   */
  async getTenantVendors(): Promise<VendorOption[]> {
    const { data } = await apiClient.get("/trainer/vendors");
    return Array.isArray(data) ? data : [];
  },

  /**
   * Initializes a new Trainer session based on the chosen scope.
   *   - Global:          POST /api/trainer/sessions/global            (Task 10.2)
   *   - Existing Vendor: POST /api/trainer/sessions/from-production   (Task 10.3)
   *   - New Vendor:      POST /api/trainer/upload                     (Task 10.4)
   *
   * For upload-based scopes (New Vendor, and Global-with-PDF), the browser already holds
   * the File, so we show it via a local object URL — the backend does not serve transient
   * training PDFs. Existing-Vendor sessions use the backend-provided invoice PDF URL.
   */
  async startSession(scope: TrainerScope, vendorName?: string, file?: File): Promise<TrainerSession> {
    if (scope === "existing_vendor") {
      if (!vendorName) {
        throw new Error("A vendor must be selected for the Existing Vendor scope.");
      }
      const { data } = await apiClient.post("/trainer/sessions/from-production", null, {
        params: { vendor_name: vendorName },
      });
      return normalizeSession(data);
    }

    if (scope === "new_vendor") {
      if (!file) {
        throw new Error("A sample PDF is required to start a New Vendor session.");
      }
      const form = new FormData();
      form.append("file", file);
      const { data } = await apiClient.post("/trainer/upload", form);
      const session = normalizeSession(data);
      session.pdfUrl = URL.createObjectURL(file);
      session.fileName = file.name;
      return session;
    }

    // scope === "global": chat-only, or optionally grounded on an uploaded PDF.
    const form = new FormData();
    if (file) form.append("file", file);
    const { data } = await apiClient.post("/trainer/sessions/global", form);
    const session = normalizeSession(data);
    if (file) {
      session.pdfUrl = URL.createObjectURL(file);
      session.fileName = file.name;
    }
    return session;
  },

  /**
   * Sends a natural-language rule correction and returns the re-extracted session.
   * POST /api/trainer/sessions/{id}/chat (Task 10.5)
   */
  async sendChatMessage(
    session: TrainerSession,
    userMessageText: string
  ): Promise<{ updatedSession: TrainerSession; newRuleCreated?: string }> {
    const { data } = await apiClient.post(`/trainer/sessions/${session.sessionId}/chat`, {
      content: userMessageText,
    });

    const updatedSession = normalizeSession(data?.updatedSession);
    // Preserve the client-side PDF preview across turns (object URLs live only in the browser).
    updatedSession.pdfUrl = updatedSession.pdfUrl ?? session.pdfUrl;
    updatedSession.fileName = updatedSession.fileName ?? session.fileName;

    return {
      updatedSession,
      newRuleCreated: data?.newRuleCreated ?? undefined,
    };
  },

  /**
   * Commits the session's active rules to the template registry (Global or vendor scope),
   * writing a new version and queuing a background re-audit where applicable.
   * POST /api/trainer/sessions/{id}/commit (Task 10.6 / 10.7)
   */
  async commitSession(session: TrainerSession): Promise<CommitResult> {
    const { data } = await apiClient.post(`/trainer/sessions/${session.sessionId}/commit`);
    return {
      scope: data?.scope,
      vendorName: data?.vendor_name ?? undefined,
      version: data?.version,
      rules: data?.rules?.constraints ?? [],
      reauditQueued: Boolean(data?.reaudit_queued),
    };
  },

  /**
   * Fetches the version history for the active template (Global, or the selected vendor).
   * GET /api/trainer/templates/history?scope=&vendor_name=  (Task 10.10)
   */
  async getRuleHistory(scope: TrainerScope, vendorName?: string): Promise<RuleVersion[]> {
    const params: Record<string, string> = { scope };
    if (scope !== "global" && vendorName) {
      params.vendor_name = vendorName;
    }
    const { data } = await apiClient.get("/trainer/templates/history", { params });
    return Array.isArray(data) ? data : [];
  },

  /**
   * Rolls a past rule version back to current (writes a new version + queues re-audit).
   * POST /api/trainer/templates/{templateId}/rollback/{version} (Task 10.10)
   */
  async rollbackTemplate(
    templateId: string,
    version: number
  ): Promise<{ version: number; reauditQueued: boolean }> {
    const { data } = await apiClient.post(`/trainer/templates/${templateId}/rollback/${version}`);
    return {
      version: data?.version,
      reauditQueued: Boolean(data?.reaudit_queued),
    };
  },

  async setSessionMode(
    sessionId: string,
    sessionMode: "qa_test" | "rule_creation"
  ): Promise<TrainerSession> {
    const { data } = await apiClient.put(`/trainer/sessions/${sessionId}/mode`, {
      session_mode: sessionMode,
    });
    return normalizeSession(data?.updatedSession ?? data);
  },
};
