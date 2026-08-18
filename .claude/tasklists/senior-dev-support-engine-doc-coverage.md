# senior-dev — Contact Us / Support Ticket Engine coverage in overview docs

Docs-only. Features BE 19 / FE 15 / Website 5 (Gaps 183, 246, 247, 248, 249–251) merged to master 2026-08-17/18 but never reached the five top-level overview docs.

Source-of-truth files read before writing (not assumed from docs):
- [x] `apps/invoice-be/routers/support.py` — 4 endpoints, exact paths/methods
- [x] `apps/invoice-be/main.py` — router mounted at prefix `/api/v1`
- [x] `apps/invoice-be/models.py::SupportTicket` + `alembic/versions/6c60f6e907a0_add_support_ticket_table.py`
- [x] `apps/invoice-website/app/` real route tree + `app/api/contact/route.ts`
- [x] `apps/invoice-fe/app/help/page.tsx`, `components/help/{SupportChatWindow,SupportTicketModal}.tsx`

## Steps
- [x] 1. TAD §6.2 — added `signup/`, `forgot-password/`, `contact/`, `billing/{success,failed}/`, `privacy/`, `terms/` and the whole `api/` subtree (all were genuinely absent; tree previously listed only layout/page/login)
- [x] 2. TAD §6.3 — added a `Contact Us (/contact)` row, explicitly separated from the Footer's marketing "Contact Sales"
- [x] 3. TAD §10.1 — added 4 rows: `POST /support/contact`, `POST /support/ticket`, `GET /support/tickets`, `POST /support/chat`; chat row records the keyword-matcher deviation rather than claiming LLM/RAG
- [x] 4. `Database_Schema_Document.md` — new `## 11. Table: supportticket` before PART 2; 18 columns, index list, and a note on the nullable/FK-less `tenant_id` vs Core Schema Rules
- [x] 5. `System_Journey_User_Admin_Guide.md` — new Part 1 subsection "When something goes wrong — getting help" (guides → assistant → escalation → website Contact Us), with an explicit expectation-setting note that replies come by email and there is no in-app ticket status board
- [x] 6. `apps/invoice-website/README.md` — `contact/page.tsx` + `api/contact/route.ts` in the dir tree, two new bullets in Key Pages & Sections
- [x] 7. `apps/invoice-fe/README.md` — `app/help/` + `components/help/` in the dir tree, `Help Center (/help)` row in the Screens table
- [x] 8. Re-read every edited region via `git diff` — additions only, no pre-existing line rewritten in any of the 5 files

Accuracy calls made while writing (checked against code, not docs):
- `/support/chat` is a deterministic keyword matcher, not LLM/RAG and not streamed — documented as such in TAD §10.1, the FE README and the journey guide, rather than repeating the spec's original claim.
- `GET /support/tickets` exists on the BE but **no** FE route consumes it (`app/api/support/` has only `chat/` and `ticket/`), so the journey guide does not promise users a ticket list.
- `supportticket` deviates from this repo's schema conventions twice (table name not snake_case; naive `TIMESTAMP` not `TIMESTAMPTZ`) — recorded in the new section instead of being papered over.

Final status: complete. All 5 files edited, additive only, left uncommitted.
