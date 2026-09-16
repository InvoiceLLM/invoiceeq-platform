"use client";

// =============================================================================
// FILE: components/chat/cards/ReviewCard.tsx
// FEATURE: FE Feature 22 Task 22.12 — invoice review as a card in Ask.
//          `/invoices/review/[id]` redirects to `/ask?invoice=<id>` (lib/navigation.ts).
//
// Contract (verified 2026-09-17):
//   GET /invoices/{id}                -> the invoice row, `sa_alerts` [{type, message, field?}]
//   PUT /audit/resolve/{id}           -> the SAME endpoint and body as the review
//                                        page's per-alert Dismiss (components/audit/AlertConsole.tsx):
//     Accept printed  {dismissed_alerts: [message], corrections: undefined, apply_as_standing_rule: undefined}
//     Accept computed {dismissed_alerts: [message], corrections: {field: computed}, apply_as_standing_rule: undefined}
//   Tell me why       -> pre-fills the Ask composer with the flag; never sent.
//
// PRINTED vs COMPUTED. "Printed" is the extracted value on the invoice row — what
// was read off the document. "Computed" must come from the backend: today's
// alerts (utils/verification_tools.py) carry the computed figure only inside the
// message text. This card does NOT parse message strings and does NOT do the
// arithmetic itself (deterministic-over-prompt). It reads `computed_value` — the
// field PROPOSED in plan open item #25 — and until the backend sends it,
// "Computed" reads "Not sent yet" and `Accept computed` stays disabled.
//
// Out of scope here, kept on the classic review page (plan open item #26):
// Mark Paid / Reject / Review later / Needs resubmission, line items, notify list.
// =============================================================================

import React, { useEffect, useState } from "react";
import { CheckCircle2, FileText, Loader2, MessageCircleQuestion, ShieldAlert } from "lucide-react";
import { apiClient } from "@/lib/apiClient";
import { formatCurrency } from "@/lib/utils";
import { chipLabel } from "@/lib/today";

export interface ReviewAlert {
  type: string;
  message: string;
  field?: string;
  /** PROPOSED (plan #25) — absent from every alert today. */
  computed_value?: string | number | null;
}

interface ReviewInvoice {
  id: string;
  status: string;
  vendor_name: string | null;
  invoice_number: string | null;
  grand_total: number | null;
  currency?: string | null;
  flow_direction?: string;
  sa_alerts?: ReviewAlert[] | null;
  [field: string]: unknown;
}

/** The backend's correction allowlist (routers/audit.py `_CORRECTABLE_FIELDS`), minus `items`. */
const FIELDS: Record<string, { label: string; money?: boolean }> = {
  vendor_name: { label: "Vendor" },
  invoice_number: { label: "Invoice number" },
  po_number: { label: "PO number" },
  invoice_date: { label: "Invoice date" },
  due_date: { label: "Due date" },
  subtotal: { label: "Subtotal", money: true },
  grand_total: { label: "Total amount", money: true },
  tax_amount: { label: "Tax amount", money: true },
};

function fieldLabel(field?: string): string {
  if (!field) return "Invoice";
  return FIELDS[field]?.label ?? chipLabel(field);
}

function display(value: unknown, field: string | undefined, currency?: string | null): string {
  if (value === null || value === undefined || value === "") return "—";
  if (field && FIELDS[field]?.money && typeof value === "number") return formatCurrency(value, currency);
  return String(value);
}

interface ReviewCardProps {
  invoiceId: string;
  /** Pre-fills the composer. Never sends. */
  onTellMeWhy?: (text: string) => void;
}

export default function ReviewCard({ invoiceId, onTellMeWhy }: ReviewCardProps) {
  const [invoice, setInvoice] = useState<ReviewInvoice | null>(null);
  const [alerts, setAlerts] = useState<ReviewAlert[]>([]);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setInvoice(null);
    setLoadError(null);
    apiClient
      .get<ReviewInvoice>(`/invoices/${invoiceId}`)
      .then((res) => {
        if (cancelled) return;
        setInvoice(res.data);
        setAlerts(res.data.sa_alerts ?? []);
      })
      .catch(() => {
        if (!cancelled) setLoadError("Invoice not found or access denied.");
      });
    return () => {
      cancelled = true;
    };
  }, [invoiceId]);

  const resolve = async (alert: ReviewAlert, corrections?: Record<string, string | number>) => {
    if (busy) return;
    setBusy(alert.message);
    setError(null);
    try {
      await apiClient.put(`/audit/resolve/${invoiceId}`, {
        dismissed_alerts: [alert.message],
        corrections,
        apply_as_standing_rule: undefined,
      });
      setAlerts((current) => current.filter((a) => a.message !== alert.message));
      if (corrections) setInvoice((current) => (current ? { ...current, ...corrections } : current));
    } catch (err) {
      const detail = (err as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail;
      setError(typeof detail === "string" ? detail : "Could not save this. Try again.");
    } finally {
      setBusy(null);
    }
  };

  if (loadError) {
    return (
      <p role="alert" data-testid="review-card-error" className="rounded-xl border border-rose-900/50 bg-rose-950/20 px-4 py-3 text-xs text-rose-300">
        {loadError}
      </p>
    );
  }

  if (!invoice) {
    return (
      <div className="flex justify-center py-4">
        <Loader2 className="h-5 w-5 animate-spin text-slate-400" aria-label="Loading invoice" />
      </div>
    );
  }

  const outbound = invoice.flow_direction?.toUpperCase() === "OUTBOUND";
  const title = invoice.invoice_number ? `Invoice ${invoice.invoice_number}` : "Invoice";

  return (
    <section data-testid="review-card" aria-label={`Review ${title}`} className="flex gap-4 rounded-xl border border-[#1E293B] bg-[#111827] p-4">
      <a
        href={`/api/invoices/${invoice.id}/pdf`}
        target="_blank"
        rel="noreferrer"
        aria-label="Open the PDF"
        className="relative hidden h-40 w-28 shrink-0 overflow-hidden rounded-lg border border-[#222D3D] bg-[#0B0F19] sm:block"
      >
        <iframe
          data-testid="review-card-thumbnail"
          title={`${title} PDF`}
          src={`/api/invoices/${invoice.id}/pdf#toolbar=0&navpanes=0&view=FitH`}
          tabIndex={-1}
          className="pointer-events-none h-full w-full"
        />
        <FileText className="absolute bottom-1.5 right-1.5 h-3.5 w-3.5 text-slate-500" aria-hidden="true" />
      </a>

      <div className="min-w-0 flex-1 space-y-3">
        <div>
          <p className="inline-flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wider text-amber-300">
            <ShieldAlert className="h-3.5 w-3.5" aria-hidden="true" />
            Review
          </p>
          <h2 className="text-sm font-semibold text-white">
            {title}
            {invoice.vendor_name ? ` · ${invoice.vendor_name}` : ""}
          </h2>
          <p className="text-[11px] text-slate-400">
            {invoice.status.replace(/_/g, " ")} · {display(invoice.grand_total, "grand_total", invoice.currency)}
          </p>
        </div>

        {outbound ? (
          <p data-testid="review-card-outbound" className="text-xs text-slate-300">
            This is an outgoing invoice.{" "}
            <a href={`/invoices/outbound-review/${invoice.id}`} className="text-sky-400 underline">
              Review it on the outgoing review page
            </a>
            .
          </p>
        ) : alerts.length === 0 ? (
          <p data-testid="review-card-clear" className="inline-flex items-center gap-1.5 text-xs text-emerald-300">
            <CheckCircle2 className="h-3.5 w-3.5" aria-hidden="true" />
            Nothing flagged on this invoice.
          </p>
        ) : (
          <ul className="space-y-2">
            {alerts.map((alert) => {
              const correctable = Boolean(alert.field && FIELDS[alert.field]);
              const computed = alert.computed_value;
              const hasComputed = computed !== undefined && computed !== null && computed !== "";
              const saving = busy === alert.message;
              return (
                <li key={alert.message} data-testid="review-flag" data-field={alert.field ?? ""} className="rounded-lg border border-[#222D3D] bg-[#0B0F19] px-3 py-2.5">
                  <p className="text-xs font-medium text-slate-100">{fieldLabel(alert.field)}</p>
                  <p className="text-[11px] text-slate-400">{alert.message}</p>
                  {alert.field && correctable && (
                    <dl className="mt-2 grid grid-cols-2 gap-2 text-xs">
                      <div>
                        <dt className="text-[10px] uppercase tracking-wider text-slate-500">Printed</dt>
                        <dd data-testid="review-flag-printed" className="m-0 text-slate-100">
                          {display(invoice[alert.field], alert.field, invoice.currency)}
                        </dd>
                      </div>
                      <div>
                        <dt className="text-[10px] uppercase tracking-wider text-slate-500">Computed</dt>
                        <dd data-testid="review-flag-computed" className="m-0 text-slate-100">
                          {hasComputed ? display(computed, alert.field, invoice.currency) : <span className="text-slate-500">Not sent yet</span>}
                        </dd>
                      </div>
                    </dl>
                  )}
                  <div className="mt-2 flex flex-wrap gap-2">
                    <button
                      type="button"
                      onClick={() => void resolve(alert)}
                      disabled={busy !== null}
                      className="inline-flex items-center gap-1 rounded-lg border border-[#222D3D] px-2.5 py-1 text-xs text-slate-200 hover:border-slate-500 disabled:opacity-50"
                    >
                      {saving && <Loader2 className="h-3 w-3 animate-spin" aria-hidden="true" />}
                      Accept printed
                    </button>
                    <button
                      type="button"
                      onClick={() => alert.field && hasComputed && void resolve(alert, { [alert.field]: computed as string | number })}
                      disabled={busy !== null || !correctable || !hasComputed}
                      title={!hasComputed ? "The computed value isn't sent by the server yet." : !correctable ? "This field can't be corrected." : undefined}
                      className="rounded-lg bg-[#3B82F6] px-2.5 py-1 text-xs font-semibold text-white hover:bg-[#2563EB] disabled:cursor-not-allowed disabled:opacity-50"
                    >
                      Accept computed
                    </button>
                    {onTellMeWhy && (
                      <button
                        type="button"
                        onClick={() => onTellMeWhy(`Why was ${fieldLabel(alert.field).toLowerCase()} flagged on ${invoice.invoice_number ? `invoice ${invoice.invoice_number}` : "this invoice"}? "${alert.message}"`)}
                        className="inline-flex items-center gap-1 rounded-lg px-2.5 py-1 text-xs text-slate-400 hover:bg-slate-800 hover:text-white"
                      >
                        <MessageCircleQuestion className="h-3 w-3" aria-hidden="true" />
                        Tell me why
                      </button>
                    )}
                  </div>
                </li>
              );
            })}
          </ul>
        )}

        {error && (
          <p role="alert" className="text-xs text-rose-300">
            {error}
          </p>
        )}
      </div>
    </section>
  );
}
