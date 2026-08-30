"""Feature 25 (Gap 339): CSV and JSON representations of one invoice.

Built for the `email_summary` output destination — these are the two files
attached to the summary email an approved invoice produces. There was no CSV or
JSON export anywhere in this backend before this (checked repo-wide), so nothing
is reused or subclassed here; equally, nothing else depends on the shape yet.

**Scope, stated so this does not quietly grow into a product surface.** This is
an email attachment builder. It is deliberately not a general export feature: no
endpoint, no UI, no pagination, no multi-invoice bundle, no column selection. If
a real export ever gets specified, it should take these builders as a starting
point rather than this file trying to anticipate it.

**Gap 338 (2026-08-30)** made the `drive_archive` destination a second consumer
of exactly these builders rather than writing its own — the file a tenant gets
in Drive and the file it gets by mail are byte-identical because they come from
the same function. Its only addition here is `export_pdf_filename()`, which
shares `_filename_stem()` with `export_filenames()` so both destinations escape
a vendor-controlled invoice number the same way.

One dict, two renderers
-----------------------
`build_invoice_summary()` produces the single source dict; `build_invoice_csv()`
and `build_invoice_json()` both render *that*. They cannot disagree about what
"the invoice's fields" means, which is the whole reason for the indirection —
two independently-written serialisers of the same row is exactly how a CSV and a
JSON end up quietly reporting different totals.

Field names are taken from `models.Invoice` and from
`agents/extraction_agent.py`'s `InvoiceLineItem` / `TaxItem` schemas, not
invented: line items are dicts with `description` / `quantity` / `unit_price` /
`amount`, and `taxes` entries are dicts with `tax_type` / `rate_percent` /
`amount`. Both columns are free-form JSON on the row, so every accessor below
tolerates a non-dict entry rather than assuming the extractor's shape held.
"""
from __future__ import annotations

import csv
import io
import json
from datetime import date, datetime
from typing import Any

from models import Invoice

# One row per line item, invoice-level fields repeated on each row. This is the
# ordinary "invoice lines" export shape: it opens in Excel/Sheets without any
# interpretation, and it stays a single rectangular table (a two-section CSV
# with a header block on top does not).
CSV_COLUMNS = (
    "invoice_id",
    "invoice_number",
    "po_number",
    "vendor_name",
    "customer_name",
    "invoice_date",
    "due_date",
    "status",
    "currency",
    "subtotal",
    "tax_amount",
    "grand_total",
    "line_description",
    "line_quantity",
    "line_unit_price",
    "line_amount",
)


def _iso(value: Any) -> Any:
    """Dates/datetimes to ISO strings; everything else through untouched.

    `json.dumps` cannot serialise `date`/`datetime`, and `invoice_date` /
    `due_date` are real `date` columns.
    """
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return value


def _line_items(invoice: Invoice) -> list[dict]:
    """`Invoice.items` is a free-form JSON column, so it is not guaranteed to
    hold the extractor's shape (or even dicts). Anything that is not a mapping
    is kept as a description-only row rather than dropped — an attachment that
    silently omits a line is worse than one that shows an odd-looking line."""
    raw = invoice.items or []
    if not isinstance(raw, list):
        return []
    out: list[dict] = []
    for entry in raw:
        if isinstance(entry, dict):
            out.append(entry)
        else:
            out.append({"description": str(entry)})
    return out


def _taxes(invoice: Invoice) -> list[dict]:
    raw = invoice.taxes or []
    if not isinstance(raw, list):
        return []
    return [e for e in raw if isinstance(e, dict)]


def build_invoice_summary(invoice: Invoice) -> dict:
    """The one dict both renderers below serialise.

    Deliberately a narrow selection of `Invoice`'s columns — the identifying
    fields, the money, the line items and the tax breakdown. Not included, on
    purpose: `file_path` (an internal blob path), `coordinates` /
    `field_confidence` / `source_document_json` (extraction internals, large and
    meaningless to a recipient), and `sa_alerts` (audit-console state, and the
    invoice being summarised here has already been resolved).
    """
    return {
        "invoice_id": str(invoice.id),
        "invoice_number": invoice.invoice_number,
        "po_number": invoice.po_number,
        "vendor_name": invoice.vendor_name,
        "customer_name": invoice.customer_name,
        "invoice_date": _iso(invoice.invoice_date),
        "due_date": _iso(invoice.due_date),
        "status": invoice.status,
        "flow_direction": invoice.flow_direction,
        "currency": invoice.currency,
        "subtotal": invoice.subtotal,
        "tax_amount": invoice.tax_amount,
        "grand_total": invoice.grand_total,
        "line_items": [
            {
                "description": item.get("description"),
                "quantity": item.get("quantity"),
                "unit_price": item.get("unit_price"),
                "amount": item.get("amount"),
            }
            for item in _line_items(invoice)
        ],
        "taxes": [
            {
                "tax_type": tax.get("tax_type"),
                "rate_percent": tax.get("rate_percent"),
                "amount": tax.get("amount"),
            }
            for tax in _taxes(invoice)
        ],
    }


def build_invoice_csv(invoice: Invoice) -> str:
    """Flat CSV: one row per line item, invoice fields repeated.

    An invoice with no line items still produces exactly one data row (with the
    four line columns empty) rather than a header-only file — "this invoice had
    no itemisation" and "the export broke" must not look the same.

    `lineterminator="\\n"` is set explicitly: csv's default is `\\r\\n`, and
    combined with the file being opened in text mode on Windows that yields
    `\\r\\r\\n`. The bytes here go straight into a base64 attachment, so pinning
    the terminator is the difference between a clean file and a mangled one.
    """
    summary = build_invoice_summary(invoice)
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=CSV_COLUMNS, lineterminator="\n")
    writer.writeheader()

    invoice_level = {
        key: summary.get(key)
        for key in (
            "invoice_id", "invoice_number", "po_number", "vendor_name",
            "customer_name", "invoice_date", "due_date", "status", "currency",
            "subtotal", "tax_amount", "grand_total",
        )
    }

    line_items = summary["line_items"]
    if not line_items:
        writer.writerow(invoice_level)
    else:
        for item in line_items:
            writer.writerow({
                **invoice_level,
                "line_description": item.get("description"),
                "line_quantity": item.get("quantity"),
                "line_unit_price": item.get("unit_price"),
                "line_amount": item.get("amount"),
            })

    return buffer.getvalue()


def build_invoice_json(invoice: Invoice) -> str:
    """Nested JSON of the same dict — line items and taxes stay lists of objects
    rather than being flattened, because the machine-readable form has no reason
    to repeat the invoice header on every line the way the CSV must."""
    return json.dumps(build_invoice_summary(invoice), indent=2, default=str)


def _filename_stem(invoice: Invoice) -> str:
    """`invoice_<sanitised invoice number>`, falling back to the invoice id.

    Replaces anything outside `[A-Za-z0-9_-]` with `_` — an invoice number is
    vendor-controlled text that reached us through OCR, so it can contain
    slashes, spaces, quotes or dots, and it is about to become a filename in
    someone's mail client (Gap 339) or in their Google Drive (Gap 338). `.` is
    excluded from the kept set along with `/` specifically so a number like
    `../../etc/passwd` cannot leave a `..` segment in the name; the only dot in
    the result is the one the caller appends with the extension.
    """
    stem = (invoice.invoice_number or str(invoice.id)).strip() or str(invoice.id)
    safe = "".join(c if (c.isalnum() or c in "_-") else "_" for c in stem)[:64]
    return f"invoice_{safe}"


def export_filenames(invoice: Invoice) -> tuple[str, str]:
    """(csv_name, json_name), stemmed on the invoice number when there is one."""
    stem = _filename_stem(invoice)
    return f"{stem}.csv", f"{stem}.json"


def export_pdf_filename(invoice: Invoice) -> str:
    """The name the invoice's own source PDF is archived under (Gap 338).

    Same stem and the same sanitisation as the CSV/JSON, so the three files an
    approval produces sort next to each other and share one escaping rule
    rather than two.
    """
    return f"{_filename_stem(invoice)}.pdf"
