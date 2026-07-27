import json
import logging
from datetime import date, timedelta
from typing import List, Optional
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlmodel import Session, select

from dependencies import get_tenant_context, get_db_session, TenantContext
from models import Invoice, ExtractionTemplate
from utils.llm import get_llm

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/dashboard", tags=["Dashboard"])

# Gap 30: cached the same way Task 6.11's chat answer cache is (inline Redis
# client, JSON blob, fixed TTL) -- the underlying data moves slowly relative
# to how often the dashboard is opened, and this is an LLM call.
INSIGHTS_CACHE_TTL_SECONDS = 3600


def _get_redis_client():
    import redis
    from config import get_settings
    return redis.Redis.from_url(get_settings().REDIS_URL, decode_responses=True)


def _insights_cache_key(tenant_id) -> str:
    return f"dashboard_insights:{tenant_id}"


class DashboardInsight(BaseModel):
    model_config = {"extra": "forbid"}
    title: str = Field(description="Short headline (8 words or fewer) for this recommendation")
    detail: str = Field(description="1-2 sentence explanation, grounded in the numbers provided")
    severity: str = Field(description="One of 'info', 'warning', or 'critical' based on financial/operational impact")


class DashboardInsightsSchema(BaseModel):
    model_config = {"extra": "forbid"}
    insights: List[DashboardInsight] = Field(default=[])

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


@router.get("/insights")
async def get_dashboard_insights(
    context: TenantContext = Depends(get_tenant_context),
    db_session: Session = Depends(get_db_session)
):
    """
    Gap 30: AI-generated strategic recommendations backing the FE's Actionable
    Insights Panel (fe_features_tracker.md Gap 4). The LLM is only ever given
    real aggregates computed below -- spend concentration, at-risk amount,
    audit rate, vendors missing a Trainer rule -- and explicitly told not to
    invent figures, so recommendations stay grounded in this tenant's actual
    data rather than generic advice.
    """
    cache_key = _insights_cache_key(context.tenant_id)
    try:
        cached = _get_redis_client().get(cache_key)
        if cached:
            return json.loads(cached)
    except Exception as e:
        logger.warning("Dashboard insights cache lookup failed, proceeding without cache: %s", e)

    invoices = db_session.exec(
        select(Invoice).where(Invoice.tenant_id == context.tenant_id)
    ).all()

    if not invoices:
        result = {"insights": []}
        return result

    templates = db_session.exec(
        select(ExtractionTemplate).where(ExtractionTemplate.tenant_id == context.tenant_id)
    ).all()

    total_invoiced = sum(inv.grand_total or 0.0 for inv in invoices)
    at_risk_amount = sum(
        inv.grand_total or 0.0 for inv in invoices if (inv.status or "").upper() == "AUDIT_REQUIRED"
    )

    spend_by_vendor: dict[str, float] = {}
    flagged_counts: dict[str, int] = {}
    for inv in invoices:
        v = inv.vendor_name or "Unknown Vendor"
        spend_by_vendor[v] = spend_by_vendor.get(v, 0.0) + (inv.grand_total or 0.0)
        if inv.sa_alerts and inv.vendor_name:
            flagged_counts[inv.vendor_name] = flagged_counts.get(inv.vendor_name, 0) + 1

    top_vendors = sorted(spend_by_vendor.items(), key=lambda x: x[1], reverse=True)[:5]

    # Same "recurring, not a one-off" vendors-needing-a-rule logic as
    # get_trainer_impact() above, recomputed here rather than imported since
    # this endpoint only needs the top 5 for prompt context, not the full list.
    vendor_names_with_rules = {t.vendor_name for t in templates if t.vendor_name is not None}
    vendors_needing_rules = sorted(
        [
            {"vendor_name": v, "flagged_invoice_count": c}
            for v, c in flagged_counts.items()
            if v not in vendor_names_with_rules and c >= 2
        ],
        key=lambda x: x["flagged_invoice_count"],
        reverse=True,
    )[:5]

    processed = [inv for inv in invoices if (inv.status or "").upper() in ("COMPLETED", "PAID", "AUDIT_REQUIRED", "REJECTED")]
    audit_required_count = sum(1 for inv in processed if (inv.status or "").upper() == "AUDIT_REQUIRED")
    audit_rate = round(100.0 * audit_required_count / len(processed), 1) if processed else 0.0

    context_blob = {
        "total_invoiced": round(total_invoiced, 2),
        "at_risk_amount": round(at_risk_amount, 2),
        "audit_rate_percent": audit_rate,
        "total_invoice_count": len(invoices),
        "top_vendors_by_spend": [{"vendor_name": v, "amount": round(a, 2)} for v, a in top_vendors],
        "vendors_needing_rules": vendors_needing_rules,
    }

    prompt = (
        "You are a financial operations analyst reviewing one tenant's invoice-processing data. "
        "Using ONLY the numbers given below -- never invent a figure that isn't present -- write 3 to 5 "
        "concise, specific, actionable recommendations for the accounts-payable team. "
        "Ground every recommendation in a specific number from the data, but write in plain, professional "
        "prose -- never quote the raw JSON field names (e.g. say 'the audit rate' not 'audit_rate_percent'). "
        "If the data shows nothing concerning, say so briefly rather than manufacturing a concern.\n\n"
        f"Data:\n{json.dumps(context_blob, indent=2)}"
    )

    try:
        structured_llm = get_llm().with_structured_output(DashboardInsightsSchema)
        response: DashboardInsightsSchema = structured_llm.invoke(prompt)
        result = response.model_dump()
    except Exception as e:
        logger.error("Dashboard insights generation failed: %s", e)
        result = {"insights": []}

    try:
        _get_redis_client().set(cache_key, json.dumps(result), ex=INSIGHTS_CACHE_TTL_SECONDS)
    except Exception as e:
        logger.warning("Dashboard insights cache write failed: %s", e)

    return result
