"""BE Gap 595 (CH-28): chat reads of financial records, written to `AuditLog`.

Every mutation of an invoice already lands in `audit_logs` -- approvals, rejections,
corrections, deletions, outbound sends. Chat did not write a single row, and chat is
the one interface that can retrieve fifty invoices' worth of vendor, amount and
payment history in one sentence. An auditor asking "who looked at our payment history
last quarter?" got an answer that was silently wrong.

**Founder ruling 2026-09-16: reuse `AuditLog`, one row per invoice.** Not a new table
and not a set-valued column, so every existing auditor-facing query, export and index
keeps working, and an invoice's trail shows reads interleaved with its approvals in
one place. The stated cost is volume: a 25-invoice answer writes 25 rows.

Two consequences of that choice, both deliberate:

  * `AuditLog.actor_user_id` became nullable (migration `e2f3a4b5c6d7`). An API key
    and an anonymous widget visitor have no `users` row, and refusing to log those
    reads -- the least accountable ones -- would defeat the point. `actor_role`
    carries `api_key` or `widget` so they are still identifiable as a class.
  * Writing is best-effort. A failure here is logged and swallowed: an audit row
    that cannot be written must not destroy an answer the user has already been
    given, and the alternative (raising after the answer is persisted) would turn a
    successful turn into a 500.
"""
from __future__ import annotations

import logging
from typing import Optional
from uuid import UUID

from sqlmodel import Session

logger = logging.getLogger(__name__)

#: The single action name every chat read is filed under, so a trail query can
#: include or exclude reads with one predicate.
CHAT_READ_ACTION = "chat_read_access"

#: How much of the question is kept. Enough to tell an auditor what was asked;
#: short enough that the trail does not become a second copy of the chat log.
MAX_QUESTION_CHARS = 500


def _resolve_actor(db_session, session_id, actor_user_id: Optional[UUID]) -> Optional[UUID]:
    """The `users.id` to file the read under.

    The synchronous and widget paths know the caller and pass it. The queue worker
    does not -- its job payload carries no identity -- so it is resolved from the
    session's owner (`ChatSession.user_id`, the Clerk id recorded by BE Gap 572)
    rather than by widening the payload at four call sites for one column.
    """
    if actor_user_id is not None:
        return actor_user_id
    try:
        from models import ChatSession, User
        from sqlmodel import select

        chat_session = db_session.get(ChatSession, UUID(str(session_id)))
        clerk_id = getattr(chat_session, "user_id", None) if chat_session else None
        if not clerk_id:
            return None
        return db_session.exec(select(User.id).where(User.clerk_user_id == clerk_id)).first()
    except Exception:  # noqa: BLE001 -- an unknown actor is still worth logging
        logger.debug("chat read audit: could not resolve actor", exc_info=True)
        return None


def record_chat_read_access(
    db_session,
    *,
    tenant_id,
    session_id,
    question: str,
    invoice_ids,
    actor_user_id: Optional[UUID] = None,
    actor_role: str = "user",
    route: Optional[str] = None,
) -> int:
    """Write one `chat_read_access` row per invoice this turn returned.

    Returns the number of rows written; 0 when the turn returned no invoices (an
    ordinary conversational turn reads nothing and is not an access event) or when
    the write failed. Never raises.
    """
    ids = [str(i) for i in (invoice_ids or []) if i]
    if not ids:
        return 0

    # Bound before the try: the handler below references them, and an import or a
    # bad tenant id would otherwise raise NameError inside the error path.
    own_session = None
    write_session = None
    try:
        from models import AuditLog

        tenant_uuid = tenant_id if isinstance(tenant_id, UUID) else UUID(str(tenant_id))
        actor = _resolve_actor(db_session, session_id, actor_user_id)
        details = {
            "session_id": str(session_id),
            "question": (question or "").strip()[:MAX_QUESTION_CHARS],
            "invoice_count": len(ids),
            "route": route,
            "actor_kind": actor_role,
        }

        # Review follow-up 2026-09-17: written on its OWN session, never the
        # caller's. This used to `db_session.commit()`, which ends the caller's
        # transaction from inside a helper -- the exact anti-pattern BE Gap 583 is
        # filed against, and doing it in the audit trail of all places would have
        # committed whatever else the turn had staged. A separate short-lived session
        # also means a trail failure rolls back only the trail.
        #
        # The caller's session is still used for the read above (resolving the actor),
        # which is a read and commits nothing.
        try:
            from database import engine

            own_session = Session(engine)
            write_session = own_session
        except Exception:
            logger.warning("chat read audit: no engine available; nothing written", exc_info=True)
            return 0

        written = 0
        for invoice_id in ids:
            try:
                invoice_uuid = UUID(str(invoice_id))
            except (ValueError, AttributeError, TypeError):
                continue
            write_session.add(
                AuditLog(
                    tenant_id=tenant_uuid,
                    invoice_id=invoice_uuid,
                    actor_user_id=actor,
                    actor_role=(actor_role or "user")[:50],
                    action=CHAT_READ_ACTION,
                    details=details,
                )
            )
            written += 1
        try:
            write_session.commit()
        finally:
            if own_session is not None:
                own_session.close()
        return written
    except Exception:  # noqa: BLE001 -- see the module docstring
        logger.warning("Failed to write chat read-access audit rows", exc_info=True)
        try:
            if write_session is not None:
                write_session.rollback()
                if own_session is not None:
                    own_session.close()
        except Exception:  # pragma: no cover
            pass
        return 0
