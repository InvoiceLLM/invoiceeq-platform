from datetime import date
from fastapi import APIRouter, Depends, Query, Response
from sqlmodel import Session, select
from sqlalchemy import func

from dependencies import get_tenant_context, get_db_session, TenantContext
from models import Invoice

router = APIRouter(prefix="/outbound-dashboard", tags=["Outbound Dashboard"])


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
