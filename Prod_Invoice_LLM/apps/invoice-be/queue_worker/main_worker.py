import os
import json
import time
import logging
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor
from azure.storage.queue import QueueClient
from config import get_settings
from utils.logging_config import setup_structured_logging, tenant_id_ctx, request_id_ctx
from queue_worker.handlers import (
    handle_process_invoice,
    handle_import_connector_file,
    handle_reaudit_templates,
    handle_deliver_webhook,
    handle_process_chat_job,
)
from queue_worker.outbound_handlers import handle_process_outbound_invoice

# Feature 19 (Task 19.3): Structured JSON logging for background worker
setup_structured_logging(service_name="queue-worker")
logger = logging.getLogger(__name__)

# Feature 19 (Task 19.2): OpenTelemetry auto-instrumentation for Azure Monitor Application Insights
appinsights_conn_str = os.getenv("APPLICATIONINSIGHTS_CONNECTION_STRING")
if appinsights_conn_str:
    try:
        from azure.monitor.opentelemetry import configure_azure_monitor
        configure_azure_monitor(
            connection_string=appinsights_conn_str,
            logger_name="invoice_worker_telemetry"
        )
        logger.info("Worker Azure Monitor OpenTelemetry successfully configured.")
    except Exception as e:
        logger.warning(f"Could not configure Worker OpenTelemetry: {e}")

# Concurrent messages processed per container replica (Gap 41/42, Jul 2026).
# The real cost per message is I/O-bound (waiting on Azure OpenAI/Doc
# Intelligence network calls), so threads parallelize it without needing
# proportional CPU. Matched to the OpenAI deployment capacity raise (20->500
# RPM) and the added Doc Intelligence resources (1->3) done alongside this -
# raising this without those would just move the bottleneck to 429s.
MAX_WORKERS = 10
MAX_DEQUEUE_ATTEMPTS = 5
DEAD_LETTER_QUEUE_NAME = "extraction-tasks-deadletter-queue"


# ---------------------------------------------------------------------------
# Gap 42 — Per-tenant fair-share queue throttling
# ---------------------------------------------------------------------------
# All tenants push messages into a single Azure Storage Queue. Without this
# check, a single enterprise tenant uploading a batch of 100+ documents can
# consume all 10 worker threads on every replica, starving smaller tenants.
#
# We use Redis to maintain a dynamic in-flight task counter per tenant.
# If a tenant exceeds PER_TENANT_MAX_INFLIGHT concurrent slots, the worker
# updates the message's visibility timeout (re-queuing it for 5s) so other
# tenants' messages can be processed first.
# ---------------------------------------------------------------------------
PER_TENANT_MAX_INFLIGHT = 3  # Max active worker slots per tenant per replica


def _get_redis_sync():
    """Helper to return a synchronous Redis client for rate-limiting."""
    try:
        import redis
        settings = get_settings()
        if settings.REDIS_URL:
            return redis.Redis.from_url(settings.REDIS_URL, decode_responses=True)
    except Exception as e:
        logger.warning("Redis client unavailable for queue throttling: %s", e)
    return None


def _acquire_tenant_slot(tenant_id: str) -> bool:
    """
    Gap 42: Checks if tenant_id has reached its fair-share processing cap.
    If below cap, increments in-flight count in Redis and returns True.
    If at cap, returns False so the message is re-queued for later.
    """
    if not tenant_id:
        return True

    r = _get_redis_sync()
    if not r:
        return True  # Fallback gracefully if Redis is down

    key = f"inflight:{tenant_id}"
    try:
        current = r.get(key)
        if current and int(current) >= PER_TENANT_MAX_INFLIGHT:
            return False

        r.incr(key)
        r.expire(key, 300)  # 5-min safety TTL to prevent orphaned counters
        return True
    except Exception as e:
        logger.warning("Failed to check/acquire tenant slot in Redis: %s", e)
        return True


def _release_tenant_slot(tenant_id: str) -> None:
    """
    Gap 42: Decrements the in-flight task counter in Redis when processing finishes.
    """
    if not tenant_id:
        return

    r = _get_redis_sync()
    if not r:
        return

    key = f"inflight:{tenant_id}"
    try:
        val = r.decr(key)
        if val <= 0:
            r.delete(key)
    except Exception as e:
        logger.warning("Failed to release tenant slot in Redis: %s", e)


def _route_to_dead_letter_queue(queue_client: QueueClient, msg, error: Exception) -> None:
    """
    Feature 19 (Task 19.4): Dead-Letter Queue (DLQ) poison message isolation.
    When a corrupted or unprocessable payload fails 5 times, it is moved to
    the Dead-Letter Queue ('extraction-tasks-deadletter-queue') and deleted
    from the active processing queue to prevent infinite retry lockup.
    """
    try:
        settings = get_settings()
        conn_str = settings.AZURE_STORAGE_CONNECTION_STRING
        if not conn_str:
            return

        dlq_client = QueueClient.from_connection_string(conn_str, DEAD_LETTER_QUEUE_NAME)
        try:
            dlq_client.create_queue()
        except Exception:
            pass

        try:
            raw_payload = json.loads(msg.content)
        except Exception:
            raw_payload = msg.content

        dlq_payload = {
            "original_message_id": msg.id,
            "dequeue_count": getattr(msg, "dequeue_count", MAX_DEQUEUE_ATTEMPTS),
            "error_type": type(error).__name__,
            "error_message": str(error),
            "failed_at": datetime.now(timezone.utc).isoformat(),
            "payload": raw_payload,
        }

        dlq_client.send_message(json.dumps(dlq_payload))
        # Purge from primary queue so worker can continue processing other messages
        queue_client.delete_message(msg.id, msg.pop_receipt)
        logger.error(
            f"POISON MESSAGE ISOLATED: Message {msg.id} failed {getattr(msg, 'dequeue_count', MAX_DEQUEUE_ATTEMPTS)} times. "
            f"Moved to Dead-Letter Queue '{DEAD_LETTER_QUEUE_NAME}' and purged from main queue.",
            extra={"extra_fields": {"action": "moved_to_deadletter_queue", "dlq": DEAD_LETTER_QUEUE_NAME, "message_id": msg.id}},
        )
    except Exception as dlq_err:
        logger.critical(f"Failed to route poison message {msg.id} to DLQ: {dlq_err}", exc_info=True)


def _process_message(queue_client: QueueClient, msg) -> None:
    """Handles one queue message end-to-end; never raises - a failure here
    must not crash the worker thread silently, since the caller (a
    ThreadPoolExecutor future) would otherwise swallow the exception until
    someone calls .result()."""
    tenant_id = None
    slot_acquired = False
    try:
        request_id_ctx.set(f"worker-{msg.id}")
        payload = json.loads(msg.content)
        task_name = payload.get("task")
        kwargs = payload.get("kwargs", {})
        tenant_id = kwargs.get("tenant_id")
        if tenant_id:
            tenant_id_ctx.set(tenant_id)

        # Gap 42: Check per-tenant fair-share throttle limit
        if tenant_id and not _acquire_tenant_slot(tenant_id):
            logger.info(
                f"Tenant {tenant_id} at concurrent capacity ({PER_TENANT_MAX_INFLIGHT}). "
                f"Re-queuing message {msg.id} for fair-share scheduling."
            )
            # Postpone message visibility by 5s so another tenant's message can process
            queue_client.update_message(msg.id, msg.pop_receipt, visibility_timeout=5)
            return

        slot_acquired = True
        logger.info(f"Received task {task_name} with args {kwargs}")

        if task_name == "process_invoice":
            handle_process_invoice(
                batch_id=kwargs.get("batch_id"),
                file_path=kwargs.get("file_path"),
                tenant_id=tenant_id
            )
        elif task_name == "process_outbound_invoice":
            handle_process_outbound_invoice(
                batch_id=kwargs.get("batch_id"),
                file_path=kwargs.get("file_path"),
                tenant_id=tenant_id
            )
        elif task_name == "import_connector_file":
            handle_import_connector_file(
                provider=kwargs.get("provider"),
                file_id=kwargs.get("file_id"),
                tenant_id=tenant_id,
                direction=kwargs.get("direction", "inbound"),
            )
        elif task_name == "reaudit_templates":
            handle_reaudit_templates(
                tenant_id=tenant_id,
                vendor_name=kwargs.get("vendor_name")
            )
        elif task_name == "deliver_webhook":
            # Gap 194: outbound webhook delivery. Runs here rather than inline
            # in the thread that committed the invoice, so a slow subscriber
            # (up to ~19s of retries/backoff) can't back-pressure ingestion.
            handle_deliver_webhook(
                tenant_id=tenant_id,
                subscription_id=kwargs.get("subscription_id"),
                event_type=kwargs.get("event_type"),
                payload=kwargs.get("payload") or {},
            )
        elif task_name == "process_chat_job":
            # Gap 280: Asynchronous chat processing via queue-worker
            handle_process_chat_job(
                job_id=kwargs.get("job_id"),
                session_id=kwargs.get("session_id"),
                user_msg_id=kwargs.get("user_msg_id"),
                content=kwargs.get("content"),
                tenant_id=tenant_id,
                # E-5 / Feature 26 task H7. The third dispatch site -- the queue
                # payload carries the key and the handler accepts it, but the
                # worker is what actually reads one and calls the other, so
                # missing it here would drop the attachment as silently as not
                # carrying it at all. `.get()` so a pre-H7 message still in the
                # queue at deploy time is processed as an ordinary chat turn
                # rather than raising.
                attachment_id=kwargs.get("attachment_id"),
            )
        else:
            logger.warning(f"Unknown task {task_name}")

        # Delete message after successful processing
        queue_client.delete_message(msg.id, msg.pop_receipt)
        logger.info(f"Task {task_name} completed and deleted from queue.")

    except Exception as ex:
        dequeue_count = getattr(msg, "dequeue_count", 1)
        logger.error(
            f"Error processing message {msg.id} (attempt {dequeue_count}/{MAX_DEQUEUE_ATTEMPTS}): {ex}",
            exc_info=True,
            extra={"extra_fields": {"message_id": msg.id, "dequeue_count": dequeue_count, "error": str(ex)}},
        )
        # Feature 19 (Task 19.4): If attempts >= 5, route to Dead-Letter Queue to unblock queue
        if dequeue_count >= MAX_DEQUEUE_ATTEMPTS:
            _route_to_dead_letter_queue(queue_client, msg, ex)
    finally:
        if slot_acquired and tenant_id:
            _release_tenant_slot(tenant_id)


def _process_redis_chat_tasks(executor: ThreadPoolExecutor) -> None:
    """Gap 280: Drains in-flight chat jobs from Redis chat_tasks_queue."""
    r = _get_redis_sync()
    if not r:
        return
    try:
        # Check for queued chat tasks in Redis
        raw = r.rpop("chat_tasks_queue")
        if raw:
            data = json.loads(raw)
            executor.submit(
                handle_process_chat_job,
                job_id=data.get("job_id"),
                session_id=data.get("session_id"),
                user_msg_id=data.get("user_msg_id"),
                content=data.get("content"),
                tenant_id=data.get("tenant_id"),
            )
    except Exception as e:
        logger.warning("Error consuming Redis chat task: %s", e)


def poll_queue():
    settings = get_settings()
    conn_str = settings.AZURE_STORAGE_CONNECTION_STRING
    queue_name = "extraction-tasks-queue"

    if not conn_str:
        logger.error("AZURE_STORAGE_CONNECTION_STRING is missing. Checking Redis queue only.")
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            while True:
                _process_redis_chat_tasks(executor)
                time.sleep(1)
        return

    queue_client = QueueClient.from_connection_string(conn_str, queue_name)

    try:
        # Create queue if it doesn't exist
        queue_client.create_queue()
    except Exception as e:
        # Queue might already exist
        pass

    logger.info(f"Starting to poll Azure Storage Queue: {queue_name} (max {MAX_WORKERS} concurrent)")

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        while True:
            try:
                # Gap 280: Poll Redis chat queue
                _process_redis_chat_tasks(executor)

                # Poll for up to MAX_WORKERS messages at once and process them
                # concurrently. QueueClient is documented safe for concurrent
                # use across threads (delete_message() per-message uses each
                # message's own pop_receipt, so there's no shared mutable
                # state between threads here).
                messages = queue_client.receive_messages(messages_per_page=MAX_WORKERS, visibility_timeout=300)
                batch = list(messages)

                if batch:
                    futures = [executor.submit(_process_message, queue_client, msg) for msg in batch]
                    for future in futures:
                        future.result()  # propagate nothing (errors handled inside), just wait for the batch

                # Short sleep to prevent tight loop if queue is empty
                time.sleep(2)

            except Exception as e:
                logger.error(f"Error communicating with Azure Storage Queue: {e}")
                time.sleep(10)


if __name__ == "__main__":
    poll_queue()

