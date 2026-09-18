"""Feature 34 (ATLAS) task 34.9 — the forecast as a warning with levers.

Spec: `docs/feature_34_atlas.md` §7.5 · `atlas_discussion.md` **D15**, **D44**.

    A warning with levers, never a chart. *"On the 22nd you are Rs 1.2L short --
    chasing these two invoices covers it, or delaying this payment covers it, or
    it resolves itself if Sharma pays on time."* A date, a number, and actions.

What this adds to what `atlas_skills.cash_position()` already did
-----------------------------------------------------------------
Slice B's cash line answers "where do you stand". It is a position and a runway,
and §14.3 said plainly that the levers were task 34.9's. This module is that
task: it walks the balance forward day by day and finds **the first day it goes
below zero**, which is a different question from "what is the net position in 30
days" and a much more useful one -- a tenant can be comfortably positive at the
end of a month and unable to pay on the 22nd.

Deterministic, per hard rule 3
------------------------------
Every number here is `Decimal` arithmetic over rows. A model may phrase the
resulting line; it does not decide whether the tenant is short, on which day, or
by how much. The three levers are selected by arithmetic too -- the largest
receivable first until the gap is covered, the single payable whose deferral
covers it, the receivable already expected before that date -- because "which
invoices would fix this" is a correctness question dressed as a suggestion.

Visible to Auditors (D44)
-------------------------
These lines declare `AtlasCapability.AUDIT`, not `ADMIN`. D44 reversed D2 for
that role: one forecast, one view of it, and the Admin still sees it as the
superset (§2.2).

What it deliberately does not do
--------------------------------
* **It does not use payment behaviour, and it says so.** §7.5's highest-value
  item is "what will actually arrive, not what is due", and this forecast is
  built on due dates. The honest response to that gap is not to silently build
  the weaker forecast and let it look like the stronger one -- `assumption` is a
  required field on the contract for exactly this reason, and it says due dates
  in words on every line. §5.2's "right flag, wrong reason" is the failure this
  avoids.
* **It never blends currencies** (§7.4, D32). One walk per currency, one line per
  currency, and no total across them.
* **It emits nothing when there is no shortfall.** A line saying "you are fine"
  is the false-positive volume §5.2 says trains a user to stop reading. The cash
  position line (Slice B) already carries the standing picture.
* **It emits nothing when the balance is unknown.** With no imported bank
  statement there is no starting point, and a walk from zero would report every
  tenant as short on day one. "Unknown" and "short" must not render the same, for
  the same reason `runway_days` is `None` rather than a large number.
"""

from __future__ import annotations

from dataclasses import dataclass, field as dc_field
from datetime import date, timedelta
from decimal import Decimal
from typing import Iterable

from sqlmodel import Session

from models import Invoice
from services.atlas_capabilities import AtlasCapability
from services.atlas_contract import (
    Action,
    Certainty,
    Forecast,
    Lever,
    Recommendation,
    Reversibility,
    Verify,
    What,
    Why,
    validate_recommendation,
)
from services.atlas_figures import computed_figure, count_reference, money_prefix, render_amount

__all__ = [
    "FORECAST_HORIZON_DAYS",
    "Shortfall",
    "shortfalls",
    "forecast_recommendations",
]

#: How far ahead the walk runs. The same month `cash_position()` uses: a payment
#: run is planned over a month, and a longer window is a chart (§7.5 says never
#: a chart).
FORECAST_HORIZON_DAYS = 30

#: The assumption, in the words the line prints. Stated as a constant because
#: §7.5 makes it a required part of the answer, and a sentence assembled per call
#: is a sentence that eventually differs between two lines of the same forecast.
DUE_DATE_ASSUMPTION = (
    "every invoice is paid on its due date, ours and theirs — I do not yet know "
    "who pays late"
)

#: How many levers of one sort to offer. Three receivables to chase is a task;
#: eleven is a list the user has to triage, which is the work the line existed to
#: remove.
_MAX_LEVERS_PER_KIND = 3


@dataclass(frozen=True)
class Shortfall:
    """The first day this currency's balance goes below zero, and by how much."""

    currency: str
    on_date: date
    #: How far below zero. A positive number: "short by" reads better than a
    #: negative balance, and the sign is in the word.
    amount: Decimal
    #: Outbound invoices due *after* `on_date` -- chasing them early covers it.
    chaseable: list[Invoice] = dc_field(default_factory=list)
    #: Inbound invoices due on or before `on_date` -- deferring one covers it.
    deferrable: list[Invoice] = dc_field(default_factory=list)
    #: Outbound invoices already due on or before `on_date`. Nothing to do: if
    #: they land on time there is no shortfall at all, which is §7.5's third
    #: lever and the only honest one that asks nothing of the user.
    already_expected: list[Invoice] = dc_field(default_factory=list)


def shortfalls(
    db: Session,
    ctx,
    *,
    balances: dict[str, Decimal] | None = None,
    horizon_days: int = FORECAST_HORIZON_DAYS,
) -> list[Shortfall]:
    """Walk each currency's balance forward and find the first short day.

    `ctx` is an `atlas_skills.SkillContext`; it is duck-typed rather than
    imported so that this module and the skills module do not import each other.

    The walk is day by day rather than a net sum on purpose. A net position is
    the answer to a question nobody asks: money that arrives on the 28th does not
    help a payment run on the 22nd, and a forecast that says otherwise is wrong
    in the direction that costs the customer a missed payment.
    """
    from services.atlas_skills import _amount, _currency_of, _latest_balances, _live_invoices

    if balances is None:
        balances = _latest_balances(db, ctx)
    if not balances:
        # No imported statement, no starting point. Stated in the module
        # docstring: a walk from zero would report every tenant as short.
        return []

    horizon = ctx.today + timedelta(days=horizon_days)
    by_currency: dict[str, list[Invoice]] = {}
    for inv in _live_invoices(db, ctx):
        if not inv.due_date or inv.due_date > horizon or inv.due_date < ctx.today:
            continue
        by_currency.setdefault(_currency_of(inv, ctx), []).append(inv)

    found: list[Shortfall] = []
    for currency, opening in sorted(balances.items()):
        invoices = by_currency.get(currency, [])
        # Only invoices that actually move money in this window.
        outflow = [i for i in invoices if i.flow_direction == "INBOUND" and i.status in _OWED]
        inflow = [i for i in invoices if i.flow_direction == "OUTBOUND" and i.status == "SENT"]
        if not outflow:
            # Nothing leaves, so nothing can run short.
            continue

        running = Decimal(opening)
        short_on: date | None = None
        day = ctx.today
        while day <= horizon:
            for inv in inflow:
                if inv.due_date == day:
                    running += _amount(inv)
            for inv in outflow:
                if inv.due_date == day:
                    running -= _amount(inv)
            if running < 0:
                short_on = day
                break
            day += timedelta(days=1)

        if short_on is None:
            continue

        gap = -running
        found.append(
            Shortfall(
                currency=currency,
                on_date=short_on,
                amount=gap,
                chaseable=_biggest_first(
                    [i for i in inflow if i.due_date and i.due_date > short_on]
                ),
                deferrable=_biggest_first(
                    [i for i in outflow if i.due_date and i.due_date <= short_on]
                ),
                already_expected=_biggest_first(
                    [i for i in inflow if i.due_date and i.due_date <= short_on]
                ),
            )
        )
    return found


#: Inbound statuses that still owe money. A REJECTED invoice is not a payable,
#: and a PAID one has already left the balance the statement reported.
_OWED = ("AUDIT_REQUIRED", "REVIEW_LATER", "NEEDS_RESUBMISSION")  # hardcode-ok: invoice STATUS tokens, this repo's own status machine (routers/audit.py), not domain data


def _biggest_first(invoices: Iterable[Invoice]) -> list[Invoice]:
    """Largest amount first, then by id so the order never wobbles.

    Largest first because a lever is judged by whether it closes the gap, and the
    fewest invoices that do it is the least work asked of the user.
    """
    from services.atlas_skills import _amount

    return sorted(invoices, key=lambda inv: (-_amount(inv), str(inv.id)))


def forecast_recommendations(
    found: Iterable[Shortfall], *, tenant_id, today: date
) -> list[Recommendation]:
    """One line per short currency: a date, a number, and the levers (§7.5)."""
    lines: list[Recommendation] = []
    for shortfall in found:
        currency = shortfall.currency
        mark = money_prefix(currency)
        rendered_gap = render_amount(shortfall.amount, currency)
        levers = _levers(shortfall)

        text = (
            f"On {_day_month(shortfall.on_date)} you are {mark}{rendered_gap} "  # hardcode-ok: the amount goes through `render_amount()`; `mark` is this line's own currency symbol
            f"short. {DUE_DATE_ASSUMPTION.capitalize()}."
        )
        figures = [
            computed_figure(
                shortfall.amount,
                currency,
                "the balance after every invoice due on or before that date, "
                "walked day by day from the last imported statement balance",
            )
        ]
        for lever in levers:
            # Every lever's amount is a figure in its own right: it is a number a
            # person reads and acts on, and §5.3 does not have a "smaller
            # numbers need no witness" clause.
            figures.append(
                computed_figure(
                    lever[1],
                    currency,
                    lever[2],
                )
            )

        lines.append(
            validate_recommendation(
                Recommendation(
                    id=f"forecast-short-{currency}",  # hardcode-ok: an id built from an ISO currency code, deterministic per D49
                    capability=AtlasCapability.AUDIT,  # D44: one forecast, one view of it.
                    skill="cash_shortfall_with_levers",
                    what=What(
                        headline=f"Short on {_day_month(shortfall.on_date)}",  # hardcode-ok: a count of levers, not money -- `count_reference` declares it
                        entity_kind="tenant",
                        entity_id=str(tenant_id),
                    ),
                    why=Why(
                        text=text,
                        figures=figures,
                        references=[count_reference(len(levers))],
                        doubt=(
                            "This is built on due dates, not on how these people "
                            "actually pay — I do not know that yet, so the day "
                            "could move."
                        ),
                    ),
                    action=Action(
                        kind="open_upcoming_payments",
                        label="Show what is due",
                        target_id=str(tenant_id),
                        params={"currency": currency, "on": shortfall.on_date.isoformat()},
                    ),
                    verify=Verify(
                        question=(
                            "Which invoices did you add up to get to that day, "
                            "and what did you assume about when each is paid?"
                        )
                    ),
                    forecast=Forecast(
                        on_date=shortfall.on_date,
                        shortfall_rendered=rendered_gap,
                        assumption=DUE_DATE_ASSUMPTION,
                        levers=[
                            Lever(
                                kind=kind,
                                label=label,
                                target_id=target_id,
                                amount_rendered=render_amount(amount, currency),
                            )
                            for kind, amount, _computation, label, target_id in levers
                        ],
                    ),
                    stake=shortfall.amount,
                    fixable_until=shortfall.on_date,
                    since=today,
                    # UNCERTAIN, and the doubt says why: the date rests on an
                    # assumption the line states. A forecast presented as certain
                    # is §5.1's exact prohibition.
                    certainty=Certainty.UNCERTAIN,
                    reversibility=Reversibility.REVERSIBLE,
                    currency=currency,
                )
            )
        )
    return lines


def _levers(shortfall: Shortfall) -> list[tuple[str, Decimal, str, str, str | None]]:
    """The actions that close the gap, chosen by arithmetic (§7.5).

    Returns `(kind, amount, computation, label, target_id)` tuples. Each one is
    selected because it **covers the gap**, not because it is interesting:

    * **chase** -- the fewest receivables due after the short day whose total
      reaches the shortfall. Largest first, so "chasing these two" is two and not
      seven.
    * **delay** -- the single payable due on or before the short day that is at
      least the shortfall. One invoice, because deferring several is a different
      and larger decision, and if none is big enough this lever is simply not
      offered rather than being offered as a partial fix.
    * **it resolves itself** -- a receivable already due before the short day.
      Nothing is asked of the user; the line is telling them the gap exists only
      because somebody might pay late. Offered last because it is the one lever
      that is not an action.
    """
    from services.atlas_skills import _amount

    levers: list[tuple[str, Decimal, str, str, str | None]] = []

    running = Decimal("0")
    chased = 0
    for inv in shortfall.chaseable:
        if running >= shortfall.amount or chased >= _MAX_LEVERS_PER_KIND:
            break
        running += _amount(inv)
        chased += 1
        levers.append(
            (
                "chase_receivable",
                _amount(inv),
                f"the total of {inv.vendor_name or 'this customer'}'s invoice, "  # hardcode-ok: a vendor name inside a computation string, not a figure; the amount beside it goes through `render_amount()`
                f"due after the short day",
                f"Chase {inv.vendor_name or 'this customer'} early",
                str(inv.id),
            )
        )
    if running < shortfall.amount:
        # Honest rather than tidy: if chasing everything available still does not
        # cover it, the lever is not a lever and is dropped entirely.
        levers = [lever for lever in levers if lever[0] != "chase_receivable"]

    for inv in shortfall.deferrable:
        if _amount(inv) >= shortfall.amount:
            levers.append(
                (
                    "delay_payable",
                    _amount(inv),
                    f"the total of {inv.vendor_name or 'this vendor'}'s invoice, "  # hardcode-ok: a vendor name inside a computation string, not a figure; the amount beside it goes through `render_amount()`
                    f"due on or before the short day",
                    f"Delay {inv.vendor_name or 'this vendor'}",
                    str(inv.id),
                )
            )
            break

    for inv in shortfall.already_expected:
        if _amount(inv) >= shortfall.amount:
            levers.append(
                (
                    "resolves_itself",
                    _amount(inv),
                    f"the total of {inv.vendor_name or 'this customer'}'s invoice, "  # hardcode-ok: a vendor name inside a computation string, not a figure; the amount beside it goes through `render_amount()`
                    f"already due on or before the short day",
                    f"It resolves itself if {inv.vendor_name or 'this customer'} pays on time",
                    None,
                )
            )
            break

    return levers


def _day_month(value: date) -> str:
    """A date, printed the way the rest of ATLAS prints one -- no year.

    Duplicated from `atlas_skills._day_month` rather than imported, because
    importing it would make this module depend on the skills module at import
    time and they already refer to each other lazily inside functions.
    """
    return f"{value.day} {value.strftime('%b')}"  # hardcode-ok: a date, not a figure -- the day number is never money
