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

import logging
from datetime import date
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlmodel import Session, select

from dependencies import TenantContext, get_db_session, get_tenant_context
from models import Document, Invoice
from services.atlas_capabilities import AtlasCapability, GrantSet, visible_to
from services.atlas_contract import (
    AtlasContractError,
    CurrencyBlendError,
    Recommendation,
    validate_recommendation,
)
from services.atlas_dismissals import dismiss, dismissed_ids, drop_dismissed
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
    lines: list[Recommendation]
    doubt_checks_run: int
    doubt_checks_skipped: int


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

    doubt_lines, checked, skipped = _doubt_lines(db, ctx, grants)
    # The doubt asks are lines too: a dismissed "attach the quotation" must not
    # come back on the next open either.
    lines.extend(drop_dismissed(doubt_lines, dismissed))

    return AtlasLinesResponse(
        ungranted=False,
        capabilities=sorted(c.value for c in grants.capabilities()),
        lines=_validated(lines),
        doubt_checks_run=checked,
        doubt_checks_skipped=skipped,
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

    return DismissResponse(
        recommendation_id=recommendation_id.strip(),
        dismissed=True,
        created=created,
    )
