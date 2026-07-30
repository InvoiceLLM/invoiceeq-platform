# Feature 7: Third-Party Connectors & Explorer View

Build integration connection toggles, folder navigation trees, and bulk file import controls.

**Corrected 2026-07-30**: this doc previously claimed Tasks 7.1/7.2 and all their files were "not yet created" — that was stale. All three files already existed on master (landed in an earlier commit, `7cc9186`) and are now functionally correct end-to-end after two real fixes (see Task 7.1 below and Gap 98 in `fe_features_tracker.md`).

### Navigation
The **admin connects once** under **Settings → Connectors** (`IntegrationCard.tsx` grid) — this is a tenant-wide connection (`TenantConnection` has no per-user column), not something each user sets up individually. A **normal user then browses/imports from the Ingestion tab**, not Settings — `components/ingestion/ConnectorBrowseBar.tsx` shows an icon per provider that's Active, on both the Receiving and Sending sub-tabs, and opens `FolderTreeExplorer.tsx` in a modal scoped to that tab's direction (`inbound`/`outbound`). This resolves an earlier open question in this doc about which screen owns file-browsing.

### Theme & Styling Specifications
* Connector cards: `bg-[#151B26] border border-[#222D3D] rounded-xl p-4`.
* Status badge: Connected `bg-[#10B981]/15 text-[#10B981]`, Disconnected `bg-slate-800 text-slate-400`.
* File Tree node folder rows: `hover:bg-[#1E293B] cursor-pointer rounded px-2 py-1 text-slate-300 transition-colors`.

### File Coordinates
* Connectors Page (admin, one-time setup): [apps/invoice-fe/app/settings/connectors/page.tsx](file:///c:/Users/S%20Banerjee/Desktop/Invoice_LLM/Prod_Invoice_LLM/apps/invoice-fe/app/settings/connectors/page.tsx)
* Integration Card Grid: [apps/invoice-fe/components/connectors/IntegrationCard.tsx](file:///c:/Users/S%20Banerjee/Desktop/Invoice_LLM/Prod_Invoice_LLM/apps/invoice-fe/components/connectors/IntegrationCard.tsx)
* Explorer Component (reused by both Settings and Ingestion): [apps/invoice-fe/components/connectors/FolderTreeExplorer.tsx](file:///c:/Users/S%20Banerjee/Desktop/Invoice_LLM/Prod_Invoice_LLM/apps/invoice-fe/components/connectors/FolderTreeExplorer.tsx)
* Ingestion Browse Bar (normal user, per-tab): [apps/invoice-fe/components/ingestion/ConnectorBrowseBar.tsx](file:///c:/Users/S%20Banerjee/Desktop/Invoice_LLM/Prod_Invoice_LLM/apps/invoice-fe/components/ingestion/ConnectorBrowseBar.tsx)
* Proxy Routes: `app/api/connectors/{status,auth-url,callback,files,import}/route.ts` — all present. `callback/[provider]/route.ts` needed a redirect-aware rewrite (2026-07-30): it used to proxy via `proxyJson`, which follows redirects server-side and would have relayed the wrong response; now uses `redirect: "manual"` and forwards the Location header as a real browser redirect.
* Backend endpoints: `get_connectors_status()`, `get_auth_url()`, `oauth_callback()`, `list_connector_files()`, `trigger_file_import()` — Google Drive does real OAuth + real file listing/download as of 2026-07-30, see `docs/feature_9_connectors.md`.

### Tasks
- `[x]` **Task 7.1: Build Integration Cards Grid** — done, plus one real bug found and fixed 2026-07-30: `handleConnect()` never redirected the browser to the real OAuth consent screen — it faked the authorization code client-side (`mock_code_for_${provider}`) and called the callback directly. Harmless while the backend was also fully mocked; would have actively broken the moment the backend started doing real token exchange (Feature 9, Gap 98), since Google/Salesforce would reject a fabricated code. Fixed: `handleConnect` now does `window.location.href = auth_url`; a confirmation banner reads `?connected=` after the round trip.
- `[x]` **Task 7.2: Code Directory Folder Explorer** — done; already correctly wired to the real endpoints, no bug found here. Now also mounted from the Ingestion tab (`ConnectorBrowseBar`), not just Settings.
- `[x]` **Task 7.3: Implement Bulk Import Trigger** — done (`FolderTreeExplorer`'s "Import Selected Files" button).

### Verification Plan
* **Manual Verification**: Settings → Connectors → Connect (real Google login now required — no more fake-code shortcut) → status flips Active → go to Ingestion (Receiving or Sending) → the Google Drive icon appears under "Load from:" → browse/select/import.
* **Automated**: FE `npx tsc --noEmit` and `npm run build` both clean as of 2026-07-30; backend contract covered by `tests/test_connectors.py` (14 tests).
