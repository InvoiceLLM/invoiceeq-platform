"use client";

import { useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { ArrowLeft, CheckCircle, XCircle, Loader2, Pencil, AlertTriangle, Sparkles } from "lucide-react";
import { apiClient } from "@/lib/apiClient";
import Shell from "@/components/layout/Shell";
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
}

interface SuggestedRule {
  scope: "global" | "existing_vendor" | "new_vendor";
  field: string;
  vendor_name: string | null;
  sample_correction: string;
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
    ? "border-[#222D3D] bg-[#1E293B] text-slate-300 pointer-events-none select-none"
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
  const [error, setError] = useState<string | null>(null);
  const [suggestedRule, setSuggestedRule] = useState<SuggestedRule | null>(null);

  useEffect(() => {
    if (!id) return;
    apiClient
      .get<InvoiceDetail>(`/invoices/${id}`)
      .then((res) => {
        setInvoice(res.data);
        setAlerts(res.data.sa_alerts ?? []);
      })
      .catch(() => setError("Invoice not found or access denied."))
      .finally(() => setLoading(false));
  }, [id]);

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
    if (targetStatus) setActionLoading(targetStatus === "PAID" ? "paid" : "rejected");
    try {
      const res = await apiClient.put(`/audit/resolve/${invoice.id}`, {
        ...(targetStatus ? { status: targetStatus } : {}),
        dismissed_alerts: alerts.map((a) => a.message),
        corrections: Object.keys(corrections).length > 0 ? corrections : undefined,
      });
      setInvoice((prev) => (prev ? { ...prev, status: targetStatus ?? prev.status, ...corrections } : prev));
      setAlerts([]);
      setCorrections({});
      if (res.data?.suggested_rule) {
        setSuggestedRule(res.data.suggested_rule);
      }
    } catch (err) {
      console.error("Resolve failed:", err);
    } finally {
      setActionLoading(null);
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
      <Shell>
        <div className="flex h-96 items-center justify-center text-slate-400">
          <Loader2 size={28} className="animate-spin" />
        </div>
      </Shell>
    );
  }

  if (error || !invoice) {
    return (
      <Shell>
        <div className="flex h-96 flex-col items-center justify-center gap-3 text-slate-400">
          <XCircle size={32} className="text-red-400" />
          <p>{error ?? "Something went wrong."}</p>
        </div>
      </Shell>
    );
  }

  const isResolved = ["PAID", "REJECTED"].includes(invoice.status);
  const hasUnsavedCorrections = Object.keys(corrections).length > 0;

  return (
    <Shell>
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

          {/* RIGHT — Details Panel */}
          <div className="flex flex-col gap-4 overflow-y-auto">
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
              onDismissed={(res) => {
                if (Object.keys(corrections).length > 0) {
                  setInvoice((prev) => (prev ? { ...prev, ...corrections } : prev));
                  setCorrections({});
                }
                if (res?.suggested_rule) setSuggestedRule(res.suggested_rule);
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
              <div className="flex items-center gap-2 rounded-lg border border-blue-600/40 bg-blue-950/20 px-3 py-2 text-xs text-blue-200">
                <Pencil size={12} />
                {Object.keys(corrections).length} field(s) corrected — will be saved when you dismiss an alert or finalize below.
              </div>
            )}

            {/* Line Items */}
            {invoice.items && invoice.items.length > 0 && (
              <div className="rounded-xl border border-[#222D3D] bg-[#0F172A] p-4">
                <p className="mb-3 text-xs font-semibold uppercase tracking-widest text-slate-400">
                  Line Items
                </p>
                <div className="space-y-2">
                  {invoice.items.map((item, idx) => (
                    <div
                      key={idx}
                      className="flex items-center justify-between rounded-lg border border-[#222D3D] bg-[#1E293B] px-3 py-2"
                    >
                      <span className="text-sm text-slate-300">
                        {idx + 1}. {item.description}
                      </span>
                      <span className="text-sm font-medium text-slate-200">
                        {fmt(item.amount)}
                      </span>
                    </div>
                  ))}
                  <div className="flex justify-between border-t border-[#222D3D] pt-2">
                    <span className="text-xs text-slate-500">Subtotal</span>
                    <span className="text-xs font-medium text-slate-300">
                      {fmt(
                        invoice.items.reduce((s, i) => s + (i.amount ?? 0), 0)
                      )}
                    </span>
                  </div>
                </div>
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
    </Shell>
  );
}
