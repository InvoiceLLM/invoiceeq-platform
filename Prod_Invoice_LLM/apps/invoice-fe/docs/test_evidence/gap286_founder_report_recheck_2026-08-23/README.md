# Gap 286 re-check -- founder-reported "overlap between Extracted Fields and metadata"

**Date:** 2026-08-23
**Trigger:** Founder reported a visual "overlap" between the "Extracted Fields" section and the
"Additional Extracted Metadata" panel in the Auditor Review Console
(app/invoices/review/[id]/page.tsx), after Gap 286 (commit 3587348, 2026-08-21) had already
fixed exactly this symptom class.
**Verdict: does NOT reproduce.** No overlap/collision/clipping found at either a wide (>1280px, xl
3-column) or narrow (<1280px, stacked grid-cols-1) viewport, against a real, metadata-rich invoice
served by the actual running backend/DB (not stubbed). The Gap 286 fix (metadata panel moved inside
the fields column's overflow-y-auto scroll container) is working as designed. Most likely
explanation for the report is a stale browser cache -- see "What was NOT tested" below.
## Environment

Real local dev stack, started fresh for this check (not mocks):
- docker compose up -d in Prod_Invoice_LLM/ -- Postgres (invoice-postgres-local), Redis, Chroma,
  Azurite.
- invoice-be: .venv uvicorn main:app on localhost:8000, alembic upgrade head run first
  (landed cleanly on head c4a91e77b208).
- invoice-fe: next dev on localhost:3000, started with DISABLE_CLERK_AUTH=true (bypasses the
  Clerk middleware page-gate only -- API auth still goes through the real backend).
- Chromium via Playwright (invoice-fe's own installed playwright package, driven by a one-off
  Node script, not the e2e/ Playwright-test suite -- this check needed a real backend + real DB row,
  which every existing spec under e2e/ deliberately stubs away).
## Auth path used to reach a real invoice

dependencies.py::get_tenant_context_allow_unpaid() has a documented dev/test path
(ALLOW_MOCK_AUTH=true, already set in invoice-be/.env): a bearer token of the form test_<uuid>
is accepted and, on first creation of the mock user row, the <uuid> part is parsed as a tenant UUID.
This DB already had a persisted user_test_default row from earlier test runs, tied to tenant
3511ae3e-27a4-49a5-897d-6a1a3fc3ac91 -- on an existing mock user, the dependency reads
user.tenant_id and ignores whatever UUID the token embeds, so the token trick alone could not steer
to an arbitrary tenant.

To reach the most metadata-rich invoice in the DB, the mock users tenant_id was retargeted for the
duration of this check only, via direct SQL against the local dev container:

    UPDATE users SET tenant_id = a614e3c0-fb30-4f82-8f9e-9fe9649e6ec1 WHERE clerk_user_id = user_test_default;
    -- ... screenshots taken ...
    UPDATE users SET tenant_id = 3511ae3e-27a4-49a5-897d-6a1a3fc3ac91 WHERE clerk_user_id = user_test_default;

(quotes around the UUID values omitted above for shell-safety in this note; the actual statements run
used standard SQL string literal quoting). Reverted immediately after screenshots were captured
(confirmed by re-querying the row afterward). No other rows were modified.
## Invoice used

Queried every non-outbound invoice in the local DB, ranked by total metadata-list length
(taxes + discounts + tax_ids + payment_instructions + references + compliance_metadata) to find the
richest available real candidate (payment_instructions is empty on every invoice in this DB -- none
seeded with that field):

    id:              97910ddb-15be-449f-9c25-ed7250f2ebf5
    tenant_id:       a614e3c0-fb30-4f82-8f9e-9fe9649e6ec1
    vendor_name:     Rhein Industrietechnik GmbH
    invoice_number:  RIT-2026-0456
    status:          COMPLETED
    currency:        EUR
    taxes:           2   (Reverse charge intra-EU 0%, VAT 19%)
    tax_ids:         2   (Seller VAT ID, Buyer VAT ID)
    references:      2   (Purchase Order, Contract value USD equivalent)
    compliance_metadata: 6 (Invoice Number, Invoice Date, PO Number, Seller VAT ID, Buyer VAT ID, Currency)
    discounts:       0
    payment_instructions: 0

13 metadata rows plus the Currency line -- the densest Additional Extracted Metadata panel available
in this dataset, i.e. the real-world stress case the panel has to survive.
## Method

Fresh Chromium context per check (no reused browser profile / no HTTP cache reused across runs --
page.route matched every request and forced a no-cache header, and each viewport did a full
page.goto() plus page.reload() before screenshotting). An Authorization: Bearer test_default header
was set at the context level so every request, including the initial navigation, carried it.

For each viewport:
1. Navigate and hard-reload the review console for the invoice above.
2. Screenshot.
3. Scroll the fields columns own overflow-y-auto inner container to scrollHeight (its actual
   end), to specifically re-test the exact failure mode Gap 286 fixed: pre-fix, the metadata panel sat
   outside this scroll container and no amount of scrolling brought its end into view.
4. Screenshot again.
5. Read getBoundingClientRect() for [data-testid=fields-panel], [data-testid=extracted-metadata-panel],
   and [data-testid=alerts-panel] directly from the DOM.
## Results

### Wide -- 1440x900 (xl 3-column layout active)

| element | bottom (px) |
|---|---|
| fields-panel | 844.00 |
| extracted-metadata-panel | 826.78 |
| alerts-panel | 844.00 |

extracted-metadata-panel bottom (826.78) is inside fields-panel bottom (844) -- fully contained, not
clipped. Screenshots: 1_wide-1440x900_initial.png, 2_wide-1440x900_scrolled-to-metadata-end.png
(after scrolling the fields column to its end, the full Additional Extracted Metadata block --
Currency, Tax IDs, Tax Breakdown, References, Compliance/e-Invoice, all 13 rows -- is visible,
readable, and does not collide with the Alerts column to its right).

### Narrow -- 1024x900 (stacked grid-cols-1 layout active, below the xl breakpoint)

| element | bottom (px) |
|---|---|
| fields-panel | 869.78 |
| extracted-metadata-panel | 852.78 |
| alerts-panel starts at | 885.78 |

Same containment property: metadata panel ends inside the fields panel, and the fields panel itself
ends comfortably above where the (now vertically-stacked, not side-by-side) Alerts panel begins -- no
collision between panels in the stacked layout either. Screenshots:
3_narrow-1024x900_fields-panel-top.png (fields column scrolled into view -- this is what scrolling to
the Extracted Fields section looks like at this width, the PDF viewer sits above it in the stack),
4_narrow-1024x900_scrolled-to-metadata-end.png (fields column's own inner scroller run to its end --
full metadata block visible, readable, correctly positioned).
5_narrow-1024x900_page-top-pdf-viewer.png is the page's initial scroll position for reference (PDF
viewer; confirms the stacked layout renders top-to-bottom as designed, nothing overlapping there
either).
## What was NOT tested

- Did not reproduce against the founders own browser/session/cache state -- this was a fresh
  Chromium profile with cache forced off on every request, specifically to rule out a stale bundle.
  Given the fix has been live in this environment (and per prior investigation, in the deployed FE
  image) since 2026-08-21, a stale service-worker or browser cache on the founders end is the leading
  candidate if what they are seeing is exactly this symptom.
- Did not test every possible zoom level or an ultra-narrow mobile viewport below 768px -- the report
  did not specify a device, and the two widths tested bracket the layouts one real breakpoint
  (xl = 1280px), which is the only place the CSS in page.tsx branches.
- Per task scope, this was investigation only -- no code changes were made.

## Cleanup performed

- users.tenant_id for user_test_default restored to its original value
  (3511ae3e-27a4-49a5-897d-6a1a3fc3ac91) immediately after the screenshots above were captured.
- Two one-off Node/Playwright driver scripts used to produce these screenshots were deleted from
  apps/invoice-fe/ after the run (not part of the app or the e2e/ suite).
