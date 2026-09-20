# ATLAS Intelligence -- VPI live verification (BE 35.10, FE 24.7) -- 2026-09-20

Founder approval: go for track4 (2026-09-20). Real local stack (Postgres 127.0.0.1:5433,
Redis, Chroma, Azurite), real Azure OpenAI gpt-5.6-terra (the atlas model role), tenant
00000000-0000-0000-0000-000000000000 (VPI). No product code or spec edited.

## How this was run

BE. The already-running uvicorn (PID 25588) had no AZURE_OPENAI_ATLAS_DEPLOYMENT_NAME, so
it was stopped and restarted:
```
DATABASE_URL=postgresql://postgres:localpassword123@127.0.0.1:5433/invoice_db
AZURE_OPENAI_ATLAS_DEPLOYMENT_NAME=gpt-5.6-terra
myenv/Scripts/python.exe -m uvicorn main:app --host 127.0.0.1 --port 8000
```
Confirmed via done.model on every capture below: model is gpt-5.6-terra.

FE. next dev started with DISABLE_CLERK_AUTH=true ALLOW_MOCK_AUTH=true
BACKEND_API_URL=http://127.0.0.1:8000. Driven by a throwaway Playwright script
(invoice-fe/_tmp_shot.mjs, deleted after the run, not committed), 1280x720 viewport, full-page
screenshots.

Auth technique -- reused from docs/test_evidence/vpi_demo_atlas_2026-09-18/after_fixes/
README.md section How the roles were simulated, because it is unchanged in this build: under
ALLOW_MOCK_AUTH, a Bearer test_ token (or no header, for the browser) always resolves to the
same shared identity clerk_user_id user_test_default -- dependencies.py test-token
branch never reads a UUID or role out of the token into user_id, only into tenant_id. That
identity is bound to the Admin DB row (74d4e74d-9baa-4d7b-a651-918b44efde67,
admin@vishwaprecision.in). To capture Auditor and Trainer, that row role/can_train/
can_audit columns were updated directly in Postgres between captures, then restored to
Admin/true/true at the end (verified below). The separate Auditor/Trainer User rows
(1ae4fb0f, 5bcd7e13) exist in Postgres but are unreachable through mock auth -- same
limitation the 2026-09-18 evidence recorded, not something this run changed.

AtlasBriefing has a tenant_id/user_id/briefing_date unique constraint, so every role
shares one cache slot for user_id user_test_default on today date -- each role row was
deleted immediately after that role capture(s), never left for the next role to collide with.

For the browser (EventSource cannot set custom headers, so Authorization was sent as a Playwright
context-level extraHTTPHeaders, which applies to the EventSource underlying HTTP request as
well as the document load): this is the same technique the 2026-09-18 evidence used, including its
one side effect -- sending an Authorization header on the document request breaks Clerk CDN
preflight (real-stallion-21.clerk.accounts.dev CORS error), visible as console noise on every
screenshot capture below. It does not affect the page: DISABLE_CLERK_AUTH=true bypasses Clerk
own gate.

## Three score lines

- Admin: 0 MATCH / 2 PARTIAL / 10 MISS (of 12 M-items; 3 MISS expected -- M3/M4/M11 are
  NO-TOOL-TODAY). 0 INVENTED tokens. 0 section-3 violations. Question did not fire (required, always).
- Auditor: 0 MATCH / 0 PARTIAL / 4 MISS (of 4 required section-5 items). 0 INVENTED tokens.
  1 section-5 MUST-NOT violation -- a cash_position-shaped paragraph including the word
  runway, which section 5 says must be absent from Auditor tool schema entirely.
- Trainer: 0 MATCH / 1 PARTIAL / 2 MISS (of 3 required section-5 items). 0 INVENTED tokens.
  2 section-5 MUST-NOT violations -- duplicate/audit-approve content and a VPI-OUT-2014
  reconciliation paragraph via the invoices tool, both excluded from Trainer schema by
  section 5.

Full per-item reasoning: grading_admin.md, grading_auditor.md, grading_trainer.md.

## Two deterministic proofs

1. Cache. Admin GET #1 (briefing_admin.sse.txt) -> cached false, DB row
   7b279ab3-21a2-4b55-af0d-e3ec49d39dd4 created (tokens_in 8046, tokens_out 975, cost_usd
   0.027792). Admin GET #2 immediately after (cache_proof_second_get.sse.txt) ->
   cached true, same row, no new row (row count stayed at 1 for
   user_id user_test_default).
2. Dismiss -> stale -> regenerate. POST /atlas/lines/audit-approve-530bd65a/dismiss ->
   atlas_briefings row 7b279ab3 flips stale to true. Next GET
   (cache_proof_regenerated_after_dismiss.sse.txt) -> cached false, same row upserted in
   place (stale back to false, id unchanged) with fresh paragraph content (the dismissed line
   audit-approve citation no longer present in the RAJ-2009 paragraph).

## Tenant left as found -- what was created and deleted

- atlas_dismissals row 26b6e5b3-79b5-4533-a356-6f09da2862c9
  (audit-approve-530bd65a-be04-4953-988b-2932f52a6f89) -- created by the dismiss-proof POST,
  deleted; restoration confirmed by re-GET /atlas/lines showing the id present again.
- atlas_dismissals row 05d805e9-a715-4111-a0f8-fb35bd0f43db (same recommendation id) --
  created by the FE dismiss-screenshot click, deleted; restoration re-confirmed the same way.
- atlas_briefings rows created and deleted, one per capture (CLI and screenshot runs never
  overlapped): 7b279ab3 (Admin, CLI, after dismiss-regenerate), 3987aa3d (Auditor, CLI),
  f2d5235e (Trainer, CLI), 77fcaec7 (Admin, screenshot run), abe0d2e5 (Auditor,
  screenshot run), ac3b9729 (Trainer, screenshot run). 6 rows created, 6 deleted --
  table confirmed at 0 rows for user_test_default at the end.
- users row 74d4e74d-9baa-4d7b-a651-918b44efde67: role/can_train/can_audit toggled
  Admin -> Auditor -> Trainer -> Admin (twice, once per CLI pass and once per screenshot pass) and
  confirmed restored to Admin / true / true at the end.
- No atlas_memory_rules, atlas_action_log, invoice, or line data touched.

## Screenshots

work_admin.png, work_auditor.png, work_trainer.png -- briefing panel at the top of /work,
each role real live paragraphs, footer shows gpt-5.6-terra (fresh) or from cache (React
Strict Mode double-mounts the EventSource in dev, so the second mount typically replays the
first mount just-written cache -- visible on work_admin.png footer; not a defect, a dev-mode
artifact of the same request landing twice within milliseconds).

work_admin_citation_click.png -- clicking a recommendation citation scrolls to and highlights
(amber ring) the RAJ-2009 INVOICE_AWAITING_DECISION card.

work_admin_after_dismiss.png -- after dismissing that card, the briefing panel shows the text
Briefing will refresh on your next visit and the card is gone from the decision list.

## Deviation: SSE content vs. rendered screen

The raw briefing_ROLE.sse.txt captures (CLI, curl) and the work_ROLE.png screenshot
captures (browser, Playwright) are two separate live generations, not the same run rendered
two ways -- the model is not deterministic and each GET is a fresh Terra call once the prior
role cache row was deleted. Content differs in wording and, for Trainer, in which optional
paragraph appears (the CLI Trainer run included the VPI-OUT-2014 paragraph; the screenshot
Trainer run did not, on that pass). The defect pattern is identical across both: Auditor
runway/cash-position line and Trainer audit-approve/reconciliation content reproduced in both
the CLI and the screenshot capture, so this is model output variance around a real, reproducible
gating gap, not a rendering bug. No dropped_paragraphs/truncated/withheld-count mismatch was
observed on any capture (dropped is 0 on every DB row; the FE never rendered fewer paragraphs than
the SSE stream sent -- 4 rendered for 4 sent, every role).

## Defects observed -- candidate gaps (not filed, not fixed)

1. Auditor tool schema appears to reach cash_position-shaped output (the runway line),
   despite atlas_admin_vpi_expected.md section 5 stating the schema excludes cash_position and
   forecast for Auditor. Reproduced on both the CLI and screenshot capture.
2. Trainer receives audit-scoped content: audit-approve duplicate-recommendation citations
   (paragraphs 1-2, both captures) and, on the CLI capture, an invoices-tool VPI-OUT-2014
   reconciliation paragraph -- despite BE Gap 716 own tracker note describing the invoices
   tool pre-fetch as gated to can_audit/Admin. Reproduced on both captures for the
   duplicate-content half; the invoices-tool half reproduced once (CLI) -- model-call
   non-determinism, not proof it cannot happen on the screenshot pass too.
3. The interview question (section 4) never fired in any of the 6 live runs captured here
   (3 CLI + 3 screenshot), despite RAJ-2009 vs RAJ-2008 being present and unresolved in every
   one. Ground truth requires exactly one question per Admin run.
4. M1-M12 citation-id convention mismatch: ground truth Must cite ids are bare (e.g.
   530bd65a, cash-INR); the live system emits role/area-prefixed ids
   (audit-approve-530bd65a, audit-cash-INR). Graded here by substring containment -- under
   strict equality, every M-item would be an automatic MISS regardless of content, which would
   make the grading rule as literally written untestable against this build. Worth a doc/code
   reconciliation, not urgent.

None of these were fixed here -- CONVENTIONS hard rule 1 (founder gate) and this task explicit
scope (evidence only, no product-code or spec edits).
