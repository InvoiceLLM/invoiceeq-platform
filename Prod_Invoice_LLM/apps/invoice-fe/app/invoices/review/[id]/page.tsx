"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import {
  CheckCircle,
  XCircle,
  Loader2,
  Pencil,
  AlertTriangle,
  Sparkles,
  ShieldCheck,
  X,
  Undo2,
  ChevronLeft,
  ChevronRight,
  ChevronDown,
} from "lucide-react";
import { apiClient } from "@/lib/apiClient";
import { formatCurrency } from "@/lib/utils";
import { useAuth } from "@/hooks/useAuth";
import { PageHeaderActions, usePageHeader } from "@/components/layout/PageHeaderContext";
import PdfViewerCanvas from "@/components/audit/PdfViewerCanvas";
import AlertConsole, { AlertCorrectionPreview } from "@/components/audit/AlertConsole";
import NotifyEmailPicker from "@/components/audit/NotifyEmailPicker";

interface LineItem {
  description: string;
  quantity?: number;
  unit_price?: number;
  amount: number;
}

interface InvoiceDetail {
  id: string;
  status: string;
  vendor_name: string | null;
  invoice_number: string | null;
  invoice_date: string | null;
  due_date: string | null;
  grand_total: number | null;
  subtotal: number | null;
  tax_amount: number | null;
  po_number: string | null;
  /**
   * FE Gap 183: ISO-4217 code. The backend has always returned it (this page
   * fetches the full ORM row via GET /invoices/{id}) -- the type simply never
   * declared it, so every amount on the auditor console rendered as "$"
   * regardless of what the document said.
   */
  currency?: string | null;
  /**
   * Gap 205: Extended metadata fields from full InvoiceExtractionSchema.
   */
  discount_amount?: number | null;
  discount_percent?: number | null;
  taxes?: { tax_type: string; rate_percent?: number; amount: number }[];
  discounts?: { discount_type: string; percent?: number; amount: number }[];
  tax_ids?: { id_type: string; value: string; party?: string }[];
  payment_instructions?: { method_type: string; details: string }[];
  references?: { ref_type: string; value: string }[];
  compliance_metadata?: { key: string; value: string }[];
  // FE Gap 112 item 4: `field` was always on the wire -- every producer in
  // `utils/verification_tools.py` sets it and `sa_alerts` is a raw JSON column
  // -- the FE just never declared or read it. It is what links an alert to the
  // field the auditor has to correct.
  sa_alerts: { type: string; message: string; field?: string }[];
  items: LineItem[] | null;
  field_confidence?: Record<string, number>;
  flow_direction?: string;
  /**
   * FE Gap 378 / BE Feature 27 (G11): the document type the extraction graph
   * classified this record as, plus the verbatim phrase it decided from.
   *
   * Both optional and both absent today — BE task G9 (`Invoice.doc_type` /
   * `Invoice.doc_type_evidence`) has not landed, and the columns are specified
   * nullable even once it does, so a record with no classification must render
   * exactly as it did before these fields existed. The evidence string is the
   * point of showing this at all: a misclassification is only reportable if the
   * auditor can see what the classifier read.
   */
  doc_type?: string | null;
  doc_type_evidence?: string | null;
}

interface SuggestedRule {
  scope: "global" | "existing_vendor" | "new_vendor";
  field: string;
  vendor_name: string | null;
  sample_correction: string;
}

interface StandingRuleResult {
  applied: boolean;
  reason?: string;
  rules_added?: string[];
}

// Task 7.3's correctable field set, each mapped to the Azure prebuilt-invoice
// confidence key that verify_field_confidence() (Gap 3) already populates on
// invoice.field_confidence — same mapping, kept in sync manually since this is
// display-only (Task 4.5), not a source of truth.
const CORRECTABLE_FIELDS: { key: keyof InvoiceDetail; label: string; azureKey: string; type: "text" | "date" | "number" }[] = [
  { key: "vendor_name", label: "Vendor", azureKey: "VendorName", type: "text" },
  { key: "invoice_number", label: "Invoice Number", azureKey: "InvoiceId", type: "text" },
  { key: "invoice_date", label: "Date", azureKey: "InvoiceDate", type: "date" },
  { key: "due_date", label: "Due Date", azureKey: "DueDate", type: "date" },
  { key: "po_number", label: "PO Number", azureKey: "PurchaseOrder", type: "text" },
  { key: "grand_total", label: "Total Amount", azureKey: "InvoiceTotal", type: "number" },
  { key: "tax_amount", label: "Tax Amount", azureKey: "TotalTax", type: "number" },
  // Gap 205: subtotal was always extracted but never shown in the correction panel.
  { key: "subtotal", label: "Subtotal", azureKey: "SubTotal", type: "number" },
];
const LOW_CONFIDENCE_THRESHOLD = 0.6;

/**
 * FE Gap 183: was a standalone hardcoded-USD copy of the same broken pattern
 * `lib/utils.ts::formatCurrency` had. Now delegates to the shared, fixed
 * helper and takes the invoice's real currency. The "—" for a null amount is
 * kept -- this console distinguishes "not extracted" from "zero", which the
 * shared helper (a dashboard formatter) does not.
 */
function fmt(val?: number | null, currency?: string | null) {
  if (val == null) return "—";
  return formatCurrency(val, currency);
}

/**
 * Task 4.6: click-to-edit field. Read-only until clicked; once dirty, its value
 * flows into the page's `corrections` diff instead of being sent on every save.
 * Task 4.5: an amber ring + warning icon when the backend's OCR confidence for
 * this field was below threshold — a prompt to double-check it, not an error.
 *
 * FE Gap 112 item 4 — the correction itself is now visible. Before this, an
 * edited field simply overwrote the extracted value in place and the only
 * evidence anything had changed was a 10px pencil glyph next to the label: the
 * auditor could not see what the document originally said, could not undo a
 * mistyped correction, and nothing tied the edit to the alert that prompted
 * it. Clicking a field now opens an explicit correction row — original value
 * struck through, new value editable, one-click revert — and the same staged
 * value is previewed against its linked alert in the Alerts column.
 */
function EditableField({
  label,
  value,
  originalDisplay,
  onChange,
  onRevert,
  isDirty,
  isLowConfidence,
  confidence,
  isFlagged,
  disabled,
  focusNonce,
  inputType = "text",
}: {
  label: string;
  value: string;
  /** Pre-correction value, formatted the way it is normally displayed. */
  originalDisplay: string;
  onChange: (next: string) => void;
  onRevert: () => void;
  isDirty: boolean;
  isLowConfidence: boolean;
  confidence?: number;
  /** An open alert names this field (FE Gap 112 item 4). */
  isFlagged?: boolean;
  disabled?: boolean;
  /** Bumped by the page when an alert asks to focus this field. */
  focusNonce?: number;
  inputType?: "text" | "date" | "number";
}) {
  const [editing, setEditing] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);
  const wrapRef = useRef<HTMLDivElement>(null);

  // Driven by the alert's field chip in the Alerts column. A nonce rather than
  // a boolean so clicking the same chip twice re-focuses rather than no-oping.
  useEffect(() => {
    if (focusNonce == null || disabled) return;
    setEditing(true);
    wrapRef.current?.scrollIntoView({ block: "nearest", behavior: "smooth" });
    inputRef.current?.focus();
    inputRef.current?.select();
  }, [focusNonce, disabled]);

  const showCorrection = !disabled && (editing || isDirty);

  const baseClass = "w-full rounded-lg border px-3 py-2 text-sm outline-none transition-colors";
  const stateClass = disabled
    ? "border-[#222D3D] bg-[#1E293B] text-slate-300 select-none cursor-not-allowed"
    : editing
    ? "border-blue-500 bg-[#1E293B] text-slate-100 cursor-text"
    : isDirty
    ? "border-blue-500/60 bg-blue-950/20 text-blue-100 cursor-pointer hover:border-blue-400"
    : isFlagged
    ? "border-yellow-600/60 bg-[#1E293B] text-slate-300 cursor-pointer hover:border-yellow-400"
    : isLowConfidence
    ? "border-amber-500/60 bg-[#1E293B] text-slate-300 cursor-pointer hover:border-amber-400"
    : "border-[#222D3D] bg-[#1E293B] text-slate-300 cursor-pointer hover:border-slate-500";

  return (
    <div ref={wrapRef} className="flex flex-col gap-1" data-testid={`field-${label}`}>
      <label className="text-xs font-medium text-slate-500 flex items-center gap-1.5">
        {label}
        {isDirty && (
          <span title="Corrected — will be saved on resolve/dismiss">
            <Pencil size={10} className="text-blue-400" />
          </span>
        )}
        {isFlagged && !isDirty && (
          <span title="An open alert refers to this field">
            <AlertTriangle size={10} className="text-yellow-400" />
          </span>
        )}
        {isLowConfidence && !isDirty && !isFlagged && (
          <span title={`OCR confidence ${Math.round((confidence ?? 0) * 100)}% — below the ${LOW_CONFIDENCE_THRESHOLD * 100}% review threshold`}>
            <AlertTriangle size={10} className="text-amber-400" />
          </span>
        )}
      </label>
      <input
        ref={inputRef}
        type={inputType}
        className={`${baseClass} ${stateClass}`}
        value={value}
        readOnly={disabled || !editing}
        onClick={() => !disabled && setEditing(true)}
        onFocus={() => !disabled && setEditing(true)}
        onBlur={() => setEditing(false)}
        onChange={(e) => onChange(e.target.value)}
        tabIndex={disabled ? -1 : 0}
      />
      {/* The correction, made visible. Shown from the moment the field is
          opened -- not only once it is dirty -- so the auditor can see what
          they are about to change away from while they type. */}
      {showCorrection && (
        <div
          data-testid="inline-correction"
          className="flex items-center gap-1.5 rounded-md border border-[#222D3D] bg-[#0B1220] px-2 py-1 text-[11px]"
        >
          <span className="shrink-0 text-slate-500">Extracted</span>
          <span className="min-w-0 flex-1 truncate text-slate-500 line-through" title={originalDisplay}>
            {originalDisplay || "empty"}
          </span>
          {isDirty && (
            <button
              type="button"
              onClick={onRevert}
              // onMouseDown-prevented so the input's blur doesn't close the
              // row out from under the click.
              onMouseDown={(e) => e.preventDefault()}
              className="flex shrink-0 items-center gap-1 rounded border border-slate-600/50 px-1.5 py-0.5 text-slate-400 transition hover:border-slate-400 hover:text-slate-200"
              title={`Discard the correction to ${label}`}
            >
              <Undo2 size={10} /> Revert
            </button>
          )}
        </div>
      )}
    </div>
  );
}

export default function AuditorReviewPage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  // Gap 193: Reopen Audit is Admin-only server-side; gate the button the same
  // way client-side rather than showing it to everyone and letting it 403.
  const { role } = useAuth();
  const isAdmin = role === "Admin";

  const [invoice, setInvoice] = useState<InvoiceDetail | null>(null);
  const [alerts, setAlerts] = useState<{ type: string; message: string; field?: string }[]>([]);
  // FE Gap 112 item 4: which field an alert last asked to open, and a
  // monotonic nonce so re-clicking the same alert chip re-focuses.
  const [focusRequest, setFocusRequest] = useState<{ field: string; nonce: number } | null>(null);
  const [corrections, setCorrections] = useState<Record<string, any>>({});
  const [loading, setLoading] = useState(true);
  const [actionLoading, setActionLoading] = useState<"paid" | "rejected" | null>(null);
  const [savingCorrection, setSavingCorrection] = useState(false);
  const [showRejectModal, setShowRejectModal] = useState(false);
  const [rejectReason, setRejectReason] = useState("Invoice Error");
  const [error, setError] = useState<string | null>(null);
  const [suggestedRule, setSuggestedRule] = useState<SuggestedRule | null>(null);
  // Task 4.10: "apply as standing rule" checkbox state + the backend's
  // safety-gated result (rule applied, or rejected because the re-extraction
  // check failed).
  const [applyAsStandingRule, setApplyAsStandingRule] = useState(false);
  const [standingRuleResult, setStandingRuleResult] = useState<StandingRuleResult | null>(null);
  const [notifyEmails, setNotifyEmails] = useState<string[]>([]);
  const [isAlertsExpanded, setIsAlertsExpanded] = useState(false);

  // FE Gap 272: Previous/Next between AUDIT_REQUIRED invoices, without
  // becoming the tab/queue strip that FE Gap 112 item 3 deliberately
  // rejected -- this fetches the same ordered id list the Audit Queue page
  // itself already queries (GET /invoices?status=AUDIT_REQUIRED), keeps it
  // client-side, and renders two arrow buttons rather than a row of tabs.
  // Deliberately re-fetched once per navigation (not shared/cached across
  // invoices) so approving/rejecting the current one and moving on reflects
  // an up-to-date queue rather than a stale snapshot from when the console
  // was first opened.
  const [auditQueueIds, setAuditQueueIds] = useState<string[]>([]);
  useEffect(() => {
    let cancelled = false;
    apiClient
      .get("/invoices", { params: { status: "AUDIT_REQUIRED", limit: 100 } })
      .then((res) => {
        if (cancelled) return;
        const ids = Array.isArray(res.data) ? res.data.map((inv: { id: string }) => inv.id) : [];
        setAuditQueueIds(ids);
      })
      .catch(() => {
        // Best effort -- Previous/Next just stay disabled if this fails.
      });
    return () => {
      cancelled = true;
    };
  }, [id]);
  const auditQueueIndex = auditQueueIds.indexOf(id);
  const previousAuditInvoiceId =
    auditQueueIndex > 0 ? auditQueueIds[auditQueueIndex - 1] : null;
  const nextAuditInvoiceId =
    auditQueueIndex >= 0 && auditQueueIndex < auditQueueIds.length - 1
      ? auditQueueIds[auditQueueIndex + 1]
      : null;

  const [isEditingItems, setIsEditingItems] = useState(false);
  const [editedItems, setEditedItems] = useState<LineItem[]>([]);

  const startEditingItems = () => {
    setEditedItems(invoice?.items ? JSON.parse(JSON.stringify(invoice.items)) : []);
    setIsEditingItems(true);
  };

  const updateItemField = (idx: number, field: keyof LineItem, value: any) => {
    setEditedItems((prev) =>
      prev.map((item, i) => {
        if (i !== idx) return item;
        const updated = { ...item, [field]: value };
        if (field === "quantity" || field === "unit_price") {
          const qty = updated.quantity;
          const price = updated.unit_price;
          if (qty != null && price != null) {
            updated.amount = Number((qty * price).toFixed(2));
          }
        }
        return updated;
      })
    );
  };

  const deleteLineItem = (idx: number) => {
    setEditedItems((prev) => prev.filter((_, i) => i !== idx));
  };

  const addLineItem = () => {
    setEditedItems((prev) => [
      ...prev,
      { description: "", quantity: undefined, unit_price: undefined, amount: 0 },
    ]);
  };

  const saveItems = () => {
    if (!invoice) return;
    const newItems = [...editedItems];
    const newSubtotal = newItems.reduce((acc, item) => acc + (Number(item.amount) || 0), 0);
    
    setInvoice((prev) => prev ? { ...prev, items: newItems, subtotal: newSubtotal } : null);
    setCorrections((prev) => ({
      ...prev,
      items: newItems,
      subtotal: newSubtotal,
    }));
    setIsEditingItems(false);
  };

  // FE Gap 110: this screen used to draw its own title + Back button + status
  // badge above the workspace, a second header under Shell's global one.
  // Declared before the loading/error early returns below, so the header names
  // the screen while it is still fetching rather than going blank.
  usePageHeader({
    title: "Auditor Review Console",
    agentIcon: "🛡️",
    agentName: "SENTINEL",
    agentRole: "Audit & Compliance",
    subtitle: invoice ? `Invoice #${invoice.invoice_number ?? invoice.id}` : undefined,
    // Deviation from the old `router.back()`: this route is reachable by deep
    // link (chat citations, dashboard rows, the notification bell), where
    // history-back can walk out of the app entirely. The Audit Queue is the
    // one destination that is always correct.
    backHref: "/invoices",
  });

  useEffect(() => {
    if (!id) return;
    apiClient
      .get<InvoiceDetail>(`/invoices/${id}`)
      .then((res) => {
        if (res.data.flow_direction?.toUpperCase() === "OUTBOUND") {
          router.replace(`/invoices/outbound-review/${id}`);
        } else {
          let items: LineItem[] = [];
          if (Array.isArray(res.data.items)) {
            items = res.data.items;
          } else if (typeof res.data.items === "string") {
            try {
              const parsed = JSON.parse(res.data.items);
              if (Array.isArray(parsed)) items = parsed;
            } catch {}
          }
          setInvoice({ ...res.data, items });
          setAlerts(res.data.sa_alerts ?? []);
          setLoading(false);
        }
      })
      .catch(() => {
        setError("Invoice not found or access denied.");
        setLoading(false);
      });
  }, [id, router]);

  // Current display value for a field: the in-progress correction if dirty, else the original.
  const displayValue = (key: keyof InvoiceDetail): string => {
    if (key in corrections) return corrections[key as string];
    const raw = invoice?.[key];
    if (raw == null) return "";
    if (key === "grand_total" || key === "tax_amount") return String(raw);
    return String(raw);
  };

  // Pre-correction value, rendered struck through in the inline correction row
  // and in the alert's preview. Deliberately reads `invoice`, never
  // `corrections`, so it keeps showing what was extracted no matter how many
  // times the auditor retypes the replacement.
  const originalDisplay = (key: keyof InvoiceDetail): string => {
    const raw = invoice?.[key];
    if (raw == null) return "";
    if (key === "grand_total" || key === "tax_amount") return fmt(Number(raw), invoice?.currency);
    return String(raw);
  };

  const handleFieldChange = (key: string, next: string) => {
    setCorrections((prev) => ({ ...prev, [key]: next }));
  };

  /** Discards a staged correction, restoring the extracted value. */
  const handleRevertField = (key: string) => {
    setCorrections((prev) => {
      const { [key]: _dropped, ...rest } = prev;
      return rest;
    });
  };

  /**
   * FE Gap 112 item 4 — links an alert to the correction staged against the
   * field it names.
   *
   * Returns null when the alert names no field, names one the auditor hasn't
   * touched, or names one the backend refuses corrections for. That last case
   * is Gap 112 item 6 (`subtotal`, `items`, and the line-item alert types have
   * no correction path at all, inbound or outbound) and is deliberately *not*
   * papered over here: those alerts keep the plain Dismiss they have always
   * had rather than being given a correction affordance the API would silently
   * drop. Resolving that needs the backend allowlist widened, which is still
   * an open product decision.
   */
  const resolveCorrection = useCallback(
    (alert: { field?: string }): AlertCorrectionPreview | null => {
      const field = alert.field;
      if (!field || !(field in corrections)) return null;
      const spec = CORRECTABLE_FIELDS.find((f) => f.key === field);
      if (!spec) return null;
      return {
        field,
        label: spec.label,
        oldValue: originalDisplay(spec.key),
        newValue: corrections[field],
      };
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [corrections, invoice]
  );

  /** Fields named by at least one still-open alert. */
  const flaggedFields = new Set(
    alerts.map((a) => a.field).filter((f): f is string => Boolean(f))
  );

  const handleResolve = async (targetStatus?: "PAID" | "REJECTED", reasonText?: string) => {
    if (!invoice) return;
    // Gap 53/FE 26: this can now also be called with no targetStatus and no
    // dismissed alerts -- just persisting a field correction on an invoice
    // that isn't AUDIT_REQUIRED (e.g. a COMPLETED invoice found to be
    // factually wrong despite passing every automated check). The backend's
    // PUT /audit/resolve already supported this (status/dismissed_alerts are
    // both optional) -- the "Save Correction" button below was the missing
    // entry point, not a new endpoint.
    if (targetStatus) {
      setActionLoading(targetStatus === "PAID" ? "paid" : "rejected");
    } else {
      setSavingCorrection(true);
    }
    try {
      const res = await apiClient.put(`/audit/resolve/${invoice.id}`, {
        ...(targetStatus ? { status: targetStatus } : {}),
        ...(reasonText ? { reject_reason: reasonText } : {}),
        dismissed_alerts: alerts.map((a) => a.message),
        corrections: Object.keys(corrections).length > 0 ? corrections : undefined,
        apply_as_standing_rule: applyAsStandingRule || undefined,
        ...(targetStatus && notifyEmails.length > 0 ? { notify_emails: notifyEmails } : {}),
      });
      setInvoice((prev) => (prev ? { ...prev, status: targetStatus ?? prev.status, ...corrections } : prev));
      setAlerts([]);
      setCorrections({});
      setApplyAsStandingRule(false);
      if (res.data?.suggested_rule) {
        setSuggestedRule(res.data.suggested_rule);
      }
      if (res.data?.standing_rule_result) {
        setStandingRuleResult(res.data.standing_rule_result);
      }
    } catch (err) {
      console.error("Resolve failed:", err);
    } finally {
      setActionLoading(null);
      setSavingCorrection(false);
    }
  };

  const handleSaveAsRule = () => {
    if (!suggestedRule) return;
    const params = new URLSearchParams({
      from: "audit",
      scope: suggestedRule.scope,
      correction: suggestedRule.sample_correction,
    });
    if (suggestedRule.vendor_name) params.set("vendor_name", suggestedRule.vendor_name);
    router.push(`/trainer?${params.toString()}`);
  };

  /* ── Loading / Error states ── */
  if (loading) {
    return (
      <div className="flex h-96 items-center justify-center text-slate-400">
        <Loader2 size={28} className="animate-spin" />
      </div>
    );
  }

  if (error || !invoice) {
    return (
      <div className="flex h-96 flex-col items-center justify-center gap-3 text-slate-400">
        <XCircle size={32} className="text-red-400" />
        <p>{error ?? "Something went wrong."}</p>
      </div>
    );
  }

  const isResolved = ["PAID", "REJECTED"].includes(invoice.status);
  const hasUnsavedCorrections = Object.keys(corrections).length > 0;

  return (
    <div className="flex h-full flex-col gap-4 p-6 overflow-y-auto custom-scrollbar">
        {/* FE Gap 110: title/subtitle/Back all moved into the shared header
            above; the live status badge rides up there too rather than holding
            a row down here.

            FE Gap 112 item 2: Mark Paid / Reject join it. They used to be two
            full-width, py-3 buttons stacked at the bottom of the details
            column -- the visually heaviest thing on a screen whose actual work
            is reading the PDF and correcting fields, and (being last in a
            scrolling column) frequently below the fold. As a compact pair in
            the header they are always reachable and sized like what they are:
            the two terminal actions, not the main content. */}
        <PageHeaderActions>
          {/* FE Gap 272: Previous/Next through the AUDIT_REQUIRED queue,
              without leaving the review console. Disabled at either end of
              the list, or entirely if this invoice isn't part of it (e.g.
              opened via a chat citation or the notification bell rather than
              from the Audit Queue itself). */}
          <div className="flex items-center gap-1">
            <button
              type="button"
              onClick={() => previousAuditInvoiceId && router.push(`/invoices/review/${previousAuditInvoiceId}`)}
              disabled={!previousAuditInvoiceId}
              title="Previous audit-required invoice"
              aria-label="Previous audit-required invoice"
              className="flex items-center justify-center rounded-lg border border-[#222D3D] p-1 sm:p-1.5 text-slate-400 transition hover:bg-[#1E293B] hover:text-slate-200 disabled:cursor-not-allowed disabled:opacity-30 disabled:hover:bg-transparent"
            >
              <ChevronLeft size={14} />
            </button>
            {auditQueueIndex >= 0 && (
              <span className="hidden text-[10px] text-slate-500 sm:inline whitespace-nowrap">
                {auditQueueIndex + 1} of {auditQueueIds.length}
              </span>
            )}
            <button
              type="button"
              onClick={() => nextAuditInvoiceId && router.push(`/invoices/review/${nextAuditInvoiceId}`)}
              disabled={!nextAuditInvoiceId}
              title="Next audit-required invoice"
              aria-label="Next audit-required invoice"
              className="flex items-center justify-center rounded-lg border border-[#222D3D] p-1 sm:p-1.5 text-slate-400 transition hover:bg-[#1E293B] hover:text-slate-200 disabled:cursor-not-allowed disabled:opacity-30 disabled:hover:bg-transparent"
            >
              <ChevronRight size={14} />
            </button>
          </div>
          <span
            className={`rounded-full border px-2 sm:px-3 py-0.5 sm:py-1 text-[10px] sm:text-xs font-medium whitespace-nowrap ${
              invoice.status === "PAID"
                ? "border-emerald-600/50 bg-emerald-500/10 text-emerald-300"
                : invoice.status === "REJECTED"
                ? "border-red-600/50 bg-red-500/10 text-red-300"
                : invoice.status === "AUDIT_REQUIRED"
                ? "border-yellow-600/50 bg-yellow-500/10 text-yellow-300"
                : "border-slate-600/50 bg-slate-700/30 text-slate-300"
            }`}
          >
            {invoice.status.replace("_", " ")}
          </span>
          {/* Gap 193: Reopen Audit / Undo Decision button for Admins when invoice is terminal (PAID or REJECTED) */}
          {isResolved && isAdmin && (
            <button
              onClick={async () => {
                if (!window.confirm("Reopen this invoice for audit? Its status will be reset to AUDIT_REQUIRED.")) return;
                try {
                  await apiClient.put(`/audit/resolve/${invoice.id}`, {
                    status: "AUDIT_REQUIRED",
                    dismissed_alerts: [],
                  });
                  setInvoice((prev) => prev ? { ...prev, status: "AUDIT_REQUIRED" } : prev);
                  setAlerts(invoice.sa_alerts ?? []);
                } catch (err: any) {
                  console.error("Reopen failed:", err);
                  window.alert(err?.message || "Failed to reopen invoice. Please try again.");
                }
              }}
              className="flex items-center gap-1.5 whitespace-nowrap rounded-lg border border-amber-500/50 bg-amber-600/10 px-2 sm:px-3 py-1 sm:py-1.5 text-[10px] sm:text-xs font-semibold text-amber-300 transition hover:bg-amber-600/30"
            >
              <Undo2 size={13} />
              Reopen Audit
            </button>
          )}
          {!isResolved && (
            <div className="flex items-center gap-2">
              <button
                onClick={() => setShowRejectModal(true)}
                disabled={!!actionLoading}
                className="flex items-center gap-1.5 whitespace-nowrap rounded-lg border border-red-500/50 bg-red-600/10 px-2 sm:px-3 py-1 sm:py-1.5 text-[10px] sm:text-xs font-semibold text-red-300 transition hover:bg-red-600/30 disabled:opacity-50"
              >
                {actionLoading === "rejected" ? (
                  <Loader2 size={13} className="animate-spin" />
                ) : (
                  <XCircle size={13} />
                )}
                Reject
              </button>
              <button
                onClick={() => handleResolve("PAID")}
                disabled={!!actionLoading}
                className="flex items-center gap-1.5 whitespace-nowrap rounded-lg border border-emerald-500/50 bg-emerald-600/20 px-2 sm:px-3 py-1 sm:py-1.5 text-[10px] sm:text-xs font-semibold text-emerald-300 transition hover:bg-emerald-600/40 disabled:opacity-50"
              >
                {actionLoading === "paid" ? (
                  <Loader2 size={13} className="animate-spin" />
                ) : (
                  <CheckCircle size={13} />
                )}
                Approve Invoice
              </button>
            </div>
          )}
        </PageHeaderActions>

        {!isResolved && (
          <NotifyEmailPicker emailSet="inbound" selected={notifyEmails} onChange={setNotifyEmails} />
        )}

        {/* Task 4.7: Rule Suggestion Prompt — surfaced after a correction pattern
            recurred enough times (Task 7.4) to be worth automating. */}
        {suggestedRule && (
          <div className="flex items-center gap-3 rounded-xl border border-purple-500/40 bg-purple-950/20 px-4 py-3">
            <Sparkles size={18} className="shrink-0 text-purple-300" />
            <div className="flex-1 text-sm text-purple-100">
              <p className="font-medium">Want to save this as a rule?</p>
              <p className="text-xs text-purple-300/80 mt-0.5">
                You've corrected <strong>{suggestedRule.field}</strong>{" "}
                {suggestedRule.scope === "global" ? "across several vendors" : `for ${suggestedRule.vendor_name}`}{" "}
                a few times now — teach the AI Trainer so it stops needing manual fixes.
              </p>
            </div>
            <button
              onClick={handleSaveAsRule}
              className="shrink-0 rounded-lg bg-purple-600 hover:bg-purple-500 text-white text-xs font-semibold px-3 py-2 transition-colors"
            >
              Open Trainer
            </button>
            <button
              onClick={() => setSuggestedRule(null)}
              className="shrink-0 text-purple-300/60 hover:text-purple-200 text-xs"
            >
              Dismiss
            </button>
          </div>
        )}

        {/* FE Gap 112 item 1 — PDF | Fields | Alerts, three real columns, the
            same left-to-right order Trainer uses (PDF → Extracted Fields →
            Chat). This was `grid-cols-2`: the PDF on the left and *everything
            else* -- alerts, the seven-field correction form, the line-item
            table, the standing-rule controls and the finalize buttons --
            stacked into one scrolling right-hand column, so the two things an
            auditor has to compare (the alert and the field it refers to) were
            usually not on screen at the same time.
        {/* FE Gap 112 item 3: there is deliberately no invoice tab/queue strip
            above this grid. One was drawn during the mockup pass and rejected
            -- this route renders exactly one invoice (`/invoices/review/[id]`)
            and the Audit Queue is the place to move between them. Confirmed
            absent in code as well */}



        {/* 3-COLUMN SPLIT LAYOUT: PDF (40%) | Extracted Fields (30%) | Line Items & Alerts (30%) */}
        <div className="grid grid-cols-1 gap-4 xl:grid-cols-[minmax(0,1.15fr)_minmax(0,0.85fr)_minmax(0,1fr)] flex-1">
          {/* COLUMN 1 (40% width) — PDF Viewer */}
          <PdfViewerCanvas
            invoiceId={invoice.id}
            title={`Invoice ${invoice.invoice_number ?? invoice.id}`}
            status={invoice.status}
          />

          {/* COLUMN 2 (30% width) — Extracted Fields & Metadata */}
          <section
            data-testid="fields-panel"
            className="flex flex-col rounded-xl border border-[#222D3D] bg-[#0F172A] overflow-hidden"
          >
            <div className="flex items-center justify-between gap-2 bg-[#0B1220] px-4 py-2.5 border-b border-[#222D3D]">
              <p className="text-xs font-semibold uppercase tracking-widest text-slate-400">
                Extracted Fields
              </p>
              <span className="shrink-0 rounded-md border border-[#222D3D] px-2 py-0.5 text-[11px] text-slate-500">
                {isResolved ? "Resolved — read-only" : "Click to edit"}
              </span>
            </div>

            <div className="flex flex-1 flex-col gap-4 overflow-y-auto custom-scrollbar p-4">
              <div className="flex flex-col gap-3">
                {CORRECTABLE_FIELDS.map(({ key, label, azureKey, type }) => {
                  const confidence = invoice.field_confidence?.[azureKey];
                  const isLowConfidence = confidence != null && confidence < LOW_CONFIDENCE_THRESHOLD;
                  const rawValue = displayValue(key);
                  const displayed =
                    type === "number" && !(key in corrections)
                      ? fmt(rawValue ? Number(rawValue) : null, invoice.currency)
                      : rawValue;
                  return (
                    <EditableField
                      key={key as string}
                      label={label}
                      value={displayed}
                      originalDisplay={originalDisplay(key)}
                      onChange={(next) => handleFieldChange(key as string, next)}
                      onRevert={() => handleRevertField(key as string)}
                      isDirty={key in corrections}
                      isLowConfidence={isLowConfidence}
                      confidence={confidence}
                      isFlagged={flaggedFields.has(key as string)}
                      disabled={isResolved}
                      focusNonce={
                        focusRequest?.field === (key as string) ? focusRequest.nonce : undefined
                      }
                      inputType={type}
                    />
                  );
                })}
              </div>

              {/* Additional Extracted Metadata Panel */}
              {(invoice.taxes?.length || invoice.discounts?.length || invoice.tax_ids?.length || invoice.payment_instructions?.length || invoice.references?.length || invoice.compliance_metadata?.length || invoice.currency || invoice.doc_type) && (
                <div
                  data-testid="extracted-metadata-panel"
                  className="flex flex-col gap-2 rounded-xl border border-[#222D3D] bg-[#0B1220] p-3"
                >
                  <p className="text-[10px] font-bold uppercase tracking-widest text-slate-500">Additional Extracted Metadata</p>

                  {/* FE Gap 378 / BE Feature 27 (G11): document type + the
                      phrase the classifier decided from. Rendered only when the
                      backend actually returned a type — absent (every record
                      today, since BE G9 hasn't landed) leaves this panel
                      identical to before, including its visibility, because
                      `doc_type` is part of the panel's own gate above.
                      The evidence line renders separately: a type can exist
                      without one (the deterministic synonym pass records the
                      matched phrase, but a low-confidence fallback lands on
                      OTHER with no phrase to quote). */}
                  {invoice.doc_type && (
                    <div data-testid="doc-type-row" className="flex justify-between gap-3 text-xs">
                      <span className="min-w-0 break-words text-slate-500">Document Type</span>
                      <span className="min-w-0 break-all text-right font-mono text-slate-300">{invoice.doc_type}</span>
                    </div>
                  )}

                  {invoice.doc_type && invoice.doc_type_evidence && (
                    <div data-testid="doc-type-evidence-row" className="flex justify-between gap-3 text-xs">
                      <span className="min-w-0 break-words text-slate-500">Type Evidence</span>
                      <span className="min-w-0 break-all text-right font-mono text-slate-400" title={invoice.doc_type_evidence}>
                        &ldquo;{invoice.doc_type_evidence}&rdquo;
                      </span>
                    </div>
                  )}

                  {invoice.currency && (
                    <div className="flex justify-between gap-3 text-xs">
                      <span className="min-w-0 break-words text-slate-500">Currency</span>
                      <span className="min-w-0 break-all text-right font-mono text-slate-300">{invoice.currency}</span>
                    </div>
                  )}

                  {(invoice.discount_amount != null || invoice.discount_percent != null) && (
                    <div className="flex justify-between gap-3 text-xs">
                      <span className="min-w-0 break-words text-slate-500">Invoice Discount</span>
                      <span className="min-w-0 break-all text-right font-mono text-slate-300">
                        {invoice.discount_percent != null ? `${invoice.discount_percent}%` : ""}
                        {invoice.discount_amount != null ? ` (${fmt(invoice.discount_amount, invoice.currency)})` : ""}
                      </span>
                    </div>
                  )}

                  {invoice.tax_ids && invoice.tax_ids.length > 0 && (
                    <div className="flex flex-col gap-1">
                      <span className="text-[10px] uppercase tracking-wide text-slate-500">Tax IDs</span>
                      {invoice.tax_ids.map((t, i) => (
                        <div key={i} className="flex justify-between gap-3 text-xs">
                          <span className="min-w-0 break-words text-slate-500">{t.id_type}{t.party ? ` (${t.party})` : ""}</span>
                          <span className="min-w-0 break-all text-right font-mono text-slate-300">{t.value}</span>
                        </div>
                      ))}
                    </div>
                  )}

                  {invoice.taxes && invoice.taxes.length > 0 && (
                    <div className="flex flex-col gap-1">
                      <span className="text-[10px] uppercase tracking-wide text-slate-500">Tax Breakdown</span>
                      {invoice.taxes.map((t, i) => (
                        <div key={i} className="flex justify-between gap-3 text-xs">
                          <span className="min-w-0 break-words text-slate-500">{t.tax_type}{t.rate_percent != null ? ` ${t.rate_percent}%` : ""}</span>
                          <span className="min-w-0 break-all text-right font-mono text-slate-300">{fmt(t.amount, invoice.currency)}</span>
                        </div>
                      ))}
                    </div>
                  )}

                  {invoice.payment_instructions && invoice.payment_instructions.length > 0 && (
                    <div className="flex flex-col gap-1">
                      <span className="text-[10px] uppercase tracking-wide text-slate-500">Payment Instructions</span>
                      {invoice.payment_instructions.map((p, i) => (
                        <div key={i} className="flex min-w-0 flex-col text-xs">
                          <span className="break-words text-slate-500">{p.method_type}</span>
                          <span className="font-mono text-slate-400 break-all">{p.details}</span>
                        </div>
                      ))}
                    </div>
                  )}

                  {invoice.references && invoice.references.length > 0 && (
                    <div className="flex flex-col gap-1">
                      <span className="text-[10px] uppercase tracking-wide text-slate-500">References</span>
                      {invoice.references.map((r, i) => (
                        <div key={i} className="flex justify-between gap-3 text-xs">
                          <span className="min-w-0 break-words text-slate-500">{r.ref_type}</span>
                          <span className="min-w-0 break-all text-right font-mono text-slate-300">{r.value}</span>
                        </div>
                      ))}
                    </div>
                  )}

                  {invoice.discounts && invoice.discounts.length > 0 && (
                    <div className="flex flex-col gap-1">
                      <span className="text-[10px] uppercase tracking-wide text-slate-500">Discount Breakdown</span>
                      {invoice.discounts.map((d, i) => (
                        <div key={i} className="flex justify-between gap-3 text-xs">
                          <span className="min-w-0 break-words text-slate-500">{d.discount_type}{d.percent != null ? ` ${d.percent}%` : ""}</span>
                          <span className="min-w-0 break-all text-right font-mono text-slate-300">{fmt(d.amount, invoice.currency)}</span>
                        </div>
                      ))}
                    </div>
                  )}

                  {invoice.compliance_metadata && invoice.compliance_metadata.length > 0 && (
                    <div className="flex flex-col gap-1">
                      <span className="text-[10px] uppercase tracking-wide text-slate-500">Compliance / e-Invoice</span>
                      {invoice.compliance_metadata.map((c, i) => (
                        <div key={i} className="flex justify-between gap-3 text-xs">
                          <span className="min-w-0 break-words text-slate-500">{c.key}</span>
                          <span className="min-w-0 break-all text-right font-mono text-slate-300">{c.value}</span>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              )}
            </div>

            {/* Pinned Corrections Footer */}
            {hasUnsavedCorrections && !isResolved && (
              <div className="shrink-0 border-t border-[#222D3D] p-3 bg-[#0F172A]">
                <div className="flex flex-col gap-2 rounded-lg border border-blue-600/40 bg-blue-950/20 px-3 py-2 text-xs text-blue-200">
                  <div className="flex items-center justify-between gap-2">
                    <span className="flex items-center gap-2">
                      <Pencil size={12} />
                      {Object.keys(corrections).length} field(s) corrected
                    </span>
                    <button
                      onClick={() => handleResolve()}
                      disabled={!!actionLoading || savingCorrection}
                      className="shrink-0 rounded-md border border-blue-500/50 bg-blue-600/20 px-2.5 py-1 text-xs font-semibold text-blue-200 transition hover:bg-blue-600/40 disabled:opacity-50"
                    >
                      {savingCorrection ? "Saving..." : "Save Correction"}
                    </button>
                  </div>
                  {invoice.vendor_name && (
                    <label className="flex cursor-pointer items-center gap-2 text-blue-300/90">
                      <input
                        type="checkbox"
                        checked={applyAsStandingRule}
                        onChange={(e) => setApplyAsStandingRule(e.target.checked)}
                        className="h-3.5 w-3.5 rounded border-blue-500/50 bg-transparent accent-blue-500"
                      />
                      Apply this correction as a standing rule for {invoice.vendor_name}?
                    </label>
                  )}
                </div>
              </div>
            )}
            {isResolved && (
              <div className="shrink-0 border-t border-[#222D3D] p-3 bg-[#0F172A] flex items-center gap-2 text-sm text-slate-400">
                <CheckCircle size={16} className="text-emerald-400" />
                Resolved as <strong className="ml-1 text-slate-200">{invoice.status}</strong>.
              </div>
            )}
          </section>

          {/* COLUMN 3 (30% width) — Discrepancy Warnings & Line Items Table */}
          <section data-testid="column-3-panel" className="flex flex-col gap-4">
            {/* Discrepancy Warnings Card */}
            <div
              data-testid="alerts-banner"
              className="flex flex-col rounded-xl border border-yellow-700/50 bg-[#0F172A] overflow-hidden shrink-0"
            >
              <button
                type="button"
                onClick={() => setIsAlertsExpanded((prev) => !prev)}
                className="flex items-center justify-between gap-3 px-4 py-2.5 bg-yellow-950/20 hover:bg-yellow-950/30 transition-colors text-left"
              >
                <div className="flex items-center gap-3">
                  <span className="rounded-full border border-[#10B981]/30 bg-[#10B981]/10 px-2.5 py-0.5 font-mono text-xs font-semibold tracking-wider text-[#10B981]">
                    SENTINEL
                  </span>
                  {alerts.length > 0 ? (
                    <span className="shrink-0 rounded-md border border-yellow-700/50 bg-yellow-950/40 px-2 py-0.5 text-[11px] font-medium text-yellow-300">
                      {alerts.length} open alert{alerts.length === 1 ? "" : "s"}
                    </span>
                  ) : (
                    <span className="shrink-0 rounded-md border border-emerald-700/50 bg-emerald-950/40 px-2 py-0.5 text-[11px] font-medium text-emerald-300">
                      No alerts
                    </span>
                  )}
                </div>
                <div className="flex items-center gap-1.5 text-xs font-medium text-slate-400 hover:text-slate-200 transition-colors">
                  <span>{isAlertsExpanded || alerts.length > 0 ? "Collapse" : "Expand alerts"}</span>
                  <ChevronDown
                    size={14}
                    className={`transition-transform duration-200 ${isAlertsExpanded || alerts.length > 0 ? "rotate-180" : ""}`}
                  />
                </div>
              </button>

              {(isAlertsExpanded || alerts.length > 0) && (
                <div className="border-t border-[#222D3D] p-4 max-h-[300px] overflow-y-auto custom-scrollbar">
                  <AlertConsole
                    invoiceId={invoice.id}
                    alerts={alerts}
                    currentStatus={invoice.status}
                    onAlertsChange={setAlerts}
                    corrections={corrections}
                    applyAsStandingRule={applyAsStandingRule}
                    resolveCorrection={resolveCorrection}
                    onFocusField={(field) =>
                      setFocusRequest((prev) => ({ field, nonce: (prev?.nonce ?? 0) + 1 }))
                    }
                    onDismissed={(res) => {
                      if (Object.keys(corrections).length > 0) {
                        setInvoice((prev) => (prev ? { ...prev, ...corrections } : prev));
                        setCorrections({});
                      }
                      setApplyAsStandingRule(false);
                      if (res?.suggested_rule) setSuggestedRule(res.suggested_rule);
                      if (res?.standing_rule_result) setStandingRuleResult(res.standing_rule_result);
                    }}
                  />

                  {standingRuleResult && (
                    <div
                      className={`mt-3 flex items-start gap-2 rounded-lg border px-3 py-2 text-xs ${
                        standingRuleResult.applied
                          ? "border-emerald-600/40 bg-emerald-950/20 text-emerald-200"
                          : "border-amber-600/40 bg-amber-950/20 text-amber-200"
                      }`}
                    >
                      <ShieldCheck size={14} className="mt-0.5 shrink-0" />
                      <div className="flex-1">
                        {standingRuleResult.applied ? (
                          <>
                            <p className="font-medium">Standing rule applied.</p>
                            {standingRuleResult.rules_added?.map((r, i) => (
                              <p key={i} className="text-emerald-300/80 mt-0.5">{r}</p>
                            ))}
                          </>
                        ) : (
                          <p>{standingRuleResult.reason || "Rule not applied."}</p>
                        )}
                      </div>
                      <button
                        onClick={() => setStandingRuleResult(null)}
                        className="shrink-0 text-current opacity-60 hover:opacity-100"
                      >
                        <X size={12} />
                      </button>
                    </div>
                  )}
                </div>
              )}
            </div>

            {/* Line Items Card */}
            <div
              data-testid="line-items-panel"
              className="flex flex-col rounded-xl border border-[#222D3D] bg-[#0F172A] overflow-hidden flex-1"
            >
            <div className="flex items-center justify-between gap-2 bg-[#0B1220] px-4 py-2.5 border-b border-[#222D3D] shrink-0">
              <div className="flex items-center gap-2 flex-wrap">
                <p className="text-xs font-semibold uppercase tracking-widest text-slate-400">
                  Line Items
                </p>
                <span className="rounded bg-slate-800 px-2 py-0.5 font-mono text-[11px] text-slate-300 border border-slate-700">
                  {(isEditingItems ? editedItems : (invoice.items ?? [])).length} items
                </span>
                <span className="rounded bg-blue-950/40 px-2 py-0.5 font-mono text-[11px] text-blue-300 border border-blue-800/40">
                  Subtotal: {fmt((isEditingItems ? editedItems : (invoice.items ?? [])).reduce((s, i) => s + (i.amount ?? 0), 0), invoice.currency)}
                </span>
              </div>

              {!isResolved && (
                isEditingItems ? (
                  <div className="flex gap-2 shrink-0">
                    <button
                      onClick={saveItems}
                      className="rounded bg-emerald-600 px-2 py-1 text-xs font-semibold text-white hover:bg-emerald-500 transition-colors"
                    >
                      Save Items
                    </button>
                    <button
                      onClick={() => setIsEditingItems(false)}
                      className="rounded bg-slate-700 px-2 py-1 text-xs font-semibold text-white hover:bg-slate-650 transition-colors"
                    >
                      Cancel
                    </button>
                  </div>
                ) : (
                  <button
                    onClick={startEditingItems}
                    className="flex items-center gap-1 rounded bg-[#3B82F6] px-2 py-1 text-xs font-semibold text-white hover:bg-blue-500 transition-colors shrink-0"
                  >
                    <Pencil size={12} />
                    Edit Items
                  </button>
                )
              )}
            </div>

            <div className="flex-1 overflow-auto custom-scrollbar p-3">
              {isEditingItems ? (
                <table className="w-full border-collapse text-left">
                  <thead>
                    <tr className="border-b border-[#222D3D] text-[10px] uppercase tracking-wide text-slate-500">
                      <th className="pb-2 pr-2 font-medium w-6">#</th>
                      <th className="pb-2 pr-2 font-medium">Description</th>
                      <th className="pb-2 pr-2 text-right font-medium w-14">Qty</th>
                      <th className="pb-2 pr-2 text-right font-medium w-20">Unit Price</th>
                      <th className="pb-2 text-right font-medium w-20">Total</th>
                      <th className="pb-2 text-center font-medium w-8">Del</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-[#222D3D]/60">
                    {editedItems.map((item, idx) => (
                      <tr key={idx} className="text-xs text-slate-300">
                        <td className="py-2 pr-2 text-slate-500 align-middle">{idx + 1}</td>
                        <td className="py-2 pr-2 align-middle">
                          <input
                            type="text"
                            value={item.description}
                            onChange={(e) => updateItemField(idx, "description", e.target.value)}
                            className="w-full rounded border border-[#222D3D] bg-[#1E293B] px-2 py-1 text-xs text-slate-200 focus:border-blue-500 outline-none"
                          />
                        </td>
                        <td className="py-2 pr-2 align-middle">
                          <input
                            type="number"
                            value={item.quantity ?? ""}
                            onChange={(e) => {
                              const qty = e.target.value === "" ? undefined : Number(e.target.value);
                              updateItemField(idx, "quantity", qty);
                            }}
                            className="w-full rounded border border-[#222D3D] bg-[#1E293B] px-2 py-1 text-xs text-slate-200 text-right focus:border-blue-500 outline-none"
                          />
                        </td>
                        <td className="py-2 pr-2 align-middle">
                          <input
                            type="number"
                            step="0.01"
                            value={item.unit_price ?? ""}
                            onChange={(e) => {
                              const price = e.target.value === "" ? undefined : Number(e.target.value);
                              updateItemField(idx, "unit_price", price);
                            }}
                            className="w-full rounded border border-[#222D3D] bg-[#1E293B] px-2 py-1 text-xs text-slate-200 text-right focus:border-blue-500 outline-none"
                          />
                        </td>
                        <td className="py-2 align-middle text-right">
                          <input
                            type="number"
                            step="0.01"
                            value={item.amount}
                            onChange={(e) => updateItemField(idx, "amount", Number(e.target.value))}
                            className="w-full rounded border border-[#222D3D] bg-[#1E293B] px-2 py-1 text-xs text-slate-200 text-right focus:border-blue-500 outline-none"
                          />
                        </td>
                        <td className="py-2 text-center align-middle">
                          <button
                            onClick={() => deleteLineItem(idx)}
                            className="text-rose-500 hover:text-rose-400 p-1 transition-colors"
                          >
                            <X size={14} />
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                  <tfoot>
                    <tr className="border-t border-[#222D3D]">
                      <td colSpan={6} className="pt-3">
                        <button
                          onClick={addLineItem}
                          className="text-xs text-blue-400 hover:text-blue-300 font-semibold"
                        >
                          + Add Line Item
                        </button>
                      </td>
                    </tr>
                    <tr className="border-t border-[#222D3D]">
                      <td colSpan={4} className="pt-2 text-xs text-slate-500">
                        Subtotal
                      </td>
                      <td className="pt-2 text-right text-xs font-medium text-slate-300">
                        {fmt(editedItems.reduce((s, i) => s + (i.amount ?? 0), 0), invoice.currency)}
                      </td>
                      <td></td>
                    </tr>
                  </tfoot>
                </table>
              ) : (
                invoice.items && invoice.items.length > 0 ? (
                  <table className="w-full border-collapse text-left">
                    <thead>
                      <tr className="border-b border-[#222D3D] text-[10px] uppercase tracking-wide text-slate-500">
                        <th className="pb-2 pr-2 font-medium">#</th>
                        <th className="pb-2 pr-2 font-medium">Description</th>
                        <th className="pb-2 pr-2 text-right font-medium">Qty</th>
                        <th className="pb-2 pr-2 text-right font-medium">Unit Price</th>
                        <th className="pb-2 text-right font-medium">Total</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-[#222D3D]/60">
                      {invoice.items.map((item, idx) => (
                        <tr key={idx} className="text-xs text-slate-300">
                          <td className="py-2 pr-2 text-slate-500">{idx + 1}</td>
                          <td className="py-2 pr-2">{item.description}</td>
                          <td className="py-2 pr-2 text-right text-slate-400">
                            {item.quantity ?? "—"}
                          </td>
                          <td className="py-2 pr-2 text-right text-slate-400">
                            {item.unit_price != null ? fmt(item.unit_price, invoice.currency) : "—"}
                          </td>
                          <td className="py-2 text-right font-medium text-slate-200">
                            {fmt(item.amount, invoice.currency)}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                    <tfoot>
                      <tr className="border-t border-[#222D3D]">
                        <td colSpan={4} className="pt-2 text-xs text-slate-500">
                          Subtotal
                        </td>
                        <td className="pt-2 text-right text-xs font-medium text-slate-300">
                          {fmt(invoice.items.reduce((s, i) => s + (i.amount ?? 0), 0), invoice.currency)}
                        </td>
                      </tr>
                    </tfoot>
                  </table>
                ) : (
                  <p className="text-xs text-slate-500 italic py-4">No line items extracted.</p>
                )
              )}
            </div>
          </div>
        </section>
      </div>

        {showRejectModal && (
          <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm">
            <div className="glass-panel w-full max-w-md p-6 rounded-2xl border border-slate-700/50 bg-[#0F172A]/90 shadow-2xl flex flex-col gap-4">
              <div>
                <h3 className="text-lg font-bold text-white">Reject Invoice</h3>
                <p className="text-xs text-slate-400 mt-1">Please select the reason for rejecting this invoice to help track AI performance metrics.</p>
              </div>

              <div className="flex flex-col gap-2">
                <label className="text-xs font-semibold text-slate-300">Rejection Reason</label>
                <select
                  value={rejectReason}
                  onChange={(e) => setRejectReason(e.target.value)}
                  className="w-full bg-[#1E293B] border border-[#222D3D] rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-blue-500"
                >
                  <option value="Invoice Error">Invoice Error (Errors on the source document itself)</option>
                  <option value="AI Extraction Error">AI Extraction Error (Missed / incorrect AI extraction)</option>
                  <option value="AI Field Extraction Error">AI Field Extraction Error (Wrong total/dates/vendor)</option>
                  <option value="AI Line Items Error">AI Line Items Error (Wrong description/qty/prices)</option>
                  <option value="AI Classification Error">AI Classification Error (Incorrect template match)</option>
                  <option value="Other AI Error">Other AI Error (General extraction failure)</option>
                  <option value="Business Logic Error">Business Logic Error (Duplicate / Invalid business vendor)</option>
                  <option value="Illegible Document">Illegible Document (Blurred PDF / Corrupted file)</option>
                  <option value="Other Non-AI Error">Other Non-AI Error</option>
                </select>
              </div>

              <div className="flex items-center justify-end gap-3 mt-2">
                <button
                  onClick={() => setShowRejectModal(false)}
                  className="px-4 py-2 text-sm font-medium text-slate-300 hover:text-white transition"
                >
                  Cancel
                </button>
                <button
                  onClick={() => {
                    setShowRejectModal(false);
                    handleResolve("REJECTED", rejectReason);
                  }}
                  className="px-4 py-2 bg-red-600 hover:bg-red-700 text-sm font-semibold text-white rounded-lg transition"
                >
                  Confirm Rejection
                </button>
              </div>
            </div>
          </div>
        )}
      </div>
  );
}
