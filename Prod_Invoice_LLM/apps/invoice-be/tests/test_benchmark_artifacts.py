"""Feature 23 — unit tests for `services/benchmark_artifacts.py`.

Scope note, stated up front the same way `test_azure_cost.py` does: these prove
the *mechanics* — that a Track 1 summary and a Track 2 output payload are mapped
onto their custom events without losing or inventing a field, that a `None`
metric stays absent from the event instead of arriving as a zero, that the blob
key is derived from the run's own timestamp/mode/label, and that every failure
mode (no storage configured, storage raising, the emitter itself raising) leaves
the calling benchmark run untouched. They do **not** prove anything reaches
Azure: no test here opens a socket.

The two payload fixtures are trimmed copies of real output shapes — Track 1's is
`benchmarks.extraction.artifacts.summarise()`'s actual keys (asserted against the
real function in `test_summary_fixture_matches_the_real_summarise_output`), and
Track 2's is `scripts/run_agent_eval.py::summarise()`'s.
"""
import json
import logging
from datetime import datetime, timezone

import pytest

import telemetry
from services import benchmark_artifacts
from services.benchmark_artifacts import (
    RUN_LABEL_NIGHTLY,
    RUN_LABEL_PREDEPLOY,
    TRACK_AGENT_EVAL,
    TRACK_EXTRACTION,
    artifact_blob_name,
    mirror_agent_eval_run,
    mirror_extraction_run,
    upload_artifact,
)

RUN_AT = datetime(2026, 8, 24, 3, 15, 0, tzinfo=timezone.utc)


def _extraction_summary(**overrides):
    """The shape `benchmarks.extraction.artifacts.summarise()` returns, with the
    2026-08-23 live-mode figures the feature doc records (13 seeded cases,
    100% recall, the one known Gap 293 clean-set false positive)."""
    summary = {
        "mode": "verify",
        "clean_documents": 4,
        "seeded_cases": 13,
        "confusion_matrix": {
            "true_positive": 13,
            "false_negative": 0,
            "false_positive": 1,
            "true_negative": 3,
            "not_applicable": 0,
            "recall": 1.0,
            "false_positive_rate": 0.25,
            "document_level_precision": 13 / 14,
        },
        "recall_by_alert_type": {},
        "field_accuracy": {"correct": 81, "total": 81, "ratio": 1.0, "note": ""},
        "false_positive_documents": [
            {"case_id": "outbound_trade_discount__clean", "alerts": ["tax_mismatch"]}
        ],
        "missed_cases": [],
        "collateral_alert_types": ["tax_mismatch"],
        "errors": [],
    }
    summary.update(overrides)
    return summary


def _agent_eval_payload(**overrides):
    """The shape `scripts/run_agent_eval.py` writes to `--out` (the same file the
    CI gate's `jq` reads), trimmed to one path and two turns."""
    payload = {
        "run_at": RUN_AT.isoformat(),
        "paths": ["default"],
        "model_under_test": None,
        "judge_mode": "combined",
        "summary": {
            "default": {
                "turns": 20,
                "llm_calls_total": 44,
                "latency_ms_median": 12345.6,
                "tokens_in_total": 180000,
                "tokens_out_total": 9000,
                "pass_rate": 0.35,
                "faithfulness_mean": 0.806,
                "relevance_mean": 0.95,
                "accuracy_mean": 0.7,
                "context_mean": 0.88,
                "context_scored_turns": 14,
                "orchestration_mean": 0.92,
                "orchestration_scored_turns": 20,
                "persona_mean": 0.75,
                "persona_scored_turns": 3,
                "judge_mode": ["combined"],
                "helpfulness_mean": 0.81,
                "helpfulness_scored_turns": 20,
                "completeness_mean": 0.77,
                "completeness_scored_turns": 20,
                "tone_mean": 0.99,
                "tone_scored_turns": 20,
                "judge_llm_calls_total": 60,
                "errors": 0,
                "cost_per_turn_usd": 0.0044,
            }
        },
        "persisted_rows": 20,
        "turns": [
            {"case_id": "titan_steel_payment_status", "path": "default", "error": None},
            {"case_id": "rajesh_steel_cgst", "path": "default", "error": None},
        ],
    }
    payload.update(overrides)
    return payload


@pytest.fixture(autouse=True)
def _no_real_storage(monkeypatch):
    """Nothing in this file may reach a real storage account.

    `benchmark_artifacts` does `from config import settings`, so patching
    attributes on that singleton is enough — the same approach
    `test_azure_cost.py` uses.
    """
    monkeypatch.setattr(benchmark_artifacts.settings, "AZURE_STORAGE_CONNECTION_STRING", "")
    monkeypatch.setattr(benchmark_artifacts.settings, "AZURE_STORAGE_ACCOUNT", "")
    monkeypatch.setattr(benchmark_artifacts.settings, "BENCHMARK_ARTIFACT_UPLOAD", True)
    monkeypatch.setattr(
        benchmark_artifacts.settings, "BENCHMARK_ARTIFACT_CONTAINER", "benchmark-artifacts"
    )


class _FakeBlobClient:
    def __init__(self, store, container, blob, fail=False):
        self._store = store
        self._container = container
        self._blob = blob
        self._fail = fail

    def upload_blob(self, body, overwrite=False, content_settings=None):
        if self._fail:
            raise RuntimeError("storage unavailable")
        self._store["uploads"].append(
            {
                "container": self._container,
                "blob": self._blob,
                "body": body,
                "overwrite": overwrite,
                "content_type": getattr(content_settings, "content_type", None),
            }
        )


class _FakeContainerClient:
    def __init__(self, store, name, exists=False):
        self._store = store
        self._name = name
        self._exists = exists

    def create_container(self):
        if self._exists:
            raise RuntimeError("ContainerAlreadyExists")
        self._store["created"].append(self._name)


class _FakeBlobService:
    """Stands in for `BlobServiceClient`, recording what it was asked to do."""

    def __init__(self, *, container_exists=False, upload_fails=False):
        self.store = {"uploads": [], "created": []}
        self._container_exists = container_exists
        self._upload_fails = upload_fails

    def get_container_client(self, name):
        return _FakeContainerClient(self.store, name, exists=self._container_exists)

    def get_blob_client(self, container, blob):
        return _FakeBlobClient(self.store, container, blob, fail=self._upload_fails)


def _events(caplog, name):
    return [r for r in caplog.records if r.getMessage() == name]


class _RecordingHandler(logging.Handler):
    """A stand-in for Azure Monitor's `LoggingHandler`, attached the same way.

    Used only by the Gap 309 tests below, and deliberately not `caplog`: every
    other test in this module reaches for `caplog.at_level(logging.INFO)`, which
    raises the level *itself* — that is precisely why a suite of 1400 tests
    never noticed that in a real script process the level was never raised at
    all and every event record was discarded before any handler ran.
    """

    def __init__(self, sink):
        super().__init__()
        self.sink = sink

    def emit(self, record):
        self.sink.append(record)


# ---------------------------------------------------------------------------
# Blob key structure
# ---------------------------------------------------------------------------


def test_blob_name_puts_the_track_first_and_the_timestamp_before_the_mode():
    """A blob listing sorts lexically; this is the ordering a reader wants."""
    assert (
        artifact_blob_name(
            TRACK_EXTRACTION, mode="live", run_label=RUN_LABEL_NIGHTLY, generated_at=RUN_AT
        )
        == "extraction/20260824T031500Z-live-nightly.json"
    )
    assert (
        artifact_blob_name(
            TRACK_AGENT_EVAL, mode="default", run_label=RUN_LABEL_PREDEPLOY, generated_at=RUN_AT
        )
        == "agent-eval/20260824T031500Z-default-predeploy.json"
    )


def test_blob_name_is_always_utc_regardless_of_the_runners_timezone():
    """The event's `generated_at` and this stamp have to name the same instant —
    a job runner in IST and a workbook in UTC must agree on which run is which."""
    from datetime import timedelta

    ist = datetime(2026, 8, 24, 8, 45, 0, tzinfo=timezone(timedelta(hours=5, minutes=30)))
    assert artifact_blob_name(
        TRACK_EXTRACTION, mode="live", run_label=RUN_LABEL_NIGHTLY, generated_at=ist
    ) == artifact_blob_name(
        TRACK_EXTRACTION, mode="live", run_label=RUN_LABEL_NIGHTLY, generated_at=RUN_AT
    )


# ---------------------------------------------------------------------------
# Upload
# ---------------------------------------------------------------------------


def test_upload_writes_json_to_the_dedicated_container_and_creates_it_first(monkeypatch):
    """`benchmark-artifacts` does not exist on the live account (verified
    2026-08-24), so the first real run has to create it or 404."""
    service = _FakeBlobService()
    monkeypatch.setattr(benchmark_artifacts, "_blob_service_client", lambda: service)

    blob_name, error = upload_artifact(
        TRACK_EXTRACTION,
        {"summary": {"mode": "live"}},
        mode="live",
        run_label=RUN_LABEL_NIGHTLY,
        generated_at=RUN_AT,
    )

    assert error is None
    assert blob_name == "extraction/20260824T031500Z-live-nightly.json"
    assert service.store["created"] == ["benchmark-artifacts"]
    upload = service.store["uploads"][0]
    assert upload["container"] == "benchmark-artifacts"
    assert upload["content_type"] == "application/json"
    assert upload["overwrite"] is True
    assert json.loads(upload["body"].decode("utf-8"))["summary"]["mode"] == "live"


def test_an_existing_container_is_not_an_error(monkeypatch):
    service = _FakeBlobService(container_exists=True)
    monkeypatch.setattr(benchmark_artifacts, "_blob_service_client", lambda: service)

    blob_name, error = upload_artifact(
        TRACK_EXTRACTION, {}, mode="verify", run_label=RUN_LABEL_PREDEPLOY, generated_at=RUN_AT
    )
    assert error is None and blob_name and service.store["uploads"]


def test_no_storage_configured_is_a_skip_not_a_failure():
    """The normal local-dev case: nothing configured, so nothing to report."""
    blob_name, error = upload_artifact(
        TRACK_EXTRACTION, {}, mode="verify", run_label=RUN_LABEL_PREDEPLOY, generated_at=RUN_AT
    )
    assert blob_name == "" and error is None


def test_a_placeholder_connection_string_is_treated_as_unconfigured(monkeypatch):
    """`.env.example`'s `your_azure_storage...` value must not be dialled — the
    same guard `services/storage.py` already applies."""
    monkeypatch.setattr(
        benchmark_artifacts.settings,
        "AZURE_STORAGE_CONNECTION_STRING",
        "DefaultEndpointsProtocol=https;AccountName=your_azure_storage_account;",
    )
    assert benchmark_artifacts._connection_string() == ""
    assert benchmark_artifacts._blob_service_client() is None


def test_upload_can_be_switched_off_without_losing_the_event(monkeypatch):
    monkeypatch.setattr(benchmark_artifacts.settings, "BENCHMARK_ARTIFACT_UPLOAD", False)
    exploded = []
    monkeypatch.setattr(
        benchmark_artifacts,
        "_blob_service_client",
        lambda: exploded.append(1),  # pragma: no cover - must not be reached
    )
    blob_name, error = upload_artifact(
        TRACK_EXTRACTION, {}, mode="verify", run_label=RUN_LABEL_NIGHTLY, generated_at=RUN_AT
    )
    assert (blob_name, error, exploded) == ("", None, [])


def test_a_storage_failure_is_reported_not_raised(monkeypatch):
    service = _FakeBlobService(upload_fails=True)
    monkeypatch.setattr(benchmark_artifacts, "_blob_service_client", lambda: service)

    blob_name, error = upload_artifact(
        TRACK_EXTRACTION, {}, mode="live", run_label=RUN_LABEL_NIGHTLY, generated_at=RUN_AT
    )
    assert blob_name == ""
    assert "storage unavailable" in error


# ---------------------------------------------------------------------------
# Track 1 — the extraction_benchmark_run event
# ---------------------------------------------------------------------------


def test_track_1_event_carries_all_five_counts_and_all_three_derived_metrics(caplog):
    with caplog.at_level(logging.INFO):
        result = mirror_extraction_run(
            _extraction_summary(), {"clean_runs": []}, run_label=RUN_LABEL_NIGHTLY
        )

    assert result.events == 1
    record = _events(caplog, telemetry.EXTRACTION_BENCHMARK_EVENT_NAME)[0]
    # The attribute the Azure Monitor exporter branches on to route this to
    # customEvents rather than traces.
    assert (
        getattr(record, "microsoft.custom_event.name")
        == telemetry.EXTRACTION_BENCHMARK_EVENT_NAME
    )
    # The five raw cells...
    assert (record.true_positive, record.false_negative) == (13, 0)
    assert (record.false_positive, record.true_negative) == (1, 3)
    assert record.not_applicable == 0
    # ...and the three derived figures, as percentages.
    assert record.alert_recall_pct == 100.0
    assert record.clean_false_positive_rate_pct == 25.0
    assert record.document_level_precision_pct == pytest.approx(92.8571, abs=1e-3)
    assert record.field_accuracy_pct == 100.0
    assert record.run_label == "nightly"
    assert record.mode == "verify"
    assert record.generated_at


def test_track_1_event_distinguishes_a_nightly_run_from_a_predeploy_one(caplog):
    with caplog.at_level(logging.INFO):
        mirror_extraction_run(_extraction_summary(mode="live"), run_label=RUN_LABEL_NIGHTLY)
        mirror_extraction_run(_extraction_summary(), run_label=RUN_LABEL_PREDEPLOY)

    records = _events(caplog, telemetry.EXTRACTION_BENCHMARK_EVENT_NAME)
    assert [(r.run_label, r.mode) for r in records] == [
        ("nightly", "live"),
        ("predeploy", "verify"),
    ]


def test_track_1_absent_metrics_stay_absent_rather_than_arriving_as_zero(caplog):
    """A `--cases`-filtered run with no clean documents has no false-positive
    rate at all. A 0.0 there would render as "perfect, zero false positives" on
    a panel with nothing behind it."""
    summary = _extraction_summary()
    summary["confusion_matrix"].update(
        {
            "false_positive": 0,
            "true_negative": 0,
            "false_positive_rate": None,
            "recall": None,
        }
    )
    summary["clean_documents"] = 0
    with caplog.at_level(logging.INFO):
        mirror_extraction_run(summary)

    record = _events(caplog, telemetry.EXTRACTION_BENCHMARK_EVENT_NAME)[0]
    assert not hasattr(record, "clean_false_positive_rate_pct")
    assert not hasattr(record, "alert_recall_pct")
    # The raw counts are still there, which is how a reader tells "nothing was
    # measured" from "measured and clean".
    assert record.false_positive == 0 and record.true_negative == 0


def test_track_1_gate_verdict_is_a_number_kql_can_average(caplog):
    with caplog.at_level(logging.INFO):
        mirror_extraction_run(_extraction_summary())  # has a false-positive document
        mirror_extraction_run(
            _extraction_summary(false_positive_documents=[], collateral_alert_types=[])
        )

    records = _events(caplog, telemetry.EXTRACTION_BENCHMARK_EVENT_NAME)
    assert [r.gate_failed for r in records] == [1, 0]


def test_track_1_event_carries_the_blob_it_was_uploaded_to(monkeypatch, caplog):
    """The join: a workbook row names the blob holding the per-case detail."""
    service = _FakeBlobService()
    monkeypatch.setattr(benchmark_artifacts, "_blob_service_client", lambda: service)

    with caplog.at_level(logging.INFO):
        result = mirror_extraction_run(
            _extraction_summary(),
            {"clean_runs": [{"case_id": "x"}]},
            run_label=RUN_LABEL_NIGHTLY,
            generated_at=RUN_AT,
        )

    record = _events(caplog, telemetry.EXTRACTION_BENCHMARK_EVENT_NAME)[0]
    assert record.artifact_blob == "extraction/20260824T031500Z-verify-nightly.json"
    assert result.artifact_blob == record.artifact_blob
    # And the blob really holds the per-case detail, not just the summary.
    body = json.loads(service.store["uploads"][0]["body"].decode("utf-8"))
    assert body["detail"]["clean_runs"] == [{"case_id": "x"}]
    assert body["run_label"] == "nightly"


def test_track_1_event_has_no_blob_field_when_the_upload_failed(monkeypatch, caplog):
    """Never a fabricated path: a link that is present is a link that resolves."""
    monkeypatch.setattr(
        benchmark_artifacts, "_blob_service_client", lambda: _FakeBlobService(upload_fails=True)
    )
    with caplog.at_level(logging.INFO):
        result = mirror_extraction_run(_extraction_summary())

    record = _events(caplog, telemetry.EXTRACTION_BENCHMARK_EVENT_NAME)[0]
    assert not hasattr(record, "artifact_blob")
    # ...but the run still emitted its numbers, and says what went wrong.
    assert result.events == 1 and result.errors and "storage unavailable" in result.errors[0]


# ---------------------------------------------------------------------------
# Track 2 — the agent_eval_summary event
# ---------------------------------------------------------------------------


def test_track_2_event_carries_every_scored_dimension_with_its_denominators(caplog):
    """Every dimension the run actually *scored* reaches the event.

    Iterated over the payload's own keys rather than over the whole of
    `EVAL_SCORE_DIMENSIONS` since Gap 307 (2026-08-26): `context_drift` is
    scored only in the multi-turn bucket, so it is legitimately absent from a
    `default`-bucket event and asserting otherwise would demand a 0.0 for a
    dimension that was never measured. The "nothing silently dropped" guard the
    original name promised is still here — it is just anchored to what was
    scored, and the drift half of it is the test below.
    """
    payload = _agent_eval_payload()
    with caplog.at_level(logging.INFO):
        result = mirror_agent_eval_run(payload, run_label=RUN_LABEL_NIGHTLY)

    assert result.events == 1
    record = _events(caplog, telemetry.AGENT_EVAL_SUMMARY_EVENT_NAME)[0]
    scored = [
        dimension
        for dimension in telemetry.EVAL_SCORE_DIMENSIONS
        if payload["summary"]["default"].get(f"{dimension}_mean") is not None
    ]
    assert len(scored) == len(telemetry.EVAL_SCORE_DIMENSIONS) - 1
    assert "context_drift" not in scored
    for dimension in scored:
        assert hasattr(record, f"{dimension}_mean"), dimension
    assert not hasattr(record, "context_drift_mean")
    assert record.faithfulness_mean == 0.806
    assert record.tone_mean == 0.99
    # `persona_score` is NULL on most turns by design — its mean is over 3 of
    # 20 turns, and the event has to say so or the number is unreadable.
    assert record.persona_scored_turns == 3
    assert record.orchestration_scored_turns == 20
    assert record.pass_rate == 0.35
    assert record.turns == 20
    assert record.errors == 0
    assert record.judge_mode == "combined"
    assert record.judge_llm_calls_total == 60
    assert record.cost_per_turn_usd == 0.0044
    assert record.run_label == "nightly"


def test_track_2_soft_metrics_are_absent_on_a_separate_judge_run(caplog):
    """A `separate` run does not score helpfulness/completeness/tone at all. A
    0.0 would read as "maximally unhelpful every night" on the trend panel."""
    payload = _agent_eval_payload(judge_mode="separate")
    stats = payload["summary"]["default"]
    stats["judge_mode"] = ["separate"]
    for dimension in ("helpfulness", "completeness", "tone"):
        stats[f"{dimension}_mean"] = None
        stats[f"{dimension}_scored_turns"] = 0

    with caplog.at_level(logging.INFO):
        mirror_agent_eval_run(payload)

    record = _events(caplog, telemetry.AGENT_EVAL_SUMMARY_EVENT_NAME)[0]
    assert record.judge_mode == "separate"
    for dimension in ("helpfulness", "completeness", "tone"):
        assert not hasattr(record, f"{dimension}_mean")
    # The six the separate judge does score are still all there.
    for dimension in ("faithfulness", "relevance", "accuracy", "context", "orchestration", "persona"):
        assert hasattr(record, f"{dimension}_mean")


def test_the_multi_turn_bucket_is_mirrored_as_its_own_event_carrying_drift(caplog):
    """Gap 307. The tier rides the existing per-path mechanism — a second
    `agent_eval_summary` event with `path="default-multiturn"`, not a new event
    type — and `context_drift_mean` appears there and only there."""
    payload = _agent_eval_payload()
    payload["summary"][benchmark_artifacts.MULTI_TURN_PATH] = {
        "turns": 12,
        "errors": 0,
        "pass_rate": 0.75,
        "faithfulness_mean": 0.88,
        "judge_mode": ["combined"],
        "context_drift_mean": 0.93,
        "context_drift_scored_turns": 7,
    }

    with caplog.at_level(logging.INFO):
        result = mirror_agent_eval_run(payload)

    records = {r.path: r for r in _events(caplog, telemetry.AGENT_EVAL_SUMMARY_EVENT_NAME)}
    assert result.events == 2
    drift_event = records[benchmark_artifacts.MULTI_TURN_PATH]
    assert drift_event.context_drift_mean == 0.93
    assert drift_event.context_drift_scored_turns == 7
    assert drift_event.turns == 12
    # And the baseline event is unchanged by the tier's existence.
    assert not hasattr(records["default"], "context_drift_mean")
    assert records["default"].turns == 20


def test_track_2_emits_one_event_per_path_not_one_per_run(caplog):
    """Averaging `default` and `sage` together would describe neither."""
    payload = _agent_eval_payload(paths=["default", "sage"])
    sage = dict(payload["summary"]["default"])
    sage.update({"faithfulness_mean": 0.62, "turns": 20})
    payload["summary"]["sage"] = sage

    with caplog.at_level(logging.INFO):
        result = mirror_agent_eval_run(payload)

    records = _events(caplog, telemetry.AGENT_EVAL_SUMMARY_EVENT_NAME)
    assert result.events == 2
    assert {(r.path, r.faithfulness_mean) for r in records} == {
        ("default", 0.806),
        ("sage", 0.62),
    }


def test_track_2_case_count_is_cases_not_turns(caplog):
    """A 5-case gate run over two paths is 10 turns; "how much of the corpus did
    this cover" is the question a reader comparing the two cadences is asking."""
    with caplog.at_level(logging.INFO):
        mirror_agent_eval_run(_agent_eval_payload(), run_label=RUN_LABEL_PREDEPLOY)

    record = _events(caplog, telemetry.AGENT_EVAL_SUMMARY_EVENT_NAME)[0]
    assert record.cases == 2  # the fixture's two distinct case_ids
    assert record.run_label == "predeploy"


def test_track_2_a_candidate_run_names_the_model_it_measured(caplog):
    with caplog.at_level(logging.INFO):
        mirror_agent_eval_run(_agent_eval_payload(model_under_test="azure:gpt-4o"))
    record = _events(caplog, telemetry.AGENT_EVAL_SUMMARY_EVENT_NAME)[0]
    assert record.model_under_test == "azure:gpt-4o"


def test_track_2_a_baseline_run_does_not_pretend_to_name_a_model(caplog):
    """`model_under_test: None` means "the application's own configured model",
    and is never rendered as the string "default"."""
    with caplog.at_level(logging.INFO):
        mirror_agent_eval_run(_agent_eval_payload())
    record = _events(caplog, telemetry.AGENT_EVAL_SUMMARY_EVENT_NAME)[0]
    assert not hasattr(record, "model_under_test")


def test_track_2_uploads_the_whole_per_turn_payload_not_the_summary(monkeypatch):
    """The blob has to answer what the event cannot — which answer the model
    actually gave, and what the judge objected to."""
    service = _FakeBlobService()
    monkeypatch.setattr(benchmark_artifacts, "_blob_service_client", lambda: service)

    result = mirror_agent_eval_run(
        _agent_eval_payload(), run_label=RUN_LABEL_PREDEPLOY, generated_at=RUN_AT
    )
    assert result.artifact_blob == "agent-eval/20260824T031500Z-default-predeploy.json"
    body = json.loads(service.store["uploads"][0]["body"].decode("utf-8"))
    assert [t["case_id"] for t in body["turns"]] == [
        "titan_steel_payment_status",
        "rajesh_steel_cgst",
    ]


def test_track_2_multi_path_run_names_both_paths_in_the_blob(monkeypatch):
    service = _FakeBlobService()
    monkeypatch.setattr(benchmark_artifacts, "_blob_service_client", lambda: service)
    payload = _agent_eval_payload()
    payload["summary"]["sage"] = dict(payload["summary"]["default"])

    result = mirror_agent_eval_run(payload, run_label=RUN_LABEL_NIGHTLY, generated_at=RUN_AT)
    assert result.artifact_blob == "agent-eval/20260824T031500Z-default-sage-nightly.json"


# ---------------------------------------------------------------------------
# Non-fatality — the whole contract of this module
# ---------------------------------------------------------------------------


def test_a_broken_telemetry_emitter_cannot_break_a_benchmark_run(monkeypatch):
    def _explode(*args, **kwargs):
        raise RuntimeError("exporter down")

    monkeypatch.setattr(telemetry, "_emit_event", _explode)
    # Must not raise: a gate that blocked a deploy because the exporter was down
    # would be instrumentation breaking the thing it instruments.
    telemetry.track_extraction_benchmark_run(
        run_label="nightly",
        mode="live",
        clean_documents=4,
        seeded_cases=13,
        true_positive=13,
        false_negative=0,
        false_positive=1,
        true_negative=3,
        not_applicable=0,
    )
    telemetry.track_agent_eval_summary(
        run_label="nightly", path="default", judge_mode="separate", turns=20
    )
    assert mirror_extraction_run(_extraction_summary()).events == 1
    assert mirror_agent_eval_run(_agent_eval_payload()).events == 1


def test_a_malformed_summary_does_not_raise(caplog):
    """A `--no-score` run has no scores and an errored run may have no matrix."""
    with caplog.at_level(logging.INFO):
        assert mirror_extraction_run({}).events == 1
        assert mirror_agent_eval_run({}).events == 0
    record = _events(caplog, telemetry.EXTRACTION_BENCHMARK_EVENT_NAME)[0]
    assert record.mode == "unknown" and record.true_positive == 0


def test_a_blob_client_that_raises_on_construction_is_survivable(monkeypatch):
    def _explode():
        raise RuntimeError("bad connection string")

    monkeypatch.setattr(benchmark_artifacts, "_blob_service_client", _explode)
    result = mirror_extraction_run(_extraction_summary())
    assert result.events == 1 and result.artifact_blob == ""
    assert "bad connection string" in result.errors[0]


def test_describe_reports_honestly_rather_than_reassuringly():
    result = benchmark_artifacts.MirrorResult(events=1, errors=["artifact upload failed (x)"])
    described = result.describe()
    assert "1 telemetry event(s)" in described
    assert "no artifact" in described
    assert "artifact upload failed" in described


# ---------------------------------------------------------------------------
# Gap 304 half (1) — the exporter attaches early, and attaches narrowly
# ---------------------------------------------------------------------------
#
# `configure_run_telemetry()` used to be called immediately before the mirror,
# deliberately, so an eval run's own per-call events could never reach
# `customEvents`. With `run_source` on every event and every GenAI span they can
# be exported and told apart, so both scripts now call it right after
# `configure_run_source()` — before the first graded turn.
#
# That makes two properties load-bearing that were not before: the call has to be
# idempotent (the mirror still calls it, and `configure_azure_monitor()` attaches
# a *second* handler if called twice — every event would then export twice and
# double this run's own cost figures), and it has to switch off the
# auto-instrumentations, because an eval run is DB-heavy per graded turn and the
# nightly job's replica timeout is 5400s.


@pytest.fixture
def fresh_exporter_state(monkeypatch):
    """Undo the module-level attach decision for one test.

    `_exporter_attached` is cached for the life of the process by design, so
    without this the first test to touch it would fix the answer for every test
    after it — the same in-process leak `run_source_ctx` hit in
    `tests/test_telemetry.py`.
    """
    monkeypatch.setattr(benchmark_artifacts, "_exporter_attached", None)


@pytest.fixture
def fake_configure_azure_monitor(monkeypatch):
    """Record the kwargs the distro would really be called with.

    Patched on the installed `azure.monitor.opentelemetry` module rather than
    faked in `sys.modules`: `configure_run_telemetry()` does the import inside
    the function, so this is the object it genuinely resolves.
    """
    import azure.monitor.opentelemetry as azure_monitor

    calls = []
    monkeypatch.setattr(
        azure_monitor, "configure_azure_monitor", lambda **kwargs: calls.append(kwargs)
    )
    monkeypatch.setenv("APPLICATIONINSIGHTS_CONNECTION_STRING", "InstrumentationKey=fake")
    return calls


def test_the_exporter_is_configured_without_the_instrumentations_an_eval_run_does_not_need(
    fresh_exporter_state, fake_configure_azure_monitor
):
    """Only the GenAI CLIENT spans and the custom events should flow. A graded
    turn executes real SQL, so leaving `psycopg2` on would fill `AppDependencies`
    with rows that say nothing about LLM cost or latency — the thing this export
    exists to make visible."""
    assert benchmark_artifacts.configure_run_telemetry() is True

    kwargs = fake_configure_azure_monitor[0]
    assert kwargs["connection_string"] == "InstrumentationKey=fake"
    assert kwargs["logger_name"] == "invoice_be_telemetry"
    assert kwargs["instrumentation_options"] == {
        "azure_sdk": {"enabled": False},
        "psycopg2": {"enabled": False},
        "requests": {"enabled": False},
        "urllib": {"enabled": False},
        "urllib3": {"enabled": False},
    }
    # A batch job has no live-metrics viewer, and performance counters describe a
    # replica that exists for the length of one run.
    assert kwargs["enable_live_metrics"] is False
    assert kwargs["enable_performance_counters"] is False


def test_every_disabled_instrumentation_is_a_name_the_distro_actually_knows():
    """A typo here would be silently ignored — the distro matches on its own
    library names and does nothing with an unknown key, so the instrumentation
    would stay on and nobody would find out until an ingestion bill. Pinned
    against the installed package's own tuple rather than a copy of it."""
    from azure.monitor.opentelemetry._constants import (
        _ALL_SUPPORTED_INSTRUMENTED_LIBRARIES,
    )

    assert set(benchmark_artifacts._BENCHMARK_INSTRUMENTATION_OPTIONS).issubset(
        set(_ALL_SUPPORTED_INSTRUMENTED_LIBRARIES)
    )
    # Nothing web-framework-shaped is switched off: none of django/fastapi/flask
    # is running in a `python scripts/...` process to begin with.
    assert not {"django", "fastapi", "flask"} & set(
        benchmark_artifacts._BENCHMARK_INSTRUMENTATION_OPTIONS
    )


def test_a_second_call_does_not_attach_a_second_exporter(
    fresh_exporter_state, fake_configure_azure_monitor
):
    """The mirror block still calls this at the end of a run. Attaching twice
    would put a second handler on `invoice_be_telemetry` and export every event
    twice — i.e. silently double the run's own cost and latency figures."""
    assert benchmark_artifacts.configure_run_telemetry() is True
    assert benchmark_artifacts.configure_run_telemetry() is True

    assert len(fake_configure_azure_monitor) == 1


def test_no_connection_string_is_a_stdout_only_run_and_is_remembered(
    fresh_exporter_state, monkeypatch
):
    """The local/CI case. The negative answer is cached too, so a second call
    cannot start dialling because an env var appeared mid-run."""
    monkeypatch.delenv("APPLICATIONINSIGHTS_CONNECTION_STRING", raising=False)
    assert benchmark_artifacts.configure_run_telemetry() is False

    monkeypatch.setenv("APPLICATIONINSIGHTS_CONNECTION_STRING", "InstrumentationKey=fake")
    import azure.monitor.opentelemetry as azure_monitor

    def _explode(**_kwargs):  # pragma: no cover - must not be reached
        raise AssertionError("the cached decision was re-evaluated")

    monkeypatch.setattr(azure_monitor, "configure_azure_monitor", _explode)
    assert benchmark_artifacts.configure_run_telemetry() is False


def test_an_exporter_that_cannot_be_configured_does_not_fail_the_run(
    fresh_exporter_state, monkeypatch
):
    """Same contract as the rest of this module: a benchmark gate must not block
    a deploy because Application Insights had a bad minute."""
    import azure.monitor.opentelemetry as azure_monitor

    def _explode(**_kwargs):
        raise RuntimeError("exporter unavailable")

    monkeypatch.setenv("APPLICATIONINSIGHTS_CONNECTION_STRING", "InstrumentationKey=fake")
    monkeypatch.setattr(azure_monitor, "configure_azure_monitor", _explode)

    assert benchmark_artifacts.configure_run_telemetry() is False


# ---------------------------------------------------------------------------
# Gap 309 — attaching the exporter is necessary and, on its own, not sufficient
# ---------------------------------------------------------------------------


@pytest.fixture
def event_loggers_at_warning():
    """Both event loggers as a fresh `python scripts/...` process finds them.

    `configure_azure_monitor()` adds a handler and never sets a level, so the
    logger sits at `NOTSET` and inherits root's `WARNING`. Restored afterwards
    because `_enable_event_logger_level()` deliberately does not restore it —
    a real run wants the level to stay up for the rest of the process.
    """
    loggers = [logging.getLogger(name) for name in telemetry._EVENT_LOGGER_NAMES]
    previous = [lg.level for lg in loggers]
    root = logging.getLogger()
    previous_root = root.level
    for lg in loggers:
        lg.setLevel(logging.NOTSET)
    root.setLevel(logging.WARNING)
    yield loggers
    for lg, level in zip(loggers, previous):
        lg.setLevel(level)
    root.setLevel(previous_root)


def test_an_info_event_is_dropped_before_any_handler_at_the_default_level(
    event_loggers_at_warning,
):
    """The premise, pinned so the fix below is not testing itself.

    This is the whole of Gap 309: `telemetry._emit_event()` logs at INFO, and in
    a bare script process `Logger.isEnabledFor(INFO)` is False — the record never
    reaches a handler, so it does not matter how correctly Azure Monitor was
    configured. Found live 2026-08-24 when `extraction_benchmark_run` was absent
    from `customEvents` after a run whose own stdout said it had been mirrored.
    """
    event_logger = event_loggers_at_warning[0]
    seen = []
    event_logger.addHandler(_RecordingHandler(seen))
    try:
        assert event_logger.isEnabledFor(logging.INFO) is False
        telemetry._emit_event("extraction_benchmark_run", {"run_label": "nightly"})
        assert seen == []
    finally:
        event_logger.handlers = [
            h for h in event_logger.handlers if not isinstance(h, _RecordingHandler)
        ]


def test_configuring_run_telemetry_raises_both_event_loggers_to_info(
    fresh_exporter_state, event_loggers_at_warning, fake_configure_azure_monitor
):
    """...and the fix: the one function both benchmark scripts call to make
    telemetry work in a standalone process now lifts the level too, so the
    handler it attaches actually receives something."""
    assert benchmark_artifacts.configure_run_telemetry() is True

    for event_logger in event_loggers_at_warning:
        assert event_logger.isEnabledFor(logging.INFO) is True


def test_the_level_is_raised_even_when_there_is_no_exporter_to_attach(
    fresh_exporter_state, event_loggers_at_warning, monkeypatch
):
    """A stdout-only run still has to emit. Without this, a local/CI run would
    not even produce the structured console line this module's docstring
    promises it falls back to."""
    monkeypatch.delenv("APPLICATIONINSIGHTS_CONNECTION_STRING", raising=False)

    assert benchmark_artifacts.configure_run_telemetry() is False

    for event_logger in event_loggers_at_warning:
        assert event_logger.isEnabledFor(logging.INFO) is True


def test_a_level_the_caller_set_lower_than_info_is_left_alone(
    fresh_exporter_state, event_loggers_at_warning, monkeypatch
):
    """A debugging run at DEBUG must not be quietly turned down to INFO."""
    monkeypatch.delenv("APPLICATIONINSIGHTS_CONNECTION_STRING", raising=False)
    event_loggers_at_warning[0].setLevel(logging.DEBUG)

    benchmark_artifacts.configure_run_telemetry()

    assert event_loggers_at_warning[0].level == logging.DEBUG


def test_configure_run_source_still_runs_before_anything_can_be_exported(
    fresh_exporter_state, fake_configure_azure_monitor, monkeypatch
):
    """Order is the whole safety argument: the tag is set first, the exporter
    second, so no event can leave the process untagged. Asserted on the two
    functions' real side effects rather than by reading the scripts."""
    order = []
    real_set_run_source = telemetry.set_run_source

    def _recording_set_run_source(value):
        order.append(("tag", value))
        return real_set_run_source(value)

    monkeypatch.setattr(telemetry, "set_run_source", _recording_set_run_source)

    # Reset afterwards: this suite runs with `pytest-randomly`, and a contextvar
    # left set here would leak `golden` into whatever test runs next in the same
    # thread — the exact intermittent failure `tests/test_telemetry.py` records.
    token = telemetry.run_source_ctx.set(telemetry.RUN_SOURCE_PRODUCTION)
    try:
        # Exactly the two lines both scripts now run, in that order.
        benchmark_artifacts.configure_run_source(RUN_LABEL_NIGHTLY)
        order.append(("exporter", benchmark_artifacts.configure_run_telemetry()))

        assert order == [("tag", "golden"), ("exporter", True)]
        assert telemetry.run_source_ctx.get() == "golden"
    finally:
        telemetry.run_source_ctx.reset(token)


# ---------------------------------------------------------------------------
# The fixtures above are claims about other modules' output — pin them
# ---------------------------------------------------------------------------


def test_summary_fixture_matches_the_real_summarise_output():
    """Guards the mapping in `mirror_extraction_run()` against a rename in
    `benchmarks/extraction/artifacts.py` — the failure mode otherwise is an
    event that silently reports 0 for a real measurement."""
    from benchmarks.extraction.artifacts import summarise
    from benchmarks.extraction.harness import BenchmarkResult

    real = summarise(BenchmarkResult(mode="verify"))
    assert set(_extraction_summary()) == set(real)
    assert set(_extraction_summary()["confusion_matrix"]) == set(real["confusion_matrix"])
    assert set(_extraction_summary()["field_accuracy"]) == set(real["field_accuracy"])


def test_every_eval_scores_dimension_is_mirrored():
    """`EVAL_SCORE_DIMENSIONS` must stay in step with `EvalScores` — a dimension
    added to the dataclass and not here would be scored and then silently
    dropped from the trend."""
    from dataclasses import fields

    from services.agent_eval import EvalScores

    scored = {
        f.name[: -len("_score")] for f in fields(EvalScores) if f.name.endswith("_score")
    }
    assert scored == set(telemetry.EVAL_SCORE_DIMENSIONS)


def test_run_agent_eval_summarise_emits_the_keys_this_module_reads():
    """Same guard on the other side: the `<dimension>_mean` /
    `<dimension>_scored_turns` names are `run_agent_eval.summarise()`'s, not
    this module's invention."""
    import sys
    from pathlib import Path

    scripts_dir = str(Path(__file__).resolve().parent.parent / "scripts")
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)
    from scripts.run_agent_eval import summarise as summarise_turns

    produced = summarise_turns(
        [
            {
                "path": "default",
                "llm_call_count": 2,
                "latency_ms": 100.0,
                "faithfulness_score": 0.5,
                "persona_score": 0.5,
                "tone_score": 0.5,
                "judge_mode": "combined",
            }
        ]
    )["default"]
    assert "faithfulness_mean" in produced
    assert "persona_scored_turns" in produced
    assert "tone_scored_turns" in produced
    assert set(produced) >= {"turns", "errors", "pass_rate", "judge_llm_calls_total"}
