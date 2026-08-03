# Agent Conventions

Shared rules for every persona under `.claude/agents/`. Each persona file references this instead of restating it — if a rule needs to change, change it here once.

## Repo layout

This persona folder lives at the true workspace root (`c:\Users\S Banerjee\Desktop\Invoice_LLM`, moved here from `Prod_Invoice_LLM/.claude/` on 2026-08-01 so discovery works and so architect's scope covers the whole workspace, not just the app subtree). All paths below are relative to this root:
- `Prod_Invoice_LLM/` — the actual product: `apps/` (invoice-be, invoice-fe, invoice-website), `infra/` (bicep/ps1), `reports/`, `docs/`.
- `files_logs/` and `myenv/` — true root-level, **outside** `Prod_Invoice_LLM/`. `files_logs/` is a pre-rebuild (2026-07-03) draft of bicep monitoring/logging/scheduler resources, superseded by `Prod_Invoice_LLM/infra/`'s 2026-07-22 rebuild but never deleted — nothing in the repo references it (confirmed by repo-wide grep, 2026-08-01). Architect should treat both root-level folders as in-scope when auditing for redundancy, not assume everything relevant sits under `Prod_Invoice_LLM/`.

## Priority order

This repo's current priority, in order: **1) finish coding, 2) functional testing, 3) dev/prod environment split, 4) load testing, 5) security testing.** Default to this order when proposing what to work on next unless explicitly told otherwise. As of 2026-08-01, Phase 1 of step 3 is done: `Prod_Invoice_LLM/infra/`'s stage/module bicep is now parameterized on a `networkIsolation` bool (dev=false/no VNet, prod=true/full private networking incl. Redis/Postgres/Storage/OpenAI/DocIntel private endpoints), `params.prod.json`/`params.prod.secrets.json.example` exist, and `.github/workflows/deploy-prod.yml` exists gated on a `production` GitHub Environment. This is templates/params/workflow only — no `az deployment group create` has been run against a prod resource group, and `params.prod.json` still has `REPLACE_WITH_...` placeholders for prod Clerk/Google/Salesforce OAuth values that need real values before an actual prod deploy. ACR is shared between dev and prod (one registry, owned by dev's RG); prod's own resource group (`invoice-llm-prod`) does not exist yet.

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

## Scope vs. output — the pattern every non-architect agent follows

1. State scope first: what will be done, to which files, and why. This is what the user approves before execution.
2. Execute.
3. File the output at the same location as the scope (see table above) — concrete evidence, not a summary claiming success. (Precedent: this repo already had docs claiming "verified via Playwright" with no committed test to back it — don't repeat that class of mistake.)

**architect** is the exception: it only ever proposes scope for *other* agents, in chat (or an Artifact for a large multi-agent brief). It has no dedicated output location of its own and never executes anything directly.

**infra-devops** is a partial exception: scope and findings/verification results are also given in chat, not filed to `reports/infra/`, unless the user explicitly asks for a written report — see the Reports row above.

## Agent roles

- **architect** — reads the task + relevant folders, proposes scope per specialist, presents for user approval. Never writes code or docs.
- **senior-dev** — implements. Writes application code, updates the relevant spec doc + tracker per the rules above.
- **functional-tester** — extends the one canonical automated-test directory per app (`Prod_Invoice_LLM/apps/invoice-be/tests/`, `Prod_Invoice_LLM/apps/invoice-fe/e2e/`, `Prod_Invoice_LLM/apps/invoice-website`'s equivalent once it exists), maintains `test_coverage_map.md` + `test_evidence/`.
- **load-tester** — reports to `Prod_Invoice_LLM/reports/load/`.
- **security-tester** — reports to `Prod_Invoice_LLM/reports/security/`.
- **infra-devops** — changes `Prod_Invoice_LLM/infra/`, reports in chat (not `reports/infra/`, unless explicitly asked).
