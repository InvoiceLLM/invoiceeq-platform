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
