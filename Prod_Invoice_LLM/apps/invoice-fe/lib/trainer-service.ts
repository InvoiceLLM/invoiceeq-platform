/**
 * AI Trainer Service Layer & Data Models
 *
 * Feature 14 (FE) / Feature 18 (BE) — alert-anchored training.
 *
 * FOR MANAGERS & DEVELOPERS:
 * This module defines the data contracts and API service layer for the AI Trainer.
 * It talks to the live FastAPI backend through this app's own same-origin proxy
 * routes under `/api/trainer/*` (see app/api/trainer/**), which forward
 * server-side to the backend `/trainer/*` endpoints. The browser never calls the
 * backend directly.
 *
 * WHAT CHANGED IN FEATURE 14 (and why the old shape is gone)
 * ----------------------------------------------------------
 * The previous version of this file had three scopes -- `global`,
 * `existing_vendor` and `new_vendor` -- and one way to create a rule: send free
 * text to `POST /trainer/sessions/{id}/chat` and let an LLM turn it into a
 * constraint. The backend removed both:
 *
 *   * `POST /trainer/sessions/global` and `POST /trainer/sessions/from-production`
 *     now return **410 Gone**. Global-scope rule *creation* is removed entirely
 *     (already-committed Global rules still apply and are still read); and
 *     `from-production` could only ever open a vendor's single newest invoice,
 *     because it resolved `order_by(created_at.desc()).first()`.
 *   * Rules are now created by clicking a **real alert on a real invoice**, via
 *     four structured correction endpoints, and nothing persists until it has
 *     cleared `POST /sessions/{id}/preview`.
 *
 * So the two calls above are deleted here rather than left in place returning
 * 410s, and `startSession(scope, ...)` is replaced by two explicit entry points:
 * `startSessionFromInvoice()` (history path) and `startSessionFromUpload()`
 * (upload path). Both land on the same session shape.
 */

import { apiClient } from "./apiClient";

/**
 * Rule scope, as the *session* reports it.
 *
 * `global` is retained in the union only because `getRuleHistory()` can still be
 * asked for the Global template's timeline (already-committed Global rules are
 * live and readable -- only their *creation* was removed). No session this file
 * creates ever carries it: `from-invoice` returns `existing_vendor` for an
 * inbound invoice and `outbound` for an outbound one, and `upload` returns
 * `new_vendor`.
 */
export type TrainerScope = "global" | "existing_vendor" | "new_vendor" | "outbound";

/**
 * Production Vendor selection option for the vendor picker.
 * `GET /api/trainer/vendors`.
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
 * One of a vendor's stored invoices, for the "pick which invoice to train on"
 * picker.
 *
 * The backend has no trainer-side per-vendor invoice list: `GET /trainer/vendors`
 * returns one `sampleInvoiceId` per vendor, which is the same latest-only
 * limitation Feature 18 removed from `from-production`. The real list comes from
 * the standard invoice list endpoint filtered by vendor -- see
 * `listVendorInvoices()` below.
 */
export interface VendorInvoiceOption {
  id: string;
  invoiceNumber?: string;
  vendorName?: string;
  status?: string;
  grandTotal?: number | null;
  currency?: string | null;
  createdAt?: string;
  invoiceDate?: string | null;
  alertCount: number;
}

/**
 * Coordinate bounding box for visual grounding highlights on the PDF viewer canvas.
 *
 * Kept as an optional field on `ExtractedVariable`. It is populated only when the
 * extraction result actually carried coordinates -- the UI must degrade to
 * "show the document, no highlight" rather than forcing a box that may not exist.
 */
export interface BoundingBox {
  page: number;
  x: number;
  y: number;
  width: number;
  height: number;
}

/**
 * Extracted invoice variable (e.g. invoice_number, subtotal, tax_amount).
 */
export interface ExtractedVariable {
  id: string;
  key: string;
  label: string;
  value: string;
  confidence: number; // 0.0 - 1.0
  isCorrected?: boolean;
  boundingBox?: BoundingBox;
}

/**
 * Conversational message bubble in the Trainer chat panel.
 *
 * Feature 18: on a `qa_test` turn `id` is now the **real `ChatMessage` UUID**
 * (`_handle_qa_test_turn` persists both sides as real rows), which is what makes
 * a thumbs-down from the QA panel routable to `PUT /chat/messages/{id}/feedback`.
 * On a `rule_creation` turn it is still a synthetic `msg-xxxxxxxx` id, so callers
 * must check `sessionMode` before treating it as a message id.
 */
export interface ChatMessage {
  id: string;
  sender: "user" | "assistant";
  text: string;
  timestamp: string;
  suggestedRule?: string;
  updatedVariables?: Partial<Record<string, string>>;
}

/**
 * One alert on the session's anchor invoice, annotated by the backend's
 * alert-type registry (`utils/alert_registry.py`) with which correction form
 * applies. `_serialize_alerts()` in `routers/trainer.py` produces this shape.
 *
 * `correctionForm` is the field the correction UI switches on -- the FE never
 * decides for itself which knob an alert type has:
 *   "tolerance"             -> abs_tol / rel_tol form (3 types)
 *   "confidence_threshold"  -> threshold form (low_confidence_field only)
 *   "severity_message"      -> relabel only; there is no numeric knob
 *   "none"                  -> not correctable at all (duplicates, failures)
 */
export interface TrainerAlert {
  id: string;
  type: string | null;
  label: string;
  message?: string | null;
  field?: string | null;
  severity?: string | null;
  correctionForm: "tolerance" | "confidence_threshold" | "severity_message" | "none";
  toleranceOverridable: boolean;
  thresholdOverridable: boolean;
  notCorrectableReason: string;
  known: boolean;
}

/** One entry from `GET /trainer/alert-types` (`list_alert_types()`). */
export interface AlertTypeSpec {
  type: string;
  label: string;
  producer: string;
  defaultField: string | null;
  toleranceOverridable: boolean;
  thresholdOverridable: boolean;
  severityOverridable: boolean;
  correctionForm: "tolerance" | "confidence_threshold" | "severity_message" | "none";
  notCorrectableReason: string;
  flaggableAsMissed: boolean;
}

/** `GET /trainer/alert-types` envelope. */
export interface AlertTypeRegistry {
  alertTypes: AlertTypeSpec[];
  toleranceOverridable: string[];
  thresholdOverridable: string[];
  /**
   * The five `*_not_verified_in_source` types. They ask a verbatim-presence
   * question with no numeric band to widen, so the tolerance endpoint 400s on
   * them. Surfaced explicitly by the backend so the UI can *explain* the absence
   * of a form instead of rendering a control that would silently do nothing.
   */
  toleranceExcluded: string[];
}

/**
 * A rule in plain structured terms — `services/rule_impact.py::describe_rule()`.
 * This is what the preview screen renders: the user approves a *rule*, not a
 * sentence an LLM happened to produce.
 */
export interface RuleDescription {
  kind: "extraction" | "tolerance_override" | "confidence_threshold_override" | "alert_override" | string;
  field: string;
  condition: string;
  scope: string | null;
  sourceAlertType: string | null;
  origin: string | null;
  text: string;
  params: Record<string, unknown>;
}

/** One historical invoice the replay says a candidate rule would change. */
export interface RuleImpactSample {
  invoiceId: string;
  invoiceNumber?: string | null;
  vendorName?: string | null;
  alertsRemoved: string[];
  alertsAdded: string[];
}

/**
 * Historical impact from `services/rule_impact.py::compute_rule_impact()`.
 *
 * `kind` is the field that matters: `not_computable` means the backend
 * deliberately refused to show a number (a text extraction rule's effect depends
 * on how a model reads a PDF), and the UI must render that honestly rather than
 * a zero. `partial` means some rules replayed and some didn't, with the
 * uncomputable part named in `notComputable`.
 */
export interface RuleImpact {
  kind: "exact" | "not_computable" | "partial";
  summary: string;
  rules: RuleDescription[];
  invoicesExamined: number;
  alertsRemoved: number | null;
  alertsAdded: number | null;
  invoicesAffected: number | null;
  alertsRelabelled: number | null;
  sample: RuleImpactSample[];
  notComputable: { reason: string; appliesTo: string | string[] }[];
}

/** `POST /trainer/sessions/{id}/preview` response. */
export interface PreviewResult {
  previewToken: string;
  scope: string;
  vendorName: string | null;
  newRules: RuleDescription[];
  impact: RuleImpact;
}

/**
 * Full state of an active Trainer sandbox session.
 *
 * Feature 18 additions: `invoiceId`, `flowDirection`, `alerts`,
 * `activeRulesDetailed`. `activeRules` keeps its old meaning (plain sentences)
 * so nothing that only renders text had to change.
 */
export interface TrainerSession {
  sessionId: string;
  scope: TrainerScope;
  vendorName?: string;
  fileName?: string;
  /**
   * Always populated server-side now, for **both** entry paths:
   *   `/api/invoices/{id}/pdf`          — a stored production invoice
   *   `/api/trainer/sessions/{id}/pdf`  — a transient upload (no Invoice row)
   * The old client-side `URL.createObjectURL(file)` is gone: it survived neither
   * a reload nor opening the session on another device, on a screen whose whole
   * job is "look at the alert next to the document that caused it".
   */
  pdfUrl?: string;
  createdAt: string;
  variables: ExtractedVariable[];
  activeRules: string[];
  activeRulesDetailed: RuleDescription[];
  chatHistory: ChatMessage[];
  sessionMode?: "qa_test" | "rule_creation";
  invoiceId?: string | null;
  flowDirection?: "INBOUND" | "OUTBOUND";
  alerts: TrainerAlert[];
}

/**
 * Historical rule template version record for auditability & rollback.
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
  templateId?: string;
}

/** Result of committing a session's staged rules to the template registry. */
export interface CommitResult {
  scope: TrainerScope;
  vendorName?: string;
  version: number;
  rules: string[];
  reauditQueued: boolean;
}

/** What a correction endpoint hands back: the updated session + the staged rule. */
export interface StagedRuleResult {
  updatedSession: TrainerSession;
  stagedRule: RuleDescription;
}

/**
 * Normalises a raw backend session payload into a well-formed TrainerSession.
 * The backend already returns the camelCase shape; this guards against missing
 * arrays / nulls so the UI never crashes on a partial response.
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
    activeRulesDetailed: Array.isArray(raw?.activeRulesDetailed) ? raw.activeRulesDetailed : [],
    chatHistory: Array.isArray(raw?.chatHistory) ? raw.chatHistory : [],
    sessionMode: raw?.sessionMode === "qa_test" ? "qa_test" : "rule_creation",
    invoiceId: raw?.invoiceId ?? null,
    flowDirection: raw?.flowDirection === "OUTBOUND" ? "OUTBOUND" : "INBOUND",
    alerts: Array.isArray(raw?.alerts) ? raw.alerts : [],
  };
}

/**
 * Service API abstraction layer — connects to the backend FastAPI trainer router
 * through this app's `/api/trainer/*` proxy routes.
 */
export const trainerService = {
  /**
   * Tenant vendors for the vendor picker.
   * `GET /api/trainer/vendors`
   */
  async getTenantVendors(): Promise<VendorOption[]> {
    const { data } = await apiClient.get("/trainer/vendors");
    return Array.isArray(data) ? data : [];
  },

  /**
   * A vendor's stored invoices, newest first — the "pick one of their invoices"
   * half of the unified entry point.
   *
   * `GET /api/invoices?vendor_name=X&limit=N`, not a trainer endpoint: the
   * backend deliberately did not add a trainer-side list route, and this one
   * already supports a `vendor_name` filter with real pagination
   * (`routers/invoices.py::list_invoices`). It is INBOUND-only by construction
   * there, which matches the picker's purpose — an outbound invoice has no
   * vendor to pick, and outbound training is reached from the outbound console
   * rather than a vendor dropdown.
   */
  async listVendorInvoices(vendorName: string, limit = 50): Promise<VendorInvoiceOption[]> {
    const { data } = await apiClient.get("/invoices", {
      params: { vendor_name: vendorName, limit },
    });
    if (!Array.isArray(data)) return [];
    return data.map((inv: any) => ({
      id: String(inv?.id),
      invoiceNumber: inv?.invoice_number ?? undefined,
      vendorName: inv?.vendor_name ?? undefined,
      status: inv?.status ?? undefined,
      grandTotal: inv?.grand_total ?? null,
      currency: inv?.currency ?? null,
      createdAt: inv?.created_at ?? undefined,
      invoiceDate: inv?.invoice_date ?? null,
      alertCount: Array.isArray(inv?.sa_alerts) ? inv.sa_alerts.length : 0,
    }));
  },

  /**
   * History path — open a **specific** stored invoice, with no reprocessing.
   * `POST /api/trainer/sessions/from-invoice`
   *
   * The backend runs no OCR and no re-extraction here (asserted by
   * `test_from_invoice_does_not_rerun_ocr`); it opens the stored extraction
   * result and the stored `sa_alerts`.
   */
  async startSessionFromInvoice(
    invoiceId: string,
    sessionMode: "qa_test" | "rule_creation" = "rule_creation"
  ): Promise<TrainerSession> {
    const { data } = await apiClient.post("/trainer/sessions/from-invoice", {
      invoice_id: invoiceId,
      session_mode: sessionMode,
    });
    return normalizeSession(data);
  },

  /**
   * Upload path — a brand-new or already-known vendor's sample PDF.
   * `POST /api/trainer/upload`
   *
   * This runs the real OCR + extraction flow and returns that document's real
   * alerts in the same session shape the history path produces. It deliberately
   * creates **no `Invoice` row** (it would consume the tenant's free-invoice
   * quota and appear on the dashboard), which is why its PDF is served from
   * `/api/trainer/sessions/{id}/pdf` rather than `/api/invoices/{id}/pdf`.
   *
   * No `URL.createObjectURL` here any more — `pdfUrl` comes back from the server.
   */
  async startSessionFromUpload(file: File): Promise<TrainerSession> {
    const form = new FormData();
    form.append("file", file);
    const { data } = await apiClient.post("/trainer/upload", form);
    const session = normalizeSession(data);
    // The backend names the file from the upload itself, but keep the local
    // name as a fallback so the header never renders blank.
    session.fileName = session.fileName ?? file.name;
    return session;
  },

  /**
   * The alert-type registry. Drives the "which alert did you expect?" picker and
   * tells the correction UI which form each type supports.
   * `GET /api/trainer/alert-types?flaggable_only=`
   */
  async getAlertTypes(flaggableOnly = false): Promise<AlertTypeRegistry> {
    const { data } = await apiClient.get("/trainer/alert-types", {
      params: flaggableOnly ? { flaggable_only: true } : undefined,
    });
    return {
      alertTypes: Array.isArray(data?.alertTypes) ? data.alertTypes : [],
      toleranceOverridable: Array.isArray(data?.toleranceOverridable) ? data.toleranceOverridable : [],
      thresholdOverridable: Array.isArray(data?.thresholdOverridable) ? data.thresholdOverridable : [],
      toleranceExcluded: Array.isArray(data?.toleranceExcluded) ? data.toleranceExcluded : [],
    };
  },

  /**
   * Correction #1 — "this alert was unnecessary" on a tolerance-taking check.
   * Only valid for the three tolerance-overridable types; anything else 400s
   * with the registry's own explanation.
   */
  async correctTolerance(
    sessionId: string,
    payload: { alertType: string; field?: string | null; absTol: number; relTol: number }
  ): Promise<StagedRuleResult> {
    const { data } = await apiClient.post(`/trainer/sessions/${sessionId}/corrections/tolerance`, {
      alert_type: payload.alertType,
      field: payload.field ?? null,
      abs_tol: payload.absTol,
      rel_tol: payload.relTol,
    });
    return { updatedSession: normalizeSession(data?.updatedSession), stagedRule: data?.stagedRule };
  },

  /**
   * Correction #2 — "this low-confidence alert was unnecessary".
   * A *threshold*, not a tolerance: a different parameter on a different backend
   * function, so it gets its own form and its own endpoint. Clamped to (0, 1] —
   * 0 would disable the check entirely, which is suppression, not tuning.
   */
  async correctConfidenceThreshold(
    sessionId: string,
    payload: { threshold: number; field?: string | null }
  ): Promise<StagedRuleResult> {
    const { data } = await apiClient.post(
      `/trainer/sessions/${sessionId}/corrections/confidence-threshold`,
      { threshold: payload.threshold, field: payload.field ?? null }
    );
    return { updatedSession: normalizeSession(data?.updatedSession), stagedRule: data?.stagedRule };
  },

  /**
   * Correction #3 — the alert is right to fire, but its severity or wording is
   * wrong. Never changes *whether* it fires.
   */
  async correctAlertOverride(
    sessionId: string,
    payload: { alertType: string; field?: string | null; severity?: string | null; message?: string | null }
  ): Promise<StagedRuleResult> {
    const { data } = await apiClient.post(`/trainer/sessions/${sessionId}/corrections/alert-override`, {
      alert_type: payload.alertType,
      field: payload.field ?? null,
      severity: payload.severity || null,
      message: payload.message || null,
    });
    return { updatedSession: normalizeSession(data?.updatedSession), stagedRule: data?.stagedRule };
  },

  /**
   * Correction #4 — "I expected an alert here and got none".
   *
   * `alertType` and `field` are the primary input, both structured picks;
   * `context` is optional prose passed to the backend as secondary colour only.
   * This is the one LLM-interpreted path and it fails closed — on a drafting
   * failure the backend 502s and stages nothing.
   */
  async flagMissedAlert(
    sessionId: string,
    payload: { alertType: string; field: string; context?: string }
  ): Promise<StagedRuleResult> {
    const { data } = await apiClient.post(`/trainer/sessions/${sessionId}/corrections/missed-alert`, {
      alert_type: payload.alertType,
      field: payload.field,
      context: payload.context || "",
    });
    return { updatedSession: normalizeSession(data?.updatedSession), stagedRule: data?.stagedRule };
  },

  /**
   * The preview-before-commit gate. Every correction path goes through this
   * before anything is written.
   * `POST /api/trainer/sessions/{id}/preview`
   */
  async previewSession(sessionId: string): Promise<PreviewResult> {
    const { data } = await apiClient.post(`/trainer/sessions/${sessionId}/preview`);
    return {
      previewToken: data?.previewToken,
      scope: data?.scope,
      vendorName: data?.vendorName ?? null,
      newRules: Array.isArray(data?.newRules) ? data.newRules : [],
      impact: data?.impact,
    };
  },

  /**
   * Sends a natural-language message to the session.
   *
   * In `qa_test` mode this is a real question about the invoice/vendor, answered
   * by the query agent and persisted as real `ChatMessage` rows (so the reply's
   * `messageId` can carry a thumbs-down). In `rule_creation` mode it is the
   * legacy conversational refinement path, which Feature 14 no longer offers as
   * a rule-creation affordance in the UI.
   * `POST /api/trainer/sessions/{id}/chat`
   */
  async sendChatMessage(
    session: TrainerSession,
    userMessageText: string
  ): Promise<{ updatedSession: TrainerSession; newRuleCreated?: string; messageId?: string }> {
    const { data } = await apiClient.post(`/trainer/sessions/${session.sessionId}/chat`, {
      content: userMessageText,
    });

    const updatedSession = normalizeSession(data?.updatedSession);
    // `pdfUrl` is server-side now, but keep the fallback so a partial response
    // can't blank the document panel mid-conversation.
    updatedSession.pdfUrl = updatedSession.pdfUrl ?? session.pdfUrl;
    updatedSession.fileName = updatedSession.fileName ?? session.fileName;

    return {
      updatedSession,
      newRuleCreated: data?.newRuleCreated ?? undefined,
      messageId: data?.messageId ?? undefined,
    };
  },

  /**
   * Commits the session's staged rules to the template registry.
   * `POST /api/trainer/sessions/{id}/commit`
   *
   * `previewToken` ties the commit to the impact estimate the user actually
   * approved: the backend 409s if the session's rules changed since it was
   * issued. It is optional on the backend (for direct API callers), but this UI
   * always sends one — a commit that never went through the gate is exactly what
   * the redesign exists to prevent.
   */
  async commitSession(session: TrainerSession, previewToken?: string): Promise<CommitResult> {
    const { data } = await apiClient.post(
      `/trainer/sessions/${session.sessionId}/commit`,
      previewToken ? { preview_token: previewToken } : {}
    );
    return {
      scope: data?.scope,
      vendorName: data?.vendor_name ?? undefined,
      version: data?.version,
      rules: data?.rules?.constraints ?? [],
      reauditQueued: Boolean(data?.reaudit_queued),
    };
  },

  /**
   * Version history for the active template.
   * `GET /api/trainer/templates/history?scope=&vendor_name=`
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
   * Rolls a past rule version back to current (writes a new version + queues
   * re-audit).
   * `POST /api/trainer/templates/{templateId}/rollback/{version}`
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

  /** Switch the session between QA test and rule-creation modes. */
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
