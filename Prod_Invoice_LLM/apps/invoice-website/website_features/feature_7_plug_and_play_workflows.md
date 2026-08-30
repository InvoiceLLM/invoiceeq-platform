# Feature Website 7: Plug & Play Workflows — Marketing Surface & Sandbox Onboarding

**STATUS: BUILT (2026-08-29) — typechecked, built and behaviourally verified; one open design regression, and no automated test coverage.** All four tasks are implemented and exercised; §6 carries the real commands and real output. Two things are deliberately *not* claimed: (1) the hero no longer fits one 700 px viewport, a property Gap 163 had verified — see §6 "Open regression", founder call needed; (2) no Playwright spec covers any of the three new components, so nothing here is protected against regression.

Status of record lives in `website_features_tracker.md` (Gaps 345–348); this doc is the design record. Each task below carries its own `[ ]`/`[~]`/`[x]` and is only ticked once the code exists **and** the verification named in §6 has actually been run.

**Update 2026-08-30 — Task 7.5 / Gap 350 added.** BE Gap 340 (sandbox `inv_test_` keys) shipped, so Task 7.4's CTA has been retargeted from `/signup` to a real "Get Sandbox API Key" button, and the claim step has been wired into `app/signup/page.tsx`. This is the **anonymous-visitor half** only; the logged-in Admin's widget-token UI is FE Feature 17. Verified against a real backend and real Postgres in all three feature-flag states (§6); **not** verified through a full real-Clerk signup, which this environment cannot complete. §7's fixture contract is amended — not dropped — because this is the first component in the feature that makes a network call.

**Update 2026-08-30 (functional-tester final gate) — the "no automated test coverage" caveat above is now closed.** `e2e/plug-and-play-homepage.spec.ts` (11 tests, default config) and `e2e/sandbox-key-cta-enabled.spec.ts` (3 tests, new `playwright.sandbox.config.ts`) cover `HeroModeTabs`, the Gap 346 SENTINEL sample, `SageChatPreview`, `WorkflowRecipeSelector` and both `SandboxKeyCta` flag states. Full existing suites re-run clean in isolation (50/51 default, the 1 failure being the same pre-existing `billing-payu-relay.spec.ts` flake this doc's own §6 already root-caused; 6/6 proxy config; 3/3 sandbox config). The **§6 "Open regression"** (hero no longer fits one 700px viewport) is unaffected by this pass and remains open for a founder call. See the Verification Plan's new subsection at the end of §6 for commands and detail.

**Target application:** `apps/invoice-website` only. `apps/invoice-be` and `apps/invoice-fe` are explicitly out of scope for this feature — see §1. (Task 7.5 reads the backend's code and calls its endpoints; it modifies nothing in it.)

---

## 1. Overview & Objective

This feature is a **marketing surface only**. It implements no workflow logic, no sandbox provisioning, no API-key issuance, and no chat backend. Everything it renders is driven by local TypeScript fixtures inside `apps/invoice-website`.

The product capability it previews — "plug the engine into what you already run" (email in, Drive watch, REST API, webhooks out; audit level; chat access) — is scoped separately as **BE Feature 25** and **FE Feature 17**, both being built in parallel by other agents. Nothing in this feature depends on either landing, and nothing here should be read as evidence that either has shipped. The single point of coupling is Task 7.4's CTA, which deliberately points at the already-live `/signup` route rather than at a sandbox-key endpoint that does not exist yet (see §5.4).

> **Superseded in part, 2026-08-30 (Task 7.5 / Gap 350) — the paragraphs above are Gaps 345–348's accurate record and are left standing.** Two claims are no longer true of the feature as a whole:
>
> 1. **"marketing surface only … no sandbox provisioning, no API-key issuance"** — Task 7.5 issues real sandbox API keys and claims real sandbox workspaces. It still implements no *workflow logic* and no *chat backend*, and it still provisions nothing itself: both new route handlers are thin relays to BE Gap 340's endpoints. The rendering of the recipe wizard, the SAGE preview, the mode tabs and the pipeline demo is still 100% local fixtures.
> 2. **"the single point of coupling is Task 7.4's CTA … a sandbox-key endpoint that does not exist yet"** — it exists now (BE Gap 340, built 2026-08-30) and that CTA calls it. The coupling is real, and it is guarded: the CTA is not rendered at all unless `NEXT_PUBLIC_SANDBOX_KEYS_ENABLED` is explicitly turned on, and if it is on while the backend's own `SANDBOX_KEYS_ENABLED` is off, the visitor gets a plain "not available yet" line instead of a dead button or an error. See §5 Task 7.5.

Why the marketing site gets this first: today's homepage tells exactly one story — "sign up and use the web application." A visitor who already runs their own AP tooling and only wants the extraction/audit engine behind it has no on-page signal that this is possible; that story currently only exists inside the Architecture Flow modal, behind a click. This feature adds that second story to the same hero, in the same visual language, without a new page and without displacing the existing web-app narrative.

### Design reference

A founder-approved static HTML/CSS/JS mockup was reviewed before implementation (`plug-and-play-homepage-mockup.html`, session scratchpad — **not committed to this repo**, same convention as the Gap 163/164 mockups). It is a visual reference for colour, layout ordering and copy tone only. Its vanilla-JS behaviour (`setMode`, `setSample`, `showSage`, `pick`, global `document.getElementById` mutation) was **not** ported — every interaction here is reimplemented as React state inside this app's existing component patterns. Where the mockup and the final brief disagree, the brief wins; the two known divergences are recorded in §5.2 and §5.4.

---

## 2. Ground truth at design time (verified against real code, 2026-08-29)

Recorded because this repo has been bitten before by specs written against stale doc claims. Each of these was read out of the actual file, not inferred from another doc:

| Fact | Where |
|---|---|
| `Hero.tsx` is **627 lines** and holds **9 `useState` hooks** (`selectedInvoice`, `activeStep`, `inspectorTab`, `isProcessing`, `rotateX`, `rotateY`, `scrollTiltX`, `scrollScale`, `isHovered`) | `components/marketing/Hero.tsx` |
| `SampleInvoice.status` is the closed union `"VERIFIED" \| "MATCHED" \| "AUDITED"` — **no alert/exception variant exists** | `Hero.tsx:26` |
| All 3 entries in `SAMPLE_INVOICES` are clean: every `rawJson` carries `routing: "AUTOMATED_APPROVAL"`, consensus 0.994–0.999 | `Hero.tsx:31–113` |
| The pipeline demo is a 4-stage animation driven by `activeStep` (0→3, 600 ms interval in `runLiveSimulation`), and the inspector is a 2-tab `inspectorTab` (`"SUMMARY" \| "JSON"`) | `Hero.tsx:191–206`, `Hero.tsx:430–606` |
| The eyebrow badge ("AI-Powered Finance Workspace") sits at `Hero.tsx:222–225`, directly above the `<h1>` | `Hero.tsx:222` |
| Homepage section order is `Hero → FlowsShowcaseSection → AITeamSection → WorkspaceShowcase → PricingTable → BenefitsStrip` | `app/page.tsx:37–42` |
| This app has no test runner other than Playwright (`test:e2e`, `test:e2e:proxy`); there is no unit-test harness | `package.json` |

### Colour tokens this feature must match (read out of `Hero.tsx`, not invented)

`#050816` console/background · `#3B82F6` blue · `#22D3EE` cyan · `#8B5CF6` violet · `#10B981` emerald · `#94A3B8` dim text · `#64748B` faint text · `rgba(255,255,255,0.08)` borders · `backdrop-blur-md` glass cards. The alert state introduced in Task 7.2 adds **`#F43F5E` rose** (and `#FDA4AF`/`#FECACA` for warning text), which is the one token not already present in `Hero.tsx` — it is taken from the approved mockup and is consistent with the `rose-500/80` traffic-light dot already used in the console header bar (`Hero.tsx:404`).

---

## 3. Component extraction plan

`Hero.tsx` is already 627 lines with 9 hooks. Nothing in this feature may be inlined into it beyond the minimum that genuinely belongs to the existing pipeline demo:

| New component | Owns | Why it is not in `Hero.tsx` |
|---|---|---|
| `HeroModeTabs.tsx` | The 2-tab switcher and both capability panels | Self-contained; one `useState`, no coupling to the pipeline demo's state |
| `SageChatPreview.tsx` | 3 prompt chips + canned answer rendering | Its own fixture + its own selection state; sits below the demo as a sibling section |
| `WorkflowRecipeSelector.tsx` | The 4-step wizard + live summary + CTA | Its own multi-key selection state; a page-level section, not hero content |

Only **Task 7.2** edits `Hero.tsx`, because widening `SampleInvoice.status` and rendering a discrepancy branch are changes to the existing demo's own type and render tree — extracting them would split one interaction model across two files for no benefit.

---

## 4. File Coordinates

### 4a. Exists today — will be modified

| File | Real symbol touched | Change |
|---|---|---|
| `components/marketing/Hero.tsx` | `interface SampleInvoice` (line 19), field `status` (line 26) | Widen the union with an alert variant; add optional `discrepancy` field |
| `components/marketing/Hero.tsx` | `const SAMPLE_INVOICES` (line 31) | Replace the `FRT-1048` entry with a discrepancy version |
| `components/marketing/Hero.tsx` | `export function Hero()` — stage-4 tile (line 483) and the "Active Sample" status pill (line 507) | Status colour/label branches on the alert state instead of being hardcoded emerald |
| `components/marketing/Hero.tsx` | `export function Hero()` — inspector left panel (line 504) | New conditional discrepancy warning card |
| `app/page.tsx` | `export default function Home()` (line 13) | Render the 3 new components in the agreed order |
| `website_features/website_features_tracker.md` | Feature Tracker list + Open Items | Feature 7 index line, Gaps 345–348, Gap 350 |
| `README.md` | "Key Pages & Sections", "Directory Structure" | Document the 3 new components |

### 4c. Task 7.5 / Gap 350 — added 2026-08-30, once BE Gap 340 shipped

Modified:

| File | Real symbol touched | Change |
|---|---|---|
| `components/marketing/WorkflowRecipeSelector.tsx` | `WorkflowRecipeSelector()` — the CTA slot inside the summary box | The `<Link href="/signup">` and its "retarget once Gap 340 ships" block comment are replaced by `<SandboxKeyCta />` |
| `app/signup/page.tsx` | `completeSignupAndProvision()`, `handleRetryProvision()`, the reveal screen's header | New `claimSandboxWorkspace()` call **before** `provisionTenant()`; new `sandboxClaim` state; reveal copy branches on it |
| `app/api/contact/route.ts` | `isValidIp()`, `resolveClientIp()` | **Moved out** to `lib/clientIp.ts` and imported back. Behaviour identical — the functions were relocated, not rewritten |
| `.env.local.example` | — | Documents `NEXT_PUBLIC_SANDBOX_KEYS_ENABLED` |

New:

| File | Exported symbol | Purpose |
|---|---|---|
| `app/api/sandbox/keys/route.ts` | `POST()` | Anonymous relay to `POST /api/v1/sandbox/keys`. Own edge rate-limit bucket; server-built `X-Client-IP`; backend 404 → `code: "sandbox_disabled"` |
| `app/api/sandbox/claim/route.ts` | `POST()` | Authenticated relay to `POST /api/v1/sandbox/claim`, modelled on `/api/auth/provision` |
| `lib/clientIp.ts` | `isValidIp()`, `resolveClientIp()` | The single trusted-IP answer, now shared by both public relays |
| `lib/sandboxKey.ts` | `storeSandboxKey()`, `readStoredSandboxKey()`, `clearStoredSandboxKey()`, `SANDBOX_KEYS_ENABLED` | The localStorage bridge between anonymous issuance and later signup |
| `components/marketing/SandboxKeyCta.tsx` | `SandboxKeyCta()` | The CTA, its four outcome states, and the shown-once reveal |

### 4b. New — no such file or function exists today

| File | Exported symbol | Purpose |
|---|---|---|
| `components/marketing/HeroModeTabs.tsx` | `HeroModeTabs()` — **new**, nothing of this name exists | 2-tab switcher; `WEB_APP_CAPABILITIES` / `PLUG_PLAY_PRIMITIVES` fixtures |
| `components/marketing/SageChatPreview.tsx` | `SageChatPreview()` — **new** | 3 pre-seeded prompts; `SAGE_PREVIEW` fixture (answer + SQL + citations) |
| `components/marketing/WorkflowRecipeSelector.tsx` | `WorkflowRecipeSelector()` — **new** | 4-step recipe wizard; `RECIPE_STEPS` fixture; live summary; `/signup` CTA |

*(Table split deliberately: an entry in 4b names a symbol that does not exist yet and must not be mistaken for a real function that can be called or grepped today.)*

---

## 5. Functionality / Tasks

### `[x]` Task 7.1 — Gap 345: two-mode hero switcher (`HeroModeTabs.tsx`)

**Built.** New `components/marketing/HeroModeTabs.tsx` exporting `HeroModeTabs()`, plus a local `CapabilityTile` presentational component and two fixtures, `WEB_APP_CAPABILITIES` (3 entries) and `PLUG_PLAY_PRIMITIVES` (4 entries). One piece of state, `mode: "app" | "plug"`.

- **"Complete Web Application"** (default) — SENTINEL Review Console / Spend Analytics / Team Roles, as a 3-up grid.
- **"Plug & Play Engine"** — Email In / Drive Sync / REST API / Webhooks, as a 4-up grid (2-up on mobile).
- Semantics: real `role="tablist"` / `role="tab"` with `aria-selected` and `aria-controls`, and `role="tabpanel"`/`aria-labelledby` on each panel — the inactive panel is unmounted, not hidden, so only one panel exists in the DOM at a time.
- Tokens taken from `Hero.tsx` verbatim: `rgba(255,255,255,0.08)` borders, `bg-white/[0.03]` + `backdrop-blur-md` glass tiles, `#3B82F6`/`#22D3EE`/`#8B5CF6`/`#10B981` icon accents, `#64748B` blurb text. The active tab uses the `from-[#3B82F6]/25 to-[#8B5CF6]/25` gradient plus an inset ring, matching the mockup's `.switcher button.active`.

**Deviation from the brief — placement.** The brief and the mockup callout both say "directly under the eyebrow badge". It was placed one block lower, after the CTA row and before the before/after transform. Inserting it literally between the badge and the `<h1>` would separate the badge from the headline it labels and break up the single-line serif headline block that Gap 163 was specifically designed and measured around. This position also matches the approved mockup's **own DOM order** (badge → headline → sub → switcher → capability panels → demo), so it follows the approved visual rather than the looser prose. Measured order confirmed at 1440×900: badge `y=104` < mode tabs `y=410` < `#pipeline-demo` `y=1044`.

**Known consequence, not silently absorbed — see §6 "Open regression".** Adding ~330 px of hero content pushes the above-the-fold block past the one-viewport height Gap 163 verified.

### `[x]` Task 7.2 — Gap 346: real SENTINEL discrepancy sample in the pipeline demo

**Built,** in `components/marketing/Hero.tsx`. This is a type change plus five render branches, not a data row:

1. **Type widened.** `SampleInvoice.status` is now `"VERIFIED" | "MATCHED" | "AUDITED" | "AUDIT_REQUIRED"`. New optional `discrepancy?: SampleDiscrepancy` (`title` / `detail` / `lineItem`) and a new optional `flagged?: boolean` on each `taxBreakdown` row. New module-level predicate `isFlagged(invoice)`, and one derived `sampleFlagged` const inside `Hero()` so every alert branch reads from a single source and cannot disagree with the others.
2. **`riskScore` split out from `confidence`.** Previously stage 3 rendered `Risk Score {selectedInvoice.confidence}` — the same number that the inspector labels "Field Precision". Those are different things, and this sample is precisely the case that proves it: the document was perfectly legible (99.4% extraction precision) and SENTINEL still held it (61.2% risk score). One shared field could not express that, so `riskScore: string` was added to the interface and set on all three samples; stage 3 now reads `riskScore`, the inspector still reads `confidence`.
3. **`FRT-1048` replaced** (rather than a 4th sample added — the demo's chip row is already tight, and the point is that one of the samples you can pick does *not* sail through). Global Freight Logistics, $18,750.50, PO-91042, now 3 line items, `status: "AUDIT_REQUIRED"`, `consensus_score: 0.612`, `routing: "HOLD_FOR_REVIEW"`, and a real `exceptions` array in `rawJson` (`PRICE_VARIANCE`, observed 5200.00 vs `vendor_90d_average` 3880.60, 34%). The `taxBreakdown` was rewritten so the three rows actually sum to $18,750.50 and the flagged row is the "Freight Surcharge" the warning names.
4. **Render branches** — all in the alert palette (`#F43F5E` with `#FDA4AF`/`#FECACA` text, the one token not already in `Hero.tsx`; consistent with the `rose-500/80` console dot at `Hero.tsx:404`):
   - sample-selector chip renders rose with an `AlertTriangle`, so the exception case is signposted before you click it;
   - stage 3 "SENTINEL Review" turns rose instead of violet and shows `Risk Score 61.2%`;
   - stage 4 relabels to **"4. Held for Review" / "Routed to an auditor"** instead of "Verified Result / Ready for Approval";
   - the "Active Sample" status pill turns rose;
   - a new warning card in the left inspector panel, gated on `selectedInvoice.discrepancy && activeStep >= 2` — i.e. it appears when the 4-stage animation reaches SENTINEL (stage 3 = index 2), the stage that produced it, so the warning lands in step with the animation rather than ahead of it;
   - the flagged `taxBreakdown` row renders rose with an inline `AlertTriangle`, so the table and the callout agree.
5. **The clean samples are unchanged** and still render exactly as before (verified — see §6).

### `[x]` Task 7.3 — Gap 347: SAGE chat preview widget (`SageChatPreview.tsx`)

**Built.** New `components/marketing/SageChatPreview.tsx` exporting `SageChatPreview()`, backed by the module-level `SAGE_PREVIEW: SagePreviewExchange[]` fixture (`prompt` / `answer` / `sql` / `citations`). One piece of state, `activeIndex: number | null` — before any click the answer pane does not exist at all, only a one-line prompt.

Three chips, with copy written for this product rather than ported from the mockup's `SAGE_A` array (the mockup's shape — answer + SQL + citation pills — was kept; its wording was not):

| Chip | Answer grounded in |
|---|---|
| "What did we spend on software last month?" | SUB-7721, INV-9842, INV-9810 |
| "Which invoices are still held for review?" | FRT-1048, DUP-2201, DUP-2202 |
| "How did Q2 vendor costs compare to Q1?" | FRT-1048, FRT-1102 |

The second chip is deliberately written to agree with Task 7.2's fixture — it names Global Freight Logistics, $18,750.50 and the same 34% variance, and its SQL filters on `routing = 'HOLD_FOR_REVIEW'`, which is the exact value in that sample's `rawJson`. The demo and the chat preview tell one consistent story rather than two unrelated made-up ones.

SQL is rendered multi-line in a `#050816` console block in `#10B981`; citations render as `#22D3EE` pills with a paperclip. Violet framing (`#8B5CF6`) throughout, matching SAGE's existing colour in `AITeamSection.tsx` and the "SAGE Ready" chip in `Hero.tsx`.

**Zero network calls** — see §7. Verified empirically, not just asserted (§6).

### `[x]` Task 7.4 — Gap 348: "Choose Your Workflow" recipe selector (`WorkflowRecipeSelector.tsx`)

**Built.** New `components/marketing/WorkflowRecipeSelector.tsx` exporting `WorkflowRecipeSelector()`, driven by the `RECIPE_STEPS: RecipeStep[]` fixture and a `DEFAULT_SELECTION` derived from each step's first option (so the summary line is never empty or half-formed).

**Four steps, not the mockup's three** — Chat Access was added to match the final wizard definition, so a visitor's selection here covers the same surface the real Feature 25 wizard will ask about:

| # | Step | Options |
|---|---|---|
| 1 | Input Channel | Dedicated Email Address · Google Drive Folder · Developer REST API |
| 2 | Audit Level | Full Auto-Pilot · Review Flagged Only · Strict Human Review |
| 3 | Output Destination | Real-time Webhook · Emailed CSV / JSON · Google Drive Archive |
| 4 | Chat Access | SAGE Chat Enabled · Pipeline Only |

Each option carries both a `label` (what the button says) and a `summaryLabel` (the fragment used in the sentence), because the two need different grammar — the summary reads as one sentence, not a slash-joined list. Options are `role="radio"` buttons with `aria-checked`, grouped in a `<fieldset>`/`<legend>` per step.

**CTA — the one point of coupling to unshipped work.** It points at **`/signup`**, which is live today, and is labelled "Start Free Trial". It does **not** point at a sandbox-key endpoint: BE Gap 340 (sandbox API keys) has not shipped, and this repo has already shipped exactly that failure once — Feature 3's Task 3.3 was marked done on the premise that no website-side work was needed, and left a live 404 on the PayU return path. A block comment above the `<Link>` records the intended follow-up: once Gap 340 lands, relabel to "Get Sandbox API Key" and retarget. The comment is in the code, not only here, so whoever ships Gap 340 finds it.

### `[x]` Task 7.5 — Gap 350: the sandbox key CTA and the claim-at-signup flow (built 2026-08-30)

Task 7.4 shipped a CTA pointing at `/signup` with a block comment saying to retarget it once BE Gap 340 landed. **Gap 340 landed on 2026-08-30**, so this is that retarget — plus the half the comment did not anticipate: an issued sandbox key is worthless unless signing up *keeps* the workspace it belongs to.

This task is deliberately scoped to the **anonymous-visitor** side only. A logged-in Admin's widget-token UI is FE Feature 17 and is not here.

#### 1. It is a relay, not a direct call — and that was checked, not assumed

`invoice-be.bicep` sets `ingress.external: false`, so a browser can reach the backend on localhost and nowhere else. Every existing backend call this app makes already goes through a server-side route handler for that reason (`/api/auth/provision` — Gap 7's record of exactly this failure; `/api/contact`; the PayU return relays). Two new handlers follow the same pattern:

* `app/api/sandbox/keys/route.ts` → `POST /api/v1/sandbox/keys`, modelled on `/api/contact` because both are **public and unauthenticated**.
* `app/api/sandbox/claim/route.ts` → `POST /api/v1/sandbox/claim`, modelled on `/api/auth/provision` because both are **Clerk-authenticated** and the backend applies the same Gap 133 Checkpoint 3c bindings (body `clerk_user_id` must equal the token's `sub`, body `clerk_org_id` must equal the token's active `org_id`).

Neither path is in `next.config.js`'s `feApiPrefixes`, so nothing rewrites `/api/sandbox/*` to invoice-fe, and neither needed a `middleware.ts` change — `/api/contact` is the precedent for an anonymous route under the bare `clerkMiddleware()` matcher and it works today.

#### 2. `X-Client-IP` is built server-side and never forwarded — the sharpest thing here

`routers/support.py::_get_client_ip`, which `routers/sandbox.py` reuses, trusts `X-Client-IP` **ahead of** `X-Forwarded-For`, because that header is this app's own attestation of who the caller is. The backend cannot derive it itself: on its hop the platform-appended XFF entry is this container's pod IP, which would bucket every website visitor into a single limiter key.

That trust is only sound while the relay builds the header from a trusted source. So in `app/api/sandbox/keys/route.ts` the fetch's `headers` is a **fresh object literal** — nothing is spread from `request.headers` — both `X-Client-IP` and `X-Forwarded-For` are **overwritten** with the server-resolved value, and the incoming `x-client-ip` is never read anywhere in the file.

Had it been a pass-through, a browser could send a fresh random value per request and defeat the backend's per-IP limit entirely, leaving only the global `SANDBOX_MAX_UNCLAIMED_TENANTS` cap (500) between an attacker and permanent exhaustion of sandbox issuance for every visitor. That cap is **not** a sufficient backstop today: BE Gap 340 records that no ACA Job schedules `scripts/sweep_sandbox_tenants.py`, so exhausted capacity is not reclaimed on any timetable.

`resolveClientIp()` itself was **moved** from `app/api/contact/route.ts` into `lib/clientIp.ts` rather than copied. It reads only the *rightmost* `X-Forwarded-For` entry (the hop our own Envoy ingress observed and appended) or a Front-Door-verified `X-Azure-ClientIP` — never a client-controlled leftmost claim. This is the same reasoning BE Gap 340 gave for reusing `_ContactRateLimiter` instead of writing a second limiter: the hard part is the trusted-IP question, and two copies of the answer drift. The sliding-window bookkeeping *is* duplicated, deliberately — the two limiters must not share a bucket, or a visitor's contact-form submissions would eat their sandbox allowance, which is the same separation `routers/sandbox.py` achieved with its own Redis key prefix.

#### 3. `SANDBOX_KEYS_ENABLED` is False everywhere — how this degrades

**There is no public endpoint that reports the flag.** Verified by reading the code, not inferred: `main.py` exposes only `/`, `/health`, `/health/liveness` and `/health/readiness`, none of which mention it, and `routers/sandbox.py::_require_sandbox_enabled()` 404s the whole surface when it is off (404 rather than 403, so a disabled deployment looks like one without the feature). The only way to *ask* is to call the issuance endpoint, and that call mints a tenant and consumes the caller's 3-per-hour allowance, so it cannot be used as a probe.

Two layers, and the second is what makes the first safe to get wrong:

1. **`NEXT_PUBLIC_SANDBOX_KEYS_ENABLED`** decides whether the CTA renders at all. It defaults to false, matching the backend's default, so **the shipped default is byte-for-byte Task 7.4's behaviour** — one gradient "Start Free Trial" link, no dead button. This is the failure Task 7.4's original comment existed to avoid, and it is not reintroduced by turning the feature on in code.
2. If the env flag is true while the backend's is false, the relay maps the backend's 404 to `code: "sandbox_disabled"` with a 503, and the CTA renders *"Sandbox keys aren't switched on yet. Start a free trial and you'll get a real workspace and API key immediately. Everything else on this page is live."* Drift is visible and harmless, never a broken-looking error.

Turning it on takes two deliberate acts in order: backend first, then a website rebuild (`NEXT_PUBLIC_*` is baked in at `docker build` time — tracker Gap 6).

#### 4. The reveal — the same shape as Gap 349's, applied to a different key type

`SandboxKeyCta.tsx` is its own component for one specific reason: **it is the only part of Feature 7 that makes a network call**, and keeping the fetch in one file means §7's contract is still checkable by reading one file rather than "the recipe selector is fixture-only except the bit at the bottom".

Four outcome states: issued, rate-limited, feature-disabled, unreachable. The reveal is the `provisionedApiKey` pattern from `app/signup/page.tsx` — monospace key, copy button with a 2s ✓ confirmation — plus an honest note whose every claim is a real property of BE Gap 340 rather than marketing rounding: it names the real limits when the backend sends them (`invoice_limit` / `chat_message_limit`, rendered as "5 invoices, 25 chat messages"), says "read and upload only" (`readonly` scope, pinned three ways backend-side), gives the real `expires_at`, and says signing up moves the workspace over rather than starting again.

The `/signup` link never disappears. It is the gradient primary when the sandbox CTA is off, a secondary link beside it when on, and inside the reveal card it becomes the *next* step ("Keep this workspace — sign up"), because claiming is what turns the throwaway workspace into a real one.

#### 5. The claim, and why its ordering is load-bearing

**How the signup page knows there is a sandbox:** `lib/sandboxKey.ts` writes the key to `localStorage` under `invoiceeq.sandbox_key.v1` at the moment it is issued. There is nothing server-side to read — the visitor was anonymous when the key was issued, by definition. localStorage rather than a cookie because the claim is initiated by client-side code on `/signup`, so the value never needs to travel to a server on its own. Reads drop malformed *and* already-expired entries, so a stale key cannot make every future signup attempt a claim that can only fail.

**`claimSandboxWorkspace()` runs before `provisionTenant()`, never after**, and this is not a preference:

* Claim first → `claim_sandbox_tenant()` attaches `clerk_org_id` to the sandbox tenant, so the subsequent provision call finds it by that id and early-returns `is_new=false`, minting nothing. The `User` row is then created on first login by `dependencies.py::get_tenant_context` — the same path any other already-existing tenant takes, so **a claim does not strand the user**. Checked against `dependencies.py`, not assumed.
* Provision first → a brand-new tenant takes the `clerk_org_id`, and the claim would then try to write that same value onto the sandbox tenant, against a UNIQUE column. Best case an error; worst case a 500 in the middle of signup.

**It never throws and never blocks signup.** A lost race, an already-claimed workspace, an expired or revoked key, `SANDBOX_KEYS_ENABLED` switched off between issuance and signup, or an unreachable backend all resolve to `NO_CLAIM` and signup proceeds as an ordinary fresh signup. Terminal statuses (400/401/403/404/409/410) additionally clear the stored key so it is not retried forever; transient ones (502/503) leave it, since it may still be good and it expires on its own.

Because a successful claim makes `provision`'s `api_key` null by design, the reveal shows `result.api_key || claim.apiKey` — the claim's own freshly-minted `inv_live_` key, which the backend created in the same transaction that revoked the `inv_test_` one. The reveal's badge and subtitle branch on `sandboxClaim.claimed` so a claimed signup reads *"Sandbox workspace kept — the invoices and chats you tried are still there"* rather than presenting a key with no explanation of what changed.

**One residual, stated rather than hidden:** if the claim succeeds and the provision call that follows it then fails terminally (a 409 — the user already belongs to another workspace), the reveal screen is not shown and that fresh `inv_live_` key is not displayed. The workspace is claimed and intact; the key is recoverable by rotating in Settings → Security. The Retry path handles the non-terminal version of this (it holds `sandboxClaim` in state and does not re-claim, since a claimed sandbox is single-winner). Left as-is because reaching it requires signing up with an account that already has a workspace.

### `[x]` Wiring — `app/page.tsx`

`SageChatPreview` renders immediately after `<Hero />`, matching the mockup (the pipeline demo produces the data, SAGE asks about it). `WorkflowRecipeSelector` renders after `<WorkspaceShowcase />` and immediately before `<PricingTable />`, **not** directly under SAGE as in the mockup — the mockup only drew the hero frame, not the whole page, and "here is the pipeline you'd get" reads straight into "here is what it costs", keeping this CTA beside the pricing CTAs instead of competing with them mid-page. Both deviations are recorded as comments in `page.tsx` itself.

Final order: `Hero` (now carrying Gaps 345 + 346) → `SageChatPreview` → `FlowsShowcaseSection` → `AITeamSection` → `WorkspaceShowcase` → `WorkflowRecipeSelector` → `PricingTable` → `BenefitsStrip`.

---

## 6. Verification Plan

All of the below was actually executed on 2026-08-29 in `apps/invoice-website`. Commands and their real output.

### Typecheck and build — clean

```
$ npx tsc --noEmit
(no output, exit 0)

$ npx next build
 ✓ Compiled successfully
 ✓ Generating static pages (13/13)
┌ ƒ /                                     21.9 kB         138 kB
```
`/` grew from the 17.2 kB / 133 kB recorded at Gap 163 to **21.9 kB / 138 kB**. Route count unchanged at 13 — this feature adds no routes.

### Playwright suite — 39 passed, 1 failure, and that failure is pre-existing

```
$ npx playwright test --workers=1
  1 failed
    e2e\billing-payu-relay.spec.ts:76 › browser POST to the relay lands on billing/failed with the unconfirmed messaging
  39 passed (1.9m)
```
**The failure was proven to be pre-existing, not assumed to be.** The Feature 7 changes were stashed (`git stash push -u` limited to the five touched paths), the same spec re-run on the untouched baseline, and it failed identically (`page.waitForURL` timeout at `billing-payu-relay.spec.ts:99`, 4 passed / 1 failed both times); the changes were then restored. It is a PayU relay redirect test and touches none of this feature's files.

**Not covered:** no Playwright spec exercises any of the three new components. This is the same residual `/contact` carries (Feature 5, Task 5.4) and it is stated rather than dropped. The behavioural evidence below is a scripted headless-Chrome run, not a committed regression test.

### Headless Chrome behavioural run (real Chrome channel, against `next start` on :3210)

Same technique as Gaps 158/159/163/164 used. Real output:

```
345 app tab visible: true          345 plug tab visible: true
345 default aria-selected app/plug: true / false
345 app panel tiles: 3             345 plug panel present before click: 0
345 after click aria-selected app/plug: false / true
345 plug panel tiles: 4
345 plug tile titles: Email In | Drive Sync | REST API | Webhooks
345 app panel gone: true
345 order badge y=104 < modeTabs y=410 < pipelineDemo y=1044: true

346 warning card before selecting FRT-1048: 0
346 status pill text: AUDIT_REQUIRED
346 warning card visible: true
346 warning detail: Freight Surcharge came in at $5,200.00 — 34% above this vendor's own 90-day average of $3,...
346 stage 4 label: 4. Held for Review
346 risk score shown: Risk Score 61.2%
346 flagged line item present: true
346 JSON routing: true | consensus 0.612: true | PRICE_VARIANCE: true
346 clean sample has no warning card: true

347 chips: 3
347 answer before click (placeholder shown): true
347 REAL answer text: 3 are open. One price variance (Global Freight Logistics, $18,750.50, flagged 34%
      over the vendor's own 90-day average) and two suspected duplicate charges from the same vendor, seven days apart.
347 answer swaps on 2nd chip: Q2 came in at $312,400 against $278,900 in Q1 — up 12%. Almo...
347 SQL contains HOLD_FOR_REVIEW: true
347 citation pills: FRT-1048, DUP-2201, DUP-2202

348 default : ...arrive via email in, are auto-approved when clean, results are pushed to your webhook — with SAGE chat over the data.
348 strict  : ...arrive via email in, are reviewed by a human every time, results are pushed to your webhook — pipeline only, no chat.
348 flagged : ...arrive via a watched Drive folder, are sent to a human only when flagged, results are pushed to your webhook — pipeline only, no chat.
348 steps rendered: 4
348 CTA href: /signup
348 CTA label: Start Free Trial
```

Screenshots reviewed at 1440×900 for the hero (both tabs), the flagged pipeline-demo state, the SAGE answer pane and the recipe selector. They live in the session scratchpad, deliberately not committed — `test_evidence/` is functional-tester-owned per CONVENTIONS, and this was a senior-dev verification run, not a filed test.

**Copy defect found by looking at the screenshot, then fixed and re-verified:** the summary sentence originally read *"are a human on every invoice … and you get it pipeline only, no chat."* Two `summaryLabel` values and the sentence's final connector were rewritten; the three-line output above is the re-run after the fix, on a rebuilt server (the first re-run silently hit a stale `next start` still serving the previous build — caught because the output was byte-identical across three different selections).

### Fixture contract (§7) — verified empirically

```
CONTRACT requests fired by Feature 7 interactions: 1
   -> http://127.0.0.1:3210/signup?_rsc=1wtp7
CONTRACT any request to /api/ at all, whole session: 0
```
Every request the page made was recorded via `page.on("request")`, then every new component was exercised (both tabs, the flagged sample, two SAGE chips, four recipe options). **One** request resulted, and it is Next's own RSC prefetch of `/signup` from the CTA `<Link>` — a page prefetch, not a data call, and identical in kind to every other `<Link>` already on this page. **Zero `/api/` requests in the entire session.** The off-origin traffic present on page load (Clerk `real-stallion-21.clerk.accounts.dev`, Google Fonts) is pre-existing `app/layout.tsx` `ClerkProvider` behaviour and fires with or without this feature.

### Task 7.5 / Gap 350 — verification, 2026-08-30

Typecheck and build, after the change:

```
$ npx tsc --noEmit
(no output, exit 0)

$ npx next build
 ✓ Compiled successfully
 ✓ Generating static pages (13/13)
┌ ƒ /                                     22 kB           140 kB
├ ƒ /api/sandbox/claim                    0 B                0 B
├ ƒ /api/sandbox/keys                     0 B                0 B
```
Route count went 13 → **15**; the two new entries are this task's relays. `/` grew 21.9 kB → 22 kB.

**This was run against a real backend and real Postgres, in all three flag states.** A second uvicorn was started on `:8010` with `SANDBOX_KEYS_ENABLED=true` in its process environment — no file in `invoice-be` was modified — while the pre-existing `:8000` instance stayed at the default (flag off). `/health/readiness` reported `database: ok` on both.

**(a) Both flags on — real browser (Chrome channel, `next start`, 1440×900):**

```
350 sandbox button visible: true
350 secondary Start Free Trial link present: 1
350 /api/ requests BEFORE click: []
350 issued key prefix: inv_test_ | length: 52
350 key looks like a sandbox key: true
350 /api/ requests AFTER click: ["POST /api/sandbox/keys"]
350 honest note: Shown once — copy it now. This is a temporary trial key (5 invoices,
      25 chat messages), read and upload only, and it expires on Sep 2, 2026, 10:19 AM.
      Sign up for real from this browser and we'll move this workspace over — you keep
      everything you tried, instead of starting over.
350 reveal heading: SANDBOX KEY ISSUED
350 keep-workspace CTA: /signup
350 copy button present: 1
350 localStorage key matches revealed key: true
350 localStorage fields: apiKey,expiresAt,tenantId
350 after reload, restored heading: YOUR SANDBOX KEY
350 total POST /api/sandbox/keys calls across whole session: 1
```
The limits in the note ("5 invoices, 25 chat messages") are the backend's own `invoice_limit`/`chat_message_limit`, not hardcoded copy. **One** issuance call across the whole session including a reload — the restored state reads localStorage, it does not re-issue.

**(b) Env flag on, backend flag off — the drift case, real browser:**

```
350 sandbox button rendered: 1
350 key revealed: 0
350 disabled message shown: 1
350 message: Sandbox keys aren't switched on yet. Start a free trial and you'll get a
      real workspace and API key immediately. Everything else on this page is live.
350 Start Free Trial label: Start Free Trial   (still present)
```

**(c) Shipped default — env flag unset, backend flag off, real browser:**

```
350 sandbox button rendered: 0
350 Start Free Trial links: 1
350 Start Free Trial label: Start Free Trial
350 is the gradient primary CTA: true
350 /api/ requests (no button to click): []
```
i.e. the default build is Task 7.4's behaviour exactly, with no dead button and no requests.

**(d) The claim path, driven through the website relay against real Postgres.** A full real-Clerk signup is not completable in this environment (see "Not verified" below), so the claim was exercised through the relay with the *exact body* `claimSandboxWorkspace()` builds, using the backend's `ALLOW_MOCK_AUTH` identity:

```
1. POST /api/v1/sandbox/keys            -> 201, tenant 2b00fa49-…b05f8
2. GET  /api/v1/sandbox/keys/me         -> 200 {"claimed":false,"chat_message_limit":25,
                                                "invoices_remaining":5,"expired":false}
3. POST :3211/api/sandbox/claim         -> 200 {"tenant_id":"2b00fa49-…b05f8",
     (through the website relay)              "clerk_org_id":"org_gap350_check",
                                              "api_key":"inv_live_zEEfOka…"}
4. GET  /api/v1/sandbox/keys/me (old key) -> 401 "Invalid or revoked API key."
5. POST /api/sandbox/claim again (old key) -> 401 (same)
6. POST /auth/provision, same org        -> 200 {"tenant_id":"2b00fa49-…b05f8",
                                                "is_new":false,"api_key":null}
```

Step 3 returns the **same `tenant_id`** as step 1 — the sandbox workspace was promoted, not replaced, which is the entire point of the feature. Step 4 proves the `inv_test_` key really is revoked in the same transaction. Step 6 confirms the assumption the signup code's `result.api_key || claim.apiKey` fallback rests on: after a claim, provisioning finds the tenant by `clerk_org_id`, returns `is_new=false` and mints **no** key, so the claim's key is the only one there is.

**One finding worth recording:** a repeat claim returns **401, not 409**. The key is revoked by the first claim, so `resolve_api_key_context()` rejects it before the already-claimed check is ever reached — the 409 path is only reachable for a still-valid key against a claimed tenant, which the atomic swap makes unreachable in practice. `claimSandboxWorkspace()` already treats 401 as terminal alongside 409/410, so this was covered, but it was confirmed rather than assumed.

**Not verified, and not claimed:**

* **No full real-Clerk signup end-to-end.** The Clerk dev instance in this environment loops on the dev-browser handshake (`Refreshing the session token resulted in an infinite redirect loop`), so `/signup` cannot be completed here — the same limitation Gap 349 recorded for its own reveal screen. What is proven is the relay + backend contract for the exact body the signup page sends (d above); what is *not* proven by execution is the surrounding React flow — that `completeSignupAndProvision()` reaches `claimSandboxWorkspace()` with the right org id after `setActive`, and that the reveal renders the claimed-variant copy. Those are typecheck-and-read-verified only.
* **No Playwright spec.** The evidence above is scripted headless-Chrome and curl, not a committed regression test — the same residual Gaps 345–348 already carry.
* **No deployed run.** Local only. `SANDBOX_KEYS_ENABLED` remains False in every real environment, including the bicep params, and `NEXT_PUBLIC_SANDBOX_KEYS_ENABLED` is unset everywhere.
* **Rate-limit behaviour was not load-tested.** The edge limiter's window/eviction logic is a copy of the contact relay's shape and was not driven to its limit; only the happy path and the backend's own limits were exercised.

### Open regression — needs a founder call, not silently accepted

At 1440×**700**, the above-the-fold block now ends at **y≈971**. Gap 163 explicitly verified and recorded that this block ended at **y≈640**, i.e. inside a ~700 px viewport with no scrolling, and treated that as a requirement of the hero design. The mode tabs plus their capability panel add roughly 330 px, which is exactly the delta.

This was not worked around by deleting hero content: the before/after invoice transform is Gap 163's own approved, superseding design (2026-08-09) and removing it to make room is outside this feature's approved scope. The approved mockup's "proposed" hero happens to show no before/after transform at all, which may mean the founder already intends the switcher to replace it — but that is an inference, not an instruction, so nothing was removed. **Three options, for the founder to pick:** (a) accept that the hero now scrolls; (b) collapse the mode-tab capability panel to a single row of labels; (c) let the switcher replace the before/after transform, as the mockup's proposed frame implies. No horizontal overflow at any width (`document.scrollWidth === clientWidth`, checked).

### functional-tester pass, 2026-08-30 — committed Playwright coverage added, full suite re-run

Additive (CONVENTIONS.md hard rule 4) — nothing above this section was edited. This closes the "no automated test coverage" / "no Playwright spec covers any of the three new components" caveat this doc's header and §6 both recorded.

**New spec:** `e2e/plug-and-play-homepage.spec.ts`, 11 tests, needing only the Next dev server (every component this covers is fixture-driven per §7's contract). Covers: `HeroModeTabs` — defaults to the app tab, switching swaps the mounted panel (the inactive panel has 0 DOM nodes, confirming unmount-not-hide as designed) and the plug-primitive tiles link to the right `/signup?intent=...`; the Gap 346 SENTINEL discrepancy sample — the clean default renders no warning card, selecting `FRT-1048` renders the discrepancy card / "4. Held for Review" stage label / `Risk Score 61.2%` once the ~1.8s pipeline animation settles, switching back to a clean sample removes it; `SageChatPreview` — no answer pane before a click, a chip reveals its answer/SQL/citations, a second chip swaps rather than appends; `WorkflowRecipeSelector` — the default selection produces the right summary sentence, each click updates it, `aria-checked` is exclusive within a step; `SandboxKeyCta`'s default (flag-unset) state renders only the Gap 348 `Start Free Trial` link with zero `/api/` requests on load.

```
npx playwright test e2e/plug-and-play-homepage.spec.ts
-> 11 passed
```

**Flag-on state, second config (mirrors `playwright.proxy.config.ts`'s own precedent for a server-env-baked branch the main config cannot reach):** `playwright.sandbox.config.ts` + `e2e/sandbox-backend-stub.mjs` (a tiny stand-in for BE Gap 340's `POST /api/v1/sandbox/keys`, same role `e2e/fe-proxy-stub.mjs` plays for the proxy config) + `e2e/sandbox-key-cta-enabled.spec.ts`, 3 tests: no fetch before the click; issuing reveals the key once with the real limits/expiry text taken from the (stubbed) response and `Start Free Trial` survives as a secondary link; the key persists to `localStorage` under `invoiceeq.sandbox_key.v1`; a reload restores it with **no** second issuance call.

```
npx playwright test --config=playwright.sandbox.config.ts
-> 3 passed
```

One environmental gotcha hit and recorded, not a code defect: the first attempt after an unrelated machine-resource incident (see the FE feature_17 doc's own note on the same incident) showed 2/3 failing against a **stale** `.next-sandbox` build cache left over from before that incident — deleting `.next-sandbox` and re-running fixed it outright, matching this repo's own precedent of recording this class of thing (e.g. FE Gap 143's port-sharing note).

**Full existing suites re-run, all three configs, in isolation (one Playwright pass at a time — see the FE doc's note on why that mattered on this machine):**

```
npx playwright test                                    -> 51 total, 50 passed, 1 failed
npx playwright test --config=playwright.proxy.config.ts -> 6 passed
npx playwright test --config=playwright.sandbox.config.ts -> 3 passed
```

The 1 default-pass failure is `billing-payu-relay.spec.ts:76`, the exact same flaky form-submit timing test this doc's own §6 already root-caused as pre-existing via `git stash` before this feature's changes existed. Independently reproduced here, nothing new. The 11 new `plug-and-play-homepage.spec.ts` tests all passed inside this same default-config run.

**Playwright config changes, additive:** `playwright.config.ts`'s `testIgnore` widened from a single string to an array (`billing-proxy-mode.spec.ts` + the new `sandbox-key-cta-enabled.spec.ts`), and `package.json` gained `test:e2e:sandbox` / updated `test:e2e:all`.

---

## 7. Fixture contract — hard constraint

> **Amended 2026-08-30 by Gap 350 (Task 7.5), narrowed rather than dropped.** The original text below said *every* component this feature adds makes zero network calls, and it also said any change that wires a real backend call in "invalidates this contract and needs its own Gap entry — it is not a refactor". That is exactly what happened, and this is that entry.
>
> **The amended contract: exactly one component in this feature may make a network call — `SandboxKeyCta.tsx` — and only on an explicit user click.** Everything else named below stays at zero, unconditionally.
>
> | Component | Network calls | On page load |
> |---|---|---|
> | `Hero.tsx` (pipeline demo, Gaps 345/346) | none | none |
> | `HeroModeTabs.tsx` | none | none |
> | `SageChatPreview.tsx` | **none — this one is load-bearing, see (1) below** | none |
> | `WorkflowRecipeSelector.tsx` | none (it renders the CTA, it does not fetch) | none |
> | `SandboxKeyCta.tsx` | `POST /api/sandbox/keys`, **click-only** | **none** |
>
> The reason the original constraint existed is untouched by this amendment: it was never "no HTTP from the homepage" as a style rule, it was **"`/` is public, unauthenticated and crawler-reachable, so nothing here may be an open uncapped path to LLM spend"**. A sandbox key is not that. It is metered on both sides — an edge rate limit in the relay, the backend's Redis-backed 3-per-hour limit, a global unclaimed-tenant cap that fails closed at 503, and `SandboxTenant.chat_messages_used` charged *before* the model call (BE Gap 340 constraint 7, which exists precisely because nothing else in the backend meters chat). It also fires on a deliberate button press, never on load or on a crawl — verified empirically in §6, where a full page load plus every other Feature 7 interaction still produced **zero** `/api/` requests, and the count went to exactly **one** only after the button was clicked.
>
> `SageChatPreview` is the component this contract was really written for, and it is **unchanged** — it still never reaches SAGE, never reaches `invoice-be`, and therefore still cannot burn OpenAI quota on anonymous marketing traffic.

The original Gap 345–348 text, kept as the record of what those tasks committed to:

**Every component added by this feature makes zero network calls.** No `fetch`, no `XMLHttpRequest`, no server action, no route handler, no `NEXT_PUBLIC_*` endpoint read. Specifically:

1. The SAGE preview's answers, SQL snippets and citation pills are a module-level `const` in `SageChatPreview.tsx`. It never reaches SAGE, never reaches `invoice-be`, and therefore **cannot burn OpenAI quota on anonymous marketing traffic** — which is the reason this constraint exists, not a stylistic preference. `/` is a fully public, unauthenticated, crawler-reachable page; a real chat call here would be an open, uncapped LLM endpoint.
2. The recipe selector computes its summary line purely from local state. Its CTA is a `<Link>` navigation, not a POST.
3. The mode tabs and the discrepancy sample are static fixture data, same as the existing `SAMPLE_INVOICES`.

Any future change that wires a real backend call into these components invalidates this contract and needs its own Gap entry — it is not a refactor.
