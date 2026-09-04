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

## 2. Implement

- Deterministic code for anything deciding correctness (hard rule 3).
- Match surrounding style. No drive-by refactors, no speculative abstractions.
- Cite the **correct** gap number in code comments. `agents/query_agent.py` currently cites
  "Gap 380" for work that is BE Gap 382 — that is the mistake this line exists to prevent.

## 3. Verify

`/verify-postgres` for anything touching the DB or an API. Smallest relevant test file first;
widen only at a track boundary. Keep the exact pass/fail line — it is what gets cited.

## 4. Update three places, not one

1. **Tracker** — mark the entry, record what actually changed, and paste the evidence line.
2. **Spec body** — the `feature_N_*.md` whose functionality the bug lives in. A tracker-only
   update leaves the spec describing behaviour the code no longer has.
3. **Code comment** — the gap number, spelled with its app prefix.

## 5. Close out

`/done` before marking `[x]`, then `/hand-back`.
