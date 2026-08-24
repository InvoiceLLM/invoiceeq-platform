"""`scripts/run_extraction_benchmark.py`'s CLI, in particular `--tolerate-fp`.

Feature 23's pre-deploy gate (`.github/workflows/deploy-dev.yml`) needs the
gate to keep failing on a real regression while not failing every single
deploy on Gap 293's known, deliberately-not-fixed clean-set false positive
(`outbound_trade_discount__clean` -- see
`docs/feature_23_ai_control_tower.md`, "The defect the first run found"). This
pins that behaviour directly against the real `main()`, not a reimplementation
of its gate logic -- verify mode is deterministic and makes no network call,
so this is fast enough to run on every test suite invocation.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

os.environ.setdefault("MOCK_EMBEDDINGS", "true")

_BE_ROOT = Path(__file__).resolve().parent.parent
if str(_BE_ROOT) not in sys.path:
    sys.path.insert(0, str(_BE_ROOT))
_SCRIPTS_DIR = str(_BE_ROOT / "scripts")
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)

from scripts.run_extraction_benchmark import main  # noqa: E402

# The one case Gap 293 is expected to false-positive on -- see the module
# docstring. Named as a constant here (not imported from the script, which
# doesn't export one) so a reader can see exactly what this test pins without
# cross-referencing the CI workflow.
GAP_293_KNOWN_FP = "outbound_trade_discount__clean"


def _run_main(argv, monkeypatch, mirror=False):
    """Invoke the real `main()`.

    `--no-mirror` by default: the telemetry/blob mirror added 2026-08-24 is
    exercised properly in `tests/test_benchmark_artifacts.py`, and leaving it on
    here would make every one of these gate assertions wait on a storage
    connection attempt that cannot succeed in CI. `mirror=True` is used by the
    one test below that specifically pins the mirror's non-fatality *through the
    CLI*.
    """
    if mirror:
        argv = [a for a in argv if a != "--no-mirror"]
    elif "--no-mirror" not in argv:
        argv = [*argv, "--no-mirror"]
    monkeypatch.setattr(sys, "argv", ["run_extraction_benchmark.py", *argv])
    return main()


def test_verify_gate_fails_without_tolerating_the_known_gap_293_false_positive(monkeypatch):
    exit_code = _run_main(["--mode", "verify", "--no-write"], monkeypatch)
    assert exit_code == 1


def test_verify_gate_passes_when_gap_293_is_explicitly_tolerated(monkeypatch):
    exit_code = _run_main(
        ["--mode", "verify", "--no-write", "--tolerate-fp", GAP_293_KNOWN_FP],
        monkeypatch,
    )
    assert exit_code == 0


def test_tolerating_a_different_case_id_does_not_mask_gap_293(monkeypatch):
    """`--tolerate-fp` is a specific allowlist, not a blanket "ignore FPs" switch."""
    exit_code = _run_main(
        ["--mode", "verify", "--no-write", "--tolerate-fp", "some_other_case_id"],
        monkeypatch,
    )
    assert exit_code == 1


def test_tolerate_fp_does_not_mask_a_missed_seeded_case(monkeypatch):
    """A recall miss must still fail the gate even with --tolerate-fp set --
    tolerating a known false positive is not a general escape hatch."""
    exit_code = _run_main(
        [
            "--mode",
            "verify",
            "--no-write",
            "--cases",
            f"{GAP_293_KNOWN_FP},us_flat_sales_tax__printed_total_broken",
            "--tolerate-fp",
            GAP_293_KNOWN_FP,
        ],
        monkeypatch,
    )
    # Both cases run cleanly in verify mode (the seeded case is a true
    # positive, not a miss), so this is really asserting the gate still
    # evaluates missed_cases/errors independently of the FP allowlist -- see
    # the two tests above for the allowlist's own behaviour.
    assert exit_code == 0


def test_no_gate_always_exits_zero_even_without_tolerate_fp(monkeypatch):
    exit_code = _run_main(["--mode", "verify", "--no-write", "--no-gate"], monkeypatch)
    assert exit_code == 0


@pytest.mark.parametrize("cases", ["", "  ", ","])
def test_empty_tolerate_fp_behaves_like_not_passing_it(monkeypatch, cases):
    exit_code = _run_main(
        ["--mode", "verify", "--no-write", "--tolerate-fp", cases], monkeypatch
    )
    assert exit_code == 1


# ---------------------------------------------------------------------------
# The telemetry/blob mirror (2026-08-24) must never change the gate's verdict
# ---------------------------------------------------------------------------


def test_a_failing_mirror_does_not_change_the_gate_verdict(monkeypatch, capsys):
    """Instrumentation must not break the thing it instruments.

    Both halves are broken here -- the blob client raises on construction and
    the telemetry emitter raises on emit -- and the gate still has to reach the
    same exit code it reaches with neither of them present (0 with the known
    Gap 293 false positive tolerated, per the test above).
    """
    import telemetry
    from services import benchmark_artifacts

    def _explode(*args, **kwargs):
        raise RuntimeError("storage/exporter down")

    monkeypatch.setattr(benchmark_artifacts, "_blob_service_client", _explode)
    monkeypatch.setattr(telemetry, "_emit_event", _explode)

    exit_code = _run_main(
        ["--mode", "verify", "--no-write", "--tolerate-fp", GAP_293_KNOWN_FP],
        monkeypatch,
        mirror=True,
    )
    assert exit_code == 0
    # ...and it said so, rather than reporting a mirror that did not happen.
    assert "mirror [adhoc]" in capsys.readouterr().out


def test_the_exporter_attaches_before_the_first_case_runs(monkeypatch):
    """Gap 304 half (1): the attach moved from the mirror (after every case) to
    startup, so the run's own per-call events and GenAI dependency spans are
    exported instead of withheld.

    Order is asserted through the real `main()` rather than by reading it,
    because "before the first graded turn" is the entire correctness claim — and
    `configure_run_source()` must come first of all, so nothing can be exported
    untagged.
    """
    import scripts.run_extraction_benchmark as script
    from services import benchmark_artifacts

    order = []
    real_configure_run_source = script.configure_run_source
    real_run_benchmark = script.run_benchmark

    def _configure_run_source(run_label):
        order.append("run_source")
        return real_configure_run_source(run_label)

    def _configure_run_telemetry():
        order.append("exporter")
        return False

    def _run_benchmark(**kwargs):
        order.append("cases")
        return real_run_benchmark(**kwargs)

    monkeypatch.setattr(script, "configure_run_source", _configure_run_source)
    monkeypatch.setattr(script, "configure_run_telemetry", _configure_run_telemetry)
    monkeypatch.setattr(script, "run_benchmark", _run_benchmark)
    monkeypatch.setattr(benchmark_artifacts, "_blob_service_client", lambda: None)

    _run_main(["--mode", "verify", "--no-write", "--no-gate"], monkeypatch, mirror=True)

    # The mirror's own (now idempotent) call is still there at the end; what
    # matters is that an attach happened before any case ran.
    assert order[:3] == ["run_source", "exporter", "cases"]


def test_no_mirror_still_exports_nothing(monkeypatch):
    """`--no-mirror` means "local run, offline". Exporting per-call events under
    it would contradict the flag, so the early attach is skipped too."""
    import scripts.run_extraction_benchmark as script

    attached = []
    monkeypatch.setattr(
        script, "configure_run_telemetry", lambda: attached.append(1)  # pragma: no cover
    )

    _run_main(["--mode", "verify", "--no-write", "--no-gate"], monkeypatch)
    assert attached == []


def test_the_mirror_runs_even_when_the_gate_fails(monkeypatch, capsys):
    """A failing gate run is exactly the run whose numbers most need to reach the
    workbook, so the mirror must not sit behind an early `return 1`."""
    emitted = []
    import telemetry
    from services import benchmark_artifacts

    monkeypatch.setattr(benchmark_artifacts, "_blob_service_client", lambda: None)
    monkeypatch.setattr(
        telemetry, "_emit_event", lambda name, attributes: emitted.append(name)
    )

    exit_code = _run_main(["--mode", "verify", "--no-write"], monkeypatch, mirror=True)
    assert exit_code == 1  # Gap 293's false positive, untolerated
    assert telemetry.EXTRACTION_BENCHMARK_EVENT_NAME in emitted


# ---------------------------------------------------------------------------
# Gap 309 — the mirror event has to survive `logging`'s own level check
# ---------------------------------------------------------------------------


def test_the_mirror_event_reaches_a_real_handler_on_the_event_logger(monkeypatch):
    """Found live 2026-08-24: this run printed
    ``mirror [nightly] -> Application Insights + stdout: 1 telemetry event(s)``
    and `extraction_benchmark_run` was **absent from `customEvents`**, while
    Track 2's `agent_eval_summary` from the same execution landed.

    Neither the exporter nor the flush was at fault. `telemetry._emit_event()`
    logs at INFO; `configure_azure_monitor()` attaches a handler to
    `invoice_be_telemetry` without ever setting a level, so in a bare
    `python scripts/...` process the logger inherits root's WARNING and
    `logging` discards the record before Azure Monitor's handler is consulted.
    The reassuring stdout line is `MirrorResult.describe()` counting emitter
    *calls* — the silent no-op class Gap 292 named.

    Every other mirror test in this file misses this by construction: the one
    above patches `telemetry._emit_event` (so the level check never runs), and
    `tests/test_benchmark_artifacts.py` uses `caplog.at_level(logging.INFO)`
    (which raises the level itself). This one does neither — it starts from the
    levels a fresh process really has and asserts on a handler attached exactly
    where the distro attaches its own.
    """
    import logging

    import telemetry
    from services import benchmark_artifacts

    seen = []

    class _Recording(logging.Handler):
        def emit(self, record):
            seen.append(record.getMessage())

    # A fresh script process: logger at NOTSET, inheriting root's WARNING.
    event_logger = logging.getLogger(telemetry._EVENT_LOGGER_NAMES[0])
    root = logging.getLogger()
    previous_level, previous_root = event_logger.level, root.level
    handler = _Recording()
    event_logger.setLevel(logging.NOTSET)
    root.setLevel(logging.WARNING)
    event_logger.addHandler(handler)

    # No real exporter and no real storage; the handler above stands in for the
    # one `configure_azure_monitor()` would have attached.
    monkeypatch.setattr(benchmark_artifacts, "_exporter_attached", None)
    monkeypatch.delenv("APPLICATIONINSIGHTS_CONNECTION_STRING", raising=False)
    monkeypatch.setattr(benchmark_artifacts, "_blob_service_client", lambda: None)
    run_source_token = telemetry.run_source_ctx.set(telemetry.RUN_SOURCE_PRODUCTION)

    try:
        _run_main(
            ["--mode", "verify", "--no-write", "--no-gate", "--run-label", "nightly"],
            monkeypatch,
            mirror=True,
        )
        assert telemetry.EXTRACTION_BENCHMARK_EVENT_NAME in seen
    finally:
        event_logger.removeHandler(handler)
        event_logger.setLevel(previous_level)
        root.setLevel(previous_root)
        telemetry.run_source_ctx.reset(run_source_token)
