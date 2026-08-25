"""Feature 23's benchmark/eval code and data that ship inside the deployed image.

Everything under `apps/invoice-be/tests/` is excluded from the Docker build
context by `.dockerignore` (`**/tests/`), which is correct for pytest itself but
meant nothing that lives there can be `import`-ed at runtime by a deployed
Container App or Container Apps Job — including `caj-agent-eval-dev`, deleted
2026-08-23 for exactly this reason (`ModuleNotFoundError` on every scheduled
run). This package is the fix: the benchmark/eval *code and data* the nightly
scheduler (`scripts/run_extraction_benchmark.py`, `scripts/run_agent_eval.py`)
needs to import at runtime live here instead, one level up from `tests/`, so
they ship with the image. Genuinely pytest-only content (test functions,
fixtures) stays in `tests/` and imports back from here where it needs the same
data. (`tests/run_agentic_sage_live.py`, the manual CLI harness this note used to
name, was deleted with the orchestrator -- Gap 316.)

See `docs/feature_20_23_24_ops_workbook.md`'s 2026-08-23 section, "The cadence
blocker", for the history.

2026-08-24 (Wave 3): `region_seed_fixtures.py` joins this package for the same
reason. The India/US/EU question banks and their ground truth are prose under
`tests/{india,us,eu}/`, which cannot ship — so the fifteen ported questions'
*data* (27 invoice rows and 6 document chunks) is re-expressed here as Python,
and the `.md` files stay in `tests/` as the human-readable source those rows and
every reference answer are traceable to.
"""
