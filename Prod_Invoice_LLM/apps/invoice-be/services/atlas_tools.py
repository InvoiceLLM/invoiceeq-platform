"""Feature 35 (ATLAS Intelligence) task 35.1 — the read-only tool registry.

Spec: `docs/feature_35_atlas_intelligence.md` §2, §3.2.

What this module is. Eleven thin adapters (the original ten, plus `invoices`
from BE Gap 716) over Feature 34's deterministic services and the invoice rows
themselves, plus the registry that decides which of them a caller's model is even
*told* about. Nothing here computes: every number a row carries was produced by
a Feature 34 function and rendered by `services/atlas_figures.py`. There is no
arithmetic in this file, by design and by CONVENTIONS hard rule 3 — the model
phrases what the services decided, and a figure it cannot get from a tool is a
figure it may not state.

Three properties this file exists to hold:

* **Absent, not refused.** `tools_for()` filters by `GrantSet` *before* the
  schema list reaches the model, exactly as `atlas_capabilities.visible_to()`
  drops rather than annotates a line. A Trainer's model is never shown
  `cash_position`, so it cannot ask for it, so there is no refusal to explain
  and no capability to infer from the shape of one.
* **Every row is citable.** Each row carries `record_kind`, `record_id`,
  `tenant_id` and `as_of`, and `run_tool()` records the non-empty ids on the
  run. Task 35.4's guard compares a paragraph's citations against exactly that
  set, so a row that reached the model but carried no id cannot be cited —
  which is the rule `orientation` relies on (it is comprehension, not evidence,
  so its rows carry no id at all).
* **Read-only.** No adapter writes an ATLAS row. The one qualification is
  `ask_sage`, which calls `routers/chat.py::run_sync_chat_turn()` as a plain
  function (Feature 34 §17.3's precedent) and that function persists the chat
  turn it runs — a chat write, not an ATLAS write, and the same rows a user
  would have created by asking SAGE the question themselves. It is capped at
  one call per briefing (§8 ruling 3) inside `run_tool()`, not inside the
  adapter, so the cap cannot be walked past by calling the adapter directly.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field as dc_field
from datetime import date
from typing import Any, Callable, Iterable
from uuid import UUID

from sqlmodel import Session, select

from services.atlas_capabilities import AtlasCapability, GrantSet
from services.atlas_figures import render_amount
from services.atlas_skills import SkillContext

logger = logging.getLogger(__name__)

__all__ = [
    "BriefingRun",
    "ToolContext",
    "ToolResult",
    "ToolSpec",
    "TOOL_REGISTRY",
    "tools_for",
    "tool_schemas",
    "run_tool",
    "tool_list_lines",
    "tool_invoices",
    "tool_cash_position",
    "tool_forecast",
    "tool_vendor_baseline",
    "tool_doubts",
    "tool_reconcile",
    "tool_action_log",
    "tool_memory_rules",
    "tool_orientation",
    "tool_ask_sage",
]

#: How many invoices one `doubts` call will look at. The router caps the same
#: read for the same reason; a tool the model can aim at one invoice does not
#: need a wider one.
_ACTION_LOG_DEFAULT = 20

#: The title an ATLAS-initiated SAGE turn is filed under. One session per
#: tenant+user, reused, so a month of briefings does not leave a month of empty
#: chat sessions behind.
_SAGE_SESSION_TITLE = "ATLAS briefing"


# ═════════════════════════════════════════════════════════════════════════════
# The run, the context, and what a tool call produces
# ═════════════════════════════════════════════════════════════════════════════

@dataclass
class BriefingRun:
    """The mutable state of one briefing, shared by every tool call in it.

    `emitted_ids` is the whole point: task 35.4's guard drops a paragraph whose
    citations name anything outside it, so "the model may only speak about what
    a tool actually returned this run" is a set membership test rather than a
    prompt rule (hard rule 3).

    `sage_calls` is carried here rather than in `run_tool()`'s frame because the
    cap is per *briefing*, not per call site.
    """

    tenant_id: UUID
    user_id: str
    emitted_ids: set[str] = dc_field(default_factory=set)
    #: `{tool, args, ms, rows, refused}` per dispatch, in order. Stored on the
    #: briefing row by task 35.6 and read by the loop's invocation cap.
    tool_calls: list[dict] = dc_field(default_factory=list)
    sage_calls: int = 0

    # ── Task 35.4/35.5 additions ────────────────────────────────────────────
    #: Every numeric token any tool put in front of the model this run, by
    #: `atlas_contract.rendered_tokens_of()`'s definition. The companion of
    #: `emitted_ids`: that set decides what may be *cited*, this one decides what
    #: may be *stated*, and both are populated here rather than in the loop so a
    #: paragraph cannot be checked against numbers the model was never shown.
    rendered_tokens: set[str] = dc_field(default_factory=set)
    #: The deployment the loop actually called, recorded by `run_briefing()`.
    model: str = ""
    tokens_in: int = 0
    tokens_out: int = 0
    cost_usd: float = 0.0
    #: Paragraphs and questions the 35.5 guards removed. §3.3's `done` event
    #: reports it, so a dropped paragraph is visible rather than merely absent.
    dropped: int = 0
    #: `"rounds"` | `"invocations"` | `"wall_clock"` once a cap was hit.
    truncated: str | None = None


@dataclass(frozen=True)
class ToolContext:
    """Everything an adapter may read, resolved once per request.

    Frozen, and it carries `grants` rather than re-deriving them: the grants a
    request resolved are the grants every tool in it runs under, and a tool that
    could widen them would make `tools_for()`'s filter decorative.
    """

    db: Session
    skill: SkillContext
    grants: GrantSet
    #: The caller, as `AtlasDismissal.user_id` spells it (a string, not a UUID).
    user_id: str = ""
    #: Reused by `ask_sage` when set, so a caller that already owns a session
    #: (a test, a future route) does not get a second one created for it.
    sage_session_id: UUID | None = None


@dataclass(frozen=True)
class ToolResult:
    """One dispatch: the rows, how long it took, and why it refused if it did."""

    tool: str
    rows: list[dict]
    ms: int
    #: Set when the call produced no evidence: unknown tool, missing argument,
    #: a second `ask_sage`, or the wrapped service raising. Never `None` and a
    #: populated `rows` at the same time.
    refused: str | None = None

    @property
    def row_count(self) -> int:
        return len(self.rows)


@dataclass(frozen=True)
class ToolSpec:
    """One tool as the model sees it, and the callable behind it.

    `capability` is what a caller must hold for this tool to appear at all.
    `None` means "no capability of its own": the tool either filters itself
    (`list_lines` goes through `visible_to()` inside `atlas_lines()`) or follows
    the caller's existing access to the matching endpoint (§3.2).
    """

    name: str
    description: str
    #: JSON-schema `properties` for the arguments. Empty for a no-argument tool.
    parameters: dict[str, Any]
    required: tuple[str, ...]
    capability: AtlasCapability | None
    adapter: Callable[["ToolContext", dict], list[dict]]

    def schema(self) -> dict:
        """The OpenAI function-calling shape `bind_tools()` accepts."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": dict(self.parameters),
                    "required": list(self.required),
                },
            },
        }


# ═════════════════════════════════════════════════════════════════════════════
# Row construction — the four fields every row carries, in one place
# ═════════════════════════════════════════════════════════════════════════════

def _row(ctx: ToolContext, kind: str, record_id: Any, **fields: Any) -> dict:
    """One JSON row. The four identity fields are written last, deliberately.

    An adapter cannot shadow `record_id` with a field of its own by accident:
    whatever it passes in `fields` is overwritten by the identity block, so the
    thing a citation points at is always the thing `run_tool()` recorded.
    """
    row: dict[str, Any] = dict(fields)
    row["record_kind"] = kind
    row["record_id"] = "" if record_id is None else str(record_id)
    row["tenant_id"] = str(ctx.skill.tenant_id)
    row["as_of"] = ctx.skill.today.isoformat()
    return row


def _figures(line) -> list[dict]:
    """A line's figures as the user already reads them (§5.3).

    `rendered` and nothing else: `Figure.value` is for arithmetic, and handing a
    model the unformatted Decimal invites it to reformat one, which is how a
    figure a user can check becomes one they cannot.
    """
    return [
        {"rendered": f.rendered, "currency": f.currency, "source": f.source.value}
        for f in line.why.figures
    ]


def _alerts_by_invoice(ctx: ToolContext) -> dict[str, dict]:
    """Every live invoice's `sa_alerts` messages, keyed by invoice id — BE Gap 716.

    The pipeline already decided this invoice is a possible duplicate, or that
    its tax does not add up, and wrote the sentence a person reads into
    `sa_alerts`. Until this gap that sentence stopped at the work screen: the
    tool rows carried a ranked headline about the invoice and not the thing the
    system had already concluded about it, so the model wrote about RAJ-2009 as
    an ordinary approval.

    `_alert_prose()` is imported from `services.atlas_skills` rather than
    reimplemented: the message is the content and the envelope is plumbing (BE
    Gap 704), and two functions disagreeing about that shape is exactly how the
    dict repr reached the screen the first time. Verbatim in, verbatim out —
    nothing here paraphrases, because a paraphrased alert is ATLAS's opinion of
    an alert.

    **BE Gap 717: each entry now also carries whether the alert is still open.**
    `{"messages": [...], "alert_open": bool}` rather than a bare list. The
    pipeline never clears `sa_alerts`, so a PAID invoice keeps the sentence it
    was once flagged with, and the briefing was repeating those as live
    findings. Whether the sentence is still an open one is `alert_is_open()`'s
    answer about the invoice's status -- imported from `atlas_skills`, which
    holds the one status list (hard rule 3: this is a correctness rule, so it is
    code with a single source, not a second list that drifts).
    """
    from services.atlas_skills import _alert_prose, _live_invoices, alert_is_open

    out: dict[str, dict] = {}
    for inv in _live_invoices(ctx.db, ctx.skill):
        messages = [prose for a in (inv.sa_alerts or []) if (prose := _alert_prose(a))]
        if messages:
            out[str(inv.id)] = {
                "messages": messages,
                "alert_open": alert_is_open(inv.status),
            }
    return out


# ═════════════════════════════════════════════════════════════════════════════
# The adapters
# ═════════════════════════════════════════════════════════════════════════════

def tool_list_lines(ctx: ToolContext, args: dict) -> list[dict]:
    """Every line on this caller's work screen, ranked, dismissals removed.

    The chain is §3.2's: `atlas_lines()` (capability-filtered inside) →
    `drop_dismissed()` → `rank()` → `collapse()`. Forecast and doubt lines are
    deliberately *not* folded in here even though the router adds them to
    `GET /atlas/lines`: they have tools of their own, and a model that got them
    from two places would cite the same shortfall twice.

    **BE Gap 716: the row now also carries `doubt` and `alerts`.** `why.doubt` is
    where `_approval_lines()` puts the invoice's own alert message, and the
    invoice's `sa_alerts` are what the pipeline concluded before any ranking
    happened. Both are copied character for character; neither is composed here.
    """
    from services.atlas_collapse import (
        capabilities_worked_by_others,
        collapse,
        group_work_by_capability,
    )
    from services.atlas_dismissals import dismissed_ids, drop_dismissed
    from services.atlas_ranking import rank
    from services.atlas_skills import atlas_lines

    dismissed = dismissed_ids(ctx.db, ctx.skill.tenant_id, ctx.user_id)
    lines = rank(
        drop_dismissed(atlas_lines(ctx.db, ctx.skill, ctx.grants), dismissed),
        ctx.skill.today,
    )

    alerts_by_invoice = _alerts_by_invoice(ctx)
    rows = [
        _row(
            ctx,
            "recommendation",
            line.id,
            skill=line.skill,
            capability=line.capability.value,
            headline=line.what.headline,
            entity_kind=line.what.entity_kind,
            entity_id=line.what.entity_id,
            why=line.why.text,
            # BE Gap 716: verbatim, both of them. `doubt` is the line's own
            # uncertainty (the alert message, where the line came from one);
            # `alerts` is what the pipeline recorded on the invoice itself, and
            # it is empty for a line whose entity is not an invoice.
            doubt=line.why.doubt,
            alerts=(
                alerts_by_invoice.get(str(line.what.entity_id), {}).get("messages", [])
                if line.what.entity_kind == "invoice"
                else []
            ),
            # BE Gap 717. `True` only while the invoice is in a status this repo
            # holds for a person to look at; a PAID invoice's old alert text is
            # still carried (provenance is not hidden) and is simply not an open
            # alert. False for a line whose entity is not an invoice, and for an
            # invoice carrying no alert at all.
            alert_open=(
                bool(
                    alerts_by_invoice.get(str(line.what.entity_id), {}).get(
                        "alert_open", False
                    )
                )
                if line.what.entity_kind == "invoice"
                else False
            ),
            figures=_figures(line),
            action=line.action.kind,
            certainty=line.certainty.value,
            currency=line.currency,
        )
        for line in lines
    ]

    held_by_others = (
        capabilities_worked_by_others(
            ctx.db,
            ctx.skill.tenant_id,
            exclude_user_id=ctx.user_id,
            line_ids_by_capability={
                capability: [line.id for line in group]
                for capability, group in group_work_by_capability(lines).items()
            },
            now=ctx.skill.now,
        )
        if ctx.grants.is_admin
        else set()
    )
    for area in collapse(
        lines, ctx.grants, held_by_others=held_by_others, today=ctx.skill.today
    ):
        rows.append(
            _row(
                ctx,
                "collapsed_area",
                # Not a stored row, so it has no id of its own. Composed from
                # the capability it stands for, which is unique within a run and
                # is what a citation about "the rest of the audit queue" means.
                "area-" + area.capability.value,
                label=area.label,
                count=area.count,
                untouched=area.untouched,
                age_unknown=area.age_unknown,
                reason=area.reason,
                headline=area.headline,
                line_ids=list(area.line_ids),
            )
        )
    return rows


def tool_invoices(ctx: ToolContext, args: dict) -> list[dict]:
    """Every live invoice this tenant holds, inbound and outbound — BE Gap 716.

    **Why this tool exists.** Every other adapter wraps Feature 34's
    *recommendation* layer, which is a ranked opinion about a subset of the
    records. An invoice that no skill emits a line for was therefore invisible:
    VPI-OUT-2014 is OUTBOUND, NEEDS_REVIEW and carries a `tax_mismatch` alert —
    the only arithmetic defect in that tenant's 26 invoices — and no row from any
    tool carried its id, so the model could not have cited it had it wanted to.
    `_approval_lines()` is inbound-only by design, and `forecast` carries
    outbound ids inside a *field* rather than as a `record_id`. This tool is the
    record, not the opinion: one row per invoice, every one of them citable.

    **It computes nothing.** The amount is rendered by `atlas_figures`, the
    alerts are `_alert_prose()`'s verbatim messages, and the low-confidence field
    list is the extractor's own keys tested against `atlas_skills._LOW_CONFIDENCE`
    — the same threshold the Trainer's lines use, read from there rather than
    restated here (hard rule 3). There is no total, no count and no comparison.

    **Visibility: `can_audit` or Admin.** A Trainer and a Loader do not get it,
    and that is not squeamishness about volume: the whole ledger with every
    party, amount and status is the audit surface (`AtlasCapability.AUDIT`), and
    a Trainer's job is the fields on the documents they are correcting. §3.2's
    rule is absent-not-refused, so they are never told it exists.

    **What it does not handle:** a tenant with thousands of live invoices puts
    all of them in one context window. There is no `limit` argument, because a
    silently truncated ledger is worse than a slow one — the bound to add, when
    there is a tenant that needs it, is a filter the model states (flow, status,
    a date range), not a cut-off it cannot see.
    """
    from services.atlas_skills import (
        _LOW_CONFIDENCE,
        _alert_prose,
        _live_invoices,
        alert_is_open,
    )

    def _sort_key(inv):
        # Soonest-due first, undated last, then the stored number so the order is
        # stable across runs and a test is not asserting a database's scan order.
        return (inv.due_date is None, inv.due_date or date.max, inv.invoice_number or "")

    rows = []
    for inv in sorted(_live_invoices(ctx.db, ctx.skill), key=_sort_key):
        currency = (inv.currency or ctx.skill.default_currency).upper()
        confidences = inv.field_confidence if isinstance(inv.field_confidence, dict) else {}
        rows.append(
            _row(
                ctx,
                "invoice",
                inv.id,
                invoice_number=inv.invoice_number,
                party=inv.vendor_name or inv.customer_name,
                flow=inv.flow_direction,
                invoice_date=(
                    inv.invoice_date.isoformat() if inv.invoice_date else None
                ),
                due_date=(inv.due_date.isoformat() if inv.due_date else None),
                # `None`, never `0.00`: an invoice still in extraction has no
                # total, and a zero there is a bill this business does not owe.
                amount=(
                    None
                    if inv.grand_total is None
                    else render_amount(inv.grand_total, currency)
                ),
                currency=currency,
                status=inv.status,
                alerts=[
                    prose for a in (inv.sa_alerts or []) if (prose := _alert_prose(a))
                ],
                # BE Gap 717: the text is kept whatever the status -- an
                # auditor reading a settled invoice should still see what was
                # once said about it -- and this flag is what says whether
                # anybody still owes a decision on it.
                alert_open=alert_is_open(inv.status),
                low_confidence_fields=sorted(
                    name
                    for name, score in confidences.items()
                    if isinstance(score, (int, float))
                    and not isinstance(score, bool)
                    and float(score) < _LOW_CONFIDENCE
                ),
            )
        )
    return rows


def tool_cash_position(ctx: ToolContext, args: dict) -> list[dict]:
    """The position, the forecast horizon and the runway, per currency (D44).

    Deviation from the spec's row description, stated rather than papered over:
    §3.2 says the rows carry "the invoice ids summed". `CashPosition` does not
    return them — it returns the counts — and re-querying the invoices here to
    manufacture ids would be new compute in a feature that adds none. The counts
    are what the service produced, so the counts are what the rows carry.
    """
    from services.atlas_skills import cash_position

    rows = []
    for position in cash_position(ctx.db, ctx.skill):
        rows.append(
            _row(
                ctx,
                "cash_position",
                "cash-" + position.currency,
                currency=position.currency,
                balance=(
                    None
                    if position.balance is None
                    else render_amount(position.balance, position.currency)
                ),
                payable_due=render_amount(position.payable_due, position.currency),
                payable_count=position.payable_count,
                receivable_due=render_amount(
                    position.receivable_due, position.currency
                ),
                receivable_count=position.receivable_count,
                horizon_days=position.horizon_days,
                projected=(
                    None
                    if position.projected is None
                    else render_amount(position.projected, position.currency)
                ),
                runway_days=position.runway_days,
                assumption=position.assumption,
            )
        )
    return rows


def tool_forecast(ctx: ToolContext, args: dict) -> list[dict]:
    """The first short day per currency, with its levers and the invoices behind them."""
    from services.atlas_forecast import forecast_recommendations, shortfalls

    found = shortfalls(ctx.db, ctx.skill)
    by_currency = {s.currency: s for s in found}

    rows = []
    for line in forecast_recommendations(
        found, tenant_id=ctx.skill.tenant_id, today=ctx.skill.today
    ):
        shortfall = by_currency.get(line.currency)
        rows.append(
            _row(
                ctx,
                "shortfall",
                line.id,
                currency=line.currency,
                headline=line.what.headline,
                why=line.why.text,
                figures=_figures(line),
                on_date=(None if shortfall is None else shortfall.on_date.isoformat()),
                levers=(
                    []
                    if line.forecast is None
                    else [
                        {
                            "kind": lever.kind,
                            "label": lever.label,
                            "target_id": lever.target_id,
                            "rendered": lever.amount_rendered,
                            "currency": line.currency,
                        }
                        for lever in line.forecast.levers
                    ]
                ),
                chaseable_invoice_ids=(
                    []
                    if shortfall is None
                    else [str(inv.id) for inv in shortfall.chaseable]
                ),
                deferrable_invoice_ids=(
                    []
                    if shortfall is None
                    else [str(inv.id) for inv in shortfall.deferrable]
                ),
                already_expected_invoice_ids=(
                    []
                    if shortfall is None
                    else [str(inv.id) for inv in shortfall.already_expected]
                ),
            )
        )
    return rows


def tool_vendor_baseline(ctx: ToolContext, args: dict) -> list[dict]:
    """What this vendor has historically billed, computed now and thrown away (D39)."""
    from services.atlas_doubt import vendor_baseline

    vendor = str(args.get("vendor") or "").strip()
    currency = (str(args.get("currency") or "") or ctx.skill.default_currency).upper()
    baseline = vendor_baseline(
        ctx.db, ctx.skill.tenant_id, vendor, currency=currency
    )
    return [
        _row(
            ctx,
            "vendor_baseline",
            "baseline-" + vendor + "-" + currency,
            vendor=baseline.vendor_name,
            currency=baseline.currency,
            invoice_count=baseline.invoice_count,
            low=render_amount(baseline.low, baseline.currency),
            high=render_amount(baseline.high, baseline.currency),
            median=render_amount(baseline.median, baseline.currency),
            is_established=baseline.is_established,
        )
    ]


def tool_doubts(ctx: ToolContext, args: dict) -> list[dict]:
    """§3.3's claim / witness / verdict, for one invoice.

    Returns every doubt including the silent checks, the way
    `doubts_for_invoice()` does: the model is reading the working, not deciding
    which of it a user sees.
    """
    from models import Invoice
    from services.atlas_doubt import doubts_for_invoice

    invoice_id = str(args.get("invoice_id") or "").strip()
    invoice = ctx.db.exec(
        select(Invoice).where(
            Invoice.id == UUID(invoice_id),
            Invoice.tenant_id == ctx.skill.tenant_id,
            Invoice.deleted_at.is_(None),  # type: ignore[union-attr]
        )
    ).first()
    if invoice is None:
        return []

    rows = []
    for index, doubt in enumerate(
        doubts_for_invoice(
            ctx.db,
            ctx.skill.tenant_id,
            invoice,
            default_currency=ctx.skill.default_currency,
        )
    ):
        rows.append(
            _row(
                ctx,
                "doubt",
                "doubt-" + str(invoice.id) + "-" + doubt.claim.kind.value + "-" + str(index),
                invoice_id=str(doubt.invoice_id),
                claim_kind=doubt.claim.kind.value,
                claim_field=doubt.claim.field,
                currency=doubt.claim.currency,
                witness=doubt.witness.value,
                verdict=doubt.verdict.value,
                working=doubt.working,
            )
        )
    return rows


def tool_reconcile(ctx: ToolContext, args: dict) -> list[dict]:
    """A vendor statement against our ledger — the five groups, as ids (§3.2).

    The same reads `POST /atlas/recon` does, with its refusals kept: a document
    that names no vendor and a statement with no readable amount both produce no
    rows rather than a guessed comparison.
    """
    from models import Document
    from services.atlas_recon import (
        ledger_lines_for_vendor,
        reconcile,
        statement_lines_from_items,
    )

    document_id = str(args.get("document_id") or "").strip()
    document = ctx.db.exec(
        select(Document).where(
            Document.id == UUID(document_id),
            Document.tenant_id == ctx.skill.tenant_id,
            Document.deleted_at.is_(None),  # type: ignore[union-attr]
        )
    ).first()
    if document is None:
        return []

    vendor = str(
        args.get("vendor")
        or document.counterparty_name
        or document.party_name
        or ""
    ).strip()
    if not vendor:
        return []

    currency = (document.currency or "").strip().upper() or ctx.skill.default_currency
    statement_lines, unreadable = statement_lines_from_items(
        document.items, currency=currency
    )
    if not statement_lines:
        return []

    result = reconcile(
        statement_lines,
        ledger_lines_for_vendor(ctx.db, ctx.skill.tenant_id, vendor),
        vendor_name=vendor,
        currency=currency,
    )

    def _statement(line) -> dict:
        return {
            "invoice_number": line.invoice_number,
            "rendered": render_amount(line.amount, line.currency),
            "currency": line.currency,
        }

    def _ledger(line) -> dict:
        return {
            "invoice_id": str(line.invoice_id),
            "invoice_number": line.invoice_number,
            "rendered": render_amount(line.amount, line.currency),
            "currency": line.currency,
        }

    rows = [
        _row(
            ctx,
            "recon_result",
            "recon-" + str(document.id),
            document_id=str(document.id),
            vendor=result.vendor_name,
            currency=result.currency,
            agrees=result.agrees,
            unreadable_rows=unreadable,
            matched=[_ledger(pair.ledger) for pair in result.matched],
            they_show_we_do_not=[_statement(l) for l in result.they_show_we_do_not],
            we_show_they_do_not=[_ledger(l) for l in result.we_show_they_do_not],
            unmatchable=[_statement(l) for l in result.unmatchable],
        )
    ]
    for difference in result.amount_differs:
        rows.append(
            _row(
                ctx,
                "recon_row",
                "recon-differs-" + str(difference.ledger.invoice_id),
                document_id=str(document.id),
                invoice_id=str(difference.ledger.invoice_id),
                invoice_number=difference.ledger.invoice_number,
                currency=result.currency,
                theirs=render_amount(
                    difference.statement.amount, difference.statement.currency
                ),
                ours=render_amount(difference.ledger.amount, difference.ledger.currency),
                # Rendered by the same helper, never re-derived here: the
                # difference is `AmountDifference`'s own property (hard rule 3).
                difference=render_amount(difference.difference, result.currency),
            )
        )
    return rows


def tool_action_log(ctx: ToolContext, args: dict) -> list[dict]:
    """What ATLAS did in this tenant, newest first. Tenant-wide, per §5.3."""
    from services.atlas_actions import recent_actions

    raw_limit = args.get("limit", _ACTION_LOG_DEFAULT)
    try:
        limit = int(raw_limit)
    except (TypeError, ValueError):
        limit = _ACTION_LOG_DEFAULT

    return [
        _row(
            ctx,
            "action",
            action.id,
            action_kind=action.action_kind,
            recommendation_id=action.recommendation_id,
            target_id=action.target_id,
            succeeded=action.succeeded,
            summary=action.summary,
            performed_by=str(action.user_id or ""),
            performed_at=(
                action.performed_at.isoformat()
                if getattr(action, "performed_at", None)
                else None
            ),
        )
        for action in recent_actions(ctx.db, ctx.skill.tenant_id, limit)
    ]


def tool_memory_rules(ctx: ToolContext, args: dict) -> list[dict]:
    """Every lesson ATLAS holds about this business, inactive ones included (§7.2)."""
    from services.atlas_memory import list_rules

    return [
        _row(
            ctx,
            "rule",
            rule.id,
            text=getattr(rule, "text", None),
            source=getattr(rule, "source", None),
            active=getattr(rule, "active", None),
            created_at=(
                rule.created_at.isoformat()
                if getattr(rule, "created_at", None)
                else None
            ),
        )
        for rule in list_rules(ctx.db, ctx.skill.tenant_id)
    ]


def tool_orientation(ctx: ToolContext, args: dict) -> list[dict]:
    """§7.1's orientation. **Carries no record ids, on purpose.**

    Orientation is comprehension, not evidence (§3.2), so its rows are emitted
    with an empty `record_id` and `run_tool()` records nothing from them. A
    paragraph whose only citation is orientation therefore names an id that was
    never emitted, and task 35.5's guard drops it — the rule is enforced by the
    absence of an id, not by a sentence in a prompt.
    """
    from services.atlas_orientation import orientation

    result = orientation(ctx.db, ctx.skill.tenant_id, ctx.grants)
    return [
        _row(
            ctx,
            "orientation",
            "",
            needed=result.needed,
            capabilities=list(result.capabilities),
            key=part.key,
            title=part.title,
            body=part.body,
        )
        for part in result.parts
    ]


def tool_ask_sage(ctx: ToolContext, args: dict) -> list[dict]:
    """One question to SAGE, answered by the real chat turn (§3.2).

    `run_sync_chat_turn()` is called as a plain function, the way Feature 34
    §17.3 calls `resolve_audit_invoice()`. It persists the turn it runs — the
    same two chat rows a user asking the question themselves would create — so
    the briefing's question and its answer are auditable in the chat history
    rather than invisible. The one-per-run cap lives in `run_tool()`.
    """
    from models import ChatSession
    from routers.chat import run_sync_chat_turn

    question = str(args.get("question") or "").strip()
    if not question:
        return []

    session_id = ctx.sage_session_id
    if session_id is None:
        existing = ctx.db.exec(
            select(ChatSession).where(
                ChatSession.tenant_id == ctx.skill.tenant_id,
                ChatSession.user_id == (ctx.user_id or None),
                ChatSession.title == _SAGE_SESSION_TITLE,
            )
        ).first()
        if existing is None:
            existing = ChatSession(
                tenant_id=ctx.skill.tenant_id,
                user_id=ctx.user_id or None,
                title=_SAGE_SESSION_TITLE,
            )
            ctx.db.add(existing)
            ctx.db.commit()
            ctx.db.refresh(existing)
        session_id = existing.id

    message = run_sync_chat_turn(
        session_id=session_id,
        content=question,
        tenant_id=ctx.skill.tenant_id,
        db_session=ctx.db,
        actor_role="atlas",
    )
    return [
        _row(
            ctx,
            "sage_answer",
            message.id,
            question=question,
            answer=getattr(message, "content", None),
            generated_sql=getattr(message, "generated_sql", None),
            invoice_ids=[
                str(i) for i in (getattr(message, "result_invoice_ids", None) or [])
            ],
        )
    ]


# ═════════════════════════════════════════════════════════════════════════════
# The registry
# ═════════════════════════════════════════════════════════════════════════════

_SPECS: tuple[ToolSpec, ...] = (
    ToolSpec(
        name="list_lines",
        description=(
            "Every recommendation on this person's work screen right now, ranked, "
            "with the ones they have dismissed removed. Start here."
        ),
        parameters={},
        required=(),
        capability=None,  # `atlas_lines()` filters itself through `visible_to()`.
        adapter=tool_list_lines,
    ),
    ToolSpec(
        name="invoices",
        description=(
            "Every invoice this workspace holds right now, money they owe and money "
            "owed to them, with what the system already flagged on each one: the "
            "alerts it raised, the fields it was unsure of, the status it is in, "
            "and when it is due. An invoice's alert is the fact about it. "
            "`alert_open` says whether that alert is still waiting on a person: "
            "false means the invoice has moved on and the text is history."
        ),
        parameters={},
        required=(),
        # BE Gap 716. The whole ledger is the audit surface, so `can_audit` (and
        # therefore Admin, whom `holds()` answers True for) sees it; a Trainer or
        # a Loader is never told it exists.
        capability=AtlasCapability.AUDIT,
        adapter=tool_invoices,
    ),
    ToolSpec(
        name="cash_position",
        description=(
            "The bank balance, what is payable and receivable inside the horizon, "
            "and the runway, one row per currency."
        ),
        parameters={},
        required=(),
        capability=AtlasCapability.ADMIN,
        adapter=tool_cash_position,
    ),
    ToolSpec(
        name="forecast",
        description=(
            "The first day each currency goes short, by how much, the levers that "
            "would cover it, and the invoices behind each lever."
        ),
        parameters={},
        required=(),
        capability=AtlasCapability.ADMIN,
        adapter=tool_forecast,
    ),
    ToolSpec(
        name="vendor_baseline",
        description=(
            "What one vendor has historically billed in one currency: how many "
            "invoices, the lowest, the highest and the median."
        ),
        parameters={
            "vendor": {"type": "string", "description": "The vendor name as it is stored."},
            "currency": {
                "type": "string",
                "description": "ISO 4217 code. Defaults to the workspace currency.",
            },
        },
        required=("vendor",),
        capability=AtlasCapability.AUDIT,
        adapter=tool_vendor_baseline,
    ),
    ToolSpec(
        name="doubts",
        description=(
            "The checkable claims on one invoice, which witness would settle each, "
            "and the verdict, with the working already written out."
        ),
        parameters={
            "invoice_id": {"type": "string", "description": "The invoice's uuid."},
        },
        required=("invoice_id",),
        capability=AtlasCapability.AUDIT,
        adapter=tool_doubts,
    ),
    ToolSpec(
        name="reconcile",
        description=(
            "Compare an attached vendor statement against our ledger: what matched, "
            "what only they show, what only we show, and where the amounts differ."
        ),
        parameters={
            "document_id": {"type": "string", "description": "The statement document's uuid."},
            "vendor": {
                "type": "string",
                "description": "Whose statement it is. Defaults to the document's own party.",
            },
        },
        required=("document_id",),
        capability=AtlasCapability.AUDIT,
        adapter=tool_reconcile,
    ),
    ToolSpec(
        name="action_log",
        description="What ATLAS has done in this workspace, newest first.",
        parameters={
            "limit": {"type": "integer", "description": "How many rows, at most 200."},
        },
        required=(),
        capability=None,
        adapter=tool_action_log,
    ),
    ToolSpec(
        name="memory_rules",
        description="Every lesson this workspace has taught ATLAS, active or not.",
        parameters={},
        required=(),
        capability=None,
        adapter=tool_memory_rules,
    ),
    ToolSpec(
        name="orientation",
        description=(
            "What ATLAS does for the capabilities this person holds. Background, "
            "not evidence: it carries no record ids and cannot be cited."
        ),
        parameters={},
        required=(),
        capability=None,
        adapter=tool_orientation,
    ),
    ToolSpec(
        name="ask_sage",
        description=(
            "Ask SAGE one question about this workspace's invoice data. Available "
            "once per briefing, so ask the question that decides something."
        ),
        parameters={
            "question": {"type": "string", "description": "One question, in plain English."},
        },
        required=("question",),
        capability=None,
        adapter=tool_ask_sage,
    ),
)

TOOL_REGISTRY: dict[str, ToolSpec] = {spec.name: spec for spec in _SPECS}


def tools_for(grants: GrantSet) -> list[ToolSpec]:
    """The tools this caller may use — filtered before the model is told anything.

    Absent, not refused (§3.2). `GrantSet.holds()` already answers True for
    every capability when `is_admin` is set, so the Admin superset needs no
    special case here, and an Admin-only tool is one that names
    `AtlasCapability.ADMIN`, which `holds()` grants to nobody else.
    """
    return [
        # Iterated off `TOOL_REGISTRY`, not the `_SPECS` tuple it was built
        # from, so the registry is the single source: `run_tool()`'s own
        # visibility re-check and this filter can never disagree about what
        # exists, and a test that swaps one spec's adapter swaps it for both.
        spec
        for spec in TOOL_REGISTRY.values()
        if spec.capability is None or grants.holds(spec.capability)
    ]


def tool_schemas(grants: GrantSet) -> list[dict]:
    """`tools_for()` as the JSON schema list handed to `bind_tools()`."""
    return [spec.schema() for spec in tools_for(grants)]


def _refusal(ctx: ToolContext, tool: str, reason: str, started: float) -> ToolResult:
    """A refusal is a result, not an exception.

    The loop must keep going: a model that asked for something it cannot have
    should be told so in a row it can read, not have the briefing die. The row
    carries the same four identity fields as any other and an empty
    `record_id`, so nothing about a refusal is citable.
    """
    return ToolResult(
        tool=tool,
        rows=[_row(ctx, "refusal", "", tool=tool, reason=reason)],
        ms=int((time.monotonic() - started) * 1000),
        refused=reason,
    )


def run_tool(
    name: str, args: dict | None, ctx: ToolContext, run: BriefingRun
) -> ToolResult:
    """Dispatch one tool call: visibility, arguments, timing, and the emitted ids.

    Four things happen here and nowhere else, so none of them can be bypassed by
    calling an adapter directly:

    1. **Visibility is re-checked.** `tools_for()` already kept the schema out of
       the model's hands; this repeats the test, because a model that invents a
       tool name it was never given must not reach the service behind it.
    2. **`ask_sage` is capped at one call per run** (§8 ruling 3). The counter
       increments on the accepted call only, so a failed SAGE turn does not
       silently spend the budget.
    3. **Every non-empty `record_id` lands in `run.emitted_ids`**, which is the
       set task 35.5's citation guard tests against.
    4. **A raising service becomes a refusal row**, logged. One tool failing is
       not a reason for a briefing to produce nothing.
    """
    started = time.monotonic()
    arguments = dict(args or {})
    spec = TOOL_REGISTRY.get(name)

    if spec is None or spec not in tools_for(ctx.grants):
        result = _refusal(ctx, name, "no such tool is available to you", started)
    else:
        missing = [key for key in spec.required if not str(arguments.get(key) or "").strip()]
        if missing:
            result = _refusal(
                ctx, name, "missing required argument: " + ", ".join(missing), started
            )
        elif name == "ask_sage" and run.sage_calls >= 1:
            result = _refusal(
                ctx,
                name,
                "SAGE has already been asked once in this briefing; one question per briefing",
                started,
            )
        else:
            if name == "ask_sage":
                run.sage_calls += 1
            try:
                rows = spec.adapter(ctx, arguments)
                result = ToolResult(
                    tool=name,
                    rows=list(rows),
                    ms=int((time.monotonic() - started) * 1000),
                )
            except Exception as exc:  # pragma: no cover - exercised by the stub test
                logger.warning(
                    "ATLAS tool %s failed for tenant %s", name, ctx.skill.tenant_id,
                    exc_info=True,
                )
                result = _refusal(ctx, name, "that tool failed: " + str(exc), started)

    _record(run, arguments, result)
    return result


def _record(run: BriefingRun, args: dict, result: ToolResult) -> None:
    """Add the result's ids and figures to the run, and log the call (§4).

    A refusal row contributes neither: its `record_id` is empty by construction,
    and its prose is an explanation rather than evidence, so nothing in it may
    license a number in the briefing.
    """
    from services.atlas_contract import rendered_tokens_of

    for row in result.rows:
        record_id = str(row.get("record_id") or "")
        if record_id:
            run.emitted_ids.add(record_id)
        if not result.refused:
            run.rendered_tokens |= rendered_tokens_of(row)
    run.tool_calls.append(
        {
            "tool": result.tool,
            "args": dict(args),
            "ms": result.ms,
            "rows": result.row_count,
            "refused": result.refused,
        }
    )


def emitted_ids_of(rows: Iterable[dict]) -> set[str]:
    """The citable ids in a row set. Used by tests and by task 35.4's assertions."""
    return {str(r.get("record_id") or "") for r in rows if str(r.get("record_id") or "")}
