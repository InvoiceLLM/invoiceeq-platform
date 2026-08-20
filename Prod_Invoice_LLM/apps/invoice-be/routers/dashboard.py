import json
import logging
from datetime import date, timedelta
from typing import List, Optional
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import func, case
from sqlmodel import Session, select

from dependencies import get_tenant_context, get_db_session, TenantContext
from models import Invoice, ExtractionTemplate, AuditLog
from services.invoice_visibility import invoice_not_deleted
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


# FE Gap 183: Invoice.currency is nullable and historically unset, so every
# aggregate below groups on this normalized expression instead of the raw
# column. COALESCE at *query* time only -- nothing is ever written back onto
# the historical NULL rows. NULLIF/TRIM collapses "" (an LLM that extracted an
# empty string) into the same bucket as NULL, and UPPER stops "usd" and "USD"
# from being reported as two separate currencies.
def _currency_expr():
    return func.upper(func.coalesce(func.nullif(func.trim(Invoice.currency), ""), "USD"))


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

    FE Gap 29: this previously pulled every matching Invoice row into Python
    (full ORM objects) just to sum/count/group them by hand. The dollar totals,
    status breakdown, top vendors, and spend-over-time series below are now
    real SQL SUM/COUNT/GROUP BY aggregates -- the DB does the work, and no
    per-invoice row set is ever materialized in the API process for them.
    average_processing_time/extraction_accuracy still need a per-row pass
    (completed_at - created_at deltas and sa_alerts list lengths have no
    portable cross-dialect SQL form in this codebase's Postgres/SQLite test
    setup), so that pass fetches only the 4 narrow columns it needs instead of
    full Invoice rows.

    FE Gap 183: every money figure here is broken out **per currency** and no
    blended cross-currency scalar is returned at all. The old flat
    total_invoiced/paid_amount/outstanding_amount/at_risk_amount keys summed
    grand_total across every currency the tenant had, so a $500 invoice and a
    ₹40,000 invoice were reported as one "40500" and then labelled with a
    single symbol by the FE. They are deliberately **removed** rather than kept
    alongside the new shape: a blended number has no correct label, so leaving
    it on the wire only invites something to render it again. No FX conversion
    is performed anywhere -- amounts in different currencies are never added.
    """
    # 1. Shared filter conditions, scoped to the current tenant
    conditions = [Invoice.tenant_id == context.tenant_id, invoice_not_deleted()]
    if start_date:
        conditions.append(func.date(Invoice.created_at) >= start_date)
    if end_date:
        conditions.append(func.date(Invoice.created_at) <= end_date)
    if vendor_name:
        conditions.append(Invoice.vendor_name == vendor_name)
    if po_number:
        conditions.append(Invoice.po_number == po_number)
    if status:
        conditions.append(Invoice.status == status)

    # 2. Money totals -- one aggregate query, computed entirely in SQL,
    # GROUP BY currency (FE Gap 183). One row per currency the tenant actually
    # has, ordered by size so the FE's KPI cards lead with the dominant one.
    currency_expr = _currency_expr()
    totals_by_currency = [
        {
            "currency": curr,
            "total_invoiced": round(total or 0.0, 2),
            "paid_amount": round(paid or 0.0, 2),
            "outstanding_amount": round(outstanding or 0.0, 2),
            "at_risk_amount": round(at_risk or 0.0, 2),
        }
        for curr, total, paid, outstanding, at_risk in db_session.exec(
            select(
                currency_expr,
                func.coalesce(func.sum(Invoice.grand_total), 0.0),
                func.coalesce(func.sum(case((Invoice.status == "PAID", Invoice.grand_total), else_=0.0)), 0.0),
                func.coalesce(
                    func.sum(
                        case(
                            (Invoice.status.in_(["COMPLETED", "AUDIT_REQUIRED", "PROCESSING"]), Invoice.grand_total),
                            else_=0.0,
                        )
                    ),
                    0.0,
                ),
                func.coalesce(func.sum(case((Invoice.status == "AUDIT_REQUIRED", Invoice.grand_total), else_=0.0)), 0.0),
            )
            .where(*conditions)
            .group_by(currency_expr)
            .order_by(func.coalesce(func.sum(Invoice.grand_total), 0.0).desc(), currency_expr)
        ).all()
    ]

    # 3. Status breakdown -- GROUP BY status
    status_counts = {
        (inv_status or "PROCESSING"): count
        for inv_status, count in db_session.exec(
            select(Invoice.status, func.count(Invoice.id)).where(*conditions).group_by(Invoice.status)
        ).all()
    }

    # 4. Top vendors by spend -- GROUP BY vendor *and* currency, ordered by
    # spend desc (full ranked list, not capped -- matches this endpoint's prior
    # behavior). A vendor billing in two currencies gets one row per currency:
    # merging them would produce a meaningless total, and the FE scales its
    # ranking bars within each currency group (FE Gap 183).
    vendor_expr = func.coalesce(Invoice.vendor_name, "Unknown Vendor")
    top_vendors = [
        {"vendor_name": v, "currency": curr, "amount": round(amt or 0.0, 2)}
        for v, curr, amt in db_session.exec(
            select(vendor_expr, currency_expr, func.sum(Invoice.grand_total))
            .where(*conditions)
            .group_by(vendor_expr, currency_expr)
            .order_by(func.sum(Invoice.grand_total).desc())
        ).all()
    ]

    # 5. Spend-over-time series -- GROUP BY date and currency, falling back to
    # created_at's date when invoice_date wasn't extracted. One point per
    # (date, currency) so the FE can draw a separate trendline per currency
    # instead of one line that jumps between scales.
    date_expr = func.coalesce(Invoice.invoice_date, func.date(Invoice.created_at))
    spend_over_time = [
        {"date": str(d), "currency": curr, "amount": round(amt or 0.0, 2)}
        for d, curr, amt in db_session.exec(
            select(date_expr, currency_expr, func.sum(Invoice.grand_total))
            .where(*conditions)
            .group_by(date_expr, currency_expr)
            .order_by(date_expr, currency_expr)
        ).all()
    ]

    # 6. average_processing_time / extraction_accuracy: narrow 4-column scan
    # (status, sa_alerts, created_at, completed_at) instead of full ORM rows.
    active_alerts_count = 0
    invoices_with_alerts = 0
    total_processed = 0
    total_processing_time = 0.0
    timed_invoice_count = 0

    detail_rows = db_session.exec(
        select(Invoice.status, Invoice.sa_alerts, Invoice.created_at, Invoice.completed_at).where(*conditions)
    ).all()
    for inv_status, sa_alerts, created_at, completed_at in detail_rows:
        inv_status = (inv_status or "PROCESSING").upper()

        if inv_status in ("COMPLETED", "PAID", "AUDIT_REQUIRED", "REJECTED"):
            total_processed += 1
            # Real elapsed time from queue pickup (created_at) to pipeline completion
            # (completed_at, set by handlers.py once when status is finalized). Invoices
            # processed before completed_at existed have it as None and are excluded
            # from the average rather than estimated.
            if completed_at:
                elapsed_seconds = (completed_at - created_at).total_seconds()
                if elapsed_seconds >= 0:
                    total_processing_time += elapsed_seconds
                    timed_invoice_count += 1

        if sa_alerts:
            active_alerts_count += len(sa_alerts)
            invoices_with_alerts += 1

    # Dynamic metrics based on data
    average_processing_time = (
        round(total_processing_time / timed_invoice_count, 1) if timed_invoice_count > 0 else 0.0
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
    TARGET_FIELDS = {"vendor_name", "invoice_number", "invoice_date", "due_date", "subtotal", "tax_amount", "grand_total"}
    for details, _, _ in audit_rows:
        if details and "corrections" in details:
            corrections = details["corrections"] or {}
            for field in corrections.keys():
                if field in TARGET_FIELDS:
                    total_corrections += 1
    
    ai_field_extraction = 100.0
    total_possible_fields = total_processed * 7
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

    # 3. AI Alerts Missed (Escape Rate of rejections due to AI Extraction Error)
    rejections_with_extraction_error = 0
    for details, _, _ in audit_rows:
        if details and details.get("target_status") == "REJECTED":
            reason = details.get("reject_reason") or ""
            if reason.startswith("AI") or "AI Extraction" in reason or "Error Invoice" in reason:
                rejections_with_extraction_error += 1
                
    ai_alerts_missed = 0.0
    if total_processed > 0:
        ai_alerts_missed = round(100.0 * (rejections_with_extraction_error / total_processed), 1)
        ai_alerts_missed = max(0.0, min(100.0, ai_alerts_missed))

    # Calculate real accuracy (what % of invoices went through without alerts)
    extraction_accuracy = 100.0
    if total_processed > 0:
        extraction_accuracy = round(100.0 * (1.0 - (invoices_with_alerts / total_processed)), 1)
        extraction_accuracy = max(0.0, min(100.0, extraction_accuracy))

    return {
        # FE Gap 183: per-currency breakdown only. The flat blended
        # total_invoiced/paid_amount/outstanding_amount/at_risk_amount keys
        # were removed, not deprecated -- see this function's docstring.
        "totals_by_currency": totals_by_currency,
        "average_processing_time": average_processing_time,
        "extraction_accuracy": extraction_accuracy,
        "active_alerts_count": active_alerts_count,
        "spend_over_time": spend_over_time,
        "top_vendors": top_vendors,
        "invoices_by_status": status_counts,
        "ai_field_extraction": ai_field_extraction,
        "ai_alert_response": ai_alert_response,
        "ai_alerts_missed": ai_alerts_missed
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
        select(Invoice).where(Invoice.tenant_id == context.tenant_id, invoice_not_deleted())
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
def get_dashboard_insights(
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

    FE Gap 183: those aggregates used to be blended cross-currency sums, i.e.
    the "grounding" fact handed to the model was arithmetic nobody could label
    correctly. Every money figure in the prompt context is now keyed by
    currency, and the prompt explicitly forbids adding or comparing amounts
    across currencies -- no FX rate exists anywhere in this system to make such
    a comparison valid.

    BE Gap 279 -- this handler is deliberately `def`, NOT `async def`.

    Its body is entirely blocking, synchronous I/O: redis-py get/set,
    SQLModel `db_session.exec()`, and `structured_llm.invoke()`, which is a
    synchronous Azure OpenAI round trip measured live at 13-19.5s on a cache
    miss. There is no `await` anywhere in it. While it was declared `async
    def`, Starlette ran it directly on the uvicorn event loop, so that 13-19s
    call froze the entire worker and every other in-flight request stalled
    behind it -- confirmed in Log Analytics, e.g. 2026-08-19T07:20:30Z where
    /dashboard/insights (16781ms), three /invoices (16750/16945/16956ms) and
    /outbound-dashboard/invoices (16937ms) all started ~07:20:13 and completed
    within 200ms of each other, then /invoices went straight back to 282ms one
    second later. That is what made the whole first dashboard load after login
    feel slow, not the panel alone: the Insights fetch took metrics and the
    invoice list down with it.

    Declared `def`, FastAPI runs it in the anyio worker threadpool instead, so
    the blocking LLM call costs this one request its latency and nothing else.
    Do not "modernise" this back to `async def` without first making every call
    inside it genuinely awaitable.
    """
    cache_key = _insights_cache_key(context.tenant_id)
    try:
        cached = _get_redis_client().get(cache_key)
        if cached:
            return json.loads(cached)
    except Exception as e:
        logger.warning("Dashboard insights cache lookup failed, proceeding without cache: %s", e)

    invoices = db_session.exec(
        select(Invoice).where(Invoice.tenant_id == context.tenant_id, invoice_not_deleted())
    ).all()

    if not invoices:
        result = {"insights": []}
        return result

    templates = db_session.exec(
        select(ExtractionTemplate).where(ExtractionTemplate.tenant_id == context.tenant_id)
    ).all()

    # Same normalization the SQL aggregates above use, applied in Python here:
    # NULL/blank -> "USD", uppercased, never written back to the row.
    def _currency_of(inv) -> str:
        return ((inv.currency or "").strip() or "USD").upper()

    totals_per_currency: dict[str, dict[str, float]] = {}
    spend_by_vendor: dict[tuple[str, str], float] = {}
    flagged_counts: dict[str, int] = {}
    for inv in invoices:
        curr = _currency_of(inv)
        amount = inv.grand_total or 0.0
        bucket = totals_per_currency.setdefault(curr, {"total_invoiced": 0.0, "at_risk_amount": 0.0})
        bucket["total_invoiced"] += amount
        if (inv.status or "").upper() == "AUDIT_REQUIRED":
            bucket["at_risk_amount"] += amount

        v = inv.vendor_name or "Unknown Vendor"
        spend_by_vendor[(v, curr)] = spend_by_vendor.get((v, curr), 0.0) + amount
        if inv.sa_alerts and inv.vendor_name:
            flagged_counts[inv.vendor_name] = flagged_counts.get(inv.vendor_name, 0) + 1

    totals_by_currency = [
        {
            "currency": curr,
            "total_invoiced": round(vals["total_invoiced"], 2),
            "at_risk_amount": round(vals["at_risk_amount"], 2),
        }
        for curr, vals in sorted(
            totals_per_currency.items(), key=lambda kv: kv[1]["total_invoiced"], reverse=True
        )
    ]

    # Ranked within each currency, never across -- a ₹ figure outranking a $
    # one is an artifact of the exchange rate, not of spend concentration.
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
        "totals_by_currency": totals_by_currency,
        "audit_rate_percent": audit_rate,
        "total_invoice_count": len(invoices),
        "top_vendors_by_spend": [
            {"vendor_name": v, "currency": curr, "amount": round(a, 2)} for (v, curr), a in top_vendors
        ],
        "vendors_needing_rules": vendors_needing_rules,
    }

    prompt = (
        "You are a financial operations analyst reviewing one tenant's invoice-processing data. "
        "Using ONLY the numbers given below -- never invent a figure that isn't present -- write 3 to 5 "
        "concise, specific, actionable recommendations for the accounts-payable team. "
        "Ground every recommendation in a specific number from the data, but write in plain, professional "
        "prose -- never quote the raw JSON field names (e.g. say 'the audit rate' not 'audit_rate_percent'). "
        "Every monetary figure below is denominated in a specific currency and is reported separately per "
        "currency. Never add, subtract, average or otherwise combine amounts in different currencies, and "
        "never state a single overall total across currencies -- no exchange rate is available to you. "
        "Always name the currency alongside any amount you quote. "
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
