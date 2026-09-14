# Feature 14: Alert-Anchored Trainer & Chat Correction Lane (FE)

Frontend half of **BE [feature_18_trainer_alert_anchored_training.md](../../invoice-be/docs/feature_18_trainer_alert_anchored_training.md)**, which is the authoritative API contract — read it first. This document covers only what the FE does with that contract.

Supersedes the rule-creation half of [feature_6_trainer.md](feature_6_trainer.md), whose File Coordinates section has been updated to point here. Everything else in Feature 6 (rule history, rollback, the workspace geometry from FE Gap 111, the plan gate from FE Gap 115) survives unchanged.

Built 2026-08-17. Closes **FE Gaps 232–238**, and appends a correction to the stale claim in **FE Gap 221**.

---

## Why this exists

A ground-truth investigation on 2026-08-12/13 closed four real defects (BE Gaps 222/223/224/226) and surfaced a deeper structural problem the four did not individually explain: **the Trainer's rule-creation flow took free text from a chat box, had an LLM interpret it into a rule, and persisted it with no structured checkpoint in between.** A rule was never tied to a specific invoice, a specific field, or a specific thing that went wrong.

The backend fixed that structurally. This pass makes the UI match — and closes one permission hole the redesign brought into focus.

---

## File Coordinates

**New**
* [lib/chat-training-service.ts](../lib/chat-training-service.ts) → `chatTrainingService` (`submitFeedback`, `clearFeedback`, `triageMessage`, `submitSourceVerdict`, `getCategories`, `previewRule`, `commitRule`, `listRules`, `deleteRule`); types `TriageReason`, `TriageNext`, `TriageEntryPoint`, `TriageDiff`, `TriageDiffResponse`, `SourceVerdictResponse`, `ChatRulePreview`, `ChatRule`, `TriageInvoice`, `ChatRuleCategory`
* [components/trainer/TrainerEntryPanel.tsx](../components/trainer/TrainerEntryPanel.tsx) → `TrainerEntryPanel` — the unified entry point (vendor → real invoice picker, or upload)
* [components/trainer/AlertListPanel.tsx](../components/trainer/AlertListPanel.tsx) → `AlertListPanel`, `severityVisual()`
* [components/trainer/AlertCorrectionModal.tsx](../components/trainer/AlertCorrectionModal.tsx) → `AlertCorrectionModal`
* [components/trainer/FlagMissedAlertModal.tsx](../components/trainer/FlagMissedAlertModal.tsx) → `FlagMissedAlertModal`
* [components/trainer/QaChatPanel.tsx](../components/trainer/QaChatPanel.tsx) → `QaChatPanel`, `isRealMessageId()`
* [components/chat/ThumbsDownTriage.tsx](../components/chat/ThumbsDownTriage.tsx) → `ThumbsDownTriage`
* Proxy routes: `app/api/trainer/sessions/from-invoice/`, `app/api/trainer/sessions/[id]/pdf/`, `app/api/trainer/sessions/[id]/preview/`, `app/api/trainer/sessions/[id]/corrections/{tolerance,confidence-threshold,alert-override,missed-alert}/`, `app/api/trainer/alert-types/`, `app/api/chat/messages/[messageId]/triage/`, `app/api/chat/messages/[messageId]/triage/source-verdict/`, `app/api/chat/rules/{,categories,preview,commit,[ruleId]}/`
* [e2e/trainer-alert-anchored.spec.ts](../e2e/trainer-alert-anchored.spec.ts) → 5 tests
* **FE Gap 478 (2026-09-14)** [components/settings/ChatRulesPanel.tsx](../components/settings/ChatRulesPanel.tsx) → `ChatRulesPanel` (default), `chatRuleCategoryLabel()`, `formatChatRuleAddedAt()`
* **FE Gap 478 (2026-09-14)** [app/settings/chat-rules/page.tsx](../app/settings/chat-rules/page.tsx) → `ChatRulesSettingsPage`, `load()`, `handleDelete()`
* **FE Gap 478 (2026-09-14)** [tests/unit/chat-rules-panel.test.tsx](../tests/unit/chat-rules-panel.test.tsx) → 9 vitest cases

**Changed**
* [app/trainer/page.tsx](../app/trainer/page.tsx) → `TrainerPermissionPrompt` (new), `TrainerContent` rewritten: `handlePickInvoice()`, `handleUploadFile()`, `handleChangeDocument()`, `handleSubmitTolerance()`, `handleSubmitThreshold()`, `handleSubmitOverride()`, `handleFlagMissed()`, `afterStage()`, `handleOpenCommit()`, `handleConfirmCommit()`, `errorMessage()`. Removed: `handleScopeChange()`, `handleSectionChange()`, `handleVendorEntryModeChange()`, `handleSelectVendor()`, `handleClearFile()`
* [lib/trainer-service.ts](../lib/trainer-service.ts) → `startSessionFromInvoice()`, `startSessionFromUpload()`, `listVendorInvoices()`, `getAlertTypes()`, `correctTolerance()`, `correctConfidenceThreshold()`, `correctAlertOverride()`, `flagMissedAlert()`, `previewSession()`, `commitSession(session, previewToken)`. Removed: `startSession(scope, …)`. New types: `TrainerAlert`, `AlertTypeSpec`, `AlertTypeRegistry`, `RuleDescription`, `RuleImpact`, `RuleImpactSample`, `PreviewResult`, `VendorInvoiceOption`, `StagedRuleResult`
* [components/trainer/CommitModal.tsx](../components/trainer/CommitModal.tsx) → reworked into the preview gate; `RuleCard()`, `ImpactBlock()` (new internals)
* [components/trainer/TrainerControlBar.tsx](../components/trainer/TrainerControlBar.tsx) → Global section removed; props now `panelTab`/`onPanelTabChange`/`hasSession`/`onChangeDocument`. Types `VendorPanelTab` replaces `GlobalSubTab`/`TrainerSection`/`VendorEntryMode`
* [components/trainer/PdfViewerPanel.tsx](../components/trainer/PdfViewerPanel.tsx) → `scope` widened to include `outbound`; empty state and loading stages reworded
* [components/chat/MessageBubble.tsx](../components/chat/MessageBubble.tsx) → `FeedbackVote` split into `handleUp()`/`handleDown()`; thumbs-down opens `ThumbsDownTriage`
* **FE Gap 478 (2026-09-14)** [components/layout/Sidebar.tsx](../components/layout/Sidebar.tsx) → `Sidebar` — `menuItems` gains the `Chat Rules` row (`/settings/chat-rules`, `ScrollText`, `visible: canTrain`), after `AI Trainer`; `activeHref` unchanged
* **FE Gap 478 (2026-09-14)** [app/settings/page.tsx](../app/settings/page.tsx) → `INTEGRATIONS` gains the `Chat Rules` tile (not `adminOnly`)
* [e2e/trainer-loading-state.spec.ts](../e2e/trainer-loading-state.spec.ts), [e2e/group-a-layout-overflow.spec.ts](../e2e/group-a-layout-overflow.spec.ts), [e2e/rbac-sidebar.spec.ts](../e2e/rbac-sidebar.spec.ts) → updated for the removed endpoints and the renamed commit button

**Deleted**
* `app/api/trainer/sessions/global/route.ts`, `app/api/trainer/sessions/from-production/route.ts` — both backend endpoints are now 410 Gone

---

## Functionality

### 1. The permission boundary (FE Gap 232)

**Rule creation lives only inside `/trainer`, and that route now gates on `can_train`.**

`app/trainer/page.tsx` previously gated on billing plan alone. `canTrain` was available from `hooks/useAuth.ts` and never read here, so any user in a Pro tenant could navigate to `/trainer` directly, see the whole sandbox render, pick an invoice and fill in a correction — and only discover the boundary when the first write 403'd. The backend was always the real enforcement, so nothing could actually be written; but a fully interactive rule-authoring screen shown to someone who cannot save anything is a boundary that exists only in the API.

`TrainerPermissionPrompt` is a full-page state, deliberately mirroring FE Gap 115's `TrainerUpgradePrompt` rather than inventing a second pattern — both are "this entire route is not for you", and a dismissable overlay would just reveal a screen that fails on first use. The plan gate is checked **first**, so a Free-tier tenant still gets the upgrade explanation rather than a confusing permissions one.

**No "train on this" affordance was added to any Auditor-facing screen.** `components/audit/AlertConsole.tsx`, `OutboundAlertConsole.tsx` and `app/invoices/review/[id]/page.tsx` are untouched by this work. Auditors resolve alerts exactly as before and never see or trigger rule creation.

### 2. Global removed as a rule-creation destination (FE Gap 233)

`TrainerControlBar` no longer has a Global section. `POST /trainer/sessions/global` is 410 Gone and `trainer_commit()` refuses a `scope="global"` session, so the tab pointed at a destination every write path now rejects. Both dead proxy routes are deleted rather than left returning 410s.

**Already-committed Global rules are untouched and still apply** — they are still read by both extraction prompt builders, the queue worker and the chat agent, and are still visible in Rule History. Only authoring new ones from this screen is gone.

`outbound` is a real scope in the FE types now: an outbound invoice has no vendor at all (the counterparty is the customer), so its rules live on the outbound-global template. That is structural, not an oversight, and `CommitModal` states the consequence honestly — outbound commits deliberately do **not** enqueue a re-audit (BE deviation 5).

### 3. One entry point, two ways in (FE Gap 234)

`TrainerEntryPanel` is the landing state. **No session is opened on mount any more** — the page used to start a Global session, and more importantly the redesign has no "default" session, because every session must be anchored to a document the user chose.

* **Upload a PDF** — `POST /trainer/upload`, real OCR + extraction, real alerts. Works for a brand-new or already-known vendor.
* **Select a vendor → pick one of their invoices** — a **real list**, which is the whole point. The endpoint this replaces resolved `order_by(created_at.desc()).first()`, so an alert on any invoice but the newest was unreachable.

Both land on the identical state: that invoice's alerts, beside that invoice's PDF.

**Where the invoice list comes from — a real contract deviation.** The backend added no trainer-side per-vendor invoice list; `GET /trainer/vendors` still returns one `sampleInvoiceId` per vendor, which is the same latest-only limitation. `listVendorInvoices()` therefore uses the standard `GET /api/invoices?vendor_name=X&limit=50`, which already supports the filter and returns `sa_alerts` — letting each row show its real alert count, which is what makes the list usable for finding the invoice carrying the alert you want to correct. It is INBOUND-only by construction there, which matches the picker's purpose.

**`pdfUrl` population.** `PdfViewerPanel` was already always-rendered, so this was data population, not new plumbing — with one exception: `GET /api/trainer/sessions/{id}/pdf` is a genuinely new proxy route, and deliberately a binary stream rather than `proxyJson` (reading a PDF through `response.text()` would corrupt it). All `URL.createObjectURL()` use is gone from `lib/trainer-service.ts`; both paths now get a server-side URL that survives a reload and works on another device.

**Coordinate highlighting is not promised.** `boundingBox` stays optional on `ExtractedVariable` and the panel degrades to showing the document without a highlight when coordinates are absent, rather than forcing a box that may not exist.

### 4. Alert list → two correction entry points (FE Gap 235)

`AlertListPanel` renders the session's real alerts. Each row renders **its own** correctability from the backend registry's per-alert `correctionForm` — the FE keeps no second copy of that mapping.

**"Train on this"** opens `AlertCorrectionModal`, a two-option picker:

| Option | Form shown | Why |
|---|---|---|
| Unnecessary, `correctionForm: "tolerance"` | `abs_tol` / `rel_tol`, with the shipped defaults beside them | The three types produced by a tolerance-taking check |
| Unnecessary, `correctionForm: "confidence_threshold"` | A **separate** threshold form | `low_confidence_field` is a different parameter on a different backend function. Reusing the tolerance UI would have shipped a control whose numbers silently did nothing |
| Unnecessary, anything else | **No form at all** — the registry's own `notCorrectableReason`, plus a link to the relabel option | The five `*_not_verified_in_source` types ask a verbatim-presence question with no band to widen; the backend 400s on them by design |
| Wrong severity or message | Severity dropdown (error/warning/info) + editable message | Relabelling never changes whether an alert fires |

The numeric forms label their reference values as **"Ships as …"**, not "your current setting": the session payload does not carry the tenant's resolved effective tolerance, so claiming to show a current value would sometimes be wrong. Stating the shipped default is something that can always be said truthfully.

**"Flag as missed"** (`FlagMissedAlertModal`) is panel-level, not per-row — a missed alert is by definition not attached to any row that exists — and is available *especially* when the list is empty, which is where a missing check is most invisible. Two structured primary inputs (registry alert type; field, picked from this invoice's own extracted fields), with free text explicitly optional and labelled as background only. The registry is fetched lazily, on open, rather than on every Trainer page load.

### 5. Preview before commit (FE Gap 236)

The header button is now **"Review & Commit"**, and clicking it *runs the preview*. There is no path to the confirm button that skips it.

`CommitModal` renders three things:
1. **Structured interpretation** — kind / field / condition / scope / source alert type per rule, from `describe_rule()`.
2. **Historical impact**, honestly:
   * `exact` → the real replay figures plus a **list of the actual invoices** that would change.
   * `not_computable` → an explicit explanation. **No number, no fabricated zero** — this is the case a blank or a "0 invoices affected" would misrepresent as reassurance.
   * `partial` → both, with the uncomputable part named separately rather than folded into the totals.
3. **Explicit Confirm**, sending `preview_token`. The backend 409s on drift; staging any new correction clears the locally held preview too, so a stale impact estimate can't be re-opened.

Gap 217's guardrail now runs at preview time, so a rejected rule surfaces while the user is still editing. `errorMessage()` unwraps the structured 400 bodies (including `flagged_rule`) so the backend's own explanation is what gets shown.

### 6. QA chat, structurally separate (FE Gap 237)

`QaChatPanel` replaces `QnAPanel` on this screen. The panel it replaces had **one text box that both answered questions and silently created extraction rules** — that ambiguity is the root of what Feature 18 was opened about.

The separation is stated in the UI, not just in a doc: a standing banner says nothing typed there creates an extraction rule, and points at the alert panel for extraction changes and at the thumbs-down for answer problems. The control bar's two modes are labelled **"Correct Alerts"** and **"Ask Questions"**.

Thumbs-down works here because QA turns are now real `ChatMessage` rows. `isRealMessageId()` gates the vote control on a genuine UUID — a synthetic `msg-xxxxxxxx` id would 404 the feedback API, so rendering a vote button for one would offer an action that cannot work.

### 7. Thumbs-down triage (FE Gap 238)

`ThumbsDownTriage` is one component used by **both** `MessageBubble::FeedbackVote` and `QaChatPanel` — same complaint, same kind of answer, so a single implementation that cannot drift.

Thumbs-**up** is unchanged and still signal-only (Gap 54's contract, byte-for-byte). Thumbs-**down**:

1. **Reason picker** — wrong data / wrong interpretation / bad tone, sent with the vote so the backend returns the next step in one round-trip. The vote is written first, so abandoning the dialog still registers the complaint.
2. **wrong data** → if several invoices fed the reply, the user is asked the only genuinely disambiguating question: *one specific invoice, or the overall answer/total?*
   * One invoice → picked from **the real set the backend returns**, never typed → auto-diff. The UI never asks "was the number right?", which is what the user came here unable to answer.
     * `mismatch` → provably a chat bug → straight to the rule step.
     * `match` → **the PDF is rendered inline, beside the stored value**, so the document question can be answered without hunting for the file. If the document disagrees, this stops being a chat correction and deep-links into `/trainer?invoice_id=…&field=…&flag_missed=1`, which opens the missed-alert form pre-filled.
   * Overall/total → the PDF is skipped entirely; the structured categories are the right question there.
3. **Category pick** — the backend's closed vocabulary, never free text; the note is secondary and labelled as never being fed to the assistant as an instruction.
4. **bad tone** → not a rule at all; links to the chat-style controls.
5. **Preview then confirm** — the commit sends the preview token (the backend 400s without one). Users without `can_train` still reach the preview and see what would be proposed, with the confirm disabled and explained — matching the backend, which gates only the commit.

---

## Deviations & known gaps

Recorded rather than quietly absorbed.

1. **No trainer-side vendor-invoice list exists** — worked around with `GET /invoices?vendor_name=`, as described in §3. If the picker should ever cover OUTBOUND invoices, that endpoint filters them out and a BE change would be needed.
2. **Chat style cannot be saved without an active trainer session.** `GET /trainer/chat-style` is session-free, but saving is still `POST /trainer/sessions/{id}/commit-behavior`. The backend's `bad_tone` triage response advertises `settingsEndpoint: "/api/v1/trainer/chat-style"`, which is **GET-only** — there is no `POST /trainer/chat-style`. Consequence: the triage flow's bad-tone branch **links to the Trainer's Chat Response Style tab** (`/trainer?panel=chat-style`) instead of saving inline, because an inline save would have to invent a session. That link is also plan- and permission-gated, so a user without Trainer access has no way to act on their own tone complaint. **Follow-up (BE):** a session-free `POST /trainer/chat-style`.
3. **Three components are now orphaned but were left on disk:** `components/trainer/QnAPanel.tsx` and `components/trainer/TrainerUploader.tsx` (dead as of this change), and `components/trainer/ScopeSelector.tsx` (already dead before it — nothing referenced it). Deleting them is outside this pass's approved scope; they are named here so they are a known follow-up rather than silent clutter. Four surviving comments in `ExtractedFieldsPanel.tsx`, `PdfViewerPanel.tsx` and `RulesRail.tsx` still reference `QnAPanel` historically.
4. **`stagedRuleCount` is approximate.** The session's `activeRulesDetailed` mixes seeded template rules with newly staged ones, and the payload carries no "staged in this session" flag. The badge subtracts `origin === "legacy_text"` entries, which is a heuristic — the authoritative count is the `newRules` list in the preview, which is what the user actually approves.
5. **The tolerance/threshold forms show shipped defaults, not the tenant's effective values** — see §4 for why.

---

## Verification

**Type check** — `npx tsc --noEmit`, exit code 0, clean. (One stale-artifact note: `.next/types` held generated route types for the two deleted proxy routes and had to be cleared; it regenerates.)

**Playwright — actually run, not asserted.** `npx playwright test`, full suite: **63 passed, 1 failed**.

* New `e2e/trainer-alert-anchored.spec.ts` — 5 tests, all passing:
  * `can_train: false` renders the permission state and **not** the workspace, and not the billing prompt either (FE Gap 232).
  * A tolerance-overridable alert offers the numeric tolerance form.
  * A `total_not_verified_in_source` alert offers **no** numeric form — the registry's explanation instead, asserting both `tolerance-form` and `threshold-form` are absent.
  * Commit runs `/preview` first and the confirm sends its exact token (asserted on the intercepted request body).
  * A `not_computable` impact renders the explanation and no sample list — the no-fabricated-zero guarantee.
* `e2e/trainer-loading-state.spec.ts` — rewritten (it stubbed the two removed endpoints and drove the old scope buttons); 2 tests passing.
* `e2e/group-a-layout-overflow.spec.ts` (4 Trainer tests) and `e2e/rbac-sidebar.spec.ts` (1) — updated for the removed `/sessions/global` stub and the renamed commit button; all passing.
* Both spec files needed `test.describe.configure({ timeout: 90_000 })` / an existing header wait: with `fullyParallel: true`, several workers race the dev server's first JIT compile of `/trainer`. Verified directly — the file passes in ~4s per test once compiled, and only the compile-racing runs timed out.

**The 1 failure is pre-existing and unrelated**: `group-a-layout-overflow.spec.ts › Gap 86 — Ingestion header row › toggle is absent for a receive-only tenant`, on `/ingestion`. **Confirmed pre-existing by re-running it with this pass's `app/`, `components/` and `lib/` changes stashed — it fails identically.** Nothing in this work touches `/ingestion`, `PageHeader` or the service-flow toggle.

**Not verified**: nothing here has been exercised against a real backend, a real tenant or real Azure OCR/LLM — every spec stubs `/api/**`. Specifically unverified end-to-end: the missed-alert LLM drafting round-trip, real preview impact numbers, the chat triage auto-diff against real stored data, and the inline PDF render in the triage dialog (the iframe is stubbed with placeholder bytes).

---

## §11. Reading the rules back — Settings › Chat Rules (FE Gap 478, 2026-09-14)

The lane above only ever **wrote** chat rules. `POST /chat/rules/commit` stored a
`TenantChatRule`, that rule was injected into every later question for the whole
workspace, and no screen in the product read it back — `GET /chat/rules` and
`DELETE /chat/rules/{rule_id}` had existed since Feature 18 with zero callers, and
the Trainer's `RuleHistoryDrawer` lists `ExtractionTemplate.rules` only and always
will, because the two stores are separate by design. The practical consequence the
founder hit: a rule taught from one bad answer silently re-scopes unrelated
questions, and the only way to even discover it existed was to open
`/api/chat/rules` in a browser tab.

**What was built.** A new tenant-wide settings screen, `/settings/chat-rules`:

* `ChatRulesSettingsPage` (`app/settings/chat-rules/page.tsx`) — owns fetching and
  mutation. `load()` fires `chatTrainingService.listRules()` and
  `chatTrainingService.getCategories()` in parallel; a categories failure is
  swallowed (`.catch(() => [])`) so a label lookup can never hide the rules
  themselves. `handleDelete(rule)` calls `chatTrainingService.deleteRule()` and
  drops the row from local state — the backend hard-deletes and flushes the answer
  cache, so there is no soft-deleted/greyed state to represent. Header via
  `usePageHeader` with `backHref: "/settings"`, matching the other settings
  subpages; errors render as generic strings, never a raw response body
  (the Website Gap 13 rule the webhooks screen established).
* `ChatRulesPanel` (`components/settings/ChatRulesPanel.tsx`) — presentational.
  One row per rule showing the literal `ruleText` that is injected, a category
  chip, "Added ‹timestamp›", the author when the API carries one (`createdBy` is
  nullable), and an `Inactive` chip when `enabled` is false. Delete is a per-row
  button that is **not rendered at all** without `canTrain`, replaced by an
  amber read-only notice; the confirm (`window.confirm`) lives with the
  affordance, since deleting a rule changes every future answer and cannot be
  undone. The empty state states where rules come from: a thumbs-down on a chat
  answer.
* `chatRuleCategoryLabel(category, labels)` — the label comes from the backend's
  own closed vocabulary (`GET /chat/rules/categories`); an unknown key degrades to
  a humanised form of the key. There is **no category map in the FE**, so a
  category added backend-side renders correctly with no frontend edit.
* `formatChatRuleAddedAt(createdAt)` — locale-formatted, `"Date unknown"` for a
  null or unparseable timestamp rather than `Invalid Date`.
* Registration: a `Chat Rules` tile in `app/settings/page.tsx`'s `INTEGRATIONS`
  list, deliberately **not** `adminOnly` — the list is readable by anyone who can
  open Settings and the destructive half is gated on `can_train`, the same
  permission `routers/chat.py::delete_chat_rule` enforces via `require_can_train`.
  The FE gate is discoverability; the backend is the control.
* **Sidebar entry (added 2026-09-14, founder decision on the same gap).** The tile
  above is only reachable through Settings, whose sidebar row is Admin-only — so a
  Trainer, the exact role that teaches these rules, still could not find the screen
  that reads them back. `Sidebar` (`components/layout/Sidebar.tsx`) now carries a
  `Chat Rules` row — `{ name: "Chat Rules", href: "/settings/chat-rules", icon:
  ScrollText, visible: canTrain }` — placed directly after `AI Trainer` in
  `menuItems`, since the two share a permission and a mental model. This is the FE
  Gap 143 pattern verbatim (`Subscriptions`, a `/settings/*` page promoted to its
  own nav row), with one deliberate difference: Subscriptions is gated on
  `role === "Admin"` because it is the billing record, whereas this row is gated on
  `canTrain` from `useAuth()`, matching the backend permission on delete. Admins
  pass `can_train` server-side (`dependencies.resolve_permissions`), so they see it
  too. No change was needed to the `activeHref` longest-prefix rule FE Gap 143
  added — `/settings` vs `/settings/chat-rules` is the same shape as
  `/settings` vs `/settings/subscriptions`, so only the deeper row lights up.
* **Settings is the long-term home.** `feature_22_today_ask_records.md` §3.3 had
  claimed its future `Records › Rules` tab would close FE Gap 478 by listing chat
  and extraction rules side by side. That claim was removed on 2026-09-14: that tab
  lists extraction rules only and links out to `/settings/chat-rules`, so there is
  one implementation and one delete affordance for chat rules, not two.

**Deviations from the proposal in the gap entry.** None on scope: no backend
change was needed, the proxy routes (`app/api/chat/rules/route.ts`,
`app/api/chat/rules/[ruleId]/route.ts`) and the service methods
(`listRules`/`deleteRule`) already existed unused. Two additions beyond the
proposal: the `Inactive` chip (the API returns `enabled`, and a disabled rule
misrepresented as active would be worse than not showing the field) and a
Refresh control.

**Boundary — what this does not do.** It cannot *edit* a rule (the backend has no
update endpoint; the workflow is delete and re-teach), cannot disable one without
deleting it (no PATCH for `enabled`), does not show which answers a rule has
affected, and does not surface the rule set anywhere inside chat itself. The
sidebar's own `Settings` row remains Admin-gated (unchanged): a non-Admin trainer
reaches this page by its dedicated `Chat Rules` row, not through Settings.

**Verification (FE Gap 478).** `npx tsc --noEmit` — exit 0, no output.
`npm test` (vitest) — `Test Files  5 passed (5)` / `Tests  44 passed (44)`,
including the new `tests/unit/chat-rules-panel.test.tsx` (9 tests) whose
assertions are properties of the render against a fixture the test mutates
(rules renamed, an unknown category substituted, a row added, the author
dropped), not literal expected strings.

**Live verification (functional-tester, 2026-09-14)** — this is what moved FE Gap
478 from `[~]` to `[x]`. Evidence:
`docs/test_evidence/fe_gap478_chat_rules_2026-09-14/README.md`. Against the local
stack with real Azure AI services and real Postgres (no `/api/**` stubbing,
`DISABLE_CLERK_AUTH=true`, Playwright chromium 1280x900): a rule was created
through the real `POST /chat/rules/preview` → `/commit` pair, `/settings/chat-rules`
rendered it with its category chip, full `ruleText` and
`"Added 14 Sept 2026, 08:31 by user_test_default"` (`before_delete.png`); the trash
affordance fired the confirm dialog and, on accept, the list fell to the
"No chat rules yet" empty state (`after_delete.png`); `GET /chat/rules` returned
`[]` and `SELECT id FROM tenant_chat_rules WHERE id='cfe830a9-…'` returned 0 rows,
confirming a hard delete rather than a soft disable. All three checks **PASS**.

**Sidebar entry verification.** `e2e/rbac-sidebar.spec.ts` gained a
`Sidebar — Chat Rules (FE Gap 478)` block: the row is visible and its `href` is
`/settings/chat-rules` for a `can_train` identity, absent for an identity holding
`can_audit` + `can_load` but not `can_train`, and visible for an Admin. The
existing exact-set assertions were extended in the same pass (`can_train` now
reveals `AI Trainer` **and** `Chat Rules`), and a pre-existing staleness was fixed
while there: FE Gap 464 added the `History` row on `can_audit` and this spec had
never been updated for it. `npx playwright test e2e/rbac-sidebar.spec.ts` —
`22 passed (1.5m)`.

**Still not covered:** the page's fetch/delete wiring has no *stubbed* Playwright
spec of its own — the live run above is the only browser evidence, so a
regression there would be caught by a manual run, not by CI.
