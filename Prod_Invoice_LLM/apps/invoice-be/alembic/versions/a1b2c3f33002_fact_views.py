"""Feature 33 (ATLAS Analyst Agent) — Fact Views and Clearance-aware Metric Views.

Revision ID: a1b2c3f33002
Revises: a1b2c3f33001
Create Date: 2026-09-15
"""
from typing import Sequence, Union

from alembic import op

revision: str = "a1b2c3f33002"
down_revision: Union[str, None] = "a1b2c3f33001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_LIVE = "i.deleted_at IS NULL AND i.status <> 'DUPLICATE'"

VIEWS: dict = {
    "v_commitments": """
        SELECT
            f.id,
            f.tenant_id,
            f.clearance,
            f.subject_kind,
            f.subject_id,
            f.counterparty_id,
            f.as_of,
            f.figures,
            f.source_kind,
            f.source_id,
            f.evidence,
            f.created_at
        FROM fact f
        WHERE f.kind = 'commitment'
    """,
    "v_delivery_events": """
        SELECT
            f.id,
            f.tenant_id,
            f.clearance,
            f.subject_kind,
            f.subject_id,
            f.counterparty_id,
            f.as_of,
            f.figures,
            f.source_kind,
            f.source_id,
            f.evidence,
            f.created_at
        FROM fact f
        WHERE f.kind = 'delivery_event'
    """,
    "v_payment_events": """
        SELECT
            f.id,
            f.tenant_id,
            f.clearance,
            f.subject_kind,
            f.subject_id,
            f.counterparty_id,
            f.as_of,
            f.figures,
            f.source_kind,
            f.source_id,
            f.evidence,
            f.created_at
        FROM fact f
        WHERE f.kind = 'payment_event'
    """,
    "v_recurrence": """
        SELECT
            f.tenant_id,
            f.clearance,
            f.counterparty_id,
            COUNT(*) AS payment_count,
            MIN(f.as_of) AS first_payment_date,
            MAX(f.as_of) AS last_payment_date
        FROM fact f
        WHERE f.kind = 'payment_event' AND f.counterparty_id IS NOT NULL
        GROUP BY f.tenant_id, f.clearance, f.counterparty_id
    """,
    "v_period_accounts": """
        SELECT
            f.id,
            f.tenant_id,
            f.clearance,
            f.subject_kind,
            f.subject_id AS account_name,
            f.counterparty_id,
            f.as_of,
            f.figures,
            f.source_kind,
            f.source_id,
            f.evidence,
            f.created_at
        FROM fact f
        WHERE f.kind = 'period_accounts'
    """,
    "v_budgets": """
        SELECT
            f.id,
            f.tenant_id,
            f.clearance,
            f.subject_kind,
            f.subject_id AS account_name,
            f.counterparty_id,
            f.as_of,
            f.figures,
            f.source_kind,
            f.source_id,
            f.evidence,
            f.created_at
        FROM fact f
        WHERE f.kind = 'budget'
    """,
    "v_vendor_spend": f"""
        SELECT
            i.tenant_id                                   AS tenant_id,
            'ops'                                         AS clearance,
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
    "v_overdue": f"""
        SELECT
            i.tenant_id                                   AS tenant_id,
            'ops'                                         AS clearance,
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
    "v_3way_match": f"""
        SELECT
            i.tenant_id                                   AS tenant_id,
            'ops'                                         AS clearance,
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
    for name in [
        "v_budgets",
        "v_period_accounts",
        "v_recurrence",
        "v_payment_events",
        "v_delivery_events",
        "v_commitments",
    ]:
        op.execute(f"DROP VIEW IF EXISTS {name}")
    # Revert v_vendor_spend, v_overdue, v_3way_match to pre-clearance definitions
    from alembic.versions.a1b2c3f30002_semantic_views import VIEWS as OLD_VIEWS
    for name in ["v_vendor_spend", "v_overdue", "v_3way_match"]:
        if name in OLD_VIEWS:
            op.execute(f"CREATE OR REPLACE VIEW {name} AS {OLD_VIEWS[name]}")
