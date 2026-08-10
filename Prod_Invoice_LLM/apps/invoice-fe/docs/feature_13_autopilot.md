# Feature 13: Autopilot — upgrade File Ingestion to decision brief

**Extends Feature 3** (`feature_3_ingestion.md` / NOVA). Autopilot is **not** a new route or a second connect UI — it is the product framing and UX upgrade of the existing Ingest screen (`/ingestion`).

Connectors stay in **Settings → Connectors** (Feature 7). Autopilot *uses* those connections and turns “upload + watch status” into “today’s audit recommendations + ask.”

### Product intent
- Same browser SaaS: Website → login → FE app. Nothing to download.
- Sidebar label **Ingest → Autopilot** (href stays `/ingestion` unless a later task deliberately redirects).
- Keep drop zone, tags, connector browse bar, status ledger, outbound Sending tab.
- Add an **audit brief** (Pay / Needs review / Reject + reason + Open) and an **Ask Autopilot** panel wired to existing Chat/RAG where possible.
- “Change in Settings” when no connector / wrong folder — do not rebuild OAuth on this page.

### File coordinates (v1 — evolve in place)
* Page: `apps/invoice-fe/app/ingestion/page.tsx`
* Sidebar: `apps/invoice-fe/components/layout/Sidebar.tsx` (nav label)
* Existing ingest components under `apps/invoice-fe/components/ingestion/*` (reuse)
* Connectors (unchanged home): `apps/invoice-fe/app/settings/connectors/page.tsx`
* Chat/RAG (reuse): Feature 5 — `apps/invoice-fe/app/chat/page.tsx` / related APIs
* BE: existing invoice status/alerts; optional later endpoint for “today’s brief” aggregation

### Out of scope (v1)
* Desktop install / third-party agent marketplace as the product face
* SAP connector
* Silent auto-pay without human confirmation
* Replacing Settings connector setup
* Completeness compare DI vs extraction (related BE Gap 178 follow-up — separate)

### Tasks
- [ ] **Task 13.1: Rename surface** — Sidebar + PageHeader: Ingest / File Ingestion → **Autopilot**; keep `/ingestion` route; update e2e/nav assertions that hardcode “Ingest”.
- [ ] **Task 13.2: Source status strip** — Show “Using {provider} · {folder} (connected in Settings)” + link to Settings when Active; grey “Connect in Settings” when none (reuse Feature 7 / ConnectorBrowseBar signals).
- [ ] **Task 13.3: Audit brief panel** — For recent/today’s jobs (or selected batch): recommendation from status/alerts (e.g. COMPLETED→Pay, AUDIT_REQUIRED→Needs review, FAILED/rejected→Reject) + short reason + Open to review console. Prefer FE composition of existing status APIs before inventing a new BE aggregate.
- [ ] **Task 13.4: Process today’s new PDFs** — Primary CTA that triggers ingest from connected source and/or focuses drop zone; must not invent a second OAuth flow.
- [ ] **Task 13.5: Ask Autopilot** — Slim chat panel on this page (embed or deep-link Feature 5 with invoice context); no duplicate RAG stack.
- [ ] **Task 13.6: Docs & verify** — Update Feature 3 cross-link; Playwright smoke for nav label + brief empty/loaded states; manual demo script (Settings connect → Autopilot brief).

### Dependencies / risks
* Live Drive/Salesforce connect on Azure still blocked by BE Gap 131 (`redirect_uri_mismatch`) — Autopilot demo can use upload until that ships.
* Recommendation rules must map honestly to existing statuses/alerts; do not fake Pay/Reject without backend signal.

### Verification plan
* Nav shows Autopilot; `/ingestion` still loads all Feature 3 / 3.1 controls.
* With no connector: strip points to Settings; upload still works.
* With mocked statuses: brief rows show correct recommendation buckets.
* Ask panel opens chat path without breaking ingest layout at 1280×720.
