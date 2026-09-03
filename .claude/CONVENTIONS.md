# Agent Conventions

Shared rules for every persona under `.claude/agents/`. Each persona file references this instead of restating it — if a rule needs to change, change it here once.

## Hard rules — these override everything else in this file

1. **Founder gate.** No implementation (code, docs, infra) begins without explicit founder approval of the stated scope, in this conversation. Architect proposals are never self-executing. Default mode for any task is investigation-only unless the approved scope says implement.
2. **Postgres is the only test evidence.** A fix may not be claimed working on SQLite-only runs — the SQLite/Postgres fidelity gap has been the root cause of 4+ incidents. Any "verified" claim must cite a run against real Postgres.
3. **Deterministic over prompt for correctness.** Any check that decides correctness (math, reconciliation, sign handling, validation) must be deterministic code. Prompt rules alone are not a control — Gaps 220–225/253 all share this failure mode. LLMs explain exceptions; they do not adjudicate them.
4. **Never delete, never rewrite approved specs.** Existing files carry institutional history behind prior fixes. New design goes in new `feature_N.x` sub-files; approved spec bodies get additive updates only.
5. **Check in-flight work first.** Before starting, list `.claude/tasklists/` files modified in the last 7 days and read `active-work.md` (workspace root). If your task overlaps their files or contradicts the current direction, stop and surface the conflict — do not proceed in parallel.
6. **Never commit. Never push. The founder does both.** The end state of every task is changes sitting **uncommitted in the working tree**, visible in the editor's Changes panel — that panel is how the founder reviews work, and a commit removes it from there before it has been read. Concretely:
   - `git commit`, `git push`, `git merge`, `git cherry-pick` (without `-n`), `git reset`, `git stash`: **do not run them** unless the founder's *current* message contains an explicit instruction naming that action for *this* change. "Push the code" earlier in the session authorises nothing later. "Finish the feature", "fix it", "run the tests", "start recovery" are not commit instructions.
   - Before running any of those commands, the agent must be able to quote the founder's sentence that authorised it. If it cannot, it does not run.
   - A task that would "naturally" end in a commit (a merge, a release, a run loop) still ends uncommitted; the agent reports "ready to commit on your word" and stops.
   - If a commit was made by mistake and **not pushed**: say so immediately and offer `git reset --mixed HEAD~1` — the founder runs it or approves it. If it **was** pushed: say so immediately; do not try to rewrite history.
   - This rule exists because it was broken 18 times, most recently on Gap 413 (2026-09-03). It is a hard rule, not a preference: an agent that commits has removed the founder's ability to review.

## Repo layout

This persona folder lives at the true workspace root (the directory containing this `.claude/` folder; moved here from `Prod_Invoice_LLM/.claude/` on 2026-08-01 so discovery works and so architect's scope covers the whole workspace, not just the app subtree). All paths below are relative to this root:
- `Prod_Invoice_LLM/` — the actual product: `apps/` (invoice-be, invoice-fe, invoice-website), `infra/` (bicep/ps1), `reports/`, `docs/`.
- `files_logs/` and `myenv/` — true root-level, **outside** `Prod_Invoice_LLM/`. `files_logs/` is a pre-rebuild (2026-07-03) draft of bicep monitoring/logging/scheduler resources, superseded by `Prod_Invoice_LLM/infra/`'s 2026-07-22 rebuild but never deleted — nothing in the repo references it (confirmed by repo-wide grep, 2026-08-01). Architect should treat both root-level folders as in-scope when auditing for redundancy, not assume everything relevant sits under `Prod_Invoice_LLM/`.

## Priority order and current state

Long-term priority order: **1) finish coding, 2) functional testing, 3) dev/prod environment split, 4) load testing, 5) security testing.** Default to this order when proposing what to work on next unless explicitly told otherwise.

**Current direction, in-flight work, and frozen paths live in `active-work.md` at the workspace root — read it, don't rely on the snapshot below.** The snapshot below is dated 2026-08-01; if `active-work.md` is missing or contradicts it, trust `active-work.md` and flag the discrepancy. As of 2026-08-01, Phase 1 of step 3 is done: `Prod_Invoice_LLM/infra/`'s stage/module bicep is now parameterized on a `networkIsolation` bool (dev=false/no VNet, prod=true/full private networking incl. Redis/Postgres/Storage/OpenAI/DocIntel private endpoints), `params.prod.json`/`params.prod.secrets.json.example` exist, and `.github/workflows/deploy-prod.yml` exists gated on a `production` GitHub Environment. This is templates/params/workflow only — no `az deployment group create` has been run against a prod resource group, and `params.prod.json` still has `REPLACE_WITH_...` placeholders for prod Clerk/Google/Salesforce OAuth values that need real values before an actual prod deploy. ACR is shared between dev and prod (one registry, owned by dev's RG); prod's own resource group (`invoice-llm-prod`) does not exist yet.

## Document types — do not mix these

| Doc type | Location | Owner | What it holds |
|---|---|---|---|
| Tracker | `Prod_Invoice_LLM/apps/*/docs/*_features_tracker.md`, `Prod_Invoice_LLM/apps/invoice-website/website_features/website_features_tracker.md` | senior-dev | Single source of truth for build **status** (`[x]`/`[~]`/`[ ]`), Gap N entries. Numbered sequentially and uniquely per tracker. |
| Spec doc | `Prod_Invoice_LLM/apps/*/docs/feature_N_*.md` | senior-dev | Target **design**: File Coordinates, Functionality narrative, Tasks, Verification Plan. Never duplicates tracker status-tracking. When a bug tied to a spec's functionality is fixed, update the spec body too, not just the tracker. |
| Test coverage map | `Prod_Invoice_LLM/apps/*/docs/test_coverage_map.md` (one per app) | functional-tester | Live status of what's actually automated/manually verified, and when. Not the same as a spec's Verification Plan (design intent, stable) — this is the running record of real test execution. |
| Test evidence | `Prod_Invoice_LLM/apps/*/docs/test_evidence/` | functional-tester | Raw proof — screenshots, DB query results, log excerpts. Linked from the coverage map, not pasted inline into it. |
| Reports | `Prod_Invoice_LLM/reports/{load,security}/<date>-<topic>.md` | load-tester, security-tester | Scope (written before running) + output (filed after) for that run, same file. These are testing-verification records — kept persistently. |

Application code and `Prod_Invoice_LLM/infra/` bicep/ps1 themselves are the record for infra-devops's actual changes. infra-devops does **not** file to `reports/infra/` by default — scope and findings go in chat instead (2026-08-01: the user doesn't want infra scoping/audit work turned into persistent report docs). If a task explicitly calls for a written report, it's a one-off, confirmed in chat, and deleted once the user has reviewed/approved it — not kept the way load/security reports are.

## Live task list — every long-running specialist run maintains one

Any task expected to take more than a few steps (multi-gap repro, a multi-file build, a multi-stage infra change) creates `.claude/tasklists/<agent>-<short-topic>.md` **before starting work** — a plain markdown checklist of the concrete steps planned, one line per step. Update it (check items off, add detail inline) as each step actually completes, not in a batch at the end — the point is that the user can open this file at any time mid-run and see real current status, not just get a summary once the whole thing finishes. This is separate from the final deliverable (tracker/report/coverage-map per the table above); the tasklist is working-state, the tracker/report is the record.

Leave the file in place once the task completes, with every item checked and a one-line final status at the bottom — don't delete it (unlike the ephemeral infra reports pattern). The user can clean these up manually once reviewed.

## Tool orchestration — execution latency rules (founder, 2026-09-03)

Priority: **fast useful answers > exhaustive investigation > perfect certainty.**

1. **Tool budget.** List every independent piece of evidence first; batch independent reads, searches and commands into one call. Never one tool call per turn when calls can be grouped. At most **2–4 evidence rounds** before producing useful output.
2. **Cache everything slow.** Azure logs and App Insights: fetch once per task into the scratchpad, query locally; combine KQL queries. Never re-read a code region whose relevant lines are already inspected. Keep a task ledger: files inspected, line ranges, facts established, commands/results, unresolved questions.
3. **No duplicate investigation.** Before any read or command: "do I already have this evidence?" If yes, reuse it.
4. **Testing strategy.** Never run the full suite first unless asked. Smallest relevant test first; widen only when targeted tests pass and it is justified. No Playwright unless browser behaviour is directly relevant.
5. **Communication deadline.** More than ~2 tool rounds or ~60 s of gathering ⇒ a progress update or partial answer ("here is what I have confirmed so far…"). Never a long silent sequence.
6. **Tool failure.** The same approach failing twice ⇒ stop, diagnose, switch approaches.
7. **Escaping.** Regex- or backslash-heavy content never goes through a shell heredoc — use the Write/Edit tool or a written script. Verify once; do not retry the same escaping.
8. **Expensive commands** (>30 s): state internally what question it answers, whether a cheaper command exists, and whether existing evidence already answers it.
9. **Partial-first.** Large task ⇒ gather enough for the first part, answer it, continue only for what is unresolved.
10. **Do not over-investigate.** Stop at confident, not exhaustive.

**Before every non-trivial task, show a short execution plan:** independent evidence to gather · which calls are batched · slow operations expected · what is cached · test strategy · when the first partial answer lands. Then follow it.

## Chat answers are brief — the default, not the exception

Answer in chat with the shortest thing that is complete: a direct answer, then only
what changes the user's next action. No recap of what was just done, no restating the
question, no narration of the search that produced the answer.

- **Tables over prose** for anything with more than two facts. Name + tiny description
  + recommendation. No explanatory paragraph under each row.
- **Reasoning appears only when the answer is counter-intuitive or a premise is wrong.**
  One or two sentences, then stop.
- **Detail belongs in the file, not the reply.** Build notes, rationale and evidence go
  in the spec, the tracker gap or the commit message — those are read deliberately;
  chat is read in passing.
- Length is earned by consequence, not by effort spent. A 40-minute investigation with
  one actionable finding is a three-line answer.

This applies to every agent's chat output, architect and infra-devops included.

## Scope vs. output — the pattern every non-architect agent follows

1. State scope first: what will be done, to which files, and why. This is what the user approves before execution.
2. Execute.
3. File the output at the same location as the scope (see table above) — concrete evidence, not a summary claiming success. (Precedent: this repo already had docs claiming "verified via Playwright" with no committed test to back it — don't repeat that class of mistake.)

**architect** is the exception: it only ever proposes scope for *other* agents, in chat (or an Artifact for a large multi-agent brief). It has no dedicated output location of its own and never executes anything directly.

**infra-devops** is a partial exception: scope and findings/verification results are also given in chat, not filed to `reports/infra/`, unless the user explicitly asks for a written report — see the Reports row above.

## Agent roles

- **architect** — reads the task + relevant folders, proposes scope per specialist, presents for user approval. Never writes code or docs.
- **senior-dev** — implements. Writes application code, updates the relevant spec doc + tracker per the rules above. Correctness-critical logic is deterministic code, never prompt-only (Hard rule 3).
- **functional-tester** — extends the one canonical automated-test directory per app; every "verified" claim cites a Postgres run, not SQLite (Hard rule 2) (`Prod_Invoice_LLM/apps/invoice-be/tests/`, `Prod_Invoice_LLM/apps/invoice-fe/e2e/`, `Prod_Invoice_LLM/apps/invoice-website`'s equivalent once it exists), maintains `test_coverage_map.md` + `test_evidence/`.
- **load-tester** — reports to `Prod_Invoice_LLM/reports/load/`.
- **security-tester** — reports to `Prod_Invoice_LLM/reports/security/`.
- **infra-devops** — changes `Prod_Invoice_LLM/infra/`, reports in chat (not `reports/infra/`, unless explicitly asked).
