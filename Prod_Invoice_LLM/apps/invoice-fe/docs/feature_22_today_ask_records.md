# Feature 22 — Today / Ask / Records / Settings: four surfaces, and ATLAS's list

**App:** invoice-fe · **Status:** spec amended 2026-09-15 per the BE Feature 33 founder interview (`FirstRun` content, the classic-layout toggle, Today's accept / edit / reject / confirm / dismiss / scenario actions, the ATLAS name) **and the same day's walkthrough rulings (classic-layout semantics, the routine-questionnaire card, Admin Run-now, native-picker upload, the pre-onboarding Today state, Trainer listing the onboarding answers) — tasks now 22.1–22.27**; build not started · lives in `fe_features_tracker.md` · **Counterpart:** BE Feature 33 (`apps/invoice-be/docs/feature_33_analyst_agent.md`) — the agent (**ATLAS**), the facts ledger, the clearance model and `GET /today` are built there; this spec is the surface. **Depends on:** FE Feature 21 (`feature_21_business_intelligence.md`, the bubble this reuses), FE Feature 1.1 RBAC (role gating).

**Founder framing, 2026-09-10:** "already there are too much complicated application with so many screens … feel free to discuss any level of changes to give end user very easy and also helpful experience, since all the components are developed just its too much information for an end user." Then, on the daily view: "so today is like dashboard + latest history screen type + insights" → yes, merged and stripped to what is actionable.

## 1. Overview

Twenty routes exist today, sorted by *which feature built them*. This feature sorts them by *what the user is trying to do*. Every user action is one of three: **what needs me** / **let me ask or do something** / **let me look something up** — so the navigation is three items plus Settings:

| Surface | Answers | What it replaces |
|---|---|---|
| **Today** | what needs me — ranked, in prose, role-aware | `/dashboard` (metrics, Needs Attention, Actionable Insights, Trainer Impact), `/ingestion` status, `/history` |
| **Ask** | the conversation — ask, attach, decide, correct, teach | `/chat`, `/trainer`, `/invoices/review/[id]`, `/invoices/outbound-review/[id]` |
| **Records** | the ledger — tables, filters, a drawer | `/invoices`, outbound list, `/invoices/outbound-builder` (as a drawer), ingestion log, rule history (FE Gap 478 / BE Gap 514) |
| **Settings** | one page, sections | `/settings` and its six sub-pages, `/admin`, `/flows`, `/settings/workflows`, `/settings/webhooks`, `/settings/connectors`, `/settings/email`, `/settings/subscriptions`, `/settings/security` |

`/debug-org` is removed. `/help` becomes the agent answering "how do I …" in Ask; the help content stays as retrievable knowledge.

**The principle.** The system comes to the user. Today speaks first; every line on it opens Ask with the question already written — or is answered in place (`Accept` / `Edit` / `Reject` a convention, `Confirm` an action, `Dismiss`, run a `Scenario`); Records and Settings are where a user goes only to look something up or to change something once. **Nothing is removed from the product — it is re-sorted.**

**Landing and the classic layout (ruled 2026-09-15; semantics corrected the same day — task 22.21).** Every login after onboarding lands on **Today**. A per-user **"classic layout"** switch turns that off. Exactly what each setting means:

| | switch off (**default**) | switch on (**classic**) |
|---|---|---|
| navigation | the four surfaces (`PrimaryNav`) | the **existing `components/layout/Sidebar.tsx` nav** as it is today — Dashboard, Ingest, Audit Queue, History, AI Trainer, Chat Rules, Chat, Settings, Subscriptions, Help — **with `Today` added as one more item** |
| landing route | `/today` | `/dashboard` |
| old routes | redirect to their new home | **render**, rather than redirect |

- The switch **control sits in `components/layout/Header.tsx`, next to the existing theme toggle** (Header.tsx:289–318). The theme toggle itself (`hooks/useTheme.ts`, Classic Dark / InfiNevo) is **untouched** — two independent switches in one place, not one combined control.
- It is **per user**, persisted through `PATCH /me/preferences` (BE 33.39, `User.ui_prefs.layout`), **not localStorage** — the preference must survive a device change.
- **One preference, read once at layout level. No per-route forks.**
- **Ruled 2026-09-15 (default, founder to override): the toggle stays indefinitely — no retirement date and no retirement trigger.** The earlier "expected to be retired once the four surfaces are the norm" wording is superseded.
- **Flag for the founder.** The ruling said "the current header tabs (Dashboard, Invoices, Chat, Trainer, Ingestion, Settings)". The real nav is a **sidebar with ten items** (listed above) and `Header.tsx` has **no tab bar at all** — bell, theme toggle and profile only. This is built **against the sidebar as it exists**; a header tab bar is not invented. Confirm the ten-item sidebar is what "classic" should keep, or name the six to keep.

**What this is not.** Not a redesign of the bubble (Feature 21 renders it; this places it). Not a dashboard — founder ruling stands, operational dashboards are Azure Workbooks; Today is a list of things that expect an action, not a metrics page. Not the onboarding advisor's content (that is BE 33 §3.7, which absorbed Feature 32); this spec renders its output. **Not the first-login experience either** — `FirstRun` is the welcome, checklist and tour (§3.2); ATLAS's Discover run happens later, after the first ingest batch settles (BE 33 §8 Q9), and is not part of first login.

**Three levels the founder can choose (§7 Q1).** (1) navigation only — collapse to four nav items, keep today's screens as tabs beneath; (2) merge — Today and Records built as specified, review stays a page; (3) chat-first — review and trainer become cards in Ask. This spec is written for level 3 and marks which tasks belong to each level.

## 2. File coordinates

| path | named component / hook | new or edit | what it does |
|---|---|---|---|
| `app/layout.tsx`, `components/nav/PrimaryNav.tsx` | `PrimaryNav` | edit / new | four items; role-aware (Settings only for Admin); the old routes redirect |
| `app/today/page.tsx` | `TodayPage` | new | the ranked list; polls `GET /today`; subscribes to `today_updated` on the tenant SSE channel |
| `components/today/TodayList.tsx` | `TodayList`, `TodaySection` (`Cash`, `Needs you` / `Decide`, `Due this week`, `This week`, `To see more`) | new | sections are role-aware: clerk sees `Needs you` / `Due` / `This week`; Admin additionally sees `Cash` / `Decide` / `To see more`. **Amended 2026-09-15 (22.26):** gains the **payment-run day grouping header** for payables. The role filter is the **server's** (BE 33.37) — same list, fewer lines, never a separate section set |
| `components/today/TodayLine.tsx` | `TodayLine` | new | one sentence + its affordance (`Decide →` / `Review →` / `Options →` / `Attach →`); click → `POST /today/{id}/open` → navigate to Ask with the returned session. Every line also carries `Dismiss` (`POST /today/{id}/dismiss`). **Amended 2026-09-15 (22.26):** also renders the four questionnaire-derived line kinds — the no-PO materials line, the pending-sign-off line, the month-close countdown and the collections-owner addressing. **Presentation only** — every figure, grouping and owner name comes from the server |
| `components/today/ConventionLine.tsx` | `ConventionLine` | new (ruled 2026-09-15) | a `ConventionProposal` answered **in place**: `Accept` / `Edit` / `Reject` → `POST /today/{id}/accept` · `/edit` · `/reject`; the line re-renders with the rule ATLAS wrote. Not a Trainer screen |
| `components/today/ActionLine.tsx` | `ActionLine` | new (ruled 2026-09-15) | an ATLAS action proposal (BE 33 §3.8): the sentence, the target, and one `Confirm` → `POST /today/{id}/confirm`. Rendered only when the user's role allows the action; a 403 renders the refusal on the line |
| `components/today/ScenarioControl.tsx` | `ScenarioControl` | new (ruled 2026-09-15) | on a forecast line: one change ("Kaveri pays 20 days late") → `POST /today/{id}/scenario` → the recomputed line, per currency |
| `components/today/PositionLine.tsx` | `PositionLine` | new | the one-sentence cash line from the forecast's certain tier, **one per currency** (no conversion, ruled 2026-09-15), plus the P&L projection line; never a tile row |
| `components/today/FpaLine.tsx` | `FpaLine` | new (ruled 2026-09-15) | one line per FP&A capability (P&L by period, margin per customer / item, budget variance, expense trend); a `NOT_CHECKED` capability renders its input request, **never an empty tile** |
| `components/today/InputRequestLine.tsx` | `InputRequestLine` | new | "Attach your Rajesh contract → check every invoice vs agreed rates"; click opens Ask with the composer's attach control focused |
| `components/today/EmptyToday.tsx` | `EmptyToday`, **`PreOnboardingToday`** | new | "Nothing yet. Forward an invoice or ask me." with the inbox address and a drop zone. **Amended 2026-09-15 (22.25):** also renders the **`pre_onboarding`** state — "upload to begin", the `docs_seen / docs_required` progress, the inbox address and the drop zone, and **no findings, no FP&A lines, no input requests**. A state distinct from the plain empty state |
| `components/today/QuestionnaireCard.tsx` | `QuestionnaireCard`, `QuestionChips`, `QuestionFreeText`, `SkipControl`, `QuestionnaireProgress` | new (22.22) | one question at a time from `GET /today/questionnaire`; a chip row **and** a free-text field for the same question; a `Skip` affordance on **every** question; a progress indicator; posts to `POST /today/questionnaire/answer`. Rendered in Ask, driven from Today. `collections_owner` renders a **user picker** with a free-text fallback; `approval_threshold` renders the ₹1,00,000 default as a prefilled value |
| `components/today/RunNowButton.tsx` | `RunNowButton` | new (22.23) | **Admin-only**; posts `POST /today/run`; disabled with a **countdown** while the 10-minute cooldown is live; renders the 429's `retry_after_seconds` **inline on the button**, not as a toast |
| `components/today/UploadButton.tsx`, `components/today/AttachButton.tsx` | `UploadButton`, `AttachButton` | new (22.24) | a **real `<input type="file">`** opening the browser's native picker, following the `components/ingestion/DropZone.tsx` pattern; post to the existing ingestion endpoint / `POST /chat/sessions/{id}/attachments`. **No new BE endpoint, no filesystem access, no directory picker** |
| `components/chat/cards/AttachPromptCard.tsx` | `AttachPromptCard` | new (22.24) | renders BE 33.34's `attach_prompt` bubble — the target and the accepted extensions the server sent — with its own `Attach` button |
| `components/layout/Header.tsx` | the layout switch, beside the existing theme toggle (Header.tsx:289–318) | **edit** (22.21) | hosts the classic-layout switch; the theme toggle (`hooks/useTheme.ts`) is unchanged |
| `components/layout/Sidebar.tsx` | the existing ten-item nav | **edit** (22.21) | gains a **`Today`** item, for the classic layout |
| `app/ask/page.tsx` | `AskPage` | rename of `app/chat/page.tsx` | sessions rail + `ChatWindow`; `?session=` deep-link from Today; `?attach=1` focuses the attach control |
| `components/chat/SessionRail.tsx` | `SessionRail` | **new — extracted** | **corrected 2026-09-15:** `components/chat/SessionRail.tsx` **does not exist**. The session rail lives **inline inside `app/chat/page.tsx`** (188 lines). Task 22.6 extracts it into this component and then adds: grouped by day; 🔒 badge on `clearance="exec"` sessions; `+ New` with a private toggle for Admin |
| `components/chat/MessageBubble.tsx` | `MessageStream` (exported at `MessageBubble.tsx:776`), `MessageBubble` | edit | **corrected 2026-09-15:** the message stream is `MessageStream`, exported from `MessageBubble.tsx` — not a separate file. Renders the new card kinds below (level 3) |
| `components/chat/cards/` | the directory itself | **new** | **corrected 2026-09-15:** `components/chat/cards/` **does not exist** and is created by task 22.10 before any card file lands in it |
| `components/chat/cards/DecisionCard.tsx` | `DecisionCard` | new | a finding with two or three buttons; posts the chosen transition to `POST /chat/insights/{id}/transition`; the bubble updates in place |
| `components/chat/cards/ReviewCard.tsx` | `ReviewCard` | new (level 3) | the invoice review as a card: PDF thumbnail, flagged fields with printed vs computed, `Accept printed` / `Accept computed` / `Tell me why`; posts to the existing `resolve_audit_invoice()` and field-correction endpoints — no new BE |
| `components/chat/cards/TeachCard.tsx` | `TeachCard` | new (level 3) | the Trainer as a mode: the agent proposes the rule and its scope (this vendor / all), `Confirm` commits through the existing `POST /trainer/sessions/{id}/commit` path |
| `components/chat/cards/InsightCard.tsx` | `InsightCard` | edit of Feature 21's | adds the **checks passed / not checked** disclosure (BE Feature 30 task 30.19) and the investigate evidence thread (BE 33 §3.1 step 4) |
| `components/chat/ChatWindow.tsx` | **`InputBar`** (inline at `ChatWindow.tsx:395`) | edit | **corrected 2026-09-15:** `components/chat/Composer.tsx` **does not exist**; the composer is `InputBar`, declared inline in `ChatWindow.tsx`. Placeholder "Ask, attach, or say 'teach'…"; `📎` + drop zone; "teach" prefix routes to the `TeachCard` flow; `?attach=1` focuses its attach control |
| `app/records/page.tsx` | `RecordsPage` with tabs `Invoices in` / `Invoices out` / `Documents` / `Rules` | new | wraps the existing tables |
| `components/records/InvoiceTable.tsx` | `InvoiceTable` | edit of `RecentInvoicesTable` / `OutboundInvoicesTable` | one component, `direction` prop; filters `Status` / `Month` / `Party`; search; export |
| `components/records/RecordDrawer.tsx` | `RecordDrawer` | new | PDF left, fields right, alerts, **facts** (linked PO, delivery events, payment events — from `facts_for()`), `Ask about this` (opens Ask seeded), `Edit`, `Delete` |
| `components/records/DocumentsTable.tsx` | `DocumentsTable` | new | every attachment that left facts, and where the facts went; exec rows only for exec clearance |
| `components/records/RulesTable.tsx` | `RulesTable` | new | BE Gap 514: extraction rules by scope (Global / vendor), opens `RuleHistoryDrawer`. **Chat rules are not duplicated here** — see §3.3 |
| `components/records/OutboundBuilderDrawer.tsx` | `OutboundBuilderDrawer` | wrap of Feature 20 | the one screen that stays a form; opened from `Invoices out` |
| `app/settings/page.tsx` | `SettingsPage` with sections `People` / `Inbox` / `Checks` / `Notify` / `Plan` / `Security` | rewrite | each section is today's sub-page's content, inline; the sub-routes redirect to `#section` |
| `components/onboarding/FirstRun.tsx` | `FirstRun`, `WelcomeStep`, `SetupChecklist`, `AppTour`, `PathChoice` | new | first login, **content ruled 2026-09-15**: the org creator (Admin) gets a welcome message, a setup checklist, a short app tour and a **choice of path** — *Set up first* or *Ingest documents first*; invited non-Admin users get welcome + tour only. Skippable, shown once per user. **No Discover run here** |
| `components/settings/LayoutPreference.tsx` | `LayoutPreference` | new (ruled 2026-09-15) | four surfaces (default) vs **classic layout**, per user. **Amended 2026-09-15 (22.21):** persists through **`PATCH /me/preferences`** (BE 33.39), not localStorage; the **control is placed in `Header.tsx` beside the theme toggle**, with this component as the Settings-side mirror of the same preference; classic = the existing sidebar nav plus a `Today` item, landing `/dashboard`. The toggle **stays indefinitely** — no retirement trigger |
| `components/settings/ChatRulesPanel.tsx` (`/settings/chat-rules`, feature_14 §11) | `ChatRulesSettingsPage`, `ChatRulesPanel` | edit (22.27) | also lists the **routine answers** (`GET /today/routine-answers`, `source="atlas_onboarding"`) and the `source="atlas"` chat rules **alongside** the hand-written ones, editable via `PATCH /today/routine-answers/{key}`. Per §3.3 this is **Settings — not a Records tab and not a second list** |
| `app/api/today/questionnaire/route.ts`, `.../questionnaire/answer/route.ts`, `.../routine-answers/route.ts`, `.../routine-answers/[key]/route.ts`, `app/api/today/run/route.ts`, `app/api/me/preferences/route.ts` | proxies | new | `proxyJson` from **`lib/backendProxy.ts` (line 142)** — the same helper every other proxy route uses |
| **`lib/today.ts`** | `getToday()`, `openTodayItem()`, `dismissTodayItem()`, `acceptTodayItem()`, `editTodayItem()`, `rejectTodayItem()`, `confirmTodayItem()`, `runTodayScenario()`, `getFacts()`, **`runTodayNow()`**, **`getQuestionnaire()`**, **`answerQuestionnaire()`**, **`getRoutineAnswers()`**, **`editRoutineAnswer()`**, **`getPreferences()`**, **`setPreferences()`** | **new** | **corrected 2026-09-15:** the original row said `lib/apiClient.ts` gains these methods. `lib/apiClient.ts` is a **7-line bare axios instance**, not a method surface. The real pattern is one module per feature — `lib/chatInsights.ts`, `lib/chatAttachments.ts`, `lib/trainer-service.ts` — so this is a new `lib/today.ts` following `lib/chatInsights.ts` |
| `app/api/today/route.ts`, `app/api/today/[id]/open/route.ts`, `.../dismiss`, `.../accept`, `.../edit`, `.../reject`, `.../confirm`, `.../scenario` | proxies | new | `proxyJson` to BE |
| `app/dashboard/page.tsx`, `app/chat/page.tsx`, `app/history/page.tsx`, `app/ingestion/page.tsx`, `app/trainer/page.tsx`, `app/invoices/review/[id]/page.tsx`, `app/invoices/outbound-review/[id]/page.tsx`, `app/admin/page.tsx`, `app/flows/page.tsx`, `app/debug-org/page.tsx`, `app/settings/*/page.tsx` | — | redirect / remove | per level (§6) |
| `components/dashboard/ActionableInsightsPanel.tsx` | — | **remove** | with BE 33.18 |

## 3. Functionality

### 3.1 Today

`TodayPage` loads `GET /today` (role and clearance resolved server-side) and renders `TodayList`. Each `TodayItem` is one sentence and one action; the sentence is the finding's gated narration or the input request's text; the action label comes from the item's kind. Sections render only when they have lines. Order within a section is the server's rank (severity, then amount). `today_updated` on the SSE channel triggers a refetch, so a clerk's decision clears the owner's line without a reload.

Click → `POST /today/{id}/open` → the server creates or resumes an Ask session seeded with the item's question and evidence → navigate to `/ask?session=…`. For input requests, `/ask?session=…&attach=1`.

**Answered in place (ruled 2026-09-15).** Not every line goes to Ask. Three kinds are resolved on Today itself, because that is where ATLAS is talking:

| line kind | affordances | posts to |
|---|---|---|
| convention proposal (`ConventionLine`) | `Accept` · `Edit` · `Reject` | `POST /today/{id}/accept` · `/edit` · `/reject` — the rule is written to the existing extraction / chat-rule store with `source="atlas"`; the Trainer then merely lists it |
| action proposal (`ActionLine`) | `Confirm` (role-gated; hidden when the role is not allowed) | `POST /today/{id}/confirm` — one execution, logged BE-side; a 403 renders on the line |
| forecast line (`ScenarioControl`) | one change → recompute | `POST /today/{id}/scenario` |
| any line | `Dismiss` | `POST /today/{id}/dismiss` — the line clears and the dismissal feeds ATLAS's `learn()` |
| routine question (`QuestionnaireCard`, ruled 2026-09-15) | chip · free text · `Skip` | `POST /today/questionnaire/answer` — one question per call; the next question replaces it in place |

Cash and FP&A lines are per currency, never blended, and an FP&A line with a missing input renders its input request rather than an empty tile (BE 33 §3.4).

Role: clerk sees `Needs you`, `Due this week`, `This week`; Auditor the same plus findings; Admin additionally `Cash`, `Decide`, `To see more`. Same endpoint, server-filtered.

**Non-Admin Today (ruled 2026-09-15, default, founder to override — closes §7 Q4).** A non-Admin gets the **same ranked list**, filtered server-side by clearance and role — **not a separate section set**. The **owner-facing lines are hidden**: payment-run grouping, pending sign-off, the setup actions, the convention proposals and the cash / FP&A lines. The FE renders exactly what the server sent and filters nothing itself.

**Before ATLAS has enough to say (ruled 2026-09-15, task 22.25).** While `GET /today` returns `{state: "pre_onboarding", docs_seen, docs_required}` (below BE's `ANALYST_ONBOARD_MIN_DOCS`), the page renders **only** "upload to begin" with the progress count, the inbox address and a drop zone — **no findings, no FP&A, no input requests, no proposals**. Distinct from the plain empty state.

**Run now — Admin (ruled 2026-09-15, task 22.23).** `RunNowButton` posts `POST /today/run`. While the 10-minute cooldown is live the button is **disabled with a countdown**; a 429 renders its `retry_after_seconds` **inline on the button**, not as a toast. Hidden entirely for non-Admins.

**Getting documents in (ruled 2026-09-15, task 22.24).** `Upload` and `Attach` are the **browser's own native file picker** (a real `<input type="file">`, the `components/ingestion/DropZone.tsx` pattern) posting to the existing ingestion endpoint and `POST /chat/sessions/{id}/attachments`. An `attach_prompt` bubble from BE 33.34 renders as `AttachPromptCard` with its own `Attach` button. **The FE never asks the backend to read a path**, and no new BE endpoint is introduced. The existing `/ingestion` page stays, reachable under Records.

**Questionnaire-derived lines (ruled 2026-09-15, task 22.26).** `TodayList` renders the payment-run day grouping header; `TodayLine` renders the no-PO materials line, the pending-sign-off line, the month-close countdown and the collections-owner addressing. **Presentation only** — every figure and every grouping decision is the server's (BE 33.30 is deterministic code).

### 3.2 Ask

Today's chat page, renamed, with three additions:

- **Seeded sessions** from Today: the first assistant turn is the finding card (`DecisionCard` or `InsightCard`) with its evidence; the user replies in the same thread and SAGE answers (BE 33 §3.6).
- **Cards as actions** (level 3): `DecisionCard` (finding transitions), `ReviewCard` (audit resolution and field correction), `TeachCard` (rule commit). Each posts to an endpoint that exists today; the card re-renders from the response. No new BE for these three.
- **Private sessions**: an Admin's `+ New` offers `Private` (sets `clearance="exec"`); exec sessions show 🔒 in the rail and are absent from every other role's rail — server-enforced (BE 33 §5), the badge is only a signal.

**`FirstRun` — content ruled 2026-09-15** (this replaces the original three-step script of add-people / pick-an-inbox / first-bubble):

| user | sees |
|---|---|
| org creator (Admin) | welcome message · setup checklist · short app tour · **choice of path**: *Set up first* or *Ingest documents first* |
| invited non-Admin | welcome message · short app tour (no checklist, no path choice) |

**Amended 2026-09-15 — the path choice now leads somewhere.** After the Admin's `PathChoice`: **Set up first** → the **routine questionnaire** (BE 33 §3.7, `QuestionnaireCard`) starts immediately; **Ingest documents first** → the questionnaire starts **right after the first Discover completes**, not at login. The two entry points are distinct, and the FE passes the chosen path to `GET /today/questionnaire`.

**Where "once per user" is stored (amended 2026-09-15).** `first_run_seen` and `tour_seen` persist in `User.ui_prefs` via `GET` / `PATCH /me/preferences` (BE 33.39). Until that task lands there is **no store for "once per user" at all** — no preference table and no `first_run_seen` column exist today (confirmed 2026-09-15), so 22.14 depends on BE 33.39.

Still skippable, still shown once per user; the same content stays reachable later by asking "how do I add someone". **Discover is not part of first login** — ATLAS profiles the business only after the first ingest batch settles (BE 33 §8 Q9), so nothing on this screen waits on an analysis run. This also closes §7 Q5 (`FirstRun` for non-Admin users): tour only, not a two-step version.

After `FirstRun` — and on every later login — the landing surface is **Today**, unless the user has switched on the classic layout in Settings (§3.4).

### 3.3 Records

Four tabs over existing data. `RecordDrawer` is the review surface for anyone who wants the full page rather than the card: same fields, same actions, plus the **facts** panel — the first place a user sees "PO-1041 linked · delivered on DC-0812 · unpaid" on an invoice. `Documents` is the ledger of attachments that left facts (BE 33 §4), which makes the persistence visible. `Rules` covers BE Gap 514.

**Chat rules are not a Records tab (amended 2026-09-14, founder).** This spec originally claimed `Rules` would close FE Gap 478 by listing extraction and chat rules side by side. FE Gap 478 was instead closed on 2026-09-14 by a dedicated settings screen, `/settings/chat-rules` (`ChatRulesSettingsPage` / `ChatRulesPanel`, feature_14 §11), with its own `can_train`-gated sidebar entry — and **Settings is the long-term home for chat rules**. So `RulesTable` lists extraction rules (`ExtractionTemplate.rules`) only, and the chat-rule half of the tab is a single link out to `/settings/chat-rules` rather than a second implementation of the same list. Two screens reading `GET /chat/rules` with two delete affordances is exactly the drift this avoids; `TenantChatRule` and `ExtractionTemplate.rules` are separate stores (models.py) and stay separately surfaced.

**The Trainer also lists the onboarding answers (ruled 2026-09-15, task 22.27).** `/settings/chat-rules` (`ChatRulesSettingsPage` / `ChatRulesPanel`) lists the six **routine answers** — BE's new `tenant_profile_rule` rows, `source="atlas_onboarding"`, read through `GET /today/routine-answers` and edited through `PATCH /today/routine-answers/{key}` — and the `source="atlas"` chat rules, **alongside** the hand-written ones. Same screen, one list, per §3.3 above: **Settings is the home; not a Records tab and not a second list.** The questionnaire is the only place these are *asked*; the Trainer is the register.

### 3.4 Settings

One scrolling page. Each section is the existing sub-page's component mounted inline; the old routes redirect to the anchor. Anything the agent configures in conversation, or that a user accepted as a convention on Today ("stop flagging freight lines", `source="atlas"`), also appears here under `Checks`, so configuration is visible without remembering the chat.

**Classic layout toggle (ruled 2026-09-15; semantics corrected the same day — see §1, task 22.21).** `LayoutPreference` is the Settings-side mirror of the preference; the **control itself sits in `components/layout/Header.tsx` next to the existing theme toggle** (Header.tsx:289–318), which is left untouched. Classic on → the **existing `components/layout/Sidebar.tsx` ten-item nav** renders **with `Today` added as one item**, the old routes render instead of redirecting, and the landing route is **`/dashboard`**. Classic off (default) → the four surfaces, landing `/today`. Per user, persisted through **`PATCH /me/preferences`** (BE 33.39) rather than localStorage, so it survives a device change. One preference, read once at layout level; no per-route forks. **The toggle stays indefinitely — no retirement date, no trigger** (ruled 2026-09-15, default, founder to override).

## 4. Data & schema changes

None in this app. BE Feature 33 owns `today_item`, `input_request`, `clearance`, `fact`, `tenant_profile_rule` (the six routine answers) and **`user.ui_prefs`** — which this app reads and writes through `GET` / `PATCH /me/preferences` (BE 33.39) for `layout`, `first_run_seen`, `tour_seen` and `questionnaire_progress`.

## 5. Tasks

Level markers: **L1** navigation only · **L2** merge · **L3** chat-first. L1 ⊂ L2 ⊂ L3.

| # | task | level |
|---|---|---|
| 22.1 | `PrimaryNav` with four items, role-aware; every old route redirects to its new home (tab or anchor); `/debug-org` removed | L1 |
| 22.2 | `RecordsPage` tabs wrapping the existing invoice tables; `InvoiceTable` unified with a `direction` prop; `OutboundBuilderDrawer` | L1 |
| 22.3 | `SettingsPage` single page with sections; sub-routes redirect to anchors | L1 |
| 22.4 | `TodayPage`, `TodayList`, `TodayLine`, `EmptyToday`; `GET /today` proxy; SSE refetch; role-aware sections | L2 |
| 22.5 | `PositionLine` and `InputRequestLine`; `open` flow into Ask with `?session=` / `&attach=1` | L2 |
| 22.6 | `AskPage` rename; `SessionRail` grouped by day, 🔒 badge, Admin `Private` toggle; seeded first turn renders the finding card | L2 |
| 22.7 | `RecordDrawer` with the facts panel (`getFacts()`); `DocumentsTable` | L2 |
| 22.8 | `RulesTable` — extraction rules by scope (BE Gap 514); chat rules are a link to `/settings/chat-rules`, not a second list (FE Gap 478 already closed there) | L2 |
| 22.9 | Remove `ActionableInsightsPanel`, `MetricsGrid` as a page, `NeedsAttentionWidget` as a page (their data is Today's); `/dashboard` redirects to `/today` | L2 |
| 22.10 | `DecisionCard` in `MessageBubble`; transitions post and re-render in place | L2 |
| 22.11 | `InsightCard` checks-passed / not-checked disclosure and evidence thread | L2 |
| 22.12 | `ReviewCard`: review as a card, posting to the existing audit-resolve and field-correction endpoints; `/invoices/review/[id]` redirects to Ask seeded with that invoice | L3 |
| 22.13 | `TeachCard` and the "teach" composer mode; `/trainer` redirects to Ask | L3 |
| 22.14 | `FirstRun` (**content ruled 2026-09-15**): Admin → welcome + setup checklist + app tour + path choice (*Set up first* / *Ingest documents first*); invited non-Admin → welcome + tour only. Skippable, shown once per user; no Discover run | L3 |
| 22.15 | Help content indexed as knowledge; `/help` redirects to Ask with "how do I…" seeded | L3 |
| 22.16 | Screenshot regression: Today (clerk, Admin, empty), Ask with each card kind, Records each tab, Settings — light and dark | all |
| 22.17 | `LayoutPreference` in Settings (ruled 2026-09-15): per-user **classic layout** toggle; default = four surfaces; every login after onboarding lands on Today. **Corrected semantics, header placement and `/me/preferences` persistence are 22.21** — build 22.21, not this row's original wording | L2 |
| 22.18 | `ConventionLine` — `Accept` / `Edit` / `Reject` answered on Today, posting to `/today/{id}/accept` · `/edit` · `/reject`; the line re-renders with the written rule (ruled 2026-09-15) | L2 |
| 22.19 | `ActionLine` — role-gated `Confirm` → `POST /today/{id}/confirm`; 403 rendered on the line; `Dismiss` on every line → `POST /today/{id}/dismiss` (ruled 2026-09-15) | L2 |
| 22.20 | `ScenarioControl` on forecast lines → `POST /today/{id}/scenario`; `PositionLine` and `FpaLine` per currency, `NOT_CHECKED` FP&A lines render their input request and never an empty tile (ruled 2026-09-15) | L2 |
| **22.21** | **Classic layout, corrected semantics** (walkthrough ruling 6) — amends 22.17. `LayoutPreference` persists through `PATCH /me/preferences` (**BE 33.39**), not localStorage; the **switch control goes in `components/layout/Header.tsx` beside the existing theme toggle** (Header.tsx:289–318), leaving `hooks/useTheme.ts` untouched; classic on → the existing **`Sidebar.tsx` ten-item nav with `Today` added**, old routes **render**, landing `/dashboard`; classic off (default) → four surfaces, landing `/today`. One preference read once at layout level, no per-route forks. The toggle **stays indefinitely**. **Founder flag in §1:** the ruling said "header tabs"; the real nav is a ten-item sidebar and `Header.tsx` has no tab bar — built against the sidebar as it exists | L2 |
| **22.22** | **`components/today/QuestionnaireCard.tsx`** (walkthrough ruling 1) — rendered in Ask, driven from Today. One question at a time from `GET /today/questionnaire`; a **chip row and a free-text field for the same question**; a `Skip` on every question; a progress indicator; posts to `POST /today/questionnaire/answer`. Triggered at **first login on the Setup path** (from `PathChoice`) or **right after the first Discover on the Ingest path**. `collections_owner` → user picker with free-text fallback; `approval_threshold` → the ₹1,00,000 default prefilled. **Needs BE 33.29** | L2 |
| **22.23** | **`components/today/RunNowButton.tsx`** (walkthrough ruling 2) — Admin-only, posts `POST /today/run`, disabled with a **countdown** during the 10-minute cooldown, renders the 429's `retry_after_seconds` **inline on the button** rather than as a toast | L2 |
| **22.24** | **Upload / Attach affordances** (walkthrough ruling 4) — `components/today/UploadButton.tsx` and `components/today/AttachButton.tsx` open the **browser's native file picker** (a real `<input type="file">`, the `components/ingestion/DropZone.tsx` pattern) and post to the existing ingestion endpoint / `POST /chat/sessions/{id}/attachments`; `components/chat/cards/AttachPromptCard.tsx` renders BE 33.34's `attach_prompt` bubble with its own Attach button. **No new BE endpoint, no filesystem access, no directory picker.** The `/ingestion` page stays, under Records | L2 |
| **22.25** | **Pre-onboarding Today** (walkthrough ruling 9) — `EmptyToday` gains the `pre_onboarding` state: "upload to begin", the `docs_seen / docs_required` progress, the inbox address and the drop zone, and **no findings, no FP&A lines, no input requests**. Distinct from the plain empty state | L2 |
| **22.26** | **Questionnaire-derived line rendering** (walkthrough ruling 1) — `TodayList` gains the payment-run day grouping header; `TodayLine` renders the no-PO materials line, the pending-sign-off line, the month-close countdown and the collections-owner addressing. **Presentation only** — every figure and grouping comes from the server | L2 |
| **22.27** | **Trainer shows the onboarding answers as editable rules** (walkthrough ruling 1) — the existing `/settings/chat-rules` screen (`ChatRulesSettingsPage` / `ChatRulesPanel`, feature_14 §11) lists `source="atlas_onboarding"` routine answers (`GET /today/routine-answers`, `PATCH /today/routine-answers/{key}`) and `source="atlas"` rules alongside the hand-written ones, with edit. Per §3.3 this is **Settings — not a Records tab, not a second list** | L2 |

**Build order (ruled 2026-09-15).** FE checkpoint 1 = L1 + L2 minus the two BE-gated tasks: 22.1–22.11, 22.17, 22.18, 22.19, 22.20, 22.21, 22.23, 22.24, 22.25, 22.26 — gate: `node node_modules/typescript/bin/tsc --noEmit` exit 0, `npx vitest run` green, Playwright on the touched specs. FE checkpoint 2 = 22.22 (needs BE 33.29), 22.27, then L3's 22.12, 22.13, 22.14 (needs BE 33.39), 22.15, 22.16 — gate: `tsc --noEmit`, full `vitest`, full Playwright including 22.16's screenshot regression in both themes. **L3 does not start before FE checkpoint 1 passes.**

## 6. Verification plan

| task | proves it |
|---|---|
| 22.1 | every old route returns a redirect to a `/today`, `/ask`, `/records?tab=`, or `/settings#` URL (route test over the list in §2); `PrimaryNav` renders 3 items for Auditor, 4 for Admin |
| 22.2 | the unified table renders the same rows for `direction=in` as `RecentInvoicesTable` did on the same fixture; builder drawer opens and submits through Feature 20's existing handler |
| 22.3 | each section mounts the existing component; deep-link `#inbox` scrolls to it |
| 22.4 | fixture `GET /today` with 5 items across 3 sections renders 5 lines in server order; an SSE `today_updated` triggers exactly one refetch; clerk fixture never renders `Cash` / `Decide` / `To see more` |
| 22.5 | clicking a line calls `POST /today/{id}/open` once and navigates with the returned session id; an input request navigates with `attach=1` and the composer's attach control has focus |
| 22.6 | an exec session is badged; a session list fixture for an Auditor contains no exec rows (the FE never filters — the assertion is that it renders exactly what the server sent); seeded session's first bubble is a `DecisionCard` |
| 22.7 | drawer on RAJ-2008 fixture shows three facts in order (commitment, delivery, payment); `Ask about this` opens Ask seeded with the invoice number |
| 22.8 | two vendor templates + one Global render as three groups; a vendor with zero rules is absent; the tab renders exactly one link to `/settings/chat-rules` and makes no `GET /chat/rules` call of its own |
| 22.9 | `/dashboard` → `/today`; no import of `ActionableInsightsPanel` remains (grep test) |
| 22.10 | `Duplicate` on a `DecisionCard` posts the transition and the bubble re-renders `ACTED` without a page reload |
| 22.11 | a card with 3 passed / 1 not-checked renders both counts and the not-checked subjects on expand |
| 22.12 | `Accept computed` posts to the same endpoint the review page did, with the same body (recorded fixture); the old review URL redirects to a seeded session |
| 22.13 | typing "teach: freight is not taxable for Rajesh" yields a `TeachCard` with scope defaulted to Rajesh; `Confirm` posts to the existing commit endpoint |
| 22.14 | first login shows `FirstRun`; second login does not; skip is honoured. Admin fixture renders welcome + checklist + tour + both path buttons; invited non-Admin fixture renders welcome + tour and **neither** the checklist nor the path choice; no `GET /today` analysis call is made from `FirstRun`. **Amended 2026-09-15:** assert `first_run_seen` is **read from and written to `/me/preferences`**, not localStorage; and that `Set up first` starts the questionnaire immediately while `Ingest documents first` does not |
| 22.17 | default preference → login lands on `/today`; classic on → login lands on the old dashboard and the old routes render rather than redirect; the preference is per user (two fixtures, one tenant) |
| 22.18 | `Accept` on a convention line posts to `/today/{id}/accept` once and the line re-renders with the rule text; `Edit` submits the edited text; `Reject` removes the line; no navigation to Ask or the Trainer occurs |
| 22.19 | an action line for an allowed role renders `Confirm` and posts once; for a disallowed role the button is absent, and a forced post's 403 renders on the line; `Dismiss` posts once and the line disappears |
| 22.20 | a two-currency forecast fixture renders two `PositionLine`s and no blended total; a scenario change posts once and re-renders the returned line; an FP&A fixture with `period_accounts` absent renders the input request text, never an empty tile |
| 22.15 | "how do I add a user" returns the help content's answer with the People section link |
| 22.16 | screenshots attached per the functional-tester skill, both themes |
| **22.21** | default preference → login lands on **`/today`**; classic on → login lands on **`/dashboard`**, the `Sidebar.tsx` nav renders and **`Today` is present as an item**, and the old routes render rather than redirect; the switch renders **in the header beside the theme toggle** and the theme toggle still works independently; the preference is **per user across two fixtures in one tenant** and round-trips through `/me/preferences` (no localStorage write asserted) |
| **22.22** | **one question at a time**; both the chip path and the free-text path post the same `key`; `Skip` posts a skip and the next question renders; the progress indicator advances; a Setup-path fixture renders the first question at first login and an Ingest-path fixture renders **nothing** until the Discover-complete signal; `collections_owner` renders the user picker with a free-text fallback |
| **22.23** | Admin fixture renders the button and posts once; a non-Admin fixture does **not** render it; a 429 fixture renders `retry_after_seconds` **on the button** with a live countdown and **no toast**; the button is disabled for the duration |
| **22.24** | the Attach control is a **real native `<input type="file">`** (asserted on the element, not a mock) posting to the **existing** endpoint; no request to any new upload path; an `attach_prompt` fixture renders `AttachPromptCard` with the server's target and accepted extensions |
| **22.25** | a `pre_onboarding` fixture renders "upload to begin", the `docs_seen / docs_required` count, the inbox address and the drop zone, and **zero** finding / FP&A / input-request lines; a threshold-crossed fixture renders the list instead |
| **22.26** | each of the five line kinds renders from its fixture: the payment-run grouping header, the no-PO materials line, the pending-sign-off line, the month-close countdown, the collections-owner addressing — and **no figure is computed client-side** (grep-shaped assertion) |
| **22.27** | the `/settings/chat-rules` fixture lists `source="atlas_onboarding"` answers beside hand-written rules with an edit affordance; an edit posts `PATCH /today/routine-answers/{key}` once; **no second list and no Records tab renders them** |

Every data assertion above is against fixtures; anything that reads live data goes through BE Feature 33's Postgres-verified endpoints and is not re-verified here.

## 7. Open decisions — founder

1. **Which level?** L1 (a week, navigation only), L2 (the real simplification; review stays a page), or L3 (chat-first; the product matches its thesis). Recommendation: L3, with L2 as the first checkpoint.
2. **Records as a fourth nav item, or a tab under Today?** Four items are proposed; three is possible if Records becomes Today's "everything" tab.
3. **Outbound Builder** stays a form in a drawer — agreed, or should it also become a guided conversation?
4. **Today for Auditor** — identical to clerk plus findings, or its own section set?
   **Ruled 2026-09-15 (default, founder to override):** the **same ranked list**, filtered server-side by clearance and role — **not its own section set**. The owner-facing lines are hidden for non-Admins: payment-run grouping, pending sign-off, setup actions, convention proposals, cash / FP&A. This also settles the questionnaire-derived lines, which are Admin-facing. §3.1, BE 33 §3.10 / task 33.37.
5. **`FirstRun` for non-Admin users** — a two-step version (inbox, drop a file), or nothing?
   **Ruled 2026-09-15:** neither. Invited non-Admin users get the **welcome message and the short app tour only** — no setup checklist, no path choice (those are the org creator's). §3.2, task 22.14.
