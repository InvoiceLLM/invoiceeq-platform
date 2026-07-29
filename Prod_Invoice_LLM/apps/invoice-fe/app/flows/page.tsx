"use client";

import { useState, useEffect, useRef } from "react";

// ─── TYPES ────────────────────────────────────────────────────────────────────

type NodeState = "idle" | "active" | "done" | "warn" | "error";
type ActivityType = "info" | "check" | "data" | "warn" | "error";

interface Activity { text: string; type: ActivityType; }
interface FlowNode {
  id: string; label: string; sublabel?: string; icon: string;
  x: number; y: number;
  agentName: string; agentRole: string;
  activities: Activity[];
  finalState?: "done" | "warn";
  isNew?: boolean;
  // Gap 64: plain-language callout shown as a blinking bubble above this node
  // while it's active -- only set on the "human-facing" nodes (user action /
  // agent reply / terminal outcome), not the internal technical steps, which
  // already have the (more technical) activity log in AgentPanel for that.
  explainer?: string;
}
interface FlowEdge {
  id: string; from: string; to: string;
  label?: string;
  variant?: "normal" | "success" | "error" | "dashed" | "vendor";
}
interface PlayStep { nodeId: string; edgeIds: string[]; }
interface FlowDef {
  id: string; name: string; badge: string; color: string; description: string;
  nodes: FlowNode[]; edges: FlowEdge[]; sequence: PlayStep[];
}

// ─── CONSTANTS ────────────────────────────────────────────────────────────────

const NW = 178; const NH = 64;
const BASE_ACTIVITY_MS = 620;

const EDGE_COLORS: Record<string, string> = {
  normal: "#475569", success: "#22C55E", error: "#EF4444", dashed: "#8B5CF6", vendor: "#F59E0B",
};

const NODE_STYLES: Record<NodeState, { bg: string; border: string; text: string; glow: string }> = {
  idle:   { bg: "#131C2E", border: "#1E293B", text: "#475569", glow: "none" },
  active: { bg: "#0F2547", border: "#3B82F6", text: "#93C5FD", glow: "0 0 18px #3B82F680" },
  done:   { bg: "#0C1F16", border: "#22C55E", text: "#86EFAC", glow: "0 0 10px #22C55E40" },
  warn:   { bg: "#1F1500", border: "#EAB308", text: "#FDE047", glow: "0 0 10px #EAB30840" },
  error:  { bg: "#1F0808", border: "#EF4444", text: "#FCA5A5", glow: "0 0 10px #EF444440" },
};

const ACTIVITY_COLORS: Record<ActivityType, string> = {
  info: "#60A5FA", check: "#34D399", data: "#A78BFA", warn: "#FBBF24", error: "#F87171",
};
const ACTIVITY_ICONS: Record<ActivityType, string> = {
  info: "→", check: "✓", data: "◆", warn: "⚠", error: "✗",
};

// ─── INBOUND FLOW ─────────────────────────────────────────────────────────────

const INBOUND: FlowDef = {
  id: "inbound", name: "Inbound Extraction Pipeline", badge: "RECEIVE", color: "#3B82F6",
  description: "Tenant receives a vendor invoice (PDF) → OCR → LangGraph classification → LLM extraction with Trainer rules → 6-check verification → COMPLETED or AUDIT_REQUIRED.",
  nodes: [
    { id: "upload", label: "PDF Upload", sublabel: "REST / Watcher / Email", icon: "⬆", x: 90, y: 30,
      explainer: "👤 User uploads an invoice PDF",
      agentName: "Invoice Upload Handler", agentRole: "routers/invoices.py",
      activities: [
        { text: "Receiving multipart/form-data — 3.2 MB", type: "info" },
        { text: "Validating MIME type: application/pdf ✓", type: "check" },
        { text: "Computing SHA-256 fingerprint...", type: "info" },
        { text: "Hash a4f3b2c1... → not in tenant index", type: "data" },
        { text: "Creating Invoice row: status=UPLOADED", type: "check" },
        { text: "Blob upload dispatched async", type: "info" },
      ],
    },
    { id: "blob", label: "Blob Storage", sublabel: "Azure Blob + Queue enqueue", icon: "🗄", x: 90, y: 150,
      agentName: "Storage & Queue Agent", agentRole: "services/storage.py · queue_worker/main_worker.py",
      activities: [
        { text: "Uploading to container: invoices/tenant-{id}/", type: "info" },
        { text: "Upload complete: 3.2 MB in 1.4s", type: "check" },
        { text: "Acquiring per-tenant in-flight slot (Gap 42)...", type: "info" },
        { text: "Slot: 1 / 5 in-flight — slot acquired ✓", type: "check" },
        { text: "Serializing queue message: invoice_id, tenant_id", type: "data" },
        { text: "Enqueued to invoice-processing-queue ✓", type: "check" },
      ],
    },
    { id: "ocr", label: "OCR Engine", sublabel: "prebuilt-invoice · 3-attempt retry", icon: "📄", x: 90, y: 300,
      agentName: "Azure Document Intelligence", agentRole: "queue_worker/handlers.py::_run_ocr()",
      activities: [
        { text: "Calling Azure Doc Intelligence — prebuilt-invoice (Gap 15)", type: "info" },
        { text: "Endpoint pool: rotating across 3 endpoints (Gap 41)", type: "data" },
        { text: "Page 1/3 — analyzing layout and fields...", type: "info" },
        { text: "Page 2/3 — line items detected (8 rows)", type: "info" },
        { text: "Page 3/3 — footer / tax summary", type: "info" },
        { text: "VendorName confidence: 0.94 | InvoiceTotal: 0.89", type: "data" },
        { text: "Raw OCR text: 2,847 chars extracted ✓", type: "check" },
      ],
    },
    { id: "classify", label: "Classify Complexity", sublabel: "STANDARD / COMPLEX", icon: "🏷", x: 90, y: 470,
      agentName: "Complexity Classifier", agentRole: "services/invoice_classifier.py → agents/extraction_agent.py::classify_node()",
      activities: [
        { text: "Scanning for multi-rate tax slabs...", type: "info" },
        { text: "IRN / e-Way Bill identifiers: NOT FOUND", type: "data" },
        { text: "Line item count: 8 (threshold: 10)", type: "data" },
        { text: "Holdback / deduction clauses: NOT FOUND", type: "data" },
        { text: "Classification → STANDARD ✓", type: "check" },
      ],
    },
    { id: "extract", label: "LLM Extraction", sublabel: "Two-stage: Global → Vendor rules", icon: "🤖", x: 90, y: 610,
      agentName: "Extraction Agent (LangGraph)", agentRole: "agents/extraction_agent.py::extract_node()",
      activities: [
        { text: "Loading INBOUND Global ExtractionTemplate (3 rules)", type: "data" },
        { text: "Rule: 'tax_amount = CGST + SGST summed'", type: "data" },
        { text: "Merging vendor template 'Vertex Industries' (2 rules)", type: "data" },
        { text: "Building extraction prompt — 1,847 tokens", type: "info" },
        { text: "gpt-5-mini call (attempt 1/3) via invoke_with_retry", type: "info" },
        { text: "vendor_name = 'Vertex Industries Pvt Ltd'", type: "check" },
        { text: "grand_total = ₹1,24,560.00", type: "check" },
        { text: "tax_amount = ₹19,956.00  (CGST ₹9,978 + SGST ₹9,978)", type: "check" },
        { text: "8 line items extracted ✓", type: "check" },
      ],
    },
    { id: "verify", label: "Verification Suite", sublabel: "6 deterministic checks", icon: "✅", x: 90, y: 800,
      agentName: "Verification Agent", agentRole: "agents/extraction_agent.py::verify_node() + utils/verification_tools.py",
      activities: [
        { text: "verify_totals_math: subtotal + tax = grand_total ✓", type: "check" },
        { text: "verify_grand_total_in_source_text: '1,24,560' found ✓", type: "check" },
        { text: "verify_line_item_amounts_in_source_text: 8/8 ✓", type: "check" },
        { text: "verify_subtotal_in_source_text: '1,04,604' found ✓", type: "check" },
        { text: "verify_field_confidence: all critical fields ≥ 60% ✓", type: "check" },
        { text: "verify_tax_amount_in_source_text: '19,956' found ✓", type: "check" },
        { text: "All 6 checks PASSED — routing to COMPLETED ✓", type: "check" },
      ],
    },
    { id: "dedup2", label: "Layer-2 Dedup", sublabel: "vendor + invoice_number (Gap 9)", icon: "🔁", x: 90, y: 970,
      agentName: "Post-Extraction Dedup Check", agentRole: "queue_worker/handlers.py::_check_layer2_duplicate()",
      activities: [
        { text: "Querying tenant invoice index (post-extraction)...", type: "info" },
        { text: "Vendor: 'Vertex Industries Pvt Ltd'", type: "data" },
        { text: "Invoice#: 'INV-2026-VTX-0042'", type: "data" },
        { text: "TRIM(LOWER) fuzzy match → NOT FOUND ✓", type: "check" },
      ],
    },
    { id: "rag_idx", label: "RAG Indexing", sublabel: "Per-tenant Chroma (Gap 55)", icon: "🔗", x: 320, y: 970,
      agentName: "Semantic Indexer", agentRole: "chroma_client.py::index_invoice_document()",
      activities: [
        { text: "Loading PDF from Blob Storage...", type: "info" },
        { text: "Splitting into page chunks (3 pages)", type: "info" },
        { text: "BAAI/bge-m3 embedding — 1024-dim vectors...", type: "data" },
        { text: "Collection: invoice_chunks_<tenant_id> (Gap 55)", type: "data" },
        { text: "Upserted 3 chunks ✓", type: "check" },
      ],
    },
    { id: "completed", label: "COMPLETED", sublabel: "SSE → Dashboard", icon: "🟢", x: 90, y: 1110,
      explainer: "✅ Done — invoice fully processed",
      agentName: "Finalization Handler", agentRole: "queue_worker/handlers.py",
      finalState: "done",
      activities: [
        { text: "Status → COMPLETED", type: "check" },
        { text: "SSE event broadcast to connected clients", type: "info" },
        { text: "Dashboard metrics cache invalidated", type: "info" },
        { text: "Invoice finalized ✓", type: "check" },
      ],
    },
    { id: "audit_req", label: "AUDIT_REQUIRED", sublabel: "Auditor Console flagged", icon: "🟡", x: 320, y: 1110,
      explainer: "⚠️ Flagged — a human needs to review this one",
      agentName: "Audit Router", agentRole: "queue_worker/handlers.py → routers/audit.py",
      finalState: "warn",
      activities: [
        { text: "Status → AUDIT_REQUIRED", type: "warn" },
        { text: "Alerts: [{type:'grand_total_mismatch', ...}]", type: "data" },
        { text: "Surfacing in Auditor Console", type: "warn" },
        { text: "Gap 26/27: correction capture + rule suggestion ready", type: "info" },
      ],
    },
  ],
  edges: [
    { id: "e-upload-blob", from: "upload", to: "blob" },
    { id: "e-blob-ocr", from: "blob", to: "ocr" },
    { id: "e-ocr-classify", from: "ocr", to: "classify" },
    { id: "e-classify-extract", from: "classify", to: "extract", label: "STANDARD" },
    { id: "e-extract-verify", from: "extract", to: "verify" },
    { id: "e-verify-dedup2", from: "verify", to: "dedup2", label: "all pass", variant: "success" },
    { id: "e-verify-audit", from: "verify", to: "audit_req", label: "alerts", variant: "error" },
    { id: "e-dedup2-rag", from: "dedup2", to: "rag_idx", variant: "success" },
    { id: "e-rag-done", from: "rag_idx", to: "completed", variant: "success" },
    { id: "e-dedup2-done", from: "dedup2", to: "completed", variant: "success" },
  ],
  sequence: [
    { nodeId: "upload", edgeIds: ["e-upload-blob"] },
    { nodeId: "blob", edgeIds: ["e-blob-ocr"] },
    { nodeId: "ocr", edgeIds: ["e-ocr-classify"] },
    { nodeId: "classify", edgeIds: ["e-classify-extract"] },
    { nodeId: "extract", edgeIds: ["e-extract-verify"] },
    { nodeId: "verify", edgeIds: ["e-verify-dedup2"] },
    { nodeId: "dedup2", edgeIds: ["e-dedup2-rag"] },
    { nodeId: "rag_idx", edgeIds: ["e-rag-done"] },
    { nodeId: "completed", edgeIds: [] },
  ],
};

// ─── OUTBOUND FLOW ────────────────────────────────────────────────────────────

const OUTBOUND: FlowDef = {
  id: "outbound", name: "Outbound Extraction Pipeline", badge: "SEND", color: "#F59E0B",
  description: "Vendor Flow (Feature 2.1): tenant uploads their own invoice to a customer. Parallel pipeline — zero-touch isolation, separate schema/agent, shared OCR + verification_tools.",
  nodes: [
    { id: "ob_upload", label: "PDF Upload", sublabel: "Gated: 'Send Invoices' toggle", icon: "⬆", x: 90, y: 30,
      explainer: "👤 User uploads an invoice to send",
      agentName: "Outbound Upload Handler", agentRole: "routers/outbound_invoices.py", isNew: true,
      activities: [
        { text: "Checking 'Send Invoices' toggle in Settings...", type: "info" },
        { text: "Toggle: ENABLED ✓", type: "check" },
        { text: "Receiving PDF — 1.8 MB", type: "info" },
        { text: "Creating Invoice row: flow_direction='OUTBOUND'", type: "data" },
        { text: "customer_id=NULL (reserved for v2 portal)", type: "data" },
        { text: "Status → UPLOADED", type: "check" },
      ],
    },
    { id: "ob_blob_q", label: "Blob + Queue", sublabel: "Outbound message type", icon: "📮", x: 90, y: 160,
      agentName: "Storage & Outbound Queue Agent", agentRole: "services/storage.py · queue_worker/main_worker.py (new elif branch)", isNew: true,
      activities: [
        { text: "Uploading to Azure Blob Storage...", type: "info" },
        { text: "File path persisted on Invoice row ✓", type: "check" },
        { text: "Enqueueing with message_type='OUTBOUND'", type: "data" },
        { text: "main_worker.py elif branch → outbound_handlers.py", type: "info" },
        { text: "Slot acquired (1/5 in-flight) ✓", type: "check" },
      ],
    },
    { id: "ob_ocr", label: "OCR Engine", sublabel: "Same _run_ocr() — imported, not edited", icon: "📄", x: 90, y: 300,
      agentName: "Azure Document Intelligence (shared)", agentRole: "queue_worker/handlers.py::_run_ocr() — import only",
      activities: [
        { text: "Importing queue_worker/handlers.py::_run_ocr() unchanged", type: "data" },
        { text: "Same endpoint pool, same retry, same model", type: "info" },
        { text: "Analyzing 2-page tenant invoice...", type: "info" },
        { text: "InvoiceTotal confidence: 0.97 | CustomerName: 0.91", type: "data" },
        { text: "OCR complete — 1,403 chars ✓", type: "check" },
      ],
    },
    { id: "ob_rules", label: "OUTBOUND Global Rules", sublabel: "flow_direction='OUTBOUND' template", icon: "📋", x: 330, y: 300,
      agentName: "Outbound Rule Loader", agentRole: "agents/outbound_extraction_agent.py::_get_outbound_template_rules()", isNew: true,
      activities: [
        { text: "Querying ExtractionTemplate WHERE flow_direction='OUTBOUND'", type: "info" },
        { text: "Standing rule found: 'customer_name uses billing block, not header'", type: "data" },
        { text: "1 standing rule injected into extraction prompt", type: "check" },
        { text: "No sandbox / no re-audit fan-out (Global-only by design)", type: "info" },
      ],
    },
    { id: "ob_extract", label: "LLM Extraction (Outbound)", sublabel: "OutboundInvoiceExtractionSchema", icon: "🤖", x: 90, y: 460,
      agentName: "Outbound Extraction Agent (LangGraph)", agentRole: "agents/outbound_extraction_agent.py::extract_node()", isNew: true,
      activities: [
        { text: "OutboundInvoiceExtractionSchema (separate schema)", type: "data" },
        { text: "Prompt: 'this is the tenant's own invoice sent to a customer'", type: "info" },
        { text: "Extracting customer_name = 'Acme Logistics Corp'", type: "check" },
        { text: "Extracting grand_total = $12,400.00", type: "check" },
        { text: "Extracting due_date = 2026-08-27", type: "check" },
        { text: "No classify / dynamic_qa split (v1 deliberate cut)", type: "info" },
      ],
    },
    { id: "ob_verify", label: "Verification Suite", sublabel: "Same verify_* functions — imported", icon: "✅", x: 90, y: 620,
      agentName: "Shared Verification Agent", agentRole: "utils/verification_tools.py — import only",
      activities: [
        { text: "Importing verify_totals_math, verify_grand_total_in_source_text...", type: "info" },
        { text: "verify_totals_math: ✓", type: "check" },
        { text: "verify_grand_total_in_source_text: '12,400' found ✓", type: "check" },
        { text: "verify_line_item_amounts_in_source_text: 3/3 ✓", type: "check" },
        { text: "All checks PASSED → VERIFIED", type: "check" },
      ],
    },
    { id: "ob_verified", label: "VERIFIED", sublabel: "Tenant confirms → SENT", icon: "🟢", x: 90, y: 760,
      explainer: "✅ Verified — ready for the tenant to send",
      agentName: "Send Confirmation Handler", agentRole: "routers/outbound_invoices.py::confirm_send()", isNew: true,
      finalState: "done",
      activities: [
        { text: "Status → VERIFIED ✓", type: "check" },
        { text: "Invoice displayed in outbound list for review", type: "info" },
        { text: "Tenant confirms → confirm_send() called", type: "info" },
        { text: "Status → SENT | sent_at = now()", type: "check" },
        { text: "Triggering RAG indexing on VERIFIED...", type: "info" },
      ],
    },
    { id: "ob_rag", label: "RAG Indexing", sublabel: "On VERIFIED — same chroma_client", icon: "🔗", x: 330, y: 760,
      agentName: "Semantic Indexer (shared)", agentRole: "chroma_client.py::index_invoice_document() — import call from outbound_handlers.py", isNew: true,
      activities: [
        { text: "outbound_handlers.py calls index_invoice_document() on VERIFIED", type: "data" },
        { text: "Same per-tenant Chroma collection ✓", type: "check" },
        { text: "2 chunks embedded and upserted ✓", type: "check" },
        { text: "Outbound invoice now queryable in Chat ✓", type: "check" },
      ],
    },
    { id: "ob_needs", label: "NEEDS_REVIEW", sublabel: "Outbound Auditor Console", icon: "🟡", x: 330, y: 620,
      explainer: "⚠️ Flagged — a human needs to review this one",
      agentName: "Outbound Audit Handler", agentRole: "routers/outbound_audit.py::resolve_outbound_alert()", isNew: true,
      finalState: "warn",
      activities: [
        { text: "Status → NEEDS_REVIEW ⚠", type: "warn" },
        { text: "Alert: grand_total_mismatch surfaced", type: "warn" },
        { text: "Auditor corrects field via correction UI", type: "info" },
        { text: "'Apply as standing rule?' checkbox", type: "data" },
        { text: "If checked → upserts OUTBOUND ExtractionTemplate row", type: "data" },
      ],
    },
  ],
  edges: [
    { id: "oe-upload-blob", from: "ob_upload", to: "ob_blob_q" },
    { id: "oe-blob-ocr", from: "ob_blob_q", to: "ob_ocr" },
    { id: "oe-rules-extract", from: "ob_rules", to: "ob_extract", label: "inject", variant: "vendor" },
    { id: "oe-ocr-extract", from: "ob_ocr", to: "ob_extract" },
    { id: "oe-extract-verify", from: "ob_extract", to: "ob_verify" },
    { id: "oe-verify-ok", from: "ob_verify", to: "ob_verified", label: "clean", variant: "success" },
    { id: "oe-verify-err", from: "ob_verify", to: "ob_needs", label: "alerts", variant: "error" },
    { id: "oe-verified-rag", from: "ob_verified", to: "ob_rag", variant: "success" },
  ],
  sequence: [
    { nodeId: "ob_upload", edgeIds: ["oe-upload-blob"] },
    { nodeId: "ob_blob_q", edgeIds: ["oe-blob-ocr"] },
    { nodeId: "ob_ocr", edgeIds: ["oe-rules-extract", "oe-ocr-extract"] },
    { nodeId: "ob_extract", edgeIds: ["oe-extract-verify"] },
    { nodeId: "ob_verify", edgeIds: ["oe-verify-ok"] },
    { nodeId: "ob_verified", edgeIds: ["oe-verified-rag"] },
    { nodeId: "ob_rag", edgeIds: [] },
  ],
};

// ─── CHAT / RAG FLOW ──────────────────────────────────────────────────────────

const CHAT: FlowDef = {
  id: "chat", name: "Chat / RAG Query Agent", badge: "QUERY", color: "#8B5CF6",
  description: "Natural-language question → Redis cache check → token-aware history → Trainer rule injection → LLM intent classification → SQL self-heal loop / hybrid RAG → answer synthesis.",
  nodes: [
    { id: "q_user", label: "User Question", sublabel: "Chat UI", icon: "💬", x: 90, y: 30,
      explainer: "👤 User asks a question in plain English",
      agentName: "Chat Endpoint", agentRole: "routers/chat.py::post_chat_message()",
      activities: [
        { text: "POST /api/v1/chat/{session_id}/message", type: "info" },
        { text: "Message: 'What's the total spend with Vertex Industries?'", type: "data" },
        { text: "Validating session ownership for tenant ✓", type: "check" },
        { text: "Dispatching to run_query_agent()", type: "info" },
      ],
    },
    { id: "q_cache", label: "Redis Answer Cache", sublabel: "1hr TTL — Task 6.11", icon: "⚡", x: 90, y: 155,
      agentName: "Cache Layer", agentRole: "agents/query_agent.py::get_cached_answer()",
      activities: [
        { text: "Cache key: chat_answer_cache:{tenant_id}:{normalized_query}", type: "data" },
        { text: "Normalized: 'what is total spend with vertex industries'", type: "data" },
        { text: "Redis GET → MISS", type: "warn" },
        { text: "Proceeding to full retrieval pipeline...", type: "info" },
      ],
    },
    { id: "q_history", label: "Token-Aware History", sublabel: "tiktoken 3,000-token budget", icon: "📜", x: 90, y: 280,
      agentName: "History Loader (Gap 23)", agentRole: "agents/query_agent.py::get_chat_history()",
      activities: [
        { text: "Fetching last 50 ChatMessage rows for session...", type: "info" },
        { text: "Encoding with tiktoken cl100k_base...", type: "data" },
        { text: "4 messages fit within 3,000-token budget", type: "data" },
        { text: "46 messages trimmed (budget exceeded)", type: "info" },
        { text: "History context: 743 tokens ✓", type: "check" },
      ],
    },
    { id: "q_rules", label: "Trainer Rules", sublabel: "Global + Vendor heuristic (Gap 48/52)", icon: "📋", x: 90, y: 405,
      agentName: "Rule Injector", agentRole: "agents/query_agent.py::_get_global_business_rules() + _get_vendor_business_rules()",
      activities: [
        { text: "Loading INBOUND Global ExtractionTemplate constraints...", type: "info" },
        { text: "Rule: 'tax_amount = CGST + SGST summed'", type: "data" },
        { text: "Vendor heuristic: 'vertex' found in query text", type: "data" },
        { text: "Loading vendor template 'Vertex Industries' (Gap 52)...", type: "info" },
        { text: "Rule: 'grand_total includes freight surcharge'", type: "data" },
        { text: "2 rules injected into prompt block ✓", type: "check" },
      ],
    },
    { id: "q_classify", label: "Intent Classification", sublabel: "LLM → SQL / RAG / CHAT", icon: "🧭", x: 90, y: 535,
      agentName: "Query Classifier", agentRole: "agents/query_agent.py::classify_query()",
      activities: [
        { text: "Structured LLM call — QueryRoutingSchema", type: "info" },
        { text: "Evaluating: 'total spend' → structured column lookup", type: "data" },
        { text: "SQL route: ANY Invoice column lookup (not just aggregates)", type: "info" },
        { text: "Route → SQL ✓", type: "check" },
      ],
    },
    { id: "q_sql", label: "SQL Generation + Self-Heal", sublabel: "≤3 attempts — Gap 11", icon: "🗃", x: 90, y: 655,
      agentName: "SQL Generation Agent (Gap 11)", agentRole: "agents/query_agent.py (SQL path)",
      activities: [
        { text: "Schema context includes: sa_alerts, status (not audit_flags) — Gap 45", type: "info" },
        { text: "LLM generates SQL (attempt 1/3)...", type: "data" },
        { text: "SQL: SELECT SUM(grand_total) FROM invoice WHERE vendor_name LIKE '%vertex%' AND tenant_id='...'", type: "data" },
        { text: "Tenant isolation regex check (Gap 20): tenant_id predicate found ✓", type: "check" },
        { text: "Mutation guard (Gap 32): no mutating keywords ✓", type: "check" },
        { text: "_normalize_string_equality: vendor_name → TRIM(LOWER(...)) (Gap 34)", type: "data" },
        { text: "Postgres execution → 1 row: {sum: 542680.00}", type: "check" },
      ],
    },
    { id: "q_synth", label: "Answer Synthesis", sublabel: "Friendly summary + citations", icon: "✍", x: 90, y: 835,
      agentName: "Answer Synthesizer", agentRole: "agents/query_agent.py (summary_prompt)",
      activities: [
        { text: "Building summary prompt with DB results + rules block...", type: "info" },
        { text: "Applying rule: 'grand_total includes freight surcharge'", type: "data" },
        { text: "LLM formats natural-language answer...", type: "info" },
        { text: "Answer: 'Your total spend with Vertex Industries is ₹5,42,680...'", type: "check" },
        { text: "Writing to Redis cache (1hr TTL) ✓", type: "check" },
      ],
    },
    { id: "q_resp", label: "Response to User", sublabel: "Markdown + saved to ChatMessage", icon: "📤", x: 90, y: 985,
      explainer: "🤖 Agent replies with a clear answer",
      agentName: "Response Handler", agentRole: "routers/chat.py",
      finalState: "done",
      activities: [
        { text: "Saving assistant reply to ChatMessage table", type: "info" },
        { text: "Returning structured JSON response ✓", type: "check" },
        { text: "Chat UI renders Markdown answer + table", type: "check" },
      ],
    },
  ],
  edges: [
    { id: "ce-user-cache", from: "q_user", to: "q_cache" },
    { id: "ce-cache-hist", from: "q_cache", to: "q_history", label: "MISS" },
    { id: "ce-cache-hit", from: "q_cache", to: "q_resp", label: "HIT ⚡", variant: "success" },
    { id: "ce-hist-rules", from: "q_history", to: "q_rules" },
    { id: "ce-rules-cls", from: "q_rules", to: "q_classify" },
    { id: "ce-cls-sql", from: "q_classify", to: "q_sql", label: "SQL" },
    { id: "ce-sql-synth", from: "q_sql", to: "q_synth" },
    { id: "ce-synth-resp", from: "q_synth", to: "q_resp", variant: "success" },
  ],
  sequence: [
    { nodeId: "q_user", edgeIds: ["ce-user-cache"] },
    { nodeId: "q_cache", edgeIds: ["ce-cache-hist"] },
    { nodeId: "q_history", edgeIds: ["ce-hist-rules"] },
    { nodeId: "q_rules", edgeIds: ["ce-rules-cls"] },
    { nodeId: "q_classify", edgeIds: ["ce-cls-sql"] },
    { nodeId: "q_sql", edgeIds: ["ce-sql-synth"] },
    { nodeId: "q_synth", edgeIds: ["ce-synth-resp"] },
    { nodeId: "q_resp", edgeIds: [] },
  ],
};

// ─── VENDOR CHAT FLOW ─────────────────────────────────────────────────────────

const VENDOR_CHAT: FlowDef = {
  id: "vendor_chat", name: "Direction-Aware Chat", badge: "SEND+RECEIVE", color: "#F59E0B",
  description: "Feature 6.1: Same query_agent.py, additive schema-description edit. Handles inbound-only, outbound-only, and combined net questions ('how much do I owe vs. how much is owed to me') in one screen.",
  nodes: [
    { id: "vc_user", label: "User Question", sublabel: "Any direction", icon: "💬", x: 90, y: 30,
      explainer: "👤 User asks a question in plain English",
      agentName: "Chat Endpoint", agentRole: "routers/chat.py::post_chat_message()",
      activities: [
        { text: "Message: 'How much do I owe vs. how much is owed to me?'", type: "data" },
        { text: "Detected: combined net question", type: "info" },
        { text: "Dispatching to run_query_agent()...", type: "info" },
      ],
    },
    { id: "vc_cache", label: "Redis Cache", sublabel: "Same — miss for new combined Q", icon: "⚡", x: 90, y: 150,
      agentName: "Cache Layer", agentRole: "agents/query_agent.py::get_cached_answer()",
      activities: [
        { text: "Cache key: combined net question → MISS", type: "warn" },
        { text: "Direction is encoded in the query text — no new key field needed", type: "info" },
      ],
    },
    { id: "vc_rules", label: "INBOUND + OUTBOUND Rules", sublabel: "Both ExtractionTemplate rows (6.1.2)", icon: "📋", x: 90, y: 270,
      agentName: "Dual-Direction Rule Injector (Feature 6.1)", agentRole: "agents/query_agent.py::_get_global_business_rules() — extended", isNew: true,
      activities: [
        { text: "Loading INBOUND Global ExtractionTemplate...", type: "info" },
        { text: "Rule: 'tax_amount = CGST + SGST summed'", type: "data" },
        { text: "Loading OUTBOUND Global ExtractionTemplate (Feature 6.1.2)...", type: "info" },
        { text: "Outbound rule: 'customer_name uses billing block, not header'", type: "data" },
        { text: "Both rule sets injected ✓", type: "check" },
      ],
    },
    { id: "vc_schema", label: "Schema + flow_direction", sublabel: "flow_direction, customer_name (6.1.1)", icon: "📝", x: 90, y: 400,
      agentName: "Schema-Aware SQL Prompt Builder (Feature 6.1)", agentRole: "agents/query_agent.py run_query_agent() SQL prompt — additive edit", isNew: true,
      activities: [
        { text: "Columns: + flow_direction VARCHAR, customer_name VARCHAR, customer_id UUID", type: "data" },
        { text: "Example pattern (net Q): SUM(CASE WHEN flow_direction='INBOUND' THEN grand_total ELSE 0 END)", type: "data" },
        { text: "Same isolation regex (Gap 20) ✓", type: "check" },
        { text: "Same 3-attempt self-repair loop (Gap 11) ✓", type: "check" },
        { text: "LLM generates combined aggregation SQL...", type: "info" },
      ],
    },
    { id: "vc_sql", label: "Combined / Net SQL", sublabel: "Conditional aggregation (CASE WHEN)", icon: "🗃", x: 90, y: 540,
      agentName: "SQL Execution (direction-aware)", agentRole: "agents/query_agent.py::execute_generated_sql()", isNew: true,
      activities: [
        { text: "SELECT SUM(CASE WHEN flow_direction='INBOUND' THEN grand_total ELSE 0 END) AS total_owed_by_us,", type: "data" },
        { text: "       SUM(CASE WHEN flow_direction='OUTBOUND' THEN grand_total ELSE 0 END) AS total_owed_to_us", type: "data" },
        { text: "FROM invoice WHERE tenant_id='...'", type: "data" },
        { text: "Result: {total_owed_by_us: 542680, total_owed_to_us: 124000}", type: "check" },
      ],
    },
    { id: "vc_synth", label: "Answer Synthesis", sublabel: "Both directions in one answer", icon: "✍", x: 90, y: 680,
      agentName: "Answer Synthesizer", agentRole: "agents/query_agent.py (summary_prompt)",
      activities: [
        { text: "Applying INBOUND + OUTBOUND rule context...", type: "info" },
        { text: "Synthesizing: 'You owe ₹5.4L to vendors (AP)'", type: "check" },
        { text: "Synthesizing: 'Customers owe you $1.24K (AR)'", type: "check" },
        { text: "Net position computed in natural language ✓", type: "check" },
      ],
    },
    { id: "vc_resp", label: "Response to User", sublabel: "Combined net answer", icon: "📤", x: 90, y: 820,
      explainer: "🤖 Agent replies with a clear answer",
      agentName: "Response Handler", agentRole: "routers/chat.py",
      finalState: "done",
      activities: [
        { text: "Returning direction-aware combined answer ✓", type: "check" },
        { text: "Inbound/outbound split visible in Markdown response", type: "info" },
        { text: "No new UI elements needed in Chat page ✓", type: "check" },
      ],
    },
  ],
  edges: [
    { id: "vce-user-cache", from: "vc_user", to: "vc_cache" },
    { id: "vce-cache-rules", from: "vc_cache", to: "vc_rules", label: "MISS" },
    { id: "vce-rules-schema", from: "vc_rules", to: "vc_schema" },
    { id: "vce-schema-sql", from: "vc_schema", to: "vc_sql", variant: "vendor" },
    { id: "vce-sql-synth", from: "vc_sql", to: "vc_synth" },
    { id: "vce-synth-resp", from: "vc_synth", to: "vc_resp", variant: "success" },
  ],
  sequence: [
    { nodeId: "vc_user", edgeIds: ["vce-user-cache"] },
    { nodeId: "vc_cache", edgeIds: ["vce-cache-rules"] },
    { nodeId: "vc_rules", edgeIds: ["vce-rules-schema"] },
    { nodeId: "vc_schema", edgeIds: ["vce-schema-sql"] },
    { nodeId: "vc_sql", edgeIds: ["vce-sql-synth"] },
    { nodeId: "vc_synth", edgeIds: ["vce-synth-resp"] },
    { nodeId: "vc_resp", edgeIds: [] },
  ],
};

const ALL_FLOWS: FlowDef[] = [INBOUND, OUTBOUND, CHAT, VENDOR_CHAT];

// ─── SVG CANVAS ───────────────────────────────────────────────────────────────

function buildPath(from: FlowNode, to: FlowNode) {
  const x1 = from.x + NW / 2, y1 = from.y + NH;
  const x2 = to.x + NW / 2, y2 = to.y;
  const mid = (y1 + y2) / 2;
  return `M${x1} ${y1} C${x1} ${mid},${x2} ${mid},${x2} ${y2}`;
}

function FlowCanvas({
  flow, nodeStates, edgePackets, onNodeClick, activeNodeId,
}: {
  flow: FlowDef;
  nodeStates: Record<string, NodeState>;
  edgePackets: Record<string, number>;
  onNodeClick: (id: string) => void;
  activeNodeId: string | null;
}) {
  const nodeMap = Object.fromEntries(flow.nodes.map((n) => [n.id, n]));

  const xs = flow.nodes.map((n) => n.x);
  const ys = flow.nodes.map((n) => n.y);
  const pad = 30;
  const minX = Math.min(...xs) - pad;
  const maxX = Math.max(...xs) + NW + pad;
  const minY = Math.min(...ys) - pad;
  const maxY = Math.max(...ys) + NH + pad;
  const svgW = maxX - minX;
  const svgH = maxY - minY;

  const tx = (x: number) => x - minX;
  const ty = (y: number) => y - minY;

  return (
    <svg viewBox={`0 0 ${svgW} ${svgH}`} width="100%" style={{ display: "block", minHeight: svgH }}>
      <defs>
        {(["normal", "success", "error", "dashed", "vendor"] as const).map((v) => (
          <marker key={v} id={`arr-${v}-${flow.id}`} markerWidth="8" markerHeight="8" refX="7" refY="3" orient="auto">
            <path d="M0,0 L0,6 L8,3 z" fill={EDGE_COLORS[v]} />
          </marker>
        ))}
        <filter id={`glow-${flow.id}`}>
          <feGaussianBlur stdDeviation="3" result="blur" />
          <feMerge><feMergeNode in="blur" /><feMergeNode in="SourceGraphic" /></feMerge>
        </filter>
      </defs>

      {/* Edge paths (referenced by animateMotion) */}
      {flow.edges.map((edge) => {
        const from = nodeMap[edge.from]; const to = nodeMap[edge.to];
        if (!from || !to) return null;
        const d = buildPath(from, to);
        const v = edge.variant ?? "normal";
        const color = EDGE_COLORS[v];
        const isActive = edgePackets[edge.id] > 0;
        return (
          <path key={edge.id} id={`path-${edge.id}`} d={d} fill="none"
            stroke={color} strokeWidth={isActive ? 2.5 : 1.5}
            strokeDasharray={v === "dashed" || v === "vendor" ? "7 4" : undefined}
            opacity={isActive ? 1 : 0.45}
            markerEnd={`url(#arr-${v}-${flow.id})`}
            style={{ transition: "opacity 0.3s, stroke-width 0.3s" }} />
        );
      })}

      {/* Edge labels */}
      {flow.edges.map((edge) => {
        if (!edge.label) return null;
        const from = nodeMap[edge.from]; const to = nodeMap[edge.to];
        if (!from || !to) return null;
        const mx = (tx(from.x) + NW / 2 + tx(to.x) + NW / 2) / 2;
        const my = (from.y + NH + to.y) / 2 - minY;
        const v = edge.variant ?? "normal";
        return (
          <text key={`lbl-${edge.id}`} x={mx + 6} y={my} fill={EDGE_COLORS[v]}
            fontSize="9.5" fontFamily="monospace" dominantBaseline="middle">{edge.label}</text>
        );
      })}

      {/* Animated packets */}
      {flow.edges.map((edge) => {
        const pCount = edgePackets[edge.id] ?? 0;
        if (pCount === 0) return null;
        const from = nodeMap[edge.from]; const to = nodeMap[edge.to];
        if (!from || !to) return null;
        const v = edge.variant ?? "normal";
        const color = EDGE_COLORS[v];
        return (
          <g key={`pkt-${edge.id}-${pCount}`} filter={`url(#glow-${flow.id})`}>
            <circle r="5" fill={color} opacity="0.9">
              <animateMotion dur="0.85s" repeatCount="1" fill="freeze">
                <mpath href={`#path-${edge.id}`} />
              </animateMotion>
              <animate attributeName="opacity" values="0;1;1;0.2" dur="0.85s" fill="freeze" />
            </circle>
            <circle r="9" fill={color} opacity="0.25">
              <animateMotion dur="0.85s" repeatCount="1" fill="freeze">
                <mpath href={`#path-${edge.id}`} />
              </animateMotion>
            </circle>
          </g>
        );
      })}

      {/* Nodes */}
      {flow.nodes.map((node) => {
        const state: NodeState = nodeStates[node.id] ?? "idle";
        const s = NODE_STYLES[state];
        const isActive = state === "active";
        const isSelected = activeNodeId === node.id;
        const x = tx(node.x); const y = ty(node.y);
        const accentColor = node.isNew ? "#F59E0B" : flow.color;
        return (
          <g key={node.id} data-node-id={node.id} transform={`translate(${x},${y})`}
            onClick={() => onNodeClick(node.id)} style={{ cursor: "pointer" }}>
            {/* Pulse ring for active */}
            {isActive && (
              <rect x={-5} y={-5} width={NW + 10} height={NH + 10} rx={12} fill="none"
                stroke={accentColor} strokeWidth={2} opacity={0.5}
                style={{ animation: "pulse-ring 1.2s ease-in-out infinite" }} />
            )}
            {/* Selection ring */}
            {isSelected && !isActive && (
              <rect x={-3} y={-3} width={NW + 6} height={NH + 6} rx={11}
                fill="none" stroke={accentColor} strokeWidth={1.5} opacity={0.7} />
            )}
            {/* Card */}
            <rect x={0} y={0} width={NW} height={NH} rx={8}
              fill={s.bg} stroke={isSelected || isActive ? accentColor : s.border}
              strokeWidth={isActive ? 1.5 : 1}
              style={{ filter: s.glow !== "none" ? `drop-shadow(${s.glow})` : undefined }} />
            {/* NEW badge */}
            {node.isNew && (
              <>
                <rect x={NW - 36} y={5} width={31} height={13} rx={3} fill="#F59E0B22" />
                <text x={NW - 20.5} y={13.5} fill="#F59E0B" fontSize="7.5" fontWeight="700" textAnchor="middle" fontFamily="Inter,sans-serif">NEW</text>
              </>
            )}
            {/* Icon */}
            <text x={11} y={23} fontSize="15" dominantBaseline="middle">{node.icon}</text>
            {/* Label */}
            <text x={33} y={20} fill={isActive ? "#E2E8F0" : s.text} fontSize="10.5"
              fontWeight="700" fontFamily="Inter,sans-serif">{node.label}</text>
            {node.sublabel && (
              <text x={33} y={35} fill="#475569" fontSize="8.5" fontFamily="Inter,sans-serif">
                {node.sublabel.length > 30 ? node.sublabel.slice(0, 29) + "…" : node.sublabel}
              </text>
            )}
            {/* State dot */}
            {state !== "idle" && (
              <circle cx={NW - 10} cy={10} r={4}
                fill={state === "active" ? accentColor : state === "done" ? "#22C55E" : state === "warn" ? "#EAB308" : "#EF4444"}
                style={isActive ? { animation: "blink 0.8s ease-in-out infinite" } : undefined} />
            )}
            {/* Gap 64: plain-language explainer bubble for human-facing
                moments (user action / agent reply / terminal outcome) --
                blinks above the node while it's active, so a non-technical
                viewer gets "user uploaded a PDF" / "agent replied" without
                having to parse the technical activity log on the right. */}
            {isActive && node.explainer && (
              <g transform="translate(0, -34)">
                <rect x={0} y={0} width={270} height={24} rx={12}
                  fill="#0B1220" stroke={accentColor} strokeWidth={1.5} />
                <circle cx={14} cy={12} r={4} fill={accentColor} style={{ animation: "blink 0.9s ease-in-out infinite" }} />
                <text x={26} y={16} fill="#E2E8F0" fontSize="10.5" fontFamily="Inter,sans-serif">
                  {node.explainer.length > 38 ? node.explainer.slice(0, 37) + "…" : node.explainer}
                </text>
              </g>
            )}
          </g>
        );
      })}
    </svg>
  );
}

// ─── AGENT PANEL ──────────────────────────────────────────────────────────────

function AgentPanel({
  node, activities, flow,
}: {
  node: FlowNode | null;
  activities: { text: string; type: ActivityType; visible: boolean }[];
  flow: FlowDef;
}) {
  const logRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (logRef.current) logRef.current.scrollTop = logRef.current.scrollHeight;
  }, [activities]);

  if (!node) {
    return (
      <div style={{ display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", height: 320, color: "#334155", textAlign: "center", gap: 10 }}>
        <span style={{ fontSize: 36 }}>🎬</span>
        <span style={{ fontSize: 13, color: "#475569" }}>Press Play to watch agents work</span>
        <span style={{ fontSize: 11, color: "#334155" }}>or click any node to inspect</span>
      </div>
    );
  }

  return (
    <div>
      {/* Agent header */}
      <div style={{ display: "flex", gap: 10, alignItems: "flex-start", marginBottom: 12 }}>
        <div style={{ fontSize: 26, lineHeight: 1, marginTop: 2 }}>{node.icon}</div>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ fontSize: 15, fontWeight: 700, color: "#E2E8F0", lineHeight: 1.3 }}>{node.agentName}</div>
          <div style={{ fontSize: 10, color: "#64748B", marginTop: 3, fontFamily: "monospace", wordBreak: "break-all" }}>{node.agentRole}</div>
          {node.isNew && (
            <span style={{ display: "inline-block", marginTop: 6, fontSize: 9, padding: "2px 7px", borderRadius: 4, background: "#F59E0B22", color: "#F59E0B", fontWeight: 700 }}>
              VENDOR FLOW — NEW
            </span>
          )}
        </div>
      </div>

      {/* Activity log */}
      <div ref={logRef} style={{ background: "#060C18", border: "1px solid #0F1E36", borderRadius: 8, padding: "12px 14px", maxHeight: 280, overflowY: "auto", fontFamily: "monospace" }}>
        <div style={{ fontSize: 9.5, color: "#1E3A5F", marginBottom: 8, borderBottom: "1px solid #0F1E36", paddingBottom: 6 }}>
          ● LIVE AGENT LOG
        </div>
        {activities.length === 0 && (
          <div style={{ color: "#1E3A5F", fontSize: 11 }}>Waiting for activation...</div>
        )}
        {activities.map((act, i) => (
          <div key={i} style={{
            display: "flex", gap: 7, marginBottom: 5, fontSize: 11, lineHeight: 1.5,
            opacity: act.visible ? 1 : 0,
            transform: act.visible ? "translateY(0)" : "translateY(4px)",
            transition: "opacity 0.25s, transform 0.25s",
          }}>
            <span style={{ color: ACTIVITY_COLORS[act.type], flexShrink: 0, width: 10, textAlign: "center" }}>
              {ACTIVITY_ICONS[act.type]}
            </span>
            <span style={{ color: act.type === "check" ? "#34D399" : act.type === "data" ? "#A78BFA" : act.type === "warn" ? "#FBBF24" : act.type === "error" ? "#F87171" : "#94A3B8" }}>
              {act.text}
            </span>
          </div>
        ))}
        {activities.length > 0 && activities[activities.length - 1].visible && (
          <div style={{ color: "#1E3A5F", fontSize: 11, marginTop: 4 }}>
            <span style={{ animation: "blink 1s infinite", display: "inline-block" }}>▌</span>
          </div>
        )}
      </div>
    </div>
  );
}

// ─── MAIN PAGE ────────────────────────────────────────────────────────────────

export default function FlowsPage() {
  const [flowId, setFlowId] = useState("inbound");
  const [nodeStates, setNodeStates] = useState<Record<string, NodeState>>({});
  const [edgePackets, setEdgePackets] = useState<Record<string, number>>({});
  const [selectedNode, setSelectedNode] = useState<string | null>(null);
  const [activeNodeId, setActiveNodeId] = useState<string | null>(null);
  const [activities, setActivities] = useState<{ text: string; type: ActivityType; visible: boolean }[]>([]);
  const [isPlaying, setIsPlaying] = useState(false);
  const [speed, setSpeed] = useState(1);
  const [stepIndex, setStepIndex] = useState(0);

  // Read URL search params (e.g. ?flow=chat or ?flow=outbound) on load
  useEffect(() => {
    if (typeof window !== "undefined") {
      const params = new URLSearchParams(window.location.search);
      const flowParam = params.get("flow") || params.get("tab") || params.get("type");
      if (flowParam) {
        const normalized = flowParam.toLowerCase().replace("-", "_");
        if (normalized === "chat" || normalized === "rag") setFlowId("chat");
        else if (normalized === "outbound" || normalized === "vendor") setFlowId("outbound");
        else if (normalized === "vendor_chat" || normalized === "direction_aware" || normalized === "direction") setFlowId("vendor_chat");
        else if (normalized === "inbound") setFlowId("inbound");
      }
    }
  }, []);

  const flow = ALL_FLOWS.find((f) => f.id === flowId) ?? INBOUND;
  const nodeMap = Object.fromEntries(flow.nodes.map((n) => [n.id, n]));
  const timeoutRefs = useRef<ReturnType<typeof setTimeout>[]>([]);
  const canvasWrapRef = useRef<HTMLDivElement>(null);

  // Gap 58/63: the canvas is much taller than its viewport (nodes run well
  // past 1000px down), so during autoplay the active node walks off-screen
  // with nothing telling the viewer to scroll -- it just looks like the
  // animation stopped. Auto-scroll the wrapper to keep the active node
  // roughly centered.
  //
  // Gap 63 fix: this originally computed the scroll target from each node's
  // raw `x`/`y` coordinates (viewBox units), assuming 1 unit = 1 CSS pixel.
  // But the SVG is `width="100%"` with no explicit `height`, so the browser
  // auto-scales height to preserve the viewBox's aspect ratio against
  // whatever width it's stretched to -- on this page that scale factor is
  // ~1.9x, not 1x. The raw-coordinate math undershot every target
  // proportionally more the further down the flow it was, so the last 1-2
  // nodes (e.g. "COMPLETED") never scrolled into view at all, even after the
  // Gap 58 fix. Reading the node's *rendered* position via
  // getBoundingClientRect() is immune to that scale factor (or any future
  // layout change) since it measures real pixels, not viewBox units.
  useEffect(() => {
    if (!isPlaying || !activeNodeId) return;
    const container = canvasWrapRef.current;
    if (!container) return;
    const target = container.querySelector(`[data-node-id="${activeNodeId}"]`);
    if (!target) return;
    const containerRect = container.getBoundingClientRect();
    const targetRect = target.getBoundingClientRect();
    const targetCenterWithinContent = (targetRect.top - containerRect.top) + container.scrollTop + targetRect.height / 2;
    const scrollTo = targetCenterWithinContent - container.clientHeight / 2;
    container.scrollTo({ top: Math.max(0, scrollTo), behavior: "smooth" });
  }, [activeNodeId, isPlaying]);

  function clearTimeouts() {
    timeoutRefs.current.forEach(clearTimeout);
    timeoutRefs.current = [];
  }

  function addTimeout(fn: () => void, ms: number) {
    const t = setTimeout(fn, ms);
    timeoutRefs.current.push(t);
    return t;
  }

  function resetFlow() {
    clearTimeouts();
    setNodeStates({});
    setEdgePackets({});
    setActiveNodeId(null);
    setActivities([]);
    setStepIndex(0);
    setIsPlaying(false);
    canvasWrapRef.current?.scrollTo({ top: 0, behavior: "smooth" });
  }

  function fireEdges(edgeIds: string[]) {
    if (edgeIds.length === 0) return;
    setEdgePackets((prev) => {
      const next = { ...prev };
      edgeIds.forEach((id) => { next[id] = (next[id] ?? 0) + 1; });
      return next;
    });
  }

  const runStep = (idx: number) => {
    const seq = flow.sequence;
    if (idx >= seq.length) {
      setIsPlaying(false);
      setActiveNodeId(null);
      return;
    }
    const step = seq[idx];
    const node = nodeMap[step.nodeId];
    if (!node) { runStep(idx + 1); return; }

    setActiveNodeId(step.nodeId);
    setSelectedNode(step.nodeId);
    setNodeStates((prev) => ({ ...prev, [step.nodeId]: "active" }));
    setActivities([]);
    setStepIndex(idx);

    const actMs = BASE_ACTIVITY_MS / speed;

    // Stream activities
    node.activities.forEach((act, i) => {
      addTimeout(() => {
        setActivities((prev) => {
          const next = [...prev];
          if (i === 0) {
            return [{ ...act, visible: false }];
          }
          return [...next, { ...act, visible: false }];
        });
        addTimeout(() => {
          setActivities((prev) => prev.map((a, ai) => (ai === i ? { ...a, visible: true } : a)));
        }, 60);
      }, i * actMs);
    });

    // After all activities: set done + fire edges + advance
    const totalMs = node.activities.length * actMs + 300 / speed;
    addTimeout(() => {
      const finalState: NodeState = node.finalState === "warn" ? "warn" : "done";
      setNodeStates((prev) => ({ ...prev, [step.nodeId]: finalState }));
      if (step.edgeIds.length > 0) {
        fireEdges(step.edgeIds);
        addTimeout(() => runStep(idx + 1), 900 / speed);
      } else {
        setIsPlaying(false);
        setActiveNodeId(null);
      }
    }, totalMs);
  };

  function handlePlay() {
    if (isPlaying) return;
    // Gap 60: the canvas wrapper sits below a ~230px header/toolbar, so on a
    // typical viewport its bottom portion starts below the fold even before
    // playback begins -- bring it fully into view the moment Play is
    // pressed, instead of relying on the viewer to notice and scroll down
    // themselves. "nearest" only moves as far as needed, so the toolbar
    // (Pause/Reset/speed controls) stays visible rather than being scrolled
    // off the top.
    canvasWrapRef.current?.scrollIntoView({ behavior: "smooth", block: "nearest" });
    // If finished, restart
    const allDone = flow.sequence.every((s) => nodeStates[s.nodeId] === "done" || nodeStates[s.nodeId] === "warn");
    if (allDone) { resetFlow(); addTimeout(() => { setIsPlaying(true); runStep(0); }, 100); return; }
    setIsPlaying(true);
    runStep(stepIndex);
  }

  function handlePause() {
    clearTimeouts();
    setIsPlaying(false);
  }

  function handleReset() { resetFlow(); }

  // Reset when flow changes
  useEffect(() => {
    resetFlow();
    setSelectedNode(null);
  }, [flowId]);

  useEffect(() => { return () => clearTimeouts(); }, []);

  const displayedNode = activeNodeId ? nodeMap[activeNodeId] : (selectedNode ? nodeMap[selectedNode] : null);

  const progress = flow.sequence.length > 0
    ? Math.round((flow.sequence.filter((s) => nodeStates[s.nodeId] === "done" || nodeStates[s.nodeId] === "warn").length / flow.sequence.length) * 100)
    : 0;

  return (
    <>
      <style>{`
        @keyframes pulse-ring { 0%,100%{opacity:0.5;transform:scale(1)} 50%{opacity:0.8;transform:scale(1.015)} }
        @keyframes blink { 0%,100%{opacity:1} 50%{opacity:0} }
        @keyframes slide-in { from{opacity:0;transform:translateY(6px)} to{opacity:1;transform:translateY(0)} }
        @keyframes hint-glow { 0%,100%{box-shadow:0 0 0 0 var(--glow-color)} 50%{box-shadow:0 0 12px 2px var(--glow-color)} }
        .flow-canvas-wrap { overflow-y: auto; }
        .flow-canvas-wrap::-webkit-scrollbar { width: 4px; }
        .flow-canvas-wrap::-webkit-scrollbar-thumb { background: #1E293B; border-radius: 2px; }
      `}</style>

      <div style={{ minHeight: "100vh", background: "linear-gradient(135deg,#060B16 0%,#0C1528 60%,#060B16 100%)", color: "#E2E8F0", fontFamily: "Inter,sans-serif", display: "flex", flexDirection: "column" }}>

        {/* ── Header ── */}
        <div style={{ borderBottom: "1px solid #131C2E", padding: "14px 24px", background: "rgba(8,13,24,0.8)", backdropFilter: "blur(12px)", position: "sticky", top: 0, zIndex: 40 }}>
          <div style={{ maxWidth: 1480, margin: "0 auto" }}>
            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12, flexWrap: "wrap" }}>
              <div>
                <h1 style={{ fontSize: 18, fontWeight: 800, letterSpacing: "-0.03em", background: "linear-gradient(90deg,#3B82F6,#F59E0B,#8B5CF6)", WebkitBackgroundClip: "text", WebkitTextFillColor: "transparent" }}>
                  System Flow Visualization
                </h1>
                <p style={{ fontSize: 11, color: "#334155", marginTop: 1 }}>Live animated agent execution · 4 flows · Inbound + Outbound (Vendor Flow) + Chat + Direction-Aware Chat</p>
              </div>

              {/* Playback controls */}
              <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                {/* Speed */}
                <div style={{ display: "flex", background: "#0C1528", border: "1px solid #1E293B", borderRadius: 8, overflow: "hidden" }}>
                  {[0.5, 1, 2, 3].map((s) => (
                    <button key={s} onClick={() => setSpeed(s)}
                      style={{ padding: "5px 9px", fontSize: 11, fontWeight: speed === s ? 700 : 400, background: speed === s ? "#1E293B" : "transparent", color: speed === s ? "#93C5FD" : "#475569", border: "none", cursor: "pointer" }}>
                      {s}×
                    </button>
                  ))}
                </div>
                <button onClick={handleReset} style={{ padding: "7px 12px", borderRadius: 7, border: "1px solid #1E293B", background: "transparent", color: "#475569", fontSize: 12, cursor: "pointer" }}>⟳</button>
                <button onClick={isPlaying ? handlePause : handlePlay}
                  style={{
                    padding: "7px 18px", borderRadius: 7, border: `1px solid ${isPlaying ? "#EF4444" : flow.color}`,
                    background: isPlaying ? "#2D0A0A" : `${flow.color}1a`, color: isPlaying ? "#F87171" : flow.color,
                    fontSize: 12.5, fontWeight: 700, cursor: "pointer", minWidth: 70,
                    // Gap 65: the hint banner alone wasn't enough -- glow the
                    // actual button being pointed at too, so the eye lands on
                    // the real target, not just the sentence about it. Uses a
                    // box-shadow pulse (not a transform:scale one) since a
                    // resizing hit-box is jumpy to click and, concretely,
                    // broke Playwright's element-stability check during
                    // verification -- a real, if narrow, signal that it's not
                    // a great interaction pattern for a clickable button.
                    ...(!isPlaying && Object.keys(nodeStates).length === 0
                      ? ({ "--glow-color": `${flow.color}90`, animation: "hint-glow 1.4s ease-in-out infinite" } as React.CSSProperties)
                      : {}),
                  }}>
                  {isPlaying ? "⏸ Pause" : "▶ Play"}
                </button>
              </div>
            </div>

            {/* Tabs */}
            <div style={{ display: "flex", gap: 5, marginTop: 12, flexWrap: "wrap" }}>
              {[
                { id: "inbound", label: "📥 Inbound Pipeline", color: "#3B82F6" },
                { id: "outbound", label: "📤 Outbound Pipeline", color: "#F59E0B" },
                { id: "chat", label: "💬 Chat / RAG Agent", color: "#8B5CF6" },
                { id: "vendor_chat", label: "🔀 Direction-Aware Chat", color: "#F59E0B" },
              ].map((t) => {
                const active = flowId === t.id;
                return (
                  <button key={t.id} onClick={() => setFlowId(t.id)}
                    style={{ padding: "6px 14px", borderRadius: 7, border: `1px solid ${active ? t.color : "#1E293B"}`, background: active ? `${t.color}18` : "rgba(12,21,40,0.6)", color: active ? t.color : "#475569", fontSize: 12, fontWeight: active ? 700 : 400, cursor: "pointer", transition: "all 0.15s" }}>
                    {t.label}
                  </button>
                );
              })}

              {/* Progress bar */}
              {progress > 0 && (
                <div style={{ marginLeft: "auto", display: "flex", alignItems: "center", gap: 8 }}>
                  <div style={{ width: 120, height: 4, background: "#0F1E36", borderRadius: 2, overflow: "hidden" }}>
                    <div style={{ width: `${progress}%`, height: "100%", background: flow.color, borderRadius: 2, transition: "width 0.5s" }} />
                  </div>
                  <span style={{ fontSize: 11, color: flow.color, fontWeight: 700 }}>{progress}%</span>
                </div>
              )}
            </div>

            {/* Gap 61: first-time guidance -- nothing on this page previously
                told a new visitor what to do; the only hint was buried in the
                AgentPanel's empty state on the right, easy to miss. Shown
                until the current flow has been played at least once. */}
            {!isPlaying && Object.keys(nodeStates).length === 0 && (
              <div style={{ marginTop: 10, padding: "8px 12px", borderRadius: 8, background: `${flow.color}12`, border: `1px solid ${flow.color}30`, fontSize: 12, color: "#94A3B8", display: "flex", alignItems: "center", gap: 8, "--glow-color": `${flow.color}80`, animation: "hint-glow 1.6s ease-in-out infinite" } as React.CSSProperties}>
                <span style={{ fontSize: 14, animation: "blink 1s ease-in-out infinite" }}>👆</span>
                <span>Pick one of the 4 flows above, then press <strong style={{ color: flow.color }}>▶ Play</strong> to watch the agents work through it step by step.</span>
              </div>
            )}
          </div>
        </div>

        {/* ── Body ── */}
        <div style={{ flex: 1, maxWidth: 1480, margin: "0 auto", width: "100%", padding: "16px 24px", display: "grid", gridTemplateColumns: "1fr 340px", gap: 16, alignItems: "start" }}>

          {/* Canvas */}
          <div ref={canvasWrapRef} className="flow-canvas-wrap" style={{ background: "rgba(8,13,24,0.6)", border: `1px solid ${flow.color}28`, borderRadius: 12, padding: "16px 20px", backdropFilter: "blur(6px)", maxHeight: "calc(100vh - 160px)", overflowY: "auto" }}>
            <div style={{ display: "flex", gap: 8, alignItems: "center", marginBottom: 10 }}>
              <span style={{ padding: "2px 8px", borderRadius: 5, background: `${flow.color}1a`, color: flow.color, fontSize: 10.5, fontWeight: 700 }}>{flow.id === "outbound" || flow.id === "vendor_chat" ? "VENDOR FLOW" : "EXISTING"}</span>
              <span style={{ fontSize: 13, fontWeight: 700, color: "#E2E8F0" }}>{flow.name}</span>
              {(flow.id === "outbound" || flow.id === "vendor_chat") && (
                <span style={{ fontSize: 10, color: "#F59E0B", opacity: 0.8 }}>
                  🟡 Nodes with NEW badge = Vendor Flow additions (spec only)
                </span>
              )}
            </div>
            <p style={{ fontSize: 11.5, color: "#475569", marginBottom: 14, lineHeight: 1.6 }}>{flow.description}</p>
            <FlowCanvas flow={flow} nodeStates={nodeStates} edgePackets={edgePackets}
              onNodeClick={(id) => { setSelectedNode(id); if (!isPlaying) setActiveNodeId(id); }}
              activeNodeId={isPlaying ? activeNodeId : selectedNode} />
          </div>

          {/* Right panel */}
          <div style={{ position: "sticky", top: 130, display: "flex", flexDirection: "column", gap: 12 }}>

            {/* Agent Activity */}
            <div style={{ background: "rgba(8,13,24,0.7)", border: `1px solid ${isPlaying ? flow.color + "50" : "#131C2E"}`, borderRadius: 10, padding: 16, transition: "border-color 0.3s" }}>
              <div style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 12 }}>
                <div style={{ width: 7, height: 7, borderRadius: "50%", background: isPlaying ? "#22C55E" : "#334155", style: isPlaying ? { animation: "blink 1s infinite" } : undefined } as React.CSSProperties} />
                <span style={{ fontSize: 10.5, fontWeight: 700, color: isPlaying ? "#22C55E" : "#334155", textTransform: "uppercase", letterSpacing: "0.09em" }}>
                  {isPlaying ? "Agent Live" : "Agent Inspector"}
                </span>
              </div>
              <AgentPanel node={displayedNode || null} activities={activities} flow={flow} />
            </div>

            {/* Legend */}
            <div style={{ background: "rgba(8,13,24,0.6)", border: "1px solid #131C2E", borderRadius: 10, padding: 14 }}>
              <p style={{ fontSize: 9.5, fontWeight: 700, color: "#334155", textTransform: "uppercase", letterSpacing: "0.1em", marginBottom: 10 }}>Legend</p>
              <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                {[
                  { color: "#3B82F6", label: "Inbound flow", dashed: false },
                  { color: "#22C55E", label: "Success path / packet", dashed: false },
                  { color: "#EF4444", label: "Error / alerts path", dashed: false },
                  { color: "#8B5CF6", label: "Optional / conditional", dashed: true },
                  { color: "#F59E0B", label: "Vendor Flow additions", dashed: true },
                ].map((item) => (
                  <div key={item.label} style={{ display: "flex", alignItems: "center", gap: 8 }}>
                    <svg width="22" height="6"><line x1="0" y1="3" x2="22" y2="3" stroke={item.color} strokeWidth="2" strokeDasharray={item.dashed ? "5 3" : undefined} /></svg>
                    <span style={{ fontSize: 11, color: "#64748B" }}>{item.label}</span>
                  </div>
                ))}
              </div>
              <div style={{ marginTop: 10, display: "grid", gridTemplateColumns: "1fr 1fr", gap: 6 }}>
                {[
                  { color: "#0F2547", border: "#3B82F6", label: "Active (processing)" },
                  { color: "#0C1F16", border: "#22C55E", label: "Done" },
                  { color: "#1F1500", border: "#EAB308", label: "Warning / Review" },
                  { color: "#131C2E", border: "#334155", label: "Idle" },
                ].map((item) => (
                  <div key={item.label} style={{ display: "flex", alignItems: "center", gap: 6 }}>
                    <div style={{ width: 14, height: 10, background: item.color, border: `1px solid ${item.border}`, borderRadius: 2, flexShrink: 0 }} />
                    <span style={{ fontSize: 10, color: "#475569" }}>{item.label}</span>
                  </div>
                ))}
              </div>
            </div>

            {/* Flow stats */}
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8 }}>
              {[
                { label: "Agents", value: flow.nodes.length, color: flow.color },
                { label: "Connections", value: flow.edges.length, color: flow.color },
                { label: "New (Vendor)", value: flow.nodes.filter((n) => n.isNew).length, color: "#F59E0B" },
                { label: "Completed", value: flow.sequence.filter((s) => nodeStates[s.nodeId] === "done" || nodeStates[s.nodeId] === "warn").length, color: "#22C55E" },
              ].map((s) => (
                <div key={s.label} style={{ background: "rgba(8,13,24,0.6)", border: "1px solid #131C2E", borderRadius: 8, padding: "10px 12px" }}>
                  <div style={{ fontSize: 22, fontWeight: 800, color: s.color }}>{s.value}</div>
                  <div style={{ fontSize: 10, color: "#334155", marginTop: 2 }}>{s.label}</div>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>
    </>
  );
}
