/**
 * BE Gap 531: the list-shaped invoice details the review pages can correct.
 *
 * Each column mirrors the backend model the correction is validated against
 * (`agents/extraction_agent.py`: TaxItem, TaxIdItem, AddressItem, …). The server
 * refuses an entry that is missing a required column or carries an unknown one,
 * and names the entry — the page shows that in its "Not saved" banner (FE Gap 499).
 */
export type DetailFormat = "money" | "percent";

export type DetailColumn = {
  key: string;
  label: string;
  kind: "text" | "number";
  required?: boolean;
  format?: DetailFormat;
};

export type DetailListSpec = {
  /** The Invoice field name sent in `corrections`. */
  field: string;
  label: string;
  /** Singular, for "Add …" and "Remove …". */
  entryLabel: string;
  columns: DetailColumn[];
};

export type DetailEntry = Record<string, string | number | undefined>;

const TAX_IDS: DetailListSpec = {
  field: "tax_ids",
  label: "Tax IDs",
  entryLabel: "tax ID",
  columns: [
    { key: "id_type", label: "Type (GSTIN, PAN, VAT…)", kind: "text", required: true },
    { key: "value", label: "Number", kind: "text", required: true },
    { key: "party", label: "Party (vendor or buyer)", kind: "text" },
  ],
};

const TAXES: DetailListSpec = {
  field: "taxes",
  label: "Tax Breakdown",
  entryLabel: "tax line",
  columns: [
    { key: "tax_type", label: "Tax (CGST, SGST, VAT…)", kind: "text", required: true },
    { key: "rate_percent", label: "Rate %", kind: "number", format: "percent" },
    { key: "amount", label: "Amount", kind: "number", required: true, format: "money" },
  ],
};

const PAYMENT_INSTRUCTIONS: DetailListSpec = {
  field: "payment_instructions",
  label: "Payment Instructions",
  entryLabel: "payment instruction",
  columns: [
    { key: "method_type", label: "Method (IBAN+SWIFT, UPI…)", kind: "text", required: true },
    { key: "details", label: "Details", kind: "text", required: true },
  ],
};

const REFERENCES: DetailListSpec = {
  field: "references",
  label: "References",
  entryLabel: "reference",
  columns: [
    { key: "ref_type", label: "Type (Sales Order, e-Way Bill…)", kind: "text", required: true },
    { key: "value", label: "Value", kind: "text", required: true },
  ],
};

const DISCOUNTS: DetailListSpec = {
  field: "discounts",
  label: "Discount Breakdown",
  entryLabel: "discount line",
  columns: [
    { key: "discount_type", label: "Discount (trade, early payment…)", kind: "text", required: true },
    { key: "percent", label: "Percent", kind: "number", format: "percent" },
    { key: "amount", label: "Amount", kind: "number", required: true, format: "money" },
  ],
};

const DEDUCTIONS: DetailListSpec = {
  field: "deductions",
  label: "Deductions",
  entryLabel: "deduction",
  columns: [
    { key: "deduction_type", label: "Deduction (retention, advance…)", kind: "text", required: true },
    { key: "amount", label: "Amount", kind: "number", required: true, format: "money" },
  ],
};

const ADDRESSES: DetailListSpec = {
  field: "addresses",
  label: "Addresses",
  entryLabel: "address",
  columns: [
    { key: "address_type", label: "Type (billing, shipping, vendor)", kind: "text", required: true },
    { key: "text", label: "Address", kind: "text", required: true },
    { key: "country", label: "Country", kind: "text" },
  ],
};

const COMPLIANCE_METADATA: DetailListSpec = {
  field: "compliance_metadata",
  label: "Compliance / e-Invoice",
  entryLabel: "compliance entry",
  columns: [
    { key: "key", label: "Key (IRN, QR code…)", kind: "text", required: true },
    { key: "value", label: "Value", kind: "text", required: true },
  ],
};

/** Inbound: every list field `routers/audit.py` accepts except line items, which have their own editor. */
export const INBOUND_DETAIL_LISTS: DetailListSpec[] = [
  TAX_IDS,
  TAXES,
  PAYMENT_INSTRUCTIONS,
  REFERENCES,
  DISCOUNTS,
  DEDUCTIONS,
  ADDRESSES,
  COMPLIANCE_METADATA,
];

/** Outbound: the list fields `routers/outbound_audit.py` accepts (an outbound invoice extracts no discount lines or deductions). */
export const OUTBOUND_DETAIL_LISTS: DetailListSpec[] = [
  TAX_IDS,
  TAXES,
  PAYMENT_INSTRUCTIONS,
  REFERENCES,
  ADDRESSES,
  COMPLIANCE_METADATA,
];

/** Drops blank cells, so the server receives only what was typed. */
export function cleanEntry(entry: DetailEntry): DetailEntry {
  return Object.fromEntries(Object.entries(entry).filter(([, value]) => value !== undefined && value !== ""));
}
