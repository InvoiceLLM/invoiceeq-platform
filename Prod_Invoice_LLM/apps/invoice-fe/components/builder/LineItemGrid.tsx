"use client";

import { Plus, Trash2 } from "lucide-react";
import { formatCurrency } from "@/lib/utils";
import { totalsFor } from "@/lib/invoiceBuilderMath";
import type { BuildItem, BuildRequest } from "@/types/invoice";

/**
 * Feature 20: the editable line-item grid of the Invoice Builder.
 *
 * Rows can be added and removed freely.
 *
 * FE Gap 462 (2026-09-05): this header used to carry a "Layout: exact copy /
 * re-rendered" pill and a `predictRenderMode()` that mirrored the backend's
 * `plan_render_mode()`. Both are deleted. There is one renderer now — every
 * clone is re-rendered with the source's harvested branding — so there is no
 * mode left to predict and nothing for the user to decide by adding a row.
 *
 * FE Gap 463 (2026-09-05): the grid now carries every figure a line prints —
 * HSN/SAC, unit of measure, a per-line discount and a per-line tax rate — and
 * the totals block carries the invoice-level discounts, any number of tax rates
 * and the deductions. That is why the component takes the whole `BuildRequest`
 * rather than `items` + `taxAmount`: the totals depend on all of it, and
 * `totalsFor()` (the mirror of BE `totals_for()`) is the single place that
 * knows how.
 *
 * Amounts are computed by `lib/invoiceBuilderMath.ts` for display only; the
 * server recomputes them from the same inputs and prints its own result.
 */

interface LineItemGridProps {
  value: BuildRequest;
  onChange: (patch: Partial<BuildRequest>) => void;
  disabled?: boolean;
}

const BLANK_ITEM: BuildItem = { description: "", quantity: "1", unit_price: "0" };

export default function LineItemGrid({ value, onChange, disabled }: LineItemGridProps) {
  const items = value.items;
  const currency = value.currency;
  const totals = totalsFor(value);

  const updateItem = (index: number, patch: Partial<BuildItem>) => {
    onChange({ items: items.map((item, i) => (i === index ? { ...item, ...patch } : item)) });
  };

  const addRow = () => onChange({ items: [...items, { ...BLANK_ITEM }] });
  const removeRow = (index: number) => onChange({ items: items.filter((_, i) => i !== index) });

  const inputClass =
    "w-full rounded-md border border-[#222D3D] bg-[#1E293B] px-2 py-1.5 text-xs text-slate-200 outline-none transition-colors placeholder:text-slate-600 focus:border-blue-500 disabled:cursor-not-allowed disabled:opacity-60";

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
      </div>

      <div className="overflow-x-auto p-3">
        <table className="w-full min-w-[720px] border-collapse text-left">
          <thead>
            <tr className="border-b border-[#222D3D] text-[10px] uppercase tracking-wide text-slate-500">
              <th className="pb-2 pr-3 font-medium">#</th>
              <th className="pb-2 pr-3 font-medium">Description</th>
              <th className="pb-2 pr-3 font-medium">HSN/SAC</th>
              <th className="pb-2 pr-3 text-right font-medium">Qty</th>
              <th className="pb-2 pr-3 font-medium">UOM</th>
              <th className="pb-2 pr-3 text-right font-medium">Unit Price</th>
              <th className="pb-2 pr-3 text-right font-medium">Disc %</th>
              <th className="pb-2 pr-3 text-right font-medium">Tax %</th>
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
                    className={`${inputClass} w-24`}
                    value={item.hsn_sac_code ?? ""}
                    disabled={disabled}
                    aria-label={`HSN or SAC code row ${index + 1}`}
                    data-testid={`item-hsn-sac-${index}`}
                    onChange={(e) => updateItem(index, { hsn_sac_code: e.target.value })}
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
                    className={`${inputClass} w-20`}
                    value={item.uom ?? ""}
                    disabled={disabled}
                    aria-label={`Unit of measure row ${index + 1}`}
                    data-testid={`item-uom-${index}`}
                    onChange={(e) => updateItem(index, { uom: e.target.value })}
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
                <td className="py-2 pr-3">
                  <input
                    className={`${inputClass} w-20 text-right`}
                    value={item.discount_percent == null ? "" : String(item.discount_percent)}
                    disabled={disabled}
                    inputMode="decimal"
                    aria-label={`Discount percent row ${index + 1}`}
                    data-testid={`item-discount-percent-${index}`}
                    onChange={(e) =>
                      updateItem(index, { discount_percent: e.target.value === "" ? null : e.target.value })
                    }
                  />
                </td>
                <td className="py-2 pr-3">
                  <input
                    className={`${inputClass} w-20 text-right`}
                    value={item.tax_percent == null ? "" : String(item.tax_percent)}
                    disabled={disabled}
                    inputMode="decimal"
                    aria-label={`Tax percent row ${index + 1}`}
                    data-testid={`item-tax-percent-${index}`}
                    onChange={(e) =>
                      updateItem(index, { tax_percent: e.target.value === "" ? null : e.target.value })
                    }
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

      {/* Totals — read-only figures, recomputed on every keystroke, and
          recomputed again authoritatively by the server (see
          lib/invoiceBuilderMath.ts). FE Gap 463: the discount, per-rate tax and
          deduction rows are editable here because they are money, and money
          belongs next to the figures it changes. */}
      <div className="border-t border-[#222D3D] bg-[#0B1220] px-4 py-3">
        <dl className="ml-auto flex w-full max-w-md flex-col gap-1.5 text-xs">
          <div className="flex items-center justify-between text-slate-400">
            <dt>Subtotal</dt>
            <dd data-testid="totals-subtotal" className="font-mono text-slate-200">
              {formatCurrency(totals.subtotal, currency)}
            </dd>
          </div>

          {value.discounts.map((discount, index) => (
            <div key={index} className="flex items-center gap-1.5" data-testid={`discount-row-${index}`}>
              <input
                className={`${inputClass} flex-1`}
                placeholder="Discount type"
                aria-label={`Discount type ${index + 1}`}
                data-testid={`discount-type-${index}`}
                value={discount.discount_type ?? ""}
                disabled={disabled}
                onChange={(e) =>
                  onChange({
                    discounts: value.discounts.map((d, i) =>
                      i === index ? { ...d, discount_type: e.target.value } : d
                    ),
                  })
                }
              />
              <input
                className={`${inputClass} w-16 text-right`}
                placeholder="%"
                inputMode="decimal"
                aria-label={`Discount percent ${index + 1}`}
                data-testid={`discount-percent-${index}`}
                value={discount.percent == null ? "" : String(discount.percent)}
                disabled={disabled}
                onChange={(e) =>
                  onChange({
                    discounts: value.discounts.map((d, i) =>
                      i === index ? { ...d, percent: e.target.value === "" ? null : e.target.value } : d
                    ),
                  })
                }
              />
              <input
                className={`${inputClass} w-24 text-right`}
                placeholder="amount"
                inputMode="decimal"
                aria-label={`Discount amount ${index + 1}`}
                data-testid={`discount-amount-${index}`}
                value={discount.amount == null ? "" : String(discount.amount)}
                disabled={disabled}
                onChange={(e) =>
                  onChange({
                    discounts: value.discounts.map((d, i) =>
                      i === index ? { ...d, amount: e.target.value === "" ? null : e.target.value } : d
                    ),
                  })
                }
              />
              <span className="w-24 shrink-0 text-right font-mono text-slate-300" data-testid={`discount-total-${index}`}>
                −{formatCurrency(totals.discount_lines[index] ?? 0, currency)}
              </span>
              <button
                type="button"
                onClick={() => onChange({ discounts: value.discounts.filter((_, i) => i !== index) })}
                disabled={disabled}
                aria-label={`Remove discount ${index + 1}`}
                data-testid={`remove-discount-${index}`}
                className="inline-flex shrink-0 items-center rounded-lg p-1 text-rose-400 transition-colors hover:bg-rose-500/10 disabled:opacity-40"
              >
                <Trash2 className="h-3 w-3" />
              </button>
            </div>
          ))}

          {value.taxes.length === 0 ? (
            <div className="flex items-center justify-between text-slate-400">
              <dt>
                <label htmlFor="builder-tax-amount">Tax</label>
              </dt>
              <dd>
                <input
                  id="builder-tax-amount"
                  className={`${inputClass} w-28 text-right`}
                  value={value.tax_amount == null ? "" : String(value.tax_amount)}
                  disabled={disabled}
                  inputMode="decimal"
                  data-testid="tax-amount"
                  onChange={(e) => onChange({ tax_amount: e.target.value })}
                />
              </dd>
            </div>
          ) : (
            value.taxes.map((tax, index) => (
              <div key={index} className="flex items-center gap-1.5" data-testid={`tax-row-${index}`}>
                <input
                  className={`${inputClass} flex-1`}
                  placeholder="Tax type (e.g. CGST)"
                  aria-label={`Tax type ${index + 1}`}
                  data-testid={`tax-type-${index}`}
                  value={tax.tax_type ?? ""}
                  disabled={disabled}
                  onChange={(e) =>
                    onChange({
                      taxes: value.taxes.map((t, i) =>
                        i === index ? { ...t, tax_type: e.target.value } : t
                      ),
                    })
                  }
                />
                <input
                  className={`${inputClass} w-16 text-right`}
                  placeholder="%"
                  inputMode="decimal"
                  aria-label={`Tax rate ${index + 1}`}
                  data-testid={`tax-rate-${index}`}
                  value={tax.rate_percent == null ? "" : String(tax.rate_percent)}
                  disabled={disabled}
                  onChange={(e) =>
                    onChange({
                      taxes: value.taxes.map((t, i) =>
                        i === index ? { ...t, rate_percent: e.target.value === "" ? null : e.target.value } : t
                      ),
                    })
                  }
                />
                <input
                  className={`${inputClass} w-24 text-right`}
                  placeholder="amount"
                  inputMode="decimal"
                  aria-label={`Tax amount ${index + 1}`}
                  data-testid={`tax-amount-${index}`}
                  value={tax.amount == null ? "" : String(tax.amount)}
                  disabled={disabled}
                  onChange={(e) =>
                    onChange({
                      taxes: value.taxes.map((t, i) =>
                        i === index ? { ...t, amount: e.target.value === "" ? null : e.target.value } : t
                      ),
                    })
                  }
                />
                <span className="w-24 shrink-0 text-right font-mono text-slate-300" data-testid={`tax-total-${index}`}>
                  {formatCurrency(totals.tax_lines[index] ?? 0, currency)}
                </span>
                <button
                  type="button"
                  onClick={() => onChange({ taxes: value.taxes.filter((_, i) => i !== index) })}
                  disabled={disabled}
                  aria-label={`Remove tax ${index + 1}`}
                  data-testid={`remove-tax-${index}`}
                  className="inline-flex shrink-0 items-center rounded-lg p-1 text-rose-400 transition-colors hover:bg-rose-500/10 disabled:opacity-40"
                >
                  <Trash2 className="h-3 w-3" />
                </button>
              </div>
            ))
          )}

          {value.deductions.map((deduction, index) => (
            <div key={index} className="flex items-center gap-1.5" data-testid={`deduction-row-${index}`}>
              <input
                className={`${inputClass} flex-1`}
                placeholder="Deduction (e.g. Retention)"
                aria-label={`Deduction type ${index + 1}`}
                data-testid={`deduction-type-${index}`}
                value={deduction.deduction_type ?? ""}
                disabled={disabled}
                onChange={(e) =>
                  onChange({
                    deductions: value.deductions.map((d, i) =>
                      i === index ? { ...d, deduction_type: e.target.value } : d
                    ),
                  })
                }
              />
              <input
                className={`${inputClass} w-24 text-right`}
                placeholder="amount"
                inputMode="decimal"
                aria-label={`Deduction amount ${index + 1}`}
                data-testid={`deduction-amount-${index}`}
                value={deduction.amount == null ? "" : String(deduction.amount)}
                disabled={disabled}
                onChange={(e) =>
                  onChange({
                    deductions: value.deductions.map((d, i) =>
                      i === index ? { ...d, amount: e.target.value === "" ? null : e.target.value } : d
                    ),
                  })
                }
              />
              <span className="w-24 shrink-0 text-right font-mono text-slate-300" data-testid={`deduction-total-${index}`}>
                −{formatCurrency(totals.deduction_lines[index] ?? 0, currency)}
              </span>
              <button
                type="button"
                onClick={() => onChange({ deductions: value.deductions.filter((_, i) => i !== index) })}
                disabled={disabled}
                aria-label={`Remove deduction ${index + 1}`}
                data-testid={`remove-deduction-${index}`}
                className="inline-flex shrink-0 items-center rounded-lg p-1 text-rose-400 transition-colors hover:bg-rose-500/10 disabled:opacity-40"
              >
                <Trash2 className="h-3 w-3" />
              </button>
            </div>
          ))}

          <div className="flex flex-wrap gap-1.5 pt-1">
            <button
              type="button"
              onClick={() =>
                onChange({ discounts: [...value.discounts, { discount_type: "", percent: null, amount: null }] })
              }
              disabled={disabled}
              data-testid="add-discount"
              className="inline-flex items-center gap-1 rounded-lg border border-blue-500/40 bg-blue-600/10 px-2 py-1 text-[11px] font-semibold text-blue-300 transition hover:bg-blue-600/25 disabled:opacity-50"
            >
              <Plus className="h-3 w-3" /> Discount
            </button>
            <button
              type="button"
              onClick={() =>
                onChange({ taxes: [...value.taxes, { tax_type: "", rate_percent: null, amount: null }] })
              }
              disabled={disabled}
              data-testid="add-tax"
              className="inline-flex items-center gap-1 rounded-lg border border-blue-500/40 bg-blue-600/10 px-2 py-1 text-[11px] font-semibold text-blue-300 transition hover:bg-blue-600/25 disabled:opacity-50"
            >
              <Plus className="h-3 w-3" /> Tax rate
            </button>
            <button
              type="button"
              onClick={() =>
                onChange({ deductions: [...value.deductions, { deduction_type: "", amount: null }] })
              }
              disabled={disabled}
              data-testid="add-deduction"
              className="inline-flex items-center gap-1 rounded-lg border border-blue-500/40 bg-blue-600/10 px-2 py-1 text-[11px] font-semibold text-blue-300 transition hover:bg-blue-600/25 disabled:opacity-50"
            >
              <Plus className="h-3 w-3" /> Deduction
            </button>
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
