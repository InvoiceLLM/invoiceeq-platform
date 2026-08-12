# Gap 133 remediation (Checkpoint 3b) — senior-dev tasklist

Scope locked by user decisions in Checkpoint 3a: strictest gating (no auto-provision),
blocking sign-up UX with Retry, no domain-tenant adoption of populated tenants,
auth hardening on `/auth/provision` bundled in.

- [x] A. `routers/auth.py::provision_tenant` — auth verification (Clerk token, `sub == clerk_user_id`),
      IntegrityError retry with `org-{clerk_org_id}.invalid`, hard 409 on second failure,
      adoption only of an org-less AND user-less domain tenant.
- [x] B. `dependencies.py::get_tenant_context_allow_unpaid` — remove Priority-3 domain fallback +
      request-time tenant creation; 409 when Priority 1/2 both miss. Track `email_is_placeholder`,
      add `email_present=` to `[jwt-diag]`.
- [x] C. website `signup/page.tsx` + `api/auth/provision/route.ts` — blocking errors, Retry button,
      real Clerk session token forwarded, server-side `console.error`, drop "best-effort" framing.
- [x] D. `TenantContext.tenant_name` (dependencies.py + email_ingestion.py), `useAuth.ts` `tenantName`,
      `Header.tsx` + `app/admin/page.tsx` display source, 4 e2e fixtures.
- [x] E. Regression tests in `tests/test_auth.py`.
- [x] Dev-DB impact query: which existing users/tenants only resolved via the removed Priority-3 path.
- [x] Verification: pytest (auth/tenant paths), `tsc --noEmit` on invoice-fe + invoice-website,
      live repro of collision + takeover bugs.
- [x] Docs: `be_features_tracker.md` Gap 133 -> `[x]`, `feature_4_auth_gateway.md` (website),
      BE `feature_1_auth.md` (if it exists), FE `feature_1_layout_theme.md`,
      cross-ref entries in website tracker (Gap 176) and FE tracker (Gap 217).

**Final status (2026-08-11): complete.** All code + tests + docs landed, uncommitted.
pytest tests/test_auth.py 26/26; full suite 316 passed / 1 pre-existing Redis failure;
tsc --noEmit clean on invoice-fe and invoice-website; live HTTP before/after repro
confirmed the 500-on-collision, the domain takeover and the anonymous takeover are all
closed. Dev-DB audit: no existing users row loses access; 5 Clerk accounts with
unprovisioned orgs will now 409 (listed in be_features_tracker.md Gap 133). No backfill
performed (out of scope). Temporary Postgres firewall rule used for the audit was
removed; verified only AllowAllAzureIPs remains.
