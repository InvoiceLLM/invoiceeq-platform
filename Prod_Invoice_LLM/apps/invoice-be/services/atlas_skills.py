"""Feature 34 (ATLAS) task 34.3 — the Auditor, Trainer and Loader skill sets.

Spec: `docs/feature_34_atlas.md` §2.3, §3.1, §5.3, §7.4 · decisions D13, D21,
D22, D38, D43, D44, D45.

What this module is
-------------------
Feature 33's sixteen capabilities were ten reads and six actions, **seven of the
ten CFO analytics**, with no Auditor skill and no Trainer skill at all -- which
is why those roles' screens were thin. Not a filtering bug, an empty skill set
(§3.1). This module is the three missing skill sets, each emitting
`services.atlas_contract.Recommendation` lines through
`validate_recommendation()` and declaring the `AtlasCapability` the work screen
filters on.

Three rulings shape what they emit
----------------------------------
* **The Auditor sees the full cash position, forecast and runway** (D44). This
  *reverses* D2 for that role: §2.3's bounded cash line -- "approving this
  commits Rs 2.4L on the 20th" with the position withheld -- is gone. There is
  one forecast and one view of it. So the cash lines below declare
  `AtlasCapability.AUDIT`, not `ADMIN`, and the Admin still sees them because
  §2.2 makes the Admin the superset of every capability. FP&A and margin
  analytics are *not* here and stay chat-only (D16).
* **A Trainer's correction line shows the invoice before and after the fix**
  (D45) -- carried by the `Correction` block added to the contract for this
  ruling, not by prose the FE would have to parse.
* **The Loader's lines are per ingestion source** (D43, task 34.13). A tenant
  may now have several; "ingestion has stopped" is a statement about one source,
  and rolling them together would hide a dead mailbox behind a healthy Drive
  folder.

Everything here is a query, run when asked
------------------------------------------
D38: ATLAS computes when the user opens the app. There is no clock, no event
hook and no background job in this module -- including for absence ("what should
have arrived and didn't", §2.3). Absence is `_quiet_source_lines()`, a
comparison of two timestamps at read time. D46 records the accepted consequence:
a customer who does not sign in is told nothing, absence included.

What is deliberately not here
-----------------------------
Ranking (§7.3, D30), collapse by area (§2.2/D20, §7.3/D41), the forecast's
levers (§7.5, task 34.9) and cold-start orientation (§7.1, task 34.12) are
Slice C. This module produces the lines; it does not order them, group them or
decide which ones fit on a screen. `atlas_lines()` returns them in skill order
for exactly that reason -- the ordering is not a ranking, and naming it one
would be the second ranking §12.3 warns about.
"""

from __future__ import annotations

from dataclasses import dataclass, field as dc_field
from datetime import date, datetime, timedelta
from decimal import Decimal
from uuid import UUID

from sqlmodel import Session, select

from models import (
    BankStatementLine,
    Invoice,
    TenantAutopilotConfig,
    TenantAutopilotLog,
)
from services.atlas_capabilities import AtlasCapability, GrantSet, visible_to
from services.atlas_contract import (
    Action,
    Certainty,
    Correction,
    Recommendation,
    Reversibility,
    Verify,
    What,
    Why,
    numeric_tokens,
    validate_recommendation,
)
from services.atlas_figures import (
    computed_figure,
    count_reference,
    money_prefix,
    render_amount,
)

__all__ = [
    "SkillContext",
    "auditor_lines",
    "trainer_lines",
    "loader_lines",
    "atlas_lines",
    "cash_position",
    "CashPosition",
]

# ─────────────────────────────────────────────────────────────────────────────
# Thresholds. Named constants, not literals buried in a query — every one of
# these is a number a founder may want to argue with, and an argument needs a
# name to point at.
# ─────────────────────────────────────────────────────────────────────────────

#: Inbound invoices in this state are the Auditor's queue (routers/audit.py).
_AWAITING_AUDIT = ("AUDIT_REQUIRED", "REVIEW_LATER")
#: How far ahead the cash forecast looks. One month is the horizon a payment run
#: is planned over; a longer one is a chart, and §7.5 says never a chart.
_FORECAST_DAYS = 30
#: An extraction field below this is "low confidence" for the Trainer.
_LOW_CONFIDENCE = 0.70
#: An invoice still PROCESSING after this long is stuck, not in flight.
_STUCK_HOURS = 6
#: A source that has ingested nothing for this long is quiet enough to say so.
_QUIET_DAYS = 7
#: Rounding slack when checking an invoice's own arithmetic. Two decimals of
#: currency, not a tolerance for disagreement.
_ARITHMETIC_SLACK = Decimal("0.02")


@dataclass(frozen=True)
class SkillContext:
    """What every skill needs and none of them should look up twice.

    `today` is passed in rather than read from the clock inside each skill, so a
    test can state the date it is asking about and a caller can compute a screen
    "as of" a moment without every query disagreeing by a few milliseconds.
    """

    tenant_id: UUID
    today: date
    #: The currency a tenant-level line speaks when the rows it read carry none.
    #: §7.4: one line, one currency, never a blend -- so a line is emitted per
    #: currency and this is only the fallback for rows with `currency = NULL`.
    default_currency: str = "INR"
    now: datetime = dc_field(default_factory=datetime.utcnow)


# ═════════════════════════════════════════════════════════════════════════════
# Shared reads
# ═════════════════════════════════════════════════════════════════════════════

def _live_invoices(db: Session, ctx: SkillContext, *, flow: str | None = None):
    stmt = select(Invoice).where(
        Invoice.tenant_id == ctx.tenant_id,
        Invoice.deleted_at.is_(None),  # type: ignore[union-attr]
    )
    if flow is not None:
        stmt = stmt.where(Invoice.flow_direction == flow)
    return list(db.exec(stmt).all())


def _numbers_in(text: str) -> list[str]:
    """Every numeric token in a verbatim string, for declaration as references.

    Used only where ATLAS reproduces a string it did not write (an extraction
    alert). It is not a way round `assert_no_undeclared_numbers` -- the check
    still runs, and anything this module *composes* still has to declare its
    numbers as figures with a computation or a document behind them.
    """
    return numeric_tokens(text)


def _currency_of(inv: Invoice, ctx: SkillContext) -> str:
    return (inv.currency or ctx.default_currency).upper()


def _amount(inv: Invoice) -> Decimal:
    return Decimal(str(inv.grand_total or 0))


def _arrived_on(inv: Invoice) -> date | None:
    """When this became work -- `Recommendation.since`, task 34.7f/34.7g.

    `created_at` is when the row appeared here, which is the honest answer to
    "how long has this been sitting with us"; `invoice_date` is when the vendor
    wrote it and would make a month-old invoice uploaded this morning look
    untouched for a month. Nullable in, nullable out: a missing timestamp ranks
    as unknown age rather than as brand new.
    """
    created = getattr(inv, "created_at", None)
    if created is None:
        return None
    return created.date() if isinstance(created, datetime) else created


# ═════════════════════════════════════════════════════════════════════════════
# The Auditor (§2.3) — approvals, and the whole cash picture (D44)
# ═════════════════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class CashPosition:
    """One currency's position, forecast and runway. Deterministic, per D44/§7.4.

    Every field is computed from rows; nothing here is a model's opinion, and
    nothing here blends currencies -- `cash_position()` returns one of these per
    currency rather than one total, because a mixed-currency total is a wrong
    number under §5.3.

    `runway_days` is `None` when it cannot be computed rather than a large
    number meaning "fine": no bank statement means no balance, and "unknown" and
    "comfortable" must never render the same.
    """

    currency: str
    #: Latest balance on this tenant's bank statement lines, if one was imported.
    balance: Decimal | None
    #: INBOUND invoices not yet resolved, due within the horizon.
    payable_due: Decimal
    payable_count: int
    #: OUTBOUND invoices sent and unpaid, due within the horizon.
    receivable_due: Decimal
    receivable_count: int
    horizon_days: int
    #: `balance + receivable_due - payable_due` when a balance is known.
    projected: Decimal | None
    runway_days: int | None
    #: The assumption the forecast rests on, stated (§7.5: "deterministic and
    #: honest are separate properties").
    assumption: str


def cash_position(db: Session, ctx: SkillContext) -> list[CashPosition]:
    """The position, the forecast and the runway, per currency (D44, §7.5).

    Deterministic arithmetic over rows -- CONVENTIONS hard rule 3. An LLM may
    phrase any of this; it may not decide whether the tenant is short.

    **The assumption is part of the answer.** This forecast uses *due dates*, and
    says so on every line it produces. §7.5's better forecast -- what will
    actually arrive, built on each customer's payment behaviour -- is task 34.9
    and is not built here; claiming behaviour-based accuracy from a due-date sum
    would be exactly the "right flag, wrong reason" failure of §5.2.
    """
    horizon = ctx.today + timedelta(days=_FORECAST_DAYS)
    by_currency: dict[str, dict] = {}

    def bucket(currency: str) -> dict:
        return by_currency.setdefault(
            currency,
            {
                "payable": Decimal("0"), "payable_count": 0,
                "receivable": Decimal("0"), "receivable_count": 0,
                "outflow_90": Decimal("0"),
            },
        )

    ninety_days_ago = ctx.today - timedelta(days=90)

    for inv in _live_invoices(db, ctx):
        currency = _currency_of(inv, ctx)
        b = bucket(currency)
        amount = _amount(inv)
        if inv.flow_direction == "INBOUND":
            if inv.status in _AWAITING_AUDIT and inv.due_date and inv.due_date <= horizon:
                b["payable"] += amount
                b["payable_count"] += 1
            # Historical outflow, for the runway denominator: what this tenant
            # actually settled over the last 90 days.
            if inv.status == "PAID" and (inv.invoice_date or ctx.today) >= ninety_days_ago:
                b["outflow_90"] += amount
        elif inv.flow_direction == "OUTBOUND":
            if inv.status == "SENT" and inv.due_date and inv.due_date <= horizon:
                b["receivable"] += amount
                b["receivable_count"] += 1

    balances = _latest_balances(db, ctx)

    positions: list[CashPosition] = []
    for currency, b in sorted(by_currency.items()):
        balance = balances.get(currency)
        projected = (
            balance + b["receivable"] - b["payable"] if balance is not None else None
        )
        runway_days: int | None = None
        if balance is not None and b["outflow_90"] > 0:
            daily_burn = b["outflow_90"] / Decimal(90)
            runway_days = int(balance / daily_burn)
        positions.append(
            CashPosition(
                currency=currency,
                balance=balance,
                payable_due=b["payable"],
                payable_count=b["payable_count"],
                receivable_due=b["receivable"],
                receivable_count=b["receivable_count"],
                horizon_days=_FORECAST_DAYS,
                projected=projected,
                runway_days=runway_days,
                assumption=(
                    "every invoice is settled on its due date, and the runway "
                    "assumes the last 90 days of payments continue"
                ),
            )
        )
    return positions


def _latest_balances(db: Session, ctx: SkillContext) -> dict[str, Decimal]:
    """The closing balance of the most recent statement line, per currency.

    `bank_statement_line` carries no currency column (it is the tenant's own
    bank account), so the balance is attributed to the context's default
    currency and to no other. Attributing one balance to several currencies would
    be the blend §7.4 forbids, done silently.
    """
    rows = list(
        db.exec(
            select(BankStatementLine)
            .where(BankStatementLine.tenant_id == ctx.tenant_id)
            .order_by(BankStatementLine.line_date)  # type: ignore[arg-type]
        ).all()
    )
    latest = next(
        (r for r in reversed(rows) if r.balance is not None),
        None,
    )
    if latest is None or latest.balance is None:
        return {}
    return {ctx.default_currency.upper(): Decimal(str(latest.balance))}


def auditor_lines(db: Session, ctx: SkillContext) -> list[Recommendation]:
    """Everything the `can_audit` grant is for (§2.1, §2.3).

    Two kinds of line, in this order: the invoices waiting on a decision, then
    the cash picture those decisions are made inside (D44).
    """
    lines: list[Recommendation] = []
    lines.extend(_approval_lines(db, ctx))
    lines.extend(_cash_lines(db, ctx))
    return lines


def _approval_lines(db: Session, ctx: SkillContext) -> list[Recommendation]:
    """One line per invoice waiting on an auditor, with what is odd about it.

    `Reversibility.IRREVERSIBLE`: resolving an invoice as PAID can be reopened by
    an Admin (Gap 193), but the payment it authorises cannot be, and D29 grades
    on the consequence rather than on whether a row can be flipped back. With
    D42 in force nothing is batchable in v1 regardless; this is what keeps that
    true if D42 is ever revisited for the reversible line types.
    """
    lines: list[Recommendation] = []
    for inv in _live_invoices(db, ctx, flow="INBOUND"):
        if inv.status not in _AWAITING_AUDIT:
            continue
        currency = _currency_of(inv, ctx)
        amount = _amount(inv)
        rendered = render_amount(amount, currency)
        mark = money_prefix(currency)
        vendor = inv.vendor_name or "an unnamed vendor"
        number = f"#{inv.invoice_number}" if inv.invoice_number else "no invoice number"
        alerts = [str(a) for a in (inv.sa_alerts or [])]

        figures = [
            computed_figure(
                amount, currency, "the invoice total as extracted from the document"
            )
        ]
        # An alert is carried into the doubt **verbatim** -- "Possible duplicate
        # of #4241" is what the pipeline wrote and is what the user must read.
        # Its numbers are declared as references rather than figures, and that is
        # a deliberate, bounded exception worth stating: `sa_alerts` strings are
        # copied character for character out of the invoice's own row, so the
        # failure §5.3 guards against -- prose from a model that rounded -- cannot
        # occur on this path. Rewriting or stripping the alert would be worse: it
        # would either hide the number the alert is about, or turn a verbatim
        # record into ATLAS's paraphrase of one.
        alert_references: list[str] = []
        if alerts:
            doubt = alerts[0] if len(alerts) == 1 else "; ".join(alerts[:3])
            certainty = Certainty.UNCERTAIN
            alert_references = _numbers_in(doubt)
        else:
            doubt = None
            certainty = Certainty.CERTAIN

        why_text = (
            f"{vendor} is waiting on a decision for {mark}{rendered}"
            + (f", due {_day_month(inv.due_date)}" if inv.due_date else "")  # hardcode-ok: a date, not a figure -- `_day_month` renders it and deliberately omits the year
            + "."
        )
        lines.append(
            validate_recommendation(
                Recommendation(
                    id=f"audit-approve-{inv.id}",
                    capability=AtlasCapability.AUDIT,
                    skill="invoice_awaiting_decision",
                    what=What(
                        headline=f"{vendor} {number}",
                        entity_kind="invoice",
                        entity_id=str(inv.id),
                    ),
                    why=Why(
                        text=why_text,
                        figures=figures,
                        references=[number] + alert_references,
                        doubt=doubt,
                    ),
                    action=Action(
                        kind="resolve_invoice",
                        label="Approve",
                        target_id=str(inv.id),
                        params={"status": "PAID"},
                    ),
                    verify=Verify(
                        question=f"Attach {number} here and show me how you read it — is the total right?",  # hardcode-ok: `number` is an invoice identifier declared on `Why.references`, not money
                        document_id=str(inv.id),
                    ),
                    # §7.3 / D30's two terms, stated by the emitter that holds
                    # them rather than inferred by the ranker out of prose. The
                    # money is the invoice's own total; the deadline is its due
                    # date, because after it the decision is late rather than
                    # pending. `since` is when it arrived, which is the aging
                    # figure D20's collapsed row prints.
                    stake=amount,
                    fixable_until=inv.due_date,
                    since=_arrived_on(inv),
                    certainty=certainty,
                    reversibility=Reversibility.IRREVERSIBLE,
                    currency=currency,
                )
            )
        )
    return lines


def _cash_lines(db: Session, ctx: SkillContext) -> list[Recommendation]:
    """The position, forecast and runway — for the Auditor as well (D44).

    One line per currency (§7.4). `AtlasCapability.AUDIT` is the declaration, and
    that single word is the whole of D44's reversal of D2: an Auditor holds
    `can_audit`, an Admin holds every capability, and nobody else sees it.
    """
    lines: list[Recommendation] = []
    for pos in cash_position(db, ctx):
        if pos.payable_count == 0 and pos.receivable_count == 0 and pos.balance is None:
            continue  # nothing known, and a line saying so is noise, not work

        mark = money_prefix(pos.currency)
        figures = [
            computed_figure(
                pos.payable_due,
                pos.currency,
                f"the {pos.payable_count} invoice(s) awaiting a decision and due "
                f"within {pos.horizon_days} days, added up",
            ),
            computed_figure(
                pos.receivable_due,
                pos.currency,
                f"the {pos.receivable_count} invoice(s) sent and unpaid and due "
                f"within {pos.horizon_days} days, added up",
            ),
        ]
        text = (
            f"Over the next {pos.horizon_days} days you are committed to "
            f"{mark}{render_amount(pos.payable_due, pos.currency)} across "
            f"{count_reference(pos.payable_count)} invoice(s), and expecting "
            f"{mark}{render_amount(pos.receivable_due, pos.currency)} across "
            f"{count_reference(pos.receivable_count)}."
        )
        if pos.balance is not None:
            figures.append(
                computed_figure(
                    pos.balance,
                    pos.currency,
                    "the closing balance on the most recent bank statement line imported",
                )
            )
            text += (
                f" Your last imported statement balance is "
                f"{mark}{render_amount(pos.balance, pos.currency)}"  # hardcode-ok: every amount goes through `render_amount()`; `mark` is the currency symbol for that line's own currency
            )
            if pos.projected is not None:
                figures.append(
                    computed_figure(
                        pos.projected,
                        pos.currency,
                        "the statement balance, plus what is expected in, minus "
                        "what is committed out, over the same window",
                    )
                )
                text += (
                    f", which leaves {mark}"
                    f"{render_amount(pos.projected, pos.currency)} at the end of "
                    f"the window"
                )
            text += "."
        if pos.runway_days is not None:
            text += (
                f" At the rate you have been paying, that balance lasts "
                f"{count_reference(pos.runway_days)} days."
            )
        text += f" This assumes {pos.assumption}."

        lines.append(
            validate_recommendation(
                Recommendation(
                    id=f"audit-cash-{pos.currency}",
                    capability=AtlasCapability.AUDIT,
                    skill="cash_position_and_runway",
                    what=What(
                        headline=f"Cash position, next {pos.horizon_days} days",
                        entity_kind="tenant",
                        entity_id=str(ctx.tenant_id),
                    ),
                    why=Why(
                        text=text,
                        figures=figures,
                        references=[
                            count_reference(pos.payable_count),
                            count_reference(pos.receivable_count),
                            count_reference(pos.horizon_days),
                            count_reference(pos.runway_days or 0),
                        ],
                    ),
                    action=Action(
                        kind="open_upcoming_payments",
                        label="Show what is due",
                        target_id=str(ctx.tenant_id),
                        params={"currency": pos.currency, "days": pos.horizon_days},
                    ),
                    verify=Verify(
                        question=(
                            "Which invoices make up this number, and what did you "
                            "assume about when they are paid?"
                        )
                    ),
                    certainty=Certainty.CERTAIN,
                    reversibility=Reversibility.REVERSIBLE,
                    currency=pos.currency,
                )
            )
        )
    return lines


# ═════════════════════════════════════════════════════════════════════════════
# The Trainer (§2.3, D21, D45) — the fix, drafted, with before and after
# ═════════════════════════════════════════════════════════════════════════════

def trainer_lines(db: Session, ctx: SkillContext) -> list[Recommendation]:
    """Extraction that is wrong, ranked by consequence, with the fix drafted.

    Two kinds of line:

    * **A drafted correction** -- the invoice's own arithmetic disagrees with its
      total, so there is a defensible "after" and the line carries the
      before/after pair D45 requires.
    * **A field ATLAS is unsure of** -- no computed replacement exists, so there
      is *no* `Correction` block. A before/after with an invented "after" would
      be worse than no after at all; the ask is to look, not to accept.

    Ranked by consequence is D21's requirement and is implemented as ordering
    here (most-affected vendor first), not as a score on the line: §7.3's ranking
    is task 34.9's and this module does not own it.
    """
    invoices = _live_invoices(db, ctx, flow="INBOUND")
    vendor_volume: dict[str, int] = {}
    for inv in invoices:
        if inv.vendor_name:
            vendor_volume[inv.vendor_name] = vendor_volume.get(inv.vendor_name, 0) + 1

    lines: list[Recommendation] = []
    for inv in invoices:
        lines.extend(_arithmetic_correction(inv, ctx, vendor_volume))
        lines.extend(_low_confidence_fields(inv, ctx))

    # Consequence first: a fix on the vendor ATLAS sees most often is worth more
    # than a one-off, which is exactly what D21 asks for.
    lines.sort(key=lambda r: -int(r.action.params.get("vendor_invoice_count", 0)))
    return lines


def _line_items_total(inv: Invoice) -> Decimal | None:
    """What the printed line items add up to, or None if they cannot be read.

    Returns None rather than 0 when no item carries a readable amount: "the
    items add up to nothing" and "there are no readable items" are different
    claims, and only one of them is ever true here.
    """
    total = Decimal("0")
    seen = False
    for item in inv.items or []:
        if not isinstance(item, dict):
            continue
        raw = item.get("total") or item.get("amount") or item.get("line_total")
        if raw is None:
            continue
        try:
            total += Decimal(str(raw))
            seen = True
        except (ArithmeticError, ValueError):
            continue
    return total if seen else None


def _arithmetic_correction(
    inv: Invoice, ctx: SkillContext, vendor_volume: dict[str, int]
) -> list[Recommendation]:
    """The invoice's own numbers disagree — before and after, on the line (D45).

    Deterministic per hard rule 3: the disagreement is arithmetic, and the
    proposed "after" is the sum of what the document itself prints, never a
    guess. Tax and discount are added back before comparing, because a total that
    legitimately includes them is not a defect.
    """
    if inv.grand_total is None:
        return []
    items_total = _line_items_total(inv)
    if items_total is None:
        return []

    tax = Decimal(str(inv.tax_amount or 0))
    discount = Decimal(str(inv.discount_amount or 0))
    expected = items_total + tax - discount
    stated = _amount(inv)
    if abs(expected - stated) <= _ARITHMETIC_SLACK:
        return []

    currency = _currency_of(inv, ctx)
    mark = money_prefix(currency)
    vendor = inv.vendor_name or "an unnamed vendor"
    number = f"#{inv.invoice_number}" if inv.invoice_number else "no invoice number"
    count = vendor_volume.get(inv.vendor_name or "", 1)

    figures = [
        computed_figure(stated, currency, "the invoice total as extracted"),
        computed_figure(
            expected,
            currency,
            "the printed line items added up, plus tax, less discount",
        ),
    ]
    return [
        validate_recommendation(
            Recommendation(
                id=f"train-arithmetic-{inv.id}",
                capability=AtlasCapability.TRAIN,
                skill="invoice_total_disagrees_with_its_items",
                what=What(
                    headline=f"{vendor} {number} does not add up",
                    entity_kind="invoice",
                    entity_id=str(inv.id),
                ),
                why=Why(
                    text=(
                        f"The total was read as {mark}{render_amount(stated, currency)}, "  # hardcode-ok: every amount goes through `render_amount()`; `mark` is the currency symbol for that line's own currency
                        f"but the printed line items add up to "
                        f"{mark}{render_amount(expected, currency)}. This vendor has "
                        f"{count_reference(count)} invoice(s) here, so the same fix "
                        f"applies to every one that follows."
                    ),
                    figures=figures,
                    references=[number, count_reference(count)],
                ),
                action=Action(
                    kind="apply_field_correction",
                    label="Correct the total",
                    target_id=str(inv.id),
                    params={
                        "field": "grand_total",
                        "value": str(expected),
                        "vendor_invoice_count": count,
                    },
                ),
                verify=Verify(
                    question=(
                        f"Attach {number} here and show me the line items you "
                        f"added up and how you got to the total."
                    ),
                    document_id=str(inv.id),
                ),
                correction=Correction(
                    field_label="Invoice total",
                    field_name="grand_total",
                    before_rendered=render_amount(stated, currency),
                    after_rendered=render_amount(expected, currency),
                ),
                # §7.3: the money at stake on a correction is the size of the
                # ERROR, not the size of the invoice. A wrong total on a small
                # invoice is a small problem, and ranking it by the invoice
                # would push every large invoice's tiny rounding slip above a
                # genuinely wrong small one. No deadline: a wrong extraction
                # does not expire, it just keeps teaching the wrong thing.
                stake=abs(expected - stated),
                since=_arrived_on(inv),
                certainty=Certainty.CERTAIN,
                reversibility=Reversibility.REVERSIBLE,
                currency=currency,
            )
        )
    ]


def _low_confidence_fields(inv: Invoice, ctx: SkillContext) -> list[Recommendation]:
    """A field the extractor was unsure of. No `Correction` — there is no after."""
    confidences = inv.field_confidence or {}
    if not isinstance(confidences, dict):
        return []
    weak = sorted(
        (
            (name, float(score))
            for name, score in confidences.items()
            if isinstance(score, (int, float)) and float(score) < _LOW_CONFIDENCE
        )
    )
    if not weak:
        return []

    vendor = inv.vendor_name or "an unnamed vendor"
    number = f"#{inv.invoice_number}" if inv.invoice_number else "no invoice number"
    names = ", ".join(name for name, _ in weak[:3])
    return [
        validate_recommendation(
            Recommendation(
                id=f"train-lowconf-{inv.id}",
                capability=AtlasCapability.TRAIN,
                skill="low_confidence_fields",
                what=What(
                    headline=f"{vendor} {number}: check {names}",
                    entity_kind="invoice",
                    entity_id=str(inv.id),
                ),
                why=Why(
                    text=(
                        f"These fields were read from a part of the document the "
                        f"extractor could not see clearly: {names}. Teaching it here "
                        f"fixes this vendor's layout, not just this invoice."
                    ),
                    references=[number],
                    doubt=(
                        "I am not confident I read these fields correctly — the "
                        "document did not read cleanly there."
                    ),
                ),
                action=Action(
                    kind="open_field_review",
                    label="Check these fields",
                    target_id=str(inv.id),
                    params={"fields": [name for name, _ in weak]},
                ),
                verify=Verify(
                    question=f"Attach {number} here and show me where you read {names} from.",
                    document_id=str(inv.id),
                ),
                # No `stake`: there is no computable error size here, and the
                # invoice total would be the wrong number -- the same reasoning
                # that keeps `Correction` off this line (§14.3). `None` ranks it
                # below any line that states money, which is D30 read literally.
                since=_arrived_on(inv),
                certainty=Certainty.UNCERTAIN,
                reversibility=Reversibility.REVERSIBLE,
                currency=_currency_of(inv, ctx),
            )
        )
    ]


# ═════════════════════════════════════════════════════════════════════════════
# The Loader (§2.3, D13, D22, D43) — per ingestion source
# ═════════════════════════════════════════════════════════════════════════════

#: The fix, not the fault (§2.3/D22). Matched on the error text a failed
#: ingestion actually records; the fallback names the source and asks for the
#: file, which is still an action rather than a complaint.
_FIX_FOR_ERROR = (
    ("quota", "This is the free-tier limit, not the file. It retries itself after "
              "the monthly refill, or immediately on a paid plan."),
    ("token", "The connection to this source needs reconnecting in Settings → Connectors."),
    ("auth", "The connection to this source needs reconnecting in Settings → Connectors."),
    ("permission", "Share the folder with the connected account, then run the source again."),
    ("unsupported", "This file type cannot be read. Re-save it as a PDF and drop it back in the folder."),
    ("too large", "The image is larger than the reader accepts. Re-save it smaller and drop it back in."),
)


def _fix_for(error_detail: str | None) -> str:
    text = (error_detail or "").lower()
    for needle, fix in _FIX_FOR_ERROR:
        if needle in text:
            return fix
    return "Open the file from the source and upload it here directly, and I will read it."


def _day_month(value: date | datetime | None) -> str:
    """"12 September" — a readable date with **no year**, deliberately.

    A bare four-digit year is money-shaped under the contract's rule, so "due in
    2026" in prose would raise `InventedNumberError` unless declared as a
    reference. Dates inside a 30-day horizon do not need a year to be
    unambiguous, and leaving it off removes the trap rather than working around
    it. Anything that genuinely needs a year declares it.
    """
    if value is None:
        return "an unknown date"
    if isinstance(value, datetime):
        value = value.date()
    return f"{value.day} {value.strftime('%B')}"  # hardcode-ok: month name from strftime, no number formatting involved


def loader_lines(db: Session, ctx: SkillContext) -> list[Recommendation]:
    """Stuck vs in flight, the fix not the fault, and what did not arrive — per source.

    D43/task 34.13 is what makes "per source" possible: before it, a tenant had
    one ingestion source by database constraint. Every line here names the source
    it is about, because "ingestion has stopped" is a statement about one source
    and a tenant with two would otherwise read a healthy Drive folder as
    reassurance about a dead mailbox.
    """
    sources = list(
        db.exec(
            select(TenantAutopilotConfig)
            .where(TenantAutopilotConfig.tenant_id == ctx.tenant_id)
            .order_by(TenantAutopilotConfig.created_at)  # type: ignore[arg-type]
        ).all()
    )
    logs = list(
        db.exec(
            select(TenantAutopilotLog).where(
                TenantAutopilotLog.tenant_id == ctx.tenant_id
            )
        ).all()
    )

    lines: list[Recommendation] = []
    for source in sources:
        mine = [log for log in logs if log.source_config_id == source.id]
        lines.extend(_failed_ingestion_lines(source, mine, ctx))
        lines.extend(_quiet_source_lines(source, mine, ctx))
    lines.extend(_stuck_invoice_lines(db, ctx))
    return lines


def _source_label(source: TenantAutopilotConfig) -> str:
    kind = {"gdrive": "Google Drive folder"}.get(source.source_type, source.source_type)
    return f"{kind} {source.source_ref}"


def _failed_ingestion_lines(
    source: TenantAutopilotConfig,
    logs: list[TenantAutopilotLog],
    ctx: SkillContext,
) -> list[Recommendation]:
    """Files this source could not bring in, each with what to do about it."""
    failures = [log for log in logs if log.status == "FAILED"]
    if not failures:
        return []
    newest = max(failures, key=lambda log: log.ingested_at)
    label = _source_label(source)
    names = ", ".join(
        sorted({log.source_file_name or log.source_file_id for log in failures})[:3]
    )
    return [
        validate_recommendation(
            Recommendation(
                id=f"load-failed-{source.id}",
                capability=AtlasCapability.LOAD,
                skill="ingestion_failures_by_source",
                what=What(
                    headline=f"{len(failures)} file(s) did not load from {label}",
                    entity_kind="ingestion_source",
                    entity_id=str(source.id),
                ),
                why=Why(
                    text=(
                        f"{count_reference(len(failures))} file(s) in this source "
                        f"failed to load, most recently {names} on "
                        f"{_day_month(newest.ingested_at)}. {_fix_for(newest.error_detail)}"
                    ),
                    references=[count_reference(len(failures))],
                ),
                action=Action(
                    kind="retry_ingestion_source",
                    label="Try this source again",
                    target_id=str(source.id),
                    params={"source_config_id": str(source.id)},
                ),
                verify=Verify(
                    question=(
                        "What exactly did this source report when the file was "
                        "refused?"
                    )
                ),
                certainty=Certainty.CERTAIN,
                reversibility=Reversibility.REVERSIBLE,
                currency=ctx.default_currency,
            )
        )
    ]


def _quiet_source_lines(
    source: TenantAutopilotConfig,
    logs: list[TenantAutopilotLog],
    ctx: SkillContext,
) -> list[Recommendation]:
    """What should have arrived and didn't (§2.3) — as a query, never a clock.

    D38: this is computed when someone opens the app, and D46 records the price
    of that honestly -- a source that stops feeding while nobody signs in is
    noticed on the next visit and not before.
    """
    successes = [log for log in logs if log.status == "SUCCESS"]
    last_seen = max((log.ingested_at for log in successes), default=None)
    reference = last_seen or source.created_at
    quiet_for = (ctx.now - reference).days
    if quiet_for < _QUIET_DAYS:
        return []

    label = _source_label(source)
    since = (
        f"Nothing has arrived since {_day_month(last_seen)}"
        if last_seen
        else "Nothing has ever arrived from it"
    )
    return [
        validate_recommendation(
            Recommendation(
                id=f"load-quiet-{source.id}",
                capability=AtlasCapability.LOAD,
                skill="ingestion_source_has_gone_quiet",
                what=What(
                    headline=f"{label} has gone quiet",
                    entity_kind="ingestion_source",
                    entity_id=str(source.id),
                ),
                why=Why(
                    text=(
                        f"{since} — {count_reference(quiet_for)} days. Either the "
                        f"invoices stopped coming, or this source stopped reaching "
                        f"them; running it now tells you which."
                    ),
                    references=[count_reference(quiet_for)],
                    doubt=(
                        "A quiet source and a quiet month look identical from here "
                        "— I cannot tell them apart without running it."
                    ),
                ),
                action=Action(
                    kind="retry_ingestion_source",
                    label="Run this source now",
                    target_id=str(source.id),
                    params={"source_config_id": str(source.id)},
                ),
                verify=Verify(
                    question="When did this source last bring anything in, and what was it?"
                ),
                certainty=Certainty.UNCERTAIN,
                reversibility=Reversibility.REVERSIBLE,
                currency=ctx.default_currency,
            )
        )
    ]


def _stuck_invoice_lines(db: Session, ctx: SkillContext) -> list[Recommendation]:
    """Stuck vs in flight (§2.3/D22) — the distinction the Loader actually needs.

    An invoice that has been PROCESSING for minutes is in flight and is not work.
    One that has been PROCESSING for hours is stuck, and saying so is the whole
    job. Not attributed to a source: an invoice carries a `batch_id`, and a batch
    reaches the tenant through any of the doors (upload, email, connector), so
    claiming a source here would be a guess where the honest line is tenant-wide.
    """
    cutoff = ctx.now - timedelta(hours=_STUCK_HOURS)
    stuck = [
        inv
        for inv in _live_invoices(db, ctx)
        if inv.status == "PROCESSING" and (inv.last_enqueued_at or inv.created_at) < cutoff
    ]
    if not stuck:
        return []
    return [
        validate_recommendation(
            Recommendation(
                id=f"load-stuck-{ctx.tenant_id}",
                capability=AtlasCapability.LOAD,
                skill="invoices_stuck_in_processing",
                what=What(
                    headline=f"{len(stuck)} invoice(s) stuck in processing",
                    entity_kind="tenant",
                    entity_id=str(ctx.tenant_id),
                ),
                why=Why(
                    text=(
                        f"{count_reference(len(stuck))} invoice(s) have been "
                        f"processing for more than {count_reference(_STUCK_HOURS)} "
                        f"hours, which is long past normal. They are not lost — they "
                        f"need putting back in the queue."
                    ),
                    references=[
                        count_reference(len(stuck)),
                        count_reference(_STUCK_HOURS),
                    ],
                ),
                action=Action(
                    kind="requeue_invoices",
                    label="Put these back in the queue",
                    target_id=str(ctx.tenant_id),
                    params={"invoice_ids": [str(inv.id) for inv in stuck]},
                ),
                verify=Verify(
                    question="Which invoices are stuck, and when did each of them arrive?"
                ),
                certainty=Certainty.CERTAIN,
                reversibility=Reversibility.REVERSIBLE,
                currency=ctx.default_currency,
            )
        )
    ]


# ═════════════════════════════════════════════════════════════════════════════
# The three together
# ═════════════════════════════════════════════════════════════════════════════

def atlas_lines(
    db: Session, ctx: SkillContext, grants: GrantSet
) -> list[Recommendation]:
    """Every line this caller may act on (§2.1).

    Filtered through `visible_to()`, which **drops** rather than annotates: a
    greyed-out row still leaks the vendor, the amount and the fact that something
    is wrong with it. A caller with no grants gets `[]` -- D3, falling out of the
    per-line test rather than being special-cased here.

    The order is skill order, not a ranking (§7.3 / task 34.9). Recon
    (`atlas_recon`) and the doubt checks (`atlas_doubt`) are not called from here
    because both need something from outside the database -- an attached
    statement, and the set of witness documents held -- and inventing those
    inputs to make one tidy entry point is how a contract starts lying.
    """
    lines = auditor_lines(db, ctx) + trainer_lines(db, ctx) + loader_lines(db, ctx)
    return visible_to(lines, grants)
