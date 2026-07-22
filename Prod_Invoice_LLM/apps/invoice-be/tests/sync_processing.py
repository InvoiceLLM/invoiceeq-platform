"""Local-run helper: processes an uploaded invoice synchronously, in-process,
instead of relying on the Azure Storage Queue + a separately-running worker.

Why: Azurite's queue emulator repeatedly wedges during local test runs
(approximate_message_count > 0 but receive_messages() returns nothing,
even after a full volume reset) — a local-emulator reliability problem,
not a product defect. The queue/worker mechanism itself is already
validated separately (KEDA autoscale rule confirmed live on
ca-queue-worker-dev). These test suites exist to check extraction/RAG
accuracy, not re-prove the queue works, so for local runs they call the
same processing code the worker would call, directly.

Only used by tests/e2e and tests/benchmark. Production upload flow
(routers/invoices.py) is untouched — it still always enqueues.
"""
from queue_worker.handlers import handle_process_invoice

MOCK_TENANT_ID = "00000000-0000-0000-0000-000000000000"


def process_invoice_sync(invoice_id: str, batch_id: str, tenant_id: str = MOCK_TENANT_ID) -> dict:
    """Mirrors the file_path the real upload endpoint constructs
    (services/storage.py::upload_pdf_to_blob_storage), then runs the same
    handler the queue worker would run, synchronously in this process."""
    file_path = f"azure://invoices/tenants/{tenant_id}/invoices/{invoice_id}.pdf"
    return handle_process_invoice(batch_id=batch_id, file_path=file_path, tenant_id=tenant_id)
