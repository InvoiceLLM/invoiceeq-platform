from datetime import date
from typing import Optional
from fastapi import APIRouter, Depends, Query, Response
from sqlmodel import Session, select
from sqlalchemy import func, case

from dependencies import get_tenant_context, get_db_session, TenantContext
from models import Invoice

router = APIRouter(prefix="/outbound-dashboard", tags=["Outbound Dashboard"])


@router.get("/metrics")
async def get_outbound_dashboard_metrics(
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    customer_name: Optional[str] = None,
    status: Optional[str] = None,
    context: TenantContext = Depends(get_tenant_context),
    db_session: Session = Depends(get_db_session),
):
    """Feature 8.1 Task 8.1.2: AR mirror of dashboard.py's get_dashboard_metrics().
    Same SQL-aggregate approach (real SUM/COUNT/GROUP BY, no full-row
    materialization for the totals/breakdown/top-customers queries) -- only
    verification_accuracy/average_days_to_payment need a per-row pass, same
    as inbound's average_processing_time/extraction_accuracy, since neither
    has a portable cross-dialect SQL form in this codebase's Postgres/SQLite
    setup. Zero edits to dashboard.py itself -- filtering logic duplicated
    against flow_direction == "OUTBOUND" rather than adding a direction
    parameter to the existing endpoint (see feature_8.1's own File
    Coordinates note on this)."""
    conditions = [Invoice.tenant_id == context.tenant_id, Invoice.flow_direction == "OUTBOUND"]
    if start_date:
        conditions.append(Invoice.invoice_date >= start_date)
    if end_date:
        conditions.append(Invoice.invoice_date <= end_date)
    if customer_name:
        conditions.append(Invoice.customer_name == customer_name)
    if status:
        conditions.append(Invoice.status == status.upper())

    # 1. Dollar totals -- one aggregate query.
    # outstanding_receivables per feature_8.1's spec: SENT/NEEDS_REVIEW/UPLOADED
    # (money not yet collected, whether or not it's out the door to the
    # customer yet). at_risk_receivables reuses Feature 7.1's read-time
    # overdue definition (SENT + due_date < today) -- no persisted OVERDUE
    # status, so this is expressed directly as a SQL condition, not a status
    # equality check.
    today = date.today()
    totals_row = db_session.exec(
        select(
            func.coalesce(func.sum(Invoice.grand_total), 0.0),
            func.coalesce(func.sum(case((Invoice.status == "PAID", Invoice.grand_total), else_=0.0)), 0.0),
            func.coalesce(
                func.sum(
                    case(
                        (Invoice.status.in_(["SENT", "NEEDS_REVIEW", "UPLOADED"]), Invoice.grand_total),
                        else_=0.0,
                    )
                ),
                0.0,
            ),
            func.coalesce(
                func.sum(
                    case(
                        ((Invoice.status == "SENT") & (Invoice.due_date < today), Invoice.grand_total),
                        else_=0.0,
                    )
                ),
                0.0,
            ),
        ).where(*conditions)
    ).first()
    total_invoiced_out, amount_collected, outstanding_receivables, at_risk_receivables = totals_row

    # 2. Status breakdown -- GROUP BY status.
    status_counts = {
        (inv_status or "UPLOADED"): count
        for inv_status, count in db_session.exec(
            select(Invoice.status, func.count(Invoice.id)).where(*conditions).group_by(Invoice.status)
        ).all()
    }

    # 3. Top customers by spend -- GROUP BY customer, mirrors top_vendors.
    customer_expr = func.coalesce(Invoice.customer_name, "Unknown Customer")
    top_customers = [
        {"customer_name": c, "amount": round(amt or 0.0, 2)}
        for c, amt in db_session.exec(
            select(customer_expr, func.sum(Invoice.grand_total))
            .where(*conditions)
            .group_by(customer_expr)
            .order_by(func.sum(Invoice.grand_total).desc())
        ).all()
    ]

    # 4. verification_accuracy / average_days_to_payment -- narrow column scan
    # (status, sa_alerts, sent_at, paid_at) instead of full ORM rows.
    processed_statuses = {"VERIFIED", "NEEDS_REVIEW", "SENT", "PAID"}
    total_processed = 0
    invoices_with_alerts = 0
    total_days_to_payment = 0.0
    paid_invoice_count = 0

    detail_rows = db_session.exec(
        select(Invoice.status, Invoice.sa_alerts, Invoice.sent_at, Invoice.paid_at).where(*conditions)
    ).all()
    for inv_status, sa_alerts, sent_at, paid_at in detail_rows:
        inv_status = (inv_status or "UPLOADED").upper()

        if inv_status in processed_statuses:
            total_processed += 1
            if sa_alerts:
                invoices_with_alerts += 1

        # Real elapsed time, same honest-average rule as
        # dashboard.py's average_processing_time: excluded from the average
        # if either timestamp is missing, never estimated.
        if sent_at and paid_at:
            elapsed_seconds = (paid_at - sent_at).total_seconds()
            if elapsed_seconds >= 0:
                total_days_to_payment += elapsed_seconds / 86400.0
                paid_invoice_count += 1

    verification_accuracy = 100.0
    if total_processed > 0:
        verification_accuracy = round(100.0 * (1.0 - (invoices_with_alerts / total_processed)), 1)
        verification_accuracy = max(0.0, min(100.0, verification_accuracy))

    average_days_to_payment = (
        round(total_days_to_payment / paid_invoice_count, 1) if paid_invoice_count > 0 else 0.0
    )

    return {
        "total_invoiced_out": round(total_invoiced_out, 2),
        "amount_collected": round(amount_collected, 2),
        "outstanding_receivables": round(outstanding_receivables, 2),
        "at_risk_receivables": round(at_risk_receivables, 2),
        "verification_accuracy": verification_accuracy,
        "average_days_to_payment": average_days_to_payment,
        "top_customers": top_customers,
        "invoices_by_status": status_counts,
    }


@router.get("/invoices")
async def list_outbound_invoices(
    response: Response,
    limit: int = Query(10, ge=1, le=100),
    offset: int = Query(0, ge=0),
    customer_name: str | None = None,
    start_date: date | None = None,
    end_date: date | None = None,
    status: str | None = None,
    status_in: str | None = None,
    context: TenantContext = Depends(get_tenant_context),
    db_session: Session = Depends(get_db_session),
):
    """Feature 8.1 Task 8.1.4 / Feature 7.1 Task 7.1.4: paginated outbound
    invoice list, feeding both the /invoices page's outbound tab
    (feature_4.1_vendor_flow_auditor.md) and the outbound Auditor's
    NEEDS_REVIEW/overdue queue. `status=overdue` is a virtual filter (SENT +
    due_date < today), not a real stored status -- everything else passes
    straight through as a real Invoice.status value. `status_in`
    (comma-separated) mirrors GET /invoices's own param, for the FE's
    "Pending" tab bundling several in-flight statuses into one server-side
    filter (see feature_4.1_vendor_flow_auditor.md's tab-grouping note)."""
    conditions = [Invoice.tenant_id == context.tenant_id, Invoice.flow_direction == "OUTBOUND"]
    if customer_name:
        conditions.append(Invoice.customer_name == customer_name)
    if start_date:
        conditions.append(Invoice.invoice_date >= start_date)
    if end_date:
        conditions.append(Invoice.invoice_date <= end_date)

    if status and status.lower() == "overdue":
        conditions.append(Invoice.status == "SENT")
        conditions.append(Invoice.due_date < date.today())
    elif status:
        conditions.append(Invoice.status == status.upper())
    elif status_in:
        conditions.append(Invoice.status.in_([s.strip().upper() for s in status_in.split(",") if s.strip()]))

    query = select(Invoice).where(*conditions)

    total = db_session.exec(
        select(func.count()).select_from(query.with_only_columns(Invoice.id).subquery())
    ).one()
    response.headers["X-Total-Count"] = str(total)

    query = query.order_by(Invoice.created_at.desc()).offset(offset).limit(limit)
    invoices = db_session.exec(query).all()

    today = date.today()
    return [
        {
            "id": inv.id,
            "invoice_number": inv.invoice_number,
            "customer_name": inv.customer_name,
            "invoice_date": inv.invoice_date,
            "due_date": inv.due_date,
            "grand_total": inv.grand_total,
            "status": inv.status,
            "is_overdue": inv.status == "SENT" and inv.due_date is not None and inv.due_date < today,
        }
        for inv in invoices
    ]
