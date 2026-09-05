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

/** A single editable line item. `amount` is never sent — the BE computes it. */
export interface BuildItem {
  description: string;
  quantity: number | string;
  unit_price: number | string;
}

/** The full editable surface of a cloned invoice. Everything not listed here is copied from the source by the BE and is not editable in v1. */
export interface BuildRequest {
  source_invoice_id: string;
  customer_name: string | null;
  invoice_number: string | null;
  /** ISO `YYYY-MM-DD`. */
  invoice_date: string | null;
  /** ISO `YYYY-MM-DD`; null when the source had no payment term to roll forward. */
  due_date: string | null;
  currency: string | null;
  items: BuildItem[];
  tax_amount: number | string | null;
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

/** `POST /build/preview` 422 body: fields the substitute path could not locate in the source PDF. */
export interface UnlocatedFieldsError {
  unlocated_fields: string[];
}

/** Which renderer the BE will use — mirrors `plan_render_mode()`. */
export type BuilderRenderMode = "substitute" | "rerender";

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
