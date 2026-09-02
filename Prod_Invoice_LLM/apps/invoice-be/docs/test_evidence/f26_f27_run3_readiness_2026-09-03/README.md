# Flag-flip readiness — `ENABLE_GENERIC_EXTRACTION` and `ENABLE_GENERIC_DOC_CHAT`

**Date:** 2026-09-03 · **Branch:** `feature/f27-f26-uncommitted-2026-09-02`
**Run:** autonomous build run 3, 02:10–03:00 · **Persona:** functional-tester

One page, one question: **what evidence exists behind flipping each flag in dev,
and what does not.** Both flags are still `False` in code. Flipping is the
founder's decision; this note is the input to it, not the decision.

---

## 1. The suite runs

| Run | Result |
|---|---|
| **Backend, full** (`pytest tests/`) | **16 failed · 2684 passed · 1 skipped · 5 deselected** (132s) |
| Pre-work baseline (end of run 2) | 16 failed · 2607 passed · 1 skipped |
| **Failure set** | **Identical, name for name.** All 16 are the same tests, listed in `02_full_suite_failures.txt` alongside the baseline's |
| Net | **+77 passing**, zero new failures |
| **FE typecheck** (`npx tsc --noEmit`) | **Clean** |
| **Playwright, full** (137 cases) | **122 passed · 15 failed** (6.4m) |

**None of the 16 backend failures belongs to Feature 26 or 27.** They are
`test_ops_recommendation` (8 workbook-band parametrisations),
`test_rag` (4), `test_chat_training`, `test_connectors`,
`test_workflow_drive_archive`, `test_workflow_email_summary` — the same set
recorded on 2026-09-02, before any of this work started.

**Of the 15 Playwright failures, exactly one is in scope**, and it is already
filed: **FE Gap 392** — `chat-attachment-upload.spec.ts` asserts the chip passes
through `extracting`, but under route interception it goes `uploading → ready`
too fast to observe. The test is wrong about correct product behaviour. The other
14 are pre-existing surfaces untouched by this work (audit console, help-support,
rbac-sidebar, async-queue, layout-overflow).

**Two honesty notes about how these numbers were obtained.**

1. The full backend suite had to be run **three times**. The first died on a
   collection error — two untracked local scratch scripts, `tests/us/` and
   `tests/realworld_tenant/run_chat_live_test.py`, share a basename and neither
   directory has an `__init__.py`. Neither is in the repo. The recorded run
   excludes the duplicate with `--ignore=tests/us/run_chat_live_test.py` and is
   otherwise unmodified.
2. The second died **mid-run with a native torch access violation**, taking the
   process down with no failure list — because Tier 3 now reaches the real
   embedding model and Playwright was running concurrently. That is **Gap 401**,
   filed and fixed here. The recorded run is the third: the backend suite alone,
   clean. A crash that eats 2600 results is worth naming rather than retrying
   quietly.

---

## 2. `ENABLE_GENERIC_EXTRACTION` — flippable in dev

**Evidence that supports it:**

| Claim | Evidence |
|---|---|
| Classification works on real documents | **24 fixtures, 13 of 14 taxonomy values, 24/24 correct** through the real `classify_doc_type()` over real PDF text (`tests/test_a_series_fixtures.py`, 55 passed) |
| It works *cheaply* | **24/24 deterministic, zero model calls.** Asserted on `doc_type_method`, not just the answer — which is how Gap 396 was found |
| The confidence threshold is calibrated, not guessed | **0.6 → 0.75** on six measured LLM-path confidences (0.90/0.92/0.93/0.95/0.95/0.95; nothing observed between 0.60 and 0.90). Both numbers kept in `MANIFEST.md`. Demotes nothing in the fixture set |
| A classified non-invoice is visible to its uploader | `GET /documents` + `GET /documents/{id}` (G14), and the FE list surface (`510c444`) — R5's rollout gate |
| The browser can learn the flag is on | `GET /config/features`, fail-closed on the FE. `tests/test_config_features.py` → 7, weighted towards what it must **not** publish |
| The uploader can pick a non-PDF | `DropZone` widened on **both** guards from one flag-derived list — FE Gap 378 closed |
| A document's chunks do not outlive it | `DELETE /documents/{id}` + batch rollback, chunks dropped after commit; `docs_` in the reembed prefix set and the sandbox sweep. **11 tests on real Postgres** |
| The invoice path did not move | T-R-3 equality holds inside the full run; no invoice test changed state |

**What is NOT covered, stated plainly:**

- **Gap 398 (open).** A document can be deleted and the product's audit trail does
  not record it — `AuditLog.invoice_id` is non-nullable. Logged at INFO only.
- **No human has driven a non-PDF upload end to end.** The widening is tested;
  the experience is not.
- The `>= 7`-day soak has not started. That is a **removal** criterion, not a flip
  criterion — see §4.

**Read:** the build gate in `config.py` is met. The flip is supportable.

---

## 3. `ENABLE_GENERIC_DOC_CHAT` — flippable in dev, with one caveat that is not about the flag

**Evidence that supports it:**

| Claim | Evidence |
|---|---|
| The answer contract reaches the browser | H16 + B12: persisted on `ChatMessage.attachment_payload`, flattened on **both** the POST return and the GET reload. Migration `f5a6b7c8d9e0` applied to Postgres and read back. V-27 asserts on the HTTP body, which is how the second instance of Gap 386 *inside its own fix* was caught |
| Prompt injection has a real control | V-25 probe **run**, not reasoned about. It found **Gap 395** — Azure's own jailbreak classifier blocks the content-branch prompt (HTTP 400, `jailbreak: detected=true`), a defence layer nothing had recorded, plus misleading retry copy. Fixed |
| Discovery degrades honestly | Tier 3 (E-4) fires from **both** the empty-tier-2 branch and the missing-party/date early return — V-12 caught that only the second one matters. Unreachable Chroma logs and returns `[]`, never fails the turn |
| Comparison and reconciliation are deterministic | `compare_documents()` four modes, L1/L2/L3 matcher, `reconcile_referenced_documents()` five outcomes. 31 + 11 tests |
| Flag-off is byte-identical to Part 1 | 6 flag-off parity tests |
| The FE renders each contract key | `tsc` clean; `chat-attachment-contract.spec.ts` green; 122/137 Playwright with one in-scope known failure |

**The caveat, and it is real: the TTL sweep is deployed and not working.**
**Gap 400.** `caj-chat-doc-ttl-dev` exists in Azure (`Succeeded`, Schedule,
`0 5 * * *`, timeout 1800, `--limit 500`), and its first execution **failed**:
`can't open file '/app/scripts/sweep_chat_attachments.py'`. The ACR image predates
the script's commit. Until an image built at or after `84e3a85` is pushed, expired
chat attachments are **not** being purged.

**Why this does not block the flip, stated precisely rather than waved away.**
Attachments are created by the upload endpoint, which is **not** gated by this
flag — `attachment_id` presence is the routing switch (B11 item 1). Turning the
flag on changes how an attachment turn is *answered*, not whether attachments
accumulate. The retention defect exists identically with the flag off. It is
urgent on its own terms and independent of this decision.

**What is NOT covered:**

- **Gap 400** above — deployed and failing is not done.
- The intent split's keyword lists have **never been measured against real
  traffic**. They are hand-written alternations. No misroute rate exists.
- **No human has driven this surface end to end**, and no screenshot is filed.
- FE Gap 392 remains open (a test defect, not a product one).

---

## 4. Flip criteria vs removal criteria — the distinction that matters here

`config.py` now carries a **removal** criterion for each flag (F27 R12, F26
R13/B11). Several items above are unmet *against those*, and that is expected:
they are the conditions for **deleting the flag-off branch**, which needs a soak,
a measured misroute rate and a human pass. None of them is a precondition for
turning a flag on in **dev**, which is how you obtain the traffic those criteria
are measured from.

Nothing in this run measured a figure by inference. The threshold came from six
recorded confidences; the suite numbers from a recorded run; the job's state from
reading the resource back and starting it.

---

## 5. What is still open after this run

| # | Item | Owner |
|---|---|---|
| 1 | **Gap 400** — rebuild and push `invoice-be:latest` from ≥ `84e3a85`, re-run the job, record an execution reaching `Succeeded` | infra-devops |
| 2 | **B11 soak** — ≥ 7 days, zero `attachment_no_indexed_text` on documents that did index | founder / ops |
| 3 | **The flag flip itself** | founder |
| 4 | Gap 398 — document audit trail (migration + reader sweep) | senior-dev |
| 5 | FE Gap 392 — the chip-state test race | senior-dev |
| 6 | A human end-to-end pass with a screenshot, both features | functional-tester |

## Files

- `01_full_suite_backend.log` — the recorded run, 16/2684/1
- `02_full_suite_failures.txt` — the 16, beside the baseline's 16
- `03_playwright_full.log` — 122/137
- `04_containerapp_job_show.txt` — `caj-chat-doc-ttl-dev` read back from Azure
