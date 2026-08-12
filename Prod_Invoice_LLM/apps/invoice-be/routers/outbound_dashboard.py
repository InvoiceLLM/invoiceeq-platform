from datetime import date
from fastapi import APIRouter, Depends, Query, Response
from sqlmodel import Session, select
from sqlalchemy import func, case, and_

from dependencies import get_tenant_context, get_db_session, TenantContext
from models import Invoice, AuditLog

router = APIRouter(prefix="/outbound-dashboard", tags=["Outbound Dashboard"])

# The outbound lifecycle's actually-persisted Invoice.status values, from
# routers/outbound_invoices.py (UPLOADED on upload, SENT on confirm-send, PAID
# on mark-paid) and queue_worker/outbound_handlers.py (VERIFIED or
# NEEDS_REVIEW after extraction). PROCESSING_OCR/EXTRACTING_DATA/FAILED are
# SSE progress events only -- they are never written to Invoice.status, so
# they deliberately don't appear in any set below.
#
# feature_8.1_vendor_flow_dashboard.md specifies outstanding_receivables as
# "SENT/NEEDS_REVIEW/UPLOADED", written before Feature 2.1 existed and so
# before VERIFIED was a real status. VERIFIED is included here anyway: it's a
# genuine in-flight state (extracted cleanly, awaiting confirm-send), and
# leaving it out would mean total_invoiced_out != amount_collected +
# outstanding_receivables, i.e. money that silently belongs to no bucket.
_OUTSTANDING_STATUSES = ["UPLOADED", "VERIFIED", "NEEDS_REVIEW", "SENT"]

# Reached a verification decision -- the denominator for verification_accuracy.
# Anything still at UPLOADED hasn't been judged yet and would otherwise drag
# the percentage down for no reason.
_VERIFICATION_DECIDED_STATUSES = ("VERIFIED", "NEEDS_REVIEW", "SENT", "PAID")


# FE Gap 183, AR side. Written here independently rather than imported from
# routers/dashboard.py's identical helper: the zero-touch rule in
# docs/architecture/System_Journey_Developer_Guide.md Part 3 keeps these two
# modules from depending on each other, and that rule outranks the duplication.
# Invoice.currency is nullable, so this normalizes at *query* time only --
# NULL/blank collapse to "USD" and casing is folded, but nothing is ever
# written back onto historical rows.
def _currency_expr():
    return func.upper(func.coalesce(func.nullif(func.trim(Invoice.currency), ""), "USD"))


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
            # FE Gap 183: this endpoint hand-builds its response dict rather
            # than returning the ORM row, so currency has to be listed
            # explicitly or every consumer of these rows renders "$".
            "currency": inv.currency,
            "status": inv.status,
            "is_overdue": inv.status == "SENT" and inv.due_date is not None and inv.due_date < today,
        }
        for inv in invoices
    ]


@router.get("/metrics")
async def get_outbound_dashboard_metrics(
    start_date: date | None = None,
    end_date: date | None = None,
    customer_name: str | None = None,
    status: str | None = None,
    context: TenantContext = Depends(get_tenant_context),
    db_session: Session = Depends(get_db_session),
):
    """Feature 8.1, Task 8.1.2: the AR mirror of GET /dashboard/metrics.

    routers/dashboard.py is neither imported from nor edited (the zero-touch
    rule in docs/architecture/System_Journey_Developer_Guide.md Part 3) -- the
    filter/aggregate shape is duplicated here against
    ``flow_direction == "OUTBOUND"`` instead. Same division of labour as the
    inbound endpoint after FE Gap 29: the dollar totals, status breakdown, top
    customers and revenue series are real SQL SUM/COUNT/GROUP BY aggregates,
    and only the two derived metrics that have no portable cross-dialect SQL
    form here (verification_accuracy's sa_alerts list lengths,
    average_days_to_payment's timestamp deltas) take a per-row pass -- and
    that pass fetches 4 narrow columns, never full Invoice rows.

    FE Gap 183, AR side: every money figure is broken out per currency, and no
    blended cross-currency scalar survives. The old flat total_invoiced_out /
    amount_collected / outstanding_receivables / at_risk_receivables keys are
    **removed**, replaced by totals_by_currency; top_customers and
    revenue_over_time carry a currency of their own. No FX conversion anywhere
    -- amounts in different currencies are never added together.
    """
    # 1. Shared filter conditions. tenant_id + flow_direction are not
    # optional: without the direction predicate this would aggregate the
    # tenant's inbound AP invoices and report them as receivables.
    conditions = [
        Invoice.tenant_id == context.tenant_id,
        Invoice.flow_direction == "OUTBOUND",
    ]
    if start_date:
        conditions.append(Invoice.invoice_date >= start_date)
    if end_date:
        conditions.append(Invoice.invoice_date <= end_date)
    if customer_name:
        conditions.append(Invoice.customer_name == customer_name)
    if status:
        conditions.append(Invoice.status == status.upper())

    today = date.today()

    # 2. Money totals -- one aggregate query, computed entirely in SQL,
    # GROUP BY currency (FE Gap 183). One row per currency actually billed in.
    # at_risk_receivables reuses feature_7.1's read-time overdue rule (SENT
    # past its due_date), the same predicate list_outbound_invoices() applies
    # for its virtual `status=overdue` filter, so the two can never disagree.
    # Still no persisted OVERDUE status: Gap 126's daily sweep
    # (services/outbound_overdue.py) reuses this same predicate to fire the
    # `outbound_invoice.overdue` webhook and writes only its own
    # `overdue_notified_at` marker -- it never touches `Invoice.status`, so
    # nothing here (or in any other status filter) changes shape because of it.
    currency_expr = _currency_expr()
    totals_by_currency = [
        {
            "currency": curr,
            "total_invoiced_out": round(billed or 0.0, 2),
            "amount_collected": round(collected or 0.0, 2),
            "outstanding_receivables": round(outstanding or 0.0, 2),
            "at_risk_receivables": round(at_risk or 0.0, 2),
        }
        for curr, billed, collected, outstanding, at_risk in db_session.exec(
            select(
                currency_expr,
                func.coalesce(func.sum(Invoice.grand_total), 0.0),
                func.coalesce(func.sum(case((Invoice.status == "PAID", Invoice.grand_total), else_=0.0)), 0.0),
                func.coalesce(
                    func.sum(case((Invoice.status.in_(_OUTSTANDING_STATUSES), Invoice.grand_total), else_=0.0)),
                    0.0,
                ),
                func.coalesce(
                    func.sum(
                        case(
                            (
                                and_(
                                    Invoice.status == "SENT",
                                    Invoice.due_date.is_not(None),
                                    Invoice.due_date < today,
                                ),
                                Invoice.grand_total,
                            ),
                            else_=0.0,
                        )
                    ),
                    0.0,
                ),
            )
            .where(*conditions)
            .group_by(currency_expr)
            .order_by(func.coalesce(func.sum(Invoice.grand_total), 0.0).desc(), currency_expr)
        ).all()
    ]

    # 3. Status breakdown -- GROUP BY status
    status_counts = {
        (inv_status or "UPLOADED"): count
        for inv_status, count in db_session.exec(
            select(Invoice.status, func.count(Invoice.id)).where(*conditions).group_by(Invoice.status)
        ).all()
    }

    # 4. Top customers by billed value -- the AR mirror of inbound's
    # top_vendors, full ranked list rather than capped, matching that
    # endpoint's behaviour. Grouped by currency as well as customer (FE Gap
    # 183): a customer billed in two currencies gets one row per currency
    # rather than a summed figure that belongs to neither.
    customer_expr = func.coalesce(Invoice.customer_name, "Unknown Customer")
    top_customers = [
        {"customer_name": c, "currency": curr, "amount": round(amt or 0.0, 2)}
        for c, curr, amt in db_session.exec(
            select(customer_expr, currency_expr, func.sum(Invoice.grand_total))
            .where(*conditions)
            .group_by(customer_expr, currency_expr)
            .order_by(func.sum(Invoice.grand_total).desc())
        ).all()
    ]

    # 5. Revenue-over-time series -- mirror of inbound's spend_over_time,
    # falling back to created_at's date when invoice_date wasn't extracted.
    # One point per (date, currency) so the FE draws a separate line per
    # currency rather than one line that jumps between scales.
    date_expr = func.coalesce(Invoice.invoice_date, func.date(Invoice.created_at))
    revenue_over_time = [
        {"date": str(d), "currency": curr, "amount": round(amt or 0.0, 2)}
        for d, curr, amt in db_session.exec(
            select(date_expr, currency_expr, func.sum(Invoice.grand_total))
            .where(*conditions)
            .group_by(date_expr, currency_expr)
            .order_by(date_expr, currency_expr)
        ).all()
    ]

    # 6. verification_accuracy / average_days_to_payment: narrow 4-column scan.
    active_alerts_count = 0
    invoices_with_alerts = 0
    total_decided = 0
    total_days_to_payment = 0.0
    timed_invoice_count = 0

    detail_rows = db_session.exec(
        select(Invoice.status, Invoice.sa_alerts, Invoice.sent_at, Invoice.paid_at).where(*conditions)
    ).all()
    for inv_status, sa_alerts, sent_at, paid_at in detail_rows:
        inv_status = (inv_status or "UPLOADED").upper()

        if inv_status in _VERIFICATION_DECIDED_STATUSES:
            total_decided += 1
            if sa_alerts:
                invoices_with_alerts += 1

        if sa_alerts:
            active_alerts_count += len(sa_alerts)

        # Real elapsed time only. An invoice missing either timestamp is
        # excluded from the average rather than estimated from anything else --
        # same honesty rule as the inbound average_processing_time fix. Rows
        # predating these columns have them as NULL and simply don't count.
        if sent_at and paid_at:
            elapsed_days = (paid_at - sent_at).total_seconds() / 86400.0
            if elapsed_days >= 0:
                total_days_to_payment += elapsed_days
                timed_invoice_count += 1

    average_days_to_payment = (
        round(total_days_to_payment / timed_invoice_count, 1) if timed_invoice_count > 0 else 0.0
    )

    # Query matching AuditLog entries for the AI score metrics calculations
    # Joining with Invoice to apply the same workspace-level and date-range filters
    audit_query = select(AuditLog.details, Invoice.sa_alerts, Invoice.status).join(
        Invoice, AuditLog.invoice_id == Invoice.id
    ).where(
        AuditLog.tenant_id == context.tenant_id,
        AuditLog.action == "RESOLVE_INVOICE"
    )
    for cond in conditions:
        audit_query = audit_query.where(cond)
    
    audit_rows = db_session.exec(audit_query).all()

    # 1. AI Field Extraction (Accuracy of the core 7 fields)
    total_corrections = 0
    TARGET_FIELDS = {"customer_name", "invoice_number", "invoice_date", "due_date", "subtotal", "tax_amount", "grand_total"}
    for details, _, _ in audit_rows:
        if details and "corrections" in details:
            corrections = details["corrections"] or {}
            for field in corrections.keys():
                if field in TARGET_FIELDS:
                    total_corrections += 1
    
    ai_field_extraction = 100.0
    total_possible_fields = total_decided * 7
    if total_possible_fields > 0:
        ai_field_extraction = round(100.0 * (1.0 - (total_corrections / total_possible_fields)), 1)
        ai_field_extraction = max(0.0, min(100.0, ai_field_extraction))

    # 2. AI Alert Response (Percentage of valid alerts vs false alarms)
    def get_alert_severity(alert) -> str:
        if isinstance(alert, dict):
            if "severity" in alert and alert["severity"]:
                return alert["severity"].lower()
            alert_type = alert.get("type", "").lower()
            alert_msg = alert.get("message", "").lower()
        else:
            alert_type = str(alert).lower()
            alert_msg = str(alert).lower()

        if any(k in alert_type or k in alert_msg for k in ["mismatch", "duplicate", "failed", "timeout", "missing", "error"]):
            return "error"
        if any(k in alert_type or k in alert_msg for k in ["not_verified", "confidence"]):
            return "warning"
        return "information"

    total_alerts_flagged = 0
    total_alerts_dismissed = 0
    for details, _, _ in audit_rows:
        if details:
            prev_alerts = details.get("previous_alerts") or []
            dismissed = details.get("dismissed_alerts_input") or []
            
            error_alerts = [a for a in prev_alerts if get_alert_severity(a) == "error"]
            total_alerts_flagged += len(error_alerts)
            
            for d in dismissed:
                is_error = False
                for a in error_alerts:
                    if isinstance(a, dict):
                        if d == a.get("id") or d == a.get("type") or d == a.get("message"):
                            is_error = True
                            break
                    elif isinstance(a, str):
                        if d == a:
                            is_error = True
                            break
                if is_error:
                    total_alerts_dismissed += 1
    
    ai_alert_response = 100.0
    if total_alerts_flagged > 0:
        ai_alert_response = round(100.0 * (1.0 - (total_alerts_dismissed / total_alerts_flagged)), 1)
        ai_alert_response = max(0.0, min(100.0, ai_alert_response))

    # % of outbound invoices that got through verification with zero alerts.
    # sa_alerts is the first-pass signal rather than the status itself: status
    # is mutable, so an invoice corrected out of NEEDS_REVIEW and sent would
    # otherwise look like it was clean all along. Mirrors how inbound's
    # extraction_accuracy reads the same field.
    verification_accuracy = 100.0
    if total_decided > 0:
        verification_accuracy = round(100.0 * (1.0 - (invoices_with_alerts / total_decided)), 1)
        verification_accuracy = max(0.0, min(100.0, verification_accuracy))

    # No combined/net figure is returned anywhere here (no inbound+outbound
    # total, no net cash position) -- that comparison stays Chat-only, per the
    # design decision recorded in both feature docs.
    return {
        # FE Gap 183: per-currency breakdown only. The flat blended
        # total_invoiced_out / amount_collected / outstanding_receivables /
        # at_risk_receivables keys were removed, not deprecated.
        "totals_by_currency": totals_by_currency,
        "average_days_to_payment": average_days_to_payment,
        "verification_accuracy": verification_accuracy,
        "active_alerts_count": active_alerts_count,
        "revenue_over_time": revenue_over_time,
        "top_customers": top_customers,
        "invoices_by_status": status_counts,
        "ai_field_extraction": ai_field_extraction,
        "ai_alert_response": ai_alert_response,
        "ai_alerts_missed": 0.0
    }
