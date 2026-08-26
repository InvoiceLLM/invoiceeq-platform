"""`scripts/run_agent_eval.py`'s CLI — specifically where a run writes.

Gap 308, found live 2026-08-24 by deploying and running `caj-benchmark-eval-dev`
rather than by reading the script. The job's persisted nightly args are
``python scripts/run_agent_eval.py --paths default --run-label nightly`` — no
``--out`` — and the default landed in ``tests/agent_eval_output.json``, a
directory `Prod_Invoice_LLM/.dockerignore` strips from the backend image
(``**/tests/``). Execution `caj-benchmark-eval-dev-d0gm1bo` therefore did every
piece of real work correctly (Track 1 recall 1.0, Track 2's 20 `agent_eval_run`
rows committed to Postgres, the `agent_eval_summary` mirror emitted) and then
died on the final write with ``FileNotFoundError: '/app/tests/
agent_eval_output.json'``. With `retryLimit 0` Container Apps records that as a
`Failed` execution, so a job whose results were entirely correct reported red
every night — which is worse than a plain crash, because it makes the execution
status useless as a monitoring signal.

These tests pin the fix from both ends: the premise (the two bicep files really
do rely on the default, so the default is what has to be safe) and the behaviour
(`main()` completes and writes its payload when `tests/` is absent, exactly as
in the image).

Gap 317 (2026-08-25) re-ran that repro against a real `docker build -f
docker/Dockerfile.be` of the current tree — before: `FileNotFoundError` on
`/app/tests/agent_eval_output.json`, exit 1, after every graded turn and one
committed row; after: exit 0, `/tmp/agent_eval_output.json`, and the full 35-case
nightly argv completing with 35 persisted rows — and closed the half Gap 308 left
open: a caller-supplied `--out` naming a directory that only exists in a checkout
could still crash in exactly the same place, which is what "just add `--out` to
the two bicep files" would have reintroduced. The last two tests here cover that,
including the point that the container default must be safe because the temp
directory already exists, not because `mkdir` hides it.

`main()` is driven with the literal nightly argv. The case list is emptied
instead of shortened so no LLM is called and no turn runs — the defect is in the
write at the end of `main()`, which is reached identically either way — and the
two out-of-process side effects (`persist`, the telemetry/blob mirror) are
stubbed rather than switched off with flags, so the argv under test stays
byte-for-byte the one Azure runs.
"""
from __future__ import annotations

import json
import logging
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock

import pytest

os.environ.setdefault("MOCK_EMBEDDINGS", "true")

_BE_ROOT = Path(__file__).resolve().parent.parent
if str(_BE_ROOT) not in sys.path:
    sys.path.insert(0, str(_BE_ROOT))
_SCRIPTS_DIR = str(_BE_ROOT / "scripts")
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)

import telemetry  # noqa: E402
import scripts.run_agent_eval as script  # noqa: E402
from scripts.run_agent_eval import (  # noqa: E402
    OUTPUT_NAME,
    default_output_dir,
    default_output_path,
)
from services import ops_recommendation as rec  # noqa: E402
from services.benchmark_artifacts import MirrorResult  # noqa: E402

#: The exact args string both `infra/08-apps.bicep` (module `benchmarkEvalJob`)
#: and `infra/benchmark-eval-job-only.bicep` persist on the job. Kept as one
#: literal so the premise test below reads the real files rather than trusting
#: this copy.
_NIGHTLY_ARGV = ["--paths", "default", "--run-label", "nightly"]

_INFRA_ROOT = _BE_ROOT.parents[1] / "infra"
_BICEP_FILES = (
    _INFRA_ROOT / "08-apps.bicep",
    _INFRA_ROOT / "benchmark-eval-job-only.bicep",
)


@pytest.fixture
def clean_run_source():
    """Undo `configure_run_source()`'s contextvar write.

    The suite runs under `pytest-randomly`; a `golden` tag left set here would
    leak into whatever test runs next in the same thread — the intermittent
    failure `tests/test_telemetry.py` already records.
    """
    token = telemetry.run_source_ctx.set(telemetry.RUN_SOURCE_PRODUCTION)
    yield
    telemetry.run_source_ctx.reset(token)


def _run_nightly_main(
    monkeypatch,
    extra_argv=(),
    recommendation_pass=None,
    track1_handoff=None,
    exporter_attached=False,
):
    """The real `main()` on the real nightly argv, with no turns and no I/O."""
    _run_main(
        monkeypatch,
        [*_NIGHTLY_ARGV, *extra_argv],
        recommendation_pass=recommendation_pass,
        track1_handoff=track1_handoff,
        exporter_attached=exporter_attached,
    )


def _run_main(
    monkeypatch, argv, recommendation_pass=None, track1_handoff=None, exporter_attached=False
):
    """`main()` with a caller-chosen argv, no turns, no out-of-process I/O.

    The recommendation pass (Gap 318) is stubbed here rather than left live for
    the same reason `persist` and the mirror are: it makes two ARM calls. The
    tests that care whether it *fires* pass their own `recommendation_pass`.

    Its telemetry mirror (Gap 319) is **not** stubbed — it emits log records and
    makes no network call of its own, so leaving it live is what lets the tests
    below assert on the events a nightly run really produces.
    """
    monkeypatch.setattr(script, "CASES", [])
    monkeypatch.setattr(script, "persist", lambda *a, **k: 0)
    monkeypatch.setattr(script, "configure_run_telemetry", lambda: exporter_attached)
    monkeypatch.setattr(script, "mirror_agent_eval_run", lambda *a, **k: MirrorResult())
    monkeypatch.setattr(
        script,
        "run_recommendation_pass",
        recommendation_pass or (lambda *a, **k: _StubPass()),
    )
    monkeypatch.setattr(script, "read_track1_handoff", lambda **k: track1_handoff)
    monkeypatch.setattr(sys, "argv", ["run_agent_eval.py", *argv])
    script.main()


class _StubPass:
    """What `recommendation_pass_step()` reads: the two attributes it prints
    from, plus the two the Gap 319 mirror stamps onto every event."""

    categories: list = []
    run_label = "nightly"
    generated_at = datetime(2026, 8, 25, 3, 47, tzinfo=timezone.utc)

    def describe(self):
        return "  [worked] stub"


# ---------------------------------------------------------------------------
# The premise: the nightly args really do rely on the default
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("bicep", _BICEP_FILES, ids=lambda p: p.name)
def test_the_persisted_nightly_args_pass_no_out_override(bicep):
    """If either bicep file ever gains an explicit `--out`, this test's whole
    reason to exist changes — so it fails loudly rather than passing on a
    premise that is no longer true."""
    # The `args:` entry, not the several comment lines that also name the
    # script: bicep comments start `//` once stripped of indentation.
    args_lines = [
        line.strip()
        for line in bicep.read_text(encoding="utf-8").splitlines()
        if "python scripts/run_agent_eval.py" in line and not line.strip().startswith("//")
    ]
    assert len(args_lines) == 1, args_lines
    assert "--paths default" in args_lines[0]
    assert "--run-label nightly" in args_lines[0]
    assert "--out" not in args_lines[0]


# ---------------------------------------------------------------------------
# Gap 308 — the default has to be writable in an image with no `tests/`
# ---------------------------------------------------------------------------


def test_the_default_output_dir_is_tests_in_a_source_checkout():
    """Local dev must not move: every earlier run's output, and the paths the
    docs quote, live under `tests/`."""
    assert default_output_dir() == _BE_ROOT / "tests"
    assert default_output_path(None).endswith(str(Path("tests") / OUTPUT_NAME))


def test_the_default_falls_back_off_tests_when_that_directory_is_absent(monkeypatch):
    """The container case. `.dockerignore` excludes `**/tests/`, so `/app/tests`
    does not exist and the old default could only ever raise."""
    monkeypatch.setattr(script, "_CHECKOUT_OUTPUT_DIR", _BE_ROOT / "no-such-dir")

    fallback = default_output_dir()
    assert fallback == Path(tempfile.gettempdir())
    assert "tests" not in Path(default_output_path(None)).parts
    # The point of the fallback: unlike `tests/` in the image, this exists.
    assert fallback.is_dir()


def test_a_candidate_run_still_gets_its_own_file_under_the_fallback(monkeypatch):
    """The substitution guard (a candidate must not overwrite the baseline) is
    independent of which directory is in use."""
    monkeypatch.setattr(script, "_CHECKOUT_OUTPUT_DIR", _BE_ROOT / "no-such-dir")

    baseline = default_output_path(None)
    candidate = default_output_path("azure:gpt-4o")

    assert Path(baseline).parent == Path(candidate).parent == Path(tempfile.gettempdir())
    assert candidate != baseline
    assert candidate.endswith("agent_eval_output_azure_gpt_4o.json")


def test_the_nightly_invocation_writes_its_output_with_no_tests_directory(
    monkeypatch, tmp_path, clean_run_source, capsys
):
    """The regression proper: the exact nightly argv, in an environment shaped
    like the image (no `tests/`), completes and leaves a readable payload.

    Before the fix this raised `FileNotFoundError` on the final `open(args.out,
    "w")` — after every graded turn had already run and persisted, which is why
    the live failure looked like a healthy job that crashed at the finish line.
    """
    missing_tests_dir = tmp_path / "app" / "tests"
    written_to = tmp_path / "fallback-tmp"
    written_to.mkdir()
    monkeypatch.setattr(script, "_CHECKOUT_OUTPUT_DIR", missing_tests_dir)
    monkeypatch.setattr(tempfile, "gettempdir", lambda: str(written_to))

    _run_nightly_main(monkeypatch)

    assert not missing_tests_dir.exists(), "the fix must not create a tests/ tree"
    output = written_to / OUTPUT_NAME
    assert output.is_file()
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["paths"] == ["default"]
    assert payload["turns"] == []
    assert f"Wrote 0 turns to {output}" in capsys.readouterr().out


def test_an_explicit_out_still_wins_over_the_fallback(
    monkeypatch, tmp_path, clean_run_source
):
    """The pre-deploy gate passes `--out /tmp/agent_eval_gate.json`
    (`.github/workflows/deploy-dev.yml`) and must keep being obeyed verbatim."""
    fallback = tmp_path / "fallback-tmp"
    fallback.mkdir()
    monkeypatch.setattr(script, "_CHECKOUT_OUTPUT_DIR", tmp_path / "no-such-dir")
    monkeypatch.setattr(tempfile, "gettempdir", lambda: str(fallback))
    explicit = tmp_path / "gate.json"

    _run_nightly_main(monkeypatch, extra_argv=["--out", str(explicit)])

    assert explicit.is_file()
    # ...and the fallback was not written to at all.
    assert list(fallback.iterdir()) == []


# ---------------------------------------------------------------------------
# Gap 317 — the same failure class closed from the caller's end
# ---------------------------------------------------------------------------


def test_an_explicit_out_under_a_missing_directory_is_created_not_crashed(
    monkeypatch, tmp_path, clean_run_source
):
    """Gap 317. Gap 308 made the *default* safe in an image with no `tests/`;
    a caller-supplied `--out` was still able to reproduce the identical crash
    (every turn graded and every row committed, then `FileNotFoundError` on the
    final write) by naming a directory that only exists in a checkout — which is
    precisely what a "just add `--out` to the two bicep files" fix would have
    reintroduced. `main()` now creates the parent instead."""
    monkeypatch.setattr(script, "_CHECKOUT_OUTPUT_DIR", tmp_path / "no-such-dir")
    explicit = tmp_path / "app" / "tests" / "agent_eval_output.json"
    assert not explicit.parent.exists()

    _run_nightly_main(monkeypatch, extra_argv=["--out", str(explicit)])

    assert explicit.is_file()
    assert json.loads(explicit.read_text(encoding="utf-8"))["paths"] == ["default"]


def test_the_nightly_default_needs_no_directory_creation_at_all(
    monkeypatch, tmp_path, clean_run_source
):
    """The container case must be safe *because the fallback already exists*,
    not because `mkdir` papers over it — a temp directory the process cannot
    create would be the same bug wearing a different path. Asserted by making
    `mkdir` fatal for the duration: the nightly run must still complete."""
    written_to = tmp_path / "fallback-tmp"
    written_to.mkdir()
    monkeypatch.setattr(script, "_CHECKOUT_OUTPUT_DIR", tmp_path / "app" / "tests")
    monkeypatch.setattr(tempfile, "gettempdir", lambda: str(written_to))

    real_mkdir = Path.mkdir

    def _explode_if_it_has_to_create_anything(self, *args, **kwargs):
        if not self.exists():
            raise AssertionError(f"had to create {self}")
        return real_mkdir(self, *args, **kwargs)

    monkeypatch.setattr(Path, "mkdir", _explode_if_it_has_to_create_anything)

    _run_nightly_main(monkeypatch)

    assert (written_to / OUTPUT_NAME).is_file()


# ---------------------------------------------------------------------------
# Gap 318 — the recommendation pass is a step in *this* job, nightly only
# ---------------------------------------------------------------------------


@pytest.fixture
def temp_output(monkeypatch, tmp_path):
    """Keep every run in this section out of the repo's `tests/` directory."""
    written_to = tmp_path / "out"
    written_to.mkdir()
    monkeypatch.setattr(script, "_CHECKOUT_OUTPUT_DIR", tmp_path / "no-such-dir")
    monkeypatch.setattr(tempfile, "gettempdir", lambda: str(written_to))
    return written_to


def _recording_pass():
    """`(calls, callable)` — the callable records and returns the stub."""
    calls = []

    def _recorder(payload, **kwargs):
        calls.append((payload, kwargs))
        return _StubPass()

    return calls, _recorder


def test_the_nightly_run_fires_the_recommendation_pass_with_its_own_results(
    monkeypatch, temp_output, clean_run_source, capsys
):
    """Gap 318's trigger: a step appended to the nightly job's own script, fed
    the payload that run just produced — not a new scheduled resource."""
    calls, recorder = _recording_pass()

    _run_nightly_main(
        monkeypatch, recommendation_pass=recorder, track1_handoff={"mode": "live"}
    )

    assert len(calls) == 1
    payload, kwargs = calls[0]
    assert payload["paths"] == ["default"]
    assert "summary" in payload
    assert kwargs["run_label"] == "nightly"
    # Track 1 ran as the previous process in the job's `&&` chain.
    assert kwargs["extraction_summary"] == {"mode": "live"}
    assert "Recommendation pass [nightly]" in capsys.readouterr().out


@pytest.mark.parametrize("run_label", ["predeploy", "adhoc"])
def test_no_other_cadence_fires_the_recommendation_pass(
    monkeypatch, temp_output, clean_run_source, run_label
):
    """`predeploy` runs a 5-case subset — below the n=20 sample guard — and runs
    on every push; putting two live ARM reads in the deploy path is exactly what
    the nightly-completion trigger design exists to avoid. `adhoc` is a
    developer's own run."""
    calls, recorder = _recording_pass()

    _run_main(
        monkeypatch,
        ["--paths", "default", "--run-label", run_label],
        recommendation_pass=recorder,
    )

    assert calls == []


def test_a_failing_recommendation_pass_cannot_fail_the_nightly_run(
    monkeypatch, temp_output, clean_run_source, capsys
):
    """It is bolted onto the end of a job that has already done all of its real
    work — the Gap 308/317 failure class, and it must not be reintroduced by the
    step that was added to watch for it."""

    def _explode(*a, **k):
        raise RuntimeError("Resource Graph 403")

    _run_nightly_main(monkeypatch, recommendation_pass=_explode)

    output = capsys.readouterr().out
    assert "Recommendation pass failed (RuntimeError: Resource Graph 403)" in output
    # The run still completed and still wrote its results.
    assert (temp_output / OUTPUT_NAME).is_file()
    assert "Wrote 0 turns to" in output


# ---------------------------------------------------------------------------
# Gap 319 — the pass's verdict has to survive the replica
# ---------------------------------------------------------------------------


def _recommendation_events(caplog):
    return [
        r for r in caplog.records if r.getMessage() == telemetry.OPS_RECOMMENDATION_EVENT_NAME
    ]


def _three_categories():
    """A `RecommendationPass` shaped like the real one, built directly: what
    these tests are about is the wiring, not the judgement (which
    `tests/test_ops_recommendation.py` covers against real pass results)."""
    return rec.RecommendationPass(
        run_label="nightly",
        generated_at=datetime(2026, 8, 25, 3, 47, tzinfo=timezone.utc),
        categories=[
            rec.CategoryRecommendation(
                category=category, status=rec.STATUS_WORKED, explanation="everything worked"
            )
            for category in rec.CATEGORY_ORDER
        ],
    )


def test_the_nightly_run_mirrors_every_category_as_its_own_event(
    monkeypatch, temp_output, clean_run_source, capsys, caplog
):
    """Before this, a verdict lived exactly as long as the job replica did. A
    Workbook cannot query Postgres, so a custom event is the only place Gap 320's
    panel can read it from."""
    with caplog.at_level(logging.INFO):
        _run_nightly_main(monkeypatch, recommendation_pass=lambda *a, **k: _three_categories())

    events = _recommendation_events(caplog)
    assert len(events) == 3
    assert [e.category for e in events] == list(rec.CATEGORY_ORDER)
    assert {e.run_label for e in events} == {"nightly"}
    assert {e.generated_at for e in events} == {"2026-08-25T03:47:00+00:00"}
    out = capsys.readouterr().out
    assert "Recommendation mirror [nightly] -> stdout only: 3 telemetry event(s)" in out
    # The run itself still finished and still wrote its results.
    assert (temp_output / OUTPUT_NAME).is_file()


@pytest.mark.parametrize("run_label", ["predeploy", "adhoc"])
def test_no_other_cadence_persists_a_recommendation(
    monkeypatch, temp_output, clean_run_source, run_label, caplog
):
    """The nightly-only gate covers the emission too — a 5-case gate run's
    verdict joining the nightly trend would make the panel unreadable, for the
    same reason `run_label` exists on every other benchmark event."""
    with caplog.at_level(logging.INFO):
        _run_main(
            monkeypatch,
            ["--paths", "default", "--run-label", run_label],
            recommendation_pass=lambda *a, **k: _three_categories(),
        )

    assert _recommendation_events(caplog) == []


def test_no_mirror_keeps_the_verdict_local(
    monkeypatch, temp_output, clean_run_source, capsys, caplog
):
    """`--no-mirror` already means "emit no event and upload no artifact (local
    run, offline)" for `agent_eval_summary`; it means the same here rather than
    a second flag."""
    with caplog.at_level(logging.INFO):
        _run_nightly_main(
            monkeypatch,
            extra_argv=["--no-mirror"],
            recommendation_pass=lambda *a, **k: _three_categories(),
        )

    assert _recommendation_events(caplog) == []
    out = capsys.readouterr().out
    # The pass still ran and still printed — only the persistence is skipped.
    assert "Recommendation pass [nightly]" in out
    assert "Recommendation mirror" not in out


def test_the_recommendation_events_are_flushed_before_the_process_exits(
    monkeypatch, temp_output, clean_run_source
):
    """`main()`'s own mirror block has already flushed by the time this step
    runs, and the OTel exporter batches on a timer — so without a second flush
    these three events die with the process. That is precisely the "the job ran
    and the workbook shows nothing" symptom the mirror exists to prevent."""
    flushes = []
    monkeypatch.setattr(script, "flush_run_telemetry", lambda: flushes.append(len(flushes)))

    _run_nightly_main(
        monkeypatch,
        recommendation_pass=lambda *a, **k: _three_categories(),
        exporter_attached=True,
    )

    # Once for the `agent_eval_summary` mirror, once after the recommendation
    # events that are emitted *after* it.
    assert len(flushes) == 2


def test_a_broken_exporter_cannot_fail_the_nightly_run(
    monkeypatch, temp_output, clean_run_source, capsys
):
    """Fail-soft at the wiring level, not just inside the emitter: this is bolted
    onto the end of a job that has already graded every turn and committed every
    row (the Gap 308/317 failure class)."""
    monkeypatch.setattr(
        telemetry,
        "track_ops_recommendation",
        MagicMock(side_effect=RuntimeError("exporter down")),
    )

    _run_nightly_main(monkeypatch, recommendation_pass=lambda *a, **k: _three_categories())

    out = capsys.readouterr().out
    assert "0 telemetry event(s)" in out and "exporter down" in out
    assert (temp_output / OUTPUT_NAME).is_file()
    assert "Wrote 0 turns to" in out
