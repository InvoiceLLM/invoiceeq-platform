"use client";

import { Plus, Trash2, Layers, Copy } from "lucide-react";
import { formatCurrency } from "@/lib/utils";
import { computeTotals } from "@/lib/invoiceBuilderMath";
import type { BuildItem, BuilderRenderMode } from "@/types/invoice";

/**
 * Feature 20: the editable line-item grid of the Invoice Builder.
 *
 * Rows can be added and removed (founder decision D3). That choice is what
 * drives the layout pill in this component's header: BE Feature 17 renders the
 * new PDF by substituting values into the *source* PDF when the row count is
 * unchanged, and falls back to a fresh structured re-render when it is not
 * (`services/invoice_builder.py::plan_render_mode`). The pill mirrors that rule
 * client-side so the user knows which of the two looks they are going to get
 * *before* spending a preview round-trip on it. It is a prediction of the
 * server's decision, never an instruction to it — the render mode is not part
 * of the build request.
 *
 * Amounts are computed by `lib/invoiceBuilderMath.ts` for display only; the
 * server recomputes them from quantity × unit price.
 */

interface LineItemGridProps {
  items: BuildItem[];
  onChange: (items: BuildItem[]) => void;
  /** Row count of the source invoice, i.e. `build-defaults` as first loaded. */
  sourceItemCount: number;
  currency: string | null;
  taxAmount: number | string | null;
  onTaxChange: (next: string) => void;
  disabled?: boolean;
}

const BLANK_ITEM: BuildItem = { description: "", quantity: "1", unit_price: "0" };

/** Mirrors BE `plan_render_mode()`: substitution only survives an unchanged row count. */
export function predictRenderMode(itemCount: number, sourceItemCount: number): BuilderRenderMode {
  return itemCount === sourceItemCount ? "substitute" : "rerender";
}

export default function LineItemGrid({
  items,
  onChange,
  sourceItemCount,
  currency,
  taxAmount,
  onTaxChange,
  disabled,
}: LineItemGridProps) {
  const totals = computeTotals(items, taxAmount);
  const renderMode = predictRenderMode(items.length, sourceItemCount);

  const updateItem = (index: number, patch: Partial<BuildItem>) => {
    onChange(items.map((item, i) => (i === index ? { ...item, ...patch } : item)));
  };

  const addRow = () => onChange([...items, { ...BLANK_ITEM }]);
  const removeRow = (index: number) => onChange(items.filter((_, i) => i !== index));

  const inputClass =
    "w-full rounded-md border border-[#222D3D] bg-[#1E293B] px-2 py-1.5 text-xs text-slate-200 outline-none transition-colors focus:border-blue-500 disabled:cursor-not-allowed disabled:opacity-60";

  return (
    <section
      data-testid="line-item-grid"
      className="flex flex-col rounded-xl border border-[#222D3D] bg-[#0F172A] overflow-hidden"
    >
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-[#222D3D] bg-[#0B1220] px-4 py-2.5">
        <div className="flex items-center gap-2">
          <p className="text-xs font-semibold uppercase tracking-widest text-slate-400">Line Items</p>
          <span className="rounded bg-slate-800 px-2 py-0.5 font-mono text-[11px] text-slate-300 border border-slate-700">
            {items.length} rows
          </span>
        </div>
        <span
          data-testid="layout-pill"
          data-render-mode={renderMode}
          title={
            renderMode === "substitute"
              ? "The row count matches the source, so the new PDF is your source PDF with the changed values substituted in place — identical layout, logo and footer."
              : "You added or removed a row, so the invoice is laid out fresh using the logo and header harvested from the source. The look will be close but not identical."
          }
          className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-[11px] font-medium ${
            renderMode === "substitute"
              ? "border-emerald-600/50 bg-emerald-500/10 text-emerald-300"
              : "border-amber-600/50 bg-amber-500/10 text-amber-300"
          }`}
        >
          {renderMode === "substitute" ? <Copy size={11} /> : <Layers size={11} />}
          {renderMode === "substitute" ? "Layout: exact copy" : "Layout: re-rendered"}
        </span>
      </div>

      <div className="overflow-x-auto p-3">
        <table className="w-full border-collapse text-left">
          <thead>
            <tr className="border-b border-[#222D3D] text-[10px] uppercase tracking-wide text-slate-500">
              <th className="pb-2 pr-3 font-medium">#</th>
              <th className="pb-2 pr-3 font-medium">Description</th>
              <th className="pb-2 pr-3 text-right font-medium">Qty</th>
              <th className="pb-2 pr-3 text-right font-medium">Unit Price</th>
              <th className="pb-2 pr-3 text-right font-medium">Amount</th>
              <th className="pb-2 text-right font-medium"></th>
            </tr>
          </thead>
          <tbody className="divide-y divide-[#222D3D]/60 text-xs text-slate-300">
            {items.map((item, index) => (
              <tr key={index} data-testid={`line-item-row-${index}`}>
                <td className="py-2 pr-3 text-slate-500">{index + 1}</td>
                <td className="py-2 pr-3">
                  <input
                    className={inputClass}
                    value={item.description ?? ""}
                    disabled={disabled}
                    aria-label={`Description row ${index + 1}`}
                    data-testid={`item-description-${index}`}
                    onChange={(e) => updateItem(index, { description: e.target.value })}
                  />
                </td>
                <td className="py-2 pr-3">
                  <input
                    className={`${inputClass} text-right`}
                    value={String(item.quantity ?? "")}
                    disabled={disabled}
                    inputMode="decimal"
                    aria-label={`Quantity row ${index + 1}`}
                    data-testid={`item-quantity-${index}`}
                    onChange={(e) => updateItem(index, { quantity: e.target.value })}
                  />
                </td>
                <td className="py-2 pr-3">
                  <input
                    className={`${inputClass} text-right`}
                    value={String(item.unit_price ?? "")}
                    disabled={disabled}
                    inputMode="decimal"
                    aria-label={`Unit price row ${index + 1}`}
                    data-testid={`item-unit-price-${index}`}
                    onChange={(e) => updateItem(index, { unit_price: e.target.value })}
                  />
                </td>
                <td
                  className="py-2 pr-3 text-right font-medium text-slate-200"
                  data-testid={`item-amount-${index}`}
                >
                  {formatCurrency(totals.amounts[index] ?? 0, currency)}
                </td>
                <td className="py-2 text-right">
                  <button
                    type="button"
                    onClick={() => removeRow(index)}
                    disabled={disabled || items.length <= 1}
                    title={items.length <= 1 ? "An invoice needs at least one line" : "Remove this row"}
                    aria-label={`Remove row ${index + 1}`}
                    data-testid={`remove-row-${index}`}
                    className="inline-flex items-center rounded-lg p-1.5 text-rose-400 transition-colors hover:bg-rose-500/10 hover:text-rose-300 disabled:cursor-not-allowed disabled:opacity-40"
                  >
                    <Trash2 className="h-3.5 w-3.5" />
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>

        <button
          type="button"
          onClick={addRow}
          disabled={disabled}
          data-testid="add-row"
          className="mt-3 inline-flex items-center gap-1.5 rounded-lg border border-blue-500/40 bg-blue-600/10 px-3 py-1.5 text-xs font-semibold text-blue-300 transition hover:bg-blue-600/25 disabled:opacity-50"
        >
          <Plus className="h-3.5 w-3.5" /> Add row
        </button>
      </div>

      {/* Totals — read-only, recomputed on every keystroke, and recomputed
          again authoritatively by the server (see lib/invoiceBuilderMath.ts). */}
      <div className="border-t border-[#222D3D] bg-[#0B1220] px-4 py-3">
        <dl className="ml-auto flex w-full max-w-xs flex-col gap-1.5 text-xs">
          <div className="flex items-center justify-between text-slate-400">
            <dt>Subtotal</dt>
            <dd data-testid="totals-subtotal" className="font-mono text-slate-200">
              {formatCurrency(totals.subtotal, currency)}
            </dd>
          </div>
          <div className="flex items-center justify-between text-slate-400">
            <dt>
              <label htmlFor="builder-tax-amount">Tax</label>
            </dt>
            <dd>
              <input
                id="builder-tax-amount"
                className={`${inputClass} w-28 text-right`}
                value={taxAmount == null ? "" : String(taxAmount)}
                disabled={disabled}
                inputMode="decimal"
                data-testid="tax-amount"
                onChange={(e) => onTaxChange(e.target.value)}
              />
            </dd>
          </div>
          <div className="flex items-center justify-between border-t border-[#222D3D] pt-1.5 text-sm font-semibold text-slate-100">
            <dt>Total</dt>
            <dd data-testid="totals-grand-total" className="font-mono">
              {formatCurrency(totals.grand_total, currency)}
            </dd>
          </div>
        </dl>
      </div>
    </section>
  );
}
