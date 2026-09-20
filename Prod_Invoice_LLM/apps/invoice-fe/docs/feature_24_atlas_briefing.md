# Feature 24 — The briefing: what ATLAS Intelligence says on open

**App:** invoice-fe · status lives in `fe_features_tracker.md`
· **Counterpart:** BE Feature 35 (`apps/invoice-be/docs/feature_35_atlas_intelligence.md`) — the agent.
· **Builds on:** FE Feature 23 (`feature_23_work_screen.md`) — the screen this panel sits on.
Feature 23 is not rewritten (CONVENTIONS hard rule 4); this file is additive.

**BE Feature 35 owns the contract.** Event names, payload shapes, citation fields and the
answer endpoint are defined in BE 35 §3.3 and referenced here, never restated. Same rule as
FE 23 and for the same reason.

---

## 1. Overview

**What this is.** A panel above the line list on `/work`. The deterministic lines from
`GET /atlas/lines` render first, unchanged. Then the briefing streams in above them: a few
paragraphs, each with the records it cites rendered as links into the lines below, and at most
one question the user can answer inline. On a cold tenant the panel shows the role-based welcome
instead.

**What it is not.**

- Not a chat. There is no free-text input in the panel. The one input is the answer to a
  question ATLAS asked. Chat stays at `/chat`, reached from a line's Verify affordance as today.
- Not a third surface. No new route, no new store. The panel is a component inside `WorkScreen`.
- Not a judge of the prose. The FE does one deterministic check: a paragraph whose citations are
  empty, or name a `record_id` not present in the `/lines` payload or the briefing's own
  `citations`, is rejected and counted, visibly, the way `doubt_checks_skipped` is surfaced today.
  The FE does no arithmetic (FE 23 §2 holds).
- Not live-updating. After a dismiss, act or answer the panel shows a small "briefing will refresh
  on your next visit" note and keeps the current text. It never re-fetches on its own (D38).

**Naming.** On screen the panel is titled "Briefing". "ATLAS" already names the whole work
screen; the panel does not repeat it.

---

## 2. File Coordinates

| path | named function / component | new or edit | what it does |
|---|---|---|---|
| `app/api/atlas/briefing/route.ts` | `GET` | new | SSE proxy to BE `GET /atlas/briefing`, same shape as `app/api/chat/jobs/[jobId]/stream/route.ts`: `force-dynamic`, forwards headers, pipes the upstream body |
| `app/api/atlas/briefing/answer/route.ts` | `POST` | new | Proxy to BE `POST /atlas/briefing/answer` |
| `lib/atlasBriefing.ts` | `BriefingEvent`, `Citation`, `BriefingParagraph`, `parseBriefingFrame(raw)`, `validateCitations(paragraph, knownIds)` | new | Types mirroring BE 35 §3.3 (imported by name, never redefined elsewhere), the SSE frame parser, and the one deterministic check: every citation's `record_id` must be in `knownIds`. Returns the paragraph or a rejection reason |
| `components/atlas/Briefing.tsx` | `Briefing({ knownIds, onAnswered, onNeedsRefresh })` | new | Opens the SSE stream on mount, renders `welcome`, `paragraph`, `question`, `truncated`, `error`, `done`. Holds `paragraphs`, `question`, `rejected` count, `status`. Renders the "will refresh on next visit" note when `onNeedsRefresh` fires |
| `components/atlas/BriefingParagraph.tsx` | `BriefingParagraph({ paragraph, onCitationClick })` | new | Prose with each citation rendered as a link. A `recommendation` citation scrolls to and highlights that `AtlasLine`; an `invoice` citation opens the invoice route; `rule` opens `MemoryPanel`; `action` opens `ActionLog` |
| `components/atlas/BriefingQuestion.tsx` | `BriefingQuestion({ question, onSubmit })` | new | The question text, its citation link, a single-line answer field, submit. On success shows the stored rule text and the refresh note |
| `components/atlas/WorkScreen.tsx` | `WorkScreen()` | edit (additive) | Mounts `<Briefing>` above the line list once `payload` is loaded, passing the set of `Recommendation.id` and `what.entity_id` from the payload as `knownIds`. Calls `onNeedsRefresh` after its existing dismiss and act handlers succeed. Nothing else in the component changes |
| `components/atlas/ColdStart.tsx` | `ColdStart()` | none | The cold tenant welcome now arrives as the `welcome` event and renders inside `Briefing`; `ColdStart` keeps rendering the existing orientation below it. Not modified |
| `tests/unit/atlas-briefing.test.tsx` | — | new | §6 |

---

## 3. Functionality

1. `WorkScreen` fetches `/api/atlas/lines` as today and renders the lines. Only after `payload`
   is set does it mount `<Briefing knownIds=…>`, so the lines are on screen before any
   briefing request is sent.
2. `Briefing` opens `EventSource("/api/atlas/briefing")` and reads frames with
   `parseBriefingFrame()`.
3. A `welcome` frame renders as the panel body with the role name; no citations, no check.
4. Each `paragraph` frame runs `validateCitations()` against `knownIds` plus every `record_id`
   the briefing has cited so far (a citation to an invoice not in the lines list is allowed when
   the BE emitted it, since BE 35's guard already proved it came from a tool). A passing paragraph
   is appended; a failing one increments `rejected` and is not rendered. The count shows as
   "n paragraphs withheld" under the panel when non-zero, never silently.
5. A `question` frame renders `BriefingQuestion`. Submit posts to `/api/atlas/briefing/answer`,
   then shows the rule text returned and the refresh note. Only one question is ever rendered;
   a second frame is ignored and counted with `rejected`.
6. `truncated` renders one line: "ATLAS stopped early (reason)". `error` renders the message in
   place of the panel body. `done` closes the stream and shows "from cache" or the model name in
   the panel footer, small.
7. When the user dismisses or acts on a line, `WorkScreen`'s existing handlers succeed as today,
   then call `onNeedsRefresh`. `Briefing` shows the note and does nothing else. The next visit to
   `/work` remounts the component and the BE decides whether to replay or regenerate.
8. Clicking a citation: `recommendation` scrolls to the matching `AtlasLine` and applies a
   two-second highlight; other kinds route as in §2.

---

## 4. Data & schema changes

None. No new client state store. The panel's state lives in the component and is discarded on
unmount.

---

## 5. Tasks

- **24.1** `lib/atlasBriefing.ts` — types, `parseBriefingFrame()`, `validateCitations()`.
- **24.2** `app/api/atlas/briefing/route.ts` and `answer/route.ts` proxies.
- **24.3** `Briefing.tsx` — stream lifecycle, event dispatch, rejected counter, refresh note.
- **24.4** `BriefingParagraph.tsx` — citation links and the scroll-to-line highlight.
- **24.5** `BriefingQuestion.tsx` — answer flow.
- **24.6** `WorkScreen.tsx` — mount after payload, pass `knownIds`, wire `onNeedsRefresh` into the dismiss and act handlers.
- **24.7** Screenshot verification on the VPI tenant, three roles, against the real BE.

---

## 6. Verification Plan

Unit tests in `tests/unit/atlas-briefing.test.tsx` with a scripted SSE fixture, the pattern the
existing `atlas-*.test.tsx` files use. The citation check and the single-question rule are
deterministic code in `lib/atlasBriefing.ts`, never left to rendering.

| task | proof |
|---|---|
| 24.1 | `parseBriefingFrame()` round-trips every event kind in BE 35 §3.3; `validateCitations()` rejects empty citations and unknown ids, accepts ids from `knownIds` or earlier citations |
| 24.2 | Proxy forwards headers and streams the body; a BE 4xx surfaces as an `error` frame, not a blank panel |
| 24.3 | Fixture with 3 valid, 1 uncited, 1 unknown-id paragraph renders 3 and shows "2 paragraphs withheld"; `truncated` line renders; `done` footer shows cached vs model |
| 24.4 | Citation click scrolls to the line with the matching id and toggles the highlight class |
| 24.5 | Submit posts the answer, renders the returned rule, shows the refresh note; a second `question` frame is not rendered |
| 24.6 | Lines render before the briefing request is made (fetch order asserted); dismiss and act call `onNeedsRefresh`; no automatic re-fetch of the briefing afterwards |
| 24.7 | Screenshots per role on the VPI tenant with the real BE 35 running on Terra, filed in `docs/test_evidence/atlas_briefing_<date>/`. The Trainer's briefing must not mention cash or forecast (grant filtering proven on screen, not only in the BE schema list) |

---

## 7. Open decisions

1. ~~Where the panel goes for the Admin.~~ **Ruled 2026-09-20: at the top**, directly after the error and outcome lines and before the collapsed areas and the line list, for every role.
2. ~~Citation to an invoice not in the lines list.~~ **Ruled 2026-09-20: allowed.** The BE guard proved the id came from a tool result; the FE renders it as a link to the invoice. §3 step 4 stands.
3. ~~Mobile.~~ **Ruled 2026-09-20: out of scope**, as for the rest of the work screen.

---

## 8. As built (2026-09-20, tasks 24.1–24.6)

Additive record of what was actually built on branch `feature/atlas-intelligence`, per
CONVENTIONS hard rule 4. §1–§7 above are untouched. Task 24.7 (screenshots on the VPI tenant)
is the functional-tester's and is **not** done — the tracker marker stays `[~]`.

### 8.1 Files

| path | what shipped |
|---|---|
| `lib/atlasBriefing.ts` | `Citation`, `BriefingParagraph`, `BriefingQuestion`, `BriefingWelcome`, `BriefingTruncated`, `BriefingError`, `BriefingDone`, the `BriefingEvent` discriminated union, `parseBriefingFrame(raw)`, `parseBriefingEvent(type, data)`, `validateCitations(paragraph, knownIds)`, `citedIds()`, `KINDS_ALLOWED_OUTSIDE_KNOWN_IDS`, `BRIEFING_STREAM_PATH`, `answerBriefingQuestion()` |
| `app/api/atlas/briefing/route.ts` | `GET`, `force-dynamic`, `maxDuration = 120`. Pipes `upstream.body` untouched with the four SSE headers the chat stream proxy uses. **Not** `proxyJson` — that buffers the whole body and would undo the backend's generator |
| `app/api/atlas/briefing/answer/route.ts` | `POST` via `proxyJson`, same shape as `app/api/atlas/memory/route.ts` |
| `components/atlas/Briefing.tsx` | `Briefing({ knownIds, needsRefresh, onAnswered })` — one `EventSource` per mount, named listeners for the six event types, `paragraphs` / `question` / `rejected` / `truncated` / `error` / `done` state, the withheld count, the truncated line, the refresh note, the footer |
| `components/atlas/BriefingParagraph.tsx` | `BriefingParagraphView({ paragraph, onCitationClick, testId })`, `revealCitation()`, `BRIEFING_HIGHLIGHT_CLASS`, `BRIEFING_HIGHLIGHT_MS`, `invoiceHref()` |
| `components/atlas/BriefingQuestion.tsx` | `BriefingQuestionView({ question, onSubmit })`, `REFRESH_NOTE` |
| `components/atlas/WorkScreen.tsx` | additive only: the import, `briefingNeedsRefresh` + `onNeedsRefresh`, the `<Briefing>` mount after the outcome line, and one call in each of the existing dismiss and act handlers |
| `styles/globals.css` | `.atlas-briefing-cited`, the two-second citation highlight |
| `tests/unit/atlas-briefing.test.tsx` | 29 tests — §6 rows 24.1, 24.3, 24.4, 24.5, 24.6 |
| `tests/unit/atlas-briefing-proxy.test.ts` | 3 tests — §6 row 24.2 |
| `vitest.setup.ts` | the `scrollIntoView` shim is now guarded on `typeof Element !== "undefined"`, because the proxy test runs in the node environment |

### 8.2 Deviations from §2/§3, and why

1. **`Briefing`'s third prop is `needsRefresh` (a boolean), not `onNeedsRefresh` (a callback).**
   §3 step 7 has `WorkScreen` *calling* `onNeedsRefresh` after a dismiss or an act and the panel
   *showing* a note — those are two directions, so the handler named `onNeedsRefresh` lives in
   `WorkScreen` (it sets `briefingNeedsRefresh`) and the panel reads the flag. Behaviour is
   exactly §3 step 7; only the prop's direction differs from the §2 table's wording.
2. **`validateCitations()` exempts `record_kind === "invoice"` from `knownIds`
   (`KINDS_ALLOWED_OUTSIDE_KNOWN_IDS`).** §7 ruling 2 allows an invoice citation from outside the
   lines list; §3 step 4's mechanism cannot express that on its own. The only thing that widens
   `knownIds` mid-briefing is a paragraph that already passed, so the **first** citation of an
   out-of-list invoice would always be withheld and no later one could ever appear — the ruling
   would be unreachable code. Every other kind still has to name a record this screen can show,
   because for those the id *is* the destination (a `recommendation` id with no line is a link to
   nothing). §3 step 4's accumulation is implemented as written and still governs `rule`,
   `action`, `shortfall` and `recon_row`.
3. **§6 row 24.2 is proved in a second file**, `tests/unit/atlas-briefing-proxy.test.ts`, with a
   `// @vitest-environment node` pragma: a Route Handler builds a `NextResponse`, which needs
   Node's fetch primitives rather than jsdom's.
4. **An upstream non-2xx is rewritten into an `error` + `done` frame pair by the proxy** (the
   status is preserved). A browser `EventSource` cannot read a status code — a 4xx with a JSON
   body reaches the panel as "connection failed" and renders nothing, which is exactly §6 row
   24.2's "not a blank panel".
5. **A second `question` frame is counted in the same visible tally as a withheld paragraph**
   (§3 step 5 says "ignored and counted with `rejected`"), so a briefing with one extra question
   reads "3 paragraphs withheld".
6. **The withheld tally is a `string[]` of reasons, not a counter.** FE 23 §2's no-arithmetic
   rule is asserted grep-shaped over every file in `components/atlas/`, so `prev + 1` is not
   available; the panel counts by collecting and renders `rejected.length`. Same reason
   `revealCitation()` scans `[data-line-id]` attributes instead of composing a CSS selector.

### 8.3 Verification run (2026-09-20)

`npm run typecheck` clean. `npx vitest run` (whole invoice-fe unit suite, including the two new
files): **195 passed | 4 skipped (199)**, 16 test files passed, 1 skipped
(`atlas-live-backend.test.tsx`, which needs a live backend). The two new files alone:
**32 passed**. No existing test changed its expectations; `atlas-no-client-arithmetic.test.ts`
now covers the three new components and passes.

**What is NOT proved by this**: nothing here ran against a real backend or a real model. The
scripted fixture is wire text in BE 35 §3.3's shape, not a captured live stream. Task 24.7 (and
BE 35 task 35.10) is where the real Terra run on the VPI tenant is proved.


---

## 9. Amendment — FE Gap 706 (2026-09-20): a citation is labelled with the record, not its key

Additive. §3 step 8's citation behaviour is unchanged — a citation still scrolls to the line,
opens the invoice, or opens the panel it names. Only what it *reads as* changed.

### 9.1 What the live run showed

The 2026-09-20 VPI run rendered the raw `record_id` under every paragraph:
`audit-approve-530bd65a-be04-4953-988b-2932f52a6f89`. That is the backend's primary key. A
finance person reading a sentence about ₹4,37,190.00 could not tell which of their invoices it
rested on without clicking, which is the opposite of what a citation is for.

### 9.2 What changed

| change | where |
|---|---|
| `invoiceNumberIn(text)` — the first invoice-number-shaped word in a string, or `null` | `lib/atlasBriefing.ts` |
| `citationLabel(citation, paragraphText, lineLabels)` — the label for one citation | `lib/atlasBriefing.ts` |
| `briefingLineLabels(lines)` — recommendation id → that line's invoice number, from the `/atlas/lines` payload | `components/atlas/WorkScreen.tsx`, passed to `<Briefing lineLabels={…}>` |
| `lineLabels` threaded through | `components/atlas/Briefing.tsx` → `BriefingParagraph.tsx` and `BriefingQuestion.tsx` |
| the id moved to `title` and `aria-label`; `data-citation-id` unchanged | `components/atlas/BriefingParagraph.tsx` |

The label, by kind: `recommendation` → the cited line's invoice number when this screen's
payload has one, else **"this line"**; `invoice` → the invoice number named in the paragraph's
own text when there is one, else **"invoice"**; `rule` → **"memory rule"**; `action` →
**"action"**; anything else (`shortfall`, `recon_row`, `cash_position`, a kind a later backend
adds) → the kind word with its underscores as spaces. **Never the id.**

Three decisions worth recording:

1. **The label is derived from data this app was sent, never parsed out of the id.** The id's
   shape is the backend's business (`cash-INR`, `area-audit`, a bare uuid, a role-prefixed
   recommendation id) and an app that read meaning out of one would break the first time an
   emitter changed a prefix.
2. **The map is built in `WorkScreen`, which owns the `/atlas/lines` payload.** The label and
   the line a citation click scrolls to are then the same record by construction — the panel
   already receives `knownIds` from that payload and this is the same source.
3. **The helpers live in `lib/atlasBriefing.ts`, not in the component.**
   `tests/unit/atlas-no-client-arithmetic.test.ts` greps every file in `components/atlas/` for
   operators; string scanning is not arithmetic, but it is not worth arguing with a grep about
   either. That test still passes over all the components, unchanged.

`invoiceNumberIn()` accepts exactly two shapes — a word carrying both an upper-case letter and a
digit (`RAJ-2009`, `VPI-OUT-2014`), and a word the sentence marked with `#` and which contains a
digit (`#1041`, which is how `atlas_skills` writes a headline's number). A money figure has no
letters, a bare date has no digits glued to a word, and a string with neither yields `null` and
the caller falls back to a generic word. Nothing is computed and nothing is reformatted.

### 9.3 Verification (2026-09-20)

`npm run typecheck` clean. `npx vitest run tests/unit/atlas-briefing.test.tsx
tests/unit/atlas-no-client-arithmetic.test.ts`: **56 passed** (4 new, in
`atlas-briefing.test.tsx`: the number reader, the per-kind labels and their fallbacks, the map
`WorkScreen` builds, and a rendered assertion that **no** citation's visible text equals its own
`data-citation-id` while `title` and `aria-label` both contain it).

Whole unit suite after the change: **199 passed | 4 skipped (203)**, 16 files passed, 1 skipped.
Run as `NODE_OPTIONS=--max-old-space-size=4096 npx vitest run tests/unit --pool=forks
--poolOptions.forks.singleFork=true`: the default worker pool hit a V8 heap OOM
("Worker exited unexpectedly") on this machine partway through the sweep. That is an environment
limit rather than a failure — the same suite had passed **195 | 4 skipped** on the default pool
minutes earlier, before the four new tests existed.
