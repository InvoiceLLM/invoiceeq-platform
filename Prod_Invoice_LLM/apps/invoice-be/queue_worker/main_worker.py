import os
import json
import time
import logging
import threading
from datetime import datetime, timezone
from typing import Optional
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
from azure.storage.queue import QueueClient
from config import get_settings
from utils.logging_config import setup_structured_logging, tenant_id_ctx, request_id_ctx
from queue_worker.handlers import (
    handle_extract_attachment,
    handle_insight_job,  # Feature 30 30.2
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
VISIBILITY_TIMEOUT_SECONDS = 120  # BE Gap 677 / Decision D8: 120s message timeout
HEARTBEAT_INTERVAL_SECONDS = 45.0  # BE Gap 677 / Decision D8: renewed every 45s


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
    Feature 19 (Task 19.4) & BE Gap 680 Part 1: Dead-Letter Queue (DLQ) poison message isolation.
    When a corrupted or unprocessable payload fails 5 times, it is moved to
    the Dead-Letter Queue ('extraction-tasks-deadletter-queue') and deleted
    from the active processing queue to prevent infinite retry lockup.
    """
    try:
        settings = get_settings()
        conn_str = settings.AZURE_STORAGE_CONNECTION_STRING

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

        # 1. Copy to the Dead-Letter Queue. BE Gap 680 (teammate finding): this used to
        # `return` when the connection string was empty -- the message was neither
        # isolated nor purged and retried forever. The DLQ client now falls back to the
        # same storage account the main queue client is already talking to.
        dlq_copied = False
        try:
            if conn_str:
                dlq_client = QueueClient.from_connection_string(conn_str, DEAD_LETTER_QUEUE_NAME)
            else:
                account_url = queue_client.url.split("?")[0].rsplit("/", 1)[0]
                dlq_client = QueueClient(account_url=account_url, queue_name=DEAD_LETTER_QUEUE_NAME,
                                         credential=queue_client.credential)
            try:
                dlq_client.create_queue()
            except Exception:
                pass
            dlq_client.send_message(json.dumps(dlq_payload))
            dlq_copied = True
        except Exception as dlq_send_err:
            # BE Gap 680: never delete a message that was not copied -- deleting it here
            # would lose the customer's job with no copy anywhere. It stays on the main
            # queue, becomes visible again, and the next failure retries this routing.
            logger.critical(
                f"POISON MESSAGE ROUTING FAILED: Message {msg.id} could not be copied to "
                f"'{DEAD_LETTER_QUEUE_NAME}' ({dlq_send_err}); left on the main queue for retry.",
                extra={"extra_fields": {"action": "deadletter_copy_failed", "dlq": DEAD_LETTER_QUEUE_NAME, "message_id": msg.id}},
            )

        if dlq_copied:
            # 2. Purge from the primary queue only once a copy exists.
            try:
                queue_client.delete_message(msg.id, msg.pop_receipt)
            except Exception as del_err:
                logger.error("Failed to purge poison message %s from main queue: %s", msg.id, del_err)

            # 3. Exact log line required by alert-rules.bicep (Sev-1 alert keys on 'POISON MESSAGE ISOLATED')
            logger.error(
                f"POISON MESSAGE ISOLATED: Message {msg.id} failed {getattr(msg, 'dequeue_count', MAX_DEQUEUE_ATTEMPTS)} times. "
                f"Moved to Dead-Letter Queue '{DEAD_LETTER_QUEUE_NAME}' and purged from main queue.",
                extra={"extra_fields": {"action": "moved_to_deadletter_queue", "dlq": DEAD_LETTER_QUEUE_NAME, "message_id": msg.id}},
            )

        # 4. BE Gap 680: emit structured Application Insights telemetry
        try:
            from telemetry import track_poison_message
            raw_dict = raw_payload if isinstance(raw_payload, dict) else {}
            task_name = raw_dict.get("task", "unknown")
            kwargs = raw_dict.get("kwargs") if isinstance(raw_dict.get("kwargs"), dict) else {}
            tenant_id = kwargs.get("tenant_id") or raw_dict.get("tenant_id") or ""

            payload_ids = {}
            for key in ("batch_id", "file_path", "provider", "file_id", "job_id"):
                val = kwargs.get(key) or raw_dict.get(key)
                if val is not None:
                    payload_ids[key] = val

            track_poison_message(
                task=task_name,
                tenant_id=str(tenant_id),
                payload_ids=payload_ids,
                error_type=type(error).__name__,
                error_message=str(error),
                dequeue_count=getattr(msg, "dequeue_count", MAX_DEQUEUE_ATTEMPTS),
                dlq_copied=dlq_copied,
            )
        except Exception as telem_err:
            logger.warning("Failed to emit poison message telemetry: %s", telem_err)

    except Exception as dlq_err:
        logger.critical(f"Failed to route poison message {msg.id} to DLQ: {dlq_err}", exc_info=True)


class MessageHeartbeat:
    """BE Gap 677: Renews visibility timeout of an in-flight Azure Storage Queue message

    periodically (Decision D8: 120s timeout, renewed every 45s) to eliminate false redeliveries,
    duplicate worker processing, and false dead-lettering during long-running extraction jobs.
    """
    def __init__(
        self,
        queue_client: QueueClient,
        msg_id: str,
        initial_pop_receipt: str,
        visibility_timeout: int = VISIBILITY_TIMEOUT_SECONDS,
        renew_interval_seconds: float = HEARTBEAT_INTERVAL_SECONDS,
    ):
        self.queue_client = queue_client
        self.msg_id = msg_id
        self.pop_receipt = initial_pop_receipt
        self.visibility_timeout = visibility_timeout
        self.renew_interval = renew_interval_seconds
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()

    def get_pop_receipt(self) -> str:
        with self._lock:
            return self.pop_receipt

    def _run(self) -> None:
        while not self._stop_event.wait(self.renew_interval):
            # The lock is held across the renewal call, and the stop flag is re-checked
            # inside it: `stop_and_get_receipt()` takes the same lock, so once it returns
            # no renewal can still be in flight and no newer receipt can appear -- the
            # receipt it hands to delete_message is final. (Review fix: the first version
            # deleted with the heartbeat still running, so a renewal landing between
            # reading the receipt and the delete invalidated it and the message was
            # redelivered -- the duplicate this gap exists to prevent.)
            with self._lock:
                if self._stop_event.is_set():
                    break
                try:
                    updated = self.queue_client.update_message(
                        self.msg_id,
                        self.pop_receipt,
                        visibility_timeout=self.visibility_timeout,
                    )
                    if updated and getattr(updated, "pop_receipt", None):
                        self.pop_receipt = updated.pop_receipt
                        logger.debug(
                            "Heartbeat renewed visibility timeout for message %s (next renewal in %ss)",
                            self.msg_id, self.renew_interval,
                        )
                except Exception as e:
                    logger.warning(
                        "Heartbeat failed to renew visibility timeout for message %s: %s",
                        self.msg_id, e,
                    )

    def stop_and_get_receipt(self) -> str:
        """Stop renewing and return the final pop receipt. Blocks until any in-flight
        renewal has finished, so the receipt cannot change after this returns."""
        self._stop_event.set()
        with self._lock:
            return self.pop_receipt

    def start(self) -> "MessageHeartbeat":
        self._thread = threading.Thread(
            target=self._run,
            name=f"heartbeat-{self.msg_id}",
            daemon=True,
        )
        self._thread.start()
        return self

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)


def _process_message(queue_client: QueueClient, msg) -> None:
    """Handles one queue message end-to-end; never raises - a failure here
    must not crash the worker thread silently, since the caller (a
    ThreadPoolExecutor future) would otherwise swallow the exception until
    someone calls .result()."""
    tenant_id = None
    slot_acquired = False
    heartbeat: Optional[MessageHeartbeat] = None
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

        # BE Gap 677: Start visibility heartbeat (120s timeout, renewed every 45s)
        heartbeat = MessageHeartbeat(
            queue_client=queue_client,
            msg_id=msg.id,
            initial_pop_receipt=msg.pop_receipt,
            visibility_timeout=VISIBILITY_TIMEOUT_SECONDS,
            renew_interval_seconds=HEARTBEAT_INTERVAL_SECONDS,
        ).start()

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
                # Gap 439: the fourth dispatch site, same `.get()` shape as the
                # single id so a message enqueued before this deploy is fine.
                attachment_ids=kwargs.get("attachment_ids"),
            )
        else:
            logger.warning(f"Unknown task {task_name}")

        # Delete after successful processing, with the heartbeat stopped FIRST so the
        # receipt used here is final (see MessageHeartbeat._run).
        final_pop_receipt = heartbeat.stop_and_get_receipt() if heartbeat else msg.pop_receipt
        queue_client.delete_message(msg.id, final_pop_receipt)
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
            if heartbeat:
                msg.pop_receipt = heartbeat.stop_and_get_receipt()
            _route_to_dead_letter_queue(queue_client, msg, ex)
    finally:
        if heartbeat:
            heartbeat.stop()
        if slot_acquired and tenant_id:
            _release_tenant_slot(tenant_id)


def _process_redis_chat_tasks(executor: ThreadPoolExecutor):
    """Gap 280: Drains in-flight chat jobs from Redis chat_tasks_queue.

    Returns the submitted Future (or None) so the poll loop can count the job against
    the same MAX_WORKERS capacity as queue messages (BE Gap 677 review fix).
    """
    r = _get_redis_sync()
    if not r:
        return None
    try:
        # Check for queued chat tasks in Redis
        raw = r.rpop("chat_tasks_queue")
        if raw:
            data = json.loads(raw)
            # Gap 452: the list now carries two job types. An older message has
            # no `task` key at all and is a chat turn, which is why the default
            # is the chat branch rather than a rejection.
            # Feature 30 30.2: the third job type on this list. Same
            # `.get("task")` shape as Gap 452's, checked before the chat-turn
            # default for the same reason -- an older message has no `task` key
            # at all and must still be read as a chat turn.
            if data.get("task") == "insight":
                return executor.submit(
                    handle_insight_job,
                    job_id=data.get("job_id"),
                    attachment_id=data.get("attachment_id"),
                    tenant_id=data.get("tenant_id"),
                    message_id=data.get("message_id"),
                    notify_job_id=data.get("notify_job_id"),
                )
            if data.get("task") == "extract_attachment":
                return executor.submit(
                    handle_extract_attachment,
                    job_id=data.get("job_id"),
                    attachment_id=data.get("attachment_id"),
                    tenant_id=data.get("tenant_id"),
                )
            return executor.submit(
                handle_process_chat_job,
                job_id=data.get("job_id"),
                session_id=data.get("session_id"),
                user_msg_id=data.get("user_msg_id"),
                content=data.get("content"),
                tenant_id=data.get("tenant_id"),
                # Gap 451, found while switching the queue on by default: THIS
                # drain -- the one that actually runs chat jobs -- never passed
                # the attachment through. H7 threaded the id through the payload,
                # the handler and the Azure-queue dispatch, but not through here,
                # so every attachment turn taken on the queue would have been
                # answered as an ordinary chat turn with the document silently
                # dropped. That is the exact failure the pre-route gate exists to
                # prevent, and it was latent only because the flag was off.
                attachment_id=data.get("attachment_id"),
                attachment_ids=data.get("attachment_ids"),
            )
    except Exception as e:
        logger.warning("Error consuming Redis chat task: %s", e)
    return None


def _poll_once(queue_client: QueueClient, executor: ThreadPoolExecutor, active_futures: set) -> set:
    """One pass of the BE Gap 677 poll loop; returns the still-running futures.

    No batch barrier: a queue message is received only when a worker slot is free, and
    Redis chat jobs occupy slots too. A message received while every thread is busy would
    wait in the executor's backlog with its visibility clock running and no heartbeat
    yet (the heartbeat starts inside `_process_message`), so it could reappear and be
    processed twice -- the review found exactly that when chat jobs were not counted.
    """
    active_futures = {f for f in active_futures if not f.done()}

    if len(active_futures) < MAX_WORKERS:
        # Gap 280: Poll Redis chat queue (one job per pass, as before)
        chat_future = _process_redis_chat_tasks(executor)
        if chat_future is not None:
            active_futures.add(chat_future)

    available_slots = MAX_WORKERS - len(active_futures)
    received_count = 0
    if available_slots > 0:
        for msg in queue_client.receive_messages(
            messages_per_page=available_slots,
            visibility_timeout=VISIBILITY_TIMEOUT_SECONDS,
        ):
            received_count += 1
            active_futures.add(executor.submit(_process_message, queue_client, msg))
            if len(active_futures) >= MAX_WORKERS:
                break

    if received_count == 0:
        if active_futures:
            # Wake as soon as any job finishes, never wait for the whole set.
            done, _ = wait(active_futures, timeout=1.0, return_when=FIRST_COMPLETED)
            active_futures.difference_update(done)
        else:
            time.sleep(2)
    return active_futures


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

    active_futures = set()

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        while True:
            try:
                # BE Gap 677: continuous capacity loop, one pass at a time (see _poll_once).
                active_futures = _poll_once(queue_client, executor, active_futures)
            except Exception as e:
                logger.error(f"Error communicating with Azure Storage Queue: {e}")
                time.sleep(10)


if __name__ == "__main__":
    poll_queue()

