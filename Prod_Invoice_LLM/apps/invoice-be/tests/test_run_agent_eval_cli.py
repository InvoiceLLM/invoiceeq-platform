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

`main()` is driven with the literal nightly argv. The case list is emptied
instead of shortened so no LLM is called and no turn runs — the defect is in the
write at the end of `main()`, which is reached identically either way — and the
two out-of-process side effects (`persist`, the telemetry/blob mirror) are
stubbed rather than switched off with flags, so the argv under test stays
byte-for-byte the one Azure runs.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

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


def _run_nightly_main(monkeypatch, extra_argv=()):
    """The real `main()` on the real nightly argv, with no turns and no I/O."""
    monkeypatch.setattr(script, "CASES", [])
    monkeypatch.setattr(script, "persist", lambda *a, **k: 0)
    monkeypatch.setattr(script, "configure_run_telemetry", lambda: False)
    monkeypatch.setattr(script, "mirror_agent_eval_run", lambda *a, **k: MirrorResult())
    monkeypatch.setattr(
        sys, "argv", ["run_agent_eval.py", *_NIGHTLY_ARGV, *extra_argv]
    )
    script.main()


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
