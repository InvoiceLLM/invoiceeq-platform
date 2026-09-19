"""Feature 34 (ATLAS) task 34.7 — what ATLAS may actually **do**.

Spec: `docs/feature_34_atlas.md` §5.3 (the boundaries) · §17 (this slice as
built) · `atlas_discussion.md` **D50, D51**.

The problem this closes
-----------------------
Slices A and B produced a screen that **explains and cannot act**. Ten action
kinds reach the wire (`services/atlas_skills.py`, `atlas_doubt.py`,
`atlas_recon.py`), `PERFORMABLE_ACTION_KINDS` was empty on both sides, and every
button rendered disabled saying "I can see this and explain it, but I cannot do
it for you yet". Until this module existed ATLAS was a report, not a tool.

D50/D51: exactly two kinds become real
--------------------------------------
Not eight. The two performable kinds share a property the others do not --
**being wrong is cheap and local**:

* ``resolve_invoice`` -> ``PUT /audit/resolve/{invoice_id}``. One record,
  visible, reversible by the same person who set it.
* ``retry_ingestion_source`` -> ``POST /autopilot/sync``, per source since D43.
  A re-run sync writes nothing new at all; both dedup layers stop a re-import.

``apply_field_correction`` and ``requeue_invoices`` are **suggest only**, and
this module is where that is enforced rather than promised. A wrong correction
does not stay on one record: it teaches a rule that then misfires on every
future invoice from that vendor, which is §5.3's "never learns a permanent rule
from one instance" seen from the other end. A wrong requeue spends pipeline work
nobody asked for and clicking again does not undo it. So the boundary is not
"read versus write" -- it is **how far the blast radius travels when ATLAS is
wrong**, §5.2's asymmetry applied to actions.

Five rules this module keeps
----------------------------
1. **It performs nothing itself.** Both performable kinds are wired to code that
   already existed and already works. `_resolve_invoice` calls
   `routers.audit.resolve_audit_invoice`, the same function the audit queue's
   own button calls -- with its rate limiter, its row lock, its `AuditLog`
   write, its alert re-check. Re-implementing any of that inside ATLAS would
   create a second path to the same decision, and the second path is the one
   that drifts.
2. **Every kind is in the table, including the ones that may never be
   performed.** `ACTION_DISPOSITIONS` covers all ten. A kind that is simply
   absent would be refused by accident; a kind that is present as `SUGGEST` is
   refused *on purpose*, and the difference is readable by the next person.
3. **The capability check on acting is its own decision** (D50, and 34.7b). The
   same grant governs seeing and acting, but they are two checks and before this
   module only the seeing one was made -- `visible_to()` drops a line from the
   payload, which is not the same as refusing a request that names its id. A
   user who cannot act is refused **here, at the endpoint**, not merely shown a
   disabled button, because a disabled button is a client-side fact.
4. **The client's `params` are never passed through.** The payload for the
   underlying endpoint is rebuilt here from a whitelist. This is not defensive
   ceremony: `AuditResolutionPayload` also accepts `corrections` and
   `apply_as_standing_rule`, so a passed-through dict would let
   `apply_field_correction` -- suggest-only by ruling -- arrive wearing
   `resolve_invoice`'s name and teach a standing rule. The ruling has to be
   enforced at the field level or it is not enforced.
5. **Every performed action is logged before the caller is answered** (§5.3,
   "every write is visible, attributed and timestamped" and "what ATLAS did is a
   real list"). `AtlasActionLog` is that list, and `GET /atlas/actions` serves
   it. A failure is logged too, with its reason: an action that failed is
   something ATLAS did, and a log that only holds successes is a log that
   flatters.

`PERFORMABLE_ACTION_KINDS` is populated one kind at a time
----------------------------------------------------------
The empty set shipped in Slice B was a deliberate honesty mechanism, not an
oversight. The rule it encodes survives this module: **a kind is added to the
`PERFORM` disposition only once the path behind it actually works**, and the FE
reads the same set over the wire rather than keeping its own copy (which is what
`GET /atlas/actions/kinds` exists for). A button is never enabled ahead of its
endpoint.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any
from uuid import UUID

from sqlmodel import Session, select

from services.atlas_capabilities import AtlasCapability, GrantSet

logger = logging.getLogger(__name__)

__all__ = [
    "ActionDisposition",
    "ACTION_DISPOSITIONS",
    "ACTION_CAPABILITY",
    "PERFORMABLE_ACTION_KINDS",
    "SUGGEST_ONLY_ACTION_KINDS",
    "ActionRefused",
    "UnknownActionKind",
    "ActionNotPerformable",
    "ActionNotPermitted",
    "ActionFailed",
    "ActionOutcome",
    "capability_for",
    "disposition_of",
    "perform_action",
    "record_action",
    "recent_actions",
]


class ActionDisposition(str, Enum):
    """What ATLAS is allowed to do with one action kind (D50, D51).

    Four values, and the three non-`PERFORM` ones are **not** a queue of things
    that will become `PERFORM` later. They are rulings:

    * `SUGGEST` -- the click resolves to a destination and opens it. It must
      never become a write (D50). The blast radius of being wrong is the reason.
    * `NAVIGATE` -- it never was a write. "Show what is due" is a link.
    * `INSTRUCT` -- the line tells the *user* to do something ATLAS does not do.
      `attach_witness_document` is this since D47: ATLAS never attaches.
    """

    PERFORM = "perform"
    SUGGEST = "suggest"
    NAVIGATE = "navigate"
    INSTRUCT = "instruct"


#: Every action kind any emitter produces, with what ATLAS may do with it.
#:
#: **Complete by construction, not by memory**: `tests/test_atlas_actions.py`
#: greps every `kind="..."` out of the three emitter modules and asserts this
#: table covers them, so a kind added by a future skill fails a test instead of
#: falling through to a 422 nobody expected.
ACTION_DISPOSITIONS: dict[str, ActionDisposition] = {
    # ── Performable (D50, D51). Both wrap an endpoint that already works. ──
    "resolve_invoice": ActionDisposition.PERFORM,
    "retry_ingestion_source": ActionDisposition.PERFORM,
    # ── Suggest only (D50). These must never become writes. ──
    "apply_field_correction": ActionDisposition.SUGGEST,
    "requeue_invoices": ActionDisposition.SUGGEST,
    # ── Navigation. Never were writes. ──
    "open_upcoming_payments": ActionDisposition.NAVIGATE,
    "open_field_review": ActionDisposition.NAVIGATE,
    "open_invoice_against_statement": ActionDisposition.NAVIGATE,
    "review_unlisted_invoices": ActionDisposition.NAVIGATE,
    # ── An instruction to the user. ──
    # D47: ATLAS does not attach a document to a chat session, and the line says
    # so in its own words.
    "attach_witness_document": ActionDisposition.INSTRUCT,
    # §14.4: "they show and we do not" drafts a message to the vendor, which is
    # `Reversibility.LEAVES_COMPANY` -- read in full and sent individually by a
    # human (§5.3). ATLAS composes; it does not send, so this is an instruction.
    "request_missing_invoices": ActionDisposition.INSTRUCT,
}

#: The capability required to **act**, per kind (34.7b).
#:
#: Separate from the capability the line *declares*, on purpose, even though the
#: two agree today: the line's capability is who the work belongs to, and this is
#: who may push the button. Deriving one from the other would mean a future line
#: type shown to one audience for context could be acted on by them too.
ACTION_CAPABILITY: dict[str, AtlasCapability] = {
    "resolve_invoice": AtlasCapability.AUDIT,
    "retry_ingestion_source": AtlasCapability.LOAD,
    "apply_field_correction": AtlasCapability.TRAIN,
    "requeue_invoices": AtlasCapability.LOAD,
    "open_upcoming_payments": AtlasCapability.AUDIT,
    "open_field_review": AtlasCapability.TRAIN,
    "open_invoice_against_statement": AtlasCapability.AUDIT,
    "review_unlisted_invoices": AtlasCapability.AUDIT,
    "attach_witness_document": AtlasCapability.AUDIT,
    "request_missing_invoices": AtlasCapability.AUDIT,
}

#: Derived, never hand-maintained -- the FE reads this over the wire.
PERFORMABLE_ACTION_KINDS: frozenset[str] = frozenset(
    kind
    for kind, disposition in ACTION_DISPOSITIONS.items()
    if disposition is ActionDisposition.PERFORM
)

SUGGEST_ONLY_ACTION_KINDS: frozenset[str] = frozenset(
    kind
    for kind, disposition in ACTION_DISPOSITIONS.items()
    if disposition is ActionDisposition.SUGGEST
)

#: The only two statuses `resolve_invoice` may set, whatever the client sends.
#:
#: `AuditResolutionPayload` also accepts `AUDIT_REQUIRED` (Gap 193's Admin-only
#: reopen of someone else's finalized decision), `REVIEW_LATER` and
#: `NEEDS_RESUBMISSION`. None of the three is what an ATLAS line offers, and an
#: action surface that accepts more than its lines emit is a surface whose real
#: capability nobody has read.
_ALLOWED_RESOLVE_STATUS = frozenset({"PAID", "REJECTED"})


# ─────────────────────────────────────────────────────────────────────────────
# Refusals — one class per reason, so the router maps them to status codes
# without re-deciding anything
# ─────────────────────────────────────────────────────────────────────────────

class ActionRefused(Exception):
    """Base: this action was not performed, and this is why."""


class UnknownActionKind(ActionRefused):
    """A kind no emitter in this backend produces."""


class ActionNotPerformable(ActionRefused):
    """A known kind ATLAS is ruled not to perform (D50) -- suggest or navigate."""

    def __init__(self, message: str, disposition: ActionDisposition) -> None:
        super().__init__(message)
        self.disposition = disposition


class ActionNotPermitted(ActionRefused):
    """The caller does not hold the capability this action requires (34.7b)."""


class ActionFailed(ActionRefused):
    """The underlying endpoint refused or errored. Its message is carried up."""


@dataclass
class ActionOutcome:
    """What one performed action did, in the words the screen shows.

    `detail` is the underlying endpoint's own answer, kept whole rather than
    summarised: `resolve_audit_invoice` returns `remaining_alerts`,
    `raised_alerts` and `unmatched_dismissals`, and a caller that only learned
    "success: true" would be told less than the audit queue's own button tells.
    """

    kind: str
    target_id: str
    summary: str
    detail: dict[str, Any] = field(default_factory=dict)


def disposition_of(kind: str) -> ActionDisposition:
    """What ATLAS may do with `kind`. Raises on a kind no emitter produces."""
    try:
        return ACTION_DISPOSITIONS[kind]
    except KeyError as exc:
        raise UnknownActionKind(
            f"{kind!r} is not an action kind this backend produces."
        ) from exc


def capability_for(kind: str) -> AtlasCapability:
    """The capability required to act on `kind` (34.7b)."""
    try:
        return ACTION_CAPABILITY[kind]
    except KeyError as exc:
        raise UnknownActionKind(
            f"{kind!r} is not an action kind this backend produces."
        ) from exc


# ─────────────────────────────────────────────────────────────────────────────
# The dispatcher (34.7a)
# ─────────────────────────────────────────────────────────────────────────────

async def perform_action(
    db: Session,
    context: Any,
    grants: GrantSet,
    *,
    kind: str,
    target_id: str,
    params: dict[str, Any] | None = None,
) -> ActionOutcome:
    """Map one action kind onto the endpoint that already performs it.

    Refuses, in this order, and each refusal is a stated position:

    1. an unknown kind -> `UnknownActionKind`;
    2. a kind ruled not performable -> `ActionNotPerformable`, carrying its
       disposition so the caller can say *why* rather than "no";
    3. a caller without the capability -> `ActionNotPermitted`. **This is the
       check 34.7b adds.** `visible_to()` already keeps the line off their
       screen, but a screen is not a gate: a request naming the line's id
       arrives at this function regardless of what was rendered.

    Only then does it dispatch, and the dispatch is a call into existing code.
    """
    params = dict(params or {})
    disposition = disposition_of(kind)

    if disposition is not ActionDisposition.PERFORM:
        raise ActionNotPerformable(_refusal_text(kind, disposition), disposition)

    required = capability_for(kind)
    if not grants.holds(required):
        raise ActionNotPermitted(
            f"You do not have permission to do this. It needs the "
            f"{required.value} capability; ask an Admin to grant it."  # hardcode-ok: an AtlasCapability enum value in a permission message -- a capability name, not a figure
        )

    if kind == "resolve_invoice":
        return await _resolve_invoice(db, context, target_id, params)
    if kind == "retry_ingestion_source":
        return _retry_ingestion_source(db, context, target_id, params)

    # Unreachable while PERFORMABLE_ACTION_KINDS is derived from the same table
    # this function branches on -- and asserted unreachable by a test, because
    # "unreachable" written in a comment is how a kind gets added to the table
    # and to no branch.
    raise UnknownActionKind(  # pragma: no cover
        f"{kind!r} is marked performable but has no dispatch branch."
    )


def _refusal_text(kind: str, disposition: ActionDisposition) -> str:
    """Why this click was not a write, said plainly rather than as a 403."""
    if disposition is ActionDisposition.SUGGEST:
        return (
            f"I do not do {kind!r} for you. I can show you exactly where to do "
            "it, but being wrong here would not stay on one record — a wrong "
            "correction teaches a rule that misfires on every invoice after "
            "it. Open it and decide."
        )
    if disposition is ActionDisposition.NAVIGATE:
        return f"{kind!r} opens a screen; there is nothing here to perform."
    return (
        f"{kind!r} is something for you to do, not for me — the line says what "
        "and where."
    )


async def _resolve_invoice(
    db: Session, context: Any, target_id: str, params: dict[str, Any]
) -> ActionOutcome:
    """`PUT /audit/resolve/{invoice_id}`, reached by calling its own handler.

    **Not an HTTP call to ourselves and not a copy of its logic.** The handler is
    an ordinary async function whose `Depends(...)` defaults are only resolved by
    FastAPI, so passing the context and session explicitly runs exactly the code
    an auditor's own click runs: Gap 561's rate limiter, Gap 541's row lock, the
    `AuditLog` write, the alert re-check and the notification fan-out.

    What this *does* have to do itself is the gate the router-level
    `Depends(require_actions_scope)` would have applied -- calling the function
    directly does not run it. `perform_action()` above has already required
    `AtlasCapability.AUDIT`, which for a human caller is the same question
    `require_actions_scope` asks (`context.can_audit`, with Admins holding it
    through `resolve_permissions`). That equivalence is asserted in
    `tests/test_atlas_actions.py` rather than left to this paragraph.
    """
    # Imported here, not at module scope: `routers.audit` pulls the extraction
    # agent and the queue worker's OCR handler, and a service importing a router
    # at import time is how a cycle starts.
    from routers.audit import AuditResolutionPayload, resolve_audit_invoice

    try:
        invoice_id = UUID(str(target_id))
    except (ValueError, AttributeError, TypeError) as exc:
        raise ActionFailed(f"{target_id!r} is not an invoice id.") from exc

    status_value = str(params.get("status") or "").upper()
    if status_value not in _ALLOWED_RESOLVE_STATUS:
        raise ActionFailed(
            f"An ATLAS decision is PAID or REJECTED; {status_value or 'nothing'} "  # hardcode-ok: an invoice STATUS token echoed back, not money; the two names are routers/audit.py's own status vocabulary
            "is not one of them."
        )

    # Rule 4 in the module docstring: the payload is rebuilt, never forwarded.
    # `corrections` and `apply_as_standing_rule` are deliberately not settable
    # from here -- that is `apply_field_correction`, which D50 made suggest-only.
    payload = AuditResolutionPayload(status=status_value)

    from fastapi import HTTPException

    try:
        result = await resolve_audit_invoice(
            invoice_id=invoice_id,
            payload=payload,
            context=context,
            db_session=db,
        )
    except HTTPException as exc:
        # Its refusal, in its own words. Re-deciding what a 404 or a 429 from the
        # audit router means would be this module holding a second opinion about
        # a rule that is not its own.
        raise ActionFailed(str(exc.detail)) from exc

    detail = dict(result) if isinstance(result, dict) else {"result": str(result)}
    verb = "approved" if status_value == "PAID" else "rejected"
    already = bool(detail.get("already_resolved"))
    summary = (
        f"This invoice was already resolved, so nothing changed."
        if already
        else f"Invoice {verb}."
    )
    return ActionOutcome(
        kind="resolve_invoice", target_id=str(invoice_id), summary=summary, detail=detail
    )


def _retry_ingestion_source(
    db: Session, context: Any, target_id: str, params: dict[str, Any]
) -> ActionOutcome:
    """`POST /autopilot/sync`, for **one** source (D51, and D43 made it possible).

    The endpoint itself runs every source (§14.2, so that Sync Now does not lie
    about what it checked). An ATLAS line is about one source -- "this Drive
    folder has gone quiet" -- so it calls `run_sync(config_id=...)`, the
    per-source entry point the same module exposes. Syncing all of them from a
    line that names one would be a button that does more than it says.

    `run_sync` resolves the config out of *this tenant's* sources and raises if
    the id is not among them, so tenant scoping is not re-implemented here.
    """
    from services.autopilot_sync import run_sync

    raw = params.get("source_config_id") or target_id
    try:
        config_id = UUID(str(raw))
    except (ValueError, AttributeError, TypeError) as exc:
        raise ActionFailed(f"{raw!r} is not an ingestion source id.") from exc

    try:
        summary_counts = run_sync(
            context.tenant_id, db, trigger="manual", config_id=config_id
        )
    except ValueError as exc:
        # "no such source for this tenant", "no active Drive connection" -- both
        # are things the user can fix, and both read better than a 500.
        raise ActionFailed(str(exc)) from exc
    except Exception as exc:  # noqa: BLE001 - reported, never swallowed
        logger.error(
            "ATLAS retry_ingestion_source failed for source %s: %s", config_id, exc
        )
        raise ActionFailed(f"That source could not be run: {exc}") from exc

    processed = int(summary_counts.get("processed", 0))
    skipped = int(summary_counts.get("skipped", 0))
    failed = int(summary_counts.get("failed", 0))
    summary = (
        f"Ran this source: {processed} new file(s) imported, "
        f"{skipped} already seen, {failed} failed."
    )
    return ActionOutcome(
        kind="retry_ingestion_source",
        target_id=str(config_id),
        summary=summary,
        detail=dict(summary_counts),
    )


# ─────────────────────────────────────────────────────────────────────────────
# The action log (34.7c) — §5.3's "what ATLAS did is a real list"
# ─────────────────────────────────────────────────────────────────────────────

def record_action(
    db: Session,
    tenant_id: UUID,
    user_id: str,
    *,
    recommendation_id: str,
    kind: str,
    target_id: str,
    succeeded: bool,
    summary: str,
) -> None:
    """One row per attempt, written before the caller is answered.

    **Failures are recorded too.** §5.3 requires that what ATLAS did is a real
    readable list; a list holding only the successes would answer "did ATLAS
    touch this invoice?" with a confident no on exactly the occasions someone is
    asking because something looks wrong.

    A logging failure never fails the action. The write already happened in the
    underlying endpoint by the time this is called, and raising here would report
    a failure for something that succeeded -- which is a worse lie than a missing
    log row. It is logged loudly instead.
    """
    from models import AtlasActionLog

    row = AtlasActionLog(
        tenant_id=tenant_id,
        user_id=user_id or "",
        recommendation_id=(recommendation_id or "").strip()[:255],
        action_kind=kind[:64],
        target_id=str(target_id)[:255],
        succeeded=succeeded,
        summary=summary[:1000],
        performed_at=datetime.now(timezone.utc).replace(tzinfo=None),
    )
    db.add(row)
    try:
        db.commit()
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        logger.error(
            "ATLAS action log write failed for %s on %s: %s", kind, target_id, exc
        )


def recent_actions(
    db: Session, tenant_id: UUID, limit: int = 50
) -> list[Any]:
    """What ATLAS did in this tenant, newest first.

    **Tenant-wide, not per user.** "What ATLAS did" is a question about the
    workspace's records -- §5.3's boundary is about writes being *visible*, and a
    per-user log would hide one auditor's resolve from the Admin who is the
    superset (§2.2). Each row carries who did it, which is the part that matters.
    """
    from models import AtlasActionLog

    return list(
        db.exec(
            select(AtlasActionLog)
            .where(AtlasActionLog.tenant_id == tenant_id)
            .order_by(AtlasActionLog.performed_at.desc())  # type: ignore[union-attr]
            .limit(max(1, min(int(limit), 200)))
        ).all()
    )
