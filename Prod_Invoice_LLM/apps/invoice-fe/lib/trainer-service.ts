/**
 * AI Trainer Sandbox Service Layer & Data Models (Feature 6)
 * 
 * FOR MANAGERS & DEVELOPERS:
 * This module defines the core data contracts and API service layer for the AI Trainer Interactive Sandbox.
 * It supports all three redesign rule scopes specified in feature_6_trainer.md & feature_10_trainer.md:
 *   1. "global": Tenant-wide, vendor-agnostic rules (e.g. VAT handling)
 *   2. "existing_vendor": Refine rules for a vendor with production history (seeds from production invoice)
 *   3. "new_vendor": Cold-start rules for a brand new vendor (seeds from uploaded sample PDF)
 * 
 * BACKEND INTEGRATION NOTE:
 * When connecting live FastAPI backend endpoints, replace mock return data inside the functions below 
 * with direct HTTP fetch calls to POST /trainer/sessions/* and GET /trainer/templates/* endpoints.
 */

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
}

/**
 * Mock Tenant Vendors Dataset for Scope #2 dropdown selection
 */
export const MOCK_TENANT_VENDORS: VendorOption[] = [
  {
    id: "v-acme",
    name: "Acme Logistics Corp",
    invoiceCount: 42,
    sampleInvoiceId: "inv-8921",
    sampleFileName: "INV-2026-ACME-049.pdf",
    samplePdfUrl: "https://www.w3.org/WAI/ER/tests/xhtml/testfiles/resources/pdf/dummy.pdf",
  },
  {
    id: "v-techsupplies",
    name: "TechSupplies Global Ltd",
    invoiceCount: 19,
    sampleInvoiceId: "inv-4412",
    sampleFileName: "TechSupplies_Invoice_882.pdf",
    samplePdfUrl: "https://www.w3.org/WAI/ER/tests/xhtml/testfiles/resources/pdf/dummy.pdf",
  },
  {
    id: "v-cloudcloud",
    name: "Cloud Hosting Solutions Inc",
    invoiceCount: 31,
    sampleInvoiceId: "inv-1092",
    sampleFileName: "CloudHosting_JUL2026.pdf",
    samplePdfUrl: "https://www.w3.org/WAI/ER/tests/xhtml/testfiles/resources/pdf/dummy.pdf",
  },
];

/**
 * Baseline mock extraction variables set for document preview
 */
const DEFAULT_MOCK_VARIABLES: ExtractedVariable[] = [
  { id: "1", key: "invoice_number", label: "Invoice Number", value: "INV-2026-089", confidence: 0.98 },
  { id: "2", key: "invoice_date", label: "Invoice Date", value: "19/07/2026", confidence: 0.72 },
  { id: "3", key: "vendor_name", label: "Vendor Name", value: "Acme Logistics Corp", confidence: 0.95 },
  { id: "4", key: "subtotal", label: "Subtotal (Taxable)", value: "$12,450.00", confidence: 0.91 },
  { id: "5", key: "tax_amount", label: "VAT / Tax Amount", value: "$2,241.00", confidence: 0.65 },
  { id: "6", key: "total_amount", label: "Grand Total", value: "$14,691.00", confidence: 0.97 },
];

/**
 * Service API Abstraction layer.
 * Connects directly to backend FastAPI router (/trainer/*) when deployed,
 * or gracefully provides responsive mock states during local frontend design validation.
 */
export const trainerService = {
  /**
   * Fetches tenant vendors for Scope #2 (Existing Vendor) dropdown picker.
   * Target Endpoint: GET /api/vendors
   */
  async getTenantVendors(): Promise<VendorOption[]> {
    return MOCK_TENANT_VENDORS;
  },

  /**
   * Initializes a new Trainer session based on the chosen scope.
   * Target Endpoints:
   *   - Global: POST /trainer/sessions/global (Task 10.2)
   *   - Existing Vendor: POST /trainer/sessions/from-production?vendor_name=X (Task 10.3)
   *   - New Vendor: POST /trainer/upload (Task 10.4)
   */
  async startSession(scope: TrainerScope, vendorName?: string, file?: File): Promise<TrainerSession> {
    const sessionId = `tr-sess-${Date.now().toString(36)}`;
    let fileName = undefined;
    let pdfUrl = undefined;
    let initialVars = DEFAULT_MOCK_VARIABLES;

    if (scope === "existing_vendor" && vendorName) {
      const v = MOCK_TENANT_VENDORS.find((vendor) => vendor.name === vendorName);
      if (v) {
        fileName = v.sampleFileName;
        pdfUrl = v.samplePdfUrl;
      } else {
        fileName = `${vendorName}_Sample_Invoice.pdf`;
      }
    } else if (scope === "new_vendor" && file) {
      fileName = file.name;
      pdfUrl = URL.createObjectURL(file);
    } else if (scope === "global") {
      if (file) {
        fileName = file.name;
        pdfUrl = URL.createObjectURL(file);
      } else {
        initialVars = []; // Global session without grounding PDF starts with empty extraction list
      }
    }

    const initialMessage: ChatMessage = {
      id: "m-init",
      sender: "assistant",
      text: scope === "global"
        ? "Welcome to the Global Rule Sandbox! All rules trained here will apply tenant-wide to every vendor. What rule would you like to add or refine?"
        : scope === "existing_vendor"
        ? `Loaded production sample invoice for ${vendorName}. What corrections or extraction rules should we refine for this vendor?`
        : `Uploaded sample invoice ${fileName || ""}. Let's set up cold-start extraction rules for this new vendor.`,
      timestamp: new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }),
    };

    return {
      sessionId,
      scope,
      vendorName,
      fileName,
      pdfUrl,
      createdAt: new Date().toISOString(),
      variables: initialVars,
      activeRules: scope === "global" ? ["VAT is a tax item after line discount"] : [],
      chatHistory: [initialMessage],
    };
  },

  /**
   * Processes a natural language rule correction instruction from the user.
   * Target Endpoint: POST /trainer/sessions/{id}/chat (Task 10.5)
   */
  async sendChatMessage(
    session: TrainerSession,
    userMessageText: string
  ): Promise<{ updatedSession: TrainerSession; newRuleCreated?: string }> {
    const timestamp = new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
    const userMsg: ChatMessage = {
      id: `msg-${Date.now()}`,
      sender: "user",
      text: userMessageText,
      timestamp,
    };

    let replyText = "";
    let suggestedRule: string | undefined = undefined;
    let updatedVariables = { ...session.variables };

    const lower = userMessageText.toLowerCase();

    // Pattern recognition simulation matching user instructions to rule constraints & variable updates
    if (lower.includes("date") || lower.includes("dd-mm-yyyy") || lower.includes("dd/mm/yyyy")) {
      suggestedRule = "Parse dates in DD/MM/YYYY format explicitly before converting to ISO";
      replyText = `Understood. I have updated the Date parser rule: "${suggestedRule}". I applied this to the active document preview.`;
      updatedVariables = updatedVariables.map((v) =>
        v.key === "invoice_date" ? { ...v, value: "19/07/2026", confidence: 0.99, isCorrected: true } : v
      );
    } else if (lower.includes("vat") || lower.includes("tax")) {
      suggestedRule = "VAT/Tax should be computed as subtotal * 18% post-discount";
      replyText = `Rule registered: "${suggestedRule}". Tax amount variable updated.`;
      updatedVariables = updatedVariables.map((v) =>
        v.key === "tax_amount" ? { ...v, value: "$2,241.00", confidence: 0.98, isCorrected: true } : v
      );
    } else if (lower.includes("number") || lower.includes("inv-")) {
      suggestedRule = "Match Invoice Number regex pattern INV-[0-9]{4}-[0-9]{3}";
      replyText = `Understood. Invoice number format rule created: "${suggestedRule}".`;
      updatedVariables = updatedVariables.map((v) =>
        v.key === "invoice_number" ? { ...v, isCorrected: true } : v
      );
    } else {
      suggestedRule = `Extract ${userMessageText.slice(0, 40)} constraint`;
      replyText = `Got it! I've analyzed your instruction and registered the constraint candidate: "${suggestedRule}". You can commit this to the registry when ready.`;
    }

    const aiMsg: ChatMessage = {
      id: `msg-ai-${Date.now()}`,
      sender: "assistant",
      text: replyText,
      timestamp,
      suggestedRule,
    };

    const combinedRules = suggestedRule ? [...session.activeRules, suggestedRule] : session.activeRules;
    const newRules = Array.from(new Set(combinedRules));

    return {
      updatedSession: {
        ...session,
        variables: updatedVariables,
        activeRules: newRules,
        chatHistory: [...session.chatHistory, userMsg, aiMsg],
      },
      newRuleCreated: suggestedRule,
    };
  },

  /**
   * Fetches historical rule versions for auditability and rollback drawer.
   * Target Endpoint: GET /trainer/templates/{id}/history (Task 10.10)
   */
  async getRuleHistory(scope: TrainerScope, vendorName?: string): Promise<RuleVersion[]> {
    return [
      {
        id: "rv-v3",
        version: 3,
        scope,
        vendorName,
        rules: [
          "Parse dates in DD/MM/YYYY format explicitly",
          "VAT/Tax is calculated at 18% post-line-discount",
          "Match Invoice Number prefix INV-",
        ],
        changedBy: "alex.auditor@enterprise.com",
        changedAt: new Date(Date.now() - 3600000 * 2).toLocaleString(),
        isCurrent: true,
      },
      {
        id: "rv-v2",
        version: 2,
        scope,
        vendorName,
        rules: [
          "VAT/Tax is calculated at 18% post-line-discount",
          "Match Invoice Number prefix INV-",
        ],
        changedBy: "sarah.lead@enterprise.com",
        changedAt: new Date(Date.now() - 3600000 * 48).toLocaleString(),
        isCurrent: false,
      },
      {
        id: "rv-v1",
        version: 1,
        scope,
        vendorName,
        rules: [
          "Default vendor extraction schema template",
        ],
        changedBy: "system_auto",
        changedAt: new Date(Date.now() - 3600000 * 120).toLocaleString(),
        isCurrent: false,
      },
    ];
  },
};
