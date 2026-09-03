"""Delete chat attachments past their TTL — Feature 26 decision E-7, task H8.

    uv run python scripts/sweep_chat_attachments.py [--dry-run] [--limit N]

WHY THIS EXISTS. Chat attachments are **the first thing in this system with a
genuine finite lifetime.** Invoice chunks deliberately have none —
`delete_invoice_chunks()` exists but is intentionally unwired from soft delete so
a restored invoice keeps its chunks. An attachment is different: it is a
transient artifact of one conversation, it has a vector footprint in a SECOND
Chroma collection (`chat_docs_{tenant_id}`), and until this script nothing ever
removed it. E-2's own H2 build note records that
`scripts/reembed_chroma_collections.py` scans `invoice_chunks_` only and is
structurally blind to `chat_docs_*`, so an orphaned collection was cleaned up by
**nothing**.

THREE THINGS ARE DELETED PER ROW, and the order matters. Chunks first, then the
blob, then the row: each step is best-effort and logged, and the row is removed
last so a crash mid-sweep leaves a row that will simply be swept again rather
than an orphaned blob or chunk set with nothing pointing at it. Deleting the row
first would make the other two unreachable forever.

`expires_at IS NULL` MEANS KEEP, NEVER "EXPIRED AT THE EPOCH". H4's build note
flags this explicitly and it is the one mistake that would be catastrophic here:
every Part 1 attachment predates the column, so the opposite reading deletes the
entire back catalogue on the first run. The query below filters
`expires_at IS NOT NULL AND expires_at <= now`, which cannot express that error.

Modelled on `scripts/sweep_sandbox_tenants.py` — same `sys.path` bootstrap, same
`--dry-run` first argument, same "report what would happen" contract.
"""
import argparse
import logging
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlmodel import Session, select  # noqa: E402

from database import engine  # noqa: E402
from models import ChatAttachment  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def expired_attachments(session: Session, limit: int | None = None):
    """Rows past their TTL, oldest first.

    `expires_at IS NOT NULL` is the load-bearing half of this predicate. A NULL
    means the row was created before the column existed (every Part 1
    attachment) or under a policy that set no expiry — either way it is KEEP.
    Writing this as `expires_at <= now` alone would be true for NULL in some
    dialects and, worse, reads as though NULL were an ancient date.

    Oldest first so a `--limit`ed run makes progress on the genuine backlog
    rather than repeatedly taking whatever the database returned first.
    """
    # `utcnow()` deliberately, despite the DeprecationWarning. Every datetime
    # column in `models.py` is NAIVE UTC (`default_factory=datetime.utcnow`), so
    # `datetime.now(UTC)` would produce an aware value and comparing aware to
    # naive raises TypeError. Changing the convention is a repo-wide migration,
    # not something to smuggle into a sweeper.
    statement = (
        select(ChatAttachment)
        .where(
            ChatAttachment.expires_at.is_not(None),
            ChatAttachment.expires_at <= datetime.utcnow(),
        )
        .order_by(ChatAttachment.expires_at.asc())
    )
    if limit:
        statement = statement.limit(limit)
    return session.exec(statement).all()


def purge_attachment(session: Session, row: ChatAttachment, dry_run: bool = False) -> dict:
    """Remove one attachment's chunks, blob and row. Best-effort per step.

    Every step is individually guarded because they fail independently and for
    different reasons: Chroma may be unreachable, a blob may already be gone from
    a previous partial run, and neither is a reason to leave the row behind
    forever. A failure logs at ERROR and the sweep continues — the alternative is
    one unreachable dependency stopping the whole cleanup, which is how unbounded
    growth starts.
    """
    outcome = {
        "attachment_id": str(row.id),
        "tenant_id": str(row.tenant_id),
        "expires_at": row.expires_at.isoformat() if row.expires_at else None,
        "chunks_deleted": False,
        "blob_deleted": False,
        "row_deleted": False,
    }
    if dry_run:
        return outcome

    # 1. Chunks. `delete_attachment_chunks()` has existed since H3 (Gap 373) and
    #    has been called by nothing except the two session-delete paths; this is
    #    the caller E-7 always intended for it.
    try:
        from services.chat_document_search import delete_attachment_chunks

        delete_attachment_chunks(row.id, row.tenant_id)
        outcome["chunks_deleted"] = True
    except Exception as e:
        logger.error("Chunk delete failed for attachment %s: %s", row.id, e)

    # 2. Blob.
    try:
        if row.blob_path:
            from services.storage import delete_pdf_from_storage

            delete_pdf_from_storage(row.blob_path)
        outcome["blob_deleted"] = True
    except Exception as e:
        logger.error("Blob delete failed for attachment %s (%s): %s", row.id, row.blob_path, e)

    # 3. The row, last -- see the module docstring on ordering.
    try:
        session.delete(row)
        outcome["row_deleted"] = True
    except Exception as e:
        logger.error("Row delete failed for attachment %s: %s", row.id, e)

    return outcome


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Delete chat attachments past their expires_at (Feature 26 E-7).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="report what would be deleted and change nothing.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="cap how many rows this run touches. The first run against a "
             "long-lived environment may have a large backlog, and a bounded "
             "first pass is easier to inspect than an unbounded one.",
    )
    args = parser.parse_args()

    with Session(engine) as session:
        rows = expired_attachments(session, limit=args.limit)
        if not rows:
            logger.info("No chat attachments past their TTL. Nothing to do.")
            return 0

        logger.info(
            "%s %d expired chat attachment(s)%s",
            "Would delete" if args.dry_run else "Deleting",
            len(rows),
            " (dry run)" if args.dry_run else "",
        )
        outcomes = [purge_attachment(session, row, dry_run=args.dry_run) for row in rows]

        if args.dry_run:
            for o in outcomes:
                logger.info(
                    "  would delete attachment %s (tenant %s, expired %s)",
                    o["attachment_id"], o["tenant_id"], o["expires_at"],
                )
            return 0

        session.commit()
        complete = sum(1 for o in outcomes if all(
            (o["chunks_deleted"], o["blob_deleted"], o["row_deleted"])
        ))
        logger.info(
            "Deleted %d attachment(s); %d fully clean, %d had at least one "
            "best-effort step fail (logged above, and the row is gone either way "
            "-- a leftover blob or chunk set is inspectable, an undeletable row "
            "would grow forever).",
            len(outcomes), complete, len(outcomes) - complete,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
