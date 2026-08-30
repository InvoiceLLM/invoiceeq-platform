"""
Feature 25 (Gap 340): delete expired, unclaimed sandbox workspaces.

Usage:
    uv run python scripts/sweep_sandbox_tenants.py [--dry-run]

Follows scripts/sweep_billing_lifecycle.py (Gaps 119/121) exactly -- same
`sys.path` bootstrap, same `--dry-run` first argument, same "report what would
change without writing anything" contract, same logging shape. That script is
invoked daily by an Azure Container Apps Job
(infra/modules/compute/billing-lifecycle-job.bicep); this one is meant to be
scheduled the same way.

WHY A REAPER EXISTS AT ALL, GIVEN THE KEY ALREADY STOPS WORKING
---------------------------------------------------------------
`dependencies.resolve_api_key_context()` refuses an expired sandbox key on every
request, so authentication is already closed the moment the TTL passes and does
not depend on this script running. What this script does is the *other* half:
without it, every "try it" click on the marketing site leaves a permanent
`Tenant` row, a permanent `SandboxTenant` row, and whatever invoices, chat
sessions and blobs the visitor created, forever. Those rows also keep counting
against the global unclaimed cap (`unclaimed_sandbox_count()` counts unclaimed
rows regardless of expiry, deliberately), so an unreaped backlog would
eventually make issuance fail closed for everyone.

So: expiry is enforced twice, on purpose. The auth check is what makes the key
*stop working*; this is what makes the workspace *go away*. A soft flag that
only one of the two reads is what the security review specifically asked this
not to be.

WHAT IT DELETES, AND WHAT IT REFUSES TO TOUCH
---------------------------------------------
Only sandbox rows with `claimed_at IS NULL` and `expires_at <= now`. A **claimed**
sandbox is an ordinary customer workspace -- it has a real Clerk org, a real
`inv_live_` key and a real owner -- and `services/sandbox.py::sandbox_is_expired()`
returns False for it for exactly that reason. Deleting a claimed workspace would
be deleting a customer's data, which is the one failure this script must not
have, so the predicate is checked in the query AND asserted per row below.
"""
import argparse
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlmodel import Session, select  # noqa: E402

from database import engine  # noqa: E402
from models import (  # noqa: E402
    ChatFeedback,
    ChatMessage,
    ChatSession,
    Invoice,
    SandboxTenant,
    Tenant,
    TenantWorkflowConfig,
)
from services.sandbox import expired_unclaimed_sandboxes  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def _purge_sandbox(session: Session, sandbox: SandboxTenant) -> dict:
    """Delete one sandbox workspace and everything scoped to it.

    Rows are removed child-first because `SandboxTenant`, `Invoice` and
    `TenantWorkflowConfig` all carry a foreign key to `tenant.id` -- dropping
    the tenant first is a ForeignKeyViolation on Postgres (and, on SQLite, a
    silent orphan, which is worse).

    Chat is deleted through its own chain (`ChatSession` -> `ChatMessage` ->
    `ChatFeedback`) rather than by tenant id, because `ChatMessage` is scoped by
    `session_id` and not by tenant -- the same asymmetry
    `routers/auth.py::_TENANT_SCOPED_TABLES` records and
    `routers/chat.py::delete_session()` already walks.

    Deliberately NOT deleted: the blob in storage behind `Invoice.file_path`.
    Blob cleanup is not something this backend does anywhere yet (no existing
    delete path removes one either -- `DELETE /invoices/{id}` is a soft delete),
    and inventing a storage-deleting code path inside a sweep job is a much
    larger change than this gap. Recorded as a known residue rather than left
    implicit; see the feature doc's "Not done, and not claimed".
    """
    counts = {"chat_sessions": 0, "chat_messages": 0, "chat_feedback": 0, "invoices": 0}
    tenant_id = sandbox.tenant_id

    sessions = session.exec(
        select(ChatSession).where(ChatSession.tenant_id == tenant_id)
    ).all()
    for chat_session in sessions:
        messages = session.exec(
            select(ChatMessage).where(ChatMessage.session_id == chat_session.id)
        ).all()
        for message in messages:
            for feedback in session.exec(
                select(ChatFeedback).where(ChatFeedback.message_id == message.id)
            ).all():
                session.delete(feedback)
                counts["chat_feedback"] += 1
            session.delete(message)
            counts["chat_messages"] += 1
        session.delete(chat_session)
        counts["chat_sessions"] += 1

    for feedback in session.exec(
        select(ChatFeedback).where(ChatFeedback.tenant_id == tenant_id)
    ).all():
        session.delete(feedback)

    for invoice in session.exec(
        select(Invoice).where(Invoice.tenant_id == tenant_id)
    ).all():
        session.delete(invoice)
        counts["invoices"] += 1

    for config in session.exec(
        select(TenantWorkflowConfig).where(TenantWorkflowConfig.tenant_id == tenant_id)
    ).all():
        session.delete(config)

    session.delete(sandbox)
    session.flush()

    tenant = session.get(Tenant, tenant_id)
    if tenant is not None:
        session.delete(tenant)

    session.commit()
    return counts


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Delete expired, unclaimed sandbox workspaces (Gap 340)."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report what would be deleted without writing anything.",
    )
    args = parser.parse_args()

    with Session(engine) as session:
        expired = expired_unclaimed_sandboxes(session)

        if args.dry_run:
            for sandbox in expired:
                logger.info(
                    "[dry-run] would delete sandbox tenant=%s expired_at=%s "
                    "chat_messages_used=%s",
                    sandbox.tenant_id, sandbox.expires_at, sandbox.chat_messages_used,
                )
            logger.info("[dry-run] sandbox reap: %s workspace(s) expired.", len(expired))
            return 0

        reaped = 0
        for sandbox in expired:
            # Re-asserted per row rather than trusted from the query: this loop
            # deletes a whole workspace, and "it was in the list" is not a good
            # enough reason to do that to a claimed one.
            if sandbox.claimed_at is not None:
                logger.warning(
                    "sandbox reap: skipping tenant=%s -- it is claimed.",
                    sandbox.tenant_id,
                )
                continue
            tenant_id = sandbox.tenant_id
            try:
                counts = _purge_sandbox(session, sandbox)
            except Exception as exc:
                # One bad workspace must not abort the sweep for the rest.
                session.rollback()
                logger.error("sandbox reap: failed for tenant=%s: %r", tenant_id, exc)
                continue
            reaped += 1
            logger.info(
                "Deleted sandbox tenant=%s (invoices=%s chat_sessions=%s "
                "chat_messages=%s)",
                tenant_id, counts["invoices"], counts["chat_sessions"],
                counts["chat_messages"],
            )

        logger.info(
            "Sandbox sweep complete: %s of %s expired workspace(s) deleted.",
            reaped, len(expired),
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
