"use client";

import { useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { ArrowLeft, CheckCircle, XCircle, Loader2, Pencil, AlertTriangle, Sparkles, ShieldCheck, X } from "lucide-react";
import { apiClient } from "@/lib/apiClient";
import PdfViewerCanvas from "@/components/audit/PdfViewerCanvas";
import AlertConsole from "@/components/audit/AlertConsole";

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
  sa_alerts: { type: string; message: string }[];
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
 */
function EditableField({
  label,
  value,
  onChange,
  isDirty,
  isLowConfidence,
  confidence,
  disabled,
  inputType = "text",
}: {
  label: string;
  value: string;
  onChange: (next: string) => void;
  isDirty: boolean;
  isLowConfidence: boolean;
  confidence?: number;
  disabled?: boolean;
  inputType?: "text" | "date" | "number";
}) {
  const [editing, setEditing] = useState(false);

  const baseClass = "w-full rounded-lg border px-3 py-2 text-sm outline-none transition-colors";
  const stateClass = disabled
    ? "border-[#222D3D] bg-[#1E293B] text-slate-300 select-none cursor-not-allowed"
    : editing
    ? "border-blue-500 bg-[#1E293B] text-slate-100 cursor-text"
    : isLowConfidence
    ? "border-amber-500/60 bg-[#1E293B] text-slate-300 cursor-pointer hover:border-amber-400"
    : "border-[#222D3D] bg-[#1E293B] text-slate-300 cursor-pointer hover:border-slate-500";

  return (
    <div className="flex flex-col gap-1">
      <label className="text-xs font-medium text-slate-500 flex items-center gap-1.5">
        {label}
        {isDirty && (
          <span title="Corrected — will be saved on resolve/dismiss">
            <Pencil size={10} className="text-blue-400" />
          </span>
        )}
        {isLowConfidence && !isDirty && (
          <span title={`OCR confidence ${Math.round((confidence ?? 0) * 100)}% — below the ${LOW_CONFIDENCE_THRESHOLD * 100}% review threshold`}>
            <AlertTriangle size={10} className="text-amber-400" />
          </span>
        )}
      </label>
      <input
        type={inputType}
        className={`${baseClass} ${stateClass}`}
        value={value}
        readOnly={disabled || !editing}
        onClick={() => !disabled && setEditing(true)}
        onBlur={() => setEditing(false)}
        onChange={(e) => onChange(e.target.value)}
        tabIndex={disabled ? -1 : 0}
      />
    </div>
  );
}

export default function AuditorReviewPage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();

  const [invoice, setInvoice] = useState<InvoiceDetail | null>(null);
  const [alerts, setAlerts] = useState<{ type: string; message: string }[]>([]);
  const [corrections, setCorrections] = useState<Record<string, string>>({});
  const [loading, setLoading] = useState(true);
  const [actionLoading, setActionLoading] = useState<"paid" | "rejected" | null>(null);
  const [savingCorrection, setSavingCorrection] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [suggestedRule, setSuggestedRule] = useState<SuggestedRule | null>(null);
  // Task 4.10: "apply as standing rule" checkbox state + the backend's
  // safety-gated result (rule applied, or rejected because the re-extraction
  // check failed).
  const [applyAsStandingRule, setApplyAsStandingRule] = useState(false);
  const [standingRuleResult, setStandingRuleResult] = useState<StandingRuleResult | null>(null);

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

  const handleFieldChange = (key: string, next: string) => {
    setCorrections((prev) => ({ ...prev, [key]: next }));
  };

  const handleResolve = async (targetStatus?: "PAID" | "REJECTED") => {
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
        {/* Page Header */}
        <div className="flex items-center gap-3">
          <button
            onClick={() => router.back()}
            className="flex items-center gap-1.5 rounded-lg border border-[#222D3D] px-3 py-1.5 text-xs text-slate-400 transition hover:border-slate-500 hover:text-slate-200"
          >
            <ArrowLeft size={13} /> Back
          </button>
          <div>
            <h1 className="text-lg font-semibold text-slate-100">Auditor Review Console</h1>
            <p className="text-xs text-slate-500">
              Invoice #{invoice.invoice_number ?? invoice.id}
            </p>
          </div>
          <span
            className={`ml-auto rounded-full border px-3 py-1 text-xs font-medium ${
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
        </div>

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

        {/* Split Layout */}
        <div className="grid flex-1 grid-cols-2 gap-4 overflow-hidden">
          {/* LEFT — PDF Viewer */}
          <PdfViewerCanvas
            invoiceId={invoice.id}
            title={`Invoice ${invoice.invoice_number ?? invoice.id}`}
            status={invoice.status}
            coordinates={invoice.coordinates ?? []}
          />

          {/* RIGHT — Details Panel. min-h-0 is required here: without it, a
              flex child's default min-height:auto lets it grow to its full
              content height instead of respecting the grid row's bounds, so
              overflow-y-auto never actually engages -- the overflow (in this
              case, the Mark Paid/Reject buttons at the very bottom) gets
              silently clipped by the grid parent's overflow-hidden instead
              of becoming scrollable. */}
          <div className="flex flex-col gap-4 overflow-y-auto min-h-0">
            {/* Section Header */}
            <div className="flex items-center justify-between">
              <p className="text-xs font-semibold uppercase tracking-widest text-slate-400">
                Auditor Details &amp; Validation
              </p>
              <span className="rounded-md border border-[#222D3D] px-2 py-1 text-xs text-slate-500">
                {isResolved ? "Resolved — read-only" : "Click a field to correct it"}
              </span>
            </div>

            {/* Alerts */}
            <AlertConsole
              invoiceId={invoice.id}
              alerts={alerts}
              currentStatus={invoice.status}
              onAlertsChange={setAlerts}
              corrections={corrections}
              applyAsStandingRule={applyAsStandingRule}
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

            {/* Metadata Fields — editable (Task 4.6), confidence-flagged (Task 4.5) */}
            <div className="grid grid-cols-2 gap-3 rounded-xl border border-[#222D3D] bg-[#0F172A] p-4">
              {CORRECTABLE_FIELDS.map(({ key, label, azureKey, type }) => {
                const confidence = invoice.field_confidence?.[azureKey];
                const isLowConfidence = confidence != null && confidence < LOW_CONFIDENCE_THRESHOLD;
                const rawValue = displayValue(key);
                const displayed = type === "number" && !(key in corrections) ? fmt(rawValue ? Number(rawValue) : null) : rawValue;
                return (
                  <div key={key as string} className={key === "vendor_name" ? "col-span-2" : undefined}>
                    <EditableField
                      label={label}
                      value={displayed}
                      onChange={(next) => handleFieldChange(key as string, next)}
                      isDirty={key in corrections}
                      isLowConfidence={isLowConfidence}
                      confidence={confidence}
                      disabled={isResolved}
                      inputType={type === "number" ? "text" : type === "date" ? "text" : "text"}
                    />
                  </div>
                );
              })}
            </div>

            {hasUnsavedCorrections && !isResolved && (
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
                  <label className="flex items-center gap-2 cursor-pointer text-blue-300/90">
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
            )}

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

            {/* Line Items (FE Gap 10): tabular view -- Description, Qty, Unit
                Price, Total -- quantity/unit_price were already present on
                LineItem but never rendered, only description + amount were. */}
            {invoice.items && invoice.items.length > 0 && (
              <div className="rounded-xl border border-[#222D3D] bg-[#0F172A] p-4 overflow-x-auto">
                <p className="mb-3 text-xs font-semibold uppercase tracking-widest text-slate-400">
                  Line Items
                </p>
                <table className="w-full text-left border-collapse">
                  <thead>
                    <tr className="text-[10px] text-slate-500 uppercase tracking-wide border-b border-[#222D3D]">
                      <th className="pb-2 pr-3 font-medium">#</th>
                      <th className="pb-2 pr-3 font-medium">Description</th>
                      <th className="pb-2 pr-3 font-medium text-right">Qty</th>
                      <th className="pb-2 pr-3 font-medium text-right">Unit Price</th>
                      <th className="pb-2 font-medium text-right">Total</th>
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

            {/* Action Buttons */}
            {!isResolved && (
              <div className="mt-auto flex flex-col gap-3 pt-2">
                <button
                  onClick={() => handleResolve("PAID")}
                  disabled={!!actionLoading}
                  className="flex w-full items-center justify-center gap-2 rounded-xl border border-emerald-500/50 bg-emerald-600/20 py-3 text-sm font-semibold text-emerald-300 transition hover:bg-emerald-600/40 disabled:opacity-50"
                >
                  {actionLoading === "paid" ? (
                    <Loader2 size={16} className="animate-spin" />
                  ) : (
                    <CheckCircle size={16} />
                  )}
                  Mark Paid &amp; Finalize
                </button>
                <button
                  onClick={() => handleResolve("REJECTED")}
                  disabled={!!actionLoading}
                  className="flex w-full items-center justify-center gap-2 rounded-xl border border-red-500/50 bg-red-600/10 py-3 text-sm font-semibold text-red-400 transition hover:bg-red-600/30 disabled:opacity-50"
                >
                  {actionLoading === "rejected" ? (
                    <Loader2 size={16} className="animate-spin" />
                  ) : (
                    <XCircle size={16} />
                  )}
                  Reject Invoice
                </button>
              </div>
            )}

            {isResolved && (
              <div className="flex items-center gap-2 rounded-xl border border-[#222D3D] bg-[#1E293B] px-4 py-3 text-sm text-slate-400">
                <CheckCircle size={16} className="text-emerald-400" />
                This invoice has been resolved as <strong className="text-slate-200 ml-1">{invoice.status}</strong>.
              </div>
            )}
          </div>
        </div>
      </div>
  );
}
