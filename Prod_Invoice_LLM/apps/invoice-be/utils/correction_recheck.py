"""Re-checking the arithmetic after a human correction (BE Gap 535).

Shared by `routers/audit.py` and `routers/outbound_audit.py`.

A correction could break the totals (grand total corrected to 100 on a 500
subtotal) and the invoice stayed approvable with no alert. After a correction
touches a money field, the two checks extraction runs — `verify_line_items_math`
and `verify_totals_math`, with the tenant's tolerance overrides — run on the
values before and after the correction, and a check that passed before and
fails after raises its alert.

"Passed before" matters: the invoice row has no `round_off` column, so an
invoice whose printed Round Off line (or the vendor's own arithmetic) made a
check fail from the start is not re-flagged on every later correction.

Founder ruling 2026-09-15: raise an alert, never block the approval, and never
rewrite a total (discounts, deductions and round-off make "subtotal + tax" the
wrong answer for real invoices).
"""
import copy
from typing import Any

from utils.rule_schema import apply_alert_overrides, tolerance_overrides
from utils.verification_tools import verify_line_items_math, verify_totals_math

#: The fields whose correction can change what the two arithmetic checks see.
MONEY_FIELDS = ("items", "subtotal", "tax_amount", "grand_total", "discount_amount", "discount_percent")


def snapshot_money_fields(invoice: Any) -> dict:
    """The invoice's money fields as they are now, copied so later changes do not reach the snapshot."""
    return {field: copy.deepcopy(getattr(invoice, field, None)) for field in MONEY_FIELDS}


def alerts_raised_by_correction(
    before: dict, after: dict, *, rules: Any, doc_type: str | None, open_alerts: list
) -> list[dict]:
    """The alerts a correction earns: checks that pass on `before` and fail on `after`, relabelled by the
    tenant's alert overrides, leaving out any identical alert that is already open. Each carries
    `raised_by: "correction"` so the trail and the auditor can tell it from an extraction alert."""
    tolerances = tolerance_overrides(rules)
    failing_before = {alert["type"] for alert in _math_alerts(before, tolerances, doc_type)}
    raised = [
        {**alert, "raised_by": "correction"}
        for alert in _math_alerts(after, tolerances, doc_type)
        if alert["type"] not in failing_before
    ]
    open_keys = {_key(alert) for alert in open_alerts}
    return [alert for alert in apply_alert_overrides(raised, rules) if _key(alert) not in open_keys]


def _math_alerts(values: dict, tolerances: dict, doc_type: str | None) -> list[dict]:
    alerts = []
    line_items_alert = verify_line_items_math(
        values["items"] or [],
        values["subtotal"],
        invoice_tax_amount=values["tax_amount"],
        tolerances=tolerances,
        doc_type=doc_type,
    )
    if line_items_alert:
        alerts.append(line_items_alert)
    totals_alert = verify_totals_math(
        values["subtotal"],
        values["tax_amount"],
        values["grand_total"],
        discount_amount=values["discount_amount"],
        discount_percent=values["discount_percent"],
        tolerances=tolerances,
    )
    if totals_alert:
        alerts.append(totals_alert)
    return alerts


def _key(alert: Any) -> tuple:
    if isinstance(alert, dict):
        return (alert.get("type"), alert.get("field"), alert.get("message"))
    return (None, None, alert)
