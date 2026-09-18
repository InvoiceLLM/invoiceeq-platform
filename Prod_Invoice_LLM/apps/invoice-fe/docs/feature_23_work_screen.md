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
