# Feature 3: Status Tracking & Real-Time SSE Streams

Expose HTTP streaming and polling endpoints to provide live status feedback to the client for uploaded batches.

### File Coordinates
* Router: [apps/invoice-be/routers/invoices.py](file:///c:/Users/S%20Banerjee/Desktop/Invoice_LLM/Prod_Invoice_LLM/apps/invoice-be/routers/invoices.py) → `sse_event_generator()`, `GET /invoices/stream/{batch_id}` → `stream_invoice_status()`, `GET /invoices/status/{job_id}` → `get_invoice_status()`
* Background Worker: [apps/invoice-be/queue_worker/handlers.py](file:///c:/Users/S%20Banerjee/Desktop/Invoice_LLM/Prod_Invoice_LLM/apps/invoice-be/queue_worker/handlers.py) → `_publish_sse_events()`

### Functionality
`stream_invoice_status()` first verifies tenant ownership of the batch (Gap 186): at least one `Invoice` row must exist with that `batch_id` **and** `tenant_id == context.tenant_id`. Missing or foreign batches both return `404` with `"Invoice not found or access denied."` — never `403`, so a guessed UUID is not an oracle. Only then does it return a `StreamingResponse` backed by `sse_event_generator(batch_id)`, an async generator that opens its own `AsyncRedis` pubsub subscription to channel `invoice.update.{batch_id}`, yields each message as an SSE `data:` frame, sends `: keep-alive\n\n` heartbeats when idle, and breaks the loop once it sees a terminal `status` (`COMPLETED` / `AUDIT_REQUIRED` / `FAILED`) — closing the connection itself rather than waiting on the client. **Gap 187 (2026-08-11):** cleanup uses nested try/finally plus `_sse_aclose` so pubsub unsubscribe/aclose and client aclose always run independently — an unsubscribe failure cannot skip tearing down the Redis client (shared pool still deferred). On the publish side, `queue_worker/handlers.py::_publish_sse_events(batch_id, payload)` is called at each stage of `handle_process_invoice()` (see `feature_2_pipeline_extraction.md`) and just does a synchronous `redis.Redis.publish()` on that same channel — it's a fire-and-forget pub/sub, not a queue, so a client that connects after a stage has already published it will never see that event (this is why the FE also needs the polling fallback below `6` files). `get_invoice_status()` is a plain synchronous DB read of the current `Invoice` row for clients that poll instead of subscribing.

### Tasks
- [x] **Task 3.1: Configure Redis Client for Pub/Sub Messaging**
  - Add Redis connection parameters to `apps/invoice-be/config.py` (ensure `REDIS_URL` is configured).
  - Implement a helper function `_get_redis_sync()` in `apps/invoice-be/queue_worker/handlers.py` to initialize the Redis connection pool.
- [x] **Task 3.2: Implement Redis Publisher in Queue Handlers**
  - Update `_publish_sse_events(batch_id: str, payload: dict)` in `apps/invoice-be/queue_worker/handlers.py`.
  - Enforce the payload structure for updates:
    ```json
    {
      "status": "PROCESSING_OCR | EXTRACTING_DATA | COMPLETED | AUDIT_REQUIRED | FAILED",
      "message": "Human-readable status description",
      "data": {} // Optional final extracted payload
    }
    ```
- [x] **Task 3.3: Implement the SSE Stream Endpoint (FastAPI)**
  - Create the stream route `GET /api/v1/invoices/stream/{batch_id}` returning a `StreamingResponse` (SSE).
  - Subscribe to the Redis channel `invoice.update.{batch_id}` and stream events to the client.
  - Implement a heartbeat check (e.g. sending keep-alive text every 15s) and cleanup connections on client disconnect.
  - **Gap 186 (2026-08-11):** ownership gate before subscribe — `batch_id` must belong to the caller's tenant or the route returns 404.
  - **Gap 187 (2026-08-11):** nested try/finally + `_sse_aclose` so pubsub and Redis client always tear down independently on success, cancel, or unsubscribe failure.
- [x] **Task 3.4: Implement the Single Status Poll Endpoint**
  - Define `GET /api/v1/invoices/status/{job_id}` in the router.
  - Query the PostgreSQL database for the current invoice record status and return it.
- [x] **Task 3.5: Include Alerts in SSE event payloads**
  - Ensure that when a task validation fails and resolves to `AUDIT_REQUIRED`, the final event payload enqueued in Redis includes the list of active validation alerts (`alerts: ["Warning message"]`) to render warnings inline on the frontend.

### Verification Plan
* **Automated Tests**: Execute `uv run pytest tests/test_sse.py`.
* **Manual Verification**: Run a mock task publisher and query the SSE route with cURL: `curl -N http://localhost:8000/api/v1/invoices/stream/{batch_id}`.
