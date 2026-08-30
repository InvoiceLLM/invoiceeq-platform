# senior-dev — Website Feature 7: Plug & Play Workflows (marketing surface)

Scope: `apps/invoice-website` only. Fixture-driven marketing preview of BE Feature 25 / FE Feature 17.
No BE/FE files touched. No real workflow logic, no network calls from any new component.

- [x] 1. Read CONVENTIONS, active-work, website tracker, existing spec precedent (`feature_6_custom_domain_integration.md`)
- [x] 2. Read `Hero.tsx` (627 lines / 9 useState — ground truth confirmed) + `app/page.tsx` + founder-approved mockup in full
- [x] 3. Re-verify gap numbers — **188–191 were NOT free**, all four are real closed BE entries. Repo max = 334; 335–344 reserved for in-flight BE F25 / FE F17. **Taking 345–348.**
- [x] 4. Write `website_features/feature_7_plug_and_play_workflows.md` (STATUS: IMPLEMENTING)
- [x] 5. File tracker Feature 7 index line + Gaps 345–348 in `website_features_tracker.md`
- [x] 6. Task 7.1 — `HeroModeTabs.tsx` built. Placed after the CTA row, not literally under the badge (would break Gap 163's headline block); matches the mockup's own DOM order. **Introduces a fold regression: y≈640 → y≈971 at 1440×700 — founder decision needed.**
- [x] 7. Task 7.2 — `status` widened with `AUDIT_REQUIRED`, `FRT-1048` replaced with a real price-variance sample, 5 alert render branches. Also split `riskScore` out of `confidence` (stage 3 was showing extraction precision labelled as a risk score).
- [x] 8. Task 7.3 — `SageChatPreview.tsx` built; answers written to agree with 7.2's fixture, not invented separately.
- [x] 9. Task 7.4 — `WorkflowRecipeSelector.tsx` built, 4 steps, CTA → `/signup` with the Gap 340 TODO in-code.
- [x] 10. Wired into `app/page.tsx`; recipe selector before pricing rather than under SAGE, commented in-file.
- [x] 11. Verified: `tsc --noEmit` clean; `next build` clean (13 routes, `/` 17.2→21.9 kB); Playwright 39 passed / 1 failed, failure **proven pre-existing** by stashing only my paths and re-running on baseline; headless-Chrome behavioural run over all 4 gaps; network watch → 1 request total (Next RSC prefetch of `/signup`), **0 `/api/` calls**.
- [x] 12. Spec body + §6 verification filled with real output; tracker Gaps 345–348 updated (345 `[~]`, 346/347/348 `[x]`, Feature 7 index `[~]`); README updated.

Final status: **complete, with two things deliberately left open and flagged rather than papered over** — (1) the above-the-fold regression from Task 7.1 needs a founder call (3 options in the spec §6); (2) no Playwright spec covers any of the 3 new components. Changes left uncommitted.
