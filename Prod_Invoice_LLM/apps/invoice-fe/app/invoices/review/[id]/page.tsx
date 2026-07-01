"use client";

import { useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { ArrowLeft, CheckCircle, XCircle, Loader2 } from "lucide-react";
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
}

const readonlyFieldClass =
  "w-full rounded-lg border border-[#222D3D] bg-[#1E293B] px-3 py-2 text-sm text-slate-300 pointer-events-none select-none outline-none";

function ReadOnlyField({ label, value }: { label: string; value?: string | null }) {
  return (
    <div className="flex flex-col gap-1">
      <label className="text-xs font-medium text-slate-500">{label}</label>
      <input className={readonlyFieldClass} value={value ?? "—"} readOnly tabIndex={-1} />
    </div>
  );
}

function fmt(val?: number | null) {
  if (val == null) return "—";
  return new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" }).format(val);
}

export default function AuditorReviewPage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();

  const [invoice, setInvoice] = useState<InvoiceDetail | null>(null);
  const [alerts, setAlerts] = useState<{ type: string; message: string }[]>([]);
  const [loading, setLoading] = useState(true);
  const [actionLoading, setActionLoading] = useState<"paid" | "rejected" | null>(null);
  const [error, setError] = useState<string | null>(null);

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

  const handleResolve = async (targetStatus: "PAID" | "REJECTED") => {
    if (!invoice) return;
    setActionLoading(targetStatus === "PAID" ? "paid" : "rejected");
    try {
      await apiClient.put(`/audit/resolve/${invoice.id}`, {
        status: targetStatus,
        dismissed_alerts: alerts.map((a) => a.message),
      });
      setInvoice((prev) => prev ? { ...prev, status: targetStatus } : prev);
      setAlerts([]);
    } catch (err) {
      console.error("Resolve failed:", err);
    } finally {
      setActionLoading(null);
    }
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
                Read-only fields
              </span>
            </div>

            {/* Alerts */}
            <AlertConsole
              invoiceId={invoice.id}
              alerts={alerts}
              currentStatus={invoice.status}
              onAlertsChange={setAlerts}
            />

            {/* Metadata Fields */}
            <div className="grid grid-cols-2 gap-3 rounded-xl border border-[#222D3D] bg-[#0F172A] p-4">
              <ReadOnlyField label="Invoice ID" value={invoice.invoice_number ?? invoice.id} />
              <ReadOnlyField label="Date" value={invoice.invoice_date ?? undefined} />
              <div className="col-span-2">
                <ReadOnlyField label="Vendor" value={invoice.vendor_name ?? undefined} />
              </div>
              <ReadOnlyField label="Total Amount" value={fmt(invoice.grand_total)} />
              <ReadOnlyField label="Tax Amount" value={fmt(invoice.tax_amount)} />
              <ReadOnlyField label="Due Date" value={invoice.due_date ?? undefined} />
              <ReadOnlyField label="PO Number" value={invoice.po_number ?? undefined} />
            </div>

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
