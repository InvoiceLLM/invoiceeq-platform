# security-tester — live dev security pass

Started 2026-09-01, founder-approved scope. Read-only against rg-invoice-llm-dev
(ENVIRONMENT=production on this "dev" box — treat it as the closest thing to
production that exists). No writes, no fixes, no pushes — this pass finds
and drafts Gap entries only; the founder reviews and decides what gets fixed.
Hard stop at 1 hour or on completion, whichever first — status emailed to
sbanerji@admsofttech.com every 15 minutes by the orchestrating session.

- [x] Capture live baseline: ENVIRONMENT=production and ALLOW_MOCK_AUTH=false
      re-confirmed (no drift). Ingress: only website external; be/fe/chromadb
      internal (external=false); queue-worker no ingress; ca-ollama-eval-dev
      external but IP-allowlisted to one /32. Front Door og-website only.
      Website proxies /api/{prefix} to internal FE/BE (ENABLE_FE_PROXY=true) —
      BE REST surface reachable externally through that proxy, BE-enforced.
- [x] Tenant isolation probes: LIVE cross-tenant probe BLOCKED (no inv_live_ key
      or Clerk sessions were provided; read-only scope precluded minting keys or
      creating tenant rows). Covered by source trace instead: every Invoice.id
      lookup across audit/invoices/outbound_*/chat/trainer is paired with
      Invoice.tenant_id == context.tenant_id; connectors rows also tenant-scoped.
      No cross-tenant leak found in code.
- [x] RBAC enforcement probes: source-traced (live role sessions not available).
      require_admin never satisfiable by an API key; Gap 173 org-clamp present.
      FINDING F5: routers/connectors.py connect/disconnect/import/files have NO
      backend role gate (only get_tenant_context) while FE reserves them to
      Admin — within-tenant privilege gap, externally reachable. Also confirmed
      the old FE isAdmin={true} hardcode is now FIXED (derives from authRole).
- [x] Auth/token handling: LIVE via public proxy — junk inv_live_ key ->
      "Invalid or revoked API key"; forged JWT (fake kid) -> "Invalid token key
      ID (kid)"; test_ mock token -> rejected (ALLOW_MOCK_AUTH=false enforced at
      runtime). BE own error messages surface, so headers reach BE and it
      validates kid/signature. Expired/forged-signature JWT not forgeable
      without Clerk private key; org-clamp confirmed by code, not live.
- [x] Infra exposure: be/fe/chromadb confirmed internal-only. F1 no WAF on
      invoiceeq-fd-profile (waf-policy + security-policy lists empty). F2
      Postgres publicNetworkAccess=Enabled + AllowAllAzureIPs (0.0.0.0) + two
      stale personal-IP dev firewall rules. F3 shared secret AdmInvoiceSecret2026
      + partial SendGrid key in plaintext at be_features_tracker.md:264/:1414 and
      feature_14_email_ingestion.md:88/103 (runtime uses KV secretRef — leak is
      docs only). F4 storage minTls=TLS1_0 + open network default. F6 ollama
      external but IP-locked. F7 KV/OpenAI/DocIntel internet-reachable, KV no
      purge protection. Secrets otherwise all KV-backed via managed identity.
- [x] File findings to Prod_Invoice_LLM/reports/security/2026-09-01-live-dev-pass.md
- [x] Draft Gap entries for founder review — drafted in the final report-back to
      the orchestrating session; NOT written into any tracker and NOT committed.
- [x] Final status line here.

FINAL STATUS: DONE (within scope). 5 confirmed findings (F1-F5), 3 lower/info
(F6-F8). Two live items (cross-tenant isolation, live RBAC role boundary)
BLOCKED on missing test credentials — mitigated by source trace. No writes,
no fixes, no commits/pushes performed. Stopped for founder review.
