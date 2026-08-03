# Gap 82 repro — "Click a field to correct it" does nothing

Real, non-headless Chromium (Playwright `headless:false`), real local stack
(Postgres + BE + FE dev server + Clerk dev keys), 2026-08-03.

## Method
Direct DOM/click testing against `app/invoices/review/[id]/page.tsx`'s
`EditableField` on real invoices pulled live from Postgres (`invoice` table),
covering every reachable state:
1. `AUDIT_REQUIRED` invoice (`2336939d-88c4-46ec-8bee-ea0ec07169bf`) — all 7
   correctable fields (Vendor, Invoice Number, Date, Due Date, PO Number,
   Total Amount, Tax Amount).
2. `COMPLETED` invoice (`b67fe5ab-248f-49b0-bbf1-60cc9840e03d`) — not in the
   `isResolved` set (`["PAID","REJECTED"]`), so should still be editable.
3. `REJECTED` invoice (`6887353b-4cce-4213-b719-dfa13813ebf4`) — in the
   `isResolved` set, so correctly should NOT be editable.

## Result: the click-to-edit mechanism itself is NOT broken
For every field on both `AUDIT_REQUIRED` and `COMPLETED` invoices:
`readOnly` flips `true` → `false` on click, the input gains focus, its
border/background classes switch to the "editing" style, typed/filled text
is accepted, and the "N field(s) corrected" / "Save Correction" bar appears
correctly. Screenshots 1–2, 4.

For the `REJECTED` invoice: `readOnly` correctly stays `true` after a click
attempt, `pointer-events-none` is applied, and clicking does nothing — this
is the code working exactly as designed (`disabled={isResolved}` in
`EditableField`), not a bug. Screenshot 3, and confirmed the
"Resolved — read-only" badge is present and visible next to the section
header.

The originally-suspected causes are all ruled out:
- `disabled` is not wired to always-true — it correctly gates only
  PAID/REJECTED invoices.
- No overlapping element intercepts the click — `document.elementFromPoint()`
  at the input's center returns the `<input>` itself in every case tested.
- `readOnly` does flip visually (border-color/background/cursor class change
  confirmed via `getComputedStyle`/`className` diff).

## One real, minor UX defect found as a byproduct
On a resolved (PAID/REJECTED) invoice, the disabled `<input>` still computes
`cursor: text` (confirmed via `getComputedStyle(el).cursor`) — the browser's
default I-beam edit cursor — because `EditableField`'s disabled `stateClass`
(`app/invoices/review/[id]/page.tsx` line ~94-95) sets no `cursor-not-allowed`
/`cursor-default` override. A user hovering a resolved invoice's fields sees
the same "this looks editable" cursor as an actually-editable field, then
nothing happens on click. Combined with the "Resolved — read-only" badge
being small, top-right, and easy to miss, this is a plausible (if unproven)
explanation for the original "does nothing" report if the tester was looking
at an already-resolved invoice rather than an active one.

## Also measured (not this gap, but relevant context)
Cold dev-server load of this page took ~14s from navigation to the fields
being interactive (Clerk dev-handshake redirect chain + `/api/invoices/{id}`
+ `/api/invoices/{id}/pdf` all sequential) under this session's constrained
system memory (~85MB free RAM at test time). A click during that window
would also appear to "do nothing" since the fields don't exist yet — a
possible secondary explanation, not confirmed as the actual cause.

## Conclusion
Gap 82 does not reproduce as a broken click handler. Recommend closing as
"cannot reproduce as described" or rewriting to track the real, minor
`cursor: text` affordance bug on resolved invoices instead.
