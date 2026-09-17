---
name: gap-work
description: Implement an approved gap fix and close it out across code, spec and tracker. Use when the founder says work the gap, fix gap N, or approves a proposed fix.
---

# Work an open gap

Precondition: the gap entry exists with a **Proposed fix**, and the founder approved it.
If there is no entry yet, use `/gap-open` first — no code change lands in this repo without a
matching gap entry filed as part of the same change.

## 1. Re-read the entry against current code

The proposed fix may have been written days ago. If the code no longer matches the recorded
root cause, stop and say so — do not quietly fix something else under that number.

## 2. State the defect CLASS and the call-site count — before writing code

An entry that describes a symptom ("PO-VPI-1041 shows the wrong days") produces a local fix.
An entry that describes a class ("a card computes days-from-term and labels it days-from-today")
produces a real one. Write the class sentence, then answer in the entry:

- **How many call sites have this defect?** Grep for the pattern, not the symptom. If the
  defect is in ten cards and you fix one, say so explicitly and say why the other nine wait.
- **What does the fix NOT handle?** A real abstraction has a boundary you can state. If you
  cannot state one, you have written a patch.

## 3. Implement

- Deterministic code for anything deciding correctness (hard rule 3).
- Match surrounding style. No drive-by refactors, no speculative abstractions.
- **No data in code.** Domain facts — vendor names, item synonyms, narration keywords, rule
  text, tolerances — go in a registry, table or threshold config the tenant can extend, never
  in an `if`. The test (Feature 30 §11.2): *would this line need editing when a new vendor,
  language, item, bank or document type arrives?* If yes, it is the wrong fix.
- The `PostToolUse` guard (`.claude/hooks/check_hardcoding.py`) flags the mechanical half of
  this as you edit. It is advisory — answer it, do not route around it.
- Cite the **correct** gap number in code comments. `agents/query_agent.py` currently cites
  "Gap 380" for work that is BE Gap 382 — that is the mistake this line exists to prevent.

## 4. Verify

`/verify-postgres` for anything touching the DB or an API. Smallest relevant test file first;
widen only at a track boundary. Keep the exact pass/fail line — it is what gets cited.

**Frontend work also needs `npm run typecheck`** in `invoice-fe` / `invoice-website`. The image build
runs `next build`, which typechecks, and neither app sets `ignoreBuildErrors` — so a type error is not
untidiness, it is a deploy that fails inside a Docker build at the end of the pipeline. No test in this
repo catches it (FE Gap 639).

Also run `tests/test_no_hardcoding.py` — the durable half of the guard.

**The test must assert a property, not the fixture's output.** `assert title == "₹437,190.00 …"`
passes for one invoice; `no finding title contains a bare \d+\.\d` passes for all of them.
Then mutate the fixture — rename the vendor, swap the currency, translate an item description,
add a line — and confirm it still passes for the right reason. If you cannot produce a second,
unrelated fixture the fix also repairs, the fix is not generic.

## 5. Update three places, not one

1. **Tracker** — mark the entry, record what actually changed, and paste the evidence line.
2. **Spec body** — the `feature_N_*.md` whose functionality the bug lives in. A tracker-only
   update leaves the spec describing behaviour the code no longer has.
3. **Code comment** — the gap number, spelled with its app prefix.

## 6. Close out

`/done` before marking `[x]`, then `/hand-back`.
