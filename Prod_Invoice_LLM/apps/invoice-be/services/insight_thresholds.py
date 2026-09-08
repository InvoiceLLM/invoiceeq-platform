"""Feature 30 task 30.0g — the gating thresholds, and the per-tenant override.

WHY THIS MODULE EXISTS
----------------------
Ruling R9 fixed three numbers ("over-invoicing history needs >= 3 linked pairs",
"quote drift needs >= 2 invoices after the quote", "repeat short delivery needs
>= 3 challans") and two tolerances (ruling R5: bank match within +/- 1 currency
unit and +/- 5 days). Every one of them decides whether the user is SHOWN a
finding, which makes them correctness-deciding logic and therefore code, never a
line in a prompt (hard rule 3, CONVENTIONS.md).

They live in one module rather than next to the cards that read them for a
concrete reason: the same threshold is read in two places (the card that gates
on it and the "checks not run + why" card that has to say *what* the threshold
was), and a card that reports a different number from the one it gated on is
worse than no explanation at all.

THE OVERRIDE
------------
A tenant with no `tenant_insight_setting` row gets the shipped constant with no
database read at all -- `threshold()` only queries when a session is handed to
it, and returns the default on any failure. That is deliberate fail-soft
behaviour: a threshold is a display gate, and a database hiccup must degrade to
"use the shipped number", never to a card that raises inside the bubble.

`threshold()` is intentionally NOT cached. The values are read a handful of times
per attachment, and a cache would mean an override set in the settings UI takes
effect at an unpredictable later moment -- the one behaviour that makes a knob
feel broken.
"""
from __future__ import annotations

import logging
from typing import Any, Mapping, Optional

logger = logging.getLogger(__name__)

#: The shipped defaults (ruling R9 for the three counts, ruling R5 for the two
#: bank tolerances). Names are the wire names: they are what a
#: `tenant_insight_setting.name` row must contain, what the "checks not run"
#: card quotes, and what a test overrides -- so renaming one is a schema change,
#: not a refactor.
THRESHOLDS: Mapping[str, float] = {
    # R9: a vendor's over-invoicing HISTORY is only a claim worth making once
    # there are enough linked PO/invoice pairs for "history" to mean anything.
    "over_invoicing_pairs": 3.0,
    # R9: "drifted +7% from quote" needs at least two invoices after the quote,
    # or the "drift" is a single data point.
    "quote_drift_invoices": 2.0,
    # R9: repeat short delivery -- one short challan is an incident, three is a
    # pattern.
    "repeat_short_delivery_challans": 3.0,
    # R5: a statement debit matches an invoice within one currency unit ...
    "bank_amount_tolerance": 1.0,
    # ... and five days either side.
    "bank_date_tolerance_days": 5.0,
}


class UnknownThresholdError(KeyError):
    """A threshold name that is not in `THRESHOLDS`.

    Raised rather than defaulted: a typo'd name silently returning 0 would open
    every gated card at once, which is the loudest possible product failure from
    the quietest possible bug.
    """


def threshold(name: str, tenant_id: Any = None, db_session: Optional[Any] = None) -> float:
    """The value of `name` for this tenant: the override if one exists, else the
    shipped constant.

    `db_session` is optional and last on purpose. Every card already holds a
    session, but the two callers that do not (the "checks not run" card building
    its explanation, and any test asserting the shipped default) must be able to
    ask for the constant without inventing a connection.

    Never raises for anything except an unknown NAME -- a broken query, a missing
    table, a rolled-back transaction all fall back to the default and log.
    """
    if name not in THRESHOLDS:
        raise UnknownThresholdError(name)
    default = float(THRESHOLDS[name])

    if db_session is None or tenant_id is None:
        return default

    try:
        from sqlmodel import select

        from models import TenantInsightSetting

        row = db_session.exec(
            select(TenantInsightSetting).where(
                TenantInsightSetting.tenant_id == tenant_id,
                TenantInsightSetting.name == name,
            )
        ).first()
        if row is not None and row.value is not None:
            return float(row.value)
    except Exception as exc:  # pragma: no cover - defensive, see docstring
        logger.warning(
            "Threshold override lookup failed for %s/%s: %s -- using default %s",
            tenant_id,
            name,
            exc,
            default,
        )
        try:
            db_session.rollback()
        except Exception:
            pass
    return default


def set_threshold(
    name: str, tenant_id: Any, value: float, db_session: Any, updated_by: str | None = None
) -> Any:
    """Upsert one tenant's override. Returns the row.

    Kept here beside `threshold()` rather than in a settings router: the
    validation that matters is "is this a real threshold name", and that check
    belongs with the list it checks against.
    """
    if name not in THRESHOLDS:
        raise UnknownThresholdError(name)

    from datetime import datetime

    from sqlmodel import select

    from models import TenantInsightSetting

    row = db_session.exec(
        select(TenantInsightSetting).where(
            TenantInsightSetting.tenant_id == tenant_id,
            TenantInsightSetting.name == name,
        )
    ).first()
    if row is None:
        row = TenantInsightSetting(
            tenant_id=tenant_id, name=name, value=float(value), updated_by=updated_by
        )
    else:
        row.value = float(value)
        row.updated_by = updated_by
        row.updated_at = datetime.utcnow()
    db_session.add(row)
    db_session.commit()
    db_session.refresh(row)
    return row


def all_thresholds(tenant_id: Any = None, db_session: Optional[Any] = None) -> dict:
    """Every threshold as this tenant sees it.

    The "checks not run + why" card (30.12) renders this: a user told "not enough
    history yet" is owed the number that "enough" means for them, including their
    own override.
    """
    return {name: threshold(name, tenant_id, db_session) for name in THRESHOLDS}
