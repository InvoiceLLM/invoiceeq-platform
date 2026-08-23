# Verify nightly + pre-deploy-gate scheduler inside a real built container

Scope: verify (not deploy) the Feature 23 nightly eval / pre-deploy CI gate actually
works inside a built `invoice-be` Docker image, now that the disk-space crisis is
resolved. No deploy, no commit/push, no bicep apply, no workflow edit.

- [x] Read CONVENTIONS.md, deploy-dev.yml, feature_20_23_24_implementation_status.md
- [x] Confirm Dockerfile path (`Prod_Invoice_LLM/docker/Dockerfile.be`, build context = `Prod_Invoice_LLM/`)
- [x] Confirm `.dockerignore` excludes `**/tests/` but not `benchmarks/`
- [x] Confirm benchmark PDF fixture cache hashes match committed files (large_43f6e0e42c98.pdf, small_bdd59cfd3deb.pdf)
- [x] Confirm `pymupdf` is a real dep, `reportlab` is dev-only, matches documented design
- [x] Build image: `docker build -f docker/Dockerfile.be -t invoice-be-verify:nightly .` from `Prod_Invoice_LLM/` — succeeded, exit 0, image 3.12GB
- [x] Confirm `tests/` absent, `benchmarks/` present + importable inside built image — confirmed via `find /app -maxdepth 1` and `python -c "import benchmarks"`
- [x] Run Track 1 (`run_extraction_benchmark.py --mode verify --no-write --tolerate-fp outbound_trade_discount__clean`) inside container — exit 0, 13/13 alert recall, 1 tolerated FP, matches documented result exactly
- [x] Run Track 2 5-case smoke subset (`run_agent_eval.py --paths default --no-persist --cases ...`) inside container with real dev Azure OpenAI creds (local .env, not committed) — exit 0, 5 turns, 0 errors, jq gate logic reproduced exactly against the real output JSON, confirms gate would pass
- [x] Report real output, pass/fail, ready-to-deploy verdict — reported in chat, verdict: ready to deploy
