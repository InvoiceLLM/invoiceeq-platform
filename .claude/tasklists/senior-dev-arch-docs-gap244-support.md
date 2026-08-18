# senior-dev — architecture/overview doc refresh (Gap 244 threshold + Support Ticket Engine)

Documentation-only pass. No application code changes. Leave uncommitted.

## Part A — factual contradictions (0.4 -> 0.49)
- [ ] Verify `chroma_client.py:43` says `RELEVANCE_DISTANCE_THRESHOLD = 0.49`
- [ ] `docs/architecture/Technical_Architecture_Document.md` §9.2 — 0.4 -> 0.49, cite Gap 244
- [ ] `docs/architecture/System_Journey_Developer_Guide.md` §9 — same fix

## Part B — Contact Us / Support Ticket Engine (Features 5/15/19)
- [ ] Verify real `apps/invoice-website/app/` route tree
- [ ] Verify exact paths/methods in `apps/invoice-be/routers/support.py`
- [ ] Verify `supportticket` model (`models.py` ~619) + migration `6c60f6e907a0`
- [ ] TAD §6.2 website directory tree — add missing route dirs
- [ ] TAD §6.3 Functional Sections table — add `/contact` row (not the marketing "Contact Sales" footer link)
- [ ] TAD §10.1 API Inventory — add the 4 support endpoints
- [ ] `docs/architecture/Database_Schema_Document.md` — add `supportticket` table section
- [ ] `docs/guides/System_Journey_User_Admin_Guide.md` — add support-ticket journey section
- [ ] `apps/invoice-website/README.md` — add `/contact` + `/api/contact`
- [ ] `apps/invoice-fe/README.md` — add `/help` screen

## Status
In progress.
