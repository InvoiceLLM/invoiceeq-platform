"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import { CheckCircle, XCircle, Loader2, Pencil, Send, ShieldCheck, X } from "lucide-react";
import { apiClient } from "@/lib/apiClient";
import { PageHeaderActions, usePageHeader } from "@/components/layout/PageHeaderContext";
import PdfViewerCanvas from "@/components/audit/PdfViewerCanvas";
import OutboundAlertConsole, { StandingRuleResult } from "@/components/audit/OutboundAlertConsole";

interface OutboundInvoiceDetail {
  id: string;
  status: string;
  customer_name: string | null;
  invoice_number: string | null;
  invoice_date: string | null;
  due_date: string | null;
  grand_total: number | null;
  tax_amount: number | null;
  sa_alerts: { type: string; message: string }[];
  items: { description: string; quantity?: number; unit_price?: number; amount: number }[] | null;
  coordinates?: { x: number; y: number; width: number; height: number; label?: string }[];
}

// Feature 4.1's correctable field set -- mirrors OutboundInvoiceExtractionSchema
// (feature_2.1_vendor_flow_ingestion.md), not inbound's field list.
const CORRECTABLE_FIELDS: { key: keyof OutboundInvoiceDetail; label: string; type: "text" | "date" | "number" }[] = [
  { key: "customer_name", label: "Customer", type: "text" },
  { key: "invoice_number", label: "Invoice Number", type: "text" },
  { key: "invoice_date", label: "Date", type: "date" },
  { key: "due_date", label: "Due Date", type: "date" },
  { key: "grand_total", label: "Total Amount", type: "number" },
  { key: "tax_amount", label: "Tax Amount", type: "number" },
];

function fmt(val?: number | null) {
  if (val == null) return "—";
  return new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" }).format(val);
}

function EditableField({
  label, value, onChange, isDirty, disabled, inputType = "text",
}: {
  label: string; value: string; onChange: (next: string) => void; isDirty: boolean; disabled?: boolean; inputType?: string;
}) {
  const [editing, setEditing] = useState(false);
  const baseClass = "w-full rounded-lg border px-3 py-2 text-sm outline-none transition-colors";
  const stateClass = disabled
    ? "border-[#222D3D] bg-[#1E293B] text-slate-300 select-none cursor-not-allowed"
    : editing
    ? "border-blue-500 bg-[#1E293B] text-slate-100 cursor-text"
    : "border-[#222D3D] bg-[#1E293B] text-slate-300 cursor-pointer hover:border-slate-500";

  return (
    <div className="flex flex-col gap-1">
      <label className="text-xs font-medium text-slate-500 flex items-center gap-1.5">
        {label}
        {isDirty && (
          <span title="Corrected -- will be saved on resolve">
            <Pencil size={10} className="text-blue-400" />
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

export default function OutboundAuditorReviewPage() {
  const { id } = useParams<{ id: string }>();

  const [invoice, setInvoice] = useState<OutboundInvoiceDetail | null>(null);
  const [alerts, setAlerts] = useState<{ type: string; message: string }[]>([]);
  const [corrections, setCorrections] = useState<Record<string, string>>({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [actionLoading, setActionLoading] = useState<"send" | "paid" | null>(null);
  const [savingCorrection, setSavingCorrection] = useState(false);
  const [applyAsStandingRule, setApplyAsStandingRule] = useState(false);
  const [standingRuleResult, setStandingRuleResult] = useState<StandingRuleResult | null>(null);

  // FE Gap 110 — see the inbound review console for the reasoning, including
  // why Back is an explicit /invoices link rather than router.back().
  usePageHeader({
    title: "Outbound Auditor Console",
    agentIcon: "🛡️",
    agentName: "SENTINEL",
    agentRole: "Audit & Compliance",
    subtitle: invoice ? `Invoice #${invoice.invoice_number ?? invoice.id}` : undefined,
    backHref: "/invoices",
  });

  useEffect(() => {
    if (!id) return;
    apiClient
      .get<OutboundInvoiceDetail>(`/invoices/${id}`)
      .then((res) => {
        setInvoice(res.data);
        setAlerts(res.data.sa_alerts ?? []);
      })
      .catch(() => setError("Invoice not found or access denied."))
      .finally(() => setLoading(false));
  }, [id]);

  const displayValue = (key: keyof OutboundInvoiceDetail): string => {
    if (key in corrections) return corrections[key as string];
    const raw = invoice?.[key];
    if (raw == null) return "";
    return String(raw);
  };

  const handleFieldChange = (key: string, next: string) => {
    setCorrections((prev) => ({ ...prev, [key]: next }));
  };

  const handleSaveCorrection = async () => {
    if (!invoice) return;
    setSavingCorrection(true);
    try {
      const res = await apiClient.put(`/outbound-audit/resolve/${invoice.id}`, {
        dismissed_alerts: alerts.map((a) => a.message),
        corrections: Object.keys(corrections).length > 0 ? corrections : undefined,
        apply_as_standing_rule: applyAsStandingRule || undefined,
      });
      setInvoice((prev) => (prev ? { ...prev, ...corrections } : prev));
      setAlerts([]);
      setCorrections({});
      setApplyAsStandingRule(false);
      if (res.data?.standing_rule_result) setStandingRuleResult(res.data.standing_rule_result);
    } catch (err) {
      console.error("Save correction failed:", err);
    } finally {
      setSavingCorrection(false);
    }
  };

  const handleConfirmSend = async () => {
    if (!invoice) return;
    setActionLoading("send");
    try {
      await apiClient.put(`/outbound-invoices/${invoice.id}/confirm-send`);
      setInvoice((prev) => (prev ? { ...prev, status: "SENT" } : prev));
    } catch (err) {
      console.error("Confirm-send failed:", err);
    } finally {
      setActionLoading(null);
    }
  };

  const handleMarkPaid = async () => {
    if (!invoice) return;
    setActionLoading("paid");
    try {
      await apiClient.put(`/outbound-invoices/${invoice.id}/mark-paid`);
      setInvoice((prev) => (prev ? { ...prev, status: "PAID" } : prev));
    } catch (err) {
      console.error("Mark-paid failed:", err);
    } finally {
      setActionLoading(null);
    }
  };

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

  const isVerifiedOrNeedsReview = invoice.status === "VERIFIED" || invoice.status === "NEEDS_REVIEW";
  const isSent = invoice.status === "SENT";
  const hasUnsavedCorrections = Object.keys(corrections).length > 0;

  return (
    <div className="flex h-full flex-col gap-4 p-6">
      {/* FE Gap 110: same treatment as the inbound review console -- title,
          subtitle and Back moved into the shared header, status badge portalled
          up beside them. */}
      <PageHeaderActions>
        <span
          className={`rounded-full border px-3 py-1 text-xs font-medium whitespace-nowrap ${
            invoice.status === "PAID"
              ? "border-emerald-600/50 bg-emerald-500/10 text-emerald-300"
              : invoice.status === "SENT"
              ? "border-sky-600/50 bg-sky-500/10 text-sky-300"
              : invoice.status === "NEEDS_REVIEW"
              ? "border-yellow-600/50 bg-yellow-500/10 text-yellow-300"
              : "border-slate-600/50 bg-slate-700/30 text-slate-300"
          }`}
        >
          {invoice.status.replace("_", " ")}
        </span>
      </PageHeaderActions>

      <div className="grid flex-1 grid-cols-2 gap-4 overflow-hidden">
        <PdfViewerCanvas
          invoiceId={invoice.id}
          title={`Invoice ${invoice.invoice_number ?? invoice.id}`}
          status={invoice.status}
          coordinates={invoice.coordinates ?? []}
        />

        <div className="flex flex-col gap-4 overflow-y-auto">
          <div className="flex items-center justify-between">
            <p className="text-xs font-semibold uppercase tracking-widest text-slate-400">
              Outbound Details &amp; Validation
            </p>
            <span className="rounded-md border border-[#222D3D] px-2 py-1 text-xs text-slate-500">
              {isSent || invoice.status === "PAID" ? "Finalized -- read-only" : "Click a field to correct it"}
            </span>
          </div>

          <OutboundAlertConsole
            invoiceId={invoice.id}
            alerts={alerts}
            onAlertsChange={setAlerts}
            corrections={corrections}
            applyAsStandingRule={applyAsStandingRule}
            onDismissed={(res) => {
              if (Object.keys(corrections).length > 0) {
                setInvoice((prev) => (prev ? { ...prev, ...corrections } : prev));
                setCorrections({});
              }
              setApplyAsStandingRule(false);
              if (res?.standing_rule_result) setStandingRuleResult(res.standing_rule_result);
            }}
          />

          <div className="grid grid-cols-2 gap-3 rounded-xl border border-[#222D3D] bg-[#0F172A] p-4">
            {CORRECTABLE_FIELDS.map(({ key, label, type }) => {
              const rawValue = displayValue(key);
              const displayed = type === "number" && !(key in corrections) ? fmt(rawValue ? Number(rawValue) : null) : rawValue;
              return (
                <div key={key as string} className={key === "customer_name" ? "col-span-2" : undefined}>
                  <EditableField
                    label={label}
                    value={displayed}
                    onChange={(next) => handleFieldChange(key as string, next)}
                    isDirty={key in corrections}
                    disabled={isSent || invoice.status === "PAID"}
                    inputType={type === "number" || type === "date" ? "text" : "text"}
                  />
                </div>
              );
            })}
          </div>

          {hasUnsavedCorrections && isVerifiedOrNeedsReview && (
            <div className="flex flex-col gap-2 rounded-lg border border-blue-600/40 bg-blue-950/20 px-3 py-2 text-xs text-blue-200">
              <div className="flex items-center justify-between gap-2">
                <span className="flex items-center gap-2">
                  <Pencil size={12} />
                  {Object.keys(corrections).length} field(s) corrected
                </span>
                <button
                  onClick={handleSaveCorrection}
                  disabled={!!actionLoading || savingCorrection}
                  className="shrink-0 rounded-md border border-blue-500/50 bg-blue-600/20 px-2.5 py-1 text-xs font-semibold text-blue-200 transition hover:bg-blue-600/40 disabled:opacity-50"
                >
                  {savingCorrection ? "Saving..." : "Save Correction"}
                </button>
              </div>
              <label className="flex items-center gap-2 cursor-pointer text-blue-300/90">
                <input
                  type="checkbox"
                  checked={applyAsStandingRule}
                  onChange={(e) => setApplyAsStandingRule(e.target.checked)}
                  className="h-3.5 w-3.5 rounded border-blue-500/50 bg-transparent accent-blue-500"
                />
                Apply this as a standing rule for all future outbound invoices?
              </label>
            </div>
          )}

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
              <button onClick={() => setStandingRuleResult(null)} className="shrink-0 text-current opacity-60 hover:opacity-100">
                <X size={12} />
              </button>
            </div>
          )}

          {invoice.items && invoice.items.length > 0 && (
            <div className="rounded-xl border border-[#222D3D] bg-[#0F172A] p-4 overflow-x-auto">
              <p className="mb-3 text-xs font-semibold uppercase tracking-widest text-slate-400">Line Items</p>
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
                      <td className="py-2 pr-3 text-right text-slate-400">{item.quantity ?? "—"}</td>
                      <td className="py-2 pr-3 text-right text-slate-400">{item.unit_price != null ? fmt(item.unit_price) : "—"}</td>
                      <td className="py-2 text-right font-medium text-slate-200">{fmt(item.amount)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          {isVerifiedOrNeedsReview && (
            <div className="mt-auto flex flex-col gap-3 pt-2">
              <button
                onClick={handleConfirmSend}
                disabled={!!actionLoading}
                className="flex w-full items-center justify-center gap-2 rounded-xl border border-emerald-500/50 bg-emerald-600/20 py-3 text-sm font-semibold text-emerald-300 transition hover:bg-emerald-600/40 disabled:opacity-50"
              >
                {actionLoading === "send" ? <Loader2 size={16} className="animate-spin" /> : <Send size={16} />}
                Approve &amp; Send
              </button>
            </div>
          )}

          {isSent && (
            <div className="mt-auto flex flex-col gap-3 pt-2">
              <button
                onClick={handleMarkPaid}
                disabled={!!actionLoading}
                className="flex w-full items-center justify-center gap-2 rounded-xl border border-emerald-500/50 bg-emerald-600/20 py-3 text-sm font-semibold text-emerald-300 transition hover:bg-emerald-600/40 disabled:opacity-50"
              >
                {actionLoading === "paid" ? <Loader2 size={16} className="animate-spin" /> : <CheckCircle size={16} />}
                Mark Paid
              </button>
            </div>
          )}

          {invoice.status === "PAID" && (
            <div className="flex items-center gap-2 rounded-xl border border-[#222D3D] bg-[#1E293B] px-4 py-3 text-sm text-slate-400">
              <CheckCircle size={16} className="text-emerald-400" />
              This invoice has been paid.
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
