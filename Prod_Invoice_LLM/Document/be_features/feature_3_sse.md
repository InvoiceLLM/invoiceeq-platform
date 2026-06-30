# Feature 3: Status Tracking & Real-Time SSE Streams

Expose HTTP streaming and polling endpoints to provide live status feedback to the client for uploaded batches.

### File Coordinates
* Router: [apps/invoice-be/routers/invoices.py](file:///c:/Users/S%20Banerjee/Desktop/Invoice_LLM/Prod_Invoice_LLM/apps/invoice-be/routers/invoices.py)
* Background Worker: [apps/invoice-be/workers/tasks.py](file:///c:/Users/S%20Banerjee/Desktop/Invoice_LLM/Prod_Invoice_LLM/apps/invoice-be/workers/tasks.py)

### Tasks
- [ ] **Task 3.1: Configure Redis Client for Pub/Sub Messaging**
  - Add Redis connection parameters to `apps/invoice-be/config.py` (ensure `REDIS_URL` is configured).
  - Implement a helper function `_get_redis_sync()` in `apps/invoice-be/workers/tasks.py` to initialize the Redis connection pool.
- [ ] **Task 3.2: Implement Redis Publisher in Celery Tasks**
  - Update `_publish_sse_events(batch_id: str, payload: dict)` in `apps/invoice-be/workers/tasks.py`.
  - Enforce the payload structure for updates:
    ```json
    {
      "status": "PROCESSING_OCR | EXTRACTING_DATA | COMPLETED | AUDIT_REQUIRED | FAILED",
      "message": "Human-readable status description",
      "data": {} // Optional final extracted payload
    }
    ```
- [ ] **Task 3.3: Implement the SSE Stream Endpoint (FastAPI)**
  - Create the stream route `GET /api/v1/invoices/stream/{batch_id}` returning a `StreamingResponse` (SSE).
  - Subscribe to the Redis channel `invoice.update.{batch_id}` and stream events to the client.
  - Implement a heartbeat check (e.g. sending keep-alive text every 15s) and cleanup connections on client disconnect.
- [ ] **Task 3.4: Implement the Single Status Poll Endpoint**
  - Define `GET /api/v1/invoices/status/{job_id}` in the router.
  - Query the PostgreSQL database for the current invoice record status and return it.
- [ ] **Task 3.5: Include Alerts in SSE event payloads**
  - Ensure that when a task validation fails and resolves to `AUDIT_REQUIRED`, the final event payload enqueued in Redis includes the list of active validation alerts (`alerts: ["Warning message"]`) to render warnings inline on the frontend.

### Verification Plan
* **Automated Tests**: Execute `uv run pytest tests/test_sse.py`.
* **Manual Verification**: Run a mock task publisher and query the SSE route with cURL: `curl -N http://localhost:8000/api/v1/invoices/stream/{batch_id}`.
