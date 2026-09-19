"""
BE Gap 680 Part 3: Dead-Letter Queue (DLQ) replay, inspection, and purge CLI script.

Allows operators to inspect poisoned/failed extraction messages in the dead-letter queue,
requeue them back into the active extraction queue for reprocessing, or purge them.

Usage:
    # Inspect messages currently in the DLQ (default action: peek without removing)
    python scripts/replay_deadletter_queue.py --action inspect [--limit 20]

    # Requeue all or specific messages back to extraction-tasks-queue
    python scripts/replay_deadletter_queue.py --action requeue [--limit 10] [--dry-run]
    python scripts/replay_deadletter_queue.py --action requeue --invoice-id <uuid>
    python scripts/replay_deadletter_queue.py --action requeue --message-id <id>

    # Purge messages from DLQ
    python scripts/replay_deadletter_queue.py --action purge --message-id <id>
    python scripts/replay_deadletter_queue.py --action purge --all [--dry-run]
"""
import argparse
import json
import logging
import os
import re
import sys
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import get_settings  # noqa: E402
from azure.storage.queue import QueueClient  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("replay_deadletter_queue")

DEFAULT_DLQ_NAME = "extraction-tasks-deadletter-queue"
DEFAULT_PRIMARY_QUEUE = "extraction-tasks-queue"


def parse_dlq_message(content: str) -> Dict[str, Any]:
    """Extracts envelope fields and unwraps inner payload from DLQ message body."""
    try:
        data = json.loads(content)
    except Exception:
        return {"raw_content": content, "payload": content}

    if isinstance(data, dict):
        return data
    return {"payload": data}


_UUID_IN_PATH = re.compile(r"/invoices/([0-9a-fA-F-]{36})\.pdf$")


def payload_ids(raw_payload: Any) -> Dict[str, Optional[str]]:
    """The identifiers an operator filters by, read from the ORIGINAL queue payload.

    Review fix (BE Gap 680): worker messages are `{"task": ..., "kwargs": {...}}` and a
    `process_invoice` message carries no `invoice_id` at all -- only `batch_id`,
    `file_path` and `tenant_id`. The invoice id is recovered from an upload path
    (`tenants/<tenant>/invoices/<invoice_id>.pdf`) when `kwargs` has none.
    """
    payload = raw_payload
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except Exception:
            payload = {}
    if not isinstance(payload, dict):
        payload = {}
    kwargs = payload.get("kwargs") if isinstance(payload.get("kwargs"), dict) else {}

    def pick(key: str) -> Optional[str]:
        value = kwargs.get(key, payload.get(key))
        return str(value) if value not in (None, "") else None

    invoice_id = pick("invoice_id")
    file_path = pick("file_path")
    if invoice_id is None and file_path:
        match = _UUID_IN_PATH.search(file_path)
        invoice_id = match.group(1) if match else None
    return {
        "task": pick("task"),
        "tenant_id": pick("tenant_id"),
        "batch_id": pick("batch_id"),
        "file_path": file_path,
        "invoice_id": invoice_id,
    }


def inspect_dlq(
    conn_str: str,
    dlq_name: str = DEFAULT_DLQ_NAME,
    limit: int = 20,
) -> List[Dict[str, Any]]:
    """Peeks at messages in DLQ without removing or updating visibility."""
    if not conn_str:
        logger.error("Storage connection string is not configured.")
        return []

    client = QueueClient.from_connection_string(conn_str, dlq_name)
    try:
        peeked_messages = client.peek_messages(max_messages=min(limit, 32))
    except Exception as e:
        logger.error("Failed to peek DLQ messages from %s: %s", dlq_name, e)
        return []

    results = []
    for msg in peeked_messages:
        parsed = parse_dlq_message(msg.content)
        raw_payload = parsed.get("payload", {})
        ids = payload_ids(raw_payload)

        summary = {
            "message_id": msg.id,
            "insertion_time": msg.insertion_time.isoformat() if msg.insertion_time else None,
            "dequeue_count": getattr(msg, "dequeue_count", None),
            "original_message_id": parsed.get("original_message_id"),
            "error_type": parsed.get("error_type"),
            "error_message": parsed.get("error_message"),
            "failed_at": parsed.get("failed_at"),
            **ids,
            "payload": raw_payload,
        }
        results.append(summary)

    return results


def requeue_messages(
    conn_str: str,
    dlq_name: str = DEFAULT_DLQ_NAME,
    target_queue: str = DEFAULT_PRIMARY_QUEUE,
    limit: int = 10,
    message_id: Optional[str] = None,
    invoice_id: Optional[str] = None,
    dry_run: bool = False,
    batch_id: Optional[str] = None,
    tenant_id: Optional[str] = None,
    task: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Receives poisoned messages from DLQ and requeues their payload to primary queue.

    A message is deleted from the DLQ only after its payload was sent to the target
    queue; a failed send leaves it in the DLQ and moves on to the next message.
    Messages received but filtered out stay invisible for the 60 s visibility window.
    """
    if not conn_str:
        logger.error("Storage connection string is not configured.")
        return []

    dlq_client = QueueClient.from_connection_string(conn_str, dlq_name)
    target_client = QueueClient.from_connection_string(conn_str, target_queue)

    if not dry_run:
        try:
            target_client.create_queue()
        except Exception:
            pass

    try:
        received = dlq_client.receive_messages(messages_per_page=min(limit, 32), visibility_timeout=60)
    except Exception as e:
        logger.error("Failed to receive messages from DLQ %s: %s", dlq_name, e)
        return []

    requeued = []
    for msg in received:
        parsed = parse_dlq_message(msg.content)
        raw_payload = parsed.get("payload", {})
        ids = payload_ids(raw_payload)
        current_inv_id = ids["invoice_id"]

        # Filter if requested
        if message_id and msg.id != message_id and parsed.get("original_message_id") != message_id:
            continue
        if invoice_id and current_inv_id != str(invoice_id):
            continue
        if batch_id and ids["batch_id"] != str(batch_id):
            continue
        if tenant_id and ids["tenant_id"] != str(tenant_id):
            continue
        if task and ids["task"] != task:
            continue

        # Prepare message body to requeue into target
        if isinstance(raw_payload, (dict, list)):
            body = json.dumps(raw_payload)
        else:
            body = str(raw_payload)

        status = "dry_run_requeued"
        if dry_run:
            logger.info("[dry-run] Would requeue msg %s (invoice %s) to %s and delete from DLQ", msg.id, current_inv_id, target_queue)
        else:
            try:
                target_client.send_message(body)
            except Exception as send_err:
                logger.error("Requeue send failed for msg %s; left in DLQ: %s", msg.id, send_err)
                status = "send_failed"
            else:
                try:
                    dlq_client.delete_message(msg.id, msg.pop_receipt)
                    status = "requeued"
                    logger.info("Requeued msg %s (invoice %s) to %s", msg.id, current_inv_id, target_queue)
                except Exception as del_err:
                    # Sent but not removed: it will be visible in the DLQ again. Say so.
                    logger.error("Requeued msg %s but could not delete it from the DLQ: %s", msg.id, del_err)
                    status = "requeued_not_deleted"

        requeued.append({
            "dlq_message_id": msg.id,
            **ids,
            "target_queue": target_queue,
            "status": status,
        })

        if len(requeued) >= limit:
            break

    return requeued


def purge_messages(
    conn_str: str,
    dlq_name: str = DEFAULT_DLQ_NAME,
    message_id: Optional[str] = None,
    purge_all: bool = False,
    limit: int = 10,
    dry_run: bool = False,
) -> int:
    """Purges messages from DLQ."""
    if not conn_str:
        logger.error("Storage connection string is not configured.")
        return 0

    dlq_client = QueueClient.from_connection_string(conn_str, dlq_name)

    if purge_all:
        if dry_run:
            logger.info("[dry-run] Would purge all messages in DLQ %s", dlq_name)
            return 0
        try:
            dlq_client.clear_messages()
            logger.info("Purged all messages from DLQ %s", dlq_name)
            return 1
        except Exception as e:
            logger.error("Failed to clear messages from DLQ %s: %s", dlq_name, e)
            return 0

    try:
        received = dlq_client.receive_messages(messages_per_page=min(limit, 32), visibility_timeout=60)
    except Exception as e:
        logger.error("Failed to receive messages for purge from DLQ: %s", e)
        return 0

    purged_count = 0
    for msg in received:
        parsed = parse_dlq_message(msg.content)
        if message_id and msg.id != message_id and parsed.get("original_message_id") != message_id:
            continue

        if dry_run:
            logger.info("[dry-run] Would delete message %s from DLQ", msg.id)
        else:
            dlq_client.delete_message(msg.id, msg.pop_receipt)
            logger.info("Deleted message %s from DLQ", msg.id)
        purged_count += 1

        if message_id:
            break

    return purged_count


def main() -> int:
    parser = argparse.ArgumentParser(description="Replay, inspect, or purge Dead-Letter Queue (DLQ) messages.")
    parser.add_argument(
        "--action",
        choices=["inspect", "requeue", "purge"],
        default="inspect",
        help="Action to perform: inspect (peek), requeue (send back to main queue), or purge (delete).",
    )
    parser.add_argument("--dlq-name", default=DEFAULT_DLQ_NAME, help="DLQ queue name (default: extraction-tasks-deadletter-queue)")
    parser.add_argument("--target-queue", default=DEFAULT_PRIMARY_QUEUE, help="Target queue for requeue (default: extraction-tasks-queue)")
    parser.add_argument("--limit", type=int, default=20, help="Maximum number of messages to process (default: 20)")
    parser.add_argument("--message-id", help="Filter or target a specific message ID")
    parser.add_argument("--invoice-id", help="Filter or target a specific invoice UUID")
    parser.add_argument("--batch-id", help="Filter requeue to one upload batch")
    parser.add_argument("--tenant-id", help="Filter requeue to one tenant")
    parser.add_argument("--task", help="Filter requeue to one task name, e.g. process_invoice or import_connector_file")
    parser.add_argument("--all", action="store_true", help="Apply action (such as purge) to all messages")
    parser.add_argument("--dry-run", action="store_true", help="Show what would happen without modifying queues")
    args = parser.parse_args()

    settings = get_settings()
    conn_str = settings.AZURE_STORAGE_CONNECTION_STRING
    if not conn_str:
        logger.error("AZURE_STORAGE_CONNECTION_STRING is not set.")
        return 2

    if args.action == "inspect":
        items = inspect_dlq(conn_str, dlq_name=args.dlq_name, limit=args.limit)
        logger.info("Found %d message(s) in DLQ '%s':", len(items), args.dlq_name)
        for idx, item in enumerate(items, 1):
            logger.info(
                "[%d] msg_id=%s invoice_id=%s error=%s: %s (failed_at=%s)",
                idx,
                item["message_id"],
                item["invoice_id"],
                item["error_type"],
                item["error_message"],
                item["failed_at"],
            )
        return 0

    elif args.action == "requeue":
        requeued = requeue_messages(
            conn_str,
            dlq_name=args.dlq_name,
            target_queue=args.target_queue,
            limit=args.limit,
            message_id=args.message_id,
            invoice_id=args.invoice_id,
            dry_run=args.dry_run,
            batch_id=args.batch_id,
            tenant_id=args.tenant_id,
            task=args.task,
        )
        done = sum(1 for r in requeued if r["status"] in ("requeued", "dry_run_requeued"))
        logger.info("Requeued %d of %d matching message(s) from DLQ to '%s'.", done, len(requeued), args.target_queue)
        return 0

    elif args.action == "purge":
        if not args.all and not args.message_id:
            logger.error("Purge requires either --all or --message-id to prevent accidental data loss.")
            return 2
        count = purge_messages(
            conn_str,
            dlq_name=args.dlq_name,
            message_id=args.message_id,
            purge_all=args.all,
            limit=args.limit,
            dry_run=args.dry_run,
        )
        logger.info("Purged %d message(s) from DLQ '%s'.", count, args.dlq_name)
        return 0

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
