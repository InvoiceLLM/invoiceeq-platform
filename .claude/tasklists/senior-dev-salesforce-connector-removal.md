# senior-dev — Salesforce connector removal (Gap 334 BE / Gap 322 FE)

Started and completed 2026-08-28. Founder decision: remove the Salesforce connector entirely.
Two root causes — (1) External Client App with Distribution State=Local structurally blocks
cross-org OAuth (`OAUTH_AUTHORIZATION_BLOCKED`, confirmed live against `ca-invoice-be-dev`),
(2) wrong data model — connector browsed Salesforce Libraries (ContentWorkspace), real invoices
live on Account/Opportunity records.

Ran as: Step 1 (Gap filing) → founder review gate → Steps 2-5 after authorization.

## Step 1 — Gap entries first (no code without gap)

- [x] Verify Gap number collision — BE tracker true max = **333** (`Gap 334` free; 332 unused/skipped), FE tracker true max = **321** (`Gap 322` free; the `322`/`330` hits in the FE file are cross-references to BE gaps inside entry bodies, checked individually, not assumed)
- [x] File **BE Gap 334** in `apps/invoice-be/docs/be_features_tracker.md`
- [x] Annotate BE **Gap 197** as superseded (one line appended, not deleted)
- [x] Annotate BE **Gap 98**'s two Salesforce sub-bullets as superseded
- [x] Annotate BE **Gap 261** / **Gap 262** as superseded
- [x] File **FE Gap 322** in `apps/invoice-fe/docs/fe_features_tracker.md`
- [x] Annotate FE **Gap 261** / **Gap 262** as superseded
- [x] **STOP gate — Gap texts reported, authorization received**

Gate resolutions received: `infra/THIRD_PARTY_INTEGRATIONS_SETUP.md` IS in scope (markdown, not
infra config); the 9 extra Salesforce-referencing files stay flagged-only; Gap entries stay `[ ]`
until real test/typecheck output exists.

## Step 2 — BE code

- [x] `utils/connector_files.py` — 4 SF functions + `SALESFORCE_API_VERSION` deleted (-132 lines); Drive functions byte-identical
- [x] `utils/connector_oauth.py` — `SALESFORCE_TOKEN_URL`, `generate_pkce_pair()` (**verified single caller first**), SF arm of `has_real_credentials`, `elif prov == "salesforce"` refresh branch, `instance_url` write-back; `base64`/`hashlib`/`secrets` imports went with PKCE
- [x] `queue_worker/handlers.py` — SF import + branch removed; `if not file_bytes` re-checked: an active connection on an unknown provider now fails loudly instead of falling through to the stub PDF, preserving Gap 180's intent
- [x] `services/autopilot_sync.py` — `SOURCE_TYPE_TO_PROVIDER` kept as 1-entry dict (vocabularies still differ — Gap 333), listing branch removed, **download collapsed to unconditional Drive** (not just else-arm deleted)
- [x] `routers/autopilot.py` — `valid_sources` + payload comment
- [x] `routers/connectors.py` — 5 handlers edited surgically (lists narrowed to `["google_drive"]`, kept in place), `status_map`, `mock_files`, PKCE plumbing, `state` param, `import redis` (**verified only PKCE used it**)
- [x] `config.py` — 3 SF settings + comment; infra-side wiring left alone and noted
- [x] `models.py` — comments only; `instance_url` kept with explicit DEAD-COLUMN note; migration `a7b8c9d0e1f2` untouched
- [x] `agents/support_agent.py` — keyword routing + 2 false "Salesforce is supported" claims (highest user-visible priority)

## Step 3 — BE tests

- [x] Re-pointed to `google_drive`, not deleted: `test_oauth_callback`, `test_list_files`, `test_handle_import_connector_file_outbound_no_azure`
- [x] Deleted: `real_salesforce_credentials` fixture, `test_salesforce_pkce_flow`, `test_oauth_callback_salesforce_verification_failure`
- [x] `pytest tests/test_connectors.py -v` — **15 passed**; `tests/test_autopilot.py` — **21 passed** (also affected). Combined re-run: **36 passed**. Both SQLite-backed by their own fixtures → **NOT Postgres evidence** per hard rule 2; functional-tester's Postgres checkpoint still required.

## Step 4 — FE code

- [x] `lib/connectorFolderShortcut.ts` type root + `STORAGE_KEYS` — changed atomically with `app/settings/connectors/page.tsx`
- [x] `components/connectors/IntegrationCard.tsx` — subtitle ternary flattened; `provider` prop **kept** (deviation, see below)
- [x] `components/ingestion/ConnectorBrowseBar.tsx` — `PROVIDER_META`/`ALL_PROVIDERS` reduced to 1 entry, **map/loop shape kept** (deviation, see below)
- [x] `app/ingestion/page.tsx` — "Cloud Source" toggle block deleted entirely; provider ternary → named const
- [x] `components/ingestion/AutopilotHistoryTable.tsx` — SF ternary arm removed; historical rows fall through to "Manual"
- [x] `app/help/content/autopilot-guide.tsx` (3 mentions), `app/settings/page.tsx` copy
- [x] `e2e/autopilot-folder-browser.spec.ts`, `e2e/gaps-282-284-286.spec.ts` — **chip-count assertion re-checked: none exists**, the status stub is incidental setup for a log-terminal test
- [x] `app/api/connectors/*/[provider]/route.ts` proxies left functional (one stale comment corrected only)
- [x] `npx tsc --noEmit` — **clean, exit 0**

## Step 5 — Docs — annotate/strike, never delete (hard rule 4)

- [x] `apps/invoice-be/docs/feature_9_connectors.md` — removal banner + strike-through across File Coordinates, Functionality, Tasks 9.2/9.5, Gap 98, Verification Plan
- [x] `apps/invoice-fe/docs/feature_7_connectors.md`
- [x] `infra/THIRD_PARTY_INTEGRATIONS_SETUP.md` — title, §3, Connected App section struck + "DO NOT PERFORM", custom-domain Step 4, params snippet
- [x] `docs/architecture/Technical_Architecture_Document.md`, `docs/architecture/Database_Schema_Document.md`
- [x] `apps/invoice-fe/docs/feature_13_autopilot.md`
- [x] `apps/invoice-be/Backend_Code_Layout_Document.md`
- [x] `feature_2_pipeline_extraction.md`, `feature_3_ingestion.md`, `feature_3.1_vendor_flow_ingestion.md`
- [x] `website_features/feature_6_custom_domain_integration.md` — SF callback URL cutover step struck as no-longer-a-task
- [x] Both Gap entries flipped `[ ]` → `[x]` with real file-by-file results and real test/typecheck output

## Out of scope (verified untouched)

`infra/` bicep/params/workflows (only the `.md` guide was edited), any `az` command, migration
`a7b8c9d0e1f2`, `TenantConnection`/`TenantAutopilotConfig` rows. The `SALESFORCE-CLIENT-SECRET`
Key Vault secret and `SALESFORCE_*` container env vars still deploy and are now inert — documented
in the setup guide, left for a separate founder-gated infra pass.

## Deviations from the plan (all deliberate, all recorded in the Gap entries)

1. **`IntegrationCard`'s `provider` prop kept**, not deleted. The subtitle ternary was flattened,
   but the prop still names which provider a card represents; keeping it means a second provider
   needs no signature change.
2. **`ConnectorBrowseBar`'s map/loop kept at N=1.** Flattening to one hardcoded chip would have
   destroyed FE Gap 113's behaviour (always render every provider, Active *or* locked with a
   "Connect in Settings" link).
3. **`SOURCE_TYPE_TO_PROVIDER` kept as a 1-entry dict.** The `gdrive`/`google_drive` vocabularies
   are still independent (Gap 333); an unknown `source_type` must still fail loudly.
4. **2 extra tests fixed beyond the 3 named.** `test_connectors_status_not_configured` /
   `test_connectors_status_active` asserted on the removed `salesforce` status key and would have
   `KeyError`'d. Now `assert "salesforce" not in data`, which guards the removal.
5. **3 stale prose comments** naming Salesforce, in files already being edited (`config.py`,
   `routers/autopilot.py`, `services/autopilot_sync.py` docstring).
6. **`agents/support_agent.py` has zero test coverage** (confirmed by grep) — the highest
   user-visible edit is verified by diff reading only. Pre-existing gap, named not hidden.

## Final status

**Complete.** 34 files changed (+385/−610). BE: `pytest tests/test_connectors.py tests/test_autopilot.py`
→ **36 passed** (SQLite, not Postgres — checkpoint still owed to functional-tester). FE:
`npx tsc --noEmit` → **clean, exit 0**. Playwright specs had their mocks updated but were **not
executed** (needs a live dev server) — not claimed as verification. All changes left uncommitted.
