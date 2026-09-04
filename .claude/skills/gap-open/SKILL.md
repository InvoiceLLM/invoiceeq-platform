---
name: gap-open
description: File a new Gap entry with symptom, evidence, root cause and proposed fix — investigation only, no code. Use when the founder reports a defect, asks to open a gap item, or asks what is wrong with something.
---

# Open a gap

A gap entry is filed **before** the fix, and the fix is a separate approved step
(`/gap-work`). This skill writes no code.

## 1. Evidence first

Reproduce it, or find the code path that produces it. A gap without evidence is a guess, and
this repo has been burned by guesses recorded as findings. Cite the real thing: a query
result, a log line, a test failure, an exact source line.

## 2. Number it — collision check immediately before writing

Gap numbers are unique per tracker, but the repo cites them from code, tasklists and specs
too, so check everywhere:

```bash
cd "C:/Users/S Banerjee/Desktop/Invoice_LLM" && grep -rhoE "Gap [0-9]{1,4}" --include="*.md" --include="*.py" --include="*.ts" --include="*.tsx" --exclude-dir=node_modules --exclude-dir=.git . | grep -oE "[0-9]+" | sort -n | uniq | tail -5
```

Take max + 1. Re-run this immediately before writing the entry, not earlier in the task —
another run may have taken the number.

## 3. Always write the app prefix

`BE Gap 414`, `FE Gap 414`, `Website Gap 414`. **Never a bare "Gap 414".** BE Gap 378 and
FE Gap 378 are two unrelated items that already collided once; the bare form is what caused it.

## 4. Write the entry

Into that app's tracker, under **Open Items / Gaps**, matching the surrounding entry style,
marked `[ ]`, with these four blocks:

- **Symptom** — what the founder or the system actually saw.
- **Evidence** — the reproduction, with the real output pasted.
- **Root cause** — the specific code path, `file.py:line` and function name.
- **Proposed fix** — what should change, and why that shape. If correctness is being decided,
  the fix is deterministic code, not a prompt rule (hard rule 3).

## 5. Stop

Report in chat: gap id, one-line root cause, one-line proposed fix. Then stop and wait for
approval. Writing the fix is `/gap-work`.
