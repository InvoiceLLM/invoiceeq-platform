# Gap 300 — LLM calls absent from `AppDependencies`

Task: make every real LLM call this app makes produce an Application Insights
`AppDependencies` row, without changing any agent behaviour.

- [x] Read `.claude/CONVENTIONS.md`, the Gap 300 entry, and Gap 301's entry (format to copy).
- [x] Option (a) feasibility — is an OTel OpenAI instrumentation actually available?
      `uv.lock` carries only django/fastapi/flask/logging/psycopg2/requests/urllib/urllib3
      instrumentations (pulled in by `azure-monitor-opentelemetry` 1.8.9). No
      `opentelemetry-instrumentation-openai(-v2)`, no `openinference`, no `traceloop`.
      Option (a) = a **new** undeclared dependency. Rejected (see notes below).
- [x] Option (b) feasibility — does the installed exporter map a hand-made span to a dependency?
      Yes: `azure-monitor-opentelemetry-exporter` **1.0.0b56** (`.venv` and `myenv` agree)
      `export/trace/_exporter.py:369-465` — a `SpanKind.CLIENT` span becomes
      `RemoteDependencyData`, and `gen_ai.system` sets `type = "GenAI | {value}"`
      (`_GEN_AI_ATTRIBUTE_PREFIX`, line 120), taking precedence over HTTP/DB mappings.
      Target comes from `peer.service` (`export/trace/_utils.py:148`).
- [x] Implement in `telemetry.py`: gen-ai span constants, `resolve_gen_ai_system()`,
      `resolve_gen_ai_peer()`, `_start_llm_dependency_span()`, `_end_llm_dependency_span()`,
      wired into `tracked_llm_call()`. Never raises; no call-site changes.
- [x] Tests in `tests/test_telemetry.py` — new Gap 300 section, incl. a test that runs the
      recorded span through the real exporter's `_convert_span_to_envelope` and asserts
      `RemoteDependencyData` / `GenAI | az.ai.openai`.
- [x] Run `pytest tests/test_telemetry.py` (full file) + adjacent LLM-call-site suites.
- [x] Update `feature_20_observability_monitoring_alerts.md` (Gap 300 fix write-up).
- [x] Update `feature_20_23_24_implementation_status.md` (where Gap 300 was first written up).
- [x] Flip Gap 300 to `[x]` in `be_features_tracker.md`, Gap 301's "fixed, not deployed" shape.
- [x] Leave everything uncommitted.

## Notes

Why not option (a): `opentelemetry-instrumentation-openai-v2` would have to be added to
`pyproject.toml`/`uv.lock`, it pins its own `opentelemetry-instrumentation` (currently
0.64b0, owned by the Azure distro), and it only patches the `openai` SDK client — so it
would cover neither the `ollama` provider nor `MockInvoiceLLM`, and it would sit outside
the "never raises" contract every other emitter in `telemetry.py` follows. Option (b)
reuses the wrapper that is already at every LLM call site.

**Final status: done, verified locally, not deployed.** 9 new tests in the Gap 300 section
of `tests/test_telemetry.py`; full `test_telemetry.py` 23 passed; adjacent
`test_query_tools`/`test_agentic_sage`/`test_agent_eval`/`test_ops_digest` 277 passed;
`ruff check` clean. One pre-existing failure in `tests/test_rag.py`
(`test_process_crash_during_agent_leaves_no_orphan_user_message`, a stale call missing
`background_tasks`) confirmed pre-existing by re-running it with `git show
HEAD:telemetry.py` restored in place. `AppDependencies` in `law-invoicellm-dev` stays
empty of GenAI rows until the next backend deploy.
