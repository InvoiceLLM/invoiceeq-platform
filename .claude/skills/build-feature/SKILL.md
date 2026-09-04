---
name: build-feature
description: Start development of an already-approved feature spec, with a live tasklist and a hard stop. Use when the founder says build, develop, complete or finish a feature, or names a feature number to work on.
---

# Build an approved feature

Precondition: the spec exists and the founder approved it **in this conversation**
(`.claude/CONVENTIONS.md` hard rule 1). Be able to quote the approving sentence. If you
cannot, ask for approval and stop.

## 1. Preflight (hard rule 5) — do this before anything else

Batch these in one call:

```bash
cd "C:/Users/S Banerjee/Desktop/Invoice_LLM" && cat active-work.md && ls -lt --time-style=long-iso .claude/tasklists | head -15
```

Then:
- Does the feature appear under **Frozen / do not touch** in `active-work.md`? → stop, say so.
- Does it overlap a tasklist touched in the last 7 days? → stop, surface the conflict.
- Does it contradict **Current direction**? → stop, surface it.

Do not proceed in parallel with in-flight work. Surfacing the conflict *is* the deliverable
in that case.

## 2. Create the tasklist before writing any code

`.claude/tasklists/senior-dev-<feature-slug>.md`:

```
# <Feature N: name> — build
Spec: <relative path to the spec>
Started: <YYYY-MM-DD HH:MM>
Hard stop: <YYYY-MM-DD HH:MM>
Definition of done: every task below checked; every Verification Plan item run and cited;
spec body and tracker updated; changes uncommitted.
Status: in progress

- [ ] N.1 <task, verbatim from the spec>
- [ ] N.2 ...
```

The **Hard stop** is not optional. If the founder did not give one, ask for it in the same
message as your plan and default to 4 hours from now if they don't specify.

Tasks come from the spec's Tasks section verbatim — do not re-scope them here.

## 3. Dispatch

Run the build as a **background `senior-dev` subagent**, passing it the tasklist path. Tell it:

- Tick each `- [ ]` to `- [x]` **as that step actually completes**, never in a batch at the end.
  This file is the only live surface the founder can watch while you run.
- Any defect found along the way gets a gap entry filed in the same change (`/gap-open`),
  never a silent fix.
- Correctness-deciding logic is deterministic code, not a prompt rule (hard rule 3).
- Verify DB/API work with `/verify-postgres`. SQLite is not evidence (hard rule 2).
- Never commit, push, merge, reset or stash (hard rule 6).

Background matters: the main session must stay free, or no status tick can fire while the
build runs.

## 4. Hand the founder the status loop

Tell them, in one line:

```bash
/loop 10m /feature-status <feature-slug>
```

## 5. On completion

Run `/done` before marking anything `[x]`, then `/hand-back`.
