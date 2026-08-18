# senior-dev — support-contact branch punch list (Gap 249 holes + docs + P3)

Worktree: `C:/Users/S Banerjee/AppData/Local/Temp/claude/support-contact-fix`
Branch: `fix/support-contact-security-and-tenant-provisioning` (on top of `23c5780`)
Do not touch Gap 250 / 251 / 133 fixes. Leave everything uncommitted.

## P1
- [x] 1. Subject-length 500 — truncated to `_SUBJECT_MAX_LENGTH` at construction in `submit_contact_inquiry`. 3 regression tests; confirmed failing pre-fix (296 and 256 chars)
- [x] 2. `_get_client_ip` / `resolveClientIp` rewritten — rightmost XFF, `X-Client-IP` proxy contract, `X-Azure-ClientIP` gated on `FRONT_DOOR_ID`+`X-Azure-FDID`, `X-Real-IP` dropped, all candidates IP-validated. Topology verified against infra/ (Front Door exists on master but is gated off and undeployed)
- [x] 3. Backend limiter moved to Redis (shared across the 5 replicas, `EXPIRE`-bounded) with a bounded in-process fallback (prune-on-check + key cap, `OrderedDict` not `defaultdict`). Website proxy `Map` given the same pruning + cap. Per-instance caveat on the proxy layer documented in code + both trackers + feature doc

## P2
- [x] 4. `feature_19_support_tickets_and_notifications.md` §3.2 item 1 — "not rate-limited" replaced with what is actually built, incl. the fallback/per-instance caveat and the subject-truncation note
- [x] 5. `models.py` `SupportTicket` docstring — `INQ-YYYY-XXXX` → `INQ-YYYY-XXXXXXXX`, with the `secrets.token_hex(4)` / Gap 251 rationale
- [x] 6. `reports/security/2026-08-18-support-contact-endpoint.md` — remediation-status table added at top; findings left unedited below. Findings 5 and 6 recorded as deliberately deferred with reasons

## P3
- [x] 7. Honeypot now `console.warn`s trigger value, claimed name/email, user agent — client-facing response deliberately unchanged
- [x] 8. `signup/page.tsx` — `ProvisionError` carries status, `isTerminalProvisionFailure()` treats 409 as terminal, terminal copy points at sign-in/support, Retry button not rendered on 409

## Verify
- [x] Backend suite green: **674 passed, 4 skipped, 5 deselected**. (5 initial failures were my dummy-env missing `AZURE_STORAGE_CONNECTION_STRING`/Google creds, not regressions — confirmed by re-running those 3 files with the vars set: 41 passed)
- [x] `tsc --noEmit` clean on `invoice-website` (caught 2 real errors in my first draft — Map iteration under a pre-ES2015 target — since fixed)
- [x] Both regression tests confirmed to FAIL against pre-fix code, not just pass against the new
- [x] `be_features_tracker.md` Gap 249 rewritten: closed, with the proxy-layer per-instance limitation stated explicitly rather than glossed
- [x] Website tracker Gap 176 (409 handling) and Gap 249 proxy entry updated; `test_coverage_map.md` given 3 new rows

**Final status:** all 8 items done. Gap 249 = solid on the backend (Redis-shared, bounded, unspoofable key), with one documented caveat: the website proxy's own window remains per-instance and is wiped by scale-to-zero, by design — it is best-effort edge shedding, not the authoritative limit. Everything left uncommitted.
