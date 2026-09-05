"use client";

import { AlertTriangle, Undo2, Pencil } from "lucide-react";
import type { BuildRequest } from "@/types/invoice";

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
 *   - `unlocatedFields` — the substitute path's 422. A marked field offers
 *     "revert to source", which restores the value the source PDF actually
 *     prints; an unchanged value needs no substitution, so reverting always
 *     clears that particular failure.
 *
 * The visual language (click-to-edit input with an inline "original value"
 * strip and a revert button) is deliberately the same as `EditableField` on
 * the outbound review page, so the two screens read as one console.
 */

/** Fields on this form the BE can name in `unlocated_fields`. */
export type BuilderHeaderField = "customer_name" | "invoice_number" | "invoice_date" | "due_date";

interface BuilderFormProps {
  value: BuildRequest;
  defaults: BuildRequest;
  onChange: (patch: Partial<BuildRequest>) => void;
  unlocatedFields: string[];
  duplicateNumberError: string | null;
  disabled?: boolean;
}

const FIELDS: { key: BuilderHeaderField; label: string; type: "text" | "date" }[] = [
  { key: "customer_name", label: "Customer", type: "text" },
  { key: "invoice_number", label: "Invoice Number", type: "text" },
  { key: "invoice_date", label: "Invoice Date", type: "date" },
  { key: "due_date", label: "Due Date", type: "date" },
];

function BuilderField({
  label,
  testId,
  value,
  sourceValue,
  onChange,
  onRevert,
  type,
  flagged,
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
  flagged: boolean;
  error?: string | null;
  disabled?: boolean;
}) {
  const isDirty = value !== sourceValue;

  return (
    <div className="flex flex-col gap-1" data-testid={`builder-field-${testId}`}>
      <label htmlFor={`builder-${testId}`} className="flex items-center gap-1.5 text-xs font-medium text-slate-500">
        {label}
        {isDirty && !flagged && <Pencil size={10} className="text-blue-400" />}
        {flagged && (
          <span title="This value could not be found in the source PDF">
            <AlertTriangle size={10} className="text-yellow-400" />
          </span>
        )}
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
            : flagged
            ? "border-yellow-600/70 bg-yellow-950/10 text-yellow-100"
            : isDirty
            ? "border-blue-500/60 bg-blue-950/20 text-blue-100"
            : "border-[#222D3D] bg-[#1E293B] text-slate-200 focus:border-blue-500"
        }`}
      />
      {(flagged || isDirty) && (
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

export default function BuilderForm({
  value,
  defaults,
  onChange,
  unlocatedFields,
  duplicateNumberError,
  disabled,
}: BuilderFormProps) {
  const flaggedSet = new Set(unlocatedFields);

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
            flagged={flaggedSet.has(key)}
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
    </section>
  );
}

/** Exported for the page's "any unlocated field left?" check and for tests. */
export const BUILDER_HEADER_FIELDS = FIELDS.map((f) => f.key);
