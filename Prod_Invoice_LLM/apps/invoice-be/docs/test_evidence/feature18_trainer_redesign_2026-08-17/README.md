# Feature 18 (BE) / Feature 14 (FE) - Alert-Anchored Trainer & Chat Correction Lane
## Independent functional-tester verification - 2026-08-17

Scope: independently confirm BE Gaps 228-232 and FE Gaps 232-238 hold, per
`.claude/tasklists/functional-tester-trainer-redesign.md`. Everything below was run
against the real local stack (docker compose Postgres/Redis/Chroma/Azurite, real
`uvicorn main:app`, real Azure OpenAI/Doc Intelligence per `.env`) - not mocks, unless
explicitly marked "unit test" (which uses the existing mocked pytest suite).

---

## 1. Full BE regression suite

`uv run pytest tests/ -p no:randomly -q` - real Postgres/Redis, fixed ordering.

**Result: 552 passed, 5 deselected, 0 failed in 197.60s.** Exactly matches the developer
claimed baseline (552/0/5, up from 470 pre-Feature-18). Full output: `01_pytest_full_suite.log`.

## 2. Migration - re-verified independently on a fresh throwaway Postgres DB

Developer verified on `f18_migtest`. I independently re-ran the identical procedure on a
different, freshly created throwaway DB (`f18_migtest_ft`), not reusing the prior DB or claim:

1. `CREATE DATABASE f18_migtest_ft` (docker exec into `invoice-postgres-local`)
2. `alembic upgrade fe6371baa50d` (full pre-Feature-18 chain, 30 revisions, clean)
3. Seeded a real `tenant` + `extraction_templates` row with `rules -> chat_style` set
   (response_length concise, tone formal, custom_instructions "Always cite invoice numbers.")
4. `alembic upgrade head` goes to `f18a0c4b7d21` and applies cleanly
5. Confirmed: `tenant_chat_settings` has exactly the seeded values, copied correctly;
   `extraction_templates.rules -> chat_style` still has the source key (non-destructive,
   as designed); `chat_feedback.reason` / `.note` and `chatmessage.result_invoice_ids`
   columns exist; `tenant_chat_rules` / `tenant_chat_settings` tables exist.
6. `alembic downgrade -1` drops both new tables and both new columns;
   the original `chat_style` data in `extraction_templates` is untouched (confirmed by
   re-querying - value byte-identical to what was seeded).
7. Dropped `f18_migtest_ft`.

Matches the developer claim exactly. Migration file itself:
`alembic/versions/f18a0c4b7d21_feature_18_chat_training_tables.py`.

Operational note, not a code defect: the actual local dev Postgres database
(`invoice_db`, used by the running backend for everything else in this evidence) was
NOT migrated to `f18a0c4b7d21` before this session started (`alembic_version` was still
at `fe6371baa50d`). I ran `alembic upgrade head` against it to proceed with live testing
(confirmed via a subsequent `GET /api/v1/chat/rules` 500ing with UndefinedTable
tenant_chat_rules before the upgrade, and returning an empty list cleanly after). Worth
knowing for whoever next brings this stack up locally.

## 3. Permission boundary (BE Gap 228 router-level gate + FE Gap 232)

Real backend, real mock-auth (ALLOW_MOCK_AUTH=true in local .env, same pattern as
prior evidence e.g. gap143_checkpoint4_retest). Built a real "can_audit but not
can_train" identity by provisioning a test_viewer mock user then setting
users.can_audit = true directly in Postgres (role stays Viewer so can_train stays
false via RoleMapper.resolve_permissions) - this is the FE Auditor-shaped case the
scope called for.

Live results, Authorization Bearer test_viewer against real http://127.0.0.1:8000:

| Endpoint | Expected | Actual |
|---|---|---|
| GET /api/v1/trainer/alert-types | 403 (router-level require_can_train) | 403 |
| GET /api/v1/trainer/vendors | 403 | 403 |
| POST /api/v1/trainer/sessions/from-invoice | 403 | 403 |
| POST /api/v1/chat/rules/commit | 403 (require_can_train) | 403 |
| POST /api/v1/chat/rules/preview | 200 (deliberately open) | 200 |

FE (real Next dev server on 3100, real backend on 8000, DISABLE_CLERK_AUTH=true,
Authorization Bearer test_viewer set on the browser context so backendProxy.ts's
"inbound header always wins" path is exercised - same mechanism the existing e2e suite
relies on):

- /trainer renders "Training Permission Required" and zero instances of
  trainer-entry-panel - confirmed live (throwaway Playwright check, deleted after use;
  screenshot not retained because Playwright clears test-results at the start of the
  next run in the same session). Reproducible via the equivalent stubbed test already in
  e2e/trainer-alert-anchored.spec.ts (FE Gap 232 test), which independently passes.

## 4. Preview-before-commit - exact impact against a real, hand-verified invoice

Real seeded tenant 3511ae3e-27a4-49a5-897d-6a1a3fc3ac91 (InvoiceEQ Test - US),
real invoice 7140ff29-5c6d-42a2-ad89-09e9b40e8c8a (APS-410093, Apex Print Solutions).

Stored data (items JSON): quantity=5000, unit_price=0.08, hand-computed
5000 x 0.08 = 400.00. Stored amount=420.00. Mismatch = 20.00 exactly, matching
the real line_item_calculation_mismatch alert own message text
(does not match calculated amount 400.00).

POST /trainer/sessions/from-invoice creates a real session with that real alert, then
POST .../corrections/tolerance with abs_tol 25 and rel_tol 0.001 (25 greater than 20,
so the alert should disappear on replay), then POST .../preview returns:

invoicesExamined 1, alertsRemoved 1, alertsAdded 0, invoicesAffected 1, kind exact,
summary: "Replayed against 1 stored invoice(s): 1 alert(s) would no longer fire
(across 1 invoice(s))."

Exactly matches hand computation. Committed (POST .../commit with the real preview
token) and confirmed via direct psql query that extraction_templates.rules on the
real DB row now holds the exact structured tolerance rule, byte-for-byte matching what
was staged. This mutation was reverted after the check (template row deleted,
version row deleted) to leave the dev DB as found.

Also tested the not_computable honesty guarantee: the free-text/LLM path
(corrections/missed-alert) is where Gap 235 (below) was found - see that section for
why a preview of a genuinely-LLM-drafted rule could not be completed live in this
environment. The not_computable contract itself (never a fabricated number) is
covered by real unit tests (test_trainer.py) that exercise compute_rule_impact()
directly with a text-kind rule already staged, independent of the drafting step, and
those pass in the full-suite run above.

## 5. Chat-correction lane isolation - direct DB assertion, live

Real POST /chat/rules/preview then POST /chat/rules/commit (category
missing_currency_context) against the real tenant, real DB.

Query 1: SELECT id, category, pattern FROM tenant_chat_rules WHERE tenant_id = the
real tenant id. Result: 1 row, the committed rule.

Query 2: SELECT vendor_name, flow_direction, and two ILIKE checks for the category
name and the rendered rule text against rules::text, FROM extraction_templates WHERE
tenant_id = the real tenant id. Result: both ILIKE checks are false on every row.

Confirmed live: the committed chat rule exists only in tenant_chat_rules and does not
appear, in any form, in any extraction_templates.rules row for the tenant. Reverted
after the check.

## 6. Wrong-data auto-diff triage - both outcomes, real chat pipeline

Asked the real chat pipeline (real Azure OpenAI, real SQL generation) "What is the
grand total on invoice APS-410093?" against the real tenant. Real answer: 453.60 USD
- matches the stored grand_total 453.6 exactly. Confirmed ChatMessage.result_invoice_ids
was populated with the real invoice id, Gap 231 harvest working live, not just in the
unit suite.

Thumbs-down with reason wrong_data returns real triage.next equal to diff_invoice
with the real invoice attached.

- Mismatch case: POST /triage with claimed_value 999.99 returns outcome mismatch,
  next category_pick (correctly routed to the chat-behaviour lane).
- Match case: POST /triage with claimed_value formatted as dollar-sign 453.60 returns
  outcome match (confirms the currency-symbol/numeric normalization works on real
  formatted input), next confirm_against_pdf.
- pdf_agrees true returns next category_pick (stays in chat lane).
- pdf_agrees false returns next extraction_flag_missed with a redirect block
  carrying the exact real invoiceId, field, vendorName and the three trainer
  endpoints - confirmed this is genuinely pre-filled, not placeholder data.

All four branches confirmed live against the real DB and real chat pipeline output.
Reverted (deleted the test ChatSession/ChatMessage rows) after the check.

## 7. Five source-text alert types - real 400s, live

POST /trainer/sessions/{id}/corrections/tolerance with each of the five
*_not_verified_in_source types, real session: all five return 400 with
rejection_reason not_tolerance_overridable and the registry own explanation
text. Confirmed live, not just via the parametrized unit test.

## 8. QA-mode conversational memory - real multi-turn test, real LLM

Real session_mode qa_test session. Turn 1: "My favorite test code word for this
session is BANANA77." Turn 2: "What was the code word I just gave you?" Real
assistant reply correctly recalled BANANA77 from turn 1. Confirmed the underlying
ChatMessage rows are real UUID-keyed rows (queried directly, all 4 real turns
present), not the old msg-hex8 synthetic ids. This directly reproduces the fix for
the confirmed latent bug (QA mode previously had zero memory because
get_chat_history of the trainer-qa-uuid string silently returned an empty string).

## 9. FE contract workarounds

- Vendor invoice-history picker: real GET /api/invoices?vendor_name=Apex+Print+Solutions
  through the real FE proxy returns a real invoice list with real alert counts,
  screenshot at ../../../invoice-fe/docs/test_evidence/feature14_trainer_redesign_2026-08-17/02_vendor_invoice_picker_real_alert_counts.png.
  Confirmed INBOUND-only by construction (matches doc).
- Bad tone chat correction: confirmed at code level (ThumbsDownTriage.tsx) the
  redirect is a real, prominent "Adjust response style" button to /trainer?panel=chat-style,
  and app/trainer/page.tsx genuinely reads that query param and opens the style tab.
  Not a dead end.
- Global-scope rules still applied: real, pre-existing legacy free-text rules on
  tenant 00000000-0000-0000-0000-000000000000's Global INBOUND row (6 plain-string
  constraints, real ground-truth data from an earlier investigation, predating this
  redesign) are still returned by agents/query_agent.py::_get_global_business_rules()
  when called live against the real DB - confirmed directly, not just by unit test.
  This is the specific regression the BE developer flagged as highest-risk.
- Dual-format regression: three real pre-existing legacy-format templates
  (Northwind Manufacturing, BrightPath Consulting LLC, and the Global row above - all
  plain list of strings, no structured objects) were run through normalize_constraints()
  live: every rendered string is byte-identical to the stored raw string, for both
  for_prompt=True and display reads.
- 410s on removed endpoints: POST /trainer/sessions/global and
  POST /trainer/sessions/from-production both confirmed live as 410 Gone with the
  documented pointer text.

## 10. Real defect found - filed as BE Gap 235

The one Feature 18 flow that genuinely needs an LLM - flag_missed_alert() missed-alert
rule drafting - fails on every live attempt against the actually configured Azure
deployment (AZURE_OPENAI_DEPLOYMENT_NAME=gpt-5-mini, a reasoning model).
routers/trainer.py calls get_llm(max_tokens=512) for this; the real completion object
shows the entire 512-token budget consumed by hidden reasoning_tokens, zero
accepted_prediction_tokens, so langchain_openai raises LengthFinishReasonError and the
endpoint (correctly, per the Gap 212 fail-closed contract) returns 502 rather than
fabricating a rule.

Reproduced twice (different alert type and field), and reproduced again at
max_tokens=1024 (still 0 accepted). Only succeeded at max_tokens=4096. See
02_gap235_llm_token_budget_failure_server_log.log for the real server log capturing
the CompletionUsage breakdown.

This also breaks the terminus of item 6 above (the pdf_agrees=false redirect target
is this same broken endpoint) - a real user following that whole flow correctly would
still hit a dead end today against this deployment.

Filed as BE Gap 235 in be_features_tracker.md (not fixed - out of scope for this
functional-testing pass per the boundary instruction).

---

## FE - separately re-run, not re-mocked in this doc

Full FE Playwright suite (npx playwright test, fullyParallel true, default workers):
49 passed, 15 failed. The 15 failures reproduce a documented dev-server JIT-compile
race under parallel load (already called out by the FE developer in
trainer-alert-anchored.spec.ts own comments for exactly this reason) - re-running
the same specs with --workers=1 --timeout=60000 brings it to 2 failed (both in
unrelated, non-Trainer parts of rbac-sidebar.spec.ts - Help nav link and the
notification-bell count - neither touched by this changeset per git diff --stat, and
out of this pass's scope), and re-running just the Trainer-relevant specs
(trainer-alert-anchored.spec.ts, trainer-loading-state.spec.ts,
group-a-layout-overflow.spec.ts) single-worker gives 21 passed, 1 failed - the
1 failure being the exact same pre-existing /ingestion Gap 86 test the developer
already flagged, independently confirmed unrelated (see FE coverage map entry).

npx tsc --noEmit: clean, exit 0, no output. Matches the developer claim.

See apps/invoice-fe/docs/test_evidence/feature14_trainer_redesign_2026-08-17/ for the
FE-side detail and screenshot.
