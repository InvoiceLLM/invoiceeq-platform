import os
import json
import time
import logging
from concurrent.futures import ThreadPoolExecutor
from azure.storage.queue import QueueClient
from config import get_settings
from queue_worker.handlers import handle_process_invoice, handle_import_connector_file

logger = logging.getLogger(__name__)

# Concurrent messages processed per container replica (Gap 41/42, Jul 2026).
# The real cost per message is I/O-bound (waiting on Azure OpenAI/Doc
# Intelligence network calls), so threads parallelize it without needing
# proportional CPU. Matched to the OpenAI deployment capacity raise (20->500
# RPM) and the added Doc Intelligence resources (1->3) done alongside this -
# raising this without those would just move the bottleneck to 429s.
MAX_WORKERS = 10


def _process_message(queue_client: QueueClient, msg) -> None:
    """Handles one queue message end-to-end; never raises - a failure here
    must not crash the worker thread silently, since the caller (a
    ThreadPoolExecutor future) would otherwise swallow the exception until
    someone calls .result()."""
    try:
        payload = json.loads(msg.content)
        task_name = payload.get("task")
        kwargs = payload.get("kwargs", {})

        logger.info(f"Received task {task_name} with args {kwargs}")

        if task_name == "process_invoice":
            handle_process_invoice(
                batch_id=kwargs.get("batch_id"),
                file_path=kwargs.get("file_path"),
                tenant_id=kwargs.get("tenant_id")
            )
        elif task_name == "import_connector_file":
            handle_import_connector_file(
                provider=kwargs.get("provider"),
                file_id=kwargs.get("file_id"),
                tenant_id=kwargs.get("tenant_id")
            )
        else:
            logger.warning(f"Unknown task {task_name}")

        # Delete message after successful processing
        queue_client.delete_message(msg.id, msg.pop_receipt)
        logger.info(f"Task {task_name} completed and deleted from queue.")

    except Exception as ex:
        logger.error(f"Error processing message {msg.id}: {ex}")
        # If it fails, we do NOT delete the message so it becomes visible again


def poll_queue():
    settings = get_settings()
    conn_str = settings.AZURE_STORAGE_CONNECTION_STRING
    queue_name = "extraction-tasks-queue"

    if not conn_str:
        logger.error("AZURE_STORAGE_CONNECTION_STRING is missing. Queue polling disabled.")
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
    logging.basicConfig(level=logging.INFO)
    poll_queue()
