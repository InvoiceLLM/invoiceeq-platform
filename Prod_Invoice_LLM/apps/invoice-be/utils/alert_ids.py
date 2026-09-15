"""Every stored alert carries its own id (BE Gap 566).

Alerts are produced in many places (`utils/verification_tools.py`, `agents/extraction_agent.py`,
`services/invoice_reconciliation.py`, the duplicate check in `routers/invoices.py`, the correction
re-check in `utils/correction_recheck.py`) and stored in a handful. Giving the id at the storage
points — not inside each producer — means one helper covers every producer, including future ones;
`tests/test_alert_ids.py` fails if a new storage point skips it.

The id is what `utils/alert_dismissal.py` matches first, so two alerts identical in type, field and
message are still two separately dismissable alerts. Alerts stored before this change have no id and
are left as they are; dismissal matches those by type + field + message (BE Gap 537).
"""
from uuid import uuid4


def with_alert_ids(alerts: list | None) -> list:
    """A copy of `alerts` in which every dict alert has an `id`.

    An existing id is kept, plain-text alerts are left unchanged, and the input list and its dicts
    are not modified.
    """
    return [
        {**alert, "id": uuid4().hex} if isinstance(alert, dict) and not alert.get("id") else alert
        for alert in alerts or []
    ]
