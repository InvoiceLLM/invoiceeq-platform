# functional-tester: invoice-website E2E suite — task list

## Already done (verified at task start)
- [x] `playwright.config.ts` + `playwright.proxy.config.ts` exist
- [x] `@playwright/test` installed, `package.json` has `test:e2e`/`test:e2e:proxy`/`test:e2e:all`
- [x] `website_features/test_coverage_map.md` exists (stub only, needs real numbers)
- [x] 5 spec files exist in `e2e/`: billing-success, billing-failed, billing-payu-relay, billing-proxy-mode, smoke

## Remaining work
- [x] Read CONVENTIONS.md
- [x] Create this tasklist
- [x] Inspect existing spec files + config
- [x] Confirm run prerequisites (webServer auto-starts `next dev`; no docker stack needed — pure server-component/route tests, no DB/backend dependency)
- [x] Root-caused and fixed a real environment blocker (NOT an app bug): this machine's Windows Device Guard/WDAC policy blocks Playwright's bundled `chrome-headless-shell.exe` (`spawn UNKNOWN` from Node; confirmed directly via `cmd /c chrome-headless-shell.exe --version` -> "was blocked by your organization's Device Guard policy"). System Google Chrome is NOT blocked. Fixed by adding `channel: "chrome"` to `playwright.config.ts`'s chromium project `use` block (test-infra config, functional-tester's scope).
- [x] Cleaned up leftover/duplicate node+playwright+dev-server processes from prior interrupted sessions (port 3200 conflicts)
- [x] Re-ran `npm run test:e2e` after the fix — **34/34 passed clean, 3.0m** (`test_e2e_run3.log`). All 3 tests flagged in the task brief as previously-failing (billing-payu-relay unconfirmed-messaging case, billing-success FE-origin-paths case, smoke landing-nav-links case) passed on this clean run — their test-results/ artifacts were stale from an earlier already-fixed diagnosis (visible in the specs' own code comments), not live bugs.
- [x] Ran `npm run test:e2e:proxy`
- [ ] Triage any remaining failures: test-authoring bug (fix) vs. real app bug (log new Gap, do NOT fix app code)
- [ ] Write real run evidence to `website_features/test_evidence/`
- [ ] Populate `test_coverage_map.md` with real pass/fail numbers + links to evidence
- [x] smoke.spec.ts already covers landing/pricing-section/login rendering — confirmed sufficient, no dedicated `/pricing` route exists separately
- [ ] Final report to user
