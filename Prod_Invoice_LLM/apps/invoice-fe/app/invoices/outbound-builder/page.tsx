"use client";

import { Suspense, useCallback, useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import Link from "next/link";
import { Loader2, XCircle, FilePlus2, ArrowLeft } from "lucide-react";
import BuilderForm from "@/components/builder/BuilderForm";
import LineItemGrid from "@/components/builder/LineItemGrid";
import BuilderPreview from "@/components/builder/BuilderPreview";
import { PageHeaderActions, usePageHeader } from "@/components/layout/PageHeaderContext";
import type { BuildDefaults, BuildRequest, BuildResponse } from "@/types/invoice";

/**
 * Feature 20: the Invoice Builder — create a new outbound invoice by cloning an
 * existing one.
 *
 * Reached only from an existing invoice (founder decision, 2026-09-04): the
 * outbound review page header and the outbound table row, both of which link
 * here with `?source=<id>` and only offer the action for a source in
 * VERIFIED/SENT/PAID/OVERDUE. There is deliberately no source picker — the user
 * chooses the source first, then builds.
 *
 * The whole screen is a thin editor over BE Feature 17's contract:
 *   GET  /outbound-invoices/{id}/build-defaults  → prefill (404/409 = ineligible)
 *   POST /outbound-invoices/build/preview        → the real PDF, nothing stored
 *   POST /outbound-invoices/build                → {batch_id, invoice_id}
 *
 * Totals shown here come from `lib/invoiceBuilderMath.ts` and are never sent;
 * the server recomputes them (BE `compute_totals`) and stores its own result in
 * `builder_intent`, which the worker later checks against what the extractor
 * reads back off the generated PDF.
 */

/** `<input type="date">` needs a bare `YYYY-MM-DD`; the BE may serialise a full ISO timestamp. */
function toDateInput(value: string | null | undefined): string | null {
  if (!value) return null;
  return String(value).slice(0, 10);
}

/**
 * FE Gap 463: every list is defaulted to `[]` here rather than left undefined.
 * The BE always sends them, but the form maps over all of them unconditionally
 * and a single missing key would blank the whole screen — and these are the
 * fields that, since BE Gap 462, are printed only if this body carries them.
 */
function normaliseDefaults(raw: BuildDefaults): BuildDefaults {
  return {
    ...raw,
    invoice_date: toDateInput(raw.invoice_date),
    due_date: toDateInput(raw.due_date),
    items: (raw.items ?? []).map((item) => ({
      ...item,
      description: item.description ?? "",
      quantity: item.quantity ?? "",
      unit_price: item.unit_price ?? "",
    })),
    addresses: raw.addresses ?? [],
    references: raw.references ?? [],
    payment_instructions: raw.payment_instructions ?? [],
    tax_ids: raw.tax_ids ?? [],
    taxes: raw.taxes ?? [],
    discounts: raw.discounts ?? [],
    deductions: raw.deductions ?? [],
    compliance_metadata: raw.compliance_metadata ?? [],
    notes: raw.notes ?? null,
  };
}

function OutboundBuilderContent() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const sourceId = searchParams.get("source");

  const [defaults, setDefaults] = useState<BuildDefaults | null>(null);
  const [form, setForm] = useState<BuildRequest | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [duplicateNumberError, setDuplicateNumberError] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [createError, setCreateError] = useState<string | null>(null);
  const [dirtySinceLastPreview, setDirtySinceLastPreview] = useState(false);

  usePageHeader({
    title: "Invoice Builder",
    agentIcon: "🛡️",
    agentName: "SENTINEL",
    agentRole: "Audit & Compliance",
    subtitle: form?.invoice_number ? `New invoice ${form.invoice_number}` : "New invoice from an existing one",
    backHref: "/invoices",
  });

  useEffect(() => {
    if (!sourceId) {
      setLoadError("No source invoice was given. Start from an existing invoice's Clone action.");
      setLoading(false);
      return;
    }
    let cancelled = false;
    (async () => {
      try {
        const response = await fetch(`/api/outbound-invoices/${sourceId}/build-defaults`, {
          cache: "no-store",
        });
        if (cancelled) return;
        if (!response.ok) {
          const payload = await response.json().catch(() => null);
          // 409 is the eligibility rule (founder decision D4): a NEEDS_REVIEW
          // source's own values are not trusted yet, so it cannot be cloned.
          // 404 is "not this tenant's invoice / not outbound / no stored PDF".
          setLoadError(
            (payload && (payload.detail as string)) ||
              (response.status === 409
                ? "This invoice cannot be used as a source — only verified, sent, paid or overdue invoices can be cloned."
                : response.status === 404
                ? "Source invoice not found."
                : `Could not load the source invoice (${response.status}).`)
          );
          return;
        }
        const data = normaliseDefaults((await response.json()) as BuildDefaults);
        setDefaults(data);
        setForm(data);
      } catch {
        if (!cancelled) setLoadError("Could not load the source invoice.");
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [sourceId]);

  const patchForm = useCallback((patch: Partial<BuildRequest>) => {
    setForm((prev) => (prev ? { ...prev, ...patch } : prev));
    setDirtySinceLastPreview(true);
  }, []);

  const handleCreate = async () => {
    if (!form) return;
    setCreating(true);
    setCreateError(null);
    setDuplicateNumberError(null);
    try {
      const response = await fetch("/api/outbound-invoices/build", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(form),
      });
      const payload = await response.json().catch(() => null);

      if (response.status === 409) {
        const message =
          (payload && (payload.detail as string)) || "Invoice number already used for this customer";
        setDuplicateNumberError(message);
        setCreateError(message);
        return;
      }
      // FE Gap 462 (2026-09-05): a 422 branch used to sit here, mirroring
      // Preview's. It was the reason Create appeared to do nothing on an
      // ordinary clone — the backend's substitution renderer refused, and this
      // told the user to revert a field or add/remove a row. That renderer is
      // deleted; `/build` has no 422 contract left.
      if (!response.ok) {
        setCreateError(
          (payload && ((payload.detail as string) || (payload.message as string))) ||
            `Could not create the invoice (${response.status}).`
        );
        return;
      }

      const created = payload as BuildResponse;
      // The new invoice enters the ordinary outbound pipeline, so the place to
      // watch it is the Sending tab's status ledger — the same one an upload
      // lands in. The ids travel as query params because that ledger's state is
      // per-page and would otherwise be empty on arrival.
      const label = encodeURIComponent(form.invoice_number || "New invoice");
      router.push(
        `/ingestion?tab=sending&builtInvoice=${created.invoice_id}&batch=${created.batch_id}&name=${label}`
      );
    } catch {
      setCreateError("Could not create the invoice — the server could not be reached.");
    } finally {
      setCreating(false);
    }
  };

  if (loading) {
    return (
      <div className="flex h-96 items-center justify-center text-slate-400">
        <Loader2 size={28} className="animate-spin" />
      </div>
    );
  }

  if (loadError || !form || !defaults) {
    return (
      <div
        data-testid="builder-load-error"
        className="flex h-96 flex-col items-center justify-center gap-3 px-6 text-center text-slate-400"
      >
        <XCircle size={32} className="text-red-400" />
        <p className="max-w-md text-sm">{loadError ?? "Something went wrong."}</p>
        <Link
          href="/invoices"
          className="inline-flex items-center gap-1.5 rounded-lg border border-[#222D3D] px-3 py-1.5 text-xs font-semibold text-slate-300 transition hover:border-slate-500 hover:text-slate-100"
        >
          <ArrowLeft size={13} /> Back to invoices
        </Link>
      </div>
    );
  }

  return (
    <div className="flex h-full flex-col gap-4 p-6 overflow-y-auto custom-scrollbar">
      <PageHeaderActions>
        <Link
          href={`/invoices/outbound-review/${defaults.source_invoice_id}`}
          data-testid="builder-source-link"
          className="whitespace-nowrap rounded-lg border border-[#222D3D] px-2 sm:px-3 py-1 sm:py-1.5 text-[10px] sm:text-xs font-medium text-slate-300 transition hover:border-slate-500 hover:text-slate-100"
        >
          Cloned from source invoice
        </Link>
        <button
          onClick={handleCreate}
          disabled={creating}
          data-testid="create-invoice"
          className="flex items-center gap-1.5 whitespace-nowrap rounded-lg border border-emerald-500/50 bg-emerald-600/20 px-2 sm:px-3 py-1 sm:py-1.5 text-[10px] sm:text-xs font-semibold text-emerald-300 transition hover:bg-emerald-600/40 disabled:opacity-50"
        >
          {creating ? <Loader2 size={13} className="animate-spin" /> : <FilePlus2 size={13} />}
          Create invoice
        </button>
      </PageHeaderActions>

      {createError && (
        <div
          data-testid="create-error"
          className="rounded-lg border border-rose-600/40 bg-rose-950/20 px-3 py-2 text-xs text-rose-200"
        >
          {createError}
        </div>
      )}

      <div className="grid grid-cols-1 gap-4 xl:grid-cols-[minmax(0,1fr)_minmax(0,1.1fr)]">
        <div className="flex flex-col gap-4">
          <BuilderForm
            value={form}
            defaults={defaults}
            onChange={patchForm}
            duplicateNumberError={duplicateNumberError}
            disabled={creating}
          />
          {/* FE Gap 463: the grid takes the whole request now — the totals
              depend on the invoice-level discounts, tax rates and deductions
              it also edits, not on the items alone. */}
          <LineItemGrid value={form} onChange={patchForm} disabled={creating} />
          <p className="text-[11px] text-slate-500">
            The invoice is laid out fresh from the source&apos;s logo and header, so rows can be added
            or removed freely. Totals are shown for your benefit and are recalculated on the server
            before anything is printed.
          </p>
        </div>

        <BuilderPreview
          body={form}
          dirtySinceLastPreview={dirtySinceLastPreview}
          onDirtyCleared={() => setDirtySinceLastPreview(false)}
          onDuplicateNumber={setDuplicateNumberError}
          disabled={creating}
        />
      </div>
    </div>
  );
}

export default function OutboundBuilderPage() {
  return (
    <Suspense fallback={<div className="p-8 text-xs text-white">Loading Invoice Builder…</div>}>
      <OutboundBuilderContent />
    </Suspense>
  );
}
