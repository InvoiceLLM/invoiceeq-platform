# Feature 19: Enterprise Observability, Container Health & Operational Alerting

Production-grade observability, automated container health lifecycle management, structured JSON telemetry, Dead-Letter Queue (DLQ) isolation, visual Azure Workbook dashboards, and multi-channel alerting across the Invoice AI SaaS platform in Azure (`rg-invoiceai-prod`).

---

### File Coordinates

* **Compute & Container Lifecycle (IaC):**
  * `infra/08-apps.bicep` → passes `APPLICATIONINSIGHTS_CONNECTION_STRING` to all 4 container app modules.
  * `infra/modules/compute/invoice-be.bicep` → Liveness probe (`GET /health`), Readiness probe (`GET /health/readiness`), Startup probe (30s initial delay), AppInsights connection string env var.
  * `infra/modules/compute/queue-worker.bicep` → AppInsights connection string env var, Dead-Letter Queue binding on `extraction-tasks-deadletter-queue`.
  * `infra/modules/compute/invoice-fe.bicep` → AppInsights connection string env var, TCP/HTTP Liveness and Readiness probes on port 3000.
  * `infra/modules/compute/invoice-website.bicep` → AppInsights connection string env var, Liveness and Readiness probes on port 3000.

* **Monitoring, Visual Dashboards & Alerting (IaC):**
  * `infra/09-monitoring.bicep` → wires `ca-invoice-website` into diagnostic settings and metric alerts; deploys the unified Azure Workbook dashboard module.
  * `infra/modules/monitoring/dashboard.bicep` (**NEW**) → `Microsoft.Insights/workbooks` resource with 6 visual panels (Container Health, Queue Throughput & DLQ, Latency Heatmap, AI TPM Quotas, Database & Redis Pool, Error Incident Feed).
  * `infra/modules/monitoring/alert-rules.bicep` → Sev 1 DLQ poison alert is a **log-based** `scheduledQueryRules` query (`ContainerAppConsoleLogs_CL | where Log_s has "POISON MESSAGE ISOLATED"`) — **BE Gap 257**, replacing a `QueueMessageCount`/`QueueName` metric filter Azure Storage does not expose. Also `ca-invoice-website` 5xx error alert.
  * `infra/modules/monitoring/action-group.bicep` → adds Webhook receivers for Microsoft Teams / Slack incident channels and PagerDuty integration alongside email receivers.
  * `infra/10-budget.bicep` → Azure Monthly Spending Budget ($300/mo cap with 80% actual and 100% forecasted spend alerts).

* **Backend Telemetry & Structured Logging:**
  * `apps/invoice-be/main.py` → initializes `azure-monitor-opentelemetry` APM; defines `/health/liveness` and `/health/readiness` (PostgreSQL connection check + Redis ping); request tracing middleware injecting `trace_id`, `request_id`, and `tenant_id`.
  * `apps/invoice-be/queue_worker/main_worker.py` → OpenTelemetry tracer initialization; implements Dead-Letter Queue (DLQ) routing on message retry count $\ge 5$; structured JSON log formatting with `tenant_id`, `file_id`, and `trace_id`.
  * `apps/invoice-be/routers/billing.py` → telemetry logging for PayU checkout completions, hash mismatches, payment failures, and tenant quota thresholds (80%/100%).

* **Frontend Telemetry & CI/CD Verification:**
  * `apps/invoice-fe/app/layout.tsx` → initializes `@microsoft/applicationinsights-web` for Real User Monitoring (RUM), capturing client-side JavaScript crashes and React hydration errors.
  * `.github/workflows/deploy-prod.yml` → adds post-deployment synthetic health check step verifying `GET /health` on all 4 deployed container apps before completing deployment.

---

### Functionality (Target Design)

#### 1. Container Lifecycle & Self-Healing Probes
Eliminates zombie/hung container instances. When a container process is deadlocked or its database connection pool is starved:
* **Liveness Probe:** Periodically checks `/health`. If unresponsive for 3 consecutive intervals (30s), Azure Container Apps terminates the container replica and starts a fresh instance.
* **Readiness Probe:** Checks `/health/readiness` (DB ping). If database pool headroom $<5\%$, the probe returns `503 Unavailable`, causing ACA to stop routing incoming user traffic to that replica until it recovers.
* **Startup Probe:** Gives container up to 60s during cold boot to load Python dependencies before liveness probes begin polling.

#### 2. OpenTelemetry APM & End-to-End Distributed Tracing
Instruments FastAPI, SQLAlchemy, Redis, and HTTPX. Injects a continuous `trace_id` that correlates:
$$\text{Browser} \longrightarrow \text{Website Gateway} \longrightarrow \text{Frontend} \longrightarrow \text{Backend API} \longrightarrow \text{PostgreSQL / Redis / Azure OpenAI}$$
Generates a visual **Application Map** in Azure Portal showing real-time call volumes, latencies, and red-node failure highlights.

#### 3. Structured JSON Logging with Trace & Tenant ID Correlation
Standardizes all application logs into structured JSON:
```json
{
  "timestamp": "2026-08-17T10:02:14.123Z",
  "level": "ERROR",
  "service": "queue-worker",
  "tenant_id": "tenant_acme_corp",
  "file_id": "inv_9921_corrupted.pdf",
  "trace_id": "4bf92f3577b34da6a3ce929d0e0e4736",
  "error_type": "DocIntelCorruptedPDFError",
  "retry_count": 5,
  "action": "moved_to_deadletter_queue"
}
```

#### 4. Dead-Letter Queue (DLQ) & Poison Message Isolation
When a corrupted or password-protected PDF causes `ca-queue-worker-prod` to fail processing $\ge 5$ times:
* The message is routed to `extraction-tasks-deadletter-queue` with diagnostic metadata.
* The corrupted message is deleted from the main queue, allowing remaining valid invoices to process without stalling.
* An immediate Sev 1 alert is emitted.

#### 5. Azure Workbooks Operations Dashboard
A single-pane-of-glass visual dashboard deployed via IaC featuring:
1. Container Health & Active Replica Matrix.
2. Storage Queue Ingestion & DLQ Live Throughput.
3. API Latency Heatmap (P50/P95/P99) & 5xx Error Rates.
4. Azure OpenAI (500k TPM quota) and Document Intelligence Concurrency Burn.
5. PostgreSQL Connection Pool Usage & Redis Cache Hit Ratio.
6. Error Breakdown and Alert Incident Feed by Tenant.

#### 6. Multi-Channel Alerting & Warnings
* **Payment Alerts:** PayU checkout failure, hash tampering, and subscription expiration reminders.
* **Tenant Quota Warnings:** In-app yellow warning banner at 80% quota (40/50 free invoices) and red lock banner at 100% (402 Payment Required).
* **Cloud Budget Alerts:** $300/month Azure spending budget alert at 80% actual spend and 100% forecasted spend.
* **AI Quota Warnings:** Sev 2 alert on Azure OpenAI 429 throttling (>5 client errors in 5m).
* **Delivery Channels:** Slack / Microsoft Teams webhook channels (`#alerts-billing`, `#alerts-infra`), PagerDuty on-call, and Action Group emails.

#### 7. Client-Side Real User Monitoring (RUM)
Captures uncaught React exceptions, client-side route transitions, and Core Web Vitals (LCP, FID) in `invoice-fe` and `invoice-website`.

#### 8. CI/CD Post-Deployment Verification Gate
Adds automated health checks in `deploy-prod.yml` to verify `GET /health` across all container apps immediately after `az containerapp update`.

---

### Tasks

- [x] **Task 19.1: Container Health Probes & AppInsights Injection in Bicep** — Updated `06-compute-env.bicep`, `invoice-be.bicep`, `queue-worker.bicep`, `invoice-fe.bicep`, `invoice-website.bicep`, and `08-apps.bicep` to add Liveness, Readiness, and Startup probes and pass `APPLICATIONINSIGHTS_CONNECTION_STRING`.
- [x] **Task 19.2: OpenTelemetry APM & Health Endpoints in Backend** — Configured `azure-monitor-opentelemetry` in `apps/invoice-be/main.py`; implemented `/health`, `/health/liveness`, and `/health/readiness` (DB ping + Redis check). Added `azure-monitor-opentelemetry` to `pyproject.toml`.
- [x] **Task 19.3: Structured JSON Logging Middleware** — Created `apps/invoice-be/utils/logging_config.py` with `StructuredJsonFormatter` and `TracingAndLoggingMiddleware`; wired into `main.py` and `main_worker.py` to emit JSON logs with `trace_id`, `request_id`, and `tenant_id`.
- [x] **Task 19.4: Dead-Letter Queue (DLQ) Isolation in Queue Worker** — Updated `apps/invoice-be/queue_worker/main_worker.py` to route messages failing $\ge 5$ attempts to `extraction-tasks-deadletter-queue` and purge them from the primary queue.
- [x] **Task 19.5: Azure Workbooks Operations Dashboard Bicep Module** — Created `infra/modules/monitoring/dashboard.bicep` defining the 6-panel single-pane-of-glass workbook; wired into `09-monitoring.bicep`.
- [x] **Task 19.6: Website Diagnostics & DLQ Alert Rules** — Added `ca-invoice-website` to diagnostic settings and 5xx alerts in `09-monitoring.bicep` and `alert-rules.bicep`; added Sev 1 Dead-Letter Queue (DLQ) poison message alert. **Corrected 2026-08-19 (BE Gap 257):** the original rule was a `metricAlerts` filter on `QueueMessageCount` + `QueueName` — that dimension does not exist on Azure Storage queue metrics, so the alert could never fire. Replaced with `Microsoft.Insights/scheduledQueryRules` over `ContainerAppConsoleLogs_CL | where Log_s has "POISON MESSAGE ISOLATED"` (same KQL as the workbook DLQ panel). `az bicep build --file infra/09-monitoring.bicep` compiles clean. **Not yet deployed / poison-message fire-tested on Azure.**
- [x] **Task 19.8: Client-Side Real User Monitoring (RUM)** — Added `@microsoft/applicationinsights-web` to `package.json` and created `AppInsightsProvider.tsx` wrapping `RootLayout` in `apps/invoice-fe/app/layout.tsx`.
- [x] **Task 19.9: CI/CD Post-Deployment Verification Gate** — Added `verify-deployment` job in `.github/workflows/deploy-prod.yml` to automatically verify public ingress and container app `Succeeded` provisioning state after release. **Extended 2026-08-19 (BE Gap 258):** dev now has the same gate in `deploy-dev.yml` (website ingress + backend `/health/readiness` curl + all four dev apps' traffic-bearing revision `Healthy`/`Running`), and `_deploy-service.yml` polls each service's latest revision health immediately after `az containerapp update` (dev and prod deploy jobs).

---

### Verification Plan

#### Automated Tests
```powershell
# 1. Validate Bicep syntax and compilation across all modified modules
az bicep build --file Prod_Invoice_LLM/infra/08-apps.bicep
az bicep build --file Prod_Invoice_LLM/infra/09-monitoring.bicep

# 2. Run backend test suite
cd Prod_Invoice_LLM/apps/invoice-be
pytest -v tests/
```

#### Manual & Staging Verification
1. **Health Probes Verification:** Run `az containerapp show --name ca-invoice-be-dev -g invoice-llm-dev` and verify probes are populated and active.
2. **Telemetry Ingestion Check:** Execute API calls and verify distributed traces appear in Application Insights `AppRequests` and Application Map.
3. **Dead-Letter Queue Isolation Test:** Inject malformed payload into `extraction-tasks-queue` and verify it routes to `extraction-tasks-deadletter-queue` without worker crash.
4. **Dashboard Verification:** Open Azure Portal $\rightarrow$ Monitor $\rightarrow$ Workbooks $\rightarrow$ *Invoice AI Operations Hub* and verify all 6 panels render live data.
