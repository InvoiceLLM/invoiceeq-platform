# Security pass — live dev environment (rg-invoice-llm-dev)

- Date: 2026-09-01
- Scope (founder-approved, read-only): tenant isolation, RBAC, auth/token handling, infra exposure — against the live dev RG (ENVIRONMENT=production on this box). No writes, no fixes, no pushes.
- Method: Azure control-plane inspection (az), black-box probes against the public domain https://invoicellm.admsofttech.com, and source trace of the backend auth/data layer. No load/fuzz/DoS.
- Public attack surface confirmed: only the website Container App is external (Front Door to website only). invoice-be, invoice-fe, chromadb are ingress-internal. The website reverse-proxies /api/{prefix} to the internal FE then BE (ENABLE_FE_PROXY=true), so the BE REST surface IS reachable from the internet through that proxy, BE-enforced.

## Remediation status (added 2026-09-01, after the review)

Findings below are as originally written and are **not** edited in place — this block records what's since been done, per explicit founder decision on each item.

| # | Finding | Status |
|---|---|---|
| F1 | No WAF on Front Door | **Deferred to Phase 2** — real Azure cost, founder's call to hold it. Recorded in `docs/phase_2_enhancements.md` §5. |
| F2 | Postgres public network access + stale firewall rules | **Deferred to Phase 2** — can't be safely closed without VNet/private-endpoint work first (dev has no VNet today; invoice-be likely reaches Postgres through that broad rule). Recorded in `docs/phase_2_enhancements.md` §6. |
| F3 | Live shared secret + partial API key in plaintext docs | **Fixed, docs-only** — BE Gap 361. Redacted from all 4 locations. Founder's explicit call not to rotate the underlying values; both remain in git history as a residual accepted risk. |
| F4 | Storage account TLS 1.0 | **Fixed** — BE Gap 361. Live (`az storage account update --min-tls-version TLS1_2`) and in `infra/modules/data/storage.bicep` (was never explicitly declared before). |
| F5 | Connector endpoints missing backend RBAC | **Fixed** — BE Gap 361. All 5 mutating endpoints now require Admin; `GET /status` deliberately left open. 6 new regression tests in `tests/test_connectors.py`. |
| F6 | Ollama eval external ingress | **Closed, removed** — the candidate was found dead-since-deploy (zero traffic since 2026-08-24) and structurally unable to produce a valid comparison (prompt truncation + timeout margin on this sizing). `ca-ollama-eval-dev`, its CAE storage link, and `infra/ollama-eval-only.bicep` all removed. Detail: `apps/invoice-be/docs/be_features_tracker.md`, Feature 23 Phase 4. |
| F7–F8 | KV purge protection, stale CORS origin | **Not actioned** — no founder decision recorded yet. |

Full detail on F3/F4/F5: `apps/invoice-be/docs/be_features_tracker.md` Gap 361.

## Baseline (re-verified, no drift)
- ca-invoice-be-dev env: ENVIRONMENT=production, ALLOW_MOCK_AUTH=false — both confirmed. ALLOW_MOCK_AUTH=false is runtime-enforced (a Bearer test_admin probe returns the message that test tokens are rejected when ALLOW_MOCK_AUTH is disabled).
- Ingress: website external; be/fe/chromadb internal (external=false); queue-worker no ingress. ca-ollama-eval-dev external but IP-allowlisted (see F6).
- Front Door invoiceeq-fd-profile: single endpoint, origin group og-website only.

## Positive confirmations (no action)
- Auth/token handling is solid. Via the public proxy: a junk inv_live_ key returns Invalid or revoked API key; a forged JWT with a fake kid returns Invalid token key ID (kid); a test_ mock token is rejected. These are the BE own messages, meaning headers reach the BE and it validates kid/signature/mock-gate.
- Tenant isolation in the data layer is systematic. Every Invoice.id lookup in routers audit, invoices, outbound_invoices, outbound_audit, chat and trainer is paired with Invoice.tenant_id == context.tenant_id. Connector rows are likewise scoped (connectors.py:441).
- API-key model (dependencies.py, services/api_keys.py): PBKDF2+salt, hmac.compare_digest; require_admin can never be satisfied by a key at any scope; readonly/actions scope fails closed to readonly; sandbox keys pinned readonly + TTL-checked every auth. Gap 173 org-clamp (reconcile_role_with_org) is present and clamps to NO_ROLE.
- Secrets: all runtime secrets use secretRef to Key Vault (kv-invoicellm-dev) via user-assigned managed identity, including INBOUND_PARSE_SHARED_SECRET. Storage blob public access disabled; Redis Enterprise clientProtocol Encrypted.
- Previously-flagged FE isAdmin hardcode on settings/connectors/page.tsx is FIXED — it now derives isAdmin from authRole == Admin.

## Findings

### F1 — No WAF on Front Door (CONFIRMED, infra)
az afd security-policy list and waf-policy list for invoiceeq-fd-profile are both empty. Front Door is the public entry to the website, which proxies the whole BE REST surface. No managed ruleset, no rate limiting, no bot/geo controls in front of an internet-facing app that reaches Postgres. Failure scenario: credential-stuffing or injection traffic hits /api/* at full rate with nothing to absorb or filter it before the app.

### F2 — Postgres broadly network-reachable + stale firewall rules (CONFIRMED, infra)
psql-invoicellm-dev: publicNetworkAccess=Enabled, Burstable Standard_B2s, HA disabled. Firewall rules: AllowAllAzureIPs (0.0.0.0 to 0.0.0.0 — every Azure IP in every tenant/subscription can open a TCP connection), plus two leftover personal-IP dev rules temp-agent-access (122.167.112.115) and claude-session-access (122.167.116.167). Credentials are still required, but the network perimeter is effectively all of Azure plus two home IPs. Failure scenario: the DB credential plus any Azure-hosted host is enough to reach the DB directly; the stale /32 rules are unowned standing access that nobody is tracking.

### F3 — Live shared secret + partial API key committed in plaintext docs (CONFIRMED, secrets)
- apps/invoice-be/docs/be_features_tracker.md:264 — inbound URL with ?key=AdmInvoiceSecret2026.
- apps/invoice-be/docs/be_features_tracker.md:1414 — SENDGRID-INBOUND-SECRET = AdmInvoiceSecret2026 AND SENDGRID-API-KEY = SG.qiVVj3... (partial) in plaintext.
- apps/invoice-be/docs/feature_14_email_ingestion.md:88,103 — same AdmInvoiceSecret2026.
The secret is live and enforced (a wrong ?key= on POST /api/v1/email/mailintegration returns 401), which is exactly why its presence in git is a real exposure: anyone with repo or history read can post attacker-controlled invoices into ingestion. Failure scenario: leaked repo, attacker calls the inbound endpoint with the known key and injects invoice documents into a tenant pipeline. Runtime config is fine (the same secret is a Key Vault secretRef); the leak is confined to committed docs.

### F4 — Storage account TLS1_0 + open network default (CONFIRMED, infra)
stinvoicellmdev2: minimumTlsVersion=TLS1_0 (should be TLS1_2), publicNetworkAccess=Enabled, networkRuleSet.defaultAction=Allow (no IP restriction). Blob anonymous access is disabled (good), so this is transport-downgrade plus broad network reach on the invoice-PDF store, not anonymous read. Failure scenario: a downgrade-capable MITM against a client still permitted to negotiate TLS 1.0 to the invoice blob store.

### F5 — Connector management has no backend role check (CONFIRMED, RBAC)
routers/connectors.py — GET /auth-url/{provider}, GET /callback/{provider}, GET /files/{provider}, POST /import/{provider}, DELETE /{provider} all depend only on get_tenant_context (authentication), with no require_admin or permission gate. The FE reserves these controls to Admin (isAdmin), so the server is the only real gate and it is not enforcing one. All are tenant-scoped (no cross-tenant reach), so this is a within-tenant privilege gap, and the routes are externally reachable (connectors is in the website proxy allowlist). Failure scenario: a tenant non-Admin member (Auditor-only, or a NO_ROLE/Restricted user) calls DELETE /api/connectors/google_drive directly and disconnects the org Google Drive autopilot source — or POST /api/connectors/import/google_drive to force an ingestion — despite the UI hiding those actions.

### F6 — Ollama eval endpoint public but IP-locked (PLAUSIBLE, infra — confirm intent)
ca-ollama-eval-dev is external=true on port 11434 (Ollama has no native auth) but carries an ipSecurityRestrictions Allow-only rule for 122.167.116.167/32 and minReplicas=0. The IP allowlist is the sole control. Confirm the endpoint is still needed (Feature 23 eval tool) and the allowlisted IP is still the intended caller; if the tool is idle, remove external ingress entirely.

### F7 — Key Vault / Cognitive services internet-reachable, no purge protection (PLAUSIBLE, infra)
kv-invoicellm-dev: publicNetworkAccess=Enabled, enablePurgeProtection unset, RBAC-authz on (good). openai-invoicellm-dev and docintel-invoicellm-dev: publicNetworkAccess=Enabled, defaultAction=Allow. All credential or RBAC-gated and expected for a non-VNET dev box, but should close under the prod networkIsolation split. Purge protection off means a deleted secret can be permanently purged with no recovery window.

### F8 — ALLOWED_ORIGINS does not include the live custom domain (INFORMATIONAL, config)
BE ALLOWED_ORIGINS lists the two azurecontainerapps.io FQDNs, not https://invoicellm.admsofttech.com. Not a live hole (browser talks to the website origin; FE to BE is server-side; BE is internal), but stale relative to the real domain and worth correcting before any direct browser-to-BE origin is ever introduced.

## Blocked / not covered
- Live cross-tenant isolation probe and live RBAC role-boundary probe need a real inv_live_ key and real Clerk sessions for the two existing tenants; none were provided to this pass. Read-only scope precluded minting keys or creating synthetic tenant rows. Covered by source trace instead (see F5 and the positive confirmations). No synthetic tenant data was created.

## Final status
Completed within scope. 5 confirmed findings (F1–F5), 3 lower/informational (F6–F8). Two live-probe items blocked on missing test credentials, mitigated by code review. No writes performed.
