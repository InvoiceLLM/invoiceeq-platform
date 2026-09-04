---
name: done
description: Definition-of-done gate — run before marking any feature, task or gap [x] in a tracker. Use when about to claim work is complete, verified, or finished.
---

# Definition of done

The dominant failure state in this repo is `[x]` on work that was written and reviewed but
never proven — Feature 27 and Feature 26 Part 2 are both sitting in it right now. This gate
exists to keep "built" and "verified" apart.

Answer every item with **yes + a citation**, or **no**. A citation is a command and its real
output line, not a recollection.

| # | Check |
|---|---|
| 1 | Every task in the spec's Tasks section implemented? |
| 2 | Every item in the spec's Verification Plan actually run? Cite command + result line for each. |
| 3 | DB- or API-touching work run against **Postgres**, not SQLite? Cite the run. |
| 4 | Migration **applied** (`alembic upgrade head` against Postgres), not merely written? |
| 5 | Spec body updated to describe what was actually built, with deviations named? |
| 6 | Tracker status marker and gap entry updated, gap numbers carrying their `BE`/`FE`/`Website` prefix? |
| 7 | Test evidence filed and the coverage map row updated, if this was functional-tester work? |
| 8 | Changes uncommitted and visible in the founder's Changes panel? |

## Verdict

- **All yes** → mark `[x]`, with the evidence citation in the tracker entry itself.
- **Any no** → mark `[~]` code-complete / unverified, and say in chat exactly which numbered
  item failed and why. Do not round up. "Verified" language without a real run behind it is
  the specific mistake this repo has already made in its own docs.
