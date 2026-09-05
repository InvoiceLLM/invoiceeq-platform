"use client";

import React, { useEffect, useState } from "react";
import {
  Building2,
  ChevronDown,
  FileText,
  Loader2,
  Sparkles,
  UploadCloud,
  AlertTriangle,
  Inbox,
} from "lucide-react";
import { trainerService, VendorOption, VendorInvoiceOption } from "@/lib/trainer-service";
import {
  acceptedUploadExtensions,
  loadFeatureFlags,
  type FeatureFlags,
} from "@/lib/featureFlags";

/**
 * Feature 14 Component: TrainerEntryPanel
 *
 * FOR MANAGERS & DEVELOPERS:
 * The single way into a training session. There is one screen with two ways in,
 * and both land on exactly the same place — that invoice's alert list, next to
 * that invoice's PDF:
 *
 *   1. **Upload a sample invoice** (PDF or photo/scan, FE Feature 19) — works
 *      whether the vendor is brand new or already
 *      known. Runs the real OCR + extraction flow (`POST /trainer/upload`) and
 *      returns that document's real alerts.
 *   2. **Pick an existing vendor, then pick one of their invoices** — a real
 *      list, not latest-only.
 *
 * Why (2) is a two-step picker and not a vendor dropdown:
 * the endpoint it replaces, `POST /trainer/sessions/from-production?vendor_name=X`,
 * resolved `order_by(created_at.desc()).first()` — so it could only ever open a
 * vendor's *newest* invoice, and an alert on any older one was simply
 * unreachable. It is now 410 Gone. Choosing the invoice is the whole point of
 * the redesign, so it is a first-class step rather than an implicit one.
 *
 * WHERE THE INVOICE LIST COMES FROM (a real deviation, documented):
 * the backend added no trainer-side per-vendor invoice list. `GET /trainer/vendors`
 * still returns a single `sampleInvoiceId` per vendor, which is the same
 * latest-only limitation. So this uses the standard
 * `GET /api/invoices?vendor_name=X&limit=50`, which already supports the filter
 * and returns `sa_alerts` — letting each row show its real alert count, which is
 * what makes the list useful for picking *which* invoice to train on.
 */

interface TrainerEntryPanelProps {
  vendors: VendorOption[];
  selectedVendorName: string;
  onSelectVendor: (vendorName: string) => void;
  /** Opens a session on a specific stored invoice (history path). */
  onPickInvoice: (invoiceId: string) => void;
  /** Opens a session on a freshly uploaded PDF (upload path). */
  onUploadFile: (file: File) => void;
  /** True while the page is awaiting a session round-trip. */
  isBusy?: boolean;
}

function formatAmount(value?: number | null, currency?: string | null): string {
  if (value === null || value === undefined) return "—";
  const prefix = currency ? `${currency} ` : "";
  return `${prefix}${Number(value).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

function formatDate(value?: string | null): string {
  if (!value) return "—";
  const d = new Date(value);
  if (isNaN(d.getTime())) return value;
  return d.toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
}

export default function TrainerEntryPanel({
  vendors,
  selectedVendorName,
  onSelectVendor,
  onPickInvoice,
  onUploadFile,
  isBusy = false,
}: TrainerEntryPanelProps) {
  const [invoices, setInvoices] = useState<VendorInvoiceOption[]>([]);
  const [loadingInvoices, setLoadingInvoices] = useState(false);
  const [invoiceError, setInvoiceError] = useState<string | null>(null);
  const [dragActive, setDragActive] = useState(false);

  // FE Feature 19: shared accept list, same pattern as DropZone/TrainerUploader.
  const [featureFlags, setFeatureFlags] = useState<FeatureFlags | null>(null);
  useEffect(() => {
    let cancelled = false;
    void loadFeatureFlags().then((flags) => {
      if (!cancelled) setFeatureFlags(flags);
    });
    return () => {
      cancelled = true;
    };
  }, []);
  const acceptedExtensions = acceptedUploadExtensions(featureFlags);

  // Load the chosen vendor's real invoice list. Re-runs on every vendor change;
  // `cancelled` guards the case where the user switches vendor mid-flight, so a
  // slow earlier response can't overwrite a newer one.
  useEffect(() => {
    if (!selectedVendorName) {
      setInvoices([]);
      setInvoiceError(null);
      return;
    }
    let cancelled = false;
    setLoadingInvoices(true);
    setInvoiceError(null);
    trainerService
      .listVendorInvoices(selectedVendorName)
      .then((rows) => {
        if (cancelled) return;
        setInvoices(rows);
      })
      .catch(() => {
        if (cancelled) return;
        setInvoices([]);
        setInvoiceError("Couldn't load this vendor's invoices.");
      })
      .finally(() => {
        if (!cancelled) setLoadingInvoices(false);
      });
    return () => {
      cancelled = true;
    };
  }, [selectedVendorName]);

  const handleDrag = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    if (e.type === "dragenter" || e.type === "dragover") setDragActive(true);
    else if (e.type === "dragleave") setDragActive(false);
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setDragActive(false);
    if (isBusy) return;
    const file = e.dataTransfer.files?.[0];
    const lowerName = file?.name.toLowerCase() ?? "";
    if (file && acceptedExtensions.some((ext) => lowerName.endsWith(ext))) {
      onUploadFile(file);
    }
  };

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file) onUploadFile(file);
    e.target.value = "";
  };

  return (
    <div
      data-testid="trainer-entry-panel"
      className="h-full min-h-0 overflow-y-auto p-6 flex flex-col items-center"
    >
      <div className="w-full max-w-3xl space-y-5">
        <div className="text-center space-y-1.5">
          <h2 className="text-base font-semibold text-white">Pick a document to train on</h2>
          <p className="text-xs text-slate-400 leading-relaxed max-w-xl mx-auto">
            Every rule is anchored to a real alert on a real invoice. Choose one of this
            vendor&apos;s stored invoices, or upload a sample PDF — both land on the same
            place: that document&apos;s alerts, beside the document itself.
          </p>
        </div>

        {/* ── Option A: existing vendor -> one of their invoices ────────── */}
        <div className="rounded-2xl border border-[#1E2D45] bg-[#0B1120]/60 p-4 space-y-3">
          <div className="flex items-center gap-2">
            <div className="w-7 h-7 rounded-lg bg-emerald-500/10 border border-emerald-500/25 flex items-center justify-center shrink-0">
              <Building2 className="w-3.5 h-3.5 text-emerald-400" />
            </div>
            <div className="min-w-0">
              <h3 className="text-xs font-semibold text-white">Select an existing vendor</h3>
              <p className="text-[11px] text-slate-500">
                Then choose which of their invoices to open — not just the latest one.
              </p>
            </div>
          </div>

          <div className="flex items-center gap-2">
            <label
              htmlFor="trainer-entry-vendor"
              className="text-[11px] font-semibold text-emerald-400 shrink-0"
            >
              Vendor
            </label>
            <div className="relative flex-1 max-w-xs">
              <select
                id="trainer-entry-vendor"
                value={selectedVendorName || ""}
                disabled={isBusy}
                onChange={(e) => onSelectVendor(e.target.value)}
                className="w-full bg-[#111827]/80 border border-[#1E2D45] text-white text-xs rounded-xl px-3 py-2 appearance-none focus:outline-none focus:border-emerald-500/60 pr-8 transition-colors cursor-pointer disabled:opacity-50"
              >
                <option value="" disabled>
                  — Choose Vendor —
                </option>
                {vendors.map((v) => (
                  <option key={v.id} value={v.name}>
                    {v.name} ({v.invoiceCount})
                  </option>
                ))}
              </select>
              <ChevronDown className="w-3.5 h-3.5 text-slate-400 absolute right-2.5 top-2.5 pointer-events-none" />
            </div>
          </div>

          {/* The real invoice picker */}
          {selectedVendorName && (
            <div
              data-testid="trainer-invoice-picker"
              className="rounded-xl border border-[#1E2D45] bg-[#070D1A] max-h-64 overflow-y-auto"
            >
              {loadingInvoices ? (
                <div className="flex items-center gap-2 p-4 text-xs text-slate-400">
                  <Loader2 className="w-3.5 h-3.5 animate-spin text-blue-400" />
                  Loading {selectedVendorName}&apos;s invoices…
                </div>
              ) : invoiceError ? (
                <div className="flex items-start gap-2 p-4 text-xs text-red-300">
                  <AlertTriangle className="w-3.5 h-3.5 shrink-0 mt-0.5" />
                  {invoiceError}
                </div>
              ) : invoices.length === 0 ? (
                <div className="flex items-start gap-2 p-4 text-xs text-slate-500">
                  <Inbox className="w-3.5 h-3.5 shrink-0 mt-0.5" />
                  No stored invoices for this vendor yet — upload a sample PDF below instead.
                </div>
              ) : (
                <ul className="divide-y divide-[#131E2E]">
                  {invoices.map((inv) => (
                    <li key={inv.id}>
                      <button
                        type="button"
                        disabled={isBusy}
                        onClick={() => onPickInvoice(inv.id)}
                        className="w-full text-left px-3.5 py-2.5 hover:bg-[#111827] transition-colors flex items-center gap-3 disabled:opacity-50 disabled:cursor-not-allowed cursor-pointer"
                      >
                        <FileText className="w-3.5 h-3.5 text-slate-500 shrink-0" />
                        <div className="min-w-0 flex-1">
                          <div className="text-xs text-slate-200 font-medium truncate">
                            {inv.invoiceNumber || "(no invoice number)"}
                          </div>
                          <div className="text-[10px] text-slate-500 font-mono">
                            {formatDate(inv.invoiceDate || inv.createdAt)} ·{" "}
                            {formatAmount(inv.grandTotal, inv.currency)}
                            {inv.status ? ` · ${inv.status}` : ""}
                          </div>
                        </div>
                        {/* The alert count is the reason this list is worth
                            rendering at all — it is how a user finds the invoice
                            carrying the alert they want to correct. */}
                        <span
                          className={`text-[10px] font-mono px-2 py-0.5 rounded-full border shrink-0 ${
                            inv.alertCount > 0
                              ? "bg-amber-500/10 text-amber-300 border-amber-500/30"
                              : "bg-slate-700/20 text-slate-500 border-slate-700"
                          }`}
                        >
                          {inv.alertCount} alert{inv.alertCount === 1 ? "" : "s"}
                        </span>
                      </button>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          )}
        </div>

        {/* ── Option B: upload a PDF ────────────────────────────────────── */}
        <div
          onDragEnter={handleDrag}
          onDragOver={handleDrag}
          onDragLeave={handleDrag}
          onDrop={handleDrop}
          className={`rounded-2xl border p-4 space-y-3 transition-all ${
            dragActive
              ? "border-blue-500/60 bg-blue-500/5"
              : "border-[#1E2D45] bg-[#0B1120]/60"
          }`}
        >
          <div className="flex items-center gap-2">
            <div className="w-7 h-7 rounded-lg bg-blue-500/10 border border-blue-500/25 flex items-center justify-center shrink-0">
              <UploadCloud className="w-3.5 h-3.5 text-blue-400" />
            </div>
            <div className="min-w-0">
              <h3 className="text-xs font-semibold text-white">Upload a sample invoice</h3>
              <p className="text-[11px] text-slate-500">
                A brand-new vendor, or another sample from a known one. Runs the real
                extraction, so you get that document&apos;s real alerts.
              </p>
            </div>
          </div>

          <label
            className={`inline-flex items-center justify-center gap-1.5 bg-[#111827]/80 hover:bg-[#1E293B] text-white text-[11px] font-semibold px-3.5 py-2 rounded-xl border border-[#1E2D45] hover:border-blue-500/40 transition-all shadow-sm ${
              isBusy ? "opacity-50 cursor-not-allowed" : "cursor-pointer"
            }`}
          >
            <Sparkles className="w-3 h-3 text-blue-400" />
            <span>Browse</span>
            <input
              type="file"
              accept={acceptedExtensions.join(",")}
              onChange={handleFileChange}
              disabled={isBusy}
              className="hidden"
            />
          </label>
          <p className="text-[10px] text-slate-600">
            A training upload is never added to your invoice list and does not count
            against your plan&apos;s invoice allowance.
          </p>
        </div>
      </div>
    </div>
  );
}
