"""BE Gap 605 (CH-39): Sweep and reap stuck or orphaned chat turns.

Usage:
    uv run python scripts/sweep_stuck_chat_turns.py [--dry-run] [--max-age-seconds 300]

Background reaper for ChatMessage rows stuck in 'queued' or 'processing'
status when worker pods crash (SIGKILL, OOM, host failure). Marks stuck
messages as 'failed', publishes failure notice to SSE channel so the frontend
loading spinner resolves, and releases tenant Redis concurrency slots.
"""
import argparse
import logging
import os
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlmodel import Session, select  # noqa: E402

from database import engine  # noqa: E402
from models import ChatMessage, ChatSession  # noqa: E402
from services.chat_queue import ChatQueueService, get_redis_client  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def reap_stuck_chat_jobs(
    session: Session,
    max_age_seconds: int = 300,
    dry_run: bool = False,
    redis_client=None,
) -> dict:
    """Finds ChatMessage rows stuck in 'queued' or 'processing' older than
    `max_age_seconds`, transitions them to 'failed', and releases their
    concurrency slots in Redis (BE Gap 605)."""
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(seconds=max_age_seconds)

    r = redis_client or get_redis_client()

    statement = (
        select(ChatMessage, ChatSession.tenant_id)
        .join(ChatSession, ChatMessage.session_id == ChatSession.id)
        .where(
            ChatMessage.status.in_(["queued", "processing"]),
            ChatMessage.created_at <= cutoff,
        )
    )

    results = session.exec(statement).all()
    reaped_count = 0
    reaped_details = []

    for msg, tenant_id in results:
        reaped_count += 1
        age_s = (now - msg.created_at.replace(tzinfo=timezone.utc)).total_seconds() if msg.created_at else max_age_seconds
        details = {
            "message_id": str(msg.id),
            "job_id": msg.job_id,
            "tenant_id": str(tenant_id),
            "status": msg.status,
            "age_seconds": round(age_s, 1),
        }
        reaped_details.append(details)

        if dry_run:
            logger.info("[DRY RUN] Would reap stuck chat message %s (job %s, tenant %s, age %.1fs)", msg.id, msg.job_id, tenant_id, age_s)
        else:
            logger.info("Reaping stuck chat message %s (job %s, tenant %s, age %.1fs)", msg.id, msg.job_id, tenant_id, age_s)
            msg.status = "failed"
            msg.error_message = "Turn timed out or worker process terminated (reaped by background sweeper)"
            session.add(msg)

            if msg.job_id and tenant_id:
                try:
                    ChatQueueService.fail_job(
                        job_id=msg.job_id,
                        tenant_id=str(tenant_id),
                        error_message=msg.error_message,
                        client=r,
                    )
                except Exception as e:
                    logger.warning("Could not fail Redis job %s during reap: %s", msg.job_id, e)

    if not dry_run and reaped_count > 0:
        session.commit()
        logger.info("Successfully reaped %d stuck chat turns", reaped_count)
    elif dry_run:
        logger.info("[DRY RUN] Found %d stuck chat turns to reap", reaped_count)

    return {
        "reaped_count": reaped_count,
        "dry_run": dry_run,
        "max_age_seconds": max_age_seconds,
        "jobs": reaped_details,
    }


def main():
    parser = argparse.ArgumentParser(description="Sweep stuck chat jobs and release concurrency slots")
    parser.add_argument("--dry-run", action="store_true", help="Report stuck jobs without modifying DB or Redis")
    parser.add_argument("--max-age-seconds", type=int, default=300, help="Age threshold in seconds (default: 300)")
    args = parser.parse_args()

    if not engine:
        logger.error("Database engine is not initialized.")
        sys.exit(1)

    with Session(engine) as session:
        reap_stuck_chat_jobs(session=session, max_age_seconds=args.max_age_seconds, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
