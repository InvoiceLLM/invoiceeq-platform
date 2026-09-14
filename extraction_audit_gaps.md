# Extraction Production-Readiness Audit — Verification Against This Tree

| | |
|---|---|
| **Date** | 2026-09-14 |
| **Status** | **VERIFIED — investigation only, nothing filed to the tracker** (CONVENTIONS hard rule 1) |
| **Verified against** | `master` @ `69f68b8` + the 2026-09-13/14 uncommitted work (anti-hardcoding harness, Feature 30 Track A, Gaps 520/521) |
| **Source document** | `extraction_audit_gaps.md` as received 2026-09-13, produced on another machine (`D:/testllm/...`, code basis `cca7aa6`) |
| **Founder question** | "check if the above attached document issues are real, also already resolved by the uncommitted task" |

## Answer in one line

**9 of 11 findings are real, 1 is wrong for the deployed environment, 1 is partly right — and none of them is resolved by the uncommitted work.** The document cannot be applied to the tracker as written because of the two problems below.

## Two blocking problems with the source document

1. **Gap numbers collide.** It proposes `BE Gap 509–519`. In this repo those numbers are already taken: 509–519 are the Feature 30 dry-run gaps filed 2026-09-09, and 520/521 were filed 2026-09-14 (builder-readback tolerance; two stale tests). Its "highest existing = 508" was read from a stale tracker. **Next free BE gap number here is 522.**
2. **Different code basis.** It cites `master @ cca7aa6 (fast-forwarded from 69f68b8)`. At verification time this machine's HEAD was `69f68b8` and `cca7aa6` was 7 commits ahead on `origin/master` (all FE InfiNevo theme work, FE Gaps 488–495). No backend file differs between the two bases, so every code citation below was checked and holds on both.

## Claim-by-claim verification

Tag: **Real** = the cited code exists as described. **Resolved** = closed by the uncommitted work. Renumbering shows where each would land if filed.

| Their # | Would file as | Claim | Real? | Evidence checked | Resolved by uncommitted work? |
|---|---|---|---|---|---|
| 509 | **522** | Money stored as `float` in `Invoice` / `Document` | **Yes** | `models.py:99,100,104,123,353-356,533` all `float \| None` | No |
| 510 | **523** | No extraction lineage (model / prompt / schema version) persisted | **Yes** | zero hits for `model_id`, `prompt_version`, `schema_version`, `prompt_hash` in `models.py` | No |
| 511 | **524** | 0.6 confidence threshold is an uncalibrated placeholder | **Yes** | `models.py:307` says so in its own comment | No |
| 512 | **525** | `build_llm()` sets no request timeout or retry count | **Yes** | zero hits for `timeout` / `max_retries` in `utils/llm.py` | No — see coordination note |
| 513 | **526** | `prebuilt-invoice` runs for every document type | **Yes** | `queue_worker/handlers.py:350-351` docstring admits it; `config.py:577` `DOC_INTEL_MODEL_ID = "prebuilt-invoice"`; no `prebuilt-layout` branch | No |
| 514 | **527** | "99.3% / <3.8s" claim does not reproduce | **Partly** | The claim exists only in `PROJECT_STATUS.md` — **not** on the website or in any presentation in this repo. The `24-53 s` figure is real at `agents/extraction_agent.py:2518` | No |
| 515 | **528** | Ground-truth fixtures at ~2 of 10 document types | **Yes** | `active-work.md:25` verbatim ("task F … at ~2 of 10 document types") | No |
| 516 | — | Empty fast deployment forces reasoning model everywhere | **Wrong for the deployed environment** | The *code default* `AZURE_OPENAI_FAST_DEPLOYMENT_NAME = ""` (`config.py:525`) is real, but the variable is wired into every container in `infra/modules/compute/invoice-be.bicep:365`, `queue-worker.bicep:335`, `scheduled-job.bicep:269`, is set in local `.env`, and Feature 29 closed with fast = `gpt-5.6-luna`. The audit read the default and not the environment. **Do not file.** | N/A |
| 517 | **529** | No batch re-extraction for historical documents | **Yes** | nothing under `scripts/` matching reprocess / re-extract / backfill; `routers/audit.py:306` is single-item | No |
| 518 | **530** | Extraction prompt has no injection framing around OCR text | **Yes** | zero hits for `document_data` / `untrusted` / `INJECTION` in `agents/extraction_agent.py` | No — but cheaper than proposed: `_INJECTION_GUARD_INSTRUCTION` already exists at `agents/query_agent.py:2523` and should be lifted into a shared util, not rewritten |
| 519 | **531** | Empty `mcp_servers/`; stale "directory watcher" wording | **Yes** | directory exists and is empty; `services/file_intake.py:3` names the watcher | No |

## Why none of it is resolved by the uncommitted work

The 26 uncommitted files touch `services/attachment_insights.py`, `utils/verification_tools.py` (one dedicated constant), `agents/query_agent.py` (one de-identified prompt literal), `pyproject.toml`, tests, trackers, skills and hooks. **None of them touches `models.py`, `utils/llm.py`, `queue_worker/handlers.py`, `agents/extraction_agent.py`, `services/file_intake.py`, `scripts/` or `mcp_servers/`.** Verified with `git status --porcelain` filtered on those paths: empty.

## Notes for the founder before filing

- **Their 509 (float money) is the consequential one.** It is a schema change to the two central tables and it alters what every benchmark and arithmetic check records. The add-only-migration rule permits it mechanically; whether Feature 27's frozen taxonomy covers *column types* is a founder ruling, not an engineering call.
- **Their 512 (LLM timeouts) overlaps Feature 29's territory** and the 2026-09-05 LLM model audit. Coordinate with that work rather than filing blind.
- **Their 514** should be rewritten as a `PROJECT_STATUS.md` correction, not a marketing gap — the number is not published anywhere customer-facing in this repo.
- The anti-hardcoding harness built 2026-09-13 (`.claude/hooks/check_hardcoding.py`, `tests/test_no_hardcoding.py`) will apply to any fix landed for these — in particular their 511 (a calibrated threshold must live in config/table, not an `if`) and 513 (a doc-type → OCR-model choice must be a registry, not a branch).

## If approved

Renumber to **BE Gap 522–531**, drop their 516, rewrite their 514 as above, and file under Open Items in `Prod_Invoice_LLM/apps/invoice-be/docs/be_features_tracker.md`. Nothing has been filed yet.
