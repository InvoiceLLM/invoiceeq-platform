# senior-dev: Gap 317 — nightly `caj-benchmark-eval-dev` FileNotFoundError on default output path

Scope: verify the reported crash against the *current* code with a real docker build/run of
`docker/Dockerfile.be`, fix if still present, close Gap 317 with real evidence. No bicep/infra
deploy, no Gap 318 work, leave everything uncommitted.

- [x] Read CONVENTIONS.md, active-work.md, Gap 317 entry, `scripts/run_agent_eval.py` output-path logic
- [x] Check for an existing partial fix — **found**: `default_output_dir()` already exists, added under
      **Gap 308** (not 299), committed `ed6f8c1` 2026-08-24 13:18 UTC, with 7 tests. Gap 317 as filed is a
      duplicate of Gap 308 at code level.
- [x] Read prior repro method (`infra-devops-feature23-benchmark-eval-job-deploy.md` step 5,
      `infra-devops-nightly-eval-docker-verify.md`)
- [x] **Why the crash was still seen live**: the locally-cached `acrinvoicellmdev2.azurecr.io/invoice-be:latest`
      (created 2026-08-24T09:08:22Z, i.e. ~4h *before* the fix commit) contains **no `default_output_dir` at
      all** — verified by reading `/app/scripts/run_agent_eval.py` inside it. The fix is in code, not in the
      image the nightly job runs.
- [x] Build the real image: `docker build -f docker/Dockerfile.be -t invoice-be-gap317:local .` — exit 0
- [x] Confirm `/app/tests` absent in the built image (`benchmarks/` present) — confirmed
- [x] BEFORE: pre-Gap-308 body restored in-image → 1 turn graded, 1 row committed to real Postgres, then
      `FileNotFoundError: '/app/tests/agent_eval_output.json'`, EXIT=1
- [x] AFTER: unmodified image, same argv → EXIT=0, `Wrote 1 turns to /tmp/agent_eval_output.json`
- [x] Decide the code change: keep the script-level default (bicep stays `--out`-free, two tests pin that);
      add the missing half — `main()` now creates `--out`'s parent dir, so a caller-supplied path cannot
      reproduce the same end-of-run crash
- [x] Tests: 2 new in `tests/test_run_agent_eval_cli.py` (9 total, was 7); mutation-checked — removing the
      one-line fix fails the new test
- [x] `ruff check` clean on both touched files
- [x] Full literal nightly argv (35 cases, real gpt-5-mini, real Postgres) against the rebuilt image →
      `NIGHTLY_EXIT=0`, 35 turns / 0 errors, 35 rows persisted, `/tmp/agent_eval_output.json` 187,046 bytes,
      ~47 min wall clock
- [x] Update Gap 317 in `be_features_tracker.md` (now `[x]`, with the before/after docker evidence and the
      correction to its stale premise), Gap 318's "blocked on" note, and
      `feature_20_23_24_ops_workbook.md` (prerequisite item, Tasks line, new blockers-table row for the
      stale image)

**Final status:** Complete. The gap as filed was half stale — the code defect was already fixed the day
before as **Gap 308** (`default_output_dir()`, commit `ed6f8c1`). What is real is that the image the
nightly job runs (`acrinvoicellmdev2.azurecr.io/invoice-be:latest`, built 2026-08-24T09:08:22Z) predates
that commit and has no `default_output_dir` at all, so the 03:00 UTC job does still fail nightly — the
open item is a **backend image refresh (deploy), not a code fix**, and no `az` command was run here.
Code change this session: one line in `main()` (`Path(args.out).parent.mkdir(parents=True, exist_ok=True)`)
closing the caller-supplied-`--out` half of the same failure class, + 2 tests (9 total), mutation-checked.
`ruff` clean, `pytest tests/test_run_agent_eval_cli.py tests/test_model_substitution.py` → 46 passed.
Everything left uncommitted. Local scratch artifacts (`gap317_repro` Postgres DB, `invoice-be-gap317:*`
images, the temp env file holding real keys) removed after the runs.
