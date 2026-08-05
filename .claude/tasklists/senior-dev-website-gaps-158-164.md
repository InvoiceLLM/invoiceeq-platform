# senior-dev — website Gaps 158/159/161/163/164 (2026-08-05)

Scope: `Prod_Invoice_LLM/apps/invoice-website/` only. No invoice-fe/invoice-be changes. No commit/push.

- [x] Read source files (AITeamSection, Header, forgot-password, Hero, login)
- [x] Gap 158 — removed `cursor-pointer` from `AgentCard` in `components/marketing/AITeamSection.tsx` (file's only occurrence); computed cursor now `auto`
- [x] Gap 159 — route-based active nav state in `components/marketing/Header.tsx`: `isActive()` on `usePathname()` + tracked hash, `NAV_ACTIVE`/`NAV_IDLE` + `aria-current`, applied to all 4 desktop links and the mobile drawer; hardcoded cyan on Architecture Flow removed (Live badge kept)
- [x] Gap 161 — `app/forgot-password/page.tsx`: `autoComplete` email / one-time-code / new-password + `name` + `inputMode` on all three inputs
- [x] Gap 163 — Hero rebuilt: serif single-line headline, one-line subhead, 1 CTA + scroll cue, `FlowNode` flow diagram w/ AI Engine ring + `AGENT_LEGEND`, sample-invoice result card, trust row. Logotype refined in `Header.tsx` (Hero has no wordmark). `onOpenFlowsModal` dropped from Hero; `app/page.tsx` updated. `#pipeline-demo` untouched.
- [x] Gap 164 — Login tab switcher (`mode` state + `tabBtnStyle`) in `app/login/page.tsx`; generic "Get started" header, Sign In (blue) / + Create Organisation (green) tabs, create pane w/ agreed copy → `/signup`; old divider + signup link removed
- [x] Build / typecheck — `tsc --noEmit` clean, `next build` clean, Playwright 34/34 pass
- [x] Visual verification — headless Chrome: headline 1 line at 1024/1280/1536/1920 no overflow; hero block ends y≈640 at 1440x700; login tab row at y≈274, signin card 692px, create pane 551px; agent cursors `auto`; nav `aria-current` exactly one active at a time
- [x] Tracker: 158/159/161/163/164 → `[x]`; 160 + 162 closed as superseded by 164
- [x] Feature docs: `feature_1_landing.md` (Tasks 1.2/1.3), `feature_2_showcase.md` (Task 2.4), `feature_4_auth_gateway.md` (Functionality 2 + 6)
- [x] `e2e/smoke.spec.ts` assertions updated for the new login structure and logotype

Status: complete. All changes left uncommitted.
