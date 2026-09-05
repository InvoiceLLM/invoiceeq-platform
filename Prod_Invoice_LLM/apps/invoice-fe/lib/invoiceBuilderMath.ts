import type {
  BuildDeduction,
  BuildDiscount,
  BuildItem,
  BuildNumber,
  BuildRequest,
  BuildTax,
} from "@/types/invoice";

/**
 * Feature 20: display-only mirror of BE Feature 17's
 * `services/invoice_builder.py::compute_totals`.
 *
 * **These numbers are never sent to the backend.** The build request carries
 * only descriptions, quantities and unit prices; the server recomputes every
 * amount and total with `Decimal` + `ROUND_HALF_UP` and stores *its* result in
 * `builder_intent`. This module exists so the user sees the totals change as
 * they type, and it must agree with the server for that to be trustworthy —
 * hence the half-up rounding below rather than JavaScript's default
 * round-half-away-from-zero-on-a-binary-float.
 *
 * Rounding, matching the BE rule exactly:
 *   amount      = round(quantity × unit_price, 2)   per line, half-up
 *   subtotal    = Σ amount
 *   grand_total = subtotal + tax_amount
 */

/**
 * What `computeTotals` returns. Field names mirror the BE `Totals` model
 * (`amounts` is the FE's older name for `line_amounts`, kept so the grid and
 * its spec do not churn).
 *
 * FE Gap 463 added everything except `amounts`/`subtotal`/`tax_amount`/
 * `grand_total`. `amounts` is now net of any per-line discount, which is the
 * same number as before for every line that has no per-line discount.
 */
export interface Totals {
  /** Per-line rounded amounts, index-aligned with the items passed in. */
  amounts: number[];
  line_discounts: number[];
  line_taxes: number[];
  subtotal: number;
  discount_lines: number[];
  discount_total: number;
  tax_lines: number[];
  tax_amount: number;
  deduction_lines: number[];
  deduction_total: number;
  grand_total: number;
}

/**
 * Parses a user-typed or wire value into a number, treating blank/garbage as 0.
 *
 * The grid's inputs are text, and a half-typed "1." or "-" must not blank the
 * totals block mid-keystroke — the BE will reject a genuinely invalid body at
 * preview/create time, which is the authoritative check.
 */
export function toNumber(value: number | string | null | undefined): number {
  if (typeof value === "number") return isFinite(value) ? value : 0;
  if (value == null) return 0;
  const parsed = Number(String(value).trim().replace(/,/g, ""));
  return isFinite(parsed) ? parsed : 0;
}

/**
 * Rounds half-up at `dp` decimal places, the way Python's
 * `Decimal.quantize(..., ROUND_HALF_UP)` does — not the way `Math.round` does.
 *
 * Two differences matter:
 *   1. `Math.round(-0.005 * 100) / 100` is `-0.0`, because Math.round breaks
 *      ties towards +∞. Decimal's HALF_UP breaks them away from zero.
 *   2. A decimal literal like `1.005` is stored as 1.00499999999999989, so
 *      naive scaling rounds it *down* while the BE, holding an exact Decimal,
 *      rounds it up. Formatting to 12 decimal places first collapses that
 *      representation error (it is ~1e-16 relative for invoice-sized values,
 *      twelve orders of magnitude below the digit being inspected) so the tie
 *      is seen as the tie it is.
 */
export function roundHalfUp(value: number, dp = 2): number {
  if (!isFinite(value)) return 0;
  const negative = value < 0;
  const [whole, fraction = ""] = Math.abs(value).toFixed(12).split(".");
  const kept = fraction.slice(0, dp).padEnd(dp, "0");
  const nextDigit = Number(fraction.charAt(dp) || "0");
  let scaled = Number(whole + kept);
  if (nextDigit >= 5) scaled += 1;
  const rounded = scaled / Math.pow(10, dp);
  return negative ? -rounded : rounded;
}

/** `roundHalfUp(base × percent ÷ 100)` — the BE's `_pct()`, same name, same rule. */
function pct(base: number, percent: number | string | null | undefined): number {
  return roundHalfUp((base * toNumber(percent)) / 100);
}

/** A value the user has not filled in at all — blank means "derive me". */
function isBlank(value: number | string | null | undefined): boolean {
  return value === null || value === undefined || String(value).trim() === "";
}

/**
 * Computes the amounts and totals the backend will compute for this request.
 *
 * FE Gap 463: extended, line for line, from BE `compute_totals()` — per-line
 * discount then per-line tax, an invoice-level discount, any number of tax
 * rates on the discounted base, and deductions:
 *
 *   gross      = round(quantity × unit_price, 2)
 *   discount   = discount_amount, else gross × discount_percent%, else 0
 *   amount     = gross − discount
 *   line tax   = tax_amount, else amount × tax_percent%, else 0
 *   subtotal   = Σ amount
 *   discounts  = Σ discounts[] (amount, else % of subtotal), else the invoice
 *                discount_amount, else % of subtotal, else 0
 *   tax        = Σ taxes[] (amount, else % of subtotal − discount), else the
 *                invoice tax_amount, else Σ line tax
 *   total      = subtotal − discount + tax − deductions
 *
 * An explicitly typed amount always wins over a percentage, at every level —
 * the same rule as the server, which is what makes this mirror trustworthy.
 * These numbers are still never sent.
 *
 * @param items      the line items as edited in `LineItemGrid`
 * @param taxAmount  the header tax field, copied from the source and editable
 * @param extras     the Gap 463 fields; omitting it reproduces the old maths
 */
export function computeTotals(
  items: Pick<
    BuildItem,
    "quantity" | "unit_price" | "discount_percent" | "discount_amount" | "tax_percent" | "tax_amount"
  >[],
  taxAmount: number | string | null | undefined,
  extras: {
    discount_percent?: BuildNumber;
    discount_amount?: BuildNumber;
    taxes?: BuildTax[];
    discounts?: BuildDiscount[];
    deductions?: BuildDeduction[];
  } = {}
): Totals {
  const amounts: number[] = [];
  const line_discounts: number[] = [];
  const line_taxes: number[] = [];
  for (const item of items) {
    const gross = roundHalfUp(toNumber(item.quantity) * toNumber(item.unit_price));
    const discount = !isBlank(item.discount_amount)
      ? roundHalfUp(toNumber(item.discount_amount))
      : !isBlank(item.discount_percent)
      ? pct(gross, item.discount_percent)
      : 0;
    const amount = roundHalfUp(gross - discount);
    const lineTax = !isBlank(item.tax_amount)
      ? roundHalfUp(toNumber(item.tax_amount))
      : !isBlank(item.tax_percent)
      ? pct(amount, item.tax_percent)
      : 0;
    amounts.push(amount);
    line_discounts.push(discount);
    line_taxes.push(lineTax);
  }

  const subtotal = roundHalfUp(amounts.reduce((sum, amount) => sum + amount, 0));

  const discount_lines = (extras.discounts ?? []).map((entry) =>
    !isBlank(entry.amount) ? roundHalfUp(toNumber(entry.amount)) : pct(subtotal, entry.percent)
  );
  const discount_total = discount_lines.length
    ? roundHalfUp(discount_lines.reduce((sum, value) => sum + value, 0))
    : !isBlank(extras.discount_amount)
    ? roundHalfUp(toNumber(extras.discount_amount))
    : !isBlank(extras.discount_percent)
    ? pct(subtotal, extras.discount_percent)
    : 0;

  const base = roundHalfUp(subtotal - discount_total);
  const tax_lines = (extras.taxes ?? []).map((entry) =>
    !isBlank(entry.amount) ? roundHalfUp(toNumber(entry.amount)) : pct(base, entry.rate_percent)
  );
  const tax = tax_lines.length
    ? roundHalfUp(tax_lines.reduce((sum, value) => sum + value, 0))
    : !isBlank(taxAmount)
    ? roundHalfUp(toNumber(taxAmount))
    : roundHalfUp(line_taxes.reduce((sum, value) => sum + value, 0));

  const deduction_lines = (extras.deductions ?? []).map((entry) =>
    roundHalfUp(toNumber(entry.amount))
  );
  const deduction_total = roundHalfUp(deduction_lines.reduce((sum, value) => sum + value, 0));

  return {
    amounts,
    line_discounts,
    line_taxes,
    subtotal,
    discount_lines,
    discount_total,
    tax_lines,
    tax_amount: tax,
    deduction_lines,
    deduction_total,
    grand_total: roundHalfUp(subtotal - discount_total + tax - deduction_total),
  };
}

/**
 * `computeTotals` over a whole build request — the mirror of BE `totals_for()`.
 * The grid and the preview both call this so that a newly-added totals-bearing
 * field cannot be wired into one and forgotten in the other.
 */
export function totalsFor(request: BuildRequest): Totals {
  return computeTotals(request.items, request.tax_amount, {
    discount_percent: request.discount_percent,
    discount_amount: request.discount_amount,
    taxes: request.taxes,
    discounts: request.discounts,
    deductions: request.deductions,
  });
}
