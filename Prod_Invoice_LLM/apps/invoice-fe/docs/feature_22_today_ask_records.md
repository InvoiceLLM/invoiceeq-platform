# Feature 22 — Today / Ask / Records / Settings: four surfaces, and the Analyst Agent's list

**App:** invoice-fe · **Status:** lives in `fe_features_tracker.md` · **Counterpart:** BE Feature 33 (`apps/invoice-be/docs/feature_33_analyst_agent.md`) — the agent, the facts ledger, the clearance model and `GET /today` are built there; this spec is the surface. **Depends on:** FE Feature 21 (`feature_21_business_intelligence.md`, the bubble this reuses), FE Feature 1.1 RBAC (role gating).

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

**The principle.** The system comes to the user. Today speaks first; every line on it opens Ask with the question already written; Records and Settings are where a user goes only to look something up or to change something once. **Nothing is removed from the product — it is re-sorted.**

**What this is not.** Not a redesign of the bubble (Feature 21 renders it; this places it). Not a dashboard — founder ruling stands, operational dashboards are Azure Workbooks; Today is a list of things that expect an action, not a metrics page. Not the onboarding advisor's content (that is Feature 32 / BE 33 §3.5); this spec renders its output.

**Three levels the founder can choose (§7 Q1).** (1) navigation only — collapse to four nav items, keep today's screens as tabs beneath; (2) merge — Today and Records built as specified, review stays a page; (3) chat-first — review and trainer become cards in Ask. This spec is written for level 3 and marks which tasks belong to each level.

## 2. File coordinates

| path | named component / hook | new or edit | what it does |
|---|---|---|---|
| `app/layout.tsx`, `components/nav/PrimaryNav.tsx` | `PrimaryNav` | edit / new | four items; role-aware (Settings only for Admin); the old routes redirect |
| `app/today/page.tsx` | `TodayPage` | new | the ranked list; polls `GET /today`; subscribes to `today_updated` on the tenant SSE channel |
| `components/today/TodayList.tsx` | `TodayList`, `TodaySection` (`Cash`, `Needs you` / `Decide`, `Due this week`, `This week`, `To see more`) | new | sections are role-aware: clerk sees `Needs you` / `Due` / `This week`; Admin additionally sees `Cash` / `Decide` / `To see more` |
| `components/today/TodayLine.tsx` | `TodayLine` | new | one sentence + one action (`Decide →` / `Review →` / `Confirm →` / `Options →` / `Attach →`); click → `POST /today/{id}/open` → navigate to Ask with the returned session |
| `components/today/PositionLine.tsx` | `PositionLine` | new | the one-sentence cash line from the forecast's certain tier, currency-keyed; never a tile row |
| `components/today/InputRequestLine.tsx` | `InputRequestLine` | new | "Attach your Rajesh contract → check every invoice vs agreed rates"; click opens Ask with the composer's attach control focused |
| `components/today/EmptyToday.tsx` | `EmptyToday` | new | "Nothing yet. Forward an invoice or ask me." with the inbox address and a drop zone |
| `app/ask/page.tsx` | `AskPage` | rename of `app/chat/page.tsx` | sessions rail + `ChatWindow`; `?session=` deep-link from Today; `?attach=1` focuses the attach control |
| `components/chat/SessionRail.tsx` | `SessionRail` | edit | grouped by day; 🔒 badge on `clearance="exec"` sessions; `+ New` with a private toggle for Admin |
| `components/chat/ChatWindow.tsx`, `components/chat/MessageBubble.tsx` | `MessageBubble` | edit | renders four new card kinds below (level 3) |
| `components/chat/cards/DecisionCard.tsx` | `DecisionCard` | new | a finding with two or three buttons; posts the chosen transition to `POST /chat/insights/{id}/transition`; the bubble updates in place |
| `components/chat/cards/ReviewCard.tsx` | `ReviewCard` | new (level 3) | the invoice review as a card: PDF thumbnail, flagged fields with printed vs computed, `Accept printed` / `Accept computed` / `Tell me why`; posts to the existing `resolve_audit_invoice()` and field-correction endpoints — no new BE |
| `components/chat/cards/TeachCard.tsx` | `TeachCard` | new (level 3) | the Trainer as a mode: the agent proposes the rule and its scope (this vendor / all), `Confirm` commits through the existing `POST /trainer/sessions/{id}/commit` path |
| `components/chat/cards/InsightCard.tsx` | `InsightCard` | edit of Feature 21's | adds the **checks passed / not checked** disclosure (BE Feature 30 task 30.19) and the investigate evidence thread (BE 33 §3.1 step 4) |
| `components/chat/Composer.tsx` | `Composer` | edit | placeholder "Ask, attach, or say 'teach'…"; `📎` + drop zone; "teach" prefix routes to `TeachCard` flow |
| `app/records/page.tsx` | `RecordsPage` with tabs `Invoices in` / `Invoices out` / `Documents` / `Rules` | new | wraps the existing tables |
| `components/records/InvoiceTable.tsx` | `InvoiceTable` | edit of `RecentInvoicesTable` / `OutboundInvoicesTable` | one component, `direction` prop; filters `Status` / `Month` / `Party`; search; export |
| `components/records/RecordDrawer.tsx` | `RecordDrawer` | new | PDF left, fields right, alerts, **facts** (linked PO, delivery events, payment events — from `facts_for()`), `Ask about this` (opens Ask seeded), `Edit`, `Delete` |
| `components/records/DocumentsTable.tsx` | `DocumentsTable` | new | every attachment that left facts, and where the facts went; exec rows only for exec clearance |
| `components/records/RulesTable.tsx` | `RulesTable` | new | BE Gap 514: extraction rules by scope (Global / vendor), opens `RuleHistoryDrawer`. **Chat rules are not duplicated here** — see §3.3 |
| `components/records/OutboundBuilderDrawer.tsx` | `OutboundBuilderDrawer` | wrap of Feature 20 | the one screen that stays a form; opened from `Invoices out` |
| `app/settings/page.tsx` | `SettingsPage` with sections `People` / `Inbox` / `Checks` / `Notify` / `Plan` / `Security` | rewrite | each section is today's sub-page's content, inline; the sub-routes redirect to `#section` |
| `components/onboarding/FirstRun.tsx` | `FirstRun` | new | first login: Ask opens with the advisor's three steps (people, inbox, drop one file) — content from BE 33 §3.5 / §3.7 (business profile, ex-Feature 32); skippable; never shown again |
| `lib/apiClient.ts` | `getToday()`, `openTodayItem()`, `getFacts()` | edit | |
| `app/api/today/route.ts`, `app/api/today/[id]/open/route.ts` | proxies | new | `proxyJson` to BE |
| `app/dashboard/page.tsx`, `app/chat/page.tsx`, `app/history/page.tsx`, `app/ingestion/page.tsx`, `app/trainer/page.tsx`, `app/invoices/review/[id]/page.tsx`, `app/invoices/outbound-review/[id]/page.tsx`, `app/admin/page.tsx`, `app/flows/page.tsx`, `app/debug-org/page.tsx`, `app/settings/*/page.tsx` | — | redirect / remove | per level (§6) |
| `components/dashboard/ActionableInsightsPanel.tsx` | — | **remove** | with BE 33.18 |

## 3. Functionality

### 3.1 Today

`TodayPage` loads `GET /today` (role and clearance resolved server-side) and renders `TodayList`. Each `TodayItem` is one sentence and one action; the sentence is the finding's gated narration or the input request's text; the action label comes from the item's kind. Sections render only when they have lines. Order within a section is the server's rank (severity, then amount). `today_updated` on the SSE channel triggers a refetch, so a clerk's decision clears the owner's line without a reload.

Click → `POST /today/{id}/open` → the server creates or resumes an Ask session seeded with the item's question and evidence → navigate to `/ask?session=…`. For input requests, `/ask?session=…&attach=1`.

Role: clerk sees `Needs you`, `Due this week`, `This week`; Auditor the same plus findings; Admin additionally `Cash`, `Decide`, `To see more`. Same endpoint, server-filtered.

### 3.2 Ask

Today's chat page, renamed, with three additions:

- **Seeded sessions** from Today: the first assistant turn is the finding card (`DecisionCard` or `InsightCard`) with its evidence; the user replies in the same thread and SAGE answers (BE 33 §3.6).
- **Cards as actions** (level 3): `DecisionCard` (finding transitions), `ReviewCard` (audit resolution and field correction), `TeachCard` (rule commit). Each posts to an endpoint that exists today; the card re-renders from the response. No new BE for these three.
- **Private sessions**: an Admin's `+ New` offers `Private` (sets `clearance="exec"`); exec sessions show 🔒 in the rail and are absent from every other role's rail — server-enforced (BE 33 §5), the badge is only a signal.

`FirstRun` is an Ask session with a fixed three-step script on first login: add people (inline form, posts to the existing user-invite endpoint), pick an inbox (copy the address / connect Drive / drop a file here), and the first document's bubble. Skippable; the same content is reachable later by asking "how do I add someone".

### 3.3 Records

Four tabs over existing data. `RecordDrawer` is the review surface for anyone who wants the full page rather than the card: same fields, same actions, plus the **facts** panel — the first place a user sees "PO-1041 linked · delivered on DC-0812 · unpaid" on an invoice. `Documents` is the ledger of attachments that left facts (BE 33 §4), which makes the persistence visible. `Rules` covers BE Gap 514.

**Chat rules are not a Records tab (amended 2026-09-14, founder).** This spec originally claimed `Rules` would close FE Gap 478 by listing extraction and chat rules side by side. FE Gap 478 was instead closed on 2026-09-14 by a dedicated settings screen, `/settings/chat-rules` (`ChatRulesSettingsPage` / `ChatRulesPanel`, feature_14 §11), with its own `can_train`-gated sidebar entry — and **Settings is the long-term home for chat rules**. So `RulesTable` lists extraction rules (`ExtractionTemplate.rules`) only, and the chat-rule half of the tab is a single link out to `/settings/chat-rules` rather than a second implementation of the same list. Two screens reading `GET /chat/rules` with two delete affordances is exactly the drift this avoids; `TenantChatRule` and `ExtractionTemplate.rules` are separate stores (models.py) and stay separately surfaced.

### 3.4 Settings

One scrolling page. Each section is the existing sub-page's component mounted inline; the old routes redirect to the anchor. Anything the agent configures in conversation ("stop flagging freight lines") also appears here under `Checks`, so configuration is visible without remembering the chat.

## 4. Data & schema changes

None in this app. BE Feature 33 owns `today_item`, `input_request`, `clearance`, `fact`.

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
| 22.14 | `FirstRun` three-step onboarding in Ask; shown once per user | L3 |
| 22.15 | Help content indexed as knowledge; `/help` redirects to Ask with "how do I…" seeded | L3 |
| 22.16 | Screenshot regression: Today (clerk, Admin, empty), Ask with each card kind, Records each tab, Settings — light and dark | all |

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
| 22.14 | first login shows `FirstRun`; second login does not; skip is honoured |
| 22.15 | "how do I add a user" returns the help content's answer with the People section link |
| 22.16 | screenshots attached per the functional-tester skill, both themes |

Every data assertion above is against fixtures; anything that reads live data goes through BE Feature 33's Postgres-verified endpoints and is not re-verified here.

## 7. Open decisions — founder

1. **Which level?** L1 (a week, navigation only), L2 (the real simplification; review stays a page), or L3 (chat-first; the product matches its thesis). Recommendation: L3, with L2 as the first checkpoint.
2. **Records as a fourth nav item, or a tab under Today?** Four items are proposed; three is possible if Records becomes Today's "everything" tab.
3. **Outbound Builder** stays a form in a drawer — agreed, or should it also become a guided conversation?
4. **Today for Auditor** — identical to clerk plus findings, or its own section set?
5. **`FirstRun` for non-Admin users** — a two-step version (inbox, drop a file), or nothing?
