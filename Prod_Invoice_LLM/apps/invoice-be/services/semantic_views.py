"""Feature 30 task 30.4 (was Feature 29 task 29.14b) — the metric layer over the
four semantic views.

WHAT A METRIC IS HERE
---------------------
A named, parameterised question with exactly one SQL answer:

    query_metric("vendor_spend", tenant_id, vendor_name="Shree Packaging Pvt Ltd")

`METRICS` is the registry. Each entry owns its own SQL, its allowed filters and a
one-line definition in plain words — the definition is not decoration, it is what
the "checks not run" card and the SQL prompt quote when they explain where a
figure came from.

THE TENANT GUARD, WHICH IS THE POINT OF THE MODULE
--------------------------------------------------
Feature 29's ruling (§11 decision 6) was "parameterised tenant WHERE", and it is
enforced three ways here, because one way is a convention and three are a
mechanism:

1. `query_metric()` **raises** without a `tenant_id`. Not "returns nothing" —
   an empty result set looks like a legitimate answer and would be narrated as
   one.
2. Every SQL string in `METRICS` must contain the literal `:tenant_id` bind
   parameter, asserted at import by `_validate_registry()`. A metric added
   without one fails at process start, not on the turn that leaks.
3. Filter values are ALWAYS bind parameters. Nothing in this module concatenates
   a caller's value into SQL — the column list is fixed by the registry, so
   there is no path from user input to SQL text.

Hard rule 3: these are figures, so they are computed here in SQL, not by a model.
The model may be TOLD a metric exists (schema linking, 30.4's second half) and may
choose one; it never writes the arithmetic.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Mapping, Optional, Sequence

logger = logging.getLogger(__name__)


class MetricError(ValueError):
    """An unknown metric, an unknown filter, or a missing tenant.

    A ValueError so a router turns it into a 400 rather than a 500, and a raise
    rather than a silent empty result: see the module docstring.
    """


@dataclass(frozen=True)
class Metric:
    """One named question.

    `filters` is a whitelist of `filter name -> SQL fragment`, each fragment
    carrying its own bind parameter. A filter the registry does not declare is
    refused, which is what keeps the SQL surface closed.
    """

    name: str
    view: str
    definition: str
    sql: str
    filters: Mapping[str, str] = field(default_factory=dict)
    order_by: str = ""
    default_limit: int = 200


#: Every metric the application may ask for. Adding one here is the ONLY way to
#: add a metric — there is deliberately no `query_sql()` escape hatch, because an
#: escape hatch is where the tenant guard stops being true.
METRICS: dict = {
    "vendor_spend": Metric(
        name="vendor_spend",
        view="v_vendor_spend",
        definition=(
            "Inbound invoice spend per vendor per month, excluding deleted and "
            "duplicate invoices."
        ),
        sql="""
            SELECT vendor_name, month, currency, invoice_count, total_amount,
                   tax_amount, first_invoice_date, last_invoice_date
            FROM v_vendor_spend
            WHERE tenant_id = :tenant_id
        """,
        filters={
            "vendor_name": "AND vendor_name = :vendor_name",
            # `IN` over a list of spellings -- the vendor master's whole output
            # (services/vendor_master.vendor_invoice_names). Expanding bind
            # parameters keep it parameterised.
            "vendor_names": "AND vendor_name = ANY(:vendor_names)",
            "since": "AND month >= :since",
            "until": "AND month <= :until",
            "currency": "AND currency = :currency",
        },
        order_by="ORDER BY month DESC, total_amount DESC",
    ),
    "overdue": Metric(
        name="overdue",
        view="v_overdue",
        definition=(
            "Invoices past their due date and not paid. OVERDUE is computed from "
            "due_date at read time; no invoice ever stores that status."
        ),
        sql="""
            SELECT invoice_id, invoice_number, vendor_name, customer_name,
                   flow_direction, currency, grand_total, invoice_date, due_date,
                   days_overdue, status
            FROM v_overdue
            WHERE tenant_id = :tenant_id
        """,
        filters={
            "vendor_name": "AND vendor_name = :vendor_name",
            "vendor_names": "AND vendor_name = ANY(:vendor_names)",
            "flow_direction": "AND flow_direction = :flow_direction",
            "due_before": "AND due_date <= :due_before",
            "min_days_overdue": "AND (CURRENT_DATE - due_date) >= :min_days_overdue",
        },
        order_by="ORDER BY days_overdue DESC",
    ),
    "tax_summary": Metric(
        name="tax_summary",
        view="v_tax_summary",
        definition=(
            "Printed tax and taxable amount per month and direction. The figures "
            "are the ones the documents state; nothing is recomputed from lines."
        ),
        sql="""
            SELECT month, flow_direction, currency, invoice_count,
                   tax_amount, taxable_amount, total_amount
            FROM v_tax_summary
            WHERE tenant_id = :tenant_id
        """,
        filters={
            "flow_direction": "AND flow_direction = :flow_direction",
            "since": "AND month >= :since",
            "until": "AND month <= :until",
        },
        order_by="ORDER BY month DESC",
    ),
    "three_way_match": Metric(
        name="three_way_match",
        view="v_3way_match",
        definition=(
            "What we have been invoiced against each PO number, per vendor. This "
            "is the invoice leg only; the order and delivery legs come from the "
            "attached documents, which are not payables."
        ),
        sql="""
            SELECT po_number, vendor_name, currency, invoice_count,
                   invoiced_amount, first_invoice_date, last_invoice_date,
                   invoice_numbers
            FROM v_3way_match
            WHERE tenant_id = :tenant_id
        """,
        filters={
            "po_number": "AND po_number = :po_number",
            "vendor_name": "AND vendor_name = :vendor_name",
            "vendor_names": "AND vendor_name = ANY(:vendor_names)",
            "min_invoice_count": "AND invoice_count >= :min_invoice_count",
        },
        order_by="ORDER BY invoiced_amount DESC",
    ),
}


def _validate_registry() -> None:
    """Guard 2 (see module docstring), run at import.

    A metric whose SQL forgot `:tenant_id` is a cross-tenant read waiting for its
    first caller. Failing the import is the loudest available failure and the
    only one that happens before any data moves.
    """
    for name, metric in METRICS.items():
        if ":tenant_id" not in metric.sql:
            raise RuntimeError(
                f"Metric {name!r} has no :tenant_id bind parameter. Every metric "
                "must filter by tenant in parameterised SQL."
            )
        for filter_name, fragment in metric.filters.items():
            if ":" not in fragment:
                raise RuntimeError(
                    f"Metric {name!r} filter {filter_name!r} has no bind parameter."
                )


_validate_registry()


def metric_definitions() -> dict:
    """`{name: definition}` — what the schema-linking step and the "where did
    this come from" line quote. Kept separate from `METRICS` so a prompt can be
    given the vocabulary without being given the SQL."""
    return {name: m.definition for name, m in METRICS.items()}


def query_metric(
    name: str,
    tenant_id: Any = None,
    db_session: Any = None,
    limit: Optional[int] = None,
    **filters: Any,
) -> list:
    """Run one metric for one tenant. Returns a list of dicts.

    Raises `MetricError` for an unknown metric, an unknown filter, or a missing
    tenant — never an empty list for any of those, because an empty list is a
    legitimate ANSWER ("nothing is overdue") and must not double as an error.
    """
    metric = METRICS.get(name)
    if metric is None:
        raise MetricError(f"Unknown metric {name!r}. Known: {sorted(METRICS)}")
    if tenant_id is None or str(tenant_id).strip() == "":
        raise MetricError(
            f"Metric {name!r} requires a tenant_id. Refusing to run an unscoped query."
        )
    if db_session is None:
        raise MetricError(f"Metric {name!r} requires a database session.")

    unknown = [f for f in filters if f not in metric.filters]
    if unknown:
        raise MetricError(
            f"Metric {name!r} does not accept {unknown}. Allowed: {sorted(metric.filters)}"
        )

    from sqlalchemy import text

    sql = metric.sql
    params: dict = {"tenant_id": str(tenant_id)}
    for filter_name, value in filters.items():
        if value is None:
            continue
        sql += "\n" + metric.filters[filter_name]
        params[filter_name] = list(value) if filter_name.endswith("_names") else value
    if metric.order_by:
        sql += "\n" + metric.order_by
    sql += "\nLIMIT :row_limit"
    params["row_limit"] = int(limit or metric.default_limit)

    try:
        rows = db_session.execute(text(sql), params).mappings().all()
    except Exception as exc:
        logger.error("Metric %s failed for tenant %s: %s", name, tenant_id, exc)
        try:
            db_session.rollback()
        except Exception:
            pass
        raise
    return [dict(r) for r in rows]


def semantic_views_enabled() -> bool:
    """`ENABLE_SEMANTIC_VIEWS` (Feature 29 capability flag, default False).

    The flag gates USE, never existence: the views are created by an add-only
    migration and exist in both states, so turning the flag off can never leave a
    query pointing at a missing view. Read at call time.
    """
    try:
        from config import get_settings

        return bool(getattr(get_settings(), "ENABLE_SEMANTIC_VIEWS", False))
    except Exception:  # pragma: no cover - defensive
        return False


def preferred_metric_for(question: str) -> Optional[str]:
    """Which metric, if any, answers this question better than raw tables.

    Deliberately a small keyword map and not a model call: this decides which
    SQL runs, and hard rule 3 puts that decision in code. It is also allowed to
    return None on anything it is not sure about — falling back to the ordinary
    schema-linked SQL is the shipped behaviour, not a failure.
    """
    if not question:
        return None
    text_l = question.lower()
    if any(k in text_l for k in ("overdue", "past due", "late payment", "outstanding since")):
        return "overdue"
    if any(k in text_l for k in ("gst", "vat", "tax paid", "tax summary", "input tax")):
        return "tax_summary"
    if any(k in text_l for k in ("against po", "purchase order total", "3-way", "three way")):
        return "three_way_match"
    if any(k in text_l for k in ("spend", "spent", "how much did we buy", "purchases from")):
        return "vendor_spend"
    return None
