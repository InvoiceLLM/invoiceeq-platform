---
name: new-feature
description: Author a new feature spec doc for invoice-be, invoice-fe or invoice-website before any code is written. Use when the founder has finished discussing a functionality and asks to write it up, spec it out, create a feature doc, or "make this a feature".
---

# Author a feature spec

The founder discusses functionality in chat, then asks for it to be written up. This skill
writes the spec — and nothing else. No code is written under this skill.

Rules that govern this: `.claude/CONVENTIONS.md` hard rule 1 (founder gate) and hard rule 4
(never delete or rewrite an approved spec — new design goes in a new `feature_N.x` sub-file).

## 1. Decide which app and which number

- BE → `Prod_Invoice_LLM/apps/invoice-be/docs/`
- FE → `Prod_Invoice_LLM/apps/invoice-fe/docs/`
- Website → `Prod_Invoice_LLM/apps/invoice-website/website_features/`

Feature numbers are per-app, so the same number exists in more than one tracker. Take the
highest `Feature N` in that app's tracker and add one. If the functionality spans apps, it
gets one spec per app, each cross-referencing the others (precedent: BE Feature 25 /
FE Feature 17 / Website Feature 7).

Read two recent sibling specs in the same folder before writing, to match house style.

## 2. Write the file

`feature_<N>_<slug>.md`, with these sections in this order:

1. **Overview** — what this does, in the founder's own framing, and explicitly what it is
   *not* (name any naming collision with existing features).
2. **File Coordinates** — a table: `path | named function / component | new or edit | what it does`.
   Named functions and components are mandatory. A path alone is not a coordinate.
3. **Functionality** — narrative walkthrough of the runtime path end to end: what enters,
   what each named function does to it, what is persisted, what the caller gets back.
4. **Data & schema changes** — models, new columns, the Alembic migration, or "none".
5. **Tasks** — numbered `N.1`, `N.2`, … Each independently completable and independently
   testable. These become the build tasklist verbatim, so write them at that granularity.
6. **Verification Plan** — per task, the real check that proves it. Anything touching the DB
   or an API cites a Postgres run (hard rule 2). Anything deciding correctness — math,
   reconciliation, sign handling, validation — is deterministic code, never a prompt rule
   (hard rule 3); say so here.
7. **Open decisions** — anything needing a founder call, written as a question, not a guess.

## 3. Add the tracker row

One `[ ]` row in that app's tracker linking the new doc. Status lives in the tracker; design
lives in the spec. Never duplicate status into the spec.

## 4. Stop

Report in chat: doc path, task count, open decisions. Then stop — implementation waits for
the founder's approval of this spec. Do not start building, and do not create the tasklist;
that is `/build-feature`.
