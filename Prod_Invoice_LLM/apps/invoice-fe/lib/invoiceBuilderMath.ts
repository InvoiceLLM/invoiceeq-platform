import type { BuildItem } from "@/types/invoice";

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

/** What `computeTotals` returns. Field names mirror the BE `Totals` model. */
export interface Totals {
  /** Per-line rounded amounts, index-aligned with the items passed in. */
  amounts: number[];
  subtotal: number;
  tax_amount: number;
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

/**
 * Computes the amounts and totals the backend will compute for this request.
 *
 * @param items      the line items as edited in `LineItemGrid`
 * @param taxAmount  the header tax field, copied from the source and editable
 */
export function computeTotals(
  items: Pick<BuildItem, "quantity" | "unit_price">[],
  taxAmount: number | string | null | undefined
): Totals {
  const amounts = items.map((item) =>
    roundHalfUp(toNumber(item.quantity) * toNumber(item.unit_price))
  );
  const subtotal = roundHalfUp(amounts.reduce((sum, amount) => sum + amount, 0));
  const tax = roundHalfUp(toNumber(taxAmount));
  return {
    amounts,
    subtotal,
    tax_amount: tax,
    grand_total: roundHalfUp(subtotal + tax),
  };
}
