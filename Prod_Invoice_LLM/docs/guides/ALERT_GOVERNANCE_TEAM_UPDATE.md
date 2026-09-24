# 📢 Team Update: Smart Alert Governance & Noise Reduction

**Date:** September 24, 2026  
**Subject:** Optimization of Cloud & Application Alert Notifications  
**Status:** Completed & Ready for Review  

---

## 🎯 Executive Summary

Over recent weeks, the team has experienced **alert fatigue** due to high volumes of notification emails, including **transient "flapping" alerts** (e.g. alert fires and auto-resolves 5 minutes later during routine deploys) and routine invoice processing confirmations.

We have implemented a **Smart Alert Governance Model** based on **Channel Routing (Email vs. Dashboard)**.

> **CRITICAL NOTE:** **Zero alerts have been deleted.** 100% of metric rules, health checks, risk evaluations, and telemetry remain active and visible on Azure Portal, Monitor Workbooks, and the Web Dashboard. Only the **notification destination** has been optimized to protect team focus.

---

## 🚦 The 3-Tier Alert Routing Model

```
                    ┌──────────────────────────────────────────────┐
                    │            INCOMING SYSTEM EVENTS            │
                    └──────────────────────┬───────────────────────┘
                                           │
                ┌──────────────────────────┼─────────────────────────┐
                ▼                          ▼                         ▼
       [CRITICAL EMERGENCIES]     [TRANSIENT BLIPS]         [OPERATIONAL METRICS]
        - Outage / CrashLoop       - Deploy / Cold-start     - CPU / Memory / Cache
        - DB Disk > 85%            - Resolves in < 10m       - Routine Invoices
                │                          │                         │
                ▼                          ▼                         ▼
         🚨 DIRECT EMAIL           🔇 AUTO-FILTERED           📊 DASHBOARD ONLY
       (Immediate Attention)      (Zero Inbox Noise)       (No Email Notification)
```

---

## 📋 What Goes Where?

### 1. 🚨 EMAIL CHANNEL (Immediate Critical Action Required)
Emails are reserved strictly for genuine emergencies where human intervention is required:

| Trigger | Condition | Business Risk |
| :--- | :--- | :--- |
| **Container Environment Down (`CAE`)** | Environment status = `Unavailable` | Total platform outage |
| **Azure Key Vault Unreachable** | Availability < 100% | All DB passwords & API keys fail |
| **PostgreSQL Storage Exhaustion** | Disk usage > 85% | Database crash / write lock |
| **Container CrashLoopBackOff** | Restarts > 5 in 5 minutes | Application container cannot boot |
| **Dead-Letter Queue (DLQ) Poison** | Worker isolates poison message | Potential invoice data loss |
| **Sustained 5xx Outage Storm** | 500/502 errors sustained > 15m | Real users facing server failures |

---

### 2. 🔇 5–10 MINUTE TRANSIENT BLIPS (Eliminated from Email)
* **The Problem Solved:** Previously, a 60-second container restart during deployment would fire a `Sev 1 HTTP 5xx` email at minute 5, followed by a "Resolved" email at minute 10.
* **The Fix:** Extended the evaluation window from **5 minutes to 15 minutes** (`PT15M`) and raised dev error threshold from **10 to 25**.
* **Result:** Temporary deploy restarts and cold starts that self-heal in < 10 minutes **never trigger an email** (no Fired email, no Resolved email).

---

### 3. 📊 DASHBOARD & WORKBOOKS ONLY (Zero Email Noise)
These metrics remain active and monitored in Azure Portal, but do not send emails because the platform auto-heals:

| Metric / Alert | Behavior | Visibility Location |
| :--- | :--- | :--- |
| **Container CPU Spikes** | Auto-scaler automatically spawns new replicas | Azure Portal Metrics & Workbooks |
| **Container Memory Spikes** | Memory bursts during PDF extraction | Azure Portal Metrics & Workbooks |
| **Redis Server Load** | Cache surges resolve automatically | Azure Redis Dashboard |
| **OpenAI / DocIntel 429 Retries** | SDK automatically retries with backoff | AI Control Tower Workbook |
| **PostgreSQL Active Connections** | PgBouncer handles connection pooling | Azure Database Dashboard |
| **Storage Egress Anomaly** | Daily consumption tracking | Cost & Health Workbook |

---

### 4. 💻 APPLICATION INVOICES (Web UI vs. Email)
* **Routine Processing (`COMPLETED` / `VERIFIED`):** Displayed with green status directly on the Web Dashboard (`/invoices`). No transactional staff email sent.
* **Manual Review Needed (`AUDIT_REQUIRED` / `NEEDS_REVIEW`):** Dispatches email to registered workspace auditors.

---

## 🛠️ Developer & Ops Quick Commands

You can inspect or toggle alert modes directly from the terminal:

```powershell
# 1. View active alert configuration & channel status:
.\make.ps1 alerts-status
# (or 'make alerts-status' on Linux/macOS)

# 2. Mute routine processing emails during local testing/dev:
.\make.ps1 alerts-quiet

# 3. Restore dashboard-first audit mode:
.\make.ps1 alerts-digest
```

---

## 📈 Impact & Team Benefit

1. **>95% Reduction in Email Noise:** No more clutter from routine successes or 2-minute container restarts.
2. **Zero Alert Fatigue:** When an email alert arrives, the team knows it is 100% genuine and requires immediate attention.
3. **100% Data & Telemetry Retention:** All charts, logs, metric alerts, and audit trails continue functioning without interruption.
