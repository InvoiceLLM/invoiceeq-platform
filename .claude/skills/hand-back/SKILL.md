---
name: hand-back
description: End-of-task close-out — confirms nothing was committed, closes the tasklist, and reports what changed. Use at the end of any task before reporting completion to the founder.
---

# Hand back

Every task in this repo ends with changes sitting **uncommitted in the working tree**, visible
in the founder's Changes panel. That panel is how the work gets reviewed; a commit removes it
from there before it has been read (`.claude/CONVENTIONS.md` hard rule 6, broken 18 times).

## 1. Prove nothing was committed

```bash
cd "C:/Users/S Banerjee/Desktop/Invoice_LLM" && git status --porcelain && echo "--- unpushed commits ---" && git log origin/master..HEAD --oneline
```

- Second command empty → correct, continue.
- Second command shows a commit made during this task → **say so immediately**, in the first
  line of your report. Offer `git reset --mixed HEAD~1` and let the founder run or approve it.
  Do not run it yourself. If it was already pushed, say that too and do not rewrite history.

## 2. Close the tasklist

In `.claude/tasklists/<agent>-<topic>.md`: every item checked, or explicitly marked not-done
with a one-line reason. Add a final status line at the bottom. Leave the file in place — the
founder cleans these up, not you.

## 3. Report, briefly

Four lines, no recap of the work:

- **Changed** — the file list.
- **Verified** — the citation (command + result line), or "not verified" and why.
- **Left open** — what remains, and what blocks it.
- **Needs a founder call** — decisions you deliberately did not make.

## 4. Never

`git commit`, `git push`, `git merge`, `git reset`, `git stash`, `git cherry-pick` — unless the
founder's **current** message names that action for **this** change, and you can quote the
sentence. A task that would "naturally" end in a commit still ends uncommitted: report
"ready to commit on your word" and stop.
