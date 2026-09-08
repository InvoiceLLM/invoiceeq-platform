# Invoice LLM — Project Status

_As of 2026-09-08. Sources: `be_features_tracker.md`, `fe_features_tracker.md`, `website_features_tracker.md`, `feature_29_llm_optimisation.md` §2, `active-work.md`. Each phase is a complete, working product increment on its own._

**AI agents:** NOVA (extraction) · SENTINEL (audit) · SAGE (chat) · EVOLVE (trainer). Models: `gpt-5.6-luna` (primary/fast), `gpt-5-mini` (judge, chat summary).

## Phase 1 — Core Invoice Platform (live) — **100% done**

| Area | Functionality | % done | AI accuracy |
|---|---|---|---|
| Auth & RBAC | Clerk multi-tenant login, Admin/Auditor/Trainer roles | 100% | n/a |
| Ingestion & Extraction (NOVA) | PDF upload → Doc Intelligence OCR → LLM field + line-item extraction, queue worker, SSE progress | 100% | Field composite **99.3%** (Luna); tax 96–100%, total 100%, line-item F1 98–100% (27 real PDFs, 3 runs) |
| Duplicate detection | SHA-256 hash + vendor/number match, UI badges | 100% | deterministic |
| Audit (SENTINEL) | Alert generation, split-screen review, approve/reject/finalize | 100% | Alert recall measured for 10 alert types (F23 benchmark) |
| Chat (SAGE) | Conversational RAG over invoices, SQL drawer, threads | 100% | Golden set pass **72.2%** (26/36), accuracy 0.76, faithfulness 0.89; judge κ 0.85 |
| Trainer (EVOLVE) | Rule sandbox (global / vendor / new-vendor), rules feed chat + audit | 100% | n/a |
| Dashboard | Metrics & analytics API + command-center UI | 100% | n/a |
| Service Flow (outbound) | Send invoices, outbound auditor, outbound dashboard, direction-aware chat | 100% | same as above |
| Connectors & Email-in | Google Drive / Salesforce OAuth, global mailbox ingestion, staff notify | 100% | n/a |
| Webhooks & Settings | HMAC-signed outbound webhooks, settings screens | 100% | n/a |
| Billing | PayU checkout, success/fail flow, lapse detection | 100% | n/a |
| Support & Help | Ticket engine, help center, AI support assistant (keyword KB), contact page | 100% | n/a |
| Admin console | User provisioning, permission toggles, Clerk debug | 100% | n/a |
| Observability | App Insights, container health, Azure Workbooks, client RUM | 100% | n/a |
| Test & benchmark suite | Tier-1 regression (~3,080 tests, real Postgres), Tier-2 daily benchmark | 100% | — |
| Website | Landing, agent showcase, pricing, auth gateway, contact | 100% | n/a |

## Phase 2 — Automation & Any-Document Intelligence — **~85% done**

| Area | Functionality | % done | AI accuracy |
|---|---|---|---|
| Tenant Autopilot (F13) | Scheduled Drive/Salesforce folder sync + dedup | 100% | n/a |
| Plug & Play Workflows (BE25 / FE17 / Web7) | API keys, Full-Automation vs Strict-Review policy, email summary output, setup wizard, marketing surface | 75% | n/a |
| Generic extraction (F27) | Classify any financial doc (8 types), doc-type-specific extraction & verification, `/documents` list; flag ON | 85% | Doc-type classification **100%** (Luna, 24 PDFs; classifier 24/24 deterministic) |
| Chat attached documents (F26) | Attach PO / GRN / credit note etc. in chat, compare to invoices, line arithmetic | 80% (Part 1 done; Part 2 behind flag, unverified) | Attachment benchmark **25/25** scenarios |
| LLM optimisation (F29) | Model registry & roles, full-record chat context, answer-contract gate, judge calibration, failure taxonomy | 100% (closed) | Chat pass 22% → **72%** after fix; judge κ 0.15 → **0.85** |
| Image upload (BE28 / FE19) | PNG/JPG/TIFF/WEBP/BMP → PDF at every entry point | 90% (Azure manual run pending) | same as extraction |
| Invoice Builder (BE17 / FE20) | Clone-and-edit outbound invoice, PDF substitute/re-render, read-back verify | 90% (live e2e pending) | deterministic read-back check |
| AI Control Tower (F23) | Extraction/alert benchmark, SAGE eval, nightly job, flat workbook | 90% | — |
| Ingestion history (FE Gap 464) | Durable run history across all ingestion doors | 100% | n/a |

Open before Phase 2 can be called complete: F27 fixture breadth (task F/V) and 27 flag-OFF parity tests (Gap 461); F26 Part 2 H6–H9 + Postgres/Redis verification; F28/F17 dev-stack manual rows; Plug & Play Drive write-back (338), sandbox keys (340), widget token (341).

## Phase 3 — Business Intelligence & Platform Expansion — **~25% done**

| Area | Functionality | % done | AI accuracy |
|---|---|---|---|
| Business Intelligence (BE30 / FE21) | Insight bubble for non-invoice docs in chat: verdict + findings, bank-statement match, per-tenant vendor master; information only (no invoice actions, Gap 492) | 70% (BE 20/23 tasks, FE 6/8; India rule cards await founder text; not yet verified live on dev with the switch on) | insight eval 20/20 figures exact (deterministic, no model) |
| Entity resolver (29.11) | Vendor/entity resolution behind `ENABLE_ENTITY_RESOLVER` | 60% (built, flag off, rollout plan not applied) | 17 Postgres tests pass |
| Desktop app (FE18) | PWA wrapper (Tauri dropped) | 0% | n/a |
| Plug & Play remainder | Drive archive write-back, sandbox `inv_test_` keys, chat widget token | 0% | n/a |
| Environments & hardening | Dev/prod split, custom domain (Front Door + WAF), branch protection | 10% (bicep compile-verified, never applied) | n/a |
| Load & security testing | Load tests, full security pass | 20% (one live dev security pass done) | n/a |
| ERP integrations | SAP / QuickBooks | 0% (deferred until paying customer) | n/a |

## Overall

| Phase | Scope | % done | Headline AI accuracy |
|---|---|---|---|
| 1 | Core invoice platform | 100% | Extraction 99.3% · Chat 72% pass |
| 2 | Automation & any-document intelligence | ~85% | Doc-type 100% · Attachment chat 25/25 |
| 3 | Business intelligence & platform expansion | ~25% | insight figures 20/20 exact (offline) |
