# Feature 10: AI Trainer Sandbox & Rules Registry

Interactive sandbox for teaching the extraction agent rules, structured into three distinct rule-template scopes rather than one flat per-vendor registry.

*(Redesigned 2026-07-13 — supersedes the previous flat "one `ExtractionTemplate` per vendor + platform-wide `default_templates.json`" design. See Rule Template Scopes below.)*

### Rule Template Scopes
1. **Global template** *(new)* — tenant-wide, vendor-agnostic. Applies to every invoice for that tenant regardless of vendor (e.g. "VAT is a tax item, applied after discount"). One per tenant.
2. **Existing production vendor template** — refines rules for a vendor that already has invoices processed in production. The sandbox initializes from a real, already-extracted production invoice instead of a fresh upload. Committing queues a re-audit of that vendor's past invoices against the updated rules.
3. **New vendor template** — cold-start rules for a vendor with no production history yet. The sandbox initializes from a freshly uploaded sample PDF. No re-audit on commit — there's no past data for that vendor to re-evaluate.

Scopes #2 and #3 both write to the same per-vendor `ExtractionTemplate` row — they differ only in how the sandbox session is seeded and whether commit triggers a re-audit.

**Concrete trigger for scope #1 — recognizing a wholly new parameter (VAT):** a rule/prompt correction can only change *how* the LLM fills in fields that already exist in `InvoiceExtractionSchema` — it cannot invent a new field at runtime. Teaching "VAT is a tax item, applied after discount" is blocked until [feature_2_pipeline_extraction.md](feature_2_pipeline_extraction.md) Task 2.21 lands (adds a structured `taxes: List[{tax_type, rate_percent, amount}]` field for the LLM to write into). Once that field exists, a Global-scope rule teaching VAT recognition applies to every vendor immediately — including whichever vendor's PDF first surfaced the need for it — with no per-vendor training required.

### Precedence & Merge
- The tenant's Global template (scope #1) applies as a baseline to every invoice for that tenant.
- A matching vendor template (scope #2 or #3) is merged on top and **wins on conflict** with the global rules.
- Resolution at extraction time is two-stage, because `vendor_name` isn't known until after the first extraction pass:
  1. First pass: apply the tenant's Global template (if any) — it doesn't require knowing the vendor.
  2. Once the first pass reveals `vendor_name`, look up that vendor's template (if any); if found, merge `global.constraints + vendor.constraints` and re-run extraction. The merged prompt explicitly instructs the LLM that vendor-specific instructions take precedence over general ones when they conflict.

### Data Model
`ExtractionTemplate` (in [models.py](file:///c:/Users/S%20Banerjee/Desktop/Invoice_LLM/Prod_Invoice_LLM/apps/invoice-be/models.py)):
- `vendor_name` becomes **nullable**. `NULL` = the tenant's Global template (scope #1) — enforced to at most one per tenant via a partial unique index (`UNIQUE (tenant_id) WHERE vendor_name IS NULL`).
- `vendor_name` set = a per-vendor template (scope #2/#3) — existing `UNIQUE (tenant_id, vendor_name)` constraint stays.
- The static `config/default_templates.json` file and the old `global_mode` commit path are **retired entirely**, not kept alongside the new design: `global_mode` wrote platform-wide rules shared across *every tenant* with no role/permission check gating it — any authenticated tenant could silently change another tenant's default extraction behavior. The new per-tenant Global template (scope #1) replaces the legitimate use case (a tenant-wide baseline) without the cross-tenant leak.

### File Coordinates
* Router: [apps/invoice-be/routers/trainer.py](file:///c:/Users/S%20Banerjee/Desktop/Invoice_LLM/Prod_Invoice_LLM/apps/invoice-be/routers/trainer.py) → `upload_transient_file()`, `trainer_chat()`, `trainer_commit()`
* Trainer Agent: [apps/invoice-be/agents/trainer_agent.py](file:///c:/Users/S%20Banerjee/Desktop/Invoice_LLM/Prod_Invoice_LLM/apps/invoice-be/agents/trainer_agent.py) → `run_trainer_agent()`, `refine_constraints()`
* Database Models: [apps/invoice-be/models.py](file:///c:/Users/S%20Banerjee/Desktop/Invoice_LLM/Prod_Invoice_LLM/apps/invoice-be/models.py)
* Pipeline Extraction Handoff: [apps/invoice-be/queue_worker/handlers.py](file:///c:/Users/S%20Banerjee/Desktop/Invoice_LLM/Prod_Invoice_LLM/apps/invoice-be/queue_worker/handlers.py) — see [feature_2_pipeline_extraction.md](feature_2_pipeline_extraction.md)

### Current Implementation (pre-redesign — none of Tasks 10.1–10.11 below have landed yet)
`routers/trainer.py` still runs the flat, single-scope design the redesign above supersedes:
1. `upload_transient_file()` (`POST /trainer/upload`) — saves the PDF to a transient local path, runs `_run_ocr()` then `agents/extraction_agent.py::run_extraction_agent()` with no rules, and stores the result in the in-process `TRAINER_SESSIONS: Dict[str, dict]` (no Redis, no TTL — lost on restart, and shared across every replica assuming there's only one, which is Task 10.9's problem).
2. `trainer_chat()` (`POST /trainer/sessions/{id}/chat`) — calls `agents/trainer_agent.py::run_trainer_agent()`, which calls `refine_constraints()` (one LLM call turning `current_constraints + user_message` into an updated `List[str]`, falling back to just appending the raw message if the LLM call fails) and then re-runs `run_extraction_agent()` with those constraints as `rules`.
3. `trainer_commit()` (`POST /trainer/sessions/{id}/commit`) — takes a `CommitPayload{global_mode: bool}`. If `global_mode=True`, it writes `{vendor_name: {constraints}}` straight into `config/default_templates.json` on local disk — **shared across every tenant**, with no permission check on who can flip that flag; this is exactly the cross-tenant leak Task 10.6 retires. Otherwise it upserts the tenant+vendor's `ExtractionTemplate` row. Either way, `vendor_name` is required (pulled from the session's `extracted_data`) — there is no path for a vendor-agnostic rule today, which is the whole reason for the Global-scope redesign above.

### Tasks
- [ ] **Task 10.1: Migrate `ExtractionTemplate` to nullable `vendor_name`**
  - Make `vendor_name` nullable; add a partial unique index enforcing one `NULL`-vendor (Global) row per `tenant_id`.
  - Write the migration; existing per-vendor rows are unaffected.
- [ ] **Task 10.2: Global-scope sandbox session route**
  - `POST /trainer/sessions/global` — starts a sandbox session with no vendor binding. Optionally seeded from a sample PDF (for grounding) or chat-only (a rule like "VAT is a tax item" doesn't strictly need a source document).
- [ ] **Task 10.3: "Initialize from Production" session route** *(scope #2 entry point)*
  - `POST /trainer/sessions/from-production?vendor_name=X` — loads an existing production `Invoice` row for that vendor (reusing its already-stored `extracted_data`; re-run OCR only if raw text wasn't retained) into the sandbox instead of requiring a fresh upload.
- [ ] **Task 10.4: Upload sandbox session route** *(scope #3 entry point — carried over from the prior design)*
  - `POST /trainer/upload` — unchanged mechanism: accepts a fresh PDF, runs OCR + Extraction Agent, returns a transient `session_id`. Used for vendors with no production history.
- [ ] **Task 10.5: Scope-aware trainer chat**
  - `run_trainer_agent()` needs to know the session's scope (Global vs Vendor). For Vendor-scope sessions, pass the tenant's current Global constraints in as read-only context so the LLM doesn't propose a vendor rule that silently duplicates or contradicts a global one — it should be told to prefer editing the global rule instead when a correction is actually general-purpose.
- [ ] **Task 10.6: Scope-based commit route**
  - `POST /trainer/sessions/{id}/commit` upserts into the Global row (`vendor_name IS NULL`) for Global-scope sessions, or the vendor's row for Vendor-scope sessions. Remove the `global_mode` flag and the `default_templates.json` write path entirely (see Data Model above).
- [ ] **Task 10.7: Re-audit trigger on commit** *(scope #2 only)*
  - Committing an "Initialize from Production" (scope #2) session queues a background re-evaluation of that vendor's existing production invoices against the updated (merged global+vendor) rules. Scope #3 commits skip this — there's no production history yet. Scope #1 (Global) commits should also queue this across *all* vendors' recent invoices for the tenant, since a global rule change can affect every vendor.
- [ ] **Task 10.8: Two-stage rule resolution in the pipeline**
  - Update `queue_worker/handlers.py::handle_process_invoice()` to fetch and apply the tenant's Global template on the *first* extraction pass (not just the vendor-specific second pass, which today only fires after `vendor_name` is known).
- [ ] **Task 10.9: Move session storage to Redis**
  - Store active sandbox sessions in Redis (TTL-bound) instead of the in-process `TRAINER_SESSIONS` dict, so sessions survive across the multi-replica `invoice-be` deployment.
- [ ] **Task 10.10: Rule versioning and rollback** *(new — safety net once trainer is a frequently-used core feature, not a rare sandbox visit)*
  - Add a `version: int` and a history table (`extraction_template_versions`, or an append-only JSONB log on `ExtractionTemplate`) capturing every committed rule change with `changed_by`, `changed_at`, and the prior `rules` value.
  - A bad Global rule affects every vendor's invoices going forward; a bad vendor rule affects only that vendor — either way, someone needs to be able to see what changed and revert it without re-deriving the rule from scratch. Add `POST /trainer/templates/{id}/rollback/{version}`.
- [ ] **Task 10.11: Accept sessions seeded from an audit correction** *(new — closes the loop from `feature_7_audit.md` Task 7.4)*
  - When the FE surfaces a "Want to save this as a rule?" prompt (triggered by a detected correction pattern), it opens a trainer session pre-populated with the suggested scope (Global or Vendor) and the sample correction already in the chat context, instead of the user starting a blank sandbox session and re-describing what they just fixed.

### Verification Plan
* **Automated Tests**: cover all three scopes — a Global-only invoice, a vendor template with no global rules, and the merge/override case where a vendor rule contradicts a global one and must win. Also verify the partial unique index rejects a second Global row per tenant, and that Global commits/re-audits never cross `tenant_id`.
* **Manual Verification**: create a Global rule ("VAT is a tax item, applied after discount") with no vendor context, upload an invoice from a brand-new vendor, and confirm the rule applies without any vendor-specific template existing.
