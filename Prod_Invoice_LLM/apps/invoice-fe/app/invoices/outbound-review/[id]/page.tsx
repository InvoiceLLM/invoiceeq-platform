"use client";

import { useEffect, useState, useRef } from "react";
import { useParams, useRouter } from "next/navigation";
import { CheckCircle, XCircle, Loader2, Pencil, Send, ShieldCheck, X, Undo2, AlertTriangle, Trash2 } from "lucide-react";
import { apiClient } from "@/lib/apiClient";
import { formatCurrency } from "@/lib/utils";
import { PageHeaderActions, usePageHeader } from "@/components/layout/PageHeaderContext";
import PdfViewerCanvas from "@/components/audit/PdfViewerCanvas";
import OutboundAlertConsole, { StandingRuleResult } from "@/components/audit/OutboundAlertConsole";
import NotifyEmailPicker from "@/components/audit/NotifyEmailPicker";

interface OutboundInvoiceDetail {
  id: string;
  status: string;
  customer_name: string | null;
  invoice_number: string | null;
  invoice_date: string | null;
  due_date: string | null;
  grand_total: number | null;
  tax_amount: number | null;
  /**
   * FE Gap 183: ISO-4217 code. The backend has always returned it (this page
   * fetches the full ORM row via GET /invoices/{id}) -- the type simply never
   * declared it, so every amount on the outbound console rendered as "$".
   */
  currency?: string | null;
  sa_alerts: { type: string; message: string; field?: string }[];
  items: { description: string; quantity?: number; unit_price?: number; amount: number }[] | null;
  coordinates?: { x: number; y: number; width: number; height: number; label?: string }[];
}

const CORRECTABLE_FIELDS: { key: keyof OutboundInvoiceDetail; label: string; type: "text" | "date" | "number" }[] = [
  { key: "customer_name", label: "Customer", type: "text" },
  { key: "invoice_number", label: "Invoice Number", type: "text" },
  { key: "invoice_date", label: "Date", type: "date" },
  { key: "due_date", label: "Due Date", type: "date" },
  { key: "grand_total", label: "Total Amount", type: "number" },
  { key: "tax_amount", label: "Tax Amount", type: "number" },
];

/**
 * FE Gap 183: was a standalone hardcoded-USD copy of the same broken pattern
 * `lib/utils.ts::formatCurrency` had. Now delegates to the shared, fixed
 * helper and takes the invoice's real currency. The "—" for a null amount is
 * kept -- this console distinguishes "not extracted" from "zero".
 */
function fmt(val?: number | null, currency?: string | null) {
  if (val == null) return "—";
  return formatCurrency(val, currency);
}

function EditableField({
  label,
  value,
  originalDisplay,
  onChange,
  onRevert,
  isDirty,
  isFlagged,
  disabled,
  focusNonce,
  inputType = "text",
}: {
  label: string;
  value: string;
  originalDisplay: string;
  onChange: (next: string) => void;
  onRevert: () => void;
  isDirty: boolean;
  isFlagged?: boolean;
  disabled?: boolean;
  focusNonce?: number;
  inputType?: "text" | "date" | "number";
}) {
  const [editing, setEditing] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);
  const wrapRef = useRef<HTMLDivElement>(null);

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

export default function OutboundAuditorReviewPage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();

  const [invoice, setInvoice] = useState<OutboundInvoiceDetail | null>(null);
  const [initialInvoice, setInitialInvoice] = useState<OutboundInvoiceDetail | null>(null);
  const [alerts, setAlerts] = useState<{ type: string; message: string; field?: string }[]>([]);
  const [corrections, setCorrections] = useState<Record<string, string>>({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [actionLoading, setActionLoading] = useState<"send" | "paid" | "delete" | null>(null);
  const [savingCorrection, setSavingCorrection] = useState(false);
  const [applyAsStandingRule, setApplyAsStandingRule] = useState(false);
  const [standingRuleResult, setStandingRuleResult] = useState<StandingRuleResult | null>(null);
  const [notifyEmails, setNotifyEmails] = useState<string[]>([]);

  const [focusRequest, setFocusRequest] = useState<{ field: string; nonce: number } | null>(null);

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
        setInitialInvoice(res.data);
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

  const originalDisplay = (key: keyof OutboundInvoiceDetail): string => {
    const raw = initialInvoice?.[key];
    if (raw == null) return "";
    if (CORRECTABLE_FIELDS.find((f) => f.key === key)?.type === "number") {
      return fmt(Number(raw), invoice?.currency);
    }
    return String(raw);
  };

  const handleFieldChange = (key: string, next: string) => {
    setCorrections((prev) => ({ ...prev, [key]: next }));
  };

  const handleRevertField = (key: string) => {
    setCorrections((prev) => {
      const next = { ...prev };
      delete next[key];
      return next;
    });
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
      await apiClient.put(`/outbound-invoices/${invoice.id}/confirm-send`, {
        ...(notifyEmails.length > 0 ? { notify_emails: notifyEmails } : {}),
      });
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
      await apiClient.put(`/outbound-invoices/${invoice.id}/mark-paid`, {
        ...(notifyEmails.length > 0 ? { notify_emails: notifyEmails } : {}),
      });
      setInvoice((prev) => (prev ? { ...prev, status: "PAID" } : prev));
    } catch (err) {
      console.error("Mark-paid failed:", err);
    } finally {
      setActionLoading(null);
    }
  };

  /**
   * Gap 282: the outbound review screen had no delete action. Same soft-delete
   * call the Outbound Invoices table and the inbound table both make —
   * `DELETE /invoices/{id}` is direction-agnostic (outbound invoices are rows
   * in the same `Invoice` table, flagged `flow_direction == "OUTBOUND"`), so no
   * outbound-specific endpoint was needed. Navigates back to the Audit Queue
   * afterwards because this route can no longer resolve the invoice it exists
   * to show.
   */
  const handleDelete = async () => {
    if (!invoice) return;
    const label = invoice.invoice_number ?? invoice.id;
    if (
      !window.confirm(
        `Delete outbound invoice ${label}? It will be removed from your outbound ledger, dashboards and reports. The record and its audit history are retained.`
      )
    ) {
      return;
    }
    setActionLoading("delete");
    try {
      await apiClient.delete(`/invoices/${invoice.id}`);
      router.push("/invoices");
    } catch (err) {
      console.error("Delete failed:", err);
      window.alert("Failed to delete invoice. Please try again.");
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
  const isResolved = invoice.status === "SENT" || invoice.status === "PAID";

  const flaggedFields = new Set(
    alerts
      .map((a) => a.field)
      .filter((f): f is string => typeof f === "string" && f !== "")
  );

  const resolveCorrection = (alert: { field?: string }) => {
    if (!alert.field) return null;
    const fieldObj = CORRECTABLE_FIELDS.find((f) => f.key === alert.field);
    if (!fieldObj) return null;
    if (!(alert.field in corrections)) return null;

    return {
      field: alert.field,
      label: fieldObj.label,
      oldValue: originalDisplay(alert.field as keyof OutboundInvoiceDetail),
      newValue: corrections[alert.field],
    };
  };

  return (
    <div className="flex h-full flex-col gap-4 p-6 overflow-y-auto xl:overflow-hidden">
      <PageHeaderActions>
        <span
          className={`rounded-full border px-2 sm:px-3 py-0.5 sm:py-1 text-[10px] sm:text-xs font-medium whitespace-nowrap ${
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

        {isVerifiedOrNeedsReview && (
          <button
            onClick={handleConfirmSend}
            disabled={!!actionLoading}
            className="flex items-center gap-1.5 whitespace-nowrap rounded-lg border border-emerald-500/50 bg-emerald-600/20 px-2 sm:px-3 py-1 sm:py-1.5 text-[10px] sm:text-xs font-semibold text-emerald-300 transition hover:bg-emerald-600/40 disabled:opacity-50"
          >
            {actionLoading === "send" ? <Loader2 size={13} className="animate-spin" /> : <Send size={13} />}
            Approve &amp; Send
          </button>
        )}

        {isSent && (
          <button
            onClick={handleMarkPaid}
            disabled={!!actionLoading}
            className="flex items-center gap-1.5 whitespace-nowrap rounded-lg border border-emerald-500/50 bg-emerald-600/20 px-2 sm:px-3 py-1 sm:py-1.5 text-[10px] sm:text-xs font-semibold text-emerald-300 transition hover:bg-emerald-600/40 disabled:opacity-50"
          >
            {actionLoading === "paid" ? <Loader2 size={13} className="animate-spin" /> : <CheckCircle size={13} />}
            Mark Paid
          </button>
        )}

        {/* Gap 282: delete, offered at every lifecycle stage the same way the
            Outbound Invoices table offers it on every row — a misfiled upload
            is just as likely to be noticed after it is SENT/PAID as before. */}
        <button
          onClick={handleDelete}
          disabled={!!actionLoading}
          title="Delete invoice"
          className="flex items-center gap-1.5 whitespace-nowrap rounded-lg border border-rose-500/50 bg-rose-600/10 px-2 sm:px-3 py-1 sm:py-1.5 text-[10px] sm:text-xs font-semibold text-rose-300 transition hover:bg-rose-600/30 disabled:opacity-50"
        >
          {actionLoading === "delete" ? <Loader2 size={13} className="animate-spin" /> : <Trash2 size={13} />}
          Delete
        </button>
      </PageHeaderActions>

      {(isVerifiedOrNeedsReview || isSent) && (
        <NotifyEmailPicker emailSet="outbound" selected={notifyEmails} onChange={setNotifyEmails} />
      )}

      <div className="grid flex-1 grid-cols-1 gap-4 xl:grid-cols-[minmax(0,1.15fr)_minmax(0,1fr)_minmax(0,1fr)] xl:overflow-hidden">
        {/* COLUMN 1 — PDF Viewer */}
        <PdfViewerCanvas
          invoiceId={invoice.id}
          title={`Invoice ${invoice.invoice_number ?? invoice.id}`}
          status={invoice.status}
          coordinates={invoice.coordinates ?? []}
        />

        {/* COLUMN 2 — Extracted Fields */}
        <section
          data-testid="fields-panel"
          className="flex min-h-[400px] xl:min-h-0 flex-col rounded-xl border border-[#222D3D] bg-[#0F172A]"
        >
          <div className="flex items-center justify-between gap-2 border-b border-[#222D3D] px-4 py-3">
            <p className="text-xs font-semibold uppercase tracking-widest text-slate-400">
              Extracted Fields
            </p>
            <span className="shrink-0 rounded-md border border-[#222D3D] px-2 py-1 text-[11px] text-slate-500">
              {isResolved ? "Resolved — read-only" : "Click a field to correct it"}
            </span>
          </div>

          <div className="flex min-h-0 flex-1 flex-col gap-4 overflow-y-auto p-4 max-h-[calc(100vh-180px)] xl:max-h-none">
            <div className="flex flex-col gap-3">
              {CORRECTABLE_FIELDS.map(({ key, label, type }) => {
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
                    isFlagged={flaggedFields.has(key as string)}
                    disabled={isResolved}
                    focusNonce={focusRequest?.field === (key as string) ? focusRequest.nonce : undefined}
                    inputType={type === "number" ? "text" : type === "date" ? "text" : "text"}
                  />
                );
              })}
            </div>

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
                  <tbody className="divide-y divide-[#222D3D]/60 text-slate-300 text-sm">
                    {invoice.items.map((item, idx) => (
                      <tr key={idx}>
                        <td className="py-2 pr-3 text-slate-500">{idx + 1}</td>
                        <td className="py-2 pr-3">{item.description}</td>
                        <td className="py-2 pr-3 text-right text-slate-400">{item.quantity ?? "—"}</td>
                        <td className="py-2 pr-3 text-right text-slate-400">{item.unit_price != null ? fmt(item.unit_price, invoice.currency) : "—"}</td>
                        <td className="py-2 text-right font-medium text-slate-200">{fmt(item.amount, invoice.currency)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>

          {hasUnsavedCorrections && !isResolved && (
            <div className="shrink-0 border-t border-[#222D3D] p-3">
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
                <label className="flex cursor-pointer items-center gap-2 text-blue-300/90">
                  <input
                    type="checkbox"
                    checked={applyAsStandingRule}
                    onChange={(e) => setApplyAsStandingRule(e.target.checked)}
                    className="h-3.5 w-3.5 rounded border-blue-500/50 bg-transparent accent-blue-500"
                  />
                  Apply this correction as a standing rule for all future outbound invoices?
                </label>
              </div>
            </div>
          )}
        </section>

        {/* COLUMN 3 — Discrepancy Warnings */}
        <section
          data-testid="alerts-panel"
          className="flex min-h-[400px] xl:min-h-0 flex-col rounded-xl border border-[#222D3D] bg-[#0F172A]"
        >
          <div className="flex items-center justify-between gap-2 border-b border-[#222D3D] px-4 py-3">
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

          <div className="flex min-h-0 flex-1 flex-col gap-3 overflow-y-auto p-4 max-h-[calc(100vh-180px)] xl:max-h-none">
            <OutboundAlertConsole
              invoiceId={invoice.id}
              alerts={alerts}
              currentStatus={invoice.status}
              onAlertsChange={setAlerts}
              corrections={corrections}
              applyAsStandingRule={applyAsStandingRule}
              resolveCorrection={resolveCorrection}
              onFocusField={(field) => setFocusRequest((prev) => ({ field, nonce: (prev?.nonce ?? 0) + 1 }))}
              onDismissed={(res) => {
                if (Object.keys(corrections).length > 0) {
                  setInvoice((prev) => (prev ? { ...prev, ...corrections } : prev));
                  setCorrections({});
                }
                setApplyAsStandingRule(false);
                if (res?.standing_rule_result) setStandingRuleResult(res.standing_rule_result);
              }}
            />

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
          </div>
        </section>
      </div>
    </div>
  );
}
