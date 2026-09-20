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

1. **Where the panel goes for the Admin**, whose screen already has collapsed areas, the forecast
   block and the memory panel. Above everything, or between the forecast and the lines?
2. **Citation to an invoice not in the lines list.** §3 step 4 allows it because the BE guard
   proved provenance. Alternative: reject anything not in the `/lines` payload, which is stricter
   but would drop true statements about invoices no line was raised for. Which?
3. **Mobile.** The work screen has no mobile layout ruling. Does the briefing panel collapse to
   its first paragraph on narrow widths, or is mobile out of scope as it is for FE 23?
