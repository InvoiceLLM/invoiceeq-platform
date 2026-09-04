---
name: feature-status
description: One-line progress delta for an in-flight feature build, plus the hard-stop check. Designed to run on a 10-minute /loop. Use when the founder asks for status on a running build, or when a /loop tick fires.
---

# Status tick

This runs every 10 minutes on a `/loop`. Every tick re-sends the conversation, so it must be
cheap: **at most two reads, no code reading, no test running, no fixing.** A tick that starts
doing work is a bug.

## 1. Read exactly two things

```bash
cd "C:/Users/S Banerjee/Desktop/Invoice_LLM" && cat .claude/tasklists/senior-dev-<slug>.md && echo "---" && git -C Prod_Invoice_LLM status --porcelain | wc -l
```

## 2. Emit one line

```
4/11 · N.5 chat attachment persist · 6 files changed · 38m to hard stop
```

Count `- [x]` against total. Name the task currently in progress (the first unchecked one).
Nothing else — no recap of what was built, no summary of the feature.

## 3. Three exit conditions — check them in this order

| Condition | Action |
|---|---|
| Every task checked | Stop the loop. Run `/done`, then `/hand-back`. |
| Hard stop reached or passed | Stop the loop. Report: tasks done, tasks unfinished, files changed and uncommitted, what the next session must pick up. **Start no new work.** |
| Same counts three ticks running | Say "no movement since <time> — possible stall" on the tick, and keep going. Do not intervene. |

## 4. Never

- Never edit code, tests, docs or the tasklist from a status tick.
- Never commit anything (hard rule 6).
- Never report progress you did not read out of the tasklist — if the file has not been
  updated, the honest tick is "tasklist not updated since <its mtime>", not an inferred guess.
