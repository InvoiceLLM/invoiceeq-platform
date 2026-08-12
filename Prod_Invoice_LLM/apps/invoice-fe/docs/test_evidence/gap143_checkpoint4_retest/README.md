# Gap 143 fix retest -- Checkpoint 4 (verification half)

Checkpoint 4 of the defect remediation plan. Pure verification, no code
changes made by this pass. Real local dev stack: Postgres/Redis/Chroma/Azurite
via docker compose (project root Prod_Invoice_LLM/), real backend
(uvicorn main:app, port 8000, ALLOW_MOCK_AUTH=true), real invoice-fe
Next.js dev server (port 3001, DISABLE_CLERK_AUTH=true -- same established
bypass pattern as gap177_checkpoint2_retest). Playwright headless
Chromium, 1280x800. 2026-08-12.

Ad hoc Node scripts driving @playwright/test's chromium were used for
each phase and deleted afterward (ephemeral verification tooling, per this
repo's test_evidence convention of filing outputs, not scaffolding).

Because this dev environment's mock-auth path always resolves to the same
persisted user_test_default user/tenant row once created (dependencies.py
looks the user up by a hardcoded mock clerk_user_id, not by whatever the
request token claims), two different techniques were used to exercise the
four states this checkpoint needs, both real and both leaving the dev DB
unchanged by the end of the run:

- Plan/tier states (paid vs free): the existing seeded tenant
  (00000000-0000-0000-0000-000000000000, "Example Workspace") was
  temporarily flipped between pro_combined and free via direct SQL,
  verified, then restored to its original pro_combined / 50 /
  NULL reset_at values.
- Role state (Admin vs Viewer): rather than mutate the DB (confirmed
  ineffective for this -- see note below), the mock auths documented
  Authorization: Bearer test_viewer token path was used, which the backend
  actually reads role from per-request. No DB write needed or made for
  this part.

## Auth mechanics note (why a DB role edit alone did nothing)

Tried first: UPDATE users SET role='Viewer' WHERE clerk_user_id=
'user_test_default', then reloaded with no Authorization header. Result:
GET /auth/me still reported "role":"Admin". Traced to
dependencies.py::get_tenant_context_allow_unpaid -- the no-header mock
branch hardcodes role = MOCK_ROLE ("Admin") and
reconcile_role_with_org() returns the token-derived role verbatim for any
is_mock_identity request, never consulting the persisted User.role at
all. The role update to the DB was reverted (back to Admin) once this was
confirmed, since it had no effect through this path and there was no reason
to leave it changed. Switching to the test_viewer mock token bearer header
(documented in dependencies.py own token-parsing branch) worked exactly
as designed -- see item 1 below.

## 1. Sidebar navigation

Admin (default mock context, no header override): screenshot
1_admin_dashboard_sidebar.png shows "Subscriptions" as its own item, between
Settings and Help, exactly where Sidebar.tsx places it. Clicked it
(2_admin_subscriptions_page_paid_tier.png) -- URL became
/settings/subscriptions, and a DOM query for every sidebar links class
list found border-l-2 (the active-row style) on exactly one href:
["/settings/subscriptions"]. Settings did not also light up.

Non-Admin (Authorization: Bearer test_viewer, confirmed via GET
/auth/me returning "role":"Viewer"): 5_nonadmin_viewer_sidebar_no_
subscriptions.png -- sidebar nav text is exactly Dashboard / Chat / Help.
Both Settings and Subscriptions links have count 0 in the DOM. Also
checked a direct URL visit to /settings/subscriptions as this same Viewer
(6_nonadmin_viewer_direct_url_subscriptions.png) for completeness, though
not explicitly asked: the page itself is still reachable (expected --
routers/billing.py::get_billing_usage is deliberately not Admin-gated,
per its own docstring: a non-Admin who can ingest invoices is exactly who
runs into the 402 that this number predicts) and correctly shows the
read-only "Only administrators can change the workspace subscription tier or
manage checkout" notice instead of the plan picker. Not a defect --
consistent with the backends documented design decision, noted here rather
than filed as a finding.

PASS on all three sub-items.

## 2. Usage tracker -- free tier

Tenant flipped to billing_plan='free', free_invoices_remaining=37,
free_quota_reset_at='2026-09-01 00:00:00'. Reloaded /settings/
subscriptions: 3_free_tier_usage_bar.png shows "13 / 50 invoices used",
a proportional bar, and "37 remaining, renews 1 Sept 2026". Real network
capture (network_responses.txt, section 2) shows GET /api/billing/usage
returning plan=free, metered=true, used=13, limit=50, remaining=37 --
used = limit - remaining = 13 reconciles exactly with the DB row, and
limit: 50 matches apps/invoice-be/config.pys
DEFAULT_FREE_INVOICES_LIMIT = 50 (not the old hardcoded 25). Numbers on
screen are traceably the same numbers in Postgres, not a client-side
recount.

PASS.

## 3. Usage tracker -- paid tier ("Not metered")

Same tenant at its real, original billing_plan='pro_combined' (captured
before the free-tier flip above, in the same run as item 1s screenshot 2).
2_admin_subscriptions_page_paid_tier.png shows "Not metered on this plan"
and "This plan has no invoice allowance enforced on it." -- no bar, no
fabricated ceiling. Network capture (network_responses.txt, section 1)
confirms plan=pro_combined, metered=false, used/limit/remaining all null.

PASS.

## 4. Error state ("Usage unavailable")

Real backend was left running and untouched; instead
context.route on **/api/billing/usage forced the browser->Next.js
route-handler leg to return 500 (a real HTTP response sent over the wire,
not a swallowed/aborted request -- network_responses.txt section 3 shows
both the outbound request and the 500 response captured via Playwrights
request/response events, and the request fired twice, consistent with
Next dev modes double-render, not a missed call). 4_usage_unavailable_
error_state.png shows amber "Usage unavailable" and "Could not reach the
billing service, this figure is not a zero, it is unknown." -- not a silent
0, which was the original Gap 143 failure mode this specifically replaces.

PASS.

## 5. e2e/rbac-sidebar.spec.ts

Command used: npx playwright test e2e/rbac-sidebar.spec.ts (this repos
package.json test:e2e script is "playwright test", i.e. the full suite;
scoped here to the one spec).

First run (backend from earlier steps still up on :8000, sharing the
default port with the specs own isolated dev server on :3100): 18/19
passed, one failure -- "bell shows the real count and links to the queue"
expected 7 but rendered 12. Root-caused, not a Gap 143 regression: that
one tests stub only covers the inbound AUDIT_REQUIRED count
(x-total-count: 7); the outbound NEEDS_REVIEW half of
Header.tsx::useNeedsAttentionCount has no page.route() stub in that
test, so with a real backend reachable on the default port it fell through
to the actual network call and added the real outbound count for tenant
00000000-... (5, confirmed via SELECT count(*) FROM invoice WHERE
tenant_id=... AND flow_direction='OUTBOUND' AND status='NEEDS_REVIEW') --
7 + 5 = 12, exactly the observed number. Confirmed as environmental
contamination, not a code defect, by stopping the backend and rerunning:
19/19 passed clean, including "Admin sees every nav item, including
Settings and Subscriptions" and both ADMIN_ONLY = ["Settings",
"Subscriptions"] assertions across the Viewer/granted-permission/Admin
describe blocks. This spec run needs the real backend stopped (or otherwise
unreachable on localhost:8000) to be a clean signal -- documented here for
whoever runs it next, since playwright.config.tss own webServer spins an
isolated dev server that will silently pick up any backend that happens to
be listening on the default port.

PASS (19/19, clean run).

## Files

- 1_admin_dashboard_sidebar.png -- Admin, dashboard, sidebar with Subscriptions item
- 2_admin_subscriptions_page_paid_tier.png -- Admin, /settings/subscriptions, pro_combined ("Not metered"), only Subscriptions row active
- 3_free_tier_usage_bar.png -- same tenant flipped to free, real usage bar (13/50, 37 remaining)
- 4_usage_unavailable_error_state.png -- simulated 500, "Usage unavailable" state
- 5_nonadmin_viewer_sidebar_no_subscriptions.png -- Viewer role (mock test_viewer token), sidebar reduced to Dashboard/Chat/Help
- 6_nonadmin_viewer_direct_url_subscriptions.png -- Viewer, direct URL to /settings/subscriptions, read-only view
- network_responses.txt -- raw GET /api/billing/usage / GET /api/auth/me bodies for every state above, plus the DB rows they were traced against

## DB state -- confirmed restored

Tenant 00000000-0000-0000-0000-000000000000: billing_plan='pro_combined',
free_invoices_remaining=50, free_quota_reset_at=NULL -- its state before
this retest began. users row for user_test_default: role='Admin' --
also its state before this retest began. No other DB rows were touched.
