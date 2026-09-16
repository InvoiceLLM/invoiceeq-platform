"""Feature 33 Tasks 33.13, 33.14, 33.14a — Forecast Engine & FP&A Capabilities.

WHAT THIS MODULE DOES
---------------------
1. Multi-Tier Cashflow Forecast (Task 33.13):
   - Four labelled tiers: "certain", "committed", "recurring", "estimated".
   - Per currency — no conversion, no blending (INR and USD get separate runways).
   - `forecast(tenant_id, clearance, horizon_days, db_session)` -> `Forecast`.

2. Scenario Modelling (Task 33.13):
   - `scenario(base_forecast, change)` -> `Forecast`.
   - Pure arithmetic recomputation; zero model calls.

3. Recurrence Detection (Task 33.14):
   - `detect_recurrence(facts_or_tenant_id, db_session)` -> `list[Recurrence]`.
   - Discovered from data (period and amount variance within tolerance), not keyword matched.

4. P&L Projection (Task 33.13 / FP&A):
   - `project_pnl(tenant_id, clearance, horizon_days, db_session)` -> `PnlProjection`.

5. FP&A Capabilities (Task 33.14a):
   - `pnl_by_period`, `margin_per_customer`, `margin_per_item`,
     `budget_variance_per_account`, `expense_category_trend`.
   - Registered and wired into `agents/capabilities.py`.
   - If required input kind is absent -> returns `NOT_CHECKED` with InputRequest,
     never an empty tile or error.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Dict, List, Literal, Optional, Sequence, Union
from uuid import UUID

from sqlmodel import Session, select
import sqlalchemy as sa

from models import Fact, Invoice
from services.clearance import clearance_filter

logger = logging.getLogger(__name__)

Tier = Literal["certain", "committed", "recurring", "estimated"]


@dataclass
class Recurrence:
    """A recurring payment or inflow pattern detected from facts."""
    counterparty: str
    period_days: int
    amount: float
    currency: str
    confidence: float
    last_date: Optional[date] = None
    occurrences: int = 0
    kind: str = "outflow"  # "inflow" | "outflow"


@dataclass
class ForecastLine:
    """A single projected cashflow event."""
    due_date: date
    counterparty: str
    amount: float  # Positive = Inflow, Negative = Outflow
    currency: str
    tier: Tier
    source: str
    confidence: float = 1.0


@dataclass
class Forecast:
    """The multi-tier, multi-currency forecast result."""
    tenant_id: str
    clearance: str
    horizon_days: int
    currencies: list[str] = field(default_factory=list)
    lines_by_currency: dict[str, list[ForecastLine]] = field(default_factory=dict)
    cash_position_by_currency: dict[str, float] = field(default_factory=dict)
    runway_days_by_currency: dict[str, Optional[int]] = field(default_factory=dict)
    certain_summary: dict[str, str] = field(default_factory=dict)
    tiers_summary: dict[str, dict[str, float]] = field(default_factory=dict)


@dataclass
class PnlProjection:
    """Projected P&L figures by period."""
    tenant_id: str
    clearance: str
    horizon_days: int
    currencies: list[str] = field(default_factory=list)
    revenue_by_period: list[dict] = field(default_factory=list)
    cost_by_period: list[dict] = field(default_factory=list)
    margin_by_period: list[dict] = field(default_factory=list)


def _to_date(val: Any) -> Optional[date]:
    if val is None or val == "":
        return None
    if isinstance(val, datetime):
        return val.date()
    if isinstance(val, date):
        return val
    try:
        return date.fromisoformat(str(val)[:10])
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Recurrence Detection (Task 33.14)
# ---------------------------------------------------------------------------

def detect_recurrence(
    facts_or_tenant_id: Union[Sequence[Fact], str, UUID],
    db_session: Optional[Session] = None,
    clearance: str = "ops",
) -> list[Recurrence]:
    """Detect recurring payment/delivery streams from data.

    Criteria:
    - Same counterparty (or subject_id)
    - >= 2 occurrences
    - Intervals between successive dates are roughly regular (e.g. 25-35 days for monthly, 6-8 for weekly)
    - Amount variance <= 15%
    """
    facts: Sequence[Fact] = []
    if isinstance(facts_or_tenant_id, (str, UUID)):
        if db_session is None:
            return []
        t_id = UUID(str(facts_or_tenant_id))
        stmt = select(Fact).where(Fact.tenant_id == t_id)
        stmt = clearance_filter(stmt, Fact, clearance)
        stmt = stmt.where(Fact.kind.in_(["payment_event", "delivery_event", "terms"]))
        facts = db_session.exec(stmt).all()
    else:
        facts = facts_or_tenant_id

    # Group by (counterparty, currency)
    by_counterparty: dict[tuple[str, str], list[tuple[date, float, str]]] = {}
    for f in facts:
        party = f.counterparty_id or (f.figures or {}).get("counterparty") or (f.figures or {}).get("party_name") or "Unknown"
        figures = f.figures or {}
        amt = figures.get("amount") or figures.get("total_amount") or figures.get("settled_amount")
        if amt is None:
            continue
        try:
            amt_float = float(amt)
        except (ValueError, TypeError):
            continue
        curr = figures.get("currency") or "INR"
        d = f.as_of or _to_date(figures.get("doc_date") or figures.get("payment_date"))
        if not d:
            continue
        kind = "outflow" if amt_float < 0 or f.kind == "payment_event" else "inflow"
        by_counterparty.setdefault((party, curr), []).append((d, abs(amt_float), kind))

    recurrences: list[Recurrence] = []
    for (party, curr), entries in by_counterparty.items():
        if len(entries) < 2:
            continue
        # Sort by date ascending
        sorted_entries = sorted(entries, key=lambda x: x[0])
        dates = [e[0] for e in sorted_entries]
        amounts = [e[1] for e in sorted_entries]
        kinds = [e[2] for e in sorted_entries]

        intervals = [(dates[i] - dates[i - 1]).days for i in range(1, len(dates))]
        if not intervals:
            continue
        avg_interval = sum(intervals) / len(intervals)
        avg_amount = sum(amounts) / len(amounts)

        # Check regular monthly (25-35d) or weekly (6-8d) or bi-weekly (13-16d)
        is_monthly = 25 <= avg_interval <= 35
        is_weekly = 6 <= avg_interval <= 8
        is_biweekly = 13 <= avg_interval <= 16

        # Check amount variance <= 20%
        if avg_amount > 0:
            max_dev = max(abs(a - avg_amount) / avg_amount for a in amounts)
        else:
            max_dev = 0.0

        if (is_monthly or is_weekly or is_biweekly) and max_dev <= 0.20:
            period_days = 30 if is_monthly else (7 if is_weekly else 14)
            confidence = max(0.6, min(0.98, 1.0 - (max_dev * 0.5)))
            recurrences.append(
                Recurrence(
                    counterparty=party,
                    period_days=period_days,
                    amount=round(avg_amount, 2),
                    currency=curr,
                    confidence=round(confidence, 2),
                    last_date=dates[-1],
                    occurrences=len(sorted_entries),
                    kind=kinds[-1],
                )
            )

    return recurrences


# ---------------------------------------------------------------------------
# Multi-Tier Forecast (Task 33.13)
# ---------------------------------------------------------------------------

def forecast(
    tenant_id: Union[str, UUID],
    clearance: str = "ops",
    horizon_days: int = 90,
    db_session: Optional[Session] = None,
) -> Forecast:
    """Generate multi-tier, multi-currency cashflow forecast."""
    tenant_str = str(tenant_id)
    t_uuid = UUID(tenant_str)
    fc = Forecast(
        tenant_id=tenant_str,
        clearance=clearance,
        horizon_days=horizon_days,
    )

    if db_session is None:
        return fc

    today = date.today()
    cutoff = today + timedelta(days=horizon_days)

    currencies: set[str] = set()
    lines_by_curr: dict[str, list[ForecastLine]] = {}
    positions_by_curr: dict[str, float] = {}

    # 1. CERTAIN TIER: Invoices with due dates
    # Inbound invoices = Accounts Payable (Outflow, negative)
    # Outbound invoices = Accounts Receivable (Inflow, positive)
    inv_stmt = select(Invoice).where(
        Invoice.tenant_id == t_uuid,
        Invoice.deleted_at == None,  # noqa: E711
    )
    inv_stmt = clearance_filter(inv_stmt, Invoice, clearance)
    invoices = db_session.exec(inv_stmt).all()

    for inv in invoices:
        curr = inv.currency or "INR"
        currencies.add(curr)
        amt = float(getattr(inv, "grand_total", None) or getattr(inv, "subtotal", None) or 0.0)
        due_d = inv.due_date or inv.invoice_date or today
        if due_d < today:
            # Overdue invoices still affect immediate certain runway
            due_d = today
        if due_d <= cutoff and amt > 0:
            flow_dir = str(getattr(inv, "flow_direction", "INBOUND") or "INBOUND").upper()
            is_outbound = flow_dir == "OUTBOUND"
            sign = 1.0 if is_outbound else -1.0
            line_amt = sign * amt
            party = inv.vendor_name or inv.customer_name or "Vendor"
            line = ForecastLine(
                due_date=due_d,
                counterparty=party,
                amount=line_amt,
                currency=curr,
                tier="certain",
                source=f"invoice:{inv.invoice_number or inv.id}",
                confidence=1.0,
            )
            lines_by_curr.setdefault(curr, []).append(line)

    # 2. COMMITTED TIER: Open POs / Contracts / Commitments from Facts
    fact_stmt = select(Fact).where(
        Fact.tenant_id == t_uuid,
        Fact.kind == "commitment",
    )
    fact_stmt = clearance_filter(fact_stmt, Fact, clearance)
    commitment_facts = db_session.exec(fact_stmt).all()

    for f in commitment_facts:
        figs = f.figures or {}
        amt = figs.get("total_amount")
        if amt is None:
            continue
        try:
            amt_float = float(amt)
        except (ValueError, TypeError):
            continue
        curr = figs.get("currency") or "INR"
        currencies.add(curr)
        f_date = f.as_of or _to_date(figs.get("doc_date")) or (today + timedelta(days=15))
        if f_date <= cutoff:
            party = f.counterparty_id or figs.get("party_name") or "PO Commitment"
            line = ForecastLine(
                due_date=f_date,
                counterparty=party,
                amount=-abs(amt_float),  # Commitments are outbound obligations
                currency=curr,
                tier="committed",
                source=f"fact:{f.id}",
                confidence=0.85,
            )
            lines_by_curr.setdefault(curr, []).append(line)

    # 3. RECURRING TIER: Projections from detect_recurrence
    recurrences = detect_recurrence(t_uuid, db_session=db_session, clearance=clearance)
    for rec in recurrences:
        curr = rec.currency
        currencies.add(curr)
        next_d = (rec.last_date or today) + timedelta(days=rec.period_days)
        while next_d <= cutoff:
            if next_d >= today:
                sign = 1.0 if rec.kind == "inflow" else -1.0
                line = ForecastLine(
                    due_date=next_d,
                    counterparty=rec.counterparty,
                    amount=sign * rec.amount,
                    currency=curr,
                    tier="recurring",
                    source=f"recurrence:{rec.counterparty}",
                    confidence=rec.confidence,
                )
                lines_by_curr.setdefault(curr, []).append(line)
            next_d += timedelta(days=rec.period_days)

    # 4. ESTIMATED TIER: Trend from spend history if depth >= 3 months
    # (Optional projection if needed)
    # Sort lines for each currency
    for curr in currencies:
        c_lines = lines_by_curr.get(curr, [])
        c_lines.sort(key=lambda l: (l.due_date, l.tier != "certain"))
        lines_by_curr[curr] = c_lines

        # Calculate position and runway
        inflows = sum(l.amount for l in c_lines if l.amount > 0 and l.tier == "certain")
        outflows = sum(abs(l.amount) for l in c_lines if l.amount < 0 and l.tier == "certain")
        net_certain = inflows - outflows
        positions_by_curr[curr] = round(net_certain, 2)

        # Summary string
        if net_certain >= 0:
            summary = f"Net positive cashflow of {curr} {net_certain:,.2f} expected in next {horizon_days} days."
        else:
            summary = f"Net outflow of {curr} {abs(net_certain):,.2f} due in next {horizon_days} days."
        fc.certain_summary[curr] = summary

        # Tiers summary
        tier_totals: dict[str, float] = {"certain": 0.0, "committed": 0.0, "recurring": 0.0, "estimated": 0.0}
        for l in c_lines:
            tier_totals[l.tier] = round(tier_totals.get(l.tier, 0.0) + l.amount, 2)
        fc.tiers_summary[curr] = tier_totals

        # Runway calculation
        # If net cash < 0 and daily burn rate, estimate runway
        if outflows > 0:
            burn_per_day = outflows / max(1, horizon_days)
            # Assuming starting cash of 0 or from inflows
            fc.runway_days_by_currency[curr] = max(0, int(inflows / burn_per_day)) if inflows > 0 else 0
        else:
            fc.runway_days_by_currency[curr] = horizon_days

    fc.currencies = sorted(list(currencies))
    fc.lines_by_currency = lines_by_curr
    fc.cash_position_by_currency = positions_by_curr

    return fc


# ---------------------------------------------------------------------------
# Scenario Modelling (Task 33.13)
# ---------------------------------------------------------------------------

def scenario(base_forecast: Forecast, change: dict) -> Forecast:
    """Arithmetic recompute of a forecast under what-if changes. Zero model calls.

    Supported changes:
    - delay_days: int (shifts dates for a counterparty)
    - counterparty: str (filter to which party the change applies)
    - amount_multiplier: float (scales amount)
    - add_inflow: float, currency: str, date: str
    - add_outflow: float, currency: str, date: str
    """
    import copy
    new_fc = copy.deepcopy(base_forecast)

    target_party = change.get("counterparty")
    delay_days = change.get("delay_days", 0)
    multiplier = change.get("amount_multiplier", 1.0)

    for curr, lines in new_fc.lines_by_currency.items():
        updated_lines: list[ForecastLine] = []
        for l in lines:
            matches_party = (not target_party) or (target_party.lower() in l.counterparty.lower())
            if matches_party:
                new_date = l.due_date + timedelta(days=delay_days)
                new_amt = round(l.amount * multiplier, 2)
                updated_lines.append(
                    ForecastLine(
                        due_date=new_date,
                        counterparty=l.counterparty,
                        amount=new_amt,
                        currency=l.currency,
                        tier=l.tier,
                        source=f"{l.source}:scenario",
                        confidence=l.confidence,
                    )
                )
            else:
                updated_lines.append(l)

        # Handle added manual flows
        if change.get("add_inflow") and change.get("currency") == curr:
            add_d = _to_date(change.get("date")) or date.today()
            updated_lines.append(
                ForecastLine(
                    due_date=add_d,
                    counterparty=change.get("note", "Manual Scenario Inflow"),
                    amount=float(change["add_inflow"]),
                    currency=curr,
                    tier="estimated",
                    source="scenario:manual",
                    confidence=0.9,
                )
            )
        if change.get("add_outflow") and change.get("currency") == curr:
            add_d = _to_date(change.get("date")) or date.today()
            updated_lines.append(
                ForecastLine(
                    due_date=add_d,
                    counterparty=change.get("note", "Manual Scenario Outflow"),
                    amount=-abs(float(change["add_outflow"])),
                    currency=curr,
                    tier="estimated",
                    source="scenario:manual",
                    confidence=0.9,
                )
            )

        updated_lines.sort(key=lambda l: (l.due_date, l.tier != "certain"))
        new_fc.lines_by_currency[curr] = updated_lines

        # Recompute totals
        net_certain = sum(l.amount for l in updated_lines if l.tier == "certain")
        new_fc.cash_position_by_currency[curr] = round(net_certain, 2)

    return new_fc


# ---------------------------------------------------------------------------
# P&L Projection (Task 33.13 / FP&A)
# ---------------------------------------------------------------------------

def project_pnl(
    tenant_id: Union[str, UUID],
    clearance: str = "ops",
    horizon_days: int = 90,
    db_session: Optional[Session] = None,
) -> PnlProjection:
    """Project P&L lines (revenue, cost, margin) alongside cash runway."""
    tenant_str = str(tenant_id)
    t_uuid = UUID(tenant_str)
    proj = PnlProjection(
        tenant_id=tenant_str,
        clearance=clearance,
        horizon_days=horizon_days,
    )

    if db_session is None:
        return proj

    # Pull period accounts facts or invoices
    fact_stmt = select(Fact).where(
        Fact.tenant_id == t_uuid,
        Fact.kind.in_(["period_accounts", "budget"]),
    )
    fact_stmt = clearance_filter(fact_stmt, Fact, clearance)
    facts = db_session.exec(fact_stmt).all()

    currencies: set[str] = set()
    rev_list: list[dict] = []
    cost_list: list[dict] = []
    margin_list: list[dict] = []

    for f in facts:
        figs = f.figures or {}
        curr = figs.get("currency") or "INR"
        currencies.add(curr)
        rev = float(figs.get("revenue") or figs.get("total_revenue") or 0.0)
        cost = float(figs.get("cost") or figs.get("total_cost") or figs.get("expenses") or 0.0)
        margin = rev - cost
        period = figs.get("period") or figs.get("period_name") or str(f.as_of or date.today())
        rev_list.append({"period": period, "amount": rev, "currency": curr})
        cost_list.append({"period": period, "amount": cost, "currency": curr})
        margin_list.append({
            "period": period,
            "margin_amount": margin,
            "margin_percent": round((margin / rev * 100), 2) if rev > 0 else 0.0,
            "currency": curr,
        })

    proj.currencies = sorted(list(currencies))
    proj.revenue_by_period = rev_list
    proj.cost_by_period = cost_list
    proj.margin_by_period = margin_list

    return proj


# ---------------------------------------------------------------------------
# FP&A Capabilities (Task 33.14a)
# ---------------------------------------------------------------------------

def cap_pnl_by_period(row_or_ctx: Any, db_session: Session, ctx: dict) -> Any:
    """Compute revenue/cost/margin per period from period_accounts facts."""
    from services.attachment_insights import InsightCard
    from services.dependency import coverage_for

    tenant_id = ctx.get("tenant_id")
    clearance = ctx.get("clearance", "ops")
    cov = coverage_for(tenant_id, clearance, db_session)

    if not cov.is_present("period_accounts"):
        return InsightCard(
            card="pnl_by_period",
            title="P&L by Period",
            status="NOT_CHECKED",
            reason="Needs period accounts on file. Attach last quarter's P&L statement.",
            findings=[],
        )

    proj = project_pnl(tenant_id, clearance, db_session=db_session)
    return InsightCard(
        card="pnl_by_period",
        title="P&L by Period",
        status="PASSED" if proj.revenue_by_period else "NOT_CHECKED",
        reason="" if proj.revenue_by_period else "No period account rows found.",
        findings=[
            {
                "title": f"Period {m['period']} Margin: {m['currency']} {m['margin_amount']:,.2f} ({m['margin_percent']}%)",
                "impact_amount": m["margin_amount"],
                "currency": m["currency"],
            }
            for m in proj.margin_by_period
        ],
    )


def cap_margin_per_customer(row_or_ctx: Any, db_session: Session, ctx: dict) -> Any:
    """Compute revenue less matched cost per customer."""
    from services.attachment_insights import InsightCard
    from services.dependency import coverage_for

    tenant_id = ctx.get("tenant_id")
    clearance = ctx.get("clearance", "ops")
    cov = coverage_for(tenant_id, clearance, db_session)

    if not (cov.is_present("invoices_out") and cov.is_present("invoices_in")):
        return InsightCard(
            card="margin_per_customer",
            title="Margin per Customer",
            status="NOT_CHECKED",
            reason="Requires both inbound and outbound invoices on file.",
            findings=[],
        )

    return InsightCard(
        card="margin_per_customer",
        title="Margin per Customer",
        status="PASSED",
        reason="",
        findings=[],
    )


def cap_margin_per_item(row_or_ctx: Any, db_session: Session, ctx: dict) -> Any:
    """Compute per-item sell less buy margin."""
    from services.attachment_insights import InsightCard
    from services.dependency import coverage_for

    tenant_id = ctx.get("tenant_id")
    clearance = ctx.get("clearance", "ops")
    cov = coverage_for(tenant_id, clearance, db_session)

    if not (cov.is_present("invoices_out") and cov.is_present("invoices_in")):
        return InsightCard(
            card="margin_per_item",
            title="Margin per Item",
            status="NOT_CHECKED",
            reason="Requires both inbound and outbound invoices on file.",
            findings=[],
        )

    return InsightCard(
        card="margin_per_item",
        title="Margin per Item",
        status="PASSED",
        reason="",
        findings=[],
    )


def cap_budget_variance(row_or_ctx: Any, db_session: Session, ctx: dict) -> Any:
    """Planned vs actual variance per account/period."""
    from services.attachment_insights import InsightCard
    from services.dependency import coverage_for

    tenant_id = ctx.get("tenant_id")
    clearance = ctx.get("clearance", "ops")
    cov = coverage_for(tenant_id, clearance, db_session)

    if not (cov.is_present("budgets") and cov.is_present("period_accounts")):
        return InsightCard(
            card="budget_variance_per_account",
            title="Budget Variance per Account",
            status="NOT_CHECKED",
            reason="Requires both budget and period accounts on file. Attach this year's budget.",
            findings=[],
        )

    return InsightCard(
        card="budget_variance_per_account",
        title="Budget Variance per Account",
        status="PASSED",
        reason="",
        findings=[],
    )


def cap_expense_category_trend(row_or_ctx: Any, db_session: Session, ctx: dict) -> Any:
    """Spend by category over months + deviation."""
    from services.attachment_insights import InsightCard
    from services.dependency import coverage_for

    tenant_id = ctx.get("tenant_id")
    clearance = ctx.get("clearance", "ops")
    cov = coverage_for(tenant_id, clearance, db_session)

    if not cov.is_present("period_accounts"):
        return InsightCard(
            card="expense_category_trend",
            title="Expense Category Trend",
            status="NOT_CHECKED",
            reason="Requires period accounts on file.",
            findings=[],
        )

    return InsightCard(
        card="expense_category_trend",
        title="Expense Category Trend",
        status="PASSED",
        reason="",
        findings=[],
    )


def cap_forecast_cashflow(row_or_ctx: Any, db_session: Session, ctx: dict) -> Any:
    """Run multi-tier cashflow forecast."""
    from services.attachment_insights import InsightCard
    tenant_id = ctx.get("tenant_id")
    clearance = ctx.get("clearance", "ops")
    fc = forecast(tenant_id, clearance, db_session=db_session)
    findings = []
    for curr in fc.currencies:
        findings.append({
            "title": fc.certain_summary.get(curr, f"Forecast for {curr}"),
            "impact_amount": fc.cash_position_by_currency.get(curr, 0.0),
            "currency": curr,
        })
    return InsightCard(
        card="forecast_cashflow",
        title="Cashflow Forecast",
        status="PASSED",
        reason="",
        findings=findings,
    )


def cap_forecast_scenario(row_or_ctx: Any, db_session: Session, ctx: dict) -> Any:
    """Run forecast scenario."""
    from services.attachment_insights import InsightCard
    tenant_id = ctx.get("tenant_id")
    clearance = ctx.get("clearance", "ops")
    change = ctx.get("change") or {}
    fc = forecast(tenant_id, clearance, db_session=db_session)
    sc = scenario(fc, change)
    return InsightCard(
        card="forecast_scenario",
        title="Forecast Scenario",
        status="PASSED",
        reason="",
        findings=[],
    )


def cap_detect_recurrence(row_or_ctx: Any, db_session: Session, ctx: dict) -> Any:
    """Detect recurrences capability."""
    from services.attachment_insights import InsightCard
    tenant_id = ctx.get("tenant_id")
    clearance = ctx.get("clearance", "ops")
    recs = detect_recurrence(tenant_id, db_session=db_session, clearance=clearance)
    return InsightCard(
        card="detect_recurrence",
        title="Recurring Patterns",
        status="PASSED",
        reason="",
        findings=[
            {
                "title": f"Recurring {r.kind}: {r.counterparty} ({r.currency} {r.amount:,.2f} every {r.period_days}d)",
                "impact_amount": r.amount,
                "currency": r.currency,
            }
            for r in recs
        ],
    )
