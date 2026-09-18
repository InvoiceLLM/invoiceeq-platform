# VPI demo tenant functional test against real Azure AI -- 2026-09-18

Real local stack (Postgres/Redis/Chroma/Azurite via docker compose), real Azure OpenAI
(gpt-5.6-luna) and real Doc Intelligence (docintel-invoicellm-dev), ALLOW_MOCK_AUTH=true.
DATABASE_URL overridden to 127.0.0.1 on the command line per BE Gap 697 (not edited in .env).

Tenant: Vishwa Precision Industries Pvt Ltd, seeded directly (not via website/Clerk) at
tenant id 00000000-0000-0000-0000-000000000000. Three users created directly in Postgres:
admin@vishwaprecision.in (Admin, all grants), auditor@vishwaprecision.in (Auditor, can_audit
only), trainer@vishwaprecision.in (Trainer, can_train only). Mock-auth testing note: the
ALLOW_MOCK_AUTH path always authenticates as a single shared identity (clerk_user_id
user_test_default); Auditor-only and Trainer-only screens were exercised by toggling that
shared identity permission flags between captures and sending a distinct Bearer token
spelling per role (test_00000000... for Admin, test_restricted_00000000... for the
zero-default role whose grants then come from the shared row). The three real User rows
above exist in Postgres for record-keeping and remain there; production Clerk auth resolves
Auditor/Trainer directly from org_role and does not have this limitation.

All 26 invoices (14 inbound: 11 PDF + 3 image-format; 12 outbound: 9 PDF + 3 image-format)
were ingested through the real pipeline (Doc Intelligence OCR + gpt-5.6-luna extraction),
matching showcase/vpi_demo/README.md ground truth exactly, including both planted duplicates
(NAT-2007, RAJ-2009) and the outbound tax mismatch (VPI-OUT-2014). Step C payments applied
(BHA-2002, OM -2000, SHR-2004 marked PAID via audit resolve; VPI-OUT-2012, VPI-OUT-2015
confirm-send + mark-paid).

## Files

- admin.png / admin_text.txt / atlas_lines_admin.json -- Admin role, GET /work full screen and
  raw GET /atlas/lines response
- auditor.png / auditor_text.txt -- Auditor-only role, GET /work
- trainer.png / trainer_text.txt -- Trainer-only role, GET /work
- sage_chat_answers.txt -- real chat/RAG answers (POST /chat/sessions/{id}/message) for: "Do
  we have any duplicate invoices?", "Which invoices need my attention?", "How much is
  outstanding?", "Convert Rajesh Steel's invoice to USD" -- session
  dee67d23-38b0-4cc6-9efd-3ddf967615f8

## Result summary

Full narrative findings reported to the founder directly. Three code defects filed as BE
Gaps 704-706 in docs/be_features_tracker.md. Also recorded there: showcase/vpi_demo/README.md
Section 8 and docs/atlas_vpi_scenario_day1_30.md describe Feature 33's design, which
docs/feature_34_atlas.md Section 8 states was never built -- Feature 34 (the live ATLAS)
replaced it with a different contract, so most of README Section 8's specific expectations
(Discover at 10 docs, five onboarding questions, weekly runs, FP&A cards, ops/exec clearance)
do not apply to what is actually running.

Demo data was left in place in Postgres under tenant 00000000-0000-0000-0000-000000000000
for the founder to click through. Both dev servers (uvicorn, next dev) and the queue worker
were stopped at the end of this session.
