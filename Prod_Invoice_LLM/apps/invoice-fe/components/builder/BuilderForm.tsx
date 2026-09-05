"use client";

import { Undo2, Pencil, Plus, Trash2 } from "lucide-react";
import type { BuildAddress, BuildRequest } from "@/types/invoice";

/**
 * Feature 20: the header fields of the Invoice Builder — customer, invoice
 * number, dates and currency.
 *
 * Everything here is prefilled from `GET /outbound-invoices/{id}/build-defaults`
 * (customer/currency copied, number incremented, dates rolled by the source's
 * payment term). Currency is read-only in v1: the substitution renderer prints
 * into the source PDF's own layout, so a different currency symbol would have
 * nowhere consistent to go — BE `BuildRequest` copies it from the source.
 *
 * Two error surfaces are driven from the page:
 *   - `duplicateNumberError` — the BE's 409 for founder decision D5 (an
 *     invoice number already used for this customer), shown against the number
 *     field rather than as a page-level banner because that is the field the
 *     user has to change.
 * FE Gap 462 (2026-09-05): a second surface, `unlocatedFields`, is deleted.
 * It flagged the fields the backend's substitution renderer could not find in
 * the source PDF and pushed the user to revert them. That renderer is gone.
 * The per-field "revert to source" button stays — it is an ordinary editing
 * convenience on a cloned value, not part of the deleted error path.
 *
 * The visual language (click-to-edit input with an inline "original value"
 * strip and a revert button) is deliberately the same as `EditableField` on
 * the outbound review page, so the two screens read as one console.
 */

/**
 * FE Gap 463 (2026-09-05), founder-approved: "user can change everything… all
 * the fields address, anything thats there in the invoice". This form now
 * carries the vendor name, the PO number, the three address blocks, the
 * secondary references, the payment instructions, the tax IDs, the compliance
 * metadata and a notes box — because since BE Gap 462 deleted the substitution
 * renderer, a field the request does not carry is not inherited from the source
 * page any more, it is simply not printed. The money-side additions (tax rates,
 * discounts, deductions) live in `LineItemGrid` with the other figures.
 */

/** The editable header fields of a clone. */
export type BuilderHeaderField =
  | "customer_name"
  | "vendor_name"
  | "invoice_number"
  | "invoice_date"
  | "due_date"
  | "po_number";

interface BuilderFormProps {
  value: BuildRequest;
  defaults: BuildRequest;
  onChange: (patch: Partial<BuildRequest>) => void;
  duplicateNumberError: string | null;
  disabled?: boolean;
}

const FIELDS: { key: BuilderHeaderField; label: string; type: "text" | "date" }[] = [
  { key: "customer_name", label: "Customer", type: "text" },
  { key: "vendor_name", label: "Your Business Name", type: "text" },
  { key: "invoice_number", label: "Invoice Number", type: "text" },
  { key: "invoice_date", label: "Invoice Date", type: "date" },
  { key: "due_date", label: "Due Date", type: "date" },
  { key: "po_number", label: "PO Number", type: "text" },
];

/** The three address blocks the BE renderer places, in the order it places them. */
const ADDRESS_BLOCKS: { type: string; label: string }[] = [
  { type: "billing", label: "Bill To Address" },
  { type: "shipping", label: "Ship To Address" },
  { type: "vendor", label: "Your Address" },
];

function BuilderField({
  label,
  testId,
  value,
  sourceValue,
  onChange,
  onRevert,
  type,
  error,
  disabled,
}: {
  label: string;
  testId: string;
  value: string;
  sourceValue: string;
  onChange: (next: string) => void;
  onRevert: () => void;
  type: "text" | "date";
  error?: string | null;
  disabled?: boolean;
}) {
  const isDirty = value !== sourceValue;

  return (
    <div className="flex flex-col gap-1" data-testid={`builder-field-${testId}`}>
      <label htmlFor={`builder-${testId}`} className="flex items-center gap-1.5 text-xs font-medium text-slate-500">
        {label}
        {isDirty && <Pencil size={10} className="text-blue-400" />}
      </label>
      <input
        id={`builder-${testId}`}
        data-testid={`builder-input-${testId}`}
        type={type}
        value={value}
        disabled={disabled}
        onChange={(e) => onChange(e.target.value)}
        className={`w-full rounded-lg border px-3 py-2 text-sm outline-none transition-colors disabled:cursor-not-allowed disabled:opacity-60 ${
          error
            ? "border-rose-500/70 bg-rose-950/20 text-rose-100"
            : isDirty
            ? "border-blue-500/60 bg-blue-950/20 text-blue-100"
            : "border-[#222D3D] bg-[#1E293B] text-slate-200 focus:border-blue-500"
        }`}
      />
      {isDirty && (
        <div className="flex items-center gap-1.5 rounded-md border border-[#222D3D] bg-[#0B1220] px-2 py-1 text-[11px]">
          <span className="shrink-0 text-slate-500">Source</span>
          <span className="min-w-0 flex-1 truncate text-slate-500" title={sourceValue}>
            {sourceValue || "empty"}
          </span>
          {isDirty && (
            <button
              type="button"
              onClick={onRevert}
              data-testid={`builder-revert-${testId}`}
              disabled={disabled}
              className="flex shrink-0 items-center gap-1 rounded border border-slate-600/50 px-1.5 py-0.5 text-slate-400 transition hover:border-slate-400 hover:text-slate-200"
              title={`Revert ${label} to the source invoice's value`}
            >
              <Undo2 size={10} /> Revert to source
            </button>
          )}
        </div>
      )}
      {error && (
        <p data-testid={`builder-error-${testId}`} className="text-[11px] text-rose-300">
          {error}
        </p>
      )}
    </div>
  );
}

/**
 * A multi-line block (an address, the notes). Same visual language as
 * `BuilderField`, minus the revert strip — reverting a five-line address to the
 * source is what the browser's own undo is for, and a strip that tall would
 * push the line items off the screen.
 */
function BuilderTextArea({
  label,
  testId,
  value,
  placeholder,
  rows,
  onChange,
  disabled,
}: {
  label: string;
  testId: string;
  value: string;
  placeholder?: string;
  rows?: number;
  onChange: (next: string) => void;
  disabled?: boolean;
}) {
  return (
    <div className="flex flex-col gap-1" data-testid={`builder-field-${testId}`}>
      <label htmlFor={`builder-${testId}`} className="text-xs font-medium text-slate-500">
        {label}
      </label>
      <textarea
        id={`builder-${testId}`}
        data-testid={`builder-input-${testId}`}
        rows={rows ?? 3}
        value={value}
        placeholder={placeholder}
        disabled={disabled}
        onChange={(e) => onChange(e.target.value)}
        className="w-full resize-y rounded-lg border border-[#222D3D] bg-[#1E293B] px-3 py-2 text-sm text-slate-200 outline-none transition-colors placeholder:text-slate-600 focus:border-blue-500 disabled:cursor-not-allowed disabled:opacity-60"
      />
    </div>
  );
}

/**
 * A repeatable two- or three-column list — references, payment instructions,
 * tax IDs, compliance metadata. All of them are `{label, value}` pairs in the
 * BE model, so one editor serves all four rather than four near-identical ones.
 */
function ListEditor<T extends object>({
  label,
  testId,
  rows,
  columns,
  blank,
  onChange,
  disabled,
}: {
  label: string;
  testId: string;
  rows: T[];
  columns: { key: keyof T & string; placeholder: string; grow?: boolean }[];
  blank: T;
  onChange: (rows: T[]) => void;
  disabled?: boolean;
}) {
  const inputClass =
    "w-full rounded-md border border-[#222D3D] bg-[#1E293B] px-2 py-1.5 text-xs text-slate-200 outline-none transition-colors placeholder:text-slate-600 focus:border-blue-500 disabled:cursor-not-allowed disabled:opacity-60";

  return (
    <div className="flex flex-col gap-1.5" data-testid={`builder-list-${testId}`}>
      <span className="text-xs font-medium text-slate-500">{label}</span>
      {rows.map((row, index) => (
        <div key={index} className="flex items-center gap-1.5" data-testid={`${testId}-row-${index}`}>
          {columns.map((column) => (
            <input
              key={column.key}
              className={`${inputClass} ${column.grow ? "flex-[2]" : "flex-1"}`}
              placeholder={column.placeholder}
              aria-label={`${label} ${column.placeholder} ${index + 1}`}
              data-testid={`${testId}-${column.key}-${index}`}
              value={String((row[column.key] as unknown as string) ?? "")}
              disabled={disabled}
              onChange={(e) =>
                onChange(
                  rows.map((existing, i) =>
                    i === index ? ({ ...existing, [column.key]: e.target.value } as T) : existing
                  )
                )
              }
            />
          ))}
          <button
            type="button"
            onClick={() => onChange(rows.filter((_, i) => i !== index))}
            disabled={disabled}
            aria-label={`Remove ${label} ${index + 1}`}
            data-testid={`${testId}-remove-${index}`}
            className="inline-flex shrink-0 items-center rounded-lg p-1.5 text-rose-400 transition-colors hover:bg-rose-500/10 hover:text-rose-300 disabled:cursor-not-allowed disabled:opacity-40"
          >
            <Trash2 className="h-3.5 w-3.5" />
          </button>
        </div>
      ))}
      <button
        type="button"
        onClick={() => onChange([...rows, { ...blank }])}
        disabled={disabled}
        data-testid={`${testId}-add`}
        className="inline-flex w-fit items-center gap-1.5 rounded-lg border border-blue-500/40 bg-blue-600/10 px-2.5 py-1 text-[11px] font-semibold text-blue-300 transition hover:bg-blue-600/25 disabled:opacity-50"
      >
        <Plus className="h-3 w-3" /> Add {label.toLowerCase()}
      </button>
    </div>
  );
}

export default function BuilderForm({
  value,
  defaults,
  onChange,
  duplicateNumberError,
  disabled,
}: BuilderFormProps) {
  return (
    <section
      data-testid="builder-form"
      className="flex flex-col rounded-xl border border-[#222D3D] bg-[#0F172A] overflow-hidden"
    >
      <div className="flex items-center justify-between gap-2 border-b border-[#222D3D] bg-[#0B1220] px-4 py-2.5">
        <p className="text-xs font-semibold uppercase tracking-widest text-slate-400">Invoice Details</p>
        <span className="shrink-0 rounded-md border border-[#222D3D] px-2 py-0.5 text-[11px] text-slate-500">
          Copied from the source — edit what changes
        </span>
      </div>

      <div className="flex flex-col gap-3 p-4">
        {FIELDS.map(({ key, label, type }) => (
          <BuilderField
            key={key}
            label={label}
            testId={key.replace(/_/g, "-")}
            type={type}
            value={(value[key] as string | null) ?? ""}
            sourceValue={(defaults[key] as string | null) ?? ""}
            error={key === "invoice_number" ? duplicateNumberError : null}
            disabled={disabled}
            onChange={(next) => onChange({ [key]: next } as Partial<BuildRequest>)}
            onRevert={() => onChange({ [key]: defaults[key] } as Partial<BuildRequest>)}
          />
        ))}

        <div className="flex flex-col gap-1">
          <label htmlFor="builder-currency" className="text-xs font-medium text-slate-500">
            Currency
          </label>
          <input
            id="builder-currency"
            data-testid="builder-input-currency"
            readOnly
            value={value.currency ?? ""}
            title="Copied from the source invoice; not editable in v1."
            className="w-full cursor-not-allowed select-none rounded-lg border border-[#222D3D] bg-[#1E293B] px-3 py-2 text-sm text-slate-400"
          />
        </div>
      </div>

      {/* FE Gap 463: the address blocks. Each one is stored as an entry in
          `addresses` keyed by `address_type`, which is what the BE renderer
          reads to decide which block to print it in — so an empty box removes
          the entry rather than printing an empty "Ship To". */}
      <div className="flex flex-col gap-3 border-t border-[#222D3D] px-4 py-4">
        <p className="text-xs font-semibold uppercase tracking-widest text-slate-400">Addresses</p>
        {ADDRESS_BLOCKS.map(({ type, label }) => (
          <BuilderTextArea
            key={type}
            label={label}
            testId={`address-${type}`}
            value={addressText(value, type)}
            placeholder="Street, city, postcode"
            onChange={(next) => onChange({ addresses: withAddress(value.addresses, type, next) })}
            disabled={disabled}
          />
        ))}
      </div>

      <div className="flex flex-col gap-3 border-t border-[#222D3D] px-4 py-4">
        <p className="text-xs font-semibold uppercase tracking-widest text-slate-400">
          References &amp; Payment
        </p>
        <ListEditor
          label="References"
          testId="references"
          rows={value.references}
          columns={[
            { key: "ref_type", placeholder: "Type (e.g. Sales Order)" },
            { key: "value", placeholder: "Value", grow: true },
          ]}
          blank={{ ref_type: "", value: "" }}
          onChange={(references) => onChange({ references })}
          disabled={disabled}
        />
        <ListEditor
          label="Payment instructions"
          testId="payment-instructions"
          rows={value.payment_instructions}
          columns={[
            { key: "method_type", placeholder: "Method (e.g. IBAN)" },
            { key: "details", placeholder: "Details", grow: true },
          ]}
          blank={{ method_type: "", details: "" }}
          onChange={(payment_instructions) => onChange({ payment_instructions })}
          disabled={disabled}
        />
        <BuilderTextArea
          label="Notes / terms"
          testId="notes"
          value={value.notes ?? ""}
          placeholder="Printed under the totals — payment terms, thanks, anything the invoice says."
          onChange={(next) => onChange({ notes: next })}
          disabled={disabled}
        />
      </div>

      <div className="flex flex-col gap-3 border-t border-[#222D3D] px-4 py-4">
        <p className="text-xs font-semibold uppercase tracking-widest text-slate-400">
          Tax IDs &amp; Compliance
        </p>
        <ListEditor
          label="Tax IDs"
          testId="tax-ids"
          rows={value.tax_ids}
          columns={[
            { key: "id_type", placeholder: "Type (e.g. GSTIN)" },
            { key: "value", placeholder: "Number", grow: true },
            { key: "party", placeholder: "vendor / buyer" },
          ]}
          blank={{ id_type: "", value: "", party: null }}
          onChange={(tax_ids) => onChange({ tax_ids })}
          disabled={disabled}
        />
        <ListEditor
          label="Compliance metadata"
          testId="compliance-metadata"
          rows={value.compliance_metadata}
          columns={[
            { key: "key", placeholder: "Key (e.g. IRN)" },
            { key: "value", placeholder: "Value", grow: true },
          ]}
          blank={{ key: "", value: "" }}
          onChange={(compliance_metadata) => onChange({ compliance_metadata })}
          disabled={disabled}
        />
      </div>
    </section>
  );
}

/** The text of the one address of this type, or "" when there is none. */
export function addressText(value: BuildRequest, addressType: string): string {
  const found = (value.addresses ?? []).find(
    (address) => (address.address_type ?? "").toLowerCase() === addressType
  );
  return found?.text ?? "";
}

/**
 * Sets (or clears) one address block, leaving every other entry — including an
 * address whose type the FE does not have a box for — exactly where it was.
 * Clearing the box drops the entry, so the BE prints no empty heading.
 */
export function withAddress(
  addresses: BuildAddress[],
  addressType: string,
  text: string
): BuildAddress[] {
  const rest = (addresses ?? []).filter(
    (address) => (address.address_type ?? "").toLowerCase() !== addressType
  );
  if (!text.trim()) return rest;
  const existing = (addresses ?? []).find(
    (address) => (address.address_type ?? "").toLowerCase() === addressType
  );
  const updated: BuildAddress = {
    address_type: addressType,
    text,
    country: existing?.country ?? null,
  };
  // Keep the original position so the blocks do not reorder as they are typed.
  const index = (addresses ?? []).findIndex(
    (address) => (address.address_type ?? "").toLowerCase() === addressType
  );
  if (index < 0) return [...rest, updated];
  const next = [...(addresses ?? [])];
  next[index] = updated;
  return next;
}

/** Exported for tests. */
export const BUILDER_HEADER_FIELDS = FIELDS.map((f) => f.key);
