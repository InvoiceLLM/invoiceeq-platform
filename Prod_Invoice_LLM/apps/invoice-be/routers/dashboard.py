import logging
from datetime import date, timedelta
from typing import Optional
from fastapi import APIRouter, Depends
from sqlmodel import Session, select

from dependencies import get_tenant_context, get_db_session, TenantContext
from models import Invoice, ExtractionTemplate

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/dashboard", tags=["Dashboard"])

@router.get("/metrics")
async def get_dashboard_metrics(
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    vendor_name: Optional[str] = None,
    po_number: Optional[str] = None,
    status: Optional[str] = None,
    context: TenantContext = Depends(get_tenant_context),
    db_session: Session = Depends(get_db_session)
):
    """
    Exposes aggregated database statistics and multi-dimensional filtering for dashboard operations.
    Enforces strict tenant isolation.
    """
    # 1. Build filtered query scoped to the current tenant
    query = select(Invoice).where(Invoice.tenant_id == context.tenant_id)
    
    if start_date:
        query = query.where(Invoice.invoice_date >= start_date)
    if end_date:
        query = query.where(Invoice.invoice_date <= end_date)
    if vendor_name:
        query = query.where(Invoice.vendor_name == vendor_name)
    if po_number:
        query = query.where(Invoice.po_number == po_number)
    if status:
        query = query.where(Invoice.status == status)

    invoices = db_session.exec(query).all()

    # 2. Perform math aggregates
    total_invoiced = 0.0
    paid_amount = 0.0
    outstanding_amount = 0.0
    at_risk_amount = 0.0
    active_alerts_count = 0
    invoices_with_alerts = 0
    total_processed = 0
    total_processing_time = 0.0
    timed_invoice_count = 0
    
    spend_by_date = {}
    spend_by_vendor = {}
    status_counts = {}

    for inv in invoices:
        grand_total = inv.grand_total or 0.0
        
        # Aggregate totals
        total_invoiced += grand_total
        
        inv_status = (inv.status or "PROCESSING").upper()
        if inv_status == "PAID":
            paid_amount += grand_total
        elif inv_status in ["COMPLETED", "AUDIT_REQUIRED", "PROCESSING"]:
            outstanding_amount += grand_total

        if inv_status == "AUDIT_REQUIRED":
            at_risk_amount += grand_total

        if inv_status in ["COMPLETED", "PAID", "AUDIT_REQUIRED", "REJECTED"]:
            total_processed += 1
            # Real elapsed time from queue pickup (created_at) to pipeline completion
            # (completed_at, set by handlers.py once when status is finalized). Invoices
            # processed before completed_at existed have it as None and are excluded
            # from the average rather than estimated.
            if inv.completed_at:
                elapsed_seconds = (inv.completed_at - inv.created_at).total_seconds()
                if elapsed_seconds >= 0:
                    total_processing_time += elapsed_seconds
                    timed_invoice_count += 1

        # Alerts count
        if inv.sa_alerts:
            active_alerts_count += len(inv.sa_alerts)
            invoices_with_alerts += 1

        # Spend over time (series)
        # Fallback to created_at date if invoice_date is not set
        d_val = inv.invoice_date or inv.created_at.date()
        d_str = d_val.isoformat()
        spend_by_date[d_str] = spend_by_date.get(d_str, 0.0) + grand_total

        # Top vendors (series)
        v_name = inv.vendor_name or "Unknown Vendor"
        spend_by_vendor[v_name] = spend_by_vendor.get(v_name, 0.0) + grand_total

        # Group count by status
        status_counts[inv_status] = status_counts.get(inv_status, 0) + 1

    # Format series data
    spend_over_time = [{"date": d, "amount": round(amt, 2)} for d, amt in sorted(spend_by_date.items())]
    top_vendors = [{"vendor_name": v, "amount": round(amt, 2)} for v, amt in sorted(spend_by_vendor.items(), key=lambda x: x[1], reverse=True)]

    # Dynamic metrics based on data
    average_processing_time = (
        round(total_processing_time / timed_invoice_count, 1) if timed_invoice_count > 0 else 0.0
    )
    
    # Calculate real accuracy (what % of invoices went through without alerts)
    extraction_accuracy = 100.0
    if total_processed > 0:
        extraction_accuracy = round(100.0 * (1.0 - (invoices_with_alerts / total_processed)), 1)
        extraction_accuracy = max(0.0, min(100.0, extraction_accuracy))

    return {
        "total_invoiced": round(total_invoiced, 2),
        "paid_amount": round(paid_amount, 2),
        "outstanding_amount": round(outstanding_amount, 2),
        "at_risk_amount": round(at_risk_amount, 2),
        "average_processing_time": average_processing_time,
        "extraction_accuracy": extraction_accuracy,
        "active_alerts_count": active_alerts_count,
        "spend_over_time": spend_over_time,
        "top_vendors": top_vendors,
        "invoices_by_status": status_counts
    }


@router.get("/trainer-impact")
async def get_trainer_impact(
    context: TenantContext = Depends(get_tenant_context),
    db_session: Session = Depends(get_db_session)
):
    """
    Gap 28: makes the Trainer's payoff visible — how many rules exist, whether
    the audit rate is trending down, and which vendors still have no rule
    despite recurring alerts. Deliberately reports a trend, not a single
    "% improvement" figure — claiming the rules *caused* a specific
    improvement percentage from this data would be overclaiming causation;
    showing the real weekly series lets the reader judge that themselves.
    """
    # 1. Rules trained — real count from extraction_templates, split by scope.
    templates = db_session.exec(
        select(ExtractionTemplate).where(ExtractionTemplate.tenant_id == context.tenant_id)
    ).all()
    global_rules = sum(1 for t in templates if t.vendor_name is None)
    vendor_rules = sum(1 for t in templates if t.vendor_name is not None)
    vendor_names_with_rules = {t.vendor_name for t in templates if t.vendor_name is not None}

    # 2. Vendors still needing a rule — vendors with a recurring alert pattern
    # (>=2 flagged invoices) that have no ExtractionTemplate row yet. Same
    # "recurring, not a one-off" reasoning as the Gap 27 suggested-rule
    # threshold, just applied at the vendor level instead of per-field.
    invoices = db_session.exec(
        select(Invoice).where(Invoice.tenant_id == context.tenant_id)
    ).all()

    flagged_counts: dict[str, int] = {}
    for inv in invoices:
        if inv.sa_alerts and inv.vendor_name:
            flagged_counts[inv.vendor_name] = flagged_counts.get(inv.vendor_name, 0) + 1

    vendors_needing_rules = sorted(
        [
            {"vendor_name": v, "flagged_invoice_count": c}
            for v, c in flagged_counts.items()
            if v not in vendor_names_with_rules and c >= 2
        ],
        key=lambda x: x["flagged_invoice_count"],
        reverse=True,
    )

    # 3. Audit-rate trend — weekly, over the real created_at/status history,
    # same "processed" status set as extraction_accuracy uses above.
    processed = [inv for inv in invoices if (inv.status or "").upper() in ("COMPLETED", "PAID", "AUDIT_REQUIRED", "REJECTED")]
    weekly: dict[str, dict[str, int]] = {}
    for inv in processed:
        week_start = (inv.created_at - timedelta(days=inv.created_at.weekday())).date()
        key = week_start.isoformat()
        bucket = weekly.setdefault(key, {"total": 0, "audit_required": 0})
        bucket["total"] += 1
        if (inv.status or "").upper() == "AUDIT_REQUIRED":
            bucket["audit_required"] += 1

    audit_rate_trend = [
        {
            "week": week,
            "audit_rate": round(100.0 * counts["audit_required"] / counts["total"], 1),
            "total_processed": counts["total"],
        }
        for week, counts in sorted(weekly.items())
    ]

    return {
        "rules_trained": {"global": global_rules, "vendor_specific": vendor_rules, "total": len(templates)},
        "vendors_needing_rules": vendors_needing_rules,
        "audit_rate_trend": audit_rate_trend,
    }
