# Feature 25 — Plug & Play Workflows: Programmatic Access, Workflow Policy & Output Destinations

**STATUS: BACKEND COMPLETE — Phase 0 (Task 25.1 / Gap 335), the role-vocabulary change (Task 25.1b / Gap 337) and the workflow config object (Task 25.2 / Gap 336) built and verified 2026-08-29; Task 25.3 (Gaps 339/338 — email summary and Drive write-back), Task 25.5's provisioning half (Gap 342), Task 25.4 (Gap 340 — sandbox `inv_test_` keys) and Task 25.5's widget half (Gap 341 — the embedded chat widget token) all built and verified 2026-08-30. Every backend task in this feature is now built. The remaining half of the feature is FE/website (FE Gap 325): none of this has a user interface, and `SANDBOX_KEYS_ENABLED` is False in every environment. **Corrected 2026-08-30 by Gap 352** (post-build security review, a fix *inside* Task 25.4 rather than new scope): Gap 340's chat meter shipped without a row lock and did not bound anything under concurrency — see the Gap 340 section §7's marked correction and Verification Plan §20.**

> **functional-tester final gate, 2026-08-30 (additive).** Combined 17-file targeted run: 454 passed, 1 failed (a genuine, reproducible ~20% flake in Gap 352's own concurrency test — the security bound holds, only the reported `used` sequence number is unreliable under concurrency; not fixed, reported). Full `pytest tests/` suite: 1734 passed, 10 failed, 9 pre-existing/unrelated + 1 genuine regression (`tests/test_rag.py::test_session_lifecycle_and_tenant_isolation` — a test-coverage gap from Gap 335's dependency swap, not a live security hole; not fixed, reported). See Verification Plan §21 for full detail. The Azure-dev migration caveat is unchanged — still four revisions behind, still nothing deployed.

> **Both of those findings are now CLOSED, 2026-08-30 — Gap 353 and Gap 354.** The flaky `used` count was the post-commit `db_session.refresh()` reading outside the `FOR UPDATE` lock window (a reporting defect; the bound always held) — fixed by capturing the reported value under the lock, proven by a before/after on the same Postgres database: **13/20 passing pre-fix, 25/25 post-fix**. The `test_rag.py` tenant-isolation test now overrides `get_tenant_or_api_key_context` and asserts the override was actually invoked — proven able to fail by temporarily breaking `routers/chat.py:314`'s check, not merely observed passing. One correction to the framing above: that test was **failing** (`assert 200 == 403`), not silently passing. See Verification Plan §22.

> This document was opened as `STATUS: IMPLEMENTING (Phase 0 in progress)` and written
> **before any of its code existed**, as the scope of record for Gap 335 (this repo's
> no-code-without-gap rule). The header was updated only once Phase 0 actually passed its
> tests — it was never used to describe work that had not happened. Only Phase 0 (Task 25.1)
> has been built.
> Everything filed under a **New — not built yet** heading below is a *design intent*, not a
> claim that the symbol exists. Do not read a name in this document as evidence that it is in
> the codebase; check the file.

---

## Overview

### What "Plug & Play" means here

The product is being opened up so a tenant's own systems — an ERP, an RPA bot, a scheduler,
a partner integration — can drive the invoice lifecycle over the API instead of a human
driving it through the web UI. The tenant chooses **how much of that lifecycle the machine is
allowed to finish**, and that choice is a single per-tenant workflow policy.

### The founder's own definition of the two policies, verbatim

> **Full Auto-Pilot** = full automation — the API key gets to call approve/reject/verify/send/mark-paid.
>
> **Strict Review** = the key stays read/upload-only, a human finalizes in the web UI.

That is the whole of the distinction. Everything in Phase 0 exists to make exactly that
sentence enforceable at the auth layer.

### What this is NOT — two things it is repeatedly mistaken for

1. **This is not a pipeline auto-approval threshold.** Nothing here changes when an invoice
   is considered clean, what `sa_alerts` gets raised, or whether extraction confidence lets
   an invoice skip review. The pipeline's judgement of an invoice is untouched. This governs
   *who is permitted to press the button*, not *whether the button should be pressed*.

2. **This is not Feature 13's "Autopilot".** Feature 13 already ships a thing called
   **Tenant Autopilot** — `TenantAutopilotConfig` / `services/autopilot_sync.py` /
   `scripts/autopilot_job.py` — which is **scheduled folder sync from Google Drive**. It is an
   *ingestion scheduler*. It has nothing to do with who may approve or send an invoice.
   Naming this new policy "Full Auto-Pilot" in the UI would collide with a shipped feature of
   the same name and a different meaning, in a product where both are configured from
   Settings.

   **Naming collision — flagged, not resolved.** Working name in this document and in code is
   **"Full Automation"** (policy values `full_automation` / `strict_review` when Gap 336 adds
   them). The founder has **not** ruled on this; if the founder prefers "Full Auto-Pilot" in
   user-facing copy, the collision needs a deliberate answer (e.g. renaming Feature 13's
   surface to "Scheduled Sync"). Until then, treat "Full Automation" as provisional.

### Phase 0's scope, and why it is first

Phase 0 (Gap 335) builds only the **auth/scope foundation**: a per-tenant API-key scope with
two tiers, a dependency that accepts either credential type, and the route rewiring that makes
the tiers mean something. The user-visible policy object, the destinations, and the sandbox
key all sit on top of it. Every one of Gaps 336/338/339/340/341/342 (BE) and FE Gap 323 reads
or writes the shape defined here, which is why it lands alone and first.

---

## Ground truth at design time

Verified against the real code on 2026-08-29, immediately before writing any of this feature's
code. Recorded because several of these facts are load-bearing and are the kind of thing that
goes stale.

* **`dependencies.py::get_api_key_context` was referenced by exactly one route in the whole
  codebase before this work**: `routers/settings.py:297`, the
  `GET /settings/security/api-key/verify` endpoint. Gap 184 built a complete, tested API-key
  auth path and then wired it to a single identity-echo endpoint — programmatic callers could
  prove a key worked and do nothing else with it. Feature 25 is what makes that path useful.

* **`models.py::RoleMapper` already has 4 roles** — Admin / Auditor / Trainer / Viewer, with
  `ROLE_PERMISSION_DEFAULTS` for each. **Trainer already matches the founder's spec**
  (`can_train=True`, `can_audit=False`, `can_load=False`); no change is needed there for the
  founder's stated role model. Role-model work is **Gap 337**, queued separately and
  deliberately **not** touched by Gap 335, so two changes do not collide in the same file.

* **`services/api_keys.py` assumes one key per tenant by design.** Its module docstring says
  so outright ("There is one key per tenant by design (this is not a key-management
  product)"), and rotation works by overwriting `api_key_hash` + `api_key_salt` +
  `api_key_prefix` together. Consequence for this feature: **scope is a property of the
  tenant, not of a key** — `Tenant.api_key_scope`, not a per-key column. A tenant cannot hold
  a readonly key and an actions key simultaneously. If that ever becomes a requirement it is a
  key-table redesign, not a column tweak.

* **`routers/audit.py`'s `require_can_audit` is a router-level dependency** (line 33,
  `APIRouter(..., dependencies=[Depends(require_can_audit)])`), so it gates every route on the
  router. As of today that router has exactly **one** route, `PUT /audit/resolve/{invoice_id}`
  — there are no read-only endpoints on it, so raising the whole router to actions scope
  removes no read access. `routers/outbound_audit.py` (line 29) is the identical shape with
  the identical single route, `PUT /outbound-audit/resolve/{invoice_id}`.

* **Pre-existing security hole, found while scoping this work and fixed as part of it.**
  `routers/outbound_invoices.py`'s `PUT /{invoice_id}/confirm-send` (line 156) and
  `PUT /{invoice_id}/mark-paid` (line 210) depended on bare `get_tenant_context` with **no
  permission gate at all** — every other financial-finalization route in the product requires
  `can_audit`, but these two required only *any* authenticated session. A Viewer with zero
  granted permissions could mark a tenant's outbound invoice SENT or PAID, fire the outbound
  webhook, and trigger the staff notification email. This is **not** something the founder
  asked to be fixed; it was found incidental to Gap 335's route audit and is corrected here
  because Gap 335 is rewriting those exact dependency lines anyway and leaving a known hole in
  a line being edited is not defensible. Recorded here rather than filed as its own gap so the
  security change is not invisible inside a feature commit.

* **`AuditLog.actor_user_id` is `UUID = Field(foreign_key="users.id")` — non-null**
  (`models.py:271`), and `resolve_api_key_context` returned `db_user_id=None`. Written at
  `routers/audit.py:464`, `routers/outbound_audit.py:232`, `routers/invoices.py:685` and
  `:807`. An actions-scoped key reaching audit-resolve would therefore have inserted NULL into
  a NOT NULL FK column and 500'd. See "The AuditLog actor problem" below.

* **Alembic had a single head, `a7c3d5e91f04`**, confirmed by an actual `alembic heads` run
  (not by reading the files). This repo has had a multi-head incident before (tracker Gap 60),
  hence the check.

* **`GET /auth/me` returns `TenantContext` verbatim** (`routers/auth.py:213`,
  `response_model=TenantContext`), so any field added to that model becomes part of that
  response.

---

## Functionality

### Phase 0 — the two scope tiers, concretely

`Tenant.api_key_scope` is one of two literal values.

| Scope | Meaning | What the key can do |
|---|---|---|
| `readonly` (**default**) | "Strict Review" — the machine feeds the system and reads from it; a human finalizes. | Upload invoices, read invoices/PDFs/status, use chat. |
| `actions` | "Full Automation" — the machine finishes the job. | Everything `readonly` can do, **plus** approve/reject/verify (audit resolve, inbound and outbound), confirm-send, and mark-paid. |

The default is `readonly` and that is a **fail-closed** decision, not a stylistic one: every
tenant that already exists at migration time, and every tenant created afterwards without an
explicit choice, must not silently acquire the ability to have a machine approve its invoices.
Widening is an explicit act.

**Training is deliberately excluded from `actions`.** The founder's description of full
automation named four things — approve, reject, verify, send (plus mark-paid) — and training
was not among them. An actions-scoped key therefore gets `can_train=False`. Letting an
integration rewrite the tenant's extraction rules is a different and much larger claim than
letting it finish an invoice, and it will not arrive as a side effect of this one.

### `get_tenant_or_api_key_context()` — what it does and why it exists

**The problem it solves.** FastAPI resolves dependencies eagerly, so "use the Clerk dependency
*or* the API-key dependency" cannot be expressed by declaring both — declaring both would run
both, and each 401s when its own credential is absent. Every dual-credential route would
otherwise need its own try/except tangle in the handler body.

**What it does.** It inspects the incoming headers itself and dispatches to exactly one of the
two existing, already-tested auth paths, then returns the same `TenantContext` either way:

1. `X-API-Key: <key>` present → API-key path (`resolve_api_key_context`).
2. otherwise `Authorization: Bearer <token>` where `services/api_keys.looks_like_api_key(token)`
   (i.e. the token carries the `inv_live_` prefix a Clerk JWT can never carry) → API-key path.
3. otherwise → the Clerk path, by calling `get_tenant_context_allow_unpaid()` and then
   `get_tenant_context()` on its result, so the 402-on-unpaid gate and the ALLOW_MOCK_AUTH
   local/test fallback behave *identically* to a route that depends on `get_tenant_context`
   directly. It calls those functions rather than reimplementing them precisely so the two
   paths cannot drift.

Header precedence (`X-API-Key` wins over `Authorization`) is inherited unchanged from Gap
184's `get_api_key_context`, extracted into a shared `_extract_api_key()` helper that both now
use, so there is one rule and not two.

**`auth_method`.** `TenantContext` gains `auth_method: str` — `"clerk"` or `"api_key"`. Before
this, a handler and an audit row genuinely could not tell which door a request came through;
Gap 184's own comment described that opacity as a feature ("downstream handlers cannot tell
(or need to tell)"). Once a key can take financial actions, that stops being acceptable: "who
did this" is an audit question, and "a machine, via key `inv_live_ab12cd`" is a different
answer from "Priya, in a browser". `key_scope: str | None` rides alongside it (`None` on the
Clerk path) so the scope check is legible instead of being inferred from the permission
booleans.

Both fields default to the Clerk values, so every existing `TenantContext(...)` construction
site is unaffected. Both appear in `GET /auth/me`'s response, which is purely additive.

### Scope-derived permissions in `resolve_api_key_context()`

Gap 184 hardcoded `role = "Viewer"` and ran it through `resolve_permissions()`. That produced
`(False, False, False)` — correct, but by way of a role label that no longer describes what is
happening once scope exists. The permissions are now derived from the scope directly:

| `api_key_scope` | `can_train` | `can_audit` | `can_load` |
|---|---|---|---|
| `readonly` | False | False | False |
| `actions` | False | **True** | **True** |

The `readonly` row is **the same effective permission set the Viewer label produced**, so
nothing about today's behaviour changes for any existing tenant — only the derivation is now
explicit rather than a side effect of a role name. `role` continues to be reported as
`"Viewer"` on the readonly path so `GET /settings/security/api-key/verify`'s existing contract
is unchanged; an `actions` key reports `role="Viewer"` too, because **scope is not a role** —
`require_admin` must never be satisfied by a key, at any scope. An integration can finish an
invoice; it cannot rotate keys, manage users, or change billing.

### `require_key_scope()` and `require_permission_or_api_key()`

`require_key_scope("actions")` follows the existing `require_permission()` factory pattern in
the same file — build a dependency, attach it per-route or per-router, get a 403 with a
human-readable reason. It resolves the dual-credential context and then:

* **API-key request** → 403 unless `key_scope == "actions"`. The message names the setting to
  change, because the caller is an integrator reading a JSON error, not a user reading a
  toast.
* **Clerk request** → 403 unless `can_audit`. This preserves the existing human gate on the
  audit routers *byte-for-byte in message text*, which `tests/test_rbac.py` asserts on
  ("audit queue"), and extends the same gate to the two outbound-invoice routes that had none.

`require_permission_or_api_key("can_load")` covers a case the two tiers alone do not.
**Upload is ingestion, not an "action"** — the founder's Strict Review definition is explicitly
"read/**upload**-only", so a `readonly` key must be able to upload. But `readonly` grants
`can_load=False`, and `POST /invoices/upload` is gated on `require_can_load` for humans. Simply
swapping in the dual dependency would have silently dropped the human `can_load` gate that
`tests/test_rbac.py::test_invoice_upload_requires_can_load` exists to protect. So: on the
Clerk path the permission is still required exactly as before; on the API-key path any scope
passes. Two different questions, two different answers, one dependency.

### The AuditLog actor problem, and how it is resolved

**The problem.** `AuditLog.actor_user_id` is a non-null FK to `users.id`. An actions-scoped key
calling `PUT /audit/resolve/{invoice_id}` would have written `actor_user_id=None` and taken a
500 on the insert. Relaxing the FK to nullable was rejected: the column being non-null is what
guarantees every audited action is attributable to *something*, and a nullable actor turns
"machine did it" and "we lost track" into the same row.

**The resolution: a lazy-created, per-tenant synthetic service user.**
`dependencies.py::resolve_api_key_service_user(tenant, db_session)` returns the `users.id` an
API-key request acts as, creating the row on first use if absent:

* `clerk_user_id = f"api_key_service_{tenant.id}"` — deterministic, unique per tenant,
  cannot collide with a real Clerk `sub` (those start `user_`).
* `email = f"api-key-service+{tenant.id}@service.invoice-llm.internal"` — `users.email` is
  globally unique, so the tenant id is inside the address; a reserved non-routable domain so
  nothing can ever try to deliver to it.
* `role = "Viewer"`, all three permission booleans `False`. **The row carries no authority.**
  Permissions for an API-key request come from the scope on the `TenantContext`, never from
  this row — it exists to satisfy the FK and to name the actor, nothing else. This is also why
  it does not require any `RoleMapper` change (Gap 337's boundary is respected).

**Lazy-created, not seeded at provisioning** — chosen deliberately:

* Seeding at tenant provisioning would create a synthetic user row for **every** tenant,
  including the overwhelming majority that never issue a key, and would require a backfill
  migration writing rows for every existing tenant. Lazy creation writes a row only for
  tenants that actually use an actions-scoped key.
* It keeps the change out of `routers/auth.py`'s provisioning path, which is the single most
  incident-prone function in this codebase (Gaps 133/157/173 all live there).
* Cost is one indexed lookup by `clerk_user_id` on API-key requests **at actions scope only**;
  readonly-scope requests keep `db_user_id=None` exactly as today and create nothing.

**Two consequences, both handled/recorded:**

* `routers/admin.py::list_tenant_users` would otherwise render this synthetic account in the
  Settings user list as if it were a person. It now excludes the one exact
  `clerk_user_id` value computed for the caller's tenant — exact equality, not a `LIKE`
  pattern, because `_` is a SQL `LIKE` wildcard and a pattern here would be quietly wrong.
* `routers/auth.py:201`'s unclaimed-tenant adoption check treats "has any users" as a blocker,
  so a tenant with a service-user row can no longer be adopted. Left as-is on purpose: a
  tenant whose actions-scoped key has genuinely been used is not an empty unclaimed tenant,
  and that check is documented as deliberately strict ("adoption firing wrongly is a tenant
  takeover").

### Routes rewired in Phase 0

Every one of these was read at its current wiring before being changed; the router-level vs.
per-endpoint distinction below is what the code actually does, not an assumption.

| Route | Before | After |
|---|---|---|
| `POST /invoices/upload` | `require_can_load` | `require_can_load_or_api_key` — human gate unchanged, any key scope passes |
| `GET /invoices`, `GET /invoices/{id}`, `GET /invoices/status/{job_id}`, `GET /invoices/{id}/pdf` | `get_tenant_context` | `get_tenant_or_api_key_context` (readonly sufficient) |
| `chat`: session list/create/rename/delete, `GET /sessions/{id}`, `POST /sessions/{id}/message`, `GET /jobs/{id}/status`, `GET /jobs/{id}/stream` | `get_tenant_context` | `get_tenant_or_api_key_context` (readonly sufficient — chat is not a financial action) |
| `routers/audit.py` (router-level, gates its single `PUT /resolve/{id}`) | `Depends(require_can_audit)` | `Depends(require_actions_scope)` |
| `routers/outbound_audit.py` (router-level, single `PUT /resolve/{id}`) | `Depends(require_can_audit)` | `Depends(require_actions_scope)` |
| `PUT /outbound-invoices/{id}/confirm-send` | `get_tenant_context` — **no permission gate** | `require_actions_scope` |
| `PUT /outbound-invoices/{id}/mark-paid` | `get_tenant_context` — **no permission gate** | `require_actions_scope` |

**Deliberately left alone in Phase 0**, and why:

* `POST /invoices/watcher/start` — a local-directory watcher is an operator tool, not an
  integration surface.
* `GET /invoices/stream/{batch_id}`, `GET /invoices/batches`, `DELETE /invoices/batches/{id}`,
  `DELETE /invoices/{id}` — SSE for a browser, and deletions, which are not in the founder's
  list of automated actions.
* `POST /outbound-invoices/upload` — outbound ingestion; not requested in Phase 0 and it
  would widen the AR surface without a stated need.
* Chat training routes (`/chat/rules/commit`, `DELETE /chat/rules/{id}`) — still
  `require_can_train`, consistent with training being excluded from `actions`.
* Everything on `routers/settings.py`, `routers/admin.py`, `routers/billing.py` — key auth must
  never reach tenant administration.

### Gap 337 — the role vocabulary: Admin, Auditor, Trainer (built 2026-08-29)

**The founder's decision.** The three user-facing roles are **Admin, Auditor,
Trainer**. "Viewer" goes away.

**Why this is not a rename.** `RoleMapper` already had four roles, and Trainer
already matched the founder's spec exactly (`can_train=True`, `can_audit=False`,
`can_load=False`) — recorded in Ground Truth above, before any of this was
touched. Nothing about Trainer changed. What changed is that the fourth name
stopped being offered.

**The actual problem: "Viewer" was two things wearing one name.**

1. A role an Admin could assign.
2. The system's **zero-permission fallback** — what an unmapped IDP role string,
   a missing/absent role, Gap 173's org-mismatch escalation clamp, the Admin
   console's pre-provisioned rows, the detach-on-remove path, and Gap 335's
   synthetic API-key service user all resolved to.

Job 2 does not go away just because job 1 does. And the fallback slot **must not
be one of the three real roles**: if it inherited Trainer, then every unknown
role string a third-party IDP emits, every org-mismatched session, and (before
Gap 335) every API-key request would silently acquire `can_train` — the ability
to rewrite the tenant's extraction rules. That is precisely the class of quiet
escalation Gap 173 exists to prevent, arriving through the back door of a
vocabulary change.

**The resolution: a nameless internal fallback.** `RoleMapper.NO_ROLE`, spelled
`"Restricted"`, with all three permission booleans False.
`RoleMapper.USER_FACING_ROLES == ("Admin", "Auditor", "Trainer")` is the
assignable set and `NO_ROLE` is deliberately **not** in it — it must never appear
in an invite dropdown or a role picker. A test asserts both properties so a
fourth user-facing role cannot reappear by accident.

**Every fallback site, and what each now does.** All were read at their current
wiring, not assumed:

| Site | Before | After |
|---|---|---|
| `RoleMapper.normalize_role(None/"")` | `"Viewer"` | `NO_ROLE` |
| `ROLE_ALIAS_MAP`: `org:member` / `member` / `viewer` | `"Viewer"` | `NO_ROLE` (`viewer` kept as a **legacy input alias** so an old Clerk role string still lands somewhere safe; `restricted` added) |
| `resolve_permissions()`'s unmapped-role default | `ROLE_PERMISSION_DEFAULTS["Viewer"]` | `...[NO_ROLE]` — so a stale `'Viewer'` row still resolves to `(False, False, False)`, not a `KeyError` |
| `reconcile_role_with_org()` (Gap 173 clamp) | clamps to `"Viewer"` | clamps to `NO_ROLE` |
| First-login clamp + unsafe-metadata Admin clamp (`dependencies.py`) | `"Viewer"` | `NO_ROLE` |
| Mock token `Bearer test_viewer` | role `"Viewer"` | role `NO_ROLE`; the **token spelling is deliberately unchanged** (it is fixture vocabulary across six test files, not user-facing copy) and `test_restricted` is accepted too |
| Gap 335 `resolve_api_key_context()` | `role = "Viewer"` | `role = NO_ROLE` |
| Gap 335 `resolve_api_key_service_user()` | `role="Viewer"` | `role=NO_ROLE` |
| `routers/admin.py::set_user_permissions()` pre-provisioned row | `"Viewer"` | `NO_ROLE` |
| `routers/admin.py::remove_tenant_user()` detach demotion | `"Viewer"` | `NO_ROLE` |

**One visible contract change, called out rather than buried.**
`GET /settings/security/api-key/verify` returns `role`, and for a key that field
is now `"Restricted"` instead of `"Viewer"`. It was never a permission input —
key permissions come from `permissions_for_key_scope()`, which is exactly why
Gap 335 derived them from scope rather than from a role string, and why nothing
had to be re-reasoned here. Any integrator asserting on that literal sees a
changed value; no access changes.

**The customer-facing copy was the highest-priority edit.**
`agents/support_agent.py` is the live Help Center chatbot and it was telling real
users to "select a role (`Admin`, `Auditor`, or `Viewer`)" and describing
Viewer's capabilities. It now names Admin / Auditor / **Trainer**, describes
Trainer's actual capability (rules in the AI Trainer, no audit or approval
rights), and adds an explicit line that Dashboard/Chat/Help are available to
everyone including a member with no role yet. That module has **zero automated
coverage** (confirmed by grep, same finding Gap 334 recorded), so this edit is
verified by reading the diff.

**Data migration `e9f0a1b2c3d4`** rewrites `users.role = 'Viewer'` → `'Restricted'`.
Deliberately **not** touched: `audit_logs.actor_role`, which records the role an
actor held *at the time they acted* — rewriting history to match today's
vocabulary is the one thing an audit trail must not do. Also untouched: any
Admin/Auditor/Trainer row, and any other free-text value an IDP produced.

### Gap 336 — `TenantWorkflowConfig` and the wizard's endpoint (built 2026-08-29)

Phase 0 stored the enforcement primitive. This is how a tenant *chooses* it
without an Admin editing a database column, plus the rest of the workflow shape
the wizard collects.

**The model.** `models.py::TenantWorkflowConfig`, one row per tenant, shaped
after `TenantAutopilotConfig` (the closest existing analogue): `UNIQUE(tenant_id)`
+ index, FK to `tenant.id`, `JSON_VARIANT` list columns.

| Column | Values | Note |
|---|---|---|
| `input_channels` | subset of `email` / `drive` / `api` / `manual` | all four work today; `api` because Gap 335 built its auth |
| `audit_policy` | `full_automation` / `strict_review` | **mirror, not source of truth** — see below |
| `output_destinations` | subset of `webhook` / `dashboard_only` | a stored intention; nothing reads it yet |
| `chat_access` | `dashboard` / `api` / `widget` | |
| `completed_at` | timestamp or null | set once, on the first successful save |

**The write-through, which is the actual point of this gap.**
`PUT /api/v1/settings/workflow` writes `Tenant.api_key_scope` in the **same
commit** as the config row:

```
full_automation  ->  Tenant.api_key_scope = "actions"
strict_review    ->  Tenant.api_key_scope = "readonly"
```

And `GET` **derives** `audit_policy` back from `Tenant.api_key_scope` rather than
reading `config.audit_policy`. That asymmetry is deliberate. `api_key_scope` is
the only column `require_key_scope()` enforces; if the two ever disagree — an
Admin editing the column directly, a partially applied write — the endpoint
reports what is *actually in force*, not what the wizard was last told. A PUT
that omits `audit_policy` re-derives it the same way, so an unrelated edit can
never quietly revert the policy to a stale row value. There is deliberately no
second, independent policy field.

**Validation: unbuilt destinations are rejected, not accepted-and-ignored.**
`email_summary` (Gap 339) and `drive_archive` (Gap 338) are designed and nothing
delivers to them. A request naming either gets a **422** whose message names the
destination, the gap that will build it, and what *is* available. Storing them
would leave a tenant believing its processed invoices are being emailed or filed
to Drive while nothing sends anything — a failure the tenant discovers only by
noticing an absence. Unknown values in either list are 422 as well, and
**validation runs before any write**, so a rejected request changes nothing —
including `api_key_scope`.

`input_channels` accepts all four values: `email` (Feature 14), `drive`
(Feature 13's sync), `manual` (the upload UI) and `api` (Gap 335).

> **Update 2026-08-30 (additive — the paragraph above is Gap 336's record and is
> left standing).** `email_summary` is **no longer rejected**: Gap 339 built its
> delivery, so the accepted set is now `webhook` / `dashboard_only` /
> `email_summary`, and only `drive_archive` (Gap 338) still 422s. `email_summary`
> carries a *different* new check in its place — it may only be selected when
> the tenant already has a registered `TenantEmailSender`, for the same
> "don't store a setting that can never deliver" reason. See the Gap 339 section
> below.

**Deviations from the original sketch, recorded rather than left implicit:**

1. **No `routers/workflows.py`.** The File Coordinates below originally called
   for a new router. The endpoints live in `routers/settings.py` instead: this
   is Settings configuration, it is Admin-gated exactly like `vendor-flow`, and
   it needs the same `Tenant` row that router already handles. A new router for
   two endpoints would have split one settings surface across two files.
2. **`GET` is Admin-only**, unlike `GET /settings/vendor-flow` which any role can
   read. It reports `api_key_scope` — security configuration — and its only
   consumer is the Admin-only Settings wizard.
3. **`chat_access` accepts `widget`** even though the widget token is Gap 341 and
   unbuilt. This is *not* the same case as the rejected destinations: storing
   "the tenant would like a widget" delivers nothing and promises nothing, while
   storing "email me summaries" implies an email that will never arrive. Flagged
   here so the distinction is a decision on the record, not an oversight. Gap 341
   should revisit it if a widget preference ever starts implying delivery.
4. **Nothing acts on `output_destinations` yet.** This gap persists and validates
   the choice; no delivery code reads the column. Worth knowing before assuming
   the feature is end-to-end.
   *(No longer true as of 2026-08-30: **Gap 339** made
   `services/workflow_outputs.py` the first reader of this column. Left in place
   because it is Gap 336's accurate record of its own scope.)*

### Gap 342 — provisioning completion: a new tenant leaves signup usable (built 2026-08-30)

Gap 335 built the auth for the `api` input channel and Gap 336 let a tenant
*select* it. Neither noticed that `routers/auth.py::provision_tenant()` creates a
`Tenant` row with Free Tier defaults and then stops, so two of the four channels
the wizard offers were dead the moment a workspace was created:

* **`api`** — `Tenant.api_key_hash` was NULL, so the credential Gap 335's
  dependency verifies did not exist until an Admin found Settings → Security and
  pressed Rotate.
* **`email`** — no `TenantEmailSender` row existed, and
  `routers/email_ingestion.py`'s webhook resolves both the tenant *and* the
  direction of an incoming mail **from that table**. A brand-new tenant's first
  forwarded invoice was therefore rejected as an unregistered sender and filed to
  `dropped_inbound_emails`. Email ingestion was unusable until somebody manually
  added a row.

This is not a gap this feature introduced. It has been live since email ingestion
shipped; Feature 25 is simply the first thing that made it obvious, by offering
both channels in a wizard.

**What was built.** Two helpers in `routers/auth.py`, plus one response field.

`_mint_provisioning_api_key(db_session, tenant)` reuses `services/api_keys.py`
end to end — `generate_api_key` / `generate_salt` / `hash_api_key` / `key_prefix`
— and writes the same four columns in the same order as
`routers/settings.py::rotate_api_key()`. No hashing, salting or prefix logic is
duplicated. `api_key_scope` is written explicitly as `readonly` rather than left
to the model default: Gap 335's fail-closed rule is that a brand-new tenant never
acquires `actions` scope automatically, and writing it makes that a decision in
the code rather than an inherited default that a future model change could move.

`_seed_admin_email_sender(db_session, tenant, admin_email)` writes one
`TenantEmailSender` row, `email_set="inbound"`, address normalised
`.strip().lower()` — byte-identical treatment to
`routers/email_ingestion.py::add_email_sender()`. The **outbound** set is
deliberately not seeded: it is gated on `send_invoices_enabled` and a paid plan,
and pre-authorizing an address to send invoices *to customers* is not something a
signup should decide.

**Idempotency, which is the whole risk here.** `services/api_keys.py` states in
its own docstring that there is one key per tenant by design and that issuance
works by *overwriting* hash + salt + prefix. A second mint therefore does not add
a key — it silently revokes the first, and the tenant discovers this as a 401
inside their integration. Three existing layers already guard the path, all
verified against the running code before anything was added:

1. `pg_advisory_xact_lock(hashtext(org_key))` serialises concurrent provisions
   for the same `clerk_org_id`;
2. `select(Tenant).where(Tenant.clerk_org_id == …)` early-returns `is_new=False`
   **before** any creation code is reached;
3. `Tenant.clerk_org_id` is `unique=True` at the schema level.

Both helpers additionally guard on their own state — the key is minted only when
`tenant.api_key_hash` is falsy, the sender seeded only when no row holds that
address — so the guarantee does not depend on all three of the caller's layers
being correct. A Clerk webhook retry, or two tabs finishing signup together,
cannot re-mint.

**The raw key follows this repo's existing shown-once contract.**
`TenantProvisionResponse.api_key: str | None` is the second and last place in the
whole API where a raw key is transmitted (the first being
`ApiKeyRotateResponse`). It is hashed on the way in, never stored in plaintext,
and never logged — the `[provision-diag]` line records the non-secret prefix
only, exactly as `rotate_api_key()`'s log line does. `None` on every other
outcome, which is what makes a repeated provision *observably* a no-op.

**Three decisions recorded rather than left implicit:**

1. **The legacy domain-adoption branch gets neither.** It returns `is_new=False`
   and is the pre-Clerk-Organizations linking path.
   `_tenant_adoption_blockers()` already refuses to adopt anything holding
   `TenantEmailSender` rows, so an adopted tenant is empty by construction — but
   widening a rare legacy branch was not in scope, and such a tenant has the
   ordinary rotate / add-sender endpoints.
2. **Today's only caller discards the key.**
   `invoice-website/app/signup/page.tsx` reads the provisioning response for
   error handling and does not surface `api_key`, so in practice a tenant must
   still rotate to *see* a key. The credential now exists and
   `GET /settings/security/api-key` reports `has_key=true`; surfacing it is FE
   work (FE Gap 323/325). Stated plainly because "minted but invisible" is a real
   if minor wart, not a solved problem.
3. **Neither addition can fail a signup.** Both are wrapped so an
   `IntegrityError` — a concurrent seed, an address already claimed by another
   workspace — rolls back and logs rather than propagating. A tenant that exists
   without a key is two clicks from being fixed; a 500 at the end of signup
   leaves a Clerk user with no workspace at all, which is precisely the failure
   Gap 133 was opened for.

**The address comes from the verified claim, never the body.** `admin_email` on
this path is already bound to the token's own `email` claim (Gap 133 Checkpoint
3c). The seed is skipped entirely when that claim is absent, because the
synthetic `{clerk_user_id}@domain.com` placeholder is not deliverable and
`TenantEmailSender.email` is *globally* unique — seeding placeholders would
collide across unrelated tenants.

### Gap 339 — the `email_summary` output destination (built 2026-08-30)

Gap 336 stored `output_destinations` and deliberately made it inert — nothing
read the column, which is exactly why `email_summary` was 422'd rather than
accepted. This gap is the first thing that **reads** it and acts.

**What happens now.** When an invoice reaches **PAID** through
`routers/audit.py::resolve_audit_invoice()` and the tenant's
`TenantWorkflowConfig.output_destinations` contains `email_summary`, the
tenant's registered addresses receive a short plain-text summary — vendor,
invoice number, amount, status, invoice date — with the invoice's extracted
fields attached twice: a CSV (one row per line item) and a JSON.

#### Recipients are pre-registered — the founder's decision, and what it buys

Recipients come from `TenantEmailSender`, the **same allowlist** that
`routers/email_ingestion.py` uses to decide whether an inbound mail may become
an invoice and that `services/staff_notify.py` validates its notify lists
against. There is deliberately **no** field anywhere that accepts a free-text
summary recipient.

The alternative — an address typed into the wizard — would have turned a
workflow setting into a "send mail from our domain to any address, on a trigger
the tenant controls" primitive, i.e. reopened precisely the outbound-spam
control `services/inbound_mail_security.py` and `staff_notify.py` exist to
enforce. Every other outbound path in this product already answers to that
allowlist; this one does too, and it is not a variation on the rule.

`email_set` is taken from the invoice's own direction via
`staff_notify.email_set_for_invoice()`, so an inbound invoice's summary can only
reach the inbound (AP) set. In practice everything reaching this code today is
INBOUND — the trigger is the inbound audit router — but keying it on the
invoice rather than hardcoding `"inbound"` is what keeps that true if the
trigger is ever widened.

#### The trigger point, and why there is exactly one

The founder's requirement was that a human clicking Approve in the Auditor
Review Console and an `actions`-scoped API key (Gap 335) calling the resolve
endpoint behave **identically**. They do, and not by keeping two call sites in
sync: both credentials converge on the *same handler*. `routers/audit.py`'s
router-level `require_actions_scope` admits either credential type, and
`get_tenant_or_api_key_context` normalises them into one `TenantContext` before
the handler body runs. So the trigger is a single block inside
`resolve_audit_invoice()`, after `db_session.commit()`, and there is nothing to
duplicate for the second path — duplicating it would have been the bug.

Placed **after** the commit on purpose: the summary must describe an invoice
that is actually PAID in the database, not one that is about to be.

**Fires on PAID only.** REJECTED is excluded (a rejected invoice has no result
worth exporting), as is Gap 193's `AUDIT_REQUIRED` reopen, which undoes a
finalization rather than being one, as is a plain alert-dismiss/correction with
no `target_status`. This is narrower than the webhook block immediately above
it, which fires on both PAID and REJECTED — that block dispatches two
*different* event types, this one has a single meaning.

**Deliberately not wired (stated so the boundary is on the record, not
implicit):** `routers/outbound_audit.py`'s resolve and
`routers/outbound_invoices.py`'s `mark-paid`. Those are the AR side; this gap
was scoped to the inbound approval event, and widening it would also widen which
sender set can receive a tenant's invoice data. If outbound summaries are ever
wanted, `deliver_email_summary()` already keys on the invoice's direction and
would need only the trigger call plus a matching change to
`EMAIL_SUMMARY_SENDER_SET`'s validation.

#### The MIME-type fix

`services/outbound_email.py::send_email()` hardcoded the attachment content type
to `"application/pdf"`, so the only attachment this module could send honestly
was a PDF. Nothing in the codebase actually passed an attachment yet (checked
repo-wide), so this was a latent defect rather than a live one — but a CSV
announced as a PDF is undisplayable in most mail clients, so it had to go first.

The type now travels with the bytes: `EmailAttachment(filename, content,
mime_type)`, plus an `attachments` list parameter for the multi-file case. The
old single-attachment parameters are unchanged and default
`attachment_mime_type` to `application/pdf` — **exactly the value that was
hardcoded** — so no existing caller changes behaviour. A test asserts that
default explicitly, so it cannot be "cleaned up" into something else later.

#### The CSV/JSON builder

`services/invoice_export.py` is genuinely new: there was no CSV or JSON export
anywhere in this backend (confirmed by repo-wide grep before writing it), so
nothing was reused. It is scoped as an **attachment builder**, not an export
feature — no endpoint, no UI, no multi-invoice bundle, no column selection.

`build_invoice_summary()` produces one dict; `build_invoice_csv()` and
`build_invoice_json()` both render *that*. Two independently-written serialisers
of the same row is how a CSV and a JSON quietly end up reporting different
totals; the indirection makes that impossible.

* **CSV** — flat, one row per line item, invoice-level fields repeated on each
  row. This is the ordinary "invoice lines" shape and stays a single rectangular
  table that opens in Excel without interpretation. An invoice with no line
  items still produces exactly one data row, because "no itemisation" and "the
  export broke" must not look the same. `lineterminator="\n"` is pinned: csv's
  default `\r\n` plus text-mode writing yields `\r\r\n`, which mangles the
  attachment.
* **JSON** — nested; `line_items` and `taxes` stay lists of objects.

Field names were read off `models.Invoice` and `agents/extraction_agent.py`'s
`InvoiceLineItem` / `TaxItem` schemas (`description` / `quantity` /
`unit_price` / `amount`; `tax_type` / `rate_percent` / `amount`), not invented.
`items` and `taxes` are free-form JSON columns, so every accessor tolerates a
non-dict entry — a weird line is kept as a description-only row rather than
dropped, since an attachment that silently omits a line is worse than one that
looks odd.

**Deliberately excluded from both files:** `file_path` (an internal blob path),
`coordinates` / `field_confidence` / `source_document_json` (extraction
internals, large and meaningless to a recipient), and `sa_alerts` (audit-console
state on an invoice that has already been resolved). A test asserts none of them
leak.

`export_filenames()` sanitises the invoice number down to `[A-Za-z0-9_-]` before
using it as a filename — it is vendor-controlled text that reached us through
OCR and is about to land in someone's mail client. `.` is excluded from the kept
set along with `/`, specifically so a number like `../../etc/passwd` cannot
leave a `..` segment; the only dot in the result is the one this function
appends.

#### A gap in Gap 336, found and closed here

Gap 336 had **no** check that `email_summary` could only be selected by a tenant
with a registered sender — it did not need one, because it rejected the
destination outright. The moment the destination became storable that hole would
have been real: a tenant with an empty allowlist could save "email me
summaries", and nothing would ever arrive. That is precisely the silent no-op
Gap 336's rejection of unbuilt destinations exists to prevent, arriving through
the back door of the destination becoming available.

So `_validate_destinations()` now takes the session and tenant id and 422s
`email_summary` unless at least one `inbound` `TenantEmailSender` row exists,
with a message naming the fix ("register one under Settings → Email first").
Gap 342 seeds exactly such a row at provisioning, so every tenant created since
2026-08-30 passes this automatically.

**And it is still handled defensively at delivery time**, because the allowlist
can be emptied *after* the destination was saved — deleting the last sender row
is an ordinary Admin action, and it must not start 500-ing every approval.
`deliver_email_summary()` logs a warning naming the tenant, the set and the
invoice, and returns `{"sent": False, ...}`.

#### Failure handling: an approval never fails because mail did

`deliver_email_summary()` **never raises** — every failure mode (no destination,
no recipients, no SendGrid key, a raising send) is logged and returned as a
`{"sent": bool, ...}` dict in the same shape `services/staff_notify.py`'s
notifiers use. The call site additionally wraps it in the same try/except the
webhook and RAG-backfill blocks use. The status transition has already
committed by that point; a mail outage must not be able to turn a successful
approval into a 500 or roll anything back.

The resolve response gains `"email_summary"`, null unless a summary was
attempted. Surfaced rather than kept internal so an integration can tell "no
summary was configured" apart from "a summary was configured and the send
failed" — the second is actionable, the first is not.

#### Not done, and not claimed

* **No FE change.** `invoice-fe`'s workflow wizard still renders `email_summary`
  with a "Not available yet — BE Gap 339" pill
  (`app/settings/workflows/page.tsx`). The backend accepts it now; the UI has
  not been told. That is FE work and out of this gap's scope.
* No outbound (AR) trigger — see above.
* No deployed run: local Postgres only, and the Azure dev database is still
  three migrations behind (unchanged by this gap, which adds none).
* No real SendGrid delivery was performed; the send client is mocked in tests.

### Gap 338 — the `drive_archive` output destination (built 2026-08-30)

The second destination, and the one that closes Task 25.3. When an invoice
reaches **PAID** through `routers/audit.py::resolve_audit_invoice()` and the
tenant's `output_destinations` contains `drive_archive`, three files are written
into the tenant's connected Google Drive: the invoice's CSV, its JSON, and its
original source PDF.

It is deliberately built *in* Gap 339's machinery rather than beside it — same
module (`services/workflow_outputs.py`), same builders
(`services/invoice_export.py`), same single trigger point, same never-raises
contract, same `{"…": bool, "code": …}` result shape surfaced on the resolve
response. The file a tenant receives by mail and the file it finds in Drive are
byte-identical because they come from the same function call; there is no second
serialiser and no second trigger to keep in sync.

#### The hard part: this is an OAuth migration, not just new code

Feature 9's connector asks Google for
`https://www.googleapis.com/auth/drive.readonly`. Reading is not writing, and
**scope is a property of the grant, not of what the app asks for today**: an
access or refresh token minted under the old consent screen carries exactly the
scopes the user approved then, and Google does not silently widen an existing
grant when an app starts requesting more. So every `TenantConnection` row for
`google_drive` created before 2026-08-30 is *connected* and *not writable*, and
those are two different questions that this feature had to stop conflating.

**The new request is `drive.readonly drive.file` — two scopes, and specifically
not the bare `drive` scope.**

* `drive.file` grants access only to files this app itself created (or that the
  user explicitly opens with it). `drive` grants access to the entirety of the
  user's Drive. Asking a tenant for full Drive access in order to drop three
  files in it is not a proportionate ask, and it was refused. The bare `drive`
  scope is still *accepted* when detecting an existing grant — it is a superset,
  so a token carrying it can write — but this app never requests it.
* `drive.readonly` stays because `drive.file` **cannot read** the tenant's
  pre-existing invoice PDFs. Dropping it would have broken the connector import
  (Feature 9) and the Autopilot sync (Feature 13) in exchange for a write path.
  Both directions are needed, so both scopes are requested.

**The visible consequence of choosing the narrow scope, recorded because it will
otherwise look like a bug:** the archive lands in an app-created folder named
`InvoiceEQ Archive`, *not* in the folder the tenant picked in the connector
browser (nor in `TenantAutopilotConfig.source_ref`). Under `drive.file`, naming a
user-created folder as a `parents` entry is rejected — the app may only write
into a folder it created itself. The alternative was the full `drive` scope. The
folder is found-or-created once per tenant via `files.list`, which under
`drive.file` can only ever see app-created files, so it cannot shadow or collide
with a user folder of the same name.

#### Detecting the old grant — lazily, and in two places

`drive_archive_readiness(db_session, tenant_id)` is the single implementation of
"can this tenant's Drive actually receive a file right now". It reads the
`TenantConnection` row, refreshes the token through the existing
`get_valid_access_token()`, and asks **Google's tokeninfo endpoint**
(`https://www.googleapis.com/oauth2/v3/tokeninfo`) what that token was actually
granted. `utils/connector_oauth.py::google_granted_scopes()` /
`token_has_drive_write_scope()` are the probe. (`googleapiclient` /
`google-auth` are not used anywhere in this backend — checked, not assumed; the
connector layer is plain `httpx`, so the probe is too.)

It runs at exactly two moments, both lazy, and **no existing tenant is forced
through a re-auth**:

1. **When the destination is selected** — `PUT /settings/workflow` 422s
   `drive_archive` unless readiness passes, with the reconnect instruction in
   the message. This is the same shape as Gap 339's registered-sender check and
   exists for the same reason: storing a destination that cannot deliver is the
   silent no-op Gap 336's rejection rule was written to prevent.
2. **Before each write** — because a tenant can disconnect Drive, or revoke the
   grant on Google's side, at any time after saving. Handled defensively rather
   than asserted, exactly as Gap 339 handles the last email sender being deleted
   after the fact.

A tenant that never turns this destination on is never asked for anything. That
was the design constraint: the alternative — invalidating every existing
connection and demanding a re-consent up front — would have interrupted every
Drive-using tenant for a feature most of them will not enable.

**The three-state scope answer, which is where the subtle bug would have been.**
`token_has_drive_write_scope()` returns `True` / `False` / `None`, and `None`
(Google unreachable, or an unexpected response) is deliberately **not** folded
into `False`:

| Probe result | `code` | `ready` | Behaviour |
|---|---|---|---|
| write scope present | `ok` | yes | archive normally |
| readonly only, or an invalid/revoked token (tokeninfo 400) | `reconnect_required` | no | 422 on select; logged skip on write |
| could not ask | `scope_unknown` | **yes** | attempt the write anyway |

Refusing on an indeterminate answer would let a blip on Google's side block a
tenant's configuration and silently stop archiving for a connection that is
perfectly fine. So it **fails open at the probe and fails loud at the write**:
if the grant really was read-only, Drive answers the create with `403`
(`401` for a revoked token), and `deliver_drive_archive()` translates both back
into the *same* `reconnect_required` code rather than surfacing a raw HTTP
error. The tenant gets one actionable state from two different detection paths.

Two further readiness states, kept distinct because their fixes differ:
`not_connected` (no active `google_drive` row — `status != "active"` counts as
not connected, matching what `routers/connectors.py` already enforces) and
`token_unusable` (`get_valid_access_token()` raised: no refresh token stored, or
the provider rejected the refresh). A sixth, `oauth_not_configured`, covers a
deployment with no Google OAuth app at all, where the stored token is the mock
exchange's `mock_access_token_…` string — probing or uploading with it would
produce a confusing 401, so it is named instead.

#### The write itself

`utils/connector_files.py` gained the write direction it never had (it held only
`list_google_drive_files` / `download_google_drive_file`; Salesforce went in Gap
334):

* `upload_google_drive_file(access_token, folder_id, filename, content_bytes,
  mime_type)` — one request, using Drive's `multipart/related` upload form so the
  metadata and the bytes travel together. The two-step create-then-PATCH-media
  alternative has a window in which a named 0-byte file exists in the tenant's
  Drive that looks like a successful archive; this has no such window. It
  always **creates**, never updates in place, so two approvals of the same
  invoice leave two files rather than one silently overwritten — an archive that
  can lose an earlier version is not an archive. It raises
  `httpx.HTTPStatusError` on a non-2xx on purpose: that is how the caller learns
  about the 403 above.
* `find_or_create_google_drive_folder(access_token, name, parent_id=None)` —
  ordered by `createdTime` so a race that creates two folders still resolves
  deterministically to one.

The source PDF is fetched with the existing
`services/storage.py::download_pdf_from_storage()`. **A missing blob does not
cost the tenant the other two files**: that one failure is isolated and reported
as `source_pdf_included: false` rather than aborting the archive. An invoice with
no `file_path` skips the download entirely.

#### Failure handling, and what the endpoint reports

`deliver_drive_archive()` **never raises** — same contract, same reasoning, and
the same belt-and-braces try/except at the call site as Gap 339. The status
transition has already committed by the time Drive is touched; a Drive outage, a
revoked token or a read-only grant must not be able to turn a successful
approval into a 500. Each destination gets its **own** try/except at the call
site so a fault in one cannot suppress the other — they are independent choices
by the tenant.

The resolve response gains `"drive_archive"`, null unless an archive was
attempted. Its `code` is the field worth reading: `reconnect_required` is how an
integration learns the tenant's Drive grant is read-only without parsing a
message or reading backend logs.

#### Not done, and not claimed

* **No FE change.** `invoice-fe`'s workflow wizard still renders `drive_archive`
  with a "Not available yet — BE Gap 338" pill, and there is no
  reconnect-required banner on the Connectors page. The backend accepts the
  destination and reports the state; the UI has not been told. FE work, out of
  scope here.
* **No real Google Drive call was made.** There is no Google account in this
  environment; the upload/folder/scope-probe seams are mocked in tests, exactly
  as Gap 339 mocked SendGrid. What is asserted is the precise call that would
  have been made.
* **No backfill and no forced re-auth** — by design, see above. Tenants
  connected before 2026-08-30 stay read-only until they reconnect.
* No outbound (AR) trigger, no deployed run, no schema change and therefore no
  migration (the Azure-dev migration count is unchanged at three).

### Found while scoping this feature, fixed, and filed elsewhere — Gap 343

`services/billing_quota.py`'s free-tier charge was wired into `routers/invoices.py`
and nowhere else, so the Google Drive import, the scheduled Autopilot sync and the
outbound upload all created invoices without charging quota. Found during this
feature's route audit and fixed on 2026-08-30, but it is a **billing** defect with
no relationship to plug-and-play, so it is filed as **Gap 343 under Feature 11**
and specified in `feature_11_billing.md` → "Free-tier quota bypass on three ingest
doors". Recorded here only so the trail from "found during Feature 25 scoping" to
"lives in Feature 11" is not lost.

### Gap 340 — sandbox `inv_test_` keys (built 2026-08-30)

The founder decision this gap was blocked on has been made, and it is the
stronger of the two options that were on the table:

> A sandbox key resolves to a **fresh, real `Tenant` row** — not a shared demo
> tenant with a flag on it — issued to an **anonymous website visitor with no
> login**, and that workspace can later be **claimed** by a real signup instead
> of being discarded.

That is what makes the sandbox worth having: a visitor uploads their own invoice
and sees their own extraction, and if they sign up they keep it. It is also what
makes this the sharpest thing in the backend, because it is the only place the
product hands a working credential to a stranger. A dedicated security review
ran against this scope **before any code was written**, and the seven sandbox
constraints below are its findings, built in rather than deferred.

#### 1. A sandbox tenant is structurally outside the adoption path

`routers/auth.py::_tenant_adoption_blockers()` — hardened by **Gap 344** the same
day to refuse any tenant holding API key material — decides whether a
domain-matched tenant may be handed to whoever is signing up. A sandbox tenant
must never be a candidate, and it is excluded three independent ways:

1. **Its `domain` is synthetic and non-matchable.** `services/sandbox.py::
   sandbox_domain()` returns `sandbox-<tenant_id>.invalid`. `.invalid` is RFC
   2606's reserved never-resolving TLD — the same device
   `_create_tenant_with_unique_domain()` already uses for a colliding org domain
   (`org-<clerk_org_id>.invalid`), so this follows an existing precedent rather
   than inventing one. `provision_tenant()` looks a domain tenant up by
   `admin_email.split("@")[-1]`, and for that to find a sandbox a caller would
   need a Clerk-verified email whose domain is one specific tenant's UUID under a
   TLD that cannot receive mail. The tenant id is inside the value because
   `Tenant.domain` is `unique=True, nullable=False` and every sandbox needs a
   distinct one.
2. **It always holds key material**, so Gap 344's check already blocks it.
3. **`_tenant_adoption_blockers()` now names it directly** — `"a sandbox
   workspace"` — so the exclusion does not depend on two properties of *other*
   code staying true.

A real-Postgres test drives the actual endpoint with the attacker-optimal input
(a signup whose email domain *is* the sandbox tenant's synthetic domain) and
asserts the signup gets its own fresh tenant.

#### 2. Claiming is an explicit, atomic, single-winner transaction

`POST /api/v1/sandbox/claim` (`routers/sandbox.py`), backed by
`services/sandbox.py::claim_sandbox_tenant()`. It is deliberately **not** a side
effect of the adoption branch: adoption is a *heuristic* ("this empty
domain-matched tenant probably belongs to whoever is signing up"), and Gaps 133
and 344 are both records of that heuristic being dangerous. A claim is not a
guess — the caller presents the sandbox key, which is possession of one specific
workspace.

The concurrency mechanism is the one `provision_tenant()` already uses, not a new
one:

1. `pg_advisory_xact_lock(hashtext('sandbox:claim:<tenant_id>'))`;
2. the row is **re-read under the lock** (`populate_existing=True`, for the same
   reason `services/billing_quota.py` needs it — without it SQLAlchemy answers
   from the identity map with pre-lock values, so the lock holds while the
   predicate is evaluated against stale state);
3. a **compare-and-set on `claimed_at IS NULL`**, the explicit unclaimed
   predicate. The loser gets `already_claimed`, never a silent overwrite.

**The key swap is in the same transaction**, and that is a requirement rather
than an optimisation: attaching the Clerk org in one commit and rotating the key
in another leaves a window in which a stranger's `inv_test_` key and the new
owner's workspace both work. `services/api_keys.py` is one-key-per-tenant by
design, so overwriting hash+salt+prefix *is* the revocation.

The domain stays synthetic on claim (`org-<clerk_org_id>.invalid`) rather than
becoming the claimer's real email domain. Rewriting it would (a) risk a
`Tenant.domain` UNIQUE collision turning a successful claim into a 500, and
(b) make the workspace a domain-adoption target for the *next* signup from that
domain — reopening what Gap 344 just closed. Scope also stays `readonly`:
claiming does not grant Full Automation.

#### 3. No `User` row and no `TenantEmailSender` row, ever

Both `User.email` and `TenantEmailSender.email` are **globally unique** columns.
Giving a sandbox tenant either would let an anonymous visitor squat a real
address and turn the real owner's later signup into a conflict — the same class
of defect Gap 133 Checkpoint 3c fixed by binding `admin_email` to the token.

The review's precondition — that `resolve_api_key_context()` works fine with
`db_user_id=None` — was **confirmed against the code, not assumed**: the
synthetic service user is resolved only at `actions` scope (Gap 335), which a
sandbox tenant can never reach. A test asserts a readonly sandbox key
authenticates with `db_user_id=None` and creates no rows.

#### 4. Permanently pinned to `readonly`

Three layers, because this is the credential a stranger holds:

* written as `readonly` at creation, explicitly rather than by model default;
* **re-derived on every authentication** in `resolve_api_key_context()` — so a
  direct database edit, or some future code path that widens `api_key_scope`,
  still cannot hand approve/send/mark-paid to a visitor's key;
* refused at `PUT /settings/workflow` when `audit_policy=full_automation`.

That third one is **already unreachable and was written anyway**. A sandbox
tenant has no `User` row (constraint 3), so nobody can hold a Clerk session for
it, so `get_tenant_context` cannot resolve one, so `_require_admin_for_workflow()`
cannot pass — which the review asked to be *verified rather than assumed*, and it
was. All three of those reasons are properties of other code; the pin is stated
where the widening happens so it survives a change to any of them.

#### 5. Issuance is rate-limited and hard-capped, failing closed

`routers/support.py::_ContactRateLimiter` is **reused**, not reimplemented. The
hard part it already solves is not the sliding window — it is
`_get_client_ip()`'s answer to "which IP claim can this platform trust"
(Front-Door-verified `X-Azure-ClientIP`, then our own proxy's `X-Client-IP`, then
the *rightmost* `X-Forwarded-For` entry, then the socket peer). BE Gap 249 is the
record of what getting that wrong costs, and a second implementation would have
been a second, drifting answer.

Two small, backward-compatible changes made the reuse honest rather than a copy:
the limiter takes a `redis_key_prefix` (both instances key on `ip:<addr>`, so a
shared namespace would make a contact-form submission eat a visitor's sandbox
allowance), and `email` became optional — the anonymous case has no address, and
a constant placeholder would put every visitor in one shared bucket. The contact
form's own default and stored keyspace are unchanged, asserted by a test.

On top of that, a **hard global cap on unclaimed sandbox tenants**
(`SANDBOX_MAX_UNCLAIMED_TENANTS`, default 500), counted **under a
`pg_advisory_xact_lock`** so two concurrent issuances cannot both read
`count == cap - 1` and both create. Past the cap, issuance returns **503
"temporarily unavailable"** and creates nothing. A rate limit bounds one client;
only a global cap bounds many.

The whole router is additionally behind `SANDBOX_KEYS_ENABLED`, **default
False** — same fail-closed reasoning as `ALLOW_MOCK_AUTH`. A deployment that has
not thought about this surface 404s it.

#### 6. A real TTL, and a real reaper — both, not either

`SandboxTenant.expires_at` is enforced **live, on every authentication**, inside
`resolve_api_key_context()`: an expired key stops verifying immediately. That is
deliberate rather than leaving expiry to the sweep — a missed job run would
otherwise silently extend every outstanding key indefinitely.

`scripts/sweep_sandbox_tenants.py` is the other half, following
`scripts/sweep_billing_lifecycle.py` (Gaps 119/121, invoked daily by an ACA Job)
exactly: same `sys.path` bootstrap, same `--dry-run` contract, same logging
shape. It **deletes the workspace** — sandbox row, tenant row, invoices, chat
sessions/messages/feedback, workflow config — rather than setting a flag. A
claimed sandbox is never expired and never reaped (`sandbox_is_expired()` returns
False for it), re-asserted per row inside the sweep loop because "it was in the
list" is not a good enough reason to delete a customer's workspace.

#### 7. Chat is metered, because nothing else meters it

The review's finding here is worth stating plainly: **`services/billing_quota.py`
covers ingestion only. There is no quota anywhere in this backend for chat or LLM
calls.** That was acceptable while every chat caller was a signed-up tenant. A
sandbox key is handed to an anonymous visitor, so without this it is an unmetered
path to real Azure OpenAI spend, funded by us, available to anyone who can click
a button on the marketing site.

`SandboxTenant.chat_messages_used` is a plain bounded counter, charged in
`routers/chat.py::post_chat_message()` (and, defensively, on the widget route)
**before** the answer is generated — metering after the model call means a caller
who disconnects mid-turn has spent money and been charged nothing. It
deliberately does **not** reuse `charge_free_quota()`'s `SELECT … FOR UPDATE` row
lock: that machinery exists because an upload batch's billable count is derived
from content hashes and a concurrent batch could over-spend a paid allowance.
Neither applies to one increment of one integer on a workspace whose issuance is
already rate-limited and capped; the worst case of a lost update is one extra
chat turn, not money.

> **Corrected 2026-08-30 by Gap 352 — the paragraph above is Gap 340's record of
> its own reasoning and is left standing, but its last sentence was wrong and the
> code no longer matches it.** Two independent security reviews found the same
> defect: `charge_sandbox_chat_message()` was a read-then-decide-then-write with
> no row lock and no atomic `SET col = col + 1`, and each chat request runs in
> its own session/transaction. "The worst case of a lost update is one extra chat
> turn" holds for exactly **two** racers. For **N** concurrent requests all
> reading the counter before any of them commits, the loss is **N−1** turns — and
> N is the choice of whoever holds the `inv_test_` key, not a fixed small number.
>
> **Measured, not argued.** Against real Postgres, limit set to 5, 24 concurrent
> charges off one sandbox key, pre-fix: **22–24 turns allowed** across repeated
> runs with the persisted counter left at **3–5**. The 25-message allowance — the
> single control standing between an anonymous stranger and unmetered Azure
> OpenAI spend — bounded nothing.
>
> **The fix is `services/billing_quota.py`'s existing idiom, not a new one.**
> `locked_sandbox_select()` mirrors `locked_tenant_select()` exactly (statement
> builder exposed so a test can assert `FOR UPDATE`), and the function now does:
> an unlocked pre-check purely to stay lock-free for ordinary tenants (which is
> every tenant on every chat turn) → `SELECT … FOR UPDATE` on the `SandboxTenant`
> row → **re-read under the lock** with `populate_existing=True` (load-bearing for
> the same reason it is in `charge_free_quota()` and `claim_sandbox_tenant()`:
> without it SQLAlchemy answers from the identity map and the lock holds while the
> limit check reads stale state) → re-check `claimed_at` and the limit under the
> lock → increment → commit. The pre-check can only ever *narrow*: an ordinary
> tenant cannot become a sandbox and a claimed sandbox cannot become unclaimed, so
> a `None` from it is never a missed charge; a concurrent claim or reaper delete
> arriving after it is caught by the re-check.
>
> The increment stays computed in Python rather than becoming `SET col = col + 1`:
> the check and the write must be **one decision**, and an atomic increment alone
> would still let a request past a spent allowance. The lock is what makes them
> one decision. The refused branch deliberately does **not** roll back — it
> returns into a caller that raises 402 immediately and the lock releases when the
> request's session closes, which is byte-for-byte what `charge_free_quota()` does
> on its own 402 branch; rolling back would give this function the power to
> discard a future caller's uncommitted work.
>
> Post-fix, same harness, every run: **exactly 5 allowed, 19 refused, counter 5.**
> See Verification Plan §20.

> **Amended again 2026-08-30 by Gap 353 — the lock was right, the *reported*
> number was not.** Feature 25's final regression gate found Gap 352's own
> concurrency test failing about 1 run in 5. Everything the lock exists for held
> in every run, including the failing ones: exactly `limit` turns granted, the
> right number refused, and the persisted counter equal to the turns granted.
> What failed was the fourth assertion — that the granted turns report `used`
> values `1..limit` with no duplicates. Observed: `[1, 2, 3, 5, 5]`,
> `[1, 3, 3, 4, 5]`, `[1, 2, 4, 4, 5]`. **A reporting defect, not a security
> defect**, and the two are worth keeping apart: the bound was never breached.
>
> **Root cause: the returned value was read after the lock had already been
> released.** The function did `sandbox.chat_messages_used += 1` →
> `db_session.commit()` → `db_session.refresh(sandbox)` → return
> `sandbox.chat_messages_used`. **`commit()` is what ends the transaction and
> releases the `FOR UPDATE` lock**, so the `refresh()` was an ordinary unlocked
> read of a row another request may already have advanced in the window between
> the two calls. Two callers landing in each other's commit/refresh window are
> both handed the later number, and the number in between is reported to nobody.
> The lock covered the *decision* (check + increment); it stopped at the commit,
> and the value handed back was read past that boundary.
>
> **The fix is an ordering change, not a new mechanism.** The number to report is
> now captured into a local **between the increment and the commit** — while the
> lock is still held — and that local is returned. It is this request's position
> in the allowance by construction, because it is computed from the value re-read
> under this lock and no other transaction can have incremented in between. The
> post-commit `refresh()` is **deleted** rather than kept alongside: it is the
> offending read, the value is already captured, and the ORM instance is not used
> again after the return. (`charge_free_quota()` keeps its own `refresh()`
> legitimately — it returns the live `Tenant` instance for the caller to keep
> using; this function returns a plain dict, so it has no such obligation.)
> Everything else in the paragraphs above — `locked_sandbox_select()`, the
> pre-check, the re-read, the re-checks, the Python-side increment, the
> no-rollback refused branch — is **unchanged**.
>
> **Before/after on the same database, because one clean run does not close a
> race.** Pre-fix reporting restored: **13 passed / 7 failed out of 20 (35%)**.
> Fixed: **25 passed / 0 failed out of 25**. See Verification Plan §22.

#### What was built

`services/sandbox.py`, `routers/sandbox.py`, `scripts/sweep_sandbox_tenants.py`,
`models.py::SandboxTenant`, six settings, and migration `b1c2d3e4f5a6`.
Three endpoints:

| Route | Auth | What it does |
|---|---|---|
| `POST /api/v1/sandbox/keys` | **none** | Issues a sandbox key + its fresh tenant |
| `GET /api/v1/sandbox/keys/me` | the sandbox key itself | Remaining expiry / chat / invoice allowance |
| `POST /api/v1/sandbox/claim` | Clerk session **+** the sandbox key | Promotes the workspace, replaces the key |

`SandboxTenant` is a table rather than columns on `Tenant` for two reasons: every
predicate in this feature is "does a row exist, and is it unclaimed", and a
nullable column's fail-open answer (NULL) would look identical to "an ordinary
tenant"; and five columns on the hottest table in the schema for a state almost
no row is in is the wrong trade.

#### One real bug this found, worth recording

The first Postgres run failed with a `ForeignKeyViolation`:
`issue_sandbox_tenant()` added the `Tenant` and the `SandboxTenant` in one flush
and the child row went out first. Because the function swallows `IntegrityError`,
it returned a silent `None` that looked exactly like hitting the global cap. An
explicit `db_session.flush()` between the two fixes it. **SQLite does not enforce
foreign keys by default, so the entire path passed there** — this is the fourth-
plus instance of the fidelity gap CONVENTIONS.md hard rule 2 exists for.

#### Not done, and not claimed

* **Blob cleanup.** The reaper deletes `Invoice` rows but not the PDFs behind
  `Invoice.file_path`. Nothing in this backend deletes a blob anywhere yet
  (`DELETE /invoices/{id}` is a soft delete), and inventing a storage-deleting
  code path inside a sweep job is a larger change than this gap. A known residue,
  stated rather than left implicit.
* **The ACA Job is not declared.** `scripts/sweep_sandbox_tenants.py` follows the
  billing sweep's pattern but no bicep resource schedules it —
  `infra/modules/compute/` was not touched. Until that lands, expiry is enforced
  by the auth check alone, which is the half that actually closes access.
* **No FE or website surface.** The "try it" button that would call
  `POST /sandbox/keys`, and the claim step in the signup flow, are FE/website
  work (FE Gap 325) and out of scope here.
* **`SANDBOX_KEYS_ENABLED` is False everywhere**, including local `.env` and the
  bicep params. Nothing is live.
* No deployed run; local Postgres only.

### Gap 341 — the embedded chat widget token (built 2026-08-30)

`chat_access = "widget"` has been storable since Gap 336 with no runtime effect.
This builds the runtime.

A widget token is pasted into **a tenant's own website's client-side code**, so
their visitors can ask the assistant a question without signing in to this
product. It is therefore visible in page source to every visitor, crawler and
browser extension, and every decision below follows from that one fact.

#### The containment is structural, not procedural

The review's constraint was that a widget token must **not** resolve to the same
`TenantContext` that `require_actions_scope` / `require_can_load_or_api_key`
inspect. It does not:

* `dependencies.py::WidgetContext` is its own type with **four** fields —
  `tenant_id`, `widget_token_id`, `auth_method`, `origin`. It has no `role`, no
  `key_scope`, no `db_user_id` and **none** of `can_train` / `can_audit` /
  `can_load`. Every permission gate in `dependencies.py` is annotated
  `context: TenantContext` and reads one of those fields, so a scope-check bug
  anywhere in the codebase has structurally nothing to check against for a widget
  token — there is no field for the bug to get wrong.
* `routers/widget.py::get_widget_context()` is declared in the widget router, not
  in `dependencies.py`. That file is where a reader goes looking for something to
  reuse, and this one must not be reused. A test walks every route in the running
  app and asserts the dependency is mounted on **exactly one** path.
* `resolve_api_key_context()` refuses a widget token outright, so even a token
  sent to a REST route cannot become a `TenantContext`.

It is **not** a third credential in `Tenant.api_key_hash`/`salt`/`prefix`. Those
are one-key-per-tenant by design, a widget token is a different trust level, and
a tenant may legitimately hold several (one per embedded site) — revoking the
marketing site's token must not break the docs site's. Hence `models.py::
WidgetToken`, with `token_prefix` **UNIQUE** (unlike `Tenant.api_key_prefix`,
which is only indexed) because it is the sole cross-tenant lookup key.

Storage reuses Gap 184's primitives verbatim — PBKDF2-HMAC-SHA256 with a fresh
per-token salt, `hmac.compare_digest`, shown-once. No hashing is reimplemented.

#### Prefix dispatch: one credential, two headers, one answer

`services/api_keys.py` gained `SANDBOX_KEY_PREFIX`, `WIDGET_TOKEN_PREFIX`,
`PLATFORM_CREDENTIAL_PREFIXES` and `looks_like_platform_credential()`.
`_extract_api_key()`'s Bearer test widened from the single `inv_live_` literal to
that function, so `Authorization: Bearer inv_widget_...` is picked up **in order
to be rejected with an accurate message**. Before, it would have fallen through
to the Clerk verifier and 401'd about a token signature while the identical value
in `X-API-Key` 401'd about an invalid API key — one credential, two headers, two
unrelated errors, and an integrator losing an afternoon. A parametrised test
asserts both headers now produce the same message, which names the one route the
token is good for.

`key_prefix()` became prefix-aware so each credential type keeps six characters
of its secret visible rather than a number that falls out of `inv_live_`'s
length. **For `inv_live_` the output is byte-identical** (9 + 6 = 15) and a test
pins that, because `Tenant.api_key_prefix` is an indexed lookup column and
changing its width for existing rows would 401 every live key.

#### CORS, and the thing that was deliberately not done

The review was explicit: **do not fix widget CORS by widening `ALLOWED_ORIGINS`
in `main.py`'s global `CORSMiddleware`.** That middleware runs with
`allow_credentials=True`, so adding a customer's domain would make every
session-authenticated route in the product cross-origin reachable, with
credentials, from that domain. It was not widened, and a test asserts the origin
list still contains only first-party values.

Instead, `routers/widget.py::WidgetCORSMiddleware` — path-scoped to
`/api/v1/widget`, mounted **after** the global one so Starlette makes it the
outer of the two (it therefore answers a preflight for an unknown origin, which
the inner one would pass through to a 405). It reflects the request `Origin`
with `Vary: Origin`, and emits **no** `Access-Control-Allow-Credentials`. That
last point is what makes reflecting an arbitrary origin safe here and unsafe in
the global middleware.

**And "emit no credentials header" turned out not to be enough.** Starlette's
`CORSMiddleware` puts `Access-Control-Allow-Credentials: true` in its
`simple_headers` and applies them to **every** response to a request carrying an
`Origin` — unconditionally, before it decides whether the origin is allowed;
only `Access-Control-Allow-Origin` is conditional. So the inner global middleware
was stamping the credentials header onto widget responses, and combined with the
reflected origin a browser would have been told it may send cookies cross-origin
to a customer's site. `WidgetCORSMiddleware._apply()` therefore **deletes** the
header rather than merely not setting it. This was caught by
`test_widget_response_never_allows_credentials`, which asserts the absence on a
real response rather than on the function's output — the version that only
checked the middleware's own headers would have passed.

#### Origin pinning: a layer, and its limits stated

`WidgetToken.allowed_origins` is checked against `Origin`/`Referer`. This is
worth having — those headers are browser-set and cannot be overridden by page
JavaScript, so it does stop a scraped token being reused from another *site*.

It stops nothing outside a browser: `curl -H 'Origin: https://acme.com'` is the
entire bypass. So it is one defensive layer on top of the structural containment
above, never a substitute, and **nothing in the code or the docs claims
otherwise** — the module docstring, the model docstring and the dependency all
say so in those terms. There is also a test,
`test_origin_pinning_is_bypassable_outside_a_browser`, which **passes by
demonstrating the bypass**; writing the limitation down as an executable
assertion is what stops a later reader treating the allowlist as a hard boundary.

An empty allowlist disables the layer rather than denying everything — a
default-deny empty list would make every freshly issued token dead on arrival,
with a support ticket as the fix.

#### The route, and why it reuses the dashboard's turn

`POST /api/v1/widget/chat/message` is the only route a widget token reaches. It
creates or reuses a `ChatSession` (another tenant's `session_id` is a 403, not a
silent new session — a published credential and guessable UUIDs make that check
load-bearing) and then calls `routers/chat.py::run_sync_chat_turn()`.

That function is **extracted verbatim** out of `post_chat_message()`'s
synchronous branch, not copied. Ordering (commit before judging and before
`track_chat_turn`), the rollback-and-re-add on an agent exception, and the
conditional title write are all unchanged. Two copies is how the quality judge
and the turn telemetry drift apart between the dashboard and the widget — and a
widget turn that emits no telemetry is invisible in exactly the surface where an
anonymous end user is talking to the product.

Always synchronous. Gap 280's async path returns a `job_id` the caller polls, and
job status/stream are chat-router routes a widget token cannot reach.

Management is Admin-only, on the Clerk path, in `routers/settings.py`:
`GET`/`POST`/`DELETE /api/v1/settings/security/widget-tokens[/{id}]`. Revocation
stamps `revoked_at` and is checked on every resolve, so it takes effect on the
next request rather than at a TTL boundary — which matters when the realistic
revocation trigger is "we found it in a paste".

#### Also fixed here: chat job tenant isolation (review item 12)

`routers/chat.py::get_chat_job_status()` and `stream_chat_job()` both declared a
`tenant_context` dependency and **never read it**. They authenticated the caller
and checked nothing else, so any authenticated caller who learned a `job_id`
could read another tenant's chat answer — the reply text, the generated SQL and
the citations, all of which are that tenant's invoice data. Every other handler
in that router does the check (`_get_owned_message()`, the session handlers);
these two were the exception.

It was dormant — `ENABLE_ASYNC_CHAT_QUEUE` defaults False, so no job ids exist to
guess in a default deployment — and it is fixed anyway, **before** the widget
token lands, because a credential in public page source drops the bar for "an
authenticated caller" to "anyone who viewed the page".

`_require_owned_chat_job()` resolves ownership through the database
(`ChatMessage.job_id` → `session_id` → `ChatSession.tenant_id`), not through the
Redis status blob: `enqueue_chat_job()` does put `tenant_id` in that blob, but
`complete_job()` and `fail_job()` overwrite it with one that has no tenant in it,
so a finished job's cache entry cannot answer the question at all. An unknown job
id is a **404**, not a 403, so the pair of responses is not a probe for which job
ids exist elsewhere. On the stream endpoint the check runs **before** the
`StreamingResponse` is constructed — raised inside the generator it would arrive
after the 200 and the headers were on the wire, i.e. as a broken stream rather
than as a 403.

The pre-existing `test_chat_job_status_and_stream_endpoints` passed with **no
rows seeded at all**, which is precisely how the missing check stayed invisible;
it was extended rather than duplicated.

#### Not done, and not claimed

* **No FE or website surface.** No embeddable JavaScript snippet, no Settings UI
  for issuing/revoking tokens, no `<script>` tag to give a customer. FE Gap 325.
* **No rate limit on the widget chat route itself.** A tenant's own published
  token can be used by their visitors as fast as they like, bounded only by the
  agent's own latency. The sandbox chat meter fires on this route too but a
  non-sandbox tenant is unmetered here, exactly as they are on the dashboard.
  Flagged rather than built: adding a per-token rate limit is real scope and was
  not among the 12 approved constraints.
* **No CSP / `frame-ancestors` guidance** shipped to tenants.
* No deployed run; local Postgres only. No real browser has loaded a widget.

### Phases 1+ — designed, not built

Recorded so the shape above is legible; each is a separate gap and none of it exists.

* **Gap 336 — `TenantWorkflowConfig`.** The user-facing policy object
  (`full_automation` / `strict_review`) that *sets* `Tenant.api_key_scope`, plus its
  read/write endpoints. Phase 0 stores the enforcement primitive; Gap 336 is how a tenant
  chooses it without an Admin editing a column.
* ~~**Gap 338 — output destination: Google Drive write-back** of processed
  results.~~ **Built 2026-08-30** — see its section above. (Gap 339, the email
  summary, was built the same day.) Task 25.3 is complete.
* ~~**Gap 340 — sandbox `inv_test_` keys.** Blocked on a founder decision about tenant
  isolation (does a sandbox key hit a separate tenant, or the real one with a flag?).~~
  **Unblocked and built 2026-08-30** — the founder chose the *separate real tenant*
  option, plus claimability. See its section above.
* ~~**Gaps 341 / 342** — remaining Phase 1+ workflow surface.~~ **Both built** — Gap 342
  on 2026-08-30 (provisioning completion), Gap 341 the same day (the widget token). With
  Gap 340 that completes every backend task in this feature.
* **FE Gap 323 / FE Gap 325** — the Settings UI for all of the above; still the only
  outstanding half.

---

## File Coordinates

### Exists today, modified by Phase 0

* `models.py` → `Tenant` — **added** `api_key_scope: str` (default `"readonly"`, max_length 20).
  No other model changed. `RoleMapper`, `User` and `AuditLog` class definitions are untouched.
* `dependencies.py` → `TenantContext` — **added** `auth_method: str = "clerk"` and
  `key_scope: str | None = None`.
* `dependencies.py` → `resolve_api_key_context()` — hardcoded `role = "Viewer"` replaced with
  scope-derived permissions; sets `auth_method`/`key_scope`; resolves `db_user_id` via the
  service user at `actions` scope.
* `dependencies.py` → `get_api_key_context()` — body's header extraction moved into the new
  shared `_extract_api_key()`; **behaviour unchanged**.
* `routers/invoices.py` → `upload_invoices()`, `list_invoices()`, `get_invoice()`,
  `get_invoice_status()`, `get_invoice_pdf()` — dependency swapped.
* `routers/chat.py` → `list_sessions()`, `create_session()`, `rename_session()`,
  `delete_session()`, `get_session_messages()`, `post_chat_message()`,
  `get_chat_job_status()`, `stream_chat_job()` — dependency swapped.
* `routers/audit.py` → router-level `dependencies=[...]` (line ~33).
* `routers/outbound_audit.py` → router-level `dependencies=[...]` (line ~29).
* `routers/outbound_invoices.py` → `confirm_send_outbound_invoice()`,
  `mark_outbound_invoice_paid()` — gate added where there was none.
* `routers/admin.py` → `list_tenant_users()` — excludes the synthetic service user.
* `tests/test_api_keys.py` → `test_key_auth_runs_as_viewer_with_no_permissions` renamed and
  rewritten as scope assertions; new scope tests added.
* `docs/feature_16_settings.md` → one additive sentence pointing here. Gap 184's spec body is
  **not** rewritten (CONVENTIONS.md hard rule 4).

### Exists today, modified by Gap 337 (role vocabulary)

* `models.py` → `RoleMapper` — **added** `NO_ROLE = "Restricted"` and
  `USER_FACING_ROLES = ("Admin", "Auditor", "Trainer")`; `ROLE_ALIAS_MAP` and
  `ROLE_PERMISSION_DEFAULTS` re-pointed off `"Viewer"`; `normalize_role()` and
  `resolve_permissions()` fall back to `NO_ROLE`. `User`'s comment updated; no column changed.
* `dependencies.py` → `reconcile_role_with_org()`, `get_tenant_context_allow_unpaid()` (mock-token
  role and the two live-JWT clamps), `resolve_api_key_context()`, `resolve_api_key_service_user()`.
* `routers/admin.py` → `set_user_permissions()` (pre-provisioned row), `remove_tenant_user()`
  (detach demotion). Imports `RoleMapper`.
* `agents/support_agent.py` → the `user_management` knowledge-base entry — live customer-facing copy.
* `routers/outbound_invoices.py` → one comment.
* `tests/test_rbac.py` (+4 new Gap 337 cases), `tests/test_api_keys.py`, `tests/test_auth.py`,
  `tests/test_audit.py`, `tests/test_billing.py`, `tests/setup_test_tenants.py`.
* `alembic/versions/e9f0a1b2c3d4_retire_viewer_role.py` — revision `e9f0a1b2c3d4`,
  down_revision `d8e9f0a1b2c3` (the single head, from a real `alembic heads` run). Data-only.
* `docs/feature_1.1_rbac.md` → one additive note at the top. Its body is **not** rewritten
  (CONVENTIONS.md hard rule 4).

### New — built by Phase 0

* `dependencies.py` → `KEY_SCOPE_READONLY`, `KEY_SCOPE_ACTIONS`, `KEY_SCOPE_VALUES`,
  `API_KEY_SERVICE_USER_EMAIL_DOMAIN`
* `dependencies.py` → `_extract_api_key(authorization, x_api_key) -> str | None`
* `dependencies.py` → `api_key_service_clerk_id(tenant_id) -> str`
* `dependencies.py` → `resolve_api_key_service_user(tenant, db_session) -> UUID`
* `dependencies.py` → `permissions_for_key_scope(scope) -> tuple[bool, bool, bool]`
* `dependencies.py` → `get_tenant_or_api_key_context(...) -> TenantContext`
* `dependencies.py` → `require_key_scope(scope)`, and `require_actions_scope`
* `dependencies.py` → `require_permission_or_api_key(permission)`, and
  `require_can_load_or_api_key`
* `alembic/versions/d8e9f0a1b2c3_add_tenant_api_key_scope.py` — revision `d8e9f0a1b2c3`,
  down_revision `a7c3d5e91f04` (the single head, from a real `alembic heads` run)

### New — built by Gap 336

* `models.py` → `TenantWorkflowConfig` (table `tenant_workflow_configs`)
* `routers/settings.py` → `AUDIT_POLICY_FULL_AUTOMATION`, `AUDIT_POLICY_STRICT_REVIEW`,
  `AUDIT_POLICY_TO_KEY_SCOPE`, `KEY_SCOPE_TO_AUDIT_POLICY`, `WORKFLOW_INPUT_CHANNELS`,
  `WORKFLOW_OUTPUT_DESTINATIONS_AVAILABLE`, `WORKFLOW_OUTPUT_DESTINATIONS_UNBUILT`,
  `WORKFLOW_CHAT_ACCESS`
* `routers/settings.py` → `WorkflowConfig` / `WorkflowConfigUpdate` (schemas),
  `_require_admin_for_workflow()`, `_validate_input_channels()`, `_validate_destinations()`,
  `_workflow_response()`, `get_workflow_settings()` (`GET /api/v1/settings/workflow`),
  `update_workflow_settings()` (`PUT /api/v1/settings/workflow`)
* `alembic/versions/f0a1b2c3d4e5_add_tenant_workflow_configs.py` — revision `f0a1b2c3d4e5`,
  down_revision `e9f0a1b2c3d4` (the single head, from a real `alembic heads` run)
* `tests/test_workflow_config.py` — 23 cases

**Not built, contrary to the original sketch:** `routers/workflows.py`. See Gap 336's
"Deviations" note above — the endpoints live in `routers/settings.py`.

### Exists today, modified by Gap 342 (provisioning completion)

* `routers/auth.py` → `TenantProvisionResponse` — **added** `api_key: str | None = None`.
* `routers/auth.py` → `provision_tenant()` — calls the two new helpers on the
  create-a-new-tenant branch only, after the admin-user block; docstring item 7 added.
  The `clerk_org_id` early return and the domain-adoption branch are **unchanged**.
* `tests/test_auth.py` → 6 new cases, plus
  `test_provision_concurrent_same_org_id_creates_one_tenant_on_postgres` **extended**
  (not duplicated) with the one-key / one-sender assertions.
* `docs/feature_16_settings.md` — not touched; Gap 184's API-key body is unchanged
  (CONVENTIONS.md hard rule 4). Issuance, hashing and rotation are all still Feature 16's.

### New — built by Gap 342

* `routers/auth.py` → `_mint_provisioning_api_key(db_session, tenant) -> str | None`
* `routers/auth.py` → `_seed_admin_email_sender(db_session, tenant, admin_email) -> bool`

**No new model, no new column, no migration.** Every column and table involved
(`Tenant.api_key_*`, `tenant_email_senders`) already existed — the defect was that
provisioning never wrote them.

### Exists today, modified by Gap 339 (email summary output destination)

* `services/outbound_email.py` → `send_email()` — the hardcoded
  `"type": "application/pdf"` replaced with a per-attachment type; **added**
  `attachment_mime_type: str = DEFAULT_ATTACHMENT_MIME_TYPE` and
  `attachments: Sequence[EmailAttachment] | None`. Existing single-attachment callers
  are byte-for-byte unaffected.
* `routers/audit.py` → `resolve_audit_invoice()` — one new block after
  `db_session.commit()`, gated on `target_status == "PAID"`; response gains
  `"email_summary"`. Nothing else in the handler changed.
* `routers/settings.py` → `WORKFLOW_OUTPUT_DESTINATIONS_AVAILABLE` gains `email_summary`;
  `WORKFLOW_OUTPUT_DESTINATIONS_UNBUILT` drops it (only `drive_archive` remains);
  `_validate_destinations()` **signature changed** to
  `(values, db_session, tenant_id)` and gained the registered-sender check;
  `update_workflow_settings()` passes the two new arguments. **Added**
  `EMAIL_SUMMARY_SENDER_SET`.
* `models.py` → `TenantWorkflowConfig` — docstring and the `output_destinations`
  comment corrected; **no column, no schema change, no migration.**
* `tests/test_workflow_config.py` — the `email_summary` half of
  `test_unbuilt_output_destinations_are_rejected` removed (it is built now) and replaced
  with `test_email_summary_is_no_longer_rejected` +
  `test_email_summary_requires_a_registered_sender`;
  `test_rejected_request_does_not_touch_api_key_scope` re-pointed at `drive_archive`;
  new `_seed_sender()` helper.
* `tests/test_audit.py` → `test_resolve_invoice_paid` — the exact-response assertion
  gains `"email_summary": None`.

### New — built by Gap 339

* `services/invoice_export.py` — `CSV_COLUMNS`, `build_invoice_summary(invoice) -> dict`,
  `build_invoice_csv(invoice) -> str`, `build_invoice_json(invoice) -> str`,
  `export_filenames(invoice) -> tuple[str, str]`, plus private `_iso` / `_line_items` /
  `_taxes`.
* `services/workflow_outputs.py` — `OUTPUT_DESTINATION_EMAIL_SUMMARY`, `CSV_MIME_TYPE`,
  `JSON_MIME_TYPE`, `tenant_output_destinations()`, `email_summary_enabled()`,
  `email_summary_recipients()`, `_summary_body()`, `deliver_email_summary()`. This is
  where Gap 338's `drive_archive` belongs when it is built.
* `services/outbound_email.py` → `EmailAttachment` (NamedTuple),
  `DEFAULT_ATTACHMENT_MIME_TYPE`.
* `tests/test_workflow_email_summary.py` — 23 cases, including one real-Postgres
  checkpoint driving **both** credential paths.

**No new model, no new column, no migration.** Gap 336's `output_destinations` column
already existed — the defect was that nothing read it.

### Exists today, modified by Gap 338 (Google Drive write-back)

* `routers/connectors.py` → `get_auth_url()` — the requested Google scope widened from the
  literal `drive.readonly` to the new `GOOGLE_DRIVE_OAUTH_SCOPE`
  (`drive.readonly drive.file`), in **both** the real-credentials branch and the mock
  consent URL. Nothing else in this router changed; the callback, listing, import and
  disconnect paths are untouched.
* `utils/connector_oauth.py` → **added** `GOOGLE_TOKENINFO_URL`,
  `GOOGLE_DRIVE_READONLY_SCOPE`, `GOOGLE_DRIVE_FILE_SCOPE`, `GOOGLE_DRIVE_FULL_SCOPE`,
  `GOOGLE_DRIVE_OAUTH_SCOPE`, `GOOGLE_DRIVE_WRITE_SCOPES`, `google_granted_scopes()`,
  `token_has_drive_write_scope()`. `get_valid_access_token()` and `has_real_credentials()`
  are **unchanged** and reused as-is.
* `utils/connector_files.py` → **added** `GOOGLE_DRIVE_UPLOAD_API`,
  `GOOGLE_DRIVE_FOLDER_MIME_TYPE`, `upload_google_drive_file()`,
  `find_or_create_google_drive_folder()`. The two existing read functions are unchanged.
* `services/invoice_export.py` → `export_filenames()` refactored onto a shared
  `_filename_stem()`; **added** `export_pdf_filename()`. Output of the existing function is
  byte-identical (a test asserts the sanitisation unchanged). No builder was duplicated.
* `services/workflow_outputs.py` → **added** the whole `drive_archive` half (below). The
  `email_summary` functions are untouched.
* `routers/settings.py` → `WORKFLOW_OUTPUT_DESTINATIONS_AVAILABLE` gains `drive_archive`;
  `WORKFLOW_OUTPUT_DESTINATIONS_UNBUILT` is now **empty** (kept, not deleted — it is the
  mechanism that stops a future destination being accepted-and-ignored);
  `_validate_destinations()` gained the readiness check. Its signature is unchanged from
  Gap 339's `(values, db_session, tenant_id)`.
* `routers/audit.py` → `resolve_audit_invoice()` — `deliver_drive_archive()` called in the
  same `target_status == "PAID"` block as the summary, in its own try/except; response
  gains `"drive_archive"`.
* `tests/test_workflow_config.py` → `test_unbuilt_output_destinations_are_rejected`
  replaced by `test_no_wizard_destination_is_unbuilt_any_more` (the *mechanism* is now
  asserted with an injected fake entry, since the real set is empty), plus
  `test_drive_archive_is_no_longer_rejected`,
  `test_drive_archive_requires_a_connected_drive`,
  `test_drive_archive_requires_a_write_scoped_grant`, and the `_seed_drive_connection()` /
  `_writable_drive()` helpers. `test_rejected_request_does_not_touch_api_key_scope`
  re-pointed at an unknown destination (`drive_archive` is valid now).
* `tests/test_audit.py` → `test_resolve_invoice_paid` — the exact-response assertion gains
  `"drive_archive": None`.
* `infra/THIRD_PARTY_INTEGRATIONS_SETUP.md` → additive "Scope note" under Google Drive
  Setup; step 2 now names both scopes. Nothing existing was rewritten.

### New — built by Gap 338

* `services/workflow_outputs.py` → `OUTPUT_DESTINATION_DRIVE_ARCHIVE`, `PDF_MIME_TYPE`,
  `DRIVE_PROVIDER`, `DRIVE_ARCHIVE_FOLDER_NAME`, the six readiness codes (`DRIVE_OK`,
  `DRIVE_NOT_CONNECTED`, `DRIVE_RECONNECT_REQUIRED`, `DRIVE_TOKEN_UNUSABLE`,
  `DRIVE_SCOPE_UNKNOWN`, `DRIVE_OAUTH_NOT_CONFIGURED`), `RECONNECT_INSTRUCTION`,
  `drive_archive_enabled()`, `tenant_drive_connection()`, `drive_archive_readiness()`,
  `_invoice_source_pdf()`, `deliver_drive_archive()`.
* `tests/test_workflow_drive_archive.py` — 31 cases, including one real-Postgres
  checkpoint driving both credential paths **and** the reconnect-required path.

**No new model, no new column, no migration** — and, deliberately, **no new
`TenantConnection` column to cache the granted scopes**. Persisting the scope was
considered and rejected: it would add a fourth un-applied migration to the Azure-dev
backlog for a value that can go stale the moment a user revokes access on Google's side,
and the token itself is the only honest source. The cost is one tokeninfo call per
selection and per archive.

### Exists today, modified by Gap 340 (sandbox `inv_test_` keys)

* `services/api_keys.py` → **added** `SANDBOX_KEY_PREFIX` (`inv_test_`),
  `generate_sandbox_key()`, `looks_like_sandbox_key()`; `looks_like_api_key()` widened to
  accept `inv_test_` as well (a sandbox key *is* an API key — same verifier, same columns);
  `key_prefix()` made prefix-aware, with the `inv_live_` output byte-identical (a test pins
  it). `hash_api_key` / `verify_api_key` / `generate_salt` / `masked_display` unchanged.
* `dependencies.py` → `resolve_api_key_context()` — **added** the sandbox block: TTL check
  (401 on an expired key, on every request) and the `readonly` re-pin. Nothing else in the
  function changed.
* `routers/auth.py` → `_tenant_adoption_blockers()` — **added** the `SandboxTenant` blocker;
  `provision_tenant()`'s docstring gains item 9. Gap 344's key-material check is untouched
  (CONVENTIONS.md hard rule 4).
* `routers/settings.py` → `update_workflow_settings()` — **added** the 403 refusing
  `full_automation` for an unclaimed sandbox tenant. Nothing else in the handler changed.
* `routers/chat.py` → `post_chat_message()` — one call to `charge_sandbox_chat_or_402()`
  before the turn runs.
* `routers/support.py` → `_ContactRateLimiter.__init__()` gains
  `redis_key_prefix=_REDIS_KEY_PREFIX` (the existing literal, so the contact form's stored
  keyspace is unchanged); `_keys()` takes `email: str | None`; `check()`'s `email` defaults
  to `None`; two `_REDIS_KEY_PREFIX` reads become `self._redis_key_prefix`. **No behavioural
  change to the contact form**, asserted by two tests.
* `config.py` → **added** `SANDBOX_KEYS_ENABLED` (default **False**),
  `SANDBOX_KEY_TTL_HOURS`, `SANDBOX_MAX_UNCLAIMED_TENANTS`, `SANDBOX_ISSUE_RATE_LIMIT`,
  `SANDBOX_ISSUE_RATE_WINDOW_SECONDS`, `SANDBOX_CHAT_MESSAGE_LIMIT`,
  `SANDBOX_INVOICE_LIMIT`.
* `main.py` → mounts `sandbox.router` under `/api/v1`.
* `tests/test_chat_queue.py` → `test_chat_job_status_and_stream_endpoints` **extended**
  (not duplicated) to seed a genuinely owned job.

### New — built by Gap 340

* `models.py` → `SandboxTenant` (table `sandbox_tenants`)
* `services/sandbox.py` → `SANDBOX_KEY_SCOPE`, `SANDBOX_TENANT_NAME`, `sandbox_domain()`,
  `is_sandbox_tenant()`, `unclaimed_sandbox_count()`, `sandbox_is_expired()`,
  `issue_sandbox_tenant()`, `charge_sandbox_chat_message()`, `SandboxClaimError`,
  `claim_sandbox_tenant()`, `expired_unclaimed_sandboxes()`
  — plus, added by **Gap 352**, `locked_sandbox_select()` (the `SELECT … FOR UPDATE`
  statement builder, exposed for the same reason
  `services/billing_quota.py::locked_tenant_select()` is)
* `routers/sandbox.py` → `SandboxKeyResponse`, `SandboxStatusResponse`,
  `SandboxClaimRequest`, `SandboxClaimResponse`, `_require_sandbox_enabled()`,
  `issue_sandbox_key()` (`POST /api/v1/sandbox/keys`), `get_sandbox_status()`
  (`GET /api/v1/sandbox/keys/me`), `claim_sandbox()` (`POST /api/v1/sandbox/claim`)
* `routers/chat.py` → `charge_sandbox_chat_or_402()`
* `scripts/sweep_sandbox_tenants.py` → `_purge_sandbox()`, `main()`
* `alembic/versions/b1c2d3e4f5a6_add_sandbox_tenants_and_widget_tokens.py` — revision
  `b1c2d3e4f5a6`, down_revision `f0a1b2c3d4e5` (the single head, from a real
  `alembic heads` run)
* `tests/test_sandbox_keys.py` — 50 cases, including two real-Postgres ones
  (**52 as of Gap 352**: `TestChatMetering::test_charge_uses_for_update` and
  `test_concurrent_chat_charges_cannot_exceed_the_allowance_on_postgres`, making
  three real-Postgres cases)

### Exists today, modified by Gap 341 (widget chat token)

* `services/api_keys.py` → **added** `WIDGET_TOKEN_PREFIX` (`inv_widget_`),
  `PLATFORM_CREDENTIAL_PREFIXES`, `generate_widget_token()`, `looks_like_widget_token()`,
  `looks_like_platform_credential()`.
* `dependencies.py` → **added** `WidgetContext`; `resolve_api_key_context()` refuses a
  widget token with a message naming the one route it is good for;
  `_extract_api_key()`'s Bearer test moved from `looks_like_api_key()` to
  `looks_like_platform_credential()`.
* `routers/chat.py` → the synchronous branch of `post_chat_message()` **extracted verbatim**
  into `run_sync_chat_turn()`; `_require_owned_chat_job()` added and wired into
  `get_chat_job_status()` and `stream_chat_job()` (review item 12).
* `routers/settings.py` → **added** `WidgetTokenSummary`, `WidgetTokenCreateResponse`,
  `WidgetTokenCreateRequest`, `_widget_token_summary()`, `list_widget_tokens()`,
  `create_widget_token()`, `delete_widget_token()`; module docstring extended.
* `main.py` → mounts `widget.router` under `/api/v1` and adds `WidgetCORSMiddleware`
  **after** the global `CORSMiddleware` (so it is the outer of the two).
  `ALLOWED_ORIGINS` and the global middleware's own configuration are **unchanged** — a
  test asserts that.

### New — built by Gap 341

* `models.py` → `WidgetToken` (table `widget_tokens`)
* `services/widget_tokens.py` → `MAX_TOKENS_PER_TENANT`, `normalize_origin()`,
  `origin_is_allowed()`, `issue_widget_token()`, `active_widget_tokens()`,
  `revoke_widget_token()`, `resolve_widget_token()`
* `routers/widget.py` → `WIDGET_PATH_PREFIX`, `WidgetCORSMiddleware`,
  `get_widget_context()`, `WidgetMessageRequest`, `WidgetMessageResponse`,
  `post_widget_chat_message()` (`POST /api/v1/widget/chat/message`)
* `tests/test_widget_token.py` — 50 cases, including one real-Postgres one
* `tests/test_chat_queue.py` → `_seed_owned_job()` plus 5 new job-isolation cases
  (one real-Postgres)

Migration `b1c2d3e4f5a6` creates **both** new tables — see its module docstring for why the
two gaps share one revision.

### Still NOT built (design intent only)

* The FE/website surface for everything above: the marketing site's "try it" button, the
  claim step in signup, the Settings UI for widget tokens, and the embeddable widget
  `<script>` itself — **FE Gap 325 / Website**. Every backend piece of Feature 25 exists;
  none of it has a user interface.
* An ACA Job scheduling `scripts/sweep_sandbox_tenants.py`. The script follows the billing
  sweep's pattern but `infra/` was not touched.

---

## Tasks

- [x] **Task 25.1 (Gap 335): dual-credential auth dependency + two-tier API key action scope.**
  `Tenant.api_key_scope` + migration `d8e9f0a1b2c3`; `TenantContext.auth_method`/`key_scope`;
  `get_tenant_or_api_key_context()`; scope-derived permissions replacing the hardcoded Viewer
  role; `require_key_scope()` / `require_permission_or_api_key()`; the synthetic per-tenant
  service user for `AuditLog.actor_user_id`; 5 routers rewired; the unguarded
  confirm-send / mark-paid routes gated. Verified — see Verification Plan.
  **Amended 2026-08-30 (Gap 354) — a test casualty of this rewire, not a feature defect.**
  Repointing the chat-session routes from `Depends(get_tenant_context)` to
  `Depends(get_tenant_or_api_key_context)` silently disarmed
  `tests/test_rag.py::test_session_lifecycle_and_tenant_isolation`, which simulated a foreign
  tenant by overriding `get_tenant_context`. FastAPI only substitutes overrides for
  dependencies declared via `Depends(...)`, and the dual dependency calls `get_tenant_context`
  as a plain function on its Clerk branch — so the override became a no-op, the request ran as
  the default `MOCK_TENANT_ID`, and the isolation branch was never reached. **The isolation
  check itself was never touched**: `routers/chat.py:314` (and its siblings at 240/277/368)
  still carry `if chat_session.tenant_id != tenant_context.tenant_id: raise 403`. The test now
  overrides `get_tenant_or_api_key_context` and additionally asserts the override was actually
  invoked, so a future rewire fails with a message naming the cause instead of an opaque
  `assert 200 == 403`. Proven able to fail, not merely observed passing — see Verification
  Plan §22. `test_rag.py` was not in this task's own narrow verification file list, which is
  why the full-suite track-boundary checkpoint is what caught it.
- [x] **Task 25.1b (Gap 337): retire "Viewer" from the role vocabulary.** User-facing roles are
  Admin / Auditor / Trainer; the zero-permission fallback moves to the never-assignable
  `RoleMapper.NO_ROLE` ("Restricted") so it cannot inherit a real role's permissions. 10 fallback
  sites rewired, live support-chatbot copy corrected, data migration `e9f0a1b2c3d4`. Verified —
  see Verification Plan.
- [x] **Task 25.2 (Gap 336): `TenantWorkflowConfig` + policy read/write endpoints.** The model +
  migration `f0a1b2c3d4e5`; `GET`/`PUT /api/v1/settings/workflow`, Admin-gated on both verbs;
  `audit_policy` writing through to `Tenant.api_key_scope` in one commit and being derived back
  from it on read; 422 rejection (not silent acceptance) of the two unbuilt output destinations.
  Built in `routers/settings.py` rather than a new `routers/workflows.py` — see Deviations.
  Verified — see Verification Plan.
- [x] **Task 25.3 (Gaps 338/339): output destinations.** Both halves built 2026-08-30.
  Kept split below because they are two gaps with two records.
  - [x] **Gap 339 — email summary (built 2026-08-30).** `services/invoice_export.py`
    (CSV + JSON builders) and `services/workflow_outputs.py`
    (`deliver_email_summary()`), fired from a single point inside
    `routers/audit.py::resolve_audit_invoice()` after the commit, on `PAID` only — so
    the human web-UI approve and the Gap 335 `actions`-key approve trigger it
    identically by construction, not by two synchronised call sites. Recipients are the
    tenant's pre-registered `TenantEmailSender` rows, never a free-text address.
    `send_email()`'s hardcoded `application/pdf` attachment type parameterized.
    `email_summary` moved out of the 422'd destination set in `routers/settings.py`,
    with a new "at least one registered sender" check taking its place. No schema
    change. Verified — see Verification Plan §10.
  - [x] **Gap 338 — Google Drive write-back (built 2026-08-30).**
    `deliver_drive_archive()` in the same `services/workflow_outputs.py`, fired
    from the same single point in `resolve_audit_invoice()` on `PAID`, writing
    the *same* CSV/JSON `services/invoice_export.py` builds plus the source PDF
    into the tenant's Drive. `upload_google_drive_file()` /
    `find_or_create_google_drive_folder()` added to `utils/connector_files.py`.
    The real work was the **OAuth migration**: the authorize URL now asks for
    `drive.readonly drive.file` (not the bare `drive` scope), and because Google
    never widens an existing grant, `drive_archive_readiness()` detects a
    pre-2026-08-30 read-only token via the tokeninfo endpoint and surfaces
    `reconnect_required` — lazily, at selection and at write, so no connected
    tenant is forced through a re-auth. `drive_archive` moved out of the 422'd
    destination set, leaving that set empty. No schema change. Verified — see
    Verification Plan §12.
- [x] **Task 25.4 (Gap 340): sandbox `inv_test_` keys (built 2026-08-30).** The founder
  decision this was blocked on is made: a sandbox key resolves to a **fresh, real Tenant
  row** (not a shared demo tenant with a flag), issued to an **anonymous visitor with no
  login**, and **claimable** by a later real signup. `services/sandbox.py` +
  `routers/sandbox.py` + `scripts/sweep_sandbox_tenants.py` + `models.py::SandboxTenant` +
  migration `b1c2d3e4f5a6`. Built against a pre-written security review's seven sandbox
  constraints, all of them in this change rather than deferred: a synthetic
  `sandbox-<id>.invalid` domain plus a named adoption blocker (so no real signup can ever
  collide with one); an explicit single-winner claim transaction under
  `pg_advisory_xact_lock` that **replaces the `inv_test_` key in the same commit** as
  attaching the Clerk org; no `User` and no `TenantEmailSender` row (both have globally
  unique email columns); `readonly` pinned in three places; per-IP rate limiting through
  the *reused* `_ContactRateLimiter` plus a fail-closed global cap; a TTL enforced at
  **every authentication** and a reaper that actually deletes; and a chat message counter,
  because `services/billing_quota.py` meters ingestion only and a sandbox key was otherwise
  an unmetered path to Azure OpenAI spend. Off by default (`SANDBOX_KEYS_ENABLED=False`).
  Verified — see Verification Plan §14/§15.
  **Amended 2026-08-30 (Gap 352):** constraint 7's counter shipped without a row lock and
  therefore did not bound anything under concurrency — 24 concurrent charges against a
  limit of 5 all passed. `charge_sandbox_chat_message()` now locks the `SandboxTenant` row
  with `services/billing_quota.py`'s existing `SELECT … FOR UPDATE` idiom and re-checks the
  limit under that lock. Reproduced pre-fix and re-verified post-fix on real Postgres —
  see Verification Plan §20.
  **Amended again 2026-08-30 (Gap 353):** the lock bounded the allowance correctly, but the
  `used` value returned to the caller was read by a post-commit `db_session.refresh()` —
  i.e. *after* `commit()` released the lock — so two concurrent callers could be handed the
  same position (`[1, 2, 3, 5, 5]`) while a position in between was reported to nobody. A
  reporting defect, not a security one; the bound was never breached. The value to report is
  now captured under the lock, between the increment and the commit, and the post-commit
  `refresh()` is gone. Before/after on the same Postgres database: pre-fix reporting 13/20
  passing, fixed 25/25 — see Verification Plan §22.
- [x] **Task 25.5 (Gaps 342/341): remaining Phase 1+ workflow surface.** Both halves built
  2026-08-30. Kept split below because they are two gaps with two records.
  - [x] **Gap 342 — provisioning completion (built 2026-08-30).**
    `_mint_provisioning_api_key()` + `_seed_admin_email_sender()` in `routers/auth.py`,
    plus `TenantProvisionResponse.api_key`. A newly provisioned tenant now holds a
    `readonly`-scoped `inv_live_` key and one authorized inbound email sender, so the
    `api` and `email` channels the wizard offers work on day one. Both additions are
    confined to the new-tenant branch and individually guarded against re-running,
    because a second key mint *revokes* the first. No schema change, no migration.
    Verified — see Verification Plan §8.
  - [x] **Gap 341 — widget token (built 2026-08-30).** `chat_access = "widget"` now
    has a runtime. `models.py::WidgetToken` (its own table — **not** a third
    credential in `Tenant`'s one-key-per-tenant columns), `dependencies.py::
    WidgetContext` (its own type with no role, no scope and none of the three
    permission booleans, so the codebase's permission gates structurally cannot
    be satisfied by it), `services/widget_tokens.py`, and `routers/widget.py`
    with **one** route — a test walks every route in the app and asserts the
    dependency is mounted exactly once. `looks_like_platform_credential()` makes
    both header spellings behave identically instead of one falling through to
    the Clerk verifier. CORS is a **path-scoped middleware that emits no
    `Access-Control-Allow-Credentials`** — the global `ALLOWED_ORIGINS` was
    deliberately not widened, since that middleware runs with credentials on and
    widening it would expose every session-authenticated route. Origin pinning is
    present, and is documented **and tested** as bypassable outside a browser.
    Admin-only issue/list/revoke on `routers/settings.py`. Verified — see
    Verification Plan §16/§17.
  - [x] **Review item 12 — chat job tenant isolation (fixed 2026-08-30, inside Gap
    341).** `routers/chat.py::get_chat_job_status()` and `stream_chat_job()` took a
    `tenant_context` dependency and never read it, so any authenticated caller who
    learned a `job_id` could read another tenant's chat answer. Dormant
    (`ENABLE_ASYNC_CHAT_QUEUE` defaults off) and fixed anyway, **before** a
    credential that lives in public page source was allowed near chat.
    `_require_owned_chat_job()` resolves ownership through the database, not the
    Redis blob (which loses `tenant_id` once a job completes); unknown ids are 404
    so the responses are not a probe. Verified — see Verification Plan §17.

---

## Dependencies outside this feature

* **Feature 1.1 — Granular RBAC** ([feature_1.1_rbac.md](feature_1.1_rbac.md)) **owns the role
  model this touches.** `RoleMapper`, the four roles, `resolve_permissions()`, and the
  `require_permission()` factory are all Feature 1.1's. Phase 0 adds a *parallel* derivation
  for key-auth requests and deliberately changes none of them. Role-model changes are **Gap
  337**, queued after this lands specifically so two agents do not edit `models.py::RoleMapper`
  at once. **Gap 337 has since landed** (2026-08-29, see its section above): the role vocabulary
  is now Admin / Auditor / Trainer plus the internal `RoleMapper.NO_ROLE` fallback, and Feature
  1.1's doc carries an additive note pointing here. The access *model* — the three permission
  booleans, `resolve_permissions()`, `require_permission()` — is unchanged.
* **Feature 16 — Settings** ([feature_16_settings.md](feature_16_settings.md)) **owns the Gap
  184 API-key foundation this extends** — `Tenant.api_key_*` columns, `services/api_keys.py`,
  the rotate/status/verify endpoints, and the original `resolve_api_key_context()`. Feature 25
  adds a scope column and widens what the key may reach; it does not change issuance, hashing,
  rotation, or the one-key-per-tenant model. A one-sentence additive pointer has been added to
  that document; its Gap 184 body is unchanged.
* **Feature 7 / 7.1 — Audit resolution** own the routers whose gating changed.
* **Feature 13 — Tenant Autopilot** — no code dependency, **naming collision only**. See
  Overview.

---

## Verification Plan

Filled in after the runs below actually happened. Nothing here is claimed from intent.

### 1. Automated tests — 172 passed, exit 0

```
.venv/Scripts/python.exe -m pytest tests/test_api_keys.py tests/test_rbac.py \
  tests/test_audit.py tests/test_outbound_audit.py tests/test_outbound_ingestion.py \
  tests/test_staff_notify.py tests/test_settings.py tests/test_auth.py \
  tests/test_queries.py tests/test_chat_queue.py -q
-> 172 passed in 372.86s
```

Narrow-test-per-task, per this repo's standing convention — the full backend suite is a
track-boundary checkpoint, not this task. The ten files are the ones touching the changed
dependencies, the five rewired routers, and the Admin user list. No failures, no regressions,
no tests skipped around.

**One real failure was caught and resolved during this run, worth recording.**
`tests/test_auth.py::test_provision_concurrent_same_org_id_creates_one_tenant_on_postgres` is
one of the few tests in this suite that runs against **real local Postgres** rather than
SQLite, and it failed with `psycopg2.errors.UndefinedColumn: column tenant.api_key_scope does
not exist` — the model had the column and the database did not. That is the migration doing
its job as a tripwire. Resolved by actually running `alembic upgrade head`; the test passes
now. Recorded because a SQLite-only run would never have surfaced it.

### 2. Migration applied against real Postgres

`alembic current` reported `a7c3d5e91f04` (exactly the previous head) before, and
`alembic upgrade head` ran `a7c3d5e91f04 -> d8e9f0a1b2c3` cleanly. Verified by querying
`information_schema` afterwards, not by assuming:

```
api_key_scope | character varying | is_nullable: NO | default: 'readonly'::character varying
existing tenant rows: 10
scope distribution after migration: [('readonly', 10)]
```

So the column really is NOT NULL with a server default, and **all 10 pre-existing tenants
landed on `readonly`** — the fail-closed property is confirmed observationally, not argued.

### 3. The AuditLog actor FK, against real Postgres

**This is the part SQLite structurally cannot prove** — SQLite does not enforce foreign keys
by default, so the entire reason the service user exists is invisible there. Run as a
throwaway script against the same local Postgres (created its own tenant, asserted, then
deleted everything it made):

```
1. tenant created; api_key_scope defaulted to 'readonly'
2. readonly key -> auth_method='api_key' scope='readonly'
   perms=(train=False, audit=False, load=False) db_user_id=None
   -> no service user row created for a readonly key. OK
3. NULL actor_user_id rejected by Postgres as expected: NotNullViolation
4. actions key -> scope='actions' role='Viewer'
   perms=(train=False, audit=True, load=True) db_user_id=b15a7214-...
   service user: email='api-key-service+c159e420-...@service.invoice-llm.internal' role='Viewer'
5. AuditLog row committed against the real non-null FK: id=577e4d0d-...
6. service user is created once and reused. OK
7. cleanup done -- tenant, service user and audit rows removed.
```

Step 3 is the bug this fixes, reproduced against the real constraint (`NotNullViolation`);
step 5 is the fix working against that same constraint. Both directions, on Postgres.

### 4. Gap 337 (role vocabulary) — automated tests, 168 passed

```
.venv/Scripts/python.exe -m pytest tests/test_rbac.py tests/test_api_keys.py -q
-> 74 passed in 288.39s

.venv/Scripts/python.exe -m pytest tests/test_auth.py tests/test_audit.py \
  tests/test_billing.py tests/test_settings.py -q
-> 94 passed in 26.70s
```

Six files, chosen by grepping `Viewer` across `tests/` rather than from a list. Four new cases
in `test_rbac.py` assert the properties this gap turns on:

* `USER_FACING_ROLES == ("Admin", "Auditor", "Trainer")`, with `NO_ROLE` and `"Viewer"` both
  outside it and `"Viewer"` gone from `ROLE_PERMISSION_DEFAULTS` — a fourth user-facing role
  cannot be reintroduced silently.
* Parametrised over `None`, `""`, `"viewer"`, `"Viewer"`, `"member"`, `"org:member"` and an
  arbitrary unmapped IDP string: every one normalises to something that is **not Trainer** and
  resolves to `(False, False, False)`. This is the actual safety property of the gap.
* A legacy `'Viewer'` row (an un-migrated database) still resolves to zero permissions rather
  than raising `KeyError`.

### 5. Gap 337 migration against real Postgres, both directions

Local Postgres held only `Admin` rows, so a legacy `'Viewer'` row was seeded first — otherwise
the migration would have "passed" by doing nothing, which proves nothing:

```
role distribution BEFORE:                  [('Admin', 2)]
role distribution AFTER seeding probe row: [('Admin', 2), ('Viewer', 1)]
alembic upgrade head -> d8e9f0a1b2c3 -> e9f0a1b2c3d4
role distribution AFTER upgrade:           [('Admin', 2), ('Restricted', 1)]
probe row role: 'Restricted'   alembic_version: e9f0a1b2c3d4
alembic downgrade -1 -> after downgrade, probe row role: 'Viewer'
alembic upgrade head (re-applied); probe row deleted, distribution back to [('Admin', 2)]
```

Up and down both exercised against the real database, and the probe row cleaned up afterwards.

### 6. Gap 336 (workflow config) — automated tests, 23 passed

```
.venv/Scripts/python.exe -m pytest tests/test_workflow_config.py -q
-> 23 passed in 12.37s

# regression across everything the same change touched:
.venv/Scripts/python.exe -m pytest tests/test_workflow_config.py tests/test_settings.py \
  tests/test_api_keys.py tests/test_auth.py -q
-> 108 passed in 14.14s
```

What the new file asserts: fail-closed defaults for a tenant that has never run the wizard **and
that a GET writes no row**; a full round-trip; one row per tenant across repeated PUTs;
`completed_at` set once and never moved by a later edit; omitted fields keeping their values;
de-duplication; the write-through in both directions (`full_automation` → `actions`,
`strict_review` → `readonly`) checked on the `Tenant` row itself, not just the response; the
derive-from-tenant behaviour when `api_key_scope` is changed underneath a stale config row; 422
for each unbuilt destination with the gap named in the message; **a rejected request leaving
`api_key_scope` and the table untouched**; 422 for unknown values in each field; all four input
channels accepted; Admin-only on both verbs; and another tenant's row never being returned.

### 7. Gap 336 against real Postgres — types, constraints and the write-through

Migration applied for real (`e9f0a1b2c3d4 -> f0a1b2c3d4e5`), then a throwaway script created its
own tenant, asserted, and deleted everything it made:

```
1. input_channels     | jsonb                       | nullable
   output_destinations| jsonb                       | nullable
   audit_policy       | character varying | NOT NULL| default 'strict_review'
   chat_access        | character varying | NOT NULL| default 'dashboard'
2. FOREIGN KEY (tenant_id) REFERENCES tenant(id)
   UNIQUE (tenant_id)  -- uq_workflow_config_tenant
4. row round-tripped as real JSONB: (['email','api'], 'array', 'full_automation')
5. second row for the same tenant -> UniqueViolation (one row per tenant, enforced)
6. orphan row for a nonexistent tenant -> ForeignKeyViolation
7. (tenant.api_key_scope, config.audit_policy) = ('actions', 'full_automation')
8. cleanup done -- probe tenant and config row removed; 0 rows left
```

Steps 5 and 6 are the part **SQLite cannot prove** — it does not enforce foreign keys by default,
and the one-row-per-tenant guarantee the endpoint's logic assumes is a database constraint, not
an application convention. `alembic downgrade -1` also ran cleanly (`to_regclass` → `None`, i.e.
the table really was dropped) and `upgrade head` recreated it, so the migration is reversible in
practice, not just on paper.

### 8. Gap 342 (provisioning completion) — automated tests, 53 passed

```
.venv/Scripts/python.exe -m pytest tests/test_auth.py -q
-> 53 passed in 19.00s          (47 pre-existing + 6 new)

# the key-column and sender-row contracts this touches, re-run:
.venv/Scripts/python.exe -m pytest tests/test_settings.py tests/test_api_keys.py \
  tests/test_email_ingestion.py -q
-> 59 passed in 14.18s
```

What the 6 new cases assert:

* A key is minted carrying the `inv_live_` prefix; `api_key_hash` **and**
  `api_key_salt` are both different from the raw value; `verify_api_key()` accepts
  the returned raw key against the stored pair; only the non-secret display prefix
  is persisted; `api_key_last_used_at` is NULL.
* `api_key_scope == "readonly"` — the fail-closed default, asserted rather than
  assumed.
* The sender row is seeded from the token's email, lowercased
  (`Real.Admin@Acme.com` → `real.admin@acme.com`), `email_set="inbound"`.
* A placeholder-email caller seeds **no** sender at all and still gets a key —
  the two additions are independent.
* The legacy domain-adoption branch gets neither, and returns `api_key=None`.
* **The double-provision case, which is the point of the gap:** a second call for
  the same org returns `api_key=None`, leaves `api_key_hash`/`api_key_salt`/
  `api_key_prefix` byte-identical, still verifies against the *first* raw key, and
  creates no second sender row.

### 9. Gap 342 against real Postgres — the idempotency mechanism, under real concurrency

The mechanism relied on is **`pg_advisory_xact_lock(hashtext(:org_key))`** plus the
`clerk_org_id` early return and that column's UNIQUE constraint — all three
pre-existing, all three verified against the running code before anything was added.
The advisory lock is a Postgres primitive and a no-op elsewhere, which is exactly
why this cannot be proven on SQLite.

`tests/test_auth.py::test_provision_concurrent_same_org_id_creates_one_tenant_on_postgres`
— the existing test that drives two threads through `provision_tenant()` off a
`threading.Barrier` — was **extended rather than duplicated**, and confirmed running
against `postgresql://…@localhost:5433/invoice_db` (not skipped):

```
.venv/Scripts/python.exe -m pytest \
  tests/test_auth.py::test_provision_concurrent_same_org_id_creates_one_tenant_on_postgres -v
-> PASSED in 13.43s
```

It now additionally asserts that across two genuinely concurrent provisions:
exactly **one** raw key is returned; the surviving stored credential verifies
against *that* key (i.e. the losing thread did not overwrite the winner's — the
silent-revocation failure mode); `api_key_scope` is `readonly`; and exactly **one**
`TenantEmailSender` row exists, with the expected address. The probe tenant, user
and sender rows are deleted in the test's own `finally`.

**Not done, not claimed for Gap 342:** no schema change and therefore no migration;
**no backfill** — tenants provisioned before 2026-08-30 still have no key and no
sender row, and whether to backfill them is a separate decision not taken here; no
deployed run; and no FE surface for the returned key, so today's website caller
discards it (FE Gap 323/325).

### 10. Gap 339 (email summary) — automated tests, 280 passed

```
.venv/Scripts/python.exe -m pytest tests/test_workflow_email_summary.py -q
-> 23 passed in 39.25s        (0 skipped -- the Postgres case really ran)

# everything the change touched, plus the notifier/scope neighbours:
.venv/Scripts/python.exe -m pytest tests/test_workflow_config.py tests/test_audit.py \
  tests/test_staff_notify.py tests/test_settings.py tests/test_api_keys.py \
  tests/test_email_ingestion.py tests/test_support.py -q
-> 171 passed in 34.77s

.venv/Scripts/python.exe -m pytest tests/test_outbound_audit.py \
  tests/test_outbound_ingestion.py tests/test_autopilot.py tests/test_rbac.py -q
-> 86 passed in 286.55s
```

Narrow-test-per-task per this repo's standing convention. `test_staff_notify.py`,
`test_support.py` and `test_autopilot.py` are in the list because they are the three
existing `send_email()` callers and the MIME change touched that function's signature.

What the 23 new cases assert, grouped by the property each protects:

* **The builders** — header row equals `CSV_COLUMNS`; one CSV row per line item with the
  invoice-level fields repeated; an itemless invoice still producing one data row; no `\r`
  in the output; the JSON carrying nested `line_items`/`taxes`; a non-dict line item kept
  rather than dropped; `file_path` / `coordinates` / `field_confidence` /
  `source_document_json` / `sa_alerts` **absent** from the summary; filename sanitisation
  of `../../etc/pa ss wd` and the invoice-id fallback.
* **The MIME fix** — the real `send_email()` run with `httpx` stubbed, asserting the
  posted SendGrid body carries `["text/csv", "application/json"]` and *not*
  `application/pdf`; and, separately, that the legacy single-attachment form still
  produces exactly `application/pdf`.
* **Recipient resolution** — resolved from `TenantEmailSender` for this tenant and this
  invoice's direction only, with another tenant's address and the `outbound` set both
  present in the fixture and both correctly excluded.
* **Fail-safe behaviour** — destination not selected → `None` and no send; no config row
  at all → `None` and no send; destination selected with an empty allowlist → logged,
  `{"sent": False}`, no send; missing `SENDGRID_API_KEY` → soft skip; a raising
  `send_email` → reported, never propagated; and end-to-end through the endpoint, a
  failing send still leaves the invoice **PAID** and the response **200**.
* **The trigger** — `PAID` sends; `REJECTED` does not; an alert-dismissal with no
  `status` does not.
* **Both credential paths, compared directly** —
  `test_api_key_approve_sends_the_identical_summary` drives one approval through mock
  Clerk auth and another through an `actions`-scoped `X-API-Key`, against the same tenant
  and the same registered sender, then asserts the two `send_email` calls have the *same*
  recipients, the *same* subject and the *same* two `(filename, mime_type)` attachments.
  It asserts equality between the paths rather than checking each in isolation.

`tests/test_workflow_config.py` also gained the two cases that close this gap's
contract with Gap 336: `email_summary` is **no longer 422'd** (it round-trips and is
stored), and it **is** 422'd when the tenant has no registered sender — with
`api_key_scope` and the config table both confirmed untouched by that rejection.

### 11. Gap 339 against real Postgres — the trigger and the recipient query

`test_workflow_email_summary.py::test_approve_sends_email_summary_on_postgres`, run
against `postgresql://…@localhost:5433/invoice_db` (**passed, not skipped** — confirmed
by running it alone and by the zero-skip count above):

```
.venv/Scripts/python.exe -m pytest \
  tests/test_workflow_email_summary.py::test_approve_sends_email_summary_on_postgres -v
-> PASSED in 19.36s
```

Why this one needs Postgres specifically: `output_destinations` is **JSONB** on Postgres
and plain JSON on SQLite, and it is the column that decides whether anything sends at
all. The test asserts the JSONB round-trip (`["email_summary"]` back out of the real
column) before it asserts anything about mail. It then creates a real
`TenantEmailSender` row and two real invoices, and drives the actual HTTP endpoint
twice — once with mock Clerk auth, once with `X-API-Key` on an `actions`-scoped key —
asserting that:

* both requests return 200 and both report `email_summary.sent == True`;
* the recipient list on **both** sends is the address that was inserted into Postgres,
  proving the allowlist query ran against the real database and not a fixture;
* the attachments carry `text/csv` + `application/json` and the CSV bytes contain the
  seeded line item;
* both invoices are `PAID` in Postgres afterwards.

The API-key path also exercises Gap 335's non-null `AuditLog.actor_user_id` FK for real —
the synthetic service user is created and written against the live constraint, which is
the part SQLite structurally cannot prove.

The test captures the pre-existing state of everything it borrows (the tenant's
`api_key_scope` and key columns, any existing workflow-config row, whether the service
user already existed) and restores or deletes all of it in a `finally`, including the
`AuditLog` rows the two resolves wrote.

**Fake SendGrid, deliberately.** `services.workflow_outputs.send_email` is patched in
every case. There is no SendGrid account in this environment, and the assertion that
matters is the exact call that *would* have been made — recipients, subject, attachment
names and content types. No real mail was sent and none is claimed.

### 12. Gap 338 (Drive write-back) — automated tests, 147 passed

```
.venv/Scripts/python.exe -m pytest tests/test_workflow_drive_archive.py -q -p no:randomly
-> 31 passed in 66.88s        (0 skipped -- the Postgres case really ran)

.venv/Scripts/python.exe -m pytest tests/test_workflow_config.py tests/test_audit.py -q -p no:randomly
-> 39 passed in 35.76s

.venv/Scripts/python.exe -m pytest tests/test_connectors.py \
  tests/test_workflow_email_summary.py tests/test_settings.py -q -p no:randomly
-> 46 passed in 55.27s

.venv/Scripts/python.exe -m pytest tests/test_autopilot.py tests/test_outbound_audit.py -q -p no:randomly
-> 31 passed in 21.03s
```

Narrow-test-per-task per this repo's standing convention. `test_connectors.py` and
`test_autopilot.py` are in the list because they are the existing consumers of the two
modules whose public surface changed (`utils/connector_oauth.py`,
`utils/connector_files.py`) and of the OAuth scope string;
`test_workflow_email_summary.py` because Gap 338 refactored `export_filenames()` onto a
shared stem and added a second caller to `services/workflow_outputs.py`.

What the 31 new cases assert, grouped by the property each protects:

* **The scope probe** — Google's space-separated `scope` string parsed into a set;
  `drive.readonly` alone → **False**, `drive.file` → True, the bare `drive` superset →
  True; a tokeninfo **400** (invalid/revoked token) → a definite `False`, not unknown; an
  unreachable endpoint and a non-JSON/5xx body → `None`, and `None` never collapsing into
  `False`. Plus the authorize URL actually carrying both scopes and *not* the bare `drive`
  one — asserted through the real `GET /connectors/auth-url/google_drive` endpoint.
* **Readiness, the re-consent detector** — the six states, each on real rows: no
  connection, a `status != "active"` row, a deployment with no Google OAuth app, a
  read-only grant (`reconnect_required`, message naming the fix), an undetermined probe
  (`scope_unknown`, **ready True** — the fail-open), a write-scoped grant (`ok`), and an
  expired token with no refresh token (`token_unusable`).
* **Delivery** — the three files uploaded in order with the right names, content types and
  bytes, all into the app-owned folder; the CSV/JSON coming from the *same* builders the
  email summary uses; a missing source PDF still archiving the other two with
  `source_pdf_included: false`; an invoice with no `file_path` not attempting a download;
  a **403 from Drive translated into `reconnect_required`** (the fail-loud half of the
  fail-open probe); a raising upload reported, never propagated; and no upload at all when
  the destination is not selected or the tenant never ran the wizard.
* **The trigger** — `PAID` archives, `REJECTED` does not; a failing upload still leaves the
  invoice PAID and the response 200; a reconnect-required tenant gets a 200, a PAID
  invoice, and `drive_archive.code == "reconnect_required"` in the body.
* **Both credential paths, compared directly** —
  `test_api_key_approve_archives_identically` drives one approval through mock Clerk auth
  and another through an `actions`-scoped `X-API-Key` against the same tenant, then asserts
  the two sets of three uploads have the same folder, filenames, content types and content
  (modulo `invoice_id`, which legitimately differs between two invoice rows). Equality
  between the paths, not each in isolation — Gap 335's dual-credential convergence
  re-confirmed after this change rather than assumed.

`tests/test_workflow_config.py` also gained the three cases that close this gap's contract
with Gap 336: `drive_archive` is **no longer 422'd**; it **is** 422'd when Drive is not
connected; and it **is** 422'd when the connection exists but the grant is read-only, with
`api_key_scope` and the config table both confirmed untouched by that rejection.

### 13. Gap 338 against real Postgres — the trigger, the JSONB read and the reconnect path

`test_workflow_drive_archive.py::test_approve_archives_to_drive_on_postgres`, run against
`postgresql://…@localhost:5433/invoice_db` (**passed, not skipped** — confirmed by running
it alone and by the zero-skip count above):

```
.venv/Scripts/python.exe -m pytest \
  tests/test_workflow_drive_archive.py::test_approve_archives_to_drive_on_postgres -v
-> PASSED in 33.91s
```

Why Postgres specifically: `output_destinations` is **JSONB** there and plain JSON on
SQLite, and it is the column that decides whether anything is archived at all. The test
asserts the JSONB round-trip (`["drive_archive"]` back out of the real column) before it
asserts anything about Drive. It then creates a real `TenantConnection` row (real Fernet
-encrypted tokens, read back through the real `get_valid_access_token()`) and three real
invoices, and drives the actual HTTP endpoint three times:

* once with mock Clerk auth and once with `X-API-Key` on an `actions`-scoped key — both
  200, both `uploaded: true`, six uploads total with identical filenames and content types
  across the two paths;
* once more with the scope probe answering "read-only" — 200, invoice still **PAID**,
  `drive_archive.code == "reconnect_required"`, and **zero** upload calls. That is the
  migration case proven end to end against the real database, not just at unit level.

The API-key path also exercises Gap 335's non-null `AuditLog.actor_user_id` FK for real,
which is the part SQLite structurally cannot prove. The test captures the pre-existing
state of everything it borrows (the tenant's `api_key_scope` and key columns, any existing
workflow-config row, any existing Drive connection, whether the service user already
existed) and restores or deletes all of it in a `finally`, including the `AuditLog` rows
the three resolves wrote.

**Fake Drive, deliberately.** `has_real_credentials`, `token_has_drive_write_scope`,
`find_or_create_google_drive_folder`, `upload_google_drive_file` and
`download_pdf_from_storage` are patched in `services.workflow_outputs` in every case.
There is no Google account in this environment; the assertion that matters is the exact
call that *would* have been made — folder, filenames, content types and bytes. No file was
written to any real Drive and none is claimed.

### 14. Gap 340 (sandbox keys) — automated tests, 50 passed

```
.venv/Scripts/python.exe -m pytest tests/test_sandbox_keys.py -q -p no:randomly
-> 50 passed in 13.00s        (0 skipped -- both Postgres cases really ran)
```

Grouped by the review constraint each protects:

* **Credential format / prefix dispatch** — `inv_test_` carried; recognised by
  `looks_like_api_key()` (it *is* an API key, same verifier, same columns) and by
  `looks_like_sandbox_key()`; and the `inv_live_` stored prefix width is still
  exactly 15 characters, pinned because `Tenant.api_key_prefix` is an indexed
  lookup column and moving its width would 401 every live key.
* **Constraint 1** — the domain is per-tenant, `.invalid`, and distinct;
  `_tenant_adoption_blockers()` reports both `"a sandbox workspace"` and
  `"a live API key"` (asserted as a list, so removing either still leaves the
  tenant unadoptable); and no address a real signup could register equals it.
* **Constraint 3** — no `User` row, no `TenantEmailSender` row, and a readonly
  sandbox key authenticating with `db_user_id=None` while creating nothing. That
  last one is the review's stated precondition, **confirmed rather than assumed**.
* **Constraint 4** — `readonly` at creation; still `readonly` at auth **after the
  column is edited to `actions` directly**; a 403 naming "read-only" on
  `PUT /audit/resolve/{id}`; `full_automation` refused at `PUT /settings/workflow`
  with `api_key_scope` confirmed untouched afterwards; and `strict_review` still
  accepted (the guard is on widening only).
* **Constraint 5** — 429 with `Retry-After` past the per-IP window; the sandbox
  and contact-form limiters are the **same class** with **different Redis
  keyspaces**; the contact form's own default prefix is unchanged; the
  no-email case keys on IP alone; 503 "temporarily unavailable" past the global
  cap with nothing created; claimed rows not counted; expired-but-unreaped rows
  **still** counted; and the whole router 404s with the flag off.
* **Constraint 6** — TTL read from settings; an expired key raising 401 from
  `resolve_api_key_context()` **and** 401ing over real HTTP; a claimed sandbox
  never expiring; the reaper's work list containing only expired-and-unclaimed;
  and `_purge_sandbox()` actually removing the tenant, the sandbox row, the chat
  session and its messages.
* **Constraint 7** — an ordinary tenant not metered; the counter incrementing to
  the limit then refusing; a **402 through the real chat endpoint** when the
  allowance is spent; a claimed sandbox no longer metered; and the sandbox
  invoice allowance coming from its own setting rather than
  `DEFAULT_FREE_INVOICES_LIMIT`.
* **Constraint 2 (sequential half)** — the key swap (old key stops verifying, new
  one starts, old key 401s through the real auth path); the row marked and kept;
  the domain staying synthetic; no `actions` scope granted on claim; a second
  claim refused; an expired sandbox unclaimable; the endpoint's org/user binding
  to the token; and an `inv_live_` key rejected at the claim endpoint.

### 15. Gap 340 against real Postgres — the claim race and the adoption exclusion

Both cases **passed, not skipped**, confirmed by running them alone:

```
.venv/Scripts/python.exe -m pytest \
  tests/test_sandbox_keys.py::test_concurrent_claims_have_exactly_one_winner_on_postgres \
  tests/test_sandbox_keys.py::test_sandbox_tenant_is_never_adopted_by_a_real_signup_on_postgres -v
-> 2 passed in 9.53s
```

**The claim race (constraint 2).** Two threads off a `threading.Barrier` — the
same harness `tests/test_auth.py::test_provision_concurrent_same_org_id_creates_
one_tenant_on_postgres` uses — race to claim one sandbox for two different Clerk
orgs. This is the assertion SQLite structurally cannot make: the guarantee rests
on `pg_advisory_xact_lock(hashtext(...))`, a Postgres primitive that is a silent
no-op elsewhere. What it asserts: exactly **one** winner; the loser gets
`already_claimed`; the tenant carries the **winner's** `clerk_org_id`; the
surviving stored credential verifies against the **winner's** live key (i.e. the
loser did not overwrite it — the silent-revocation failure mode); and the
original `inv_test_` key verifies against **nothing**.

**The adoption exclusion (constraint 1).** Rather than asserting the blocker list
in isolation, this drives the real `provision_tenant()` with the
attacker-optimal input: a signup whose verified email domain **is** the sandbox
tenant's own synthetic domain, which is the single input that could make the
domain lookup find it. Postgres specifically because that path takes two
`pg_advisory_xact_lock`s and because `Tenant.domain`'s UNIQUE constraint is what
forces the fallback branch. Asserted: the signup gets its **own** fresh tenant;
the sandbox tenant's `clerk_org_id`, `name` and `domain` are all untouched; and
the sandbox key still resolves to the sandbox tenant, not to the new company's
workspace.

Both tests clean up every row they create in a `finally`.

**One real bug this run caught.** The first Postgres execution failed with
`ForeignKeyViolation` — `issue_sandbox_tenant()` flushed the `SandboxTenant`
before the `Tenant`, and because the function swallows `IntegrityError` it
returned a silent `None` indistinguishable from hitting the global cap. Fixed
with an explicit `db_session.flush()`. **SQLite does not enforce foreign keys by
default, so all 48 non-Postgres cases passed while this was broken.** Recorded
because it is exactly the fidelity gap CONVENTIONS.md hard rule 2 exists for.

### 16. Gap 341 (widget token) — automated tests, 50 passed

```
.venv/Scripts/python.exe -m pytest tests/test_widget_token.py -q -p no:randomly
-> 50 passed in 12.23s         (0 skipped -- the Postgres case really ran)
```

* **Constraint 9** — all three prefixes recognised as ours and a Clerk-shaped JWT
  not; `inv_widget_` **not** matching `looks_like_api_key()`; the prefix slice;
  and — parametrised over both headers — `Authorization: Bearer` and `X-API-Key`
  producing the **same** 401 message, which names
  `/api/v1/widget/chat/message`. Plus `resolve_api_key_context()` refusing a
  widget token directly.
* **Constraint 8** — `WidgetContext.model_fields` asserted to be exactly
  `{tenant_id, widget_token_id, auth_method, origin}` and to contain none of
  `role` / `key_scope` / `can_*` / `db_user_id` / `billing_plan`, so adding one
  later fails here rather than silently widening a published credential;
  `WidgetContext` not being a `TenantContext`; a walk over **every route in the
  running app** asserting `get_widget_context` is mounted on exactly one path;
  and four real routes (chat sessions, chat job status, invoices, api-key verify)
  each 401ing a widget token.
* **Storage** — the raw token never persisted and unrecoverable from what is;
  two live tokens for one tenant; issuing a widget token **not touching**
  `Tenant.api_key_*`; revocation immediate; the revoked row kept, not deleted;
  another tenant's token not revocable; wrong/unknown/empty all the same answer;
  `last_used_at` stamped.
* **Constraint 11** — origin normalisation parametrised over eight inputs;
  an empty allowlist disabling the layer (rather than denying everything);
  case-insensitive matching with path discarded; a 403 for an unregistered
  origin over real HTTP; and
  `test_origin_pinning_is_bypassable_outside_a_browser`, which **passes by
  demonstrating the bypass** — a forged `Origin` header is accepted. That is the
  honest state of the control, written as an executable assertion so no later
  reader treats the allowlist as a hard boundary.
* **Constraint 10** — the global `ALLOWED_ORIGINS` asserted to still contain only
  first-party values; `WidgetCORSMiddleware` asserted to be the **outermost**
  middleware; a preflight from an unknown origin answered 200 with the origin
  reflected and `Vary: Origin`; **no `Access-Control-Allow-Credentials` on either
  the preflight or a real response**; non-widget paths untouched; and exactly one
  `Access-Control-Allow-Origin` value even for an origin that is also in the
  global list.
* **The route** — 401 with no token; 401 with an `inv_live_` key; a first message
  creating a session labelled "Website widget chat"; a follow-up reusing it;
  another tenant's `session_id` a 403 and an unknown one a 404; and
  `run_sync_chat_turn` asserted to be the function actually called, i.e. the
  widget is not a second answer path.
* **Admin management** — issue/list/revoke round trip with the raw token in the
  create response and **absent** from the listing; 403 on all three verbs for a
  non-Admin; 422 for an unusable origin; the per-tenant cap; 404 for an unknown id.

**One real bug this file caught, and it is the important one.**
`test_widget_response_never_allows_credentials` asserts the absence of
`Access-Control-Allow-Credentials` on a **real response**, not on the
middleware's own output — and it failed. Starlette's `CORSMiddleware` applies its
`simple_headers` (which include that header when `allow_credentials=True`) to
every response to a request carrying an `Origin`, **unconditionally**, before it
decides whether the origin is allowed; only `Access-Control-Allow-Origin` is
conditional. So the inner global middleware was stamping the credentials header
onto widget responses, and combined with the reflected origin a browser would
have been told it may send cookies cross-origin to a customer's site.
`WidgetCORSMiddleware._apply()` now **deletes** the header rather than merely not
setting it. A version of this test that checked only the middleware's own headers
would have passed.

A second, smaller one: `normalize_origin("not a url at all")` returned
`https://not a url at all`, because `urlsplit()` happily reports that as a
netloc — so an Admin could have stored an allowed origin no browser can ever
send, pinning the token to nothing and discovering it as 403s from their own
visitors. A strict host pattern plus an http/https-only scheme check fixes it.

### 17. Gap 341 against real Postgres — tenant isolation, and the chat-job fix

```
.venv/Scripts/python.exe -m pytest \
  tests/test_widget_token.py::test_widget_token_is_tenant_isolated_on_postgres -v
-> 1 passed in 10.08s

.venv/Scripts/python.exe -m pytest \
  tests/test_chat_queue.py::test_job_isolation_on_postgres -v
-> 1 passed in 9.92s

.venv/Scripts/python.exe -m pytest tests/test_chat_queue.py -q -p no:randomly
-> 13 passed in 13.79s
```

**Widget token isolation.** Two real tenants, two real tokens. Why Postgres:
`widget_tokens.token_prefix` is UNIQUE at the schema level (unlike
`tenant.api_key_prefix`, which is only indexed) because it is the sole
cross-tenant lookup key, and `tenant_id` is a real FK — neither is enforced on
SQLite. Asserted: `allowed_origins` round-tripping through real JSONB; each raw
token resolving to **its own** tenant only; each tenant's listing containing only
its own rows; tenant A's revoke not reaching tenant B's token; a duplicate
`token_prefix` raising `IntegrityError`; and an orphan `tenant_id` raising
`IntegrityError`. The last two are the part SQLite structurally cannot prove.

**The chat-job fix (review item 12).** Two real tenants, two real chat sessions,
two real queued messages, and `_require_owned_chat_job()` driven for all four
(caller, job) combinations against real Postgres — each tenant reads its own job,
neither reads the other's (403), and an unknown id is a 404. Postgres because the
ownership answer is a two-hop join across `chat_messages.session_id` →
`chat_sessions.tenant_id`, and this repo does not claim a security fix on a
SQLite-only run.

Four further cases at the HTTP level assert that the status endpoint 403s
another tenant's job **with `get_job_status` never called at all** (so the other
tenant's answer is never even in memory), that the stream endpoint 403s as a
403 rather than as a broken `text/event-stream` and leaks none of the payload,
that unknown ids are 404 on both, and that a caller's own job is still readable.
The pre-existing `test_chat_job_status_and_stream_endpoints` was **extended, not
duplicated** — it previously passed with **no rows seeded at all**, which is
precisely how the missing check stayed invisible.

### 18. Regression across everything the two gaps touched

```
.venv/Scripts/python.exe -m pytest tests/test_api_keys.py tests/test_auth.py \
  tests/test_settings.py tests/test_support.py -q -p no:randomly
-> 168 passed in 20.98s

.venv/Scripts/python.exe -m pytest tests/test_workflow_config.py tests/test_rbac.py \
  tests/test_audit.py -q -p no:randomly
-> 82 passed in 300.91s

.venv/Scripts/python.exe -m pytest tests/test_chat_training.py tests/test_sse.py \
  -q -p no:randomly
-> 38 passed in 21.43s
```

Narrow-test-per-task per this repo's standing convention. The file list is the
one the diff touches: `test_api_keys.py` (the prefix helpers and
`_extract_api_key`), `test_auth.py` (`_tenant_adoption_blockers`),
`test_settings.py` (the workflow guard and the new widget-token endpoints),
`test_support.py` (the rate-limiter change — the one place a regression would be
a live public endpoint), `test_workflow_config.py` (`update_workflow_settings`),
`test_rbac.py` and `test_audit.py` (the scope gates a sandbox key must fail), and
`test_chat_training.py` / `test_sse.py` (the `run_sync_chat_turn` extraction and
the streaming path). **351 pre-existing cases, zero failures, nothing skipped
around.**

### 19. Migration `b1c2d3e4f5a6` against real Postgres, both directions

`alembic heads` reported `f0a1b2c3d4e5` as the single head before (a real run,
not read off the files — Gap 60 is the multi-head incident that check exists
for). Applied, inspected via `information_schema` and `pg_indexes`/`pg_constraint`
rather than assumed, then reversed and re-applied:

```
alembic current                 -> f0a1b2c3d4e5
alembic upgrade head            -> f0a1b2c3d4e5 -> b1c2d3e4f5a6

sandbox_tenants
  chat_messages_used | integer | NOT NULL | default 0
  expires_at         | timestamp | NOT NULL
  claimed_at         | timestamp | NULL          <- the compare-and-set predicate
  CON uq_sandbox_tenant (u), sandbox_tenants_tenant_id_fkey (f)
  IDX idx_sandbox_tenant_tenant_id / _claimed / _expires

widget_tokens
  allowed_origins | jsonb | NULL
  token_prefix    | varchar | NOT NULL
  IDX idx_widget_token_prefix (UNIQUE) / idx_widget_token_tenant
  CON widget_tokens_tenant_id_fkey (f)

alembic downgrade -1            -> to_regclass on both tables: [None, None]
alembic upgrade head            -> re-applied
alembic heads                   -> b1c2d3e4f5a6 (head)     -- still single
```

`claimed_at` really is nullable (so `IS NULL` is a meaningful predicate rather
than a column that can never be null), the FKs and the UNIQUE prefix index really
exist, and the migration is reversible in practice rather than on paper.

**Not done, not claimed for Gaps 340/341:** the Azure-dev migration backlog is
now **four** revisions, not three (`d8e9f0a1b2c3`, `e9f0a1b2c3d4`, `f0a1b2c3d4e5`,
`b1c2d3e4f5a6`) — none of them has been applied there. No deployed run. No real
browser has loaded a widget and no anonymous visitor has been issued a key;
`SANDBOX_KEYS_ENABLED` is False everywhere. No ACA Job schedules the sandbox
reaper. No blob is deleted when a sandbox is reaped. No FE or website surface
exists for any of it.

### 20. Gap 352 — the sandbox chat meter's race, reproduced and then closed

This section exists because "tests pass" would not have been evidence: the
pre-fix code passed all 50 of Gap 340's tests, including the two Postgres ones.
The claim being made is **comparative**, so it was measured both ways on the same
database with the same harness.

**(a) The bug, reproduced against the pre-fix function on real Postgres.** A
throwaway script (scratchpad, not committed, **production code unmodified**) held
a verbatim copy of the old `charge_sandbox_chat_message()` body and drove it with
`SANDBOX_CHAT_MESSAGE_LIMIT = 5` and 24 threads released off a
`threading.Barrier`, each on its **own** `Session` — one transaction per thread,
exactly as one HTTP request is:

```
mode = prefix   limit = 5   concurrency = 24
run 1:  ALLOWED turns : 22   refused : 2    final counter : 5
run 2:  ALLOWED turns : 19   refused : 5    final counter : 4
run 3:  ALLOWED turns : 24   refused : 0    final counter : 4
run 4:  ALLOWED turns : 24   refused : 0    final counter : 3
```

Run 3 and run 4 are the full statement of the defect: **every one of 24 requests
was allowed against an allowance of 5, and the persisted counter finished at 3.**
The counter did not merely lag — it recorded fewer turns than a *single* honest
sequential run would have, because N−1 of the increments were computed from the
same stale read and overwrote each other. The 25-turn production allowance, the
one control between an anonymous `inv_test_` holder and unmetered Azure OpenAI
spend, bounded nothing.

**(b) The same harness against the fixed function, same database, same limit:**

```
mode = fixed    limit = 5   concurrency = 24
run 1:  ALLOWED turns : 5   refused : 19   final counter : 5   OVERSPEND: 0
run 2:  ALLOWED turns : 5   refused : 19   final counter : 5   OVERSPEND: 0
run 3:  ALLOWED turns : 5   refused : 19   final counter : 5   OVERSPEND: 0
run 4:  ALLOWED turns : 5   refused : 19   final counter : 5   OVERSPEND: 0
```

**(c) The committed regression test, and proof it can actually fail.**
`tests/test_sandbox_keys.py::test_concurrent_chat_charges_cannot_exceed_the_allowance_on_postgres`
is the same harness, cleaning up in a `finally`. It asserts four things, not one:
turns granted `== limit`; refusals `== concurrency - limit`; the persisted counter
`== turns granted` (a counter that lags is how the pre-fix version kept answering
past a spent allowance); and that the granted turns reported `used` values
`1..limit` with no duplicates (pre-fix, two callers were both told they were
message 2, and three were all told message 3 — the lost-update signature).

A test that only passes proves nothing about a concurrency fix, so the pre-fix
body was swapped into the test module by a throwaway pytest plugin — again with
**no production file modified** — and the committed test **failed**:

```
pytest -p prefix_plugin tests/test_sandbox_keys.py::test_concurrent_chat_charges_cannot_exceed_the_allowance_on_postgres
-> FAILED
   AssertionError: 23 turns allowed against a limit of 5 -- the meter is not
   bounding under concurrency
   assert 23 == 5
```

and passes against the real one:

```
.venv/Scripts/python.exe -m pytest \
  tests/test_sandbox_keys.py::test_concurrent_chat_charges_cannot_exceed_the_allowance_on_postgres \
  tests/test_sandbox_keys.py::test_concurrent_claims_have_exactly_one_winner_on_postgres \
  tests/test_sandbox_keys.py::TestChatMetering::test_charge_uses_for_update -v
-> 3 passed in 6.82s        (Postgres cases really ran, not skipped)
```

**(d) The file, and its neighbour.**

```
.venv/Scripts/python.exe -m pytest tests/test_sandbox_keys.py -q -p no:randomly
-> 52 passed in 13.69s      (50 pre-existing + 2 new, exit 0, nothing skipped)

.venv/Scripts/python.exe -m pytest tests/test_sandbox_keys.py tests/test_widget_token.py -q -p no:randomly
-> 102 passed in 13.50s     (the widget chat route is the other caller of
                             charge_sandbox_chat_or_402)
```

**(e) SQLite could not have caught this, and that is the point.** SQLAlchemy's
SQLite dialect renders `with_for_update()` as **nothing at all**, so a reverted
fix passes there silently. `TestChatMetering::test_charge_uses_for_update` is the
SQLite-safe half — it asserts the statement carries `FOR UPDATE` structurally, the
same assertion `tests/test_ingestion.py::test_charge_free_quota_uses_for_update`
makes about `locked_tenant_select()` — and the Postgres case is the half that
proves the behaviour. Both, not either.

**Database left clean.** Every run deletes the sandbox row and its tenant in a
`finally`. Checked afterwards: 4 `sandbox_tenants` rows remain, all timestamped
08:58–10:19 (other agents' earlier runs), none from this work; every row this
task created is gone.

**Not done, not claimed for Gap 352.** No schema change and no migration — the
column already existed; the defect was that the read and the write were not one
decision. **No rate limit on chat itself** — this bounds a *sandbox* workspace's
total turns; a signed-up tenant's chat is still unmetered, exactly as Gap 341
recorded. Nothing else in the sandbox/widget system was touched — in particular
`scripts/sweep_sandbox_tenants.py` and `infra/` are untouched (the reaper's
missing ACA Job is separate work). No deployed run; local Postgres only, and
`SANDBOX_KEYS_ENABLED` is still False everywhere.

**What is still NOT claimed.** No deployed-environment run: this is local Postgres, not the
Azure dev database, and no `alembic upgrade head` has been run there. No end-to-end HTTP call
with a real `inv_live_` key against a deployed instance. The FE has no UI for setting
`api_key_scope` yet (that is Gap 336 + FE Gap 323), so today the column is only settable
directly in the database.

**What the automated tests assert:**

* `readonly` (and default, and unset) scope → `can_train`/`can_audit`/`can_load` all False —
  identical to the pre-change Viewer behaviour.
* `actions` scope → `can_audit`/`can_load` True, `can_train` **False**.
* `api_key_scope` defaults to `readonly` on a freshly created tenant (fail-closed).
* An `actions` key still reports `role="Viewer"` — scope never becomes a role, and
  `require_admin` is never satisfied by a key.
* A `readonly` key gets 403 on `PUT /audit/resolve/{id}` with a message naming the scope
  setting; an `actions` key passes the gate.
* Human 403 messages on the audit routers are unchanged ("audit queue"), and
  `test_invoice_upload_requires_can_load` still passes — the human `can_load` gate on upload
  survived the dual-credential swap.
* `confirm-send` and `mark-paid` now 403 for a permissionless Viewer (the pre-existing hole).
* An unauthenticated/garbage credential is still 401 on every rewired route.

**Outstanding, not done and not claimed:**

0. *(added 2026-08-29 with Gaps 337/336)* The Azure-dev migration item below is now **three**
   revisions behind, not one: `d8e9f0a1b2c3`, `e9f0a1b2c3d4`, `f0a1b2c3d4e5`. Also: nothing
   reads `TenantWorkflowConfig.output_destinations` yet, and `chat_access = "widget"` is
   storable with no runtime effect (Gap 341). The FE wizard is FE Gap 323 and does not exist.
   The one caveat that *is* closed: `api_key_scope` is no longer settable only in the database —
   `PUT /api/v1/settings/workflow` is the supported route.
0b. *(added 2026-08-30 with Gap 339)* Two corrections to item 0 and one new caveat.
   `TenantWorkflowConfig.output_destinations` **is** read now —
   `services/workflow_outputs.py` reads it on every approval. The Azure-dev migration
   count is unchanged at three revisions, because Gap 339 adds no migration. New: the
   **FE wizard still labels `email_summary` "Not available yet — BE Gap 339"**
   (`invoice-fe/app/settings/workflows/page.tsx`), so a tenant cannot select from the UI
   a destination the API now accepts. That is FE work, deliberately out of this gap's
   scope. Also unclaimed: no outbound (AR) approval triggers a summary, and no real
   SendGrid delivery has been performed.
0c. *(added 2026-08-30 with Gap 338)* Every destination the wizard offers now
   delivers something, so `WORKFLOW_OUTPUT_DESTINATIONS_UNBUILT` is empty. The
   Azure-dev migration count is still three — Gap 338 adds none. New caveats:
   the **FE wizard still labels `drive_archive` "Not available yet — BE Gap
   338"** and has no reconnect-required banner on the Connectors page (FE work);
   **every tenant that connected Google Drive before 2026-08-30 must reconnect**
   before this destination can work, by design and not by omission — the old
   grant is `drive.readonly` and Google will not widen it; and no real Google
   Drive upload has been performed (the Drive client is mocked in tests).
1. `alembic upgrade head` against the **Azure dev** database (only local Postgres has been
   migrated).
2. A real HTTP call with an `inv_live_` key against a **deployed** instance, end to end.
3. Rotating a key does not reset `api_key_scope` — reasoned (rotation writes only
   hash/salt/prefix) but not explicitly tested.
4. Load/security review of the widened surface: five routers are now reachable by a
   non-browser credential that previously reached exactly one endpoint.

### 21. functional-tester final gate pass, 2026-08-30 -- combined regression + new Playwright coverage

Everything below is additive (CONVENTIONS.md hard rule 4) -- nothing above this
section was edited. Full scope, commands and root-cause detail: `docs/test_coverage_map.md`
(two new rows filed this pass) and `docs/test_evidence/feature25_final_gate_2026-08-30/`.

**Combined 17-file targeted run** (`test_outbound_invoices.py` from the original
task brief does not exist in this repo -- substituted `test_outbound_ingestion.py` /
`test_outbound_audit.py` / `test_staff_notify.py`, the files that actually cover
the outbound confirm-send/mark-paid gate and the MIME-type change):

```
pytest tests/test_api_keys.py tests/test_rbac.py tests/test_audit.py \
  tests/test_outbound_ingestion.py tests/test_outbound_audit.py \
  tests/test_workflow_config.py tests/test_workflow_email_summary.py \
  tests/test_workflow_drive_archive.py tests/test_auth.py \
  tests/test_billing_free_quota.py tests/test_autopilot.py tests/test_connectors.py \
  tests/test_sandbox_keys.py tests/test_widget_token.py tests/test_chat_queue.py \
  tests/test_settings.py tests/test_staff_notify.py -q -p no:randomly
-> 454 passed, 1 failed in 31.30s
```

**Full suite** (bare `pytest tests/` errors at collection -- a pre-existing
basename collision between two gitignored manual-live-test scratch scripts,
`tests/us/run_chat_live_test.py` and `tests/realworld_tenant/run_chat_live_test.py`,
same workaround this repo used on 2026-08-28):

```
pytest tests/ --ignore=tests/us --ignore=tests/realworld_tenant -q -p no:randomly
-> 1734 passed, 10 failed, 1 skipped, 5 deselected in 63.65s
```

**Every failure root-caused via `git stash` on the whole uncommitted
`apps/invoice-be` diff** (verified clean before, restored byte-for-byte after
via `git status`, in both directions):

* **9 of the 10 full-suite failures are pre-existing and unrelated** -- 8x
  `tests/test_ops_recommendation.py::test_each_band_is_still_the_live_panels_band[...]`
  and 1x `tests/test_rag.py::test_process_crash_during_agent_leaves_no_orphan_user_message`
  (`background_tasks` TypeError), both reproduced identically on clean HEAD and
  matching this same failure signature already recorded in `docs/test_coverage_map.md`'s
  2026-08-28 entry, from before this feature existed.

* **1 genuine regression, in the combined run's own failure too:
  `tests/test_sandbox_keys.py::test_concurrent_chat_charges_cannot_exceed_the_allowance_on_postgres`
  is a real, reproducible ~20% flake.** Re-run 5x in isolation: 1/5 failed. This is
  Gap 352's own regression test for its concurrency fix -- and the fix has a
  residual bug. `services/sandbox.py::charge_sandbox_chat_message()` calls
  `db_session.refresh(sandbox)` *after* `db_session.commit()`, i.e. after the
  `SELECT ... FOR UPDATE` lock has already been released. Two racing writers can
  each have their `refresh()` read back a counter value the *other* writer already
  advanced to, so both report the same `used` position and the position one lower
  is never reported by anyone (`assert [1, 2, 3, 5, 5] == [1, 2, 3, 4, 5]` was the
  observed diff). **The actual security bound is unaffected** -- total turns
  granted and the persisted counter were correct in every run observed, including
  the failing one; only the per-caller `used` sequence number in the API response
  is unreliable under concurrency. **Not fixed** -- reported here for senior-dev,
  per this pass's own boundary against touching application code.

* **1 genuine regression, full-suite only:
  `tests/test_rag.py::test_session_lifecycle_and_tenant_isolation` is a real
  regression caused by this feature (BE Gap 335), not a flake.** Passes on clean
  HEAD in isolation; fails on current code in isolation
  (`assert 200 == 403` at `tests/test_rag.py:72`). Root cause: the test does
  `app.dependency_overrides[get_tenant_context] = lambda: TenantContext(tenant_id=foreign_tenant_id, ...)`
  to simulate a cross-tenant GET on a chat session, expecting 403. Gap 335 rewired
  every chat-session route -- including this one -- from
  `Depends(get_tenant_context)` to `Depends(get_tenant_or_api_key_context)`, so the
  test's override no longer targets the dependency the route actually resolves; the
  request proceeds under the real/default identity and the isolation branch is
  never reached, returning 200.
  **Confirmed NOT a live security hole**, by reading the route rather than assuming:
  `routers/chat.py:314`'s `if chat_session.tenant_id != tenant_context.tenant_id:
  raise 403` is present and untouched by Gap 335's diff. Only this test's ability
  to *simulate* a foreign tenant broke -- the isolation check it was written to
  protect is still there and still correct.
  **Why this slipped through Gap 335's own verification**: `test_rag.py` was never
  in Gap 335's modified-file list (File Coordinates above) or in any of its narrow
  verification runs (section 1's file list is `test_api_keys.py`, `test_rbac.py`,
  `test_audit.py`, `test_outbound_audit.py`, `test_outbound_ingestion.py`,
  `test_staff_notify.py`, `test_settings.py`, `test_auth.py`, `test_queries.py`,
  `test_chat_queue.py` -- not `test_rag.py`). This is exactly the gap the
  "narrow test per task, full suite at track-boundary checkpoints" convention
  exists to catch, and this pass is that checkpoint.
  **Not fixed** -- `test_rag.py` is pre-existing, not this pass's own spec; the
  one-line fix (override `get_tenant_or_api_key_context` instead of
  `get_tenant_context`) is reported here for senior-dev's call, not applied.

**Migration/deployment caveat, re-confirmed, not papered over:** local Postgres
is at `alembic heads` = `b1c2d3e4f5a6` (single head, confirmed by a real
`alembic heads`/`alembic current` run, not read off the files). The **Azure dev
database remains unmigrated** -- four revisions behind
(`d8e9f0a1b2c3`, `e9f0a1b2c3d4`, `f0a1b2c3d4e5`, `b1c2d3e4f5a6`), exactly as every
prior section in this Verification Plan already recorded. Nothing in this pass
changes that.

> **Correction, 2026-09-01 (founder-requested live-Azure verification): the
> caveat above is stale.** The Azure dev environment was deployed on
> 2026-08-30 (`ca-invoice-be-dev--0000104`, image `377f12f...`, byte-identical
> to the commit that shipped this feature). That container's own startup log
> (`entrypoint.sh` runs `alembic upgrade head` on boot) shows all four
> migrations above applying cleanly at `13:02:30Z`, immediately followed by
> `Application startup complete` with no traceback. **The Azure dev database
> is fully migrated and this feature is live end-to-end there today** -- a
> real `inv_live_` key against the live environment now works exactly as
> described in this doc. This correction was verified directly (container
> revision + deploy logs), not re-derived from this doc's own prior claim.

> **Follow-on finding, same 2026-09-01 investigation, closed same day as
> FE Gap 358: "live end-to-end" above was true of invoice-be in isolation,
> not of the only path a real external caller has to it.** A direct
> `az containerapp exec` into `ca-invoice-be-dev` proved the key-auth logic
> itself works (`GET /api/v1/settings/security/api-key/verify` -> `200`).
> But the public path -- Front Door -> invoice-website -> invoice-fe ->
> invoice-be, the only route an actual outside integrator has -- 404'd:
> invoice-fe's own Clerk middleware ran `.protect()` on every `/api/*`
> request and redirected it to a `/clerk_<nonce>` handshake path before any
> route handler, key or not, ever ran. So before FE Gap 358, this feature was
> reachable by internal Azure diagnostics only, not by the third-party
> integrations it exists for. FE Gap 358 fixed it: invoice-fe now exempts
> `/api/*` from `.protect()` (verified safe -- every route it proxies to
> enforces its own tenant-auth dependency, so nothing that was actually
> protected became reachable), added the missing `verify` proxy route, and
> stopped silently dropping the `X-API-Key` header. See FE Gap 358 in
> `apps/invoice-fe/docs/fe_features_tracker.md` for the full fix. A live
> redeploy + a real external probe through the public domain is still
> outstanding -- functional-tester's job, sequenced after deploy, not done
> as part of either gap.

**New committed Playwright coverage this pass added (FE and website, not this
app):** see `feature_17_plug_and_play_workflows.md` section 8 and
`feature_7_plug_and_play_workflows.md`'s Verification Plan addendum.

> **Both findings above are now CLOSED — Gap 353 and Gap 354, fixed 2026-08-30.
> See §22 below.** This section is left standing as the record of what the gate
> found and what it deliberately did not fix, per the additive-only rule.

### 22. Gaps 353/354 — closing the two findings the final gate raised

Two narrow fixes, one to production code and one to a test. Scope was deliberately
these two only: the full combined regression had just been run by §21's gate pass,
so re-running it would prove nothing new and would violate this repo's own
"narrow test per task" convention. Evidence files:
`docs/test_evidence/feature25_final_gate_2026-08-30/03_gap353_repeated_run_before_after.txt`
and `.../04_gap354_fail_then_pass.txt`.

#### Gap 353 — the flaky reported `used` count

Changed: `services/sandbox.py::charge_sandbox_chat_message()` only. Capture the
value to report between the increment and the `commit()` (while the `FOR UPDATE`
lock is still held) and return that local; delete the post-commit
`db_session.refresh()`, which was the unlocked read causing the flake.

**A race is not proven fixed by one clean pass, so this is a before/after on the
same machine and the same real Postgres database, one fresh pytest *process* per
run** (`tests/test_sandbox_keys.py::test_concurrent_chat_charges_cannot_exceed_the_allowance_on_postgres`,
`-p no:randomly`, DATABASE_URL = `postgresql://…@localhost:5433/invoice_db`;
the test self-skips when Postgres is unreachable and did not skip):

| | Runs | Passed | Failed | Rate |
|---|---|---|---|---|
| **Before** — fix temporarily reverted in place, pre-fix reporting restored | 20 | 13 | 7 | **35% failure** |
| **After** — fix in place | 25 | **25** | **0** | **0%** |

Every one of the 7 baseline failures is the same signature and only that
signature — `[1, 3, 3, 4, 5]`, `[1, 2, 4, 4, 5]`, `[1, 3, 3, 4, 5]` etc. against
the expected `[1, 2, 3, 4, 5]` — with all three bounding assertions (turns
granted, turns refused, persisted counter) green in all 20. That is the
reporting defect and nothing else, and it matches (slightly exceeds) the ~1-in-5
rate §21 observed, confirming it is the same defect. At a 35% per-run failure
rate, 25 consecutive clean runs by chance is `0.65^25 ≈ 1.4e-5`.

Whole file: `pytest tests/test_sandbox_keys.py` → **52 passed in 9.21s**, exit 0,
nothing skipped, all three real-Postgres cases executed.

**The test needed no strengthening.** Gap 352 already wrote it asserting four
things, and the fourth —
`sorted(r["used"] for r in allowed) == list(range(1, limit + 1))` — is precisely
the uniqueness assertion this defect violates. It was left byte-for-byte alone;
a second spelling of a working assertion is only a second thing to keep in sync.

**Database left clean.** The only rows remaining in `sandboxtenant` afterwards
are 4 created at 08:58–10:19 UTC by earlier sessions; all 45 runs here ran
12:03–12:30 UTC and cleaned up after themselves (the test's cleanup is in a
`finally`, so even the 7 failing runs cleaned up). The pre-existing rows were
deliberately not deleted — they belong to other work.

#### Gap 354 — the disarmed tenant-isolation test

Changed: `tests/test_rag.py` only. No production code.

**First, a correction to §21's own framing.** The test was not "passing without
verifying" — it was **failing**, `assert 200 == 403` at `tests/test_rag.py:72`,
which is what §21's `02_full_suite_run_summary.log` line 28 records and what a
direct re-run reproduces. Same root cause and same fix, but a red test that reads
like a security regression is a different thing to triage than a green test
proving nothing, and the record should say which it was.

**The fix, and why it is not a bare one-line repoint.** The override now targets
`get_tenant_or_api_key_context`, the dependency the route actually declares. No
established convention existed to copy: a grep of `tests/` for
`dependency_overrides[` found **only this test** overriding a tenant dependency at
all (`test_auth.py` overrides `get_authenticated_clerk_identity`,
`test_autopilot.py` overrides `get_session`; every other dual-credential test
authenticates with a real `X-API-Key` header instead), so the local shape was kept
and repointed rather than a new pattern invented. Added alongside: the override is
now a named function that records each invocation, and the test asserts it was
invoked **before** asserting the 403.

**Proven able to fail, three ways, not merely observed passing:**

| Run | Setup | Result |
|---|---|---|
| (a) | Fixed test, isolation intact | **passes** (1 passed in 6.34s) |
| (b) | `routers/chat.py:314`'s ownership check temporarily neutered to `if False:` | **fails `assert 200 == 403`** — and the new `assert override_calls` guard **passed on that same run**, proving the request genuinely executed as a foreign tenant and the isolation branch genuinely let it through |
| (c) | Override temporarily repointed back at `get_tenant_context`, production code correct | **fails on the new guard**, with its message naming the cause — i.e. the guard catches the exact Gap 335 failure mode |

(b) is the one that matters: it is the difference between a test that catches a
broken isolation check and one that merely fails for its own reasons. Both
temporary edits were backed up before and restored after, and the restores were
verified (`grep -c` → 0 for every temporary marker, all four
`chat_session.tenant_id != tenant_context.tenant_id` checks present at lines
240/277/314/368, tests re-run green).

Whole file: `pytest tests/test_rag.py` → **58 passed, 1 failed**. The one failure
is `test_process_crash_during_agent_leaves_no_orphan_user_message`
(`TypeError: post_chat_message() missing 1 required positional argument:
'background_tasks'`), **pre-existing and unrelated** — §21 already root-caused it
via `git stash` as failing identically on clean HEAD. **Deliberately not fixed
here:** it is a real defect but a different one, outside this task's two-fix
scope, and it needs its own Gap entry before anyone touches it (no code change
without a Gap).

**Not done, not claimed for §22.** No schema change, no migration, no router
change, no FE/website change. The Azure-dev migration caveat is unchanged —
still four revisions behind, still nothing deployed. The full suite was not
re-run and no claim is made about it beyond §21's numbers.
