import os
import json
import time
import logging
from azure.storage.queue import QueueClient
from config import get_settings
from queue_worker.handlers import handle_process_invoice, handle_import_connector_file

logger = logging.getLogger(__name__)

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

    logger.info(f"Starting to poll Azure Storage Queue: {queue_name}")

    while True:
        try:
            # Poll for messages
            messages = queue_client.receive_messages(messages_per_page=1, visibility_timeout=300)
            
            for msg in messages:
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
            
            # Short sleep to prevent tight loop if queue is empty
            time.sleep(2)
            
        except Exception as e:
            logger.error(f"Error communicating with Azure Storage Queue: {e}")
            time.sleep(10)

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    poll_queue()
