"""Feature 30 task 30.3 (was Feature 29 task 29.14a) — the four semantic views.

WHY VIEWS AT ALL
----------------
"What did we spend with this vendor?" is currently answered by whatever SQL the
model wrote that turn. Two turns can therefore answer the same question
differently — one counts DUPLICATE rows, one forgets `deleted_at`, one counts an
OUTBOUND invoice as spend — and there is no artefact anywhere that says which is
right. A view IS that artefact: the definition of a metric, written once, in the
database, where the answer is computed.

THE FOUR RULES EVERY VIEW BELOW OBEYS
-------------------------------------
1. **`tenant_id` is a column, never a filter baked in.** A view that hard-coded a
   tenant would need one view per tenant. The caller filters, and
   `services/semantic_views.py::query_metric()` refuses to run without that
   filter (30.4) — the guard is in code that can be tested, not in a comment.
2. **`deleted_at IS NULL`.** A soft-deleted invoice is not spend. This is the
   single most repeated omission in hand-written SQL in this repo.
3. **`status <> 'DUPLICATE'`.** Gap 195's duplicate rows point at an original;
   counting both doubles the money.
4. **OVERDUE is computed, never stored** (`models.Invoice.status`'s own note): no
   `status = 'OVERDUE'` exists anywhere, so `v_overdue` derives it from
   `due_date` and the absence of `paid_at`.

`CREATE OR REPLACE VIEW` and an idempotent drop in `downgrade()`: a view is not
data, so re-running this costs nothing and loses nothing.

down_revision `a1b2c3f30001` confirmed as the single head by `alembic heads`
immediately before writing this file.

Revision ID: a1b2c3f30002
Revises: a1b2c3f30001
Create Date: 2026-09-08
"""
from typing import Sequence, Union

from alembic import op

revision: str = "a1b2c3f30002"
down_revision: Union[str, None] = "a1b2c3f30001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


#: Shared predicate, written out in each view rather than factored into a base
#: view: a reader checking whether `v_overdue` excludes deleted rows must be able
#: to see the answer in `v_overdue`, not two levels down.
_LIVE = "i.deleted_at IS NULL AND i.status <> 'DUPLICATE'"


VIEWS: dict = {
    # Spend per vendor per month. INBOUND only -- an outbound invoice is revenue,
    # and one view that mixed the two would answer "what did we spend" with a
    # number that includes what we billed.
    "v_vendor_spend": f"""
        SELECT
            i.tenant_id                                   AS tenant_id,
            COALESCE(i.vendor_name, '(unnamed vendor)')   AS vendor_name,
            date_trunc('month', i.invoice_date)::date     AS month,
            i.currency                                    AS currency,
            COUNT(*)                                      AS invoice_count,
            SUM(COALESCE(i.grand_total, 0))               AS total_amount,
            SUM(COALESCE(i.tax_amount, 0))                AS tax_amount,
            MIN(i.invoice_date)                           AS first_invoice_date,
            MAX(i.invoice_date)                           AS last_invoice_date
        FROM invoice i
        WHERE {_LIVE}
          AND i.flow_direction = 'INBOUND'
          AND i.invoice_date IS NOT NULL
        GROUP BY i.tenant_id, COALESCE(i.vendor_name, '(unnamed vendor)'),
                 date_trunc('month', i.invoice_date), i.currency
    """,
    # What is past due, per invoice. `days_overdue` is derived at read time from
    # CURRENT_DATE, which is the only correct way to hold a value that changes
    # every midnight without anything writing to the row.
    "v_overdue": f"""
        SELECT
            i.tenant_id                                   AS tenant_id,
            i.id                                          AS invoice_id,
            i.invoice_number                              AS invoice_number,
            i.vendor_name                                 AS vendor_name,
            i.customer_name                               AS customer_name,
            i.flow_direction                              AS flow_direction,
            i.currency                                    AS currency,
            i.grand_total                                 AS grand_total,
            i.invoice_date                                AS invoice_date,
            i.due_date                                    AS due_date,
            (CURRENT_DATE - i.due_date)                   AS days_overdue,
            i.status                                      AS status
        FROM invoice i
        WHERE {_LIVE}
          AND i.due_date IS NOT NULL
          AND i.due_date < CURRENT_DATE
          AND i.paid_at IS NULL
          AND i.status <> 'PAID'
    """,
    # Tax per month, for the compliance cards. `taxes` (the per-line JSONB) is
    # deliberately NOT unnested here: the printed `tax_amount` is the figure the
    # document states, and a second, derived total would give two answers to one
    # question. 30.11's rule cards read the JSONB directly when they need the
    # split.
    "v_tax_summary": f"""
        SELECT
            i.tenant_id                                   AS tenant_id,
            date_trunc('month', i.invoice_date)::date     AS month,
            i.flow_direction                              AS flow_direction,
            i.currency                                    AS currency,
            COUNT(*)                                      AS invoice_count,
            SUM(COALESCE(i.tax_amount, 0))                AS tax_amount,
            SUM(COALESCE(i.subtotal, 0))                  AS taxable_amount,
            SUM(COALESCE(i.grand_total, 0))               AS total_amount
        FROM invoice i
        WHERE {_LIVE}
          AND i.invoice_date IS NOT NULL
        GROUP BY i.tenant_id, date_trunc('month', i.invoice_date),
                 i.flow_direction, i.currency
    """,
    # One row per (PO number, vendor): what was ordered against that PO across
    # our invoices. The "3-way" name is the industry one; what this view supplies
    # is the INVOICE leg. The order leg comes from the attached PO and the
    # delivery leg from the challan, both of which live on `chat_attachments` and
    # neither of which is a payable -- joining them in here would put a
    # non-payable into a view that reads from `invoice` (Feature 26 D2).
    "v_3way_match": f"""
        SELECT
            i.tenant_id                                   AS tenant_id,
            i.po_number                                   AS po_number,
            COALESCE(i.vendor_name, '(unnamed vendor)')   AS vendor_name,
            i.currency                                    AS currency,
            COUNT(*)                                      AS invoice_count,
            SUM(COALESCE(i.grand_total, 0))               AS invoiced_amount,
            MIN(i.invoice_date)                           AS first_invoice_date,
            MAX(i.invoice_date)                           AS last_invoice_date,
            ARRAY_AGG(i.invoice_number ORDER BY i.invoice_date NULLS LAST)
                                                          AS invoice_numbers
        FROM invoice i
        WHERE {_LIVE}
          AND i.flow_direction = 'INBOUND'
          AND i.po_number IS NOT NULL
          AND TRIM(i.po_number) <> ''
        GROUP BY i.tenant_id, i.po_number,
                 COALESCE(i.vendor_name, '(unnamed vendor)'), i.currency
    """,
}


def upgrade() -> None:
    for name, body in VIEWS.items():
        op.execute(f"CREATE OR REPLACE VIEW {name} AS {body}")


def downgrade() -> None:
    for name in VIEWS:
        op.execute(f"DROP VIEW IF EXISTS {name}")
