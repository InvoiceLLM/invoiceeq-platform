# Feature 23 — The work screen

**App:** invoice-fe · **Status:** spec, build not started · lives in `fe_features_tracker.md`
· **Counterpart:** BE Feature 34 (`apps/invoice-be/docs/feature_34_atlas.md`) — ATLAS itself.
**Supersedes:** FE Feature 22 (`feature_22_today_ask_records.md`), kept not deleted — it holds
the founder framing and walkthrough rulings this spec reverses.
**Decision record:** `apps/invoice-be/docs/atlas_discussion.md` (D1–D33).

**BE Feature 34 owns every contract.** Payload shapes, field names, event names, enum values and
the capability model are defined there and **referenced here, never restated**. Where this spec
needs a field it cites the BE section. That rule exists because the F22/F33 seam produced this
session's worst defects — a field the FE read that the BE never emitted, a live event promised by
both specs and published by neither.

---

## 1. What this is

**A user signs in and lands on their work.** Recommendations shaped by what they can act on, with
a conversation attached to every line (D9).

Not four surfaces. Not a navigation model. **One screen, and it is the app.**

### 1.1 What Feature 22 got right, and where it went

The founder's framing on 2026-09-10 was correct: *"too much complicated application with so many
screens … too much information for an end user."* Feature 22's answer was to re-sort twenty routes
into four. **This spec's answer is to give each person one screen of their own work.**

Of Feature 22's four surfaces, exactly one was new. `/ask` was `<ChatScreen title="Ask">`.
Settings was the existing settings relaid out. Records was the existing ledger plus a placeholder
tab. **Today was the only thing that did not already exist**, and it is what survives here.

### 1.2 Structure (D9, D10, D33)

| | |
|---|---|
| **The work screen** | Where a user lands. Their recommendations, ranked |
| **Chat** | Attached to every line, **not a tab**. Keeps its own route for direct use |
| **Records** | **Unchanged**, behind a menu. A ledger: searchable, filterable, exportable |
| **Settings** | **Unchanged**, behind a menu. ATLAS proposes most changes in place (BE 34 §7.2); the page remains for deliberate visits |
| `/trainer`, `/ingestion` | Keep their own routes, as today |

**Records and Settings are not rebuilt and not re-homed** (D33). Lookup is a search box, not an
agent's job. The earlier instinct to re-home them came from their place in the four-surfaces
model, not from any user need.

**Deleted:** `PrimaryNav`, the legacy redirect table, `NEXT_PUBLIC_FOUR_SURFACES`, and the
classic-layout toggle — which was specced to stay indefinitely and now has no duality to toggle
between (D10).

**FE Gaps 501 and 502 close by deletion.** Nothing redirects away from `/invoices/review/:id` or
`/trainer`, so neither orphans its affordances. The FE 501 ruling of 2026-09-17 (six affordances
into a Records detail view) is **superseded**.

---

## 2. The line

Every line renders four things, per BE 34 §1. **A line missing any of them is a defect, and the
FE asserts this rather than tolerating it.**

| | Rendering |
|---|---|
| **What** | The subject, one sentence, as sent. Never recomposed client-side |
| **Why** | The server's reason, verbatim. **If the user must look something up to judge the line, the line was incomplete** — that is a BE defect, reported not patched |
| **Action** | One click. Batchable only when BE 34 §5.1 marks it certain |
| **Verify** | Opens chat on this line with the document attached and the question pre-seeded |

**No arithmetic client-side, ever.** Every figure is printed exactly as the server sent it — no
rounding, no summing, no currency blending (BE 34 §5.3, §7.4). This is asserted by test, in the
shape FE Feature 22 already used: a grep-shaped assertion that no numeric operator appears in the
line components.

**Uncertainty** renders as the server's words, never as a number or a percentage bar, and an
uncertain line **never appears inside a batch control** (BE 34 §5.1).

---

## 3. Per profile

The FE **filters nothing**. The server sends what this user may act on (BE 34 §2.1); the client
renders what it receives. This is unchanged from Feature 22 and was the one thing that design got
structurally right.

| Profile | Screen |
|---|---|
| **Admin** | Every line type, with other grant-holders' work **collapsed to one row per area**, openable (BE 34 §2.2) |
| `can_audit` | Invoice decisions, outbound, recon prompts, the cash consequence of a decision |
| `can_train` | Corrections ranked by consequence, drafted fixes, proof teaching worked, bad rules |
| `can_load` | Stuck vs in flight, why it failed and the fix, what did not arrive |
| **no grants** | **"No tasks assigned. Ask your admin for access."** Not an error, not an empty list — a stated position (D3) |

**Collapsed rows** render the area name, the count, and the aging figure the server sends. They
expand in place; they do not navigate.

---

## 4. Batch acceptance

**One click may accept a batch** — "approve these 8" — but only for items the server marked
certain and reversible (BE 34 §5.3).

**Blocked on Q6.** *If it cannot be undone as a batch, it cannot be accepted as one.* The undo
affordance, its window, and what it shows are undesigned. **This task does not start until Q6 is
answered.**

**Never batched, per D29:** anything irreversible, and anything leaving the company. Every
outbound message — every chase email — is **shown in full and sent individually**. There is no
UI path that sends more than one message per click, and a test asserts it.

---

## 5. Cold start (BE 34 §7.1)

The first session teaches the **working relationship**, not the screens (D24). Three parts, in
order, per role:

1. **What your job looks like with ATLAS** — one short passage, role-specific
2. **How to verify me** — and the user **does it once, on a real line**, before the orientation
   ends. This is the part that matters: a user who verifies once relates to ATLAS differently
   from one who was told to trust it
3. **What I will be able to do as I learn** — the honest arc

**Then teaching continues in place** (D25) — a capability is explained the first time it becomes
relevant, never dumped on day one.

**Deleted from Feature 22:** the setup checklist, the path choice, and the upfront questionnaire
(D17). ATLAS proposes settings when the data shows them; it does not ask a user to configure a
product they have not used.

---

## 6. Recon (BE 34 §3.2, §3.3)

A line may carry an **attach affordance** with its reason:

> This rate differs from their quotation. Attach it and I'll compare line by line.

Attaching opens chat with the document and the question pre-seeded. **The recon result renders as
four groups** — matched · they show and we do not · we show and they do not · amount differs —
each printed from the server's own rows.

**The affordance appears only when the server sends it.** The FE never decides a document is
needed; that judgement is BE 34 §3.3's decision rule.

---

## 7. Forecast (BE 34 §7.5)

Renders as **a warning with levers**: a date, a number, and the actions that close the gap. Each
lever is a line with its own one-click action.

**The stated assumption renders with it** — on-time payment versus historical behaviour — because
a user making a decision needs to know which number they are looking at.

**Never a chart on this screen.** Admin only (D2). `ScenarioControl` is removed (D5).

---

## 8. What Feature 22 loses

| Task | Disposition |
|---|---|
| 22.1 | **Deleted** — `PrimaryNav` and the redirect table |
| 22.3 | **Deleted** — Settings as one scrolling page with anchor redirects |
| 22.9, 22.12, 22.13, 22.15 | **Deleted** — the `/dashboard`, review, trainer and help redirects |
| 22.21 | **Deleted** — the classic-layout toggle has nothing to toggle |
| 22.20 | **Deleted** — `ScenarioControl` |
| 22.22, 22.26 | **Deleted** — the upfront questionnaire and its derived lines (D4, D17) |
| 22.6 (part) | **Deleted** — the Ask rename, private sessions, the 🔒 badge |
| 22.4 | **Changed** — Today becomes the work screen, filtered by capability |
| 22.5 | **Changed** — `open` becomes chat-attached-to-this-line |
| 22.19 | **Changed** — per-line confirm becomes batch accept (§4) |
| 22.18 | **Changed** — convention accept/reject becomes noise pruning (D12) |
| 22.14 | **Changed** — `FirstRun` becomes §5 |
| 22.27 | **Changed** — becomes the register of settings ATLAS maintains |
| 22.2, 22.7, 22.8, 22.16 | **Kept** — Records tabs, the record drawer, the rules table, screenshot regression |

**Surviving code worth keeping:** the Today line components, the Today contracts, the SSE stream
and the chat deep links. They were the parts worth building. **The navigation shell is what goes.**

---

## 9. Tasks

To be numbered once BE Feature 34's contracts exist. Nothing here starts before its BE half.

1. Delete `PrimaryNav`, the redirect table and the flag; restore the sidebar with the work screen added
2. The line component — what / why / action / verify (§2)
3. Capability-filtered rendering and the no-grants empty state (§3)
4. Collapsed rows for the Admin (§3)
5. The verify affordance: chat, on this line, document attached (§2)
6. Recon attach and result rendering (§6)
7. Forecast lines with levers and the stated assumption (§7)
8. **Batch accept + undo — blocked on Q6** (§4)
9. Cold-start orientation, per role, with the verification step (§5)
10. Remove the questionnaire, `ScenarioControl`, private sessions, the classic toggle (§8)

---

## 10. Verification plan

`npx vitest run` and `tsc --noEmit` (the `typecheck` script added in FE Gap 639) on every task.

Invariants asserted, not assumed:

- A no-grants fixture renders **"No tasks assigned"** and **zero** lines
- A line whose capability the user lacks is **absent**, not disabled
- **No numeric operator appears in any line component** — grep-shaped, as Feature 22 did it
- No rendered total spans two currencies
- An uncertain line is **never inside a batch control**
- **No UI path sends more than one outbound message per click**
- A line missing `why` or `verify` **fails the test** rather than rendering degraded
- Removing a redirect does not orphan a route: `/invoices/review/:id` and `/trainer` both render

---

## 11. Amendment — the 2026-09-17 rulings, and three things above that are wrong

**Additive. Nothing in §1–§10 is rewritten** (CONVENTIONS hard rule 4): those sections hold the
reasoning the rulings acted on, and a spec that quietly agrees with itself afterwards teaches the
next reader nothing. Decisions are `apps/invoice-be/docs/atlas_discussion.md` **D34–D46**, recorded
as BE Feature 34 §13. This section is written at the start of the FE build (2026-09-18) so the
build is against the rulings, not against the body above.

### 11.1 What the rulings change on this screen

| § above | Still correct? | Ruling |
|---|---|---|
| §3, the `can_audit` row | **No — reversed** | **D44**: the Auditor sees the **full cash position, forecast and runway**, not "the cash consequence of a decision". One forecast, one view of it. §3's table is left as written; this row supersedes it. FP&A and margin analytics stay chat-only (D16) |
| §4, batch acceptance | **No — not built at all** | **D42**: nothing is batchable in v1. Individual accept only; batch accept *and* its undo are deferred until usage shows which line types are safe. **No batch control ships**, so §10's "an uncertain line is never inside a batch control" is vacuous — see 11.3 |
| §2, "Batchable only when … marked certain" | Contract intact, no consumer | `Recommendation.batchable` is still computed and still on the wire (BE §12.2). The FE reads it and renders nothing from it in v1 |
| §7, forecast with levers | **Blocked** | The levers are BE task 34.9, Slice C, unbuilt. The Auditor's cash line exists today (34.3) and states its assumption; it has no levers yet |
| §5, cold start | **Blocked** | BE task 34.12, Slice C, unbuilt |
| §3, Admin collapsed rows | **Blocked** | BE task 34.7, Slice C, unbuilt |
| — | New | **D36/D38**: ATLAS has **no notification, channel, digest or escalation** and speaks only when the app is opened. Everything computes on open. There is nothing to subscribe to, no SSE stream for this screen, and no badge count to poll |
| — | New | **D45**: a Trainer's correction line shows the invoice **before and after** the fix, carried as BE §14.6's typed `Correction` block — never prose the FE parses |
| — | New | **D34**: a "you missed this" affordance is the only false-negative detector. BE task 34.14, Slice C, unbuilt |

### 11.2 §8's "surviving code worth keeping" is factually wrong

> *"Surviving code worth keeping: the Today line components, the Today contracts, the SSE stream
> and the chat deep links."*

**None of it exists.** Verified by grep over `apps/invoice-fe` on 2026-09-18: no `PrimaryNav`, no
`ScenarioControl`, no `NEXT_PUBLIC_FOUR_SURFACES`, no `app/today/`, no `components/today/`. FE
Feature 22 was specced and amended twice and **never built**, so:

- **§9's task 1 and task 10 are no-ops.** There is nothing to delete, no redirect table to remove
  and no classic-layout toggle to strip. The existing ten-item `components/layout/Sidebar.tsx` is
  untouched by this feature, and the work screen is added beside it rather than replacing a
  navigation model that was never shipped.
- **The "Deleted" list in §1.2 is a list of things that were never created.** It reads as work; it
  is not.

Flagged, not rewritten. §8's disposition table is still the record of what Feature 22 *would* have
lost, which is why it stays.

### 11.3 The verification plan, amended where a ruling made an invariant vacuous

§10's list stands, with two entries corrected rather than quietly re-passed:

- *"An uncertain line is never inside a batch control"* — **vacuous under D42.** The test asserts
  the stronger, checkable fact: **no batch control exists in the FE at all** (no multi-select, no
  "approve these N", no bulk action), asserted grep-shaped over `components/atlas/`. Claiming the
  original test ran would be claiming a control was inspected that was never rendered.
- *"No UI path sends more than one outbound message per click"* — held, and also partly vacuous:
  no action endpoint exists yet (BE §15.2), so no UI path sends anything. The assertion is that
  every action affordance is a single line's single button, one click to one `action.kind`.

### 11.4 Scope actually built (2026-09-18)

Tasks **2, 3, 5 and 6** of §9, plus the BE endpoint they read (**BE Gap 691**, BE §15). Tasks 1 and
10 are the no-ops above; **task 8 is not built by ruling** (D42); tasks 4, 7 and 9 need BE 34.7,
34.9 and 34.12, which are Slice C and unbuilt. Nothing is stubbed for them — a placeholder for a
capability the backend cannot serve is the F33 failure (118/118 tests passing over 10 dead
capabilities) in miniature.

---

## 12. As built — 2026-09-18

**Additive record; §1–§11 are unchanged.** Branch `feature/atlas`, uncommitted. Tasks **2, 3, 5 and
6** of §9, plus the backend endpoint they read (**BE Gap 691**, recorded as BE Feature 34 §15).

### 12.1 Files

| File | Task | What it holds |
|---|---|---|
| `lib/atlas.ts` | all | The contract, transcribed from BE §12.2 / §15.2 — types, `lineDefect()`, `PERFORMABLE_ACTION_KINDS`, `ATTACH_ACTION_KINDS`, `verifyChatHref()`, the two calls |
| `components/atlas/AtlasLine.tsx` | 2 | What · why · action · verify, the doubt, D45's before/after pair, the figures with their working |
| `components/atlas/WorkScreen.tsx` | 3 | The read, the two empty states, the skipped-checks note |
| `components/atlas/ReconPanel.tsx` | 6 | The statement picker and §6's four groups |
| `app/work/page.tsx` | 3 | The route |
| `app/api/atlas/lines/route.ts` · `app/api/atlas/recon/route.ts` | 3, 6 | `proxyJson` handlers |
| `components/chat/ChatWindow.tsx` · `app/chat/page.tsx` | 5 | One optional `initialSeed` prop, and `/chat?seed=…` read from the query string |
| `tests/unit/atlas-line.test.tsx` · `atlas-work-screen.test.tsx` · `atlas-no-client-arithmetic.test.ts` · `atlas-live-backend.test.tsx` · `atlas-fixtures.ts` | all | 34 unit tests + 4 live-backend tests |

### 12.2 Decisions taken during the build, and why

- **A new route (`/work`) rather than a replaced landing page.** §9's task 1 is a no-op (§11.2), so
  there was no navigation shell to restore and no redirect to remove. Re-homing where a user lands
  is a founder decision, not a side effect of building a screen. The existing ten-item sidebar is
  untouched; `/invoices/review/:id`, `/trainer`, `/chat` and `/dashboard` were each checked to
  still answer 200.
- **An action whose endpoint does not exist renders disabled and says so.** BE §15.2 ships no
  action endpoint — every `kind` is Slice C. `PERFORMABLE_ACTION_KINDS` is therefore **empty**, and
  the line prints "I can see this and explain it, but I cannot do it for you yet." A button that
  404s is the F33 failure mode; an empty set that one entry is added to per landed endpoint is not.
- **A line missing a part renders as a named defect**, not as a tidy card with a hole in it, so a
  backend regression is visible on the screen it broke rather than absorbed by the layout.
- **The recon panel picks an already-ingested `Document`** rather than uploading. The comparison
  runs on extracted rows, so a file nothing has read cannot be compared; `GET /documents`
  (Feature 27 G14) is exactly that list.
- **`ReconRow` carries no numeric value**, only `amount_rendered`. A number a client *can* add up is
  one it eventually does.

### 12.3 What is honestly incomplete

- **The Verify affordance seeds the question but does not attach the document** (§2 asks for both).
  `POST /chat/sessions/{id}/attachments` takes an uploaded file and has no by-id path for a
  document the tenant already holds, so attaching would mean re-uploading a second copy of their
  own document to make a UI promise look kept. Filed as **FE Gap 640**; the document id travels on
  the URL as `verify_document_id` and is unread until that gap closes.
- **Tasks 4, 7 and 9 are not built** and nothing is stubbed for them — they need BE 34.7, 34.9 and
  34.12 (Slice C). **Task 8 is not built by ruling** (D42).
- **Lines arrive in skill order, which is not a ranking** (BE §15.5). §1's "their recommendations,
  ranked" is not yet true, and no client-side sort was added to make it look true.

### 12.4 Verification

```
npx vitest run          → 78 passed | 4 skipped (the live-backend file, which is opt-in)
npx tsc --noEmit        → clean
ATLAS_LIVE_URL=http://127.0.0.1:8077 npx vitest run tests/unit/atlas-live-backend.test.tsx
                        → 4 passed (renders the real response from a running invoice-be)
```

**End-to-end, in a real browser** (`next dev` → route handler → invoice-be → Postgres, `/work`):
**6 lines, 0 defects, 0 page errors**; the recon flow driven through to matched 1 · they show 1 ·
we show 2 · differs 1 · unreadable 1; the Verify link opening chat with the line's own question
already in the composer and nothing sent.

**One backend defect was found by that first live call** — the contract's number tokeniser
swallowing a trailing comma, rejecting a correctly-declared line and 500ing the recon endpoint.
Filed as **BE Gap 692** and fixed in the same change. It is the argument for this section: 59
passing backend tests and 34 passing FE tests did not find it, and one real request did.

---

## 13. As built — D47, D48 and D49 (2026-09-18)

**Additive record; §1–§12 are unchanged** (CONVENTIONS hard rule 4). Branch `feature/atlas`,
uncommitted. Founder rulings **D47, D48 and D49**, taken 2026-09-18 and recorded in
`apps/invoice-be/docs/atlas_discussion.md`. **BE Feature 34 §16 owns every contract named here**
— the dismiss endpoint, the dismissal store and the `Verify` wording rule are defined there and
referenced, never restated.

Tracker entries: **FE Gap 640 closed** by D47, plus **FE Gap 694** (D48) and **FE Gap 696** (D49).

### 13.1 Files

| File | Ruling | What it holds |
|---|---|---|
| `lib/atlas.ts` | D47, D49 | `VERIFY_ATTACH_HINT`, `dismissAtlasLine()`, and a `verifyChatHref()` doc that no longer describes an attachment |
| `components/atlas/AtlasLine.tsx` | D47, D49 | The attach hint under Verify, and the Dismiss control on every line |
| `components/atlas/WorkScreen.tsx` | D49 | `onDismiss` — posts, then **re-reads** |
| `app/api/atlas/lines/[id]/dismiss/route.ts` | D49 | The `proxyJson` handler |
| `hooks/useAtlasMode.ts` | D48 | `AtlasMode`, `ATLAS_MODE_STORAGE_KEY`, `useAtlasMode()` |
| `components/layout/AtlasModeToggle.tsx` | D48 | The switch |
| `components/layout/Header.tsx` | D48 | One line: the switch, rendered beside the bell |
| `tests/unit/atlas-d47-d49.test.tsx` | all | 12 tests — 3 · 6 · 3 |

### 13.2 D47 — the Verify affordance stops over-promising (FE Gap 640 closes)

**The gap closes as a wording change, and the by-id attachment path was deliberately not built.**
Both fixes FE Gap 640 proposed — a `document_id` on the chat attachment create endpoint, and a
chat-session document focus — are BE work that the founder ruled against building. Nothing
re-uploads a copy of a document the tenant already holds to make the promise look kept.

What ships instead: the Verify link still opens `/chat?seed=…` with the line's question in the
composer, and the line now carries `VERIFY_ATTACH_HINT` beneath it —
*"Attach the document in chat and compare it there — I do not attach it for you."* The hint is
rendered **only when `verify.document_id` is present**: a cash-position line has nothing to
attach and the sentence would read as a nag.

`verify_document_id` still travels on the URL, because it names *which* document to attach. It is
still read by nothing, and that is now a stated position rather than a deferred promise.

The BE holds the same rule as code (BE §16.2), so the two cannot drift: a question naming a
document must say to attach it, and no question may claim it is already attached.

### 13.3 D48 — the ATLAS / traditional toggle

**A previous spec claimed a header tab bar. There is none.** `components/layout/Header.tsx` was
read before anything was written: it has the needs-attention bell (Gap 87/95), the dual-theme
switch (FE Gap 478) and the profile dropdown. The toggle sits **between the bell and the theme
switch** and copies the theme switch's own shape — `role="switch"`, `aria-checked`, a sliding
thumb — so it reads as one of a pair rather than a new kind of control.

- **localStorage only** (`app_atlas_mode`), namespaced like the neighbouring `app_theme`. **No
  per-user preference store was built** and none exists; the consequence D48 states is that the
  choice does not follow a user to another device and **nobody can see which mode people use**.
- **First render is always `classic`**, with the stored value read in an effect — `localStorage`
  does not exist on the server, and reading it during the first client render would make the
  markup disagree with the server's. Same pattern as `useTheme`. Blocked storage (private
  browsing) throws on access and is caught: a toggle that cannot remember still has to work.
- **The existing screens are not removed, not re-homed and not redirected.** Turning it on pushes
  `/work`. Turning it off pushes `/dashboard` **only when the user is standing on `/work`** —
  throwing someone off the invoice they are reading is a navigation change nobody asked for, and
  there is a test for exactly that.
- It is **not gated on any grant**. Every signed-in user has a work screen, and an ungranted one
  is told so by the screen itself (D3).

**A separate component, not inline in `Header`**, because `Header` pulls Clerk's `useUser` /
`useClerk`, `useAuth`, `usePathname` and the page-header context — a unit test of the switch
would otherwise have to stand all of that up to click one button.

### 13.4 D49 — a dismiss control on every line

**It is on every line**, whatever its capability, certainty or action kind, because the reason a
line needs to go away ("I did the comparison in chat already") is independent of all three.

**The FE does no dismissal filtering.** The click posts to
`POST /api/atlas/lines/{id}/dismiss` and then **re-reads `GET /atlas/lines`**. It does not splice
the row out of local state. The backend consults the dismissal store before it assembles the
response (BE §16.3), so the line is *absent from the payload*, and the re-read is what proves
that at the only place it matters. A client-side splice would be a second copy of the backend's
rule and would mask the day the server stopped honouring it — the same reasoning §3 already gives
for not re-implementing the capability filter.

**A failed dismissal is said out loud**, in the screen's existing error line. A dismiss that
failed silently would leave the user believing the line is gone until the next open brings it
back, which is precisely the experience D49 exists to end.

**Not a snooze**, and the control makes no claim about the underlying problem: the title reads
*"I have handled this. Do not show it to me again."*

### 13.5 Verification

```
npx vitest run       → 90 passed | 4 skipped   (was 78 | 4; the 12 new tests are this section's)
npx tsc --noEmit     → clean
ATLAS_LIVE_URL=http://127.0.0.1:8077 npx vitest run tests/unit/atlas-live-backend.test.tsx
                     → 4 passed (the real response from a running invoice-be)
```

The FE tests state their own limit in the file header: **a unit test with a mocked `apiClient`
cannot prove a dismissal survives a recompute.** That is a property of the database and the
router, and it is proven in BE §16.5 — dismissed at the wire with `curl`, absent from the raw
JSON on a full recompute, and **still absent after the backend process was killed and restarted**.

FE Gap 641's lesson was applied to the new tests: anything awaiting an async child waits for the
child, never for the container.

---

## 14. As built — the screen can act (2026-09-18)

**Additive record; §1–§13 are unchanged** (CONVENTIONS hard rule 4). Branch `feature/atlas`,
uncommitted, on top of commit `2baf8bb`. **BE Feature 34 §17 owns every contract named here** —
the act endpoint, the action dispositions, the ranking fields, the collapsed-area row, the
forecast block and the orientation payload are all defined there and referenced, never restated.

Tasks: **§9 task 4** (collapsed rows), **task 7** (forecast lines with levers), **task 9**
(cold-start orientation), plus the FE half of BE 34.7 (the action click) and BE 34.14 ("you missed
this"). **Task 8 is still not built, by ruling** (D42). Tracker entries: **FE Gaps 700–703**.

### 14.1 Files

| File | Task | What it holds |
|---|---|---|
| `lib/atlas.ts` | all | `AtlasAreaRow`, `AtlasForecast`, `AtlasLever`, `AtlasOrientation`, `AtlasActionKinds`; `rank_cut` / `areas` / `forecast` on the existing shapes; `actOnAtlasLine()`, `fetchActionKinds()`, `fetchAtlasOrientation()`, `reportMissed()`, `actionDestination()`; `isActionPerformable(kind, known)` |
| `components/atlas/AtlasLine.tsx` | 4, 7 | The action button, the suggest-only destination link, the forecast block, the "you missed this" control |
| `components/atlas/WorkScreen.tsx` | 4 | The kinds read, `onAct`, the outcome line, the rank cut and *Show everything*, the collapsed area rows |
| `components/atlas/ColdStart.tsx` | 9 | §7.1's three parts, the day-one findings, the import offer |
| `components/atlas/MissedThis.tsx` | — | D34's report control |
| `app/api/atlas/lines/[id]/act/route.ts` · `actions/kinds/route.ts` · `orientation/route.ts` · `missed/route.ts` | all | `proxyJson` handlers |
| `tests/unit/atlas-actions.test.tsx` · `atlas-fixtures.ts` | all | 23 new tests |

### 14.2 The one decision that matters most: this app still holds no list of what it can do

`PERFORMABLE_ACTION_KINDS` shipped **empty** in §12 as a deliberate honesty mechanism, and **it is
still empty**. BE 34.7 made two kinds real, and the obvious change — type them into the constant —
is the one this build refused.

Instead the screen reads `GET /atlas/actions/kinds` on mount and passes the answer down. A
hand-maintained copy is precisely what lets a button be enabled ahead of its endpoint, which is the
failure the empty set was invented to prevent; it is also what silently breaks the day a kind is
withdrawn on the backend. `isActionPerformable(kind, known)` takes the server's set, and its default
is the empty one.

**While that read is in flight, or after it fails, every action renders disabled and no error is
shown.** "I do not know whether I can do this" and "I can" must not look the same, and the safe
answer to the unknown is the button that does nothing. No error banner, because the line already
says *"I can see this and explain it, but I cannot do it for you yet"* and a second message above
the work would push the work down the page to report something the user can already see.

`tests/unit/atlas-actions.test.tsx` asserts `PERFORMABLE_ACTION_KINDS.size === 0` directly. If
anybody ever "fixes" it by transcribing the backend's list, that test goes red.

### 14.3 The action click, and the line that is a link instead

**Performable (D50/D51 — two kinds).** The button posts `{kind, target_id, params}` from the line
it was rendered from, then **re-reads `GET /atlas/lines`**. It does not splice the row out: D38
recomputes every line on open, so whether a resolved invoice still has a line is the server's
answer. A client-side splice would be this app holding an opinion about a record it did not write,
and would mask the day the backend stopped agreeing — the same reasoning §13.4 already gives for
dismissal.

The outcome is the **server's sentence**, printed as sent, in its own line above the list. It is
kept separate from the error line because *"Invoice approved."* and *"that did not go through"* are
different facts and a user who sees one must not have to work out which they got.

**Suggest only (D50 — `apply_field_correction`, `requeue_invoices`).** These render as a **`Link`
to `actionDestination()`**, not a button. There is no `onClick` for a later change to fill in, and
the note under the line reads *"I will take you there — this one is yours to decide."* rather than
*"I cannot do it for you yet"*: the first is a ruling and the second is a state that will change,
and printing the wrong one promises a feature nobody intends to build.

**`Action` still carries no URL** (BE §12.2), so the destinations live in this app's own route
table. **Flagged rather than invented:** `/invoices` does not read a status query parameter today,
so "open the stuck list" opens the invoice list and not a filtered one. No query string is appended,
because a parameter this app sends and no page reads is the F33/F22 seam in miniature. Filed as
**FE Gap 702**.

### 14.4 Task 4 — collapsed rows for the Admin

The server decides who sees them (BE §17.5); this renders what it was sent and computes nothing.
An area row prints the backend's `headline` verbatim — every count in it is the server's, for the
same reason every figure is.

**Opening one is an expansion, not a request.** `line_ids` point into the same payload's `lines`,
so the rows are already here. There is no loading state inside an expanded area and no way for
opening one to fail, which is what "coverage is total; volume is not" has to mean in a client.

### 14.5 Task 7 — the forecast with levers

A date, a shortfall and a list. **Never a chart**: BE §7.5 says so in those words, and there is no
graph, no sparkline and no trend line in the block.

- **The assumption renders unconditionally.** It is required on the contract and it is the half of
  the answer that is easy to drop — "deterministic and honest are separate properties", and a
  shortfall date shown without what it assumed is the deterministic half on its own.
- **A lever is not a button.** BE §5.3: ATLAS never moves money and never sends outside the company
  unseen. Chasing a customer and deferring a payment are things the person does; rendering them
  clickable would be this screen claiming an authority the whole feature exists to refuse.
- Every amount is `lever.amount_rendered`, a string the server formatted. There is no `value` on
  the type and nothing here adds two levers together.

### 14.6 Task 9 — cold start

`ColdStart` renders §7.1's three parts, the day-one findings and the historical-import offer, and
**composes none of the words**. Part 3 — *"right now I do not know your vendors… in a month I
will"* — is a commitment about what the product will do, which is why it is a fixed table on the
backend and why nothing here shortens or re-orders it.

- **It renders itself away.** `needed` is the server's answer to "has this workspace seen an
  invoice", so there is no flag for this component to own and nothing for `WorkScreen` to decide.
- **Not a tour** (D25). No step counter, no "next", no "skip", no completion state, nothing stored.
- **A failed fetch is silent.** This is an explanation, not work: a failure to load it must not put
  an error banner above a queue that loaded perfectly well.
- The import offer is a sentence, never a button or a required step — everything works without it.

### 14.7 "You missed this" (BE 34.14, D34)

One control, one line of text, no category picker, no severity, no required fields beyond the
sentence. §5.2 says false negatives are already invisible and under-reported, so every field added
here is a reason somebody does not bother.

The description is sent **exactly as typed** — it is the evidence ATLAS was wrong, and trimming or
templating it anywhere along the path would be the product editing its own report card. The
acknowledgement is §5.2's: plain, and then stop.

**Honest limit:** D34 says "on any record". This control is on ATLAS lines only; the invoice,
trainer and document screens do not carry it. The endpoint takes any `entity_kind`/`entity_id`, so
that is remaining FE work, not a backend gap. Filed as **FE Gap 703**.

### 14.8 Verification

```
npx vitest run       → 117 passed | 4 skipped   (was 90 | 4; 23 new tests, plus 4 that the
                       grep-shaped no-arithmetic guard generates per new component file)
npx tsc --noEmit     → clean
```

The new file states its own limit in its header: **a unit test with a mocked `apiClient` cannot
prove an invoice was resolved.** That is a property of the backend, the browser and Postgres, and
it is proven in BE Feature 34 §17.11 — a real Chromium click on `/work` that ended with
`invoice.status = 'PAID'` read back out of the database, plus the `atlas_action_log` row that
records it.

FE Gap 641's lesson is applied to the new tests: `enabledAction()` waits for the **button's own
performable state**, not for the container, because the button and the answer that enables it come
from two different requests.

### 14.9 What is still not built

- **Task 8 (batch accept + undo) — by ruling** (D42). There is still no batch control anywhere in
  `components/atlas/`, asserted grep-shaped by `atlas-no-client-arithmetic.test.ts`.
- **No memory surface.** BE 34.10 serves `GET/POST/PATCH/DELETE /atlas/memory` and D12's noise
  suggestions, and **this app renders none of it**. §7.2's promise is that a user can read, change
  or delete a wrong lesson, and today they can only do that with `curl`. Filed as **FE Gap 700** —
  it is the largest honest gap in this slice.
- **No action-log surface.** `GET /atlas/actions` serves "what ATLAS did" and nothing displays it.
  §5.3 requires the list to exist and it does; requiring it to be *reachable by a user* is the next
  step. Filed as **FE Gap 701**.
- **No behaviour-based forecast**, because the backend does not produce one and the line says so.

## 15. As built — the four surfaces Slice C had no screen for (2026-09-18)

**Additive record; §1–§14 are unchanged** (CONVENTIONS hard rule 4). Branch `feature/atlas`,
uncommitted, on top of commit `2baf8bb`. **BE Feature 34 §17 owns every contract named here.**

Tracker entries closed: **FE Gaps 700, 701, 702, 703**. Each was a backend Slice C built with no
screen — a promise the product makes that until this change was kept only with `curl`.

**§14 recorded three of these as honest limits and they are now closed. Those paragraphs are left
standing rather than rewritten** (hard rule 4): §14.3's "no query string is appended", §14.7's
"this control is on ATLAS lines only" and §14.9's "no memory surface / no action-log surface" are
the state of the previous slice, and this section is what changed.

### 15.1 Files

| File | Gap | What it holds |
|---|---|---|
| `lib/atlas.ts` | 700, 701, 702 | `AtlasMemoryRule`, `AtlasNoiseSuggestion`, `AtlasMemoryResponse`, `AtlasActionLogEntry`, `AtlasActionLogResponse`; `fetchAtlasMemory()`, `addMemoryRule()`, `editMemoryRule()`, `deleteMemoryRule()`, `fetchAtlasActions()`; `actionDestination()` now filters, plus `INVOICE_STATUS_PARAM`, `INVOICE_VENDOR_PARAM`, `STUCK_INVOICE_STATUS` |
| `components/atlas/MemoryPanel.tsx` | 700 | List, inline edit, active toggle, hard delete, "tell me something", D12's suggestions with an accept control |
| `components/atlas/ActionLog.tsx` | 701 | Collapsed panel, newest first, successes **and refusals**, attributed and timestamped |
| `components/atlas/WorkScreen.tsx` | 700, 701 | Both panels mounted below the work |
| `app/api/atlas/memory/route.ts` · `memory/[id]/route.ts` · `actions/route.ts` | 700, 701 | `proxyJson` handlers (GET/POST, PATCH/DELETE, GET) |
| `app/invoices/page.tsx` | 702 | `useSearchParams()` behind a `Suspense` boundary, `urlFilters()`, the seeded first fetch |
| `components/dashboard/FilterBar.tsx` | 702 | `initialFilters` prop, which outranks the saved filter set |
| `app/invoices/review/[id]/page.tsx` · `app/trainer/page.tsx` · `components/ingestion/IngestionHistoryTable.tsx` | 703 | `MissedThis` on the record surfaces |
| `tests/unit/atlas-memory.test.tsx` · `atlas-action-log.test.tsx` · `atlas-destinations.test.tsx` · `atlas-missed-surfaces.test.tsx` | all | 34 new tests |

### 15.2 FE Gap 700 — the memory surface, and the bound that makes it short

§7.2/D31's argument is that *"a wrong lesson that cannot be found haunts the system forever"*. The
backend has served all four verbs since Slice C; the product's answer to finding a wrong lesson was
a terminal. `MemoryPanel` is that answer on a screen.

- **Delete is a hard delete and the control says so.** `atlas_memory_rules` has no `deleted_at`
  column (verified against the live schema, §15.6), the backend removes the row, and this panel
  **re-reads** rather than splicing — so what the list shows afterwards is what Postgres has. There
  is no undo, deliberately: an undo implies a copy kept somewhere, which is a soft delete wearing a
  different name.
- **Switching a rule off is a different act and is offered separately.** "This is wrong" and "this
  is right but not now" are different sentences; `active=false` keeps what the rule said.
- **Inactive rules are listed.** A switched-off rule the user cannot see is one they can neither
  switch back on nor delete.
- **D40 is the bound, and it is stated on the screen as well as in the code.** A derived
  observation — a vendor's usual range — is recomputed at check time and thrown away (D39) and is
  **not** a memory rule; listing one would invite a user to "edit" a figure computed from their own
  invoices, which fixing the invoices fixes and editing does not. The panel therefore has exactly
  **one** source of rows, `GET /atlas/memory`'s `rules`, asserted in `atlas-memory.test.tsx`; and
  `MEMORY_SCOPE_NOTE` tells the user why the list is shorter than they might expect, because
  without it an incomplete-looking list reads as a broken one.
- **D12's suggestions are rendered in their own list and never write themselves.** Accepting one is
  `POST /atlas/memory` with the server's own sentence — the user agreeing is what turns an offer
  into a rule. A suggestion that quietly became a rule would be the silent write §5.3 forbids,
  arriving through the door marked "learning".
- **A failed read is said out loud.** A memory list that renders empty because a read failed looks
  exactly like a system that has learned nothing, and a user would conclude their correction never
  landed.

### 15.3 FE Gap 701 — the action log

§5.3 lists *"what ATLAS did is a real list"* as a **boundary**. A list only a developer can query is
not visible in the sense that sentence means, so the boundary was not actually held until this
panel existed.

- **Refusals are rows, not errors.** The 409 a suggest-only kind gets carries D50's reasoning in
  full; a 403 and the underlying endpoint's own 422 are written too. A log holding only successes
  answers *"did ATLAS touch this invoice?"* with a confident no on exactly the occasions somebody
  is asking because something looks wrong. `data-succeeded` is on every row and both variants are
  proven live (§15.6).
- **Tenant-wide and unfiltered, because the backend decided that.** This component sorts nothing
  and drops nothing; a second ordering is the one that eventually disagrees.
- **It re-reads on open**, since the user opens it to check whether what they just did is really
  recorded.
- **It is not the audit trail.** `AuditLog` still records a resolve exactly as the audit queue's
  own button does. What this answers is the narrower question: which of those came from an ATLAS
  line, and which line.

### 15.4 FE Gap 702 — both ends of the seam, in one change

§14.3 flagged rather than worked around: a parameter this app sends and no page reads is the
F33/F22 defect in miniature. So the fix changed both ends together, and the test asserts them
against **each other** rather than each against its own idea of the parameter name — it takes the
URL `actionDestination()` produces, hands it to the real `/invoices` page as its search params, and
asserts the page then asks the backend for the filtered set.

- `requeue_invoices` → `?status=PROCESSING`, because `services/atlas_skills.py::_stuck_in_processing`
  selects on exactly that. **The hours-since-enqueue half is not expressible as a list filter and is
  not faked**: the destination is a superset of the line's invoices, and the line already says how
  many are stuck.
- `review_unlisted_invoices` → `?vendor=<target_id>`, because the recon emitter puts the vendor in
  `target_id` and `GET /invoices` filters on `vendor_name`.
- **`params.invoice_ids` is deliberately not sent.** `GET /invoices` has no id-set filter, so
  passing one would be inventing a parameter the backend never reads — the same defect again. The
  filter is the narrowest one both ends genuinely support, and no narrower.
- **The parameter names are exported from `lib/atlas.ts` and imported by the page.** Two string
  literals that happen to agree today are how this seam reopens.
- **The bar SHOWS the filter, it is not just applied behind it** (`FilterBar`'s new
  `initialFilters`). A list quietly filtered by something the controls do not display is worse than
  an unfiltered one: the user cannot tell why rows are missing, or clear it.
- **A URL filter outranks a saved filter set**, and saves nothing to `localStorage`. The click the
  user just made is a stronger statement of intent than a filter set they saved last Tuesday.
- Only `status` and `vendor` were lifted into the URL. `tag` and the date range stay component
  state — a full URL-state refactor is not what this gap asked for.

### 15.5 FE Gap 703 — "you missed this" on a record

D34 says *"on any record"*. It shipped on ATLAS lines only, which is the surface where it is least
needed: a line is a thing ATLAS already noticed. It is now on the invoice review console, the
trainer, and `IngestionHistoryTable` — **which is this product's documents list**, since FE Gap 464
folded `app/documents/page.tsx` into History.

- **Not capability-gated anywhere**, matching the backend (BE §17.7): a miss is noticed by whoever
  happens to be looking, and §5.2 says that evidence is already the scarcest there is.
- **Not gated on an invoice being resolved either.** Noticing a miss usually happens *after* the
  decision, and a control that disappears at the decision is absent for most of the cases it exists
  to catch.
- **The record's own kind is passed through unchanged** — `file.kind` on a History row is
  `"invoice" | "document" | "autopilot_file" | "rejected_email"`, and flattening a rejected email to
  "invoice" would file the evidence against a row that does not exist. The trainer reports
  `"invoice"` when the session has one and `"trainer_session"` when it is a transient upload with no
  `Invoice` row.
- **It is not the trainer's "Flag missed alert", and both are on that screen on purpose.**
  `FlagMissedAlertModal` stages a *rule* in the sandbox, scoped to a vendor template, which the user
  then commits. This reports a *miss* to ATLAS's memory: one sentence, nothing staged, nothing to
  commit. Merging them would make every observation a rule change, which is the friction D34 says
  stops people reporting at all.

### 15.6 Verification

```
npx vitest run     → 155 passed | 4 skipped   (was 117 | 4; 34 new tests, plus 4 the
                     grep-shaped no-arithmetic guard generates per new component file)
npx tsc --noEmit   → clean
```

Three pre-existing tests were updated, not weakened: `atlas-actions.test.tsx` and
`atlas-work-screen.test.tsx` had fall-through `get` mocks that answered any unknown path with a
LIST, and the work screen now performs two more reads. That mock handed `ActionLog` an array whose
`.entries` is `Array.prototype.entries`, which React then invoked as a state updater — so the
component was also changed to use the functional setter form, which cannot be re-read as an
instruction. The mocks now name `/atlas/memory` and `/atlas/actions` explicitly.

**The acceptance proof is live, and a unit test is not it.** Real Chromium → `next dev` on `:3077`
→ the FE route handlers → `uvicorn` on `127.0.0.1:8077` → Postgres on `127.0.0.1:5433`
(**`127.0.0.1`, never `localhost`** — BE Gap 697). No mocked `apiClient`, no fixture.

```
D12_SUGGESTION_ON_SCREEN: "You have dismissed invoices waiting on your decision 41 times.
                           Shall I stop bringing them to you?"   <- computed from 41 real
                                                                   atlas_dismissals rows
RULE_CREATED_FROM_UI:                7fba5265-bcdd-416f-9c2c-baffa85a8f82
RULE_TEXT_AFTER_EDIT_ON_SCREEN:      "FE Gap 700 live proof: EDITED IN THE BROWSER."
D12_SUGGESTION_ACCEPTED_BECAME_RULE: yes, on the user's click -- not before it
RULE_GONE_FROM_SCREEN_AFTER_DELETE:  true
ACTION_LOG_HAS_SUCCESS:              true   ("Invoice approved.", resolve_invoice)
ACTION_LOG_HAS_REFUSAL:              true   (the 409: "I do not do 'apply_field_correction'
                                             for you...", plus two 422s)
INVOICES_REQUEST_STATUS_FILTER:      /api/invoices?limit=8&offset=0&status=PROCESSING
STUCK_ROW_VISIBLE / NON_STUCK_HIDDEN: true / true
INVOICES_REQUEST_VENDOR_FILTER:      /api/invoices?vendor_name=Unlisted+Vendor+Pvt+Ltd&limit=8&offset=0
VENDOR_ROW_VISIBLE / OTHER_HIDDEN:   true / true
MISSED_CONTROL_ON_INVOICE_REVIEW:    true, and the report was accepted
PAGE_ERRORS:                         none
```

Read back out of Postgres afterwards, **not off the screen**:

```
the deleted rule, by id   -> 0 rows in atlas_memory_rules
the deleted rule, by text -> 0 rows
atlas_memory_rules columns -> id, tenant_id, active, created_at, updated_at, created_by,
                              text, source, origin_ref     <- there is no deleted_at to hide in
memory after the run      -> ('told', 'You have dismissed invoices waiting on your decision 41...')
                             ('missed_report', 'I missed this, and you told me: FE Gap 703 live proof...')
atlas_missed_reports      -> ('invoice', '474b0d2e-...', rule_id 6586c1e6-..., the sentence, unedited)
atlas_action_log          -> ('resolve_invoice', True,  'user_test_default', 09:01:47, 'Invoice approved.')
                             ('resolve_invoice', False, ..., 'An ATLAS decision is PAID or REJECTED...')
                             ('apply_field_correction', False, ..., "I do not do 'apply_field_correction'...")
```

**Every seeded row was removed afterwards** — two invoices, 41 dismissals, the memory rules, the
missed report, the action-log rows and the `audit_logs` row the resolve wrote. They existed to give
the mock tenant's screen something to act on and are not test data anyone should find later.

**No backend file was changed by this work**, so BE Feature 34's own numbers stand unaltered.

### 15.7 What this deliberately does not do

- **No memory settings page.** Both panels live on `/work`, collapsed, below the work — they are how
  a user checks ATLAS, not work ATLAS is asking for, and either above the queue would push the
  actual work down the page.
- **No undo for a deleted rule, and no "what I dismissed" surface.** Both would be a retained copy,
  which is the soft delete the founder's rule forbids. A rule deleted in error is retyped.
- **No paging on the action log.** The backend serves the most recent 50; a user needing more than
  that is asking an audit question, and `audit_logs` is where that is answered.
- **`tag` and the date range are still component state**, not URL state.
- **No "you missed this" on the invoice LIST rows.** The control is on record *screens*; a textarea
  inside a table cell would be a worse version of the same affordance one click away.

---

## 16. As built — what real data exposed on this screen (2026-09-18)

**Additive, per hard rule 4.** Nothing above is rewritten. §1's framing — one screen, and it is the
app — is what makes the defect below a defect, and it stands exactly as written.

### 16.1 Every line rendered twice, and neither side was wrong on its own

The VPI demo tenant was loaded — 26 real invoices — and the work screen opened as the Admin. All
nine lines appeared **twice**: once inside the collapsed area they belong to, once in the ranked list
below it.

**The backend was right.** `areas[].line_ids` and `lines[]` hold the same ids on purpose: collapse
**groups, never removes** (BE 34 §2.2, D20/D41). That is the property that makes an area openable in
place with no second request — "coverage is total; volume is not" is only true in a client if the
contents of a collapsed row are already in the payload.

**This component was right too, twice over.** It rendered `areas` from `areas`, and it rendered
`lines` from `lines`, in the server's order, filtering nothing — which is this file's own stated rule
and a correct one.

**So the defect existed only where the two meet, which is exactly the seam §1 exists to close.**
Neither side could have fixed it alone without giving up something real: the backend could only have
fixed it by making `areas` a truncation of `lines`, which costs openable-in-place; this component
could only fix it by holding an opinion about which list owns a line — which is what it now does,
deliberately, and says so.

**The rule, stated once, in `WorkScreen.tsx`:** *an area owns the lines it stands for; everything
else is a plain line.* `looseLines` is that sentence as code. The ranking is untouched — `lines`
keeps the server's order and this filters it, never re-sorts it (BE §7.3, D30). `rank_cut` is applied
to the list that is actually rendered, because a count of rows above the fold applied to a list the
areas have taken rows out of would hide lines that were never below any cut.

### 16.2 Why 155 passing tests did not catch a line rendered twice

This is the part worth keeping. The suite had tests for both halves:

- *"opens in place, out of the payload it already holds"* asserted the opened area contains two
  `atlas-line` nodes. **True.**
- *"renders the server's order and never re-sorts it"* asserted the list contains the lines the
  payload carried. **True.**

Both passed, both were correct, and the screen showed everything twice. **Nobody counted the
screen.** Every assertion was scoped to a subtree or to a prop, and the defect lived in the sum of
two subtrees — which is not a place any of those tests could look.

The same shape explains the other five defects in this pass (BE Feature 34 §18.1): the suites
asserted payload shape and component props, and nobody asserted the sentence a user reads or the
number they act on.

**What the new tests do differently.** `atlas-actions.test.tsx` gains two that are written from the
screen inwards:

- *"renders a line exactly once, no matter how the area is left"* — counts `atlas-line` nodes with
  the area **collapsed** (zero, because both lines belong to it) and with it **open** (two, each
  appearing once), asserting per-id rather than in aggregate so a regression names the line.
- *"leaves a line no area stands for in the plain list, once"* — the cash tile case, which is what
  made the duplication visible on real data in the first place: a line carrying the `audit`
  capability that belongs to no area and must therefore still be on screen.

Both were confirmed to **fail** against the pre-fix component before being kept. A test that passes
before and after a fix is not evidence of the fix.

### 16.3 What changed on the wire, and what a client must now not assume

One backend change is visible here and is easy to get wrong later (BE Feature 34 §18.5):

> **`AreaRow.count` is pieces of work, not lines.** `count <= line_ids.length`, and the two differ
> whenever ATLAS has more than one thing to say about one invoice.

This screen prints `area.headline` verbatim and never composes a count, so nothing here had to
change for it. The invariant is recorded because `count === line_ids.length` is exactly the kind of
assumption a future component would make while looking reasonable — and a test asserting that
equality is one of the things that existed, passed, and had to be relaxed.

Also: an area now **excludes** tenant-level lines (the cash position, the runway, the shortfall
warning). They arrive in `lines` with no area claiming them, so they render in the plain list — which
is what §1's "a user lands on their work" requires of a standing figure the Admin must always be able
to see.

### 16.4 Verification

| Check | Command | Result |
|---|---|---|
| The two new render-count tests, plus the existing area suite | `npx vitest run tests/unit/atlas-actions.test.tsx` | 25 passed |
| Whole unit suite | `npx vitest run` | see §16.5 |
| Types | `npx tsc --noEmit` | clean |
| Falsification | the same file, with `looseLines` reverted to `payload.lines` | the two new tests fail, the other 23 pass |

Re-driven live against the VPI demo tenant (`00000000-0000-0000-0000-000000000000`) at
`localhost:3000` with a real backend on `:8000` — not a fixture, not a mock — for all three roles.
Screenshots and the raw payload are filed in
`apps/invoice-be/docs/test_evidence/vpi_demo_atlas_2026-09-18/`, beside the originals so the before
and after read together.

### 16.5 Suite state at the end of this change

Recorded rather than summarised, because "all green" has been claimed in this repo before without a
run behind it. See the handback and `apps/invoice-be/docs/test_coverage_map.md` for the exact
numbers from this session's run.
