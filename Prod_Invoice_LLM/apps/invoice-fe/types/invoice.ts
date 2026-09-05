/**
 * Feature 20 (Invoice Builder — Clone & Edit): the wire shapes shared by the
 * builder page, its proxy routes and `lib/invoiceBuilderMath.ts`.
 *
 * These mirror the pydantic models in BE Feature 17
 * (`services/invoice_builder.py::BuildRequest` / `BuildItem`) exactly — the
 * builder posts this body unchanged to `/build/preview` and `/build`.
 *
 * Money and quantity fields are typed `number | string` on purpose. The
 * backend models them as `Decimal`, and pydantic v2 can serialise a Decimal
 * either as a JSON number or as a string depending on serialisation mode, so
 * the FE must tolerate both on the way in. On the way out the builder always
 * sends what the user typed, as a string, and the BE parses it — the FE's own
 * arithmetic is display-only (see `lib/invoiceBuilderMath.ts`).
 */

/** Money-ish wire value: the BE models these as `Decimal`. */
export type BuildNumber = number | string | null;

/**
 * FE Gap 463 (2026-09-05): the nested shapes below mirror
 * `services/invoice_builder.py`'s `BuildAddress`, `BuildReference`,
 * `BuildPaymentInstruction`, `BuildTaxId`, `BuildTax`, `BuildDiscount`,
 * `BuildDeduction` and `BuildComplianceItem` — which in turn mirror the
 * `Invoice` model's JSON columns. Nothing here is FE-only.
 */

/** `address_type` drives which block the renderer prints it in. */
export interface BuildAddress {
  address_type: string;
  text: string;
  country: string | null;
}

export interface BuildReference {
  ref_type: string;
  value: string;
}

export interface BuildPaymentInstruction {
  method_type: string;
  details: string;
}

export interface BuildTaxId {
  id_type: string;
  value: string;
  party: string | null;
}

/** `amount` blank means "derive it from `rate_percent`" — see `computeTotals`. */
export interface BuildTax {
  tax_type: string;
  rate_percent: BuildNumber;
  amount: BuildNumber;
}

export interface BuildDiscount {
  discount_type: string;
  percent: BuildNumber;
  amount: BuildNumber;
}

export interface BuildDeduction {
  deduction_type: string;
  amount: BuildNumber;
}

export interface BuildComplianceItem {
  key: string;
  value: string;
}

/**
 * A single editable line item. `amount` is never sent — the BE computes it.
 *
 * FE Gap 463 widened this to the rest of what a line prints. The extra fields
 * are optional because a source invoice extracted by the OUTBOUND schema
 * carries none of them, and a body without them is still valid to the BE.
 */
export interface BuildItem {
  description: string;
  quantity: number | string;
  unit_price: number | string;
  hsn_sac_code?: string | null;
  uom?: string | null;
  discount_percent?: BuildNumber;
  discount_amount?: BuildNumber;
  tax_percent?: BuildNumber;
  tax_amount?: BuildNumber;
}

/**
 * The full editable surface of a cloned invoice.
 *
 * FE Gap 463 (founder, 2026-09-05: "user can change everything… all the fields
 * address, anything thats there in the invoice"). Before this the editable set
 * stopped at customer/number/dates/currency/items/tax, which was survivable
 * only while the BE painted the new values onto the source page. BE Gap 462
 * deleted that renderer, so a field this body does not carry is no longer
 * inherited — it is simply not printed. Everything below therefore mirrors
 * `BuildRequest` in `services/invoice_builder.py` field for field.
 *
 * Still not here, and still inherited from the source PDF: the logo, the
 * letterhead and the legal footer, which the BE harvests off page 1.
 */
export interface BuildRequest {
  source_invoice_id: string;
  customer_name: string | null;
  vendor_name: string | null;
  invoice_number: string | null;
  /** ISO `YYYY-MM-DD`. */
  invoice_date: string | null;
  /** ISO `YYYY-MM-DD`; null when the source had no payment term to roll forward. */
  due_date: string | null;
  po_number: string | null;
  currency: string | null;
  items: BuildItem[];
  tax_amount: BuildNumber;
  discount_percent: BuildNumber;
  discount_amount: BuildNumber;
  addresses: BuildAddress[];
  references: BuildReference[];
  payment_instructions: BuildPaymentInstruction[];
  tax_ids: BuildTaxId[];
  taxes: BuildTax[];
  discounts: BuildDiscount[];
  deductions: BuildDeduction[];
  compliance_metadata: BuildComplianceItem[];
  /** Free text printed under the totals. The BE has no `Invoice.notes` column: it lives in `builder_intent` only, so it is not read back and does not survive into a clone-of-a-clone. */
  notes: string | null;
}

/**
 * `GET /outbound-invoices/{id}/build-defaults` returns a `BuildRequest` —
 * every field copied from the source, the invoice number incremented and the
 * dates rolled forward. Declared as its own name because the page treats the
 * first response as the immutable "source values" it can revert to.
 */
export type BuildDefaults = BuildRequest;

/** `POST /outbound-invoices/build` — same envelope the outbound upload returns. */
export interface BuildResponse {
  batch_id: string;
  invoice_id: string;
}

// FE Gap 462 (2026-09-05): `UnlocatedFieldsError` and `BuilderRenderMode` were
// deleted here along with the backend's substitution renderer. `/build/preview`
// no longer has a 422 contract, and there is only one render mode.

/**
 * Statuses a source invoice may be in for the Invoice Builder to clone it —
 * BE Feature 17 founder decision D4. `NEEDS_REVIEW` is deliberately excluded:
 * its own extracted values have not been trusted yet, so cloning them would
 * propagate an unreviewed reading. The backend enforces this with a 409 on
 * `GET /outbound-invoices/{id}/build-defaults`; the two entry points below just
 * avoid offering an action that would bounce.
 */
export const CLONE_ELIGIBLE_STATUSES = ["VERIFIED", "SENT", "PAID", "OVERDUE"] as const;

/**
 * Whether an outbound invoice may seed a clone.
 *
 * `isOverdue` is a separate argument because the outbound list endpoint models
 * overdue as a boolean on an otherwise `SENT` row rather than as a status of
 * its own — `OVERDUE` in D4's list is that condition, not a stored value.
 */
export function canCloneSource(status: string | null | undefined, isOverdue?: boolean): boolean {
  if (isOverdue) return true;
  return (CLONE_ELIGIBLE_STATUSES as readonly string[]).includes(status ?? "");
}
