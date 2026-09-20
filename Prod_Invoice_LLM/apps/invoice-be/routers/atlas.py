"""Feature 34 (ATLAS) — the HTTP surface the work screen reads.

Spec: `docs/feature_34_atlas.md` §15 (this router's two envelopes) · §12.2 (the
`Recommendation` contract this serves verbatim) · §14 (the skills behind it).
Filed as **BE Gap 691**: Slices A and B built `services/atlas_skills.py`,
`atlas_recon.py` and `atlas_doubt.py` and **nothing in `routers/` exposed any of
them**, so every recommendation ATLAS could produce was unreachable by a
browser. FE Feature 23 is built against this module.

What this router does, and what it deliberately does not
--------------------------------------------------------
It **reads**. `GET /atlas/lines` returns the lines the caller may act on and
`POST /atlas/recon` compares an attached vendor statement against our ledger.
Neither writes anything.

The **action** endpoints -- `resolve_invoice`, `apply_field_correction`,
`retry_ingestion_source` and the rest of §14.6's dispatch vocabulary -- are
still Slice C and are still absent. That is not an oversight: inventing them
here would be §12.2's seam ("a field the FE reads that the BE never emits")
facing the other way. The FE renders `action.label` and dispatches on
`action.kind`; a kind with no endpoint behind it is a button the FE knows it
cannot yet perform, which is a visible, testable state rather than a 404 at the
worst moment.

Three rules this module keeps
-----------------------------
1. **No new auth path.** `get_tenant_context` is the same dependency every other
   product route uses, and `GrantSet.from_context()` reads the grants that
   request already resolved through `RoleMapper.resolve_permissions()`. There is
   no ATLAS-specific permission check anywhere in this file.
2. **Absent, not disabled** (§2.1). Filtering is `visible_to()`'s, inside
   `atlas_lines()`; a line the caller lacks the capability for never reaches the
   response, so it cannot leak through a field the FE forgets to honour.
3. **A dismissed line never reaches the response** (D49). The dismissal store
   is consulted **before the response is assembled**, in this router, which is
   the one place every line-producing path passes through -- the skills, the
   §3.3 doubt asks and the recon lines alike. It **drops**, exactly like
   `visible_to()`: a dismissed line is not in the payload, not flagged in it.
   The FE filters nothing (FE §3), so anything on the wire is on the screen.
4. **Every line is validated on the way out.** `validate_recommendation()` runs
   again here, after the skills have already run it, because this is the last
   point before the wire: a line that blends currencies or prints an undeclared
   number must fail loudly here rather than render on a screen. A failure is a
   500 naming the line id -- **never a dropped line**, because silently dropping
   it would hide the defect the check exists to find.

Cost, stated (§13.5)
--------------------
D38 puts every computation on the open-the-app path. The doubt checks (§3.3) are
per invoice, so this router runs them over the audit queue only and over at most
`_DOUBT_INVOICE_CAP` of it. That cap is a stated limit, not a silent truncation:
the response carries `doubt_checks_run` and `doubt_checks_skipped` so a screen
that is missing checks can say so instead of looking complete.
"""

from __future__ import annotations

import json
import logging
from datetime import date, datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlmodel import Session, select

from agents.atlas_agent import run_briefing
from agents.atlas_prompts import welcome_for
from dependencies import TenantContext, get_db_session, get_tenant_context
from models import Document, Invoice
from services.atlas_actions import (
    ACTION_DISPOSITIONS,
    PERFORMABLE_ACTION_KINDS,
    SUGGEST_ONLY_ACTION_KINDS,
    ActionFailed,
    ActionNotPerformable,
    ActionNotPermitted,
    UnknownActionKind,
    perform_action,
    recent_actions,
    record_action,
)
from services.atlas_capabilities import AtlasCapability, GrantSet, visible_to
from services.atlas_collapse import (
    capabilities_worked_by_others,
    collapse,
    group_work_by_capability,
)
from services.atlas_ranking import RANK_CUT, rank
from services.atlas_contract import (
    AtlasContractError,
    BriefingEvent,
    CurrencyBlendError,
    Recommendation,
    validate_recommendation,
)
from services.atlas_dismissals import dismiss, dismissed_ids, drop_dismissed
from services.atlas_forecast import forecast_recommendations, shortfalls
from services.atlas_briefing_cache import (
    get_cached as cached_briefing,
    invalidate as invalidate_briefing,
    replay_events,
    store as store_briefing,
)
from services.atlas_memory import (
    RuleSource,
    add_rule,
    delete_rule,
    edit_rule,
    list_rules,
    noise_suggestions,
    report_missed,
)
from services.atlas_orientation import orientation, tenant_has_history
from services.atlas_doubt import doubt_recommendations, doubts_for_invoice, witnesses_held
from services.atlas_figures import render_amount
from services.atlas_recon import (
    ReconResult,
    ledger_lines_for_vendor,
    recon_recommendations,
    reconcile,
    statement_lines_from_items,
)
from services.atlas_skills import SkillContext, atlas_lines
from services.atlas_tools import BriefingRun, ToolContext
from utils.llm import get_llm_for_role

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/atlas", tags=["ATLAS"])

#: The two inbound statuses that make an invoice the Auditor's (routers/audit.py).
_AWAITING_AUDIT = ("AUDIT_REQUIRED", "REVIEW_LATER")

#: How many awaiting-audit invoices the §3.3 doubt checks run over per request.
#: §13.5 names "is check-time derivation fast enough for thousands of invoices"
#: as a build-time unknown to be answered by measurement; this is the bound that
#: keeps the unknown from becoming a timeout, and the response says when it bit.
_DOUBT_INVOICE_CAP = 50


# ─────────────────────────────────────────────────────────────────────────────
# Envelopes. Spec §15 owns these names; FE Feature 23 references them.
# ─────────────────────────────────────────────────────────────────────────────

class AtlasLinesResponse(BaseModel):
    """The work screen's whole payload.

    `ungranted` is a field rather than an inference the client makes from
    `len(lines) == 0`, because D3's empty state ("No tasks assigned. Ask your
    admin for access.") and an empty queue ("nothing needs you right now") are
    different sentences and a client that guessed between them would tell a busy
    Auditor they have no access on the one morning they are clear.
    """

    ungranted: bool
    #: The `AtlasCapability` values this caller holds, as wire strings. Sent so
    #: the screen can name what it is showing -- never so it can filter, which
    #: already happened server-side (§2.1).
    capabilities: list[str]
    #: **Ranked** since task 34.7f -- money at stake x how soon it stops being
    #: fixable (§7.3, D30). Every line the caller may act on is here, in that
    #: order; nothing is withheld because of its rank.
    lines: list[Recommendation]
    doubt_checks_run: int
    doubt_checks_skipped: int
    #: How many lines are above the fold (§7.3, D30). **A display hint, not a
    #: truncation** -- `lines` is complete, and "ATLAS ranks; it does not hide"
    #: is only true if what is below the cut is in the same payload. A client
    #: that ignored this field would show everything, which is the safe failure.
    rank_cut: int = RANK_CUT
    #: §2.2 / D20 and §7.3 / D41: the Admin's view of work other grant-holders
    #: are handling, one row per area, with its aging figure. Empty for anyone
    #: who is not an Admin, and empty for a solo owner under the volume
    #: threshold. **The lines these rows stand for are still in `lines`** --
    #: this groups, it does not remove, which is what makes a row openable in
    #: place with no second request.
    areas: list["AreaRow"] = Field(default_factory=list)


class AreaRow(BaseModel):
    """One collapsed area (§2.2, D20) — "Corrections — 34 pending, 3 untouched".

    `line_ids` point into this same response's `lines`. That is the whole shape
    of "openable in place": the client expands a row using what it already has,
    so a collapsed area can never be a view of work the payload does not
    contain.
    """

    capability: str
    label: str
    #: Pieces of **work**, not lines: `len(line_ids)` can legitimately exceed it
    #: when ATLAS has two things to say about one invoice. See
    #: `services/atlas_collapse.py` on what real data found here.
    count: int
    untouched: int
    age_unknown: int
    reason: str
    headline: str
    line_ids: list[str]


AtlasLinesResponse.model_rebuild()


class ReconRequest(BaseModel):
    """Attach this statement and compare it (§3.2, §6)."""

    #: A `documents` row id -- the vendor statement, already ingested and
    #: extracted. Not an upload: this router does not accept files, and the
    #: ingestion path that produces a `Document` is unchanged.
    document_id: UUID
    #: Optional override for whose statement it is. Used when the extraction did
    #: not name a party; never used to override a name it did read.
    vendor_name: str | None = None


class ReconRow(BaseModel):
    """One row of one group, already rendered (§2: no arithmetic client-side).

    Every amount is a string the server formatted. The FE prints it and does
    nothing else to it -- there is no `value` on this model on purpose, because a
    number a client can add up is a number a client will eventually add up.
    """

    invoice_number: str | None = None
    invoice_id: str | None = None
    amount_rendered: str
    #: Present only on the `amount_differs` group: theirs, ours, and the gap.
    theirs_rendered: str | None = None
    ours_rendered: str | None = None
    difference_rendered: str | None = None


class ReconGroups(BaseModel):
    """§6's four groups, plus what could not be read.

    `unmatchable` is kept beside the four rather than folded into
    "they show and we do not", which would manufacture a finding about the vendor
    out of a column our extraction could not read.
    """

    matched: list[ReconRow] = Field(default_factory=list)
    they_show_we_do_not: list[ReconRow] = Field(default_factory=list)
    we_show_they_do_not: list[ReconRow] = Field(default_factory=list)
    amount_differs: list[ReconRow] = Field(default_factory=list)
    unmatchable: list[ReconRow] = Field(default_factory=list)


class ReconResponse(BaseModel):
    vendor_name: str
    currency: str
    document_id: str
    agrees: bool
    groups: ReconGroups
    #: Rows of the attached statement that carried no amount at all, so could not
    #: be compared. Reported rather than dropped.
    unreadable_rows: int
    #: The recon as work (§1) -- `recon_recommendations()`, capability-filtered
    #: like every other line. Empty when the statement agrees: agreement is not
    #: work (§14.4).
    lines: list[Recommendation]


# ─────────────────────────────────────────────────────────────────────────────
# GET /atlas/lines
# ─────────────────────────────────────────────────────────────────────────────

def _validated(lines: list[Recommendation]) -> list[Recommendation]:
    """The boundaries, run once more at the wire (§5.3).

    Fails the request rather than the line. A line that cannot pass its own
    contract is a backend defect, and returning the other nineteen would let it
    sit unnoticed behind a screen that looks fine.
    """
    out: list[Recommendation] = []
    for line in lines:
        try:
            out.append(validate_recommendation(line))
        except AtlasContractError as exc:
            logger.error("ATLAS line %s failed its own contract: %s", line.id, exc)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"ATLAS line {line.id} failed its own contract: {exc}",
            ) from exc
    return out


@router.get("/lines", response_model=AtlasLinesResponse)
def get_atlas_lines(
    context: TenantContext = Depends(get_tenant_context),
    db: Session = Depends(get_db_session),
) -> AtlasLinesResponse:
    """Every recommendation this caller may act on, computed now (D38).

    No cache, no job, no clock: ATLAS speaks when the app is opened (D36), so
    this is where it speaks.
    """
    grants = GrantSet.from_context(context)
    if grants.is_ungranted():
        # D3, and the reason the flag is on the envelope: zero lines because you
        # hold no grants is a different answer from zero lines because you are
        # clear, and the screen says so.
        return AtlasLinesResponse(
            ungranted=True,
            capabilities=[],
            lines=[],
            doubt_checks_run=0,
            doubt_checks_skipped=0,
        )

    ctx = SkillContext(tenant_id=context.tenant_id, today=date.today())

    # D49, read once and applied to every producer below. Fetched before any
    # line is built so the filter is the last thing between a producer and the
    # response, and a dismissed line costs nothing downstream of it.
    dismissed = dismissed_ids(db, context.tenant_id, context.user_id)

    lines = drop_dismissed(atlas_lines(db, ctx, grants), dismissed)

    # Task 34.9 (§7.5, D15). Emitted here rather than inside `atlas_lines()`
    # because `services/atlas_forecast.py` reads the skills module lazily to
    # avoid a cycle, and a producer that imports its caller is a worse shape than
    # one more call at the one place every producer already passes through.
    # `AtlasCapability.AUDIT` is declared on the line (D44), so `visible_to()`
    # decides the audience exactly as it does for every other line.
    forecast_lines = visible_to(
        forecast_recommendations(
            shortfalls(db, ctx), tenant_id=ctx.tenant_id, today=ctx.today
        ),
        grants,
    )
    lines.extend(drop_dismissed(forecast_lines, dismissed))

    doubt_lines, checked, skipped = _doubt_lines(db, ctx, grants)
    # The doubt asks are lines too: a dismissed "attach the quotation" must not
    # come back on the next open either.
    lines.extend(drop_dismissed(doubt_lines, dismissed))

    # Task 34.7f. **Ranked after filtering and dismissal, never before**: a line
    # the caller cannot act on or has already handled must not take a place in
    # the order, and `visible_to()` preserves order precisely so that the filter
    # does not quietly become a second ranking (§12.3).
    lines = rank(_validated(lines), ctx.today)

    # Task 34.7g. Computed from the ranked list, and it removes nothing from it.
    areas = collapse(
        lines,
        grants,
        held_by_others=(
            capabilities_worked_by_others(
                db,
                context.tenant_id,
                exclude_user_id=context.user_id,
                # The same grouping `collapse()` will use, computed once and
                # handed over: "which lines are in this area" must have one
                # answer, or the row's reason and the row's contents describe
                # two different sets.
                line_ids_by_capability={
                    capability: [line.id for line in group]
                    for capability, group in group_work_by_capability(lines).items()
                },
                now=ctx.now,
            )
            if grants.is_admin
            # The query is skipped entirely for a non-Admin, because `collapse()`
            # returns [] for them anyway and a read nobody uses is a read on
            # D38's open-the-app path that costs everyone.
            else set()
        ),
        today=ctx.today,
    )

    return AtlasLinesResponse(
        ungranted=False,
        capabilities=sorted(c.value for c in grants.capabilities()),
        lines=lines,
        doubt_checks_run=checked,
        doubt_checks_skipped=skipped,
        rank_cut=RANK_CUT,
        areas=[
            AreaRow(
                capability=area.capability.value,
                label=area.label,
                count=area.count,
                untouched=area.untouched,
                age_unknown=area.age_unknown,
                reason=area.reason,
                headline=area.headline,
                line_ids=area.line_ids,
            )
            for area in areas
        ],
    )


def _doubt_lines(
    db: Session, ctx: SkillContext, grants: GrantSet
) -> tuple[list[Recommendation], int, int]:
    """§3.3's asks, for the invoices a decision is actually pending on.

    `atlas_lines()` does not call these (§14, and it says why: the doubt checks
    need the set of witness documents held, which is outside the skills' own
    reads). A request *can* answer that, once, so the router does -- and passes
    the answer in, rather than letting each invoice re-query it.

    Only the audit queue is checked. A doubt about an invoice that is already
    resolved is an ask about a decision nobody is making.
    """
    if not grants.holds(AtlasCapability.AUDIT):
        return [], 0, 0

    candidates = list(
        db.exec(
            select(Invoice)
            .where(
                Invoice.tenant_id == ctx.tenant_id,
                Invoice.deleted_at.is_(None),  # type: ignore[union-attr]
                Invoice.flow_direction == "INBOUND",
                Invoice.status.in_(_AWAITING_AUDIT),  # type: ignore[union-attr]
            )
            .order_by(Invoice.created_at.desc())  # type: ignore[union-attr]
        ).all()
    )
    checked = candidates[:_DOUBT_INVOICE_CAP]
    skipped = len(candidates) - len(checked)

    held = witnesses_held(db, ctx.tenant_id)
    lines: list[Recommendation] = []
    for invoice in checked:
        doubts = doubts_for_invoice(
            db,
            ctx.tenant_id,
            invoice,
            held=held,
            default_currency=ctx.default_currency,
        )
        lines.extend(
            doubt_recommendations(
                invoice, doubts, default_currency=ctx.default_currency
            )
        )
    return visible_to(lines, grants), len(checked), skipped


# ─────────────────────────────────────────────────────────────────────────────
# POST /atlas/recon
# ─────────────────────────────────────────────────────────────────────────────

def _rendered_groups(result: ReconResult) -> ReconGroups:
    """The four groups as strings, so the client never formats a number."""
    currency = result.currency
    return ReconGroups(
        matched=[
            ReconRow(
                invoice_number=pair.statement.invoice_number,
                invoice_id=str(pair.ledger.invoice_id),
                amount_rendered=render_amount(pair.ledger.amount, currency),
            )
            for pair in result.matched
        ],
        they_show_we_do_not=[
            ReconRow(
                invoice_number=row.invoice_number,
                amount_rendered=render_amount(row.amount, currency),
            )
            for row in result.they_show_we_do_not
        ],
        we_show_they_do_not=[
            ReconRow(
                invoice_number=row.invoice_number,
                invoice_id=str(row.invoice_id),
                amount_rendered=render_amount(row.amount, currency),
            )
            for row in result.we_show_they_do_not
        ],
        amount_differs=[
            ReconRow(
                invoice_number=diff.statement.invoice_number,
                invoice_id=str(diff.ledger.invoice_id),
                amount_rendered=render_amount(diff.ledger.amount, currency),
                theirs_rendered=render_amount(diff.statement.amount, currency),
                ours_rendered=render_amount(diff.ledger.amount, currency),
                difference_rendered=render_amount(diff.difference, currency),
            )
            for diff in result.amount_differs
        ],
        unmatchable=[
            ReconRow(
                invoice_number=row.invoice_number,
                amount_rendered=render_amount(row.amount, currency),
            )
            for row in result.unmatchable
        ],
    )


@router.post("/recon", response_model=ReconResponse)
def post_atlas_recon(
    payload: ReconRequest,
    context: TenantContext = Depends(get_tenant_context),
    db: Session = Depends(get_db_session),
) -> ReconResponse:
    """Compare an attached vendor statement against our ledger (§3.2, 34.4).

    Every refusal below is a stated one. The alternative to refusing is guessing
    a vendor, a currency or an invoice number, and a guess here is reported to a
    user as a reconciliation result -- which §5.2 says costs trust that does not
    come back.
    """
    document: Document | None = db.exec(
        select(Document).where(
            Document.id == payload.document_id,
            Document.tenant_id == context.tenant_id,
            Document.deleted_at.is_(None),  # type: ignore[union-attr]
        )
    ).first()
    # 404 and not 403 on another tenant's id, the same way routers/documents.py
    # answers: a 403 confirms the row exists.
    if document is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Document not found"
        )

    vendor = (
        payload.vendor_name
        or document.counterparty_name
        or document.party_name
        or ""
    ).strip()
    if not vendor:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                "This statement does not name the vendor it is from, so there is "
                "nothing to compare it against. Tell me whose statement it is."
            ),
        )

    currency = (document.currency or "").strip().upper() or "INR"
    statement_lines, unreadable = statement_lines_from_items(
        document.items, currency=currency
    )
    if not statement_lines:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                "No row on this statement carried an amount I could read, so "
                "there is nothing to reconcile."
            ),
        )

    ledger = ledger_lines_for_vendor(db, context.tenant_id, vendor)
    try:
        result = reconcile(
            statement_lines, ledger, vendor_name=vendor, currency=currency
        )
    except CurrencyBlendError as exc:
        # §7.4: refused, never converted. 409 rather than 422 -- the request was
        # well formed and the data it points at is what conflicts.
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(exc)
        ) from exc

    lines = recon_recommendations(result, document_id=str(document.id))
    # D49 again -- recon lines are lines. A user who has settled "they show and
    # we do not" for #1043 does not want it back every time they re-attach the
    # statement.
    lines = drop_dismissed(
        lines, dismissed_ids(db, context.tenant_id, context.user_id)
    )
    grants = GrantSet.from_context(context)
    return ReconResponse(
        vendor_name=result.vendor_name,
        currency=result.currency,
        document_id=str(document.id),
        agrees=result.agrees,
        groups=_rendered_groups(result),
        unreadable_rows=unreadable,
        lines=_validated(visible_to(lines, grants)),
    )


# ─────────────────────────────────────────────────────────────────────────────
# POST /atlas/lines/{recommendation_id}/dismiss
# ─────────────────────────────────────────────────────────────────────────────

class DismissResponse(BaseModel):
    """What one dismiss click did.

    `created` is False on a repeat click. It is reported rather than hidden
    because the endpoint is idempotent by design and a client that wanted to
    know (a future D12 noise-pruning surface counting dismissals) should not
    have to infer it from a status code.
    """

    recommendation_id: str
    dismissed: bool
    created: bool


@router.post("/lines/{recommendation_id}/dismiss", response_model=DismissResponse)
def dismiss_atlas_line(
    recommendation_id: str,
    context: TenantContext = Depends(get_tenant_context),
    db: Session = Depends(get_db_session),
) -> DismissResponse:
    """Mark one line handled, for this user, for good (D49).

    **The one write in this router.** It records nothing about *why* and nothing
    about whether the underlying problem was solved -- D49 is a manual dismiss,
    not an automatic resolution, and inferring a resolution from a click would
    be exactly the certainty §5.1 forbids ATLAS from claiming.

    **Not a snooze.** There is no expiry parameter and no code that returns the
    line later.

    The id is taken as given. It is deterministic, it is the caller's own
    screen's line id, and an id that matches nothing suppresses nothing -- see
    `services/atlas_dismissals.dismiss()` for why validating it would cost a
    full recompute to reject something harmless.
    """
    try:
        created = dismiss(
            db, context.tenant_id, context.user_id, recommendation_id
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc

    # Feature 35 task 35.8: the briefing described this line; it no longer
    # describes today. Marked stale, never regenerated here (§8 ruling 4).
    invalidate_briefing(db, context.tenant_id, context.user_id)

    return DismissResponse(
        recommendation_id=recommendation_id.strip(),
        dismissed=True,
        created=created,
    )


# ─────────────────────────────────────────────────────────────────────────────
# POST /atlas/lines/{recommendation_id}/act  —  task 34.7 (D50, D51)
# ─────────────────────────────────────────────────────────────────────────────

class ActRequest(BaseModel):
    """One click on one line's action.

    The three fields are `Action`'s own (§12.2) minus its label, sent back by
    the client that rendered them. They are **re-checked here, not trusted**:
    `kind` is looked up in `ACTION_DISPOSITIONS`, and `params` is never forwarded
    to the underlying endpoint -- `services/atlas_actions.py` rebuilds the
    payload from a whitelist, so a field that endpoint accepts but no ATLAS line
    offers (`corrections`, `apply_as_standing_rule`) cannot arrive through here.

    `recommendation_id` is on the URL rather than in this body because it is what
    the action log records, and because it makes the call read the same shape as
    the dismiss endpoint beside it.
    """

    kind: str = Field(min_length=1)
    target_id: str = Field(min_length=1)
    params: dict = Field(default_factory=dict)


class ActResponse(BaseModel):
    """What the click did, in the words the screen shows."""

    recommendation_id: str
    kind: str
    target_id: str
    performed: bool
    #: The outcome sentence, or the refusal. Always present: a click that
    #: produced no sentence is a click the user cannot tell the result of.
    summary: str
    #: The underlying endpoint's own answer, whole. `resolve_audit_invoice`
    #: returns `remaining_alerts`, `raised_alerts` and `unmatched_dismissals`,
    #: and a work screen told only "success" would know less than the audit
    #: queue's own button does.
    detail: dict = Field(default_factory=dict)


@router.post("/lines/{recommendation_id}/act", response_model=ActResponse)
async def act_on_atlas_line(
    recommendation_id: str,
    payload: ActRequest,
    context: TenantContext = Depends(get_tenant_context),
    db: Session = Depends(get_db_session),
) -> ActResponse:
    """Perform one line's action, by calling the endpoint that already does it.

    **This is the endpoint that makes ATLAS a tool rather than a report.** Before
    it, `PERFORMABLE_ACTION_KINDS` was empty on both sides and every button on
    the work screen rendered disabled.

    Two kinds only (D50/D51) -- `resolve_invoice` and `retry_ingestion_source`.
    Everything else in §14.6's vocabulary is refused **409**, with the reason,
    because a suggest-only kind reaching a write path is the failure D50 exists
    to prevent and a silent 404 would read as "not built yet".

    **The capability check here is a second, separate decision** (34.7b). The
    caller's grants already decided what they could *see*: `visible_to()` drops
    lines they may not act on, so this line was never on their screen. That is
    not a gate -- a request naming a line id arrives here whatever was rendered,
    and a user without the grant is refused **403** at this endpoint. The two
    checks read the same grant and are asked at two different moments.

    **Every attempt is logged** (34.7c), success or refusal, before the answer is
    returned: §5.3's "what ATLAS did is a real list" is only true if the list
    also holds what it tried and could not do.
    """
    grants = GrantSet.from_context(context)
    kind = payload.kind.strip()
    target_id = payload.target_id.strip()

    def _log(succeeded: bool, summary: str) -> None:
        record_action(
            db,
            context.tenant_id,
            context.user_id,
            recommendation_id=recommendation_id,
            kind=kind,
            target_id=target_id,
            succeeded=succeeded,
            summary=summary,
        )

    try:
        outcome = await perform_action(
            db,
            context,
            grants,
            kind=kind,
            target_id=target_id,
            params=payload.params,
        )
    except UnknownActionKind as exc:
        # Not logged: nothing was attempted, and a row for a kind this backend
        # does not produce would be a record of the client's typo.
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    except ActionNotPerformable as exc:
        # 409, not 403 and not 404: the caller may well hold every grant, and
        # the kind certainly exists. What conflicts is the ruling.
        _log(False, str(exc))
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(exc)
        ) from exc
    except ActionNotPermitted as exc:
        _log(False, str(exc))
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)
        ) from exc
    except ActionFailed as exc:
        # The underlying endpoint's own refusal, carried up unedited. A 422 here
        # rather than a 500 because these are things a user can act on: a wrong
        # id, a source with no connection, a rate limit.
        _log(False, str(exc))
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc

    _log(True, outcome.summary)
    # Feature 35 task 35.8: something the briefing reported as pending has been
    # done. Only on success -- a refused action changed nothing to be stale about.
    invalidate_briefing(db, context.tenant_id, context.user_id)
    return ActResponse(
        recommendation_id=recommendation_id.strip(),
        kind=outcome.kind,
        target_id=outcome.target_id,
        performed=True,
        summary=outcome.summary,
        detail=outcome.detail,
    )


# ─────────────────────────────────────────────────────────────────────────────
# GET /atlas/actions  and  GET /atlas/actions/kinds  —  tasks 34.7c, 34.7d
# ─────────────────────────────────────────────────────────────────────────────

class ActionLogEntry(BaseModel):
    """One thing ATLAS did, attributed and timestamped (§5.3)."""

    id: str
    recommendation_id: str
    kind: str
    target_id: str
    succeeded: bool
    summary: str
    user_id: str
    performed_at: datetime


class ActionLogResponse(BaseModel):
    entries: list[ActionLogEntry]


@router.get("/actions", response_model=ActionLogResponse)
def get_atlas_actions(
    context: TenantContext = Depends(get_tenant_context),
    db: Session = Depends(get_db_session),
) -> ActionLogResponse:
    """What ATLAS did in this workspace, newest first (§5.3, task 34.7c).

    **Tenant-wide, not per caller.** The boundary §5.3 states is that a write is
    *visible* -- a per-user list would hide one auditor's resolve from the Admin
    who is the superset (§2.2) and answerable for it. Each row names who clicked.

    Not capability-filtered either, for the same reason: this is a record of
    writes, not a work queue, and a record with rows missing is not a record.
    """
    rows = recent_actions(db, context.tenant_id)
    return ActionLogResponse(
        entries=[
            ActionLogEntry(
                id=str(row.id),
                recommendation_id=row.recommendation_id,
                kind=row.action_kind,
                target_id=row.target_id,
                succeeded=row.succeeded,
                summary=row.summary,
                user_id=row.user_id,
                performed_at=row.performed_at,
            )
            for row in rows
        ]
    )


class ActionKindsResponse(BaseModel):
    """Which action kinds this backend can actually perform, right now.

    **The FE reads this rather than keeping its own list** (34.7d). Slice B
    shipped `PERFORMABLE_ACTION_KINDS` as an empty constant in `lib/atlas.ts`,
    which was the honest value then and is a second copy of a backend fact now.
    A copy is what lets a button be enabled ahead of its endpoint -- the exact
    failure that set was invented to prevent.
    """

    #: Kinds `POST /lines/{id}/act` will actually perform.
    performable: list[str]
    #: Kinds that resolve to a destination and are **never** writes (D50).
    suggest_only: list[str]
    #: Every kind this backend emits, with its disposition.
    dispositions: dict[str, str]


@router.get("/actions/kinds", response_model=ActionKindsResponse)
def get_atlas_action_kinds(
    context: TenantContext = Depends(get_tenant_context),
) -> ActionKindsResponse:
    """The dispositions table, on the wire (task 34.7d).

    A read with no tenant data in it; the auth dependency stays because every
    other route on this router has it and an unauthenticated hole in a product
    router is a thing nobody notices until it matters.
    """
    return ActionKindsResponse(
        performable=sorted(PERFORMABLE_ACTION_KINDS),
        suggest_only=sorted(SUGGEST_ONLY_ACTION_KINDS),
        dispositions={
            kind: disposition.value
            for kind, disposition in sorted(ACTION_DISPOSITIONS.items())
        },
    )


# ─────────────────────────────────────────────────────────────────────────────
# GET /atlas/orientation  —  task 34.12 (§7.1, D24, D25)
# ─────────────────────────────────────────────────────────────────────────────

class OrientationPartOut(BaseModel):
    key: str
    title: str
    body: str


class OrientationResponse(BaseModel):
    """What a workspace with no history is told (§7.1).

    `needed` is **reported, not enforced**. The server says whether this tenant
    has any invoices yet; the screen decides what to do with that. A user who
    wants to read the explanation again on a busy workspace is not something
    worth preventing, and an endpoint that refused would be enforcing D25's
    "teach once" as a rule about *access* when it is a rule about *volume*.
    """

    needed: bool
    capabilities: list[str]
    parts: list[OrientationPartOut]
    day_one_finds: list[str]
    historical_import_offer: str


@router.get("/orientation", response_model=OrientationResponse)
def get_atlas_orientation(
    context: TenantContext = Depends(get_tenant_context),
    db: Session = Depends(get_db_session),
) -> OrientationResponse:
    """Cold-start orientation, for the capabilities this caller holds (34.12).

    Separate from `GET /atlas/lines` on purpose, and the reason is D25's "teach
    once, then keep teaching in place": the orientation is not a line, it is not
    ranked, it is not dismissible and it does not belong in a list of work. A
    tenth entry in `lines` that behaved differently from the other nine would be
    the shape that invites a client to special-case it.
    """
    result = orientation(db, context.tenant_id, GrantSet.from_context(context))
    return OrientationResponse(
        needed=result.needed,
        capabilities=result.capabilities,
        parts=[
            OrientationPartOut(key=p.key, title=p.title, body=p.body)
            for p in result.parts
        ],
        day_one_finds=result.day_one_finds,
        historical_import_offer=result.historical_import_offer,
    )


# ─────────────────────────────────────────────────────────────────────────────
# /atlas/memory  —  task 34.10 (§7.2, D31, bounded by D40, plus D12)
# /atlas/missed  —  task 34.14 (§5.2 Q13, D34)
# ─────────────────────────────────────────────────────────────────────────────

class MemoryRuleOut(BaseModel):
    """One lesson ATLAS holds, in the words it was given in (§7.2)."""

    id: str
    text: str
    source: str
    origin_ref: str | None = None
    active: bool
    created_by: str
    created_at: datetime
    updated_at: datetime


class NoiseSuggestionOut(BaseModel):
    """D12, as a suggestion. **Never a rule that wrote itself.**"""

    family: str
    description: str
    count: int
    text: str


class MemoryResponse(BaseModel):
    """What ATLAS believes about this business, and what it is about to ask.

    The two are separate lists on purpose. A rule is something a person put
    there; a suggestion is arithmetic over dismissals that a person has not
    agreed to yet, and §5.3's "never writes silently" is the difference between
    them. Flattening the two would make the second look like the first.
    """

    rules: list[MemoryRuleOut]
    noise_suggestions: list[NoiseSuggestionOut]


class MemoryRuleCreate(BaseModel):
    text: str = Field(min_length=1)


class MemoryRuleUpdate(BaseModel):
    """Both optional, and they are different acts.

    `active=False` switches a rule off and keeps what it said. Deleting it is
    `DELETE`, which removes the row — the founder's rule is that delete means
    delete, and §7.2's reason agrees: a lesson in a soft-deleted limbo is
    precisely a lesson that cannot be found.
    """

    text: str | None = None
    active: bool | None = None


def _rule_out(rule) -> MemoryRuleOut:
    return MemoryRuleOut(
        id=str(rule.id),
        text=rule.text,
        source=rule.source,
        origin_ref=rule.origin_ref,
        active=rule.active,
        created_by=rule.created_by,
        created_at=rule.created_at,
        updated_at=rule.updated_at,
    )


@router.get("/memory", response_model=MemoryResponse)
def get_atlas_memory(
    context: TenantContext = Depends(get_tenant_context),
    db: Session = Depends(get_db_session),
) -> MemoryResponse:
    """Everything ATLAS believes about this business, readable (§7.2, 34.10).

    **Inactive rules are included.** The promise is that a wrong lesson can be
    *found*; a switched-off rule the user cannot see is one they can neither
    switch back on nor delete.

    **Most of what ATLAS knows is deliberately not here** (D40). Vendor
    baselines and claims are derived at check time and thrown away (D39); the
    line shows its own working instead. This list is what ATLAS was told or what
    a user agreed it should remember — which is the only part that could be
    silently wrong for months.
    """
    return MemoryResponse(
        rules=[_rule_out(r) for r in list_rules(db, context.tenant_id)],
        noise_suggestions=[
            NoiseSuggestionOut(
                family=s.family, description=s.description, count=s.count, text=s.text
            )
            for s in noise_suggestions(db, context.tenant_id)
        ],
    )


@router.post("/memory", response_model=MemoryRuleOut, status_code=status.HTTP_201_CREATED)
def post_atlas_memory(
    payload: MemoryRuleCreate,
    context: TenantContext = Depends(get_tenant_context),
    db: Session = Depends(get_db_session),
) -> MemoryRuleOut:
    """Tell ATLAS something, in your own words (§7.2, source `told`).

    The source is fixed to `told` here and is not a field on the request: a
    client that could name its own provenance could label a lesson it invented
    as one the user gave, and provenance is what makes a wrong lesson judgeable.
    """
    try:
        rule = add_rule(db, context.tenant_id, context.user_id, text=payload.text)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    # Feature 35 task 35.8: memory rules go into the briefing's prompt, so a new
    # one makes today's briefing a briefing written without it.
    invalidate_briefing(db, context.tenant_id, context.user_id)
    return _rule_out(rule)


@router.patch("/memory/{rule_id}", response_model=MemoryRuleOut)
def patch_atlas_memory(
    rule_id: UUID,
    payload: MemoryRuleUpdate,
    context: TenantContext = Depends(get_tenant_context),
    db: Session = Depends(get_db_session),
) -> MemoryRuleOut:
    """Correct a lesson, or switch it off (§7.2: "read it, change it or delete it")."""
    try:
        rule = edit_rule(
            db,
            context.tenant_id,
            rule_id,
            text=payload.text,
            active=payload.active,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    if rule is None:
        # 404 and not 403 on another tenant's id, the same way this router's
        # recon route answers: a 403 confirms the row exists.
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No such rule")
    return _rule_out(rule)


@router.delete("/memory/{rule_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_atlas_memory(
    rule_id: UUID,
    context: TenantContext = Depends(get_tenant_context),
    db: Session = Depends(get_db_session),
) -> None:
    """Delete a lesson. **The row goes.**

    Not a soft delete, not a `deleted_at`, not an archive. §7.2's whole argument
    is that a wrong lesson which cannot be found haunts the system forever, and
    a retained-but-hidden rule is the definition of one that cannot be found.
    """
    if not delete_rule(db, context.tenant_id, rule_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No such rule")


class MissedReportRequest(BaseModel):
    """"You missed this" (D34) — the only false-negative detector there is."""

    entity_kind: str = Field(min_length=1)
    entity_id: str = Field(min_length=1)
    #: What ATLAS should have caught, in the user's own words. **Stored
    #: unedited**: it is the evidence ATLAS was wrong, and paraphrasing it would
    #: be the system editing its own report card.
    description: str = Field(min_length=1)


class MissedReportResponse(BaseModel):
    id: str
    #: The memory rule this produced. The report on its own changes nothing; the
    #: rule is the half that protects the next invoice (§7.2).
    rule: MemoryRuleOut


@router.post("/missed", response_model=MissedReportResponse, status_code=status.HTTP_201_CREATED)
def post_atlas_missed(
    payload: MissedReportRequest,
    context: TenantContext = Depends(get_tenant_context),
    db: Session = Depends(get_db_session),
) -> MissedReportResponse:
    """Report something ATLAS should have caught (task 34.14, D34).

    **On any record, from any caller with any grant.** The affordance is
    deliberately not capability-gated: a miss is noticed by whoever happens to be
    looking, and a Loader who spots a duplicate is the same evidence as an
    Auditor who does. Gating it would suppress reports of exactly the kind §5.2
    says are already invisible and under-reported.

    Under-reporting is accepted and recorded (§13.4): this endpoint measures
    nothing and there is no miss-rate anywhere. What it does is turn one person's
    observation into a lesson the whole workspace can read.
    """
    try:
        report, rule = report_missed(
            db,
            context.tenant_id,
            context.user_id,
            entity_kind=payload.entity_kind,
            entity_id=payload.entity_id,
            description=payload.description,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    return MissedReportResponse(id=str(report.id), rule=_rule_out(rule))


# ─────────────────────────────────────────────────────────────────────────────
# GET /atlas/briefing  and  POST /atlas/briefing/answer
# Feature 35 (ATLAS Intelligence) tasks 35.7 and 35.9
#
# Spec: `docs/feature_35_atlas_intelligence.md` §3.1, §3.3, §3.5, §4.
#
# This is the only place in the product that calls `agents/atlas_agent.py`. Four
# paths, decided in this order and each one cheaper than the next:
#
#   1. no grants           -> `welcome` for "user", `done`. No LLM, nothing stored.
#   2. no tenant history   -> `welcome` for the role, `done`. No LLM, nothing
#                             stored (§3.5: a welcome is not a briefing, and
#                             storing one would make a cold tenant look briefed).
#   3. fresh, not stale    -> the stored frames replayed, `done{cached: true}`.
#   4. otherwise           -> `run_briefing()`, streamed as it is produced, then
#                             stored.
#
# **Why the whole thing is inside one `try`.** An SSE response's headers are on
# the wire the moment the first frame is yielded, so an exception after that
# point is not a 500 -- it is a truncated stream, which the FE sees as a
# briefing that simply stopped. Feature 34 §15.6 (BE Gap 692) is the precedent
# for what that costs: a guard raising in a response path took out the whole
# screen. Here the failure is contained to the briefing panel: `error` then
# `done`, and the connection closes cleanly.
# ─────────────────────────────────────────────────────────────────────────────

def _frame(event) -> str:
    """One SSE frame in §3.3's shape: an `event:` line, a `data:` line, a blank one.

    Named events rather than `routers/chat.py`'s bare `data:` lines, because §3.3
    defines six event types the FE dispatches on by name. `default=str` for the
    same reason every other JSON dump in ATLAS carries it: a `Decimal` amount or
    a `date` reaching the encoder must not be the thing that ends the stream.
    """
    return "event: {}\ndata: {}\n\n".format(
        event.type, json.dumps(event.data, default=str)
    )


@router.get("/briefing")
def get_atlas_briefing(
    context: TenantContext = Depends(get_tenant_context),
    db: Session = Depends(get_db_session),
) -> StreamingResponse:
    """The briefing, as Server-Sent Events (§3.3).

    A **synchronous** generator handed to `StreamingResponse`, which Starlette
    iterates in a worker thread. That is deliberate: `run_briefing()` is a
    blocking generator (the model call and every tool dispatch are synchronous
    SQLAlchemy and HTTP work), and wrapping it in an `async def` would run all of
    it on the event loop -- the exact defect BE Gap 602 records for the chat
    stream, where one blocking read per iteration stalled every other request in
    the process.
    """
    grants = GrantSet.from_context(context)
    today = date.today()
    tenant_id = context.tenant_id
    user_id = context.user_id

    def stream():
        try:
            for frame in _briefing_frames(db, tenant_id, user_id, grants, today):
                yield frame
        except Exception as exc:  # noqa: BLE001 -- see this section's header
            logger.exception(
                "ATLAS briefing failed for tenant %s user %s", tenant_id, user_id
            )
            yield _frame(BriefingEvent(type="error", data={"message": str(exc)}))
            yield _frame(
                BriefingEvent(
                    type="done",
                    data={"cached": False, "model": "", "dropped_paragraphs": 0},
                )
            )

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            # Same three headers `routers/chat.py` sends: without
            # `X-Accel-Buffering` the reverse proxy in front of the container
            # buffers the whole stream and the briefing arrives all at once,
            # which defeats the reason `run_briefing()` is a generator at all.
            "X-Accel-Buffering": "no",
        },
    )


def _briefing_frames(db, tenant_id, user_id, grants, today):
    """The four paths, in order. Yields SSE frame strings."""
    # -- 1 and 2: the welcome paths. No model call on either (§3.5) ----------
    if grants.is_ungranted() or not tenant_has_history(db, tenant_id):
        role = _briefing_role(grants)
        yield _frame(
            BriefingEvent(type="welcome", data={"role": role, "text": welcome_for(role)})
        )
        yield _frame(
            BriefingEvent(
                type="done",
                data={"cached": False, "model": "", "dropped_paragraphs": 0},
            )
        )
        return

    # -- 3: a briefing already written today, still current ------------------
    row = cached_briefing(db, tenant_id, user_id, today)
    if row is not None and not row.stale:
        for event in replay_events(row):
            yield _frame(event)
        yield _frame(
            BriefingEvent(
                type="done",
                data={
                    "cached": True,
                    "model": row.model,
                    "dropped_paragraphs": row.dropped,
                },
            )
        )
        return

    # -- 4: a fresh run, streamed as it is produced, then stored -------------
    ctx = ToolContext(
        db=db,
        skill=SkillContext(tenant_id=tenant_id, today=today),
        grants=grants,
        user_id=user_id,
    )
    run = BriefingRun(tenant_id=tenant_id, user_id=user_id)
    produced: list = []

    for event in run_briefing(
        db,
        ctx,
        today=today,
        llm=get_llm_for_role("atlas"),
        role=_briefing_role(grants),
        run=run,
    ):
        # The `done` the agent emits is the agent's; this route owns the wire's,
        # because only the route knows whether the answer came from a cache
        # (§3.3's `cached` field). Every other frame goes out as produced.
        if event.type == "done":
            continue
        produced.append(event)
        yield _frame(event)

    # Stored **after** the stream, from the frames that were actually sent, so a
    # replay tomorrow is what the browser saw today rather than what the model
    # said. A storage failure must not truncate a briefing the user already has.
    try:
        store_briefing(db, run, produced, today=today)
    except Exception:  # noqa: BLE001
        logger.exception(
            "ATLAS briefing could not be stored for tenant %s user %s",
            tenant_id, user_id,
        )

    yield _frame(
        BriefingEvent(
            type="done",
            data={
                "cached": False,
                "model": run.model,
                "dropped_paragraphs": run.dropped,
            },
        )
    )


def _briefing_role(grants: GrantSet) -> str:
    """The §3.5 role word for this caller.

    Duplicates `agents.atlas_agent._role_from()`'s ladder rather than importing
    a private name. The two agree by test (`test_atlas_briefing_router.py`), not
    by import, and the welcome path must work without the agent module being
    involved at all.
    """
    if grants.is_admin:
        return "admin"
    if grants.can_audit:
        return "auditor"
    if grants.can_train:
        return "trainer"
    if grants.can_load:
        return "loader"
    return "user"


class BriefingAnswerRequest(BaseModel):
    """The answer to the briefing's one question (§3.3).

    `question_text` is sent back by the client that rendered it and is stored as
    part of the lesson rather than trusted as a key: there is no question row to
    look up, because §3.1 step 6 allows exactly one question per briefing and it
    lives in `atlas_briefings.question`. What makes the answer judgeable later is
    that the rule reads as a question and its answer, which is what
    `_interview_rule_text()` composes.
    """

    question_text: str = Field(min_length=1, max_length=2000)
    answer: str = Field(min_length=1, max_length=2000)


def _interview_rule_text(question: str, answer: str) -> str:
    """One lesson, in the user's own words, with the question that prompted it.

    **Neither half is paraphrased**, for `report_missed()`'s reason (§7.2): the
    sentence is the evidence, and ATLAS rewriting it would make ATLAS the author
    of a belief the user was supposed to own. The question is kept with it
    because an answer without its question is unjudgeable six weeks later --
    "yes, always" means nothing on its own.
    """
    return "{} — {}".format(question.strip(), answer.strip())


@router.post(
    "/briefing/answer",
    response_model=MemoryRuleOut,
    status_code=status.HTTP_201_CREATED,
)
def post_atlas_briefing_answer(
    payload: BriefingAnswerRequest,
    context: TenantContext = Depends(get_tenant_context),
    db: Session = Depends(get_db_session),
) -> MemoryRuleOut:
    """Answer the briefing's question; it becomes a memory rule (task 35.9).

    **The question is not re-validated here, and that is deliberate.** It was
    already validated in the loop (tasks 35.4/35.5): `validate_briefing_paragraph()`
    runs over the question exactly as over a paragraph, so a question that
    invented a number or cited nothing never reached the browser and cannot be
    answered. Re-checking it here would need the run's emitted-id set, which is
    gone by the time the user types, and would mean re-implementing the guard
    against a weaker input -- which is how one control becomes two that disagree.

    The source is fixed to `interview` and is not a request field, for the same
    reason `POST /atlas/memory` fixes `told`: a client that could name its own
    provenance could label a lesson it invented as one the user gave.
    """
    try:
        rule = add_rule(
            db,
            context.tenant_id,
            context.user_id,
            text=_interview_rule_text(payload.question_text, payload.answer),
            source=RuleSource.INTERVIEW,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc

    # Feature 35 task 35.9: the briefing asked, it has been answered, and the
    # answer is now a rule the next briefing's prompt carries.
    invalidate_briefing(db, context.tenant_id, context.user_id)
    return _rule_out(rule)
