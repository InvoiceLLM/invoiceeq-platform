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
} from "lucide-react";
import { apiClient } from "@/lib/apiClient";
import { PageHeaderActions, usePageHeader } from "@/components/layout/PageHeaderContext";
import PdfViewerCanvas from "@/components/audit/PdfViewerCanvas";
import AlertConsole, { AlertCorrectionPreview } from "@/components/audit/AlertConsole";

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
  tax_amount: number | null;
  po_number: string | null;
  // FE Gap 112 item 4: `field` was always on the wire -- every producer in
  // `utils/verification_tools.py` sets it and `sa_alerts` is a raw JSON column
  // -- the FE just never declared or read it. It is what links an alert to the
  // field the auditor has to correct.
  sa_alerts: { type: string; message: string; field?: string }[];
  items: LineItem[] | null;
  coordinates?: { x: number; y: number; width: number; height: number; label?: string }[];
  field_confidence?: Record<string, number>;
  flow_direction?: string;
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
];
const LOW_CONFIDENCE_THRESHOLD = 0.6;

function fmt(val?: number | null) {
  if (val == null) return "—";
  return new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" }).format(val);
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

  const [invoice, setInvoice] = useState<InvoiceDetail | null>(null);
  const [alerts, setAlerts] = useState<{ type: string; message: string; field?: string }[]>([]);
  // FE Gap 112 item 4: which field an alert last asked to open, and a
  // monotonic nonce so re-clicking the same alert chip re-focuses.
  const [focusRequest, setFocusRequest] = useState<{ field: string; nonce: number } | null>(null);
  const [corrections, setCorrections] = useState<Record<string, string>>({});
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
          setInvoice(res.data);
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
    if (key === "grand_total" || key === "tax_amount") return fmt(Number(raw));
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
      <div className="flex h-full flex-col gap-4 p-6">
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
          <span
            className={`rounded-full border px-3 py-1 text-xs font-medium whitespace-nowrap ${
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
          {!isResolved && (
            <div className="flex items-center gap-2">
              <button
                onClick={() => setShowRejectModal(true)}
                disabled={!!actionLoading}
                className="flex items-center gap-1.5 whitespace-nowrap rounded-lg border border-red-500/50 bg-red-600/10 px-3 py-1.5 text-xs font-semibold text-red-300 transition hover:bg-red-600/30 disabled:opacity-50"
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
                className="flex items-center gap-1.5 whitespace-nowrap rounded-lg border border-emerald-500/50 bg-emerald-600/20 px-3 py-1.5 text-xs font-semibold text-emerald-300 transition hover:bg-emerald-600/40 disabled:opacity-50"
              >
                {actionLoading === "paid" ? (
                  <Loader2 size={13} className="animate-spin" />
                ) : (
                  <CheckCircle size={13} />
                )}
                Mark Paid
              </button>
            </div>
          )}
        </PageHeaderActions>

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

            FE Gap 112 item 3: there is deliberately no invoice tab/queue strip
            above this grid. One was drawn during the mockup pass and rejected
            -- this route renders exactly one invoice (`/invoices/review/[id]`)
            and the Audit Queue is the place to move between them. Confirmed
            absent in code as well: nothing here has ever rendered one. */}
        <div className="grid flex-1 grid-cols-1 gap-4 overflow-hidden lg:grid-cols-[minmax(0,1.15fr)_minmax(0,1fr)_minmax(0,1fr)]">
          {/* COLUMN 1 — PDF Viewer (unchanged; it already manages its own
              internal scrolling and zoom/rotate toolbar). */}
          <PdfViewerCanvas
            invoiceId={invoice.id}
            title={`Invoice ${invoice.invoice_number ?? invoice.id}`}
            status={invoice.status}
            coordinates={invoice.coordinates ?? []}
          />

          {/* COLUMN 2 — Fields. min-h-0 is required on every one of these flex
              columns: without it, a flex child's default min-height:auto lets
              it grow to its full content height instead of respecting the grid
              row's bounds, so overflow-y-auto never actually engages and the
              overflow gets silently clipped by the grid parent's
              overflow-hidden instead of becoming scrollable. */}
          <section
            data-testid="fields-panel"
            className="flex min-h-0 flex-col rounded-xl border border-[#222D3D] bg-[#0F172A]"
          >
            <div className="flex items-center justify-between gap-2 border-b border-[#222D3D] px-4 py-3">
              <p className="text-xs font-semibold uppercase tracking-widest text-slate-400">
                Extracted Fields
              </p>
              <span className="shrink-0 rounded-md border border-[#222D3D] px-2 py-1 text-[11px] text-slate-500">
                {isResolved ? "Resolved — read-only" : "Click a field to correct it"}
              </span>
            </div>

            <div className="flex min-h-0 flex-1 flex-col gap-4 overflow-y-auto p-4">
              {/* Metadata Fields — editable (Task 4.6), confidence-flagged
                  (Task 4.5), alert-flagged and correction-visible (Gap 112
                  item 4). Single column now that this is a dedicated panel
                  rather than half the screen: two columns of inputs plus their
                  correction rows would not fit at 1280px. */}
              <div className="flex flex-col gap-3">
                {CORRECTABLE_FIELDS.map(({ key, label, azureKey, type }) => {
                  const confidence = invoice.field_confidence?.[azureKey];
                  const isLowConfidence = confidence != null && confidence < LOW_CONFIDENCE_THRESHOLD;
                  const rawValue = displayValue(key);
                  const displayed = type === "number" && !(key in corrections) ? fmt(rawValue ? Number(rawValue) : null) : rawValue;
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
                      inputType={type === "number" ? "text" : type === "date" ? "text" : "text"}
                    />
                  );
                })}
              </div>

              {/* Line Items (FE Gap 10): tabular view -- Description, Qty, Unit
                  Price, Total -- quantity/unit_price were already present on
                  LineItem but never rendered, only description + amount were. */}
              {invoice.items && invoice.items.length > 0 && (
                <div className="overflow-x-auto rounded-xl border border-[#222D3D] bg-[#0B1220] p-4">
                  <p className="mb-3 text-xs font-semibold uppercase tracking-widest text-slate-400">
                    Line Items
                  </p>
                  <table className="w-full border-collapse text-left">
                    <thead>
                      <tr className="border-b border-[#222D3D] text-[10px] uppercase tracking-wide text-slate-500">
                        <th className="pb-2 pr-3 font-medium">#</th>
                        <th className="pb-2 pr-3 font-medium">Description</th>
                        <th className="pb-2 pr-3 text-right font-medium">Qty</th>
                        <th className="pb-2 pr-3 text-right font-medium">Unit Price</th>
                        <th className="pb-2 text-right font-medium">Total</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-[#222D3D]/60">
                      {invoice.items.map((item, idx) => (
                        <tr key={idx} className="text-sm text-slate-300">
                          <td className="py-2 pr-3 text-slate-500">{idx + 1}</td>
                          <td className="py-2 pr-3">{item.description}</td>
                          <td className="py-2 pr-3 text-right text-slate-400">
                            {item.quantity ?? "—"}
                          </td>
                          <td className="py-2 pr-3 text-right text-slate-400">
                            {item.unit_price != null ? fmt(item.unit_price) : "—"}
                          </td>
                          <td className="py-2 text-right font-medium text-slate-200">
                            {fmt(item.amount)}
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
                          {fmt(invoice.items.reduce((s, i) => s + (i.amount ?? 0), 0))}
                        </td>
                      </tr>
                    </tfoot>
                  </table>
                </div>
              )}
            </div>

            {/* Pending-corrections footer, pinned to the bottom of this panel
                rather than scrolling away with the fields it summarises. */}
            {hasUnsavedCorrections && !isResolved && (
              <div className="shrink-0 border-t border-[#222D3D] p-3">
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
                  {/* Task 4.10 (Gap 67 / BE Gap 62): vendor-scoped only -- no
                      vendor name resolved on this invoice means there's nothing
                      to scope the rule to. */}
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
          </section>

          {/* COLUMN 3 — Alerts. Everything about resolving the invoice lives
              here: the open alerts, each with the correction staged against
              its own field (Gap 112 item 4), and the standing-rule outcome
              that a dismiss can produce. */}
          <section
            data-testid="alerts-panel"
            className="flex min-h-0 flex-col rounded-xl border border-[#222D3D] bg-[#0F172A]"
          >
            <div className="flex items-center justify-between gap-2 border-b border-[#222D3D] px-4 py-3">
              {/* Moved out of AlertConsole itself, which used to draw this
                  strip inline above the list; as a panel header it matches
                  the PDF and Fields columns. */}
              <p className="flex items-center gap-2 text-xs font-semibold uppercase tracking-widest text-slate-400">
                Discrepancy Warnings
                <span className="rounded-full border border-[#10B981]/30 bg-[#10B981]/10 px-2 py-0.5 font-mono text-[10px] font-semibold normal-case tracking-normal text-[#10B981]">
                  SENTINEL
                </span>
              </p>
              {alerts.length > 0 && (
                <span className="shrink-0 rounded-md border border-yellow-700/50 bg-yellow-950/30 px-2 py-1 text-[11px] font-medium text-yellow-300">
                  {alerts.length} open
                </span>
              )}
            </div>

            <div className="flex min-h-0 flex-1 flex-col gap-3 overflow-y-auto p-4">
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

              {/* Task 4.10 result banner -- surfaced after any Dismiss / Save
                  Correction / Mark Paid / Reject call made with the box checked. */}
              {standingRuleResult && (
                <div
                  className={`flex items-start gap-2 rounded-lg border px-3 py-2 text-xs ${
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
                          <p key={i} className="mt-0.5 text-emerald-300/80">{r}</p>
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

              {isResolved && (
                <div className="flex items-center gap-2 rounded-xl border border-[#222D3D] bg-[#1E293B] px-4 py-3 text-sm text-slate-400">
                  <CheckCircle size={16} className="text-emerald-400" />
                  This invoice has been resolved as{" "}
                  <strong className="ml-1 text-slate-200">{invoice.status}</strong>.
                </div>
              )}
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
