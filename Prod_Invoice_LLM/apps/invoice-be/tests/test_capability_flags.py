"""Gap 482 (Feature 29 phase-2 P0.6) -- the five phase-2 capability flags.

Every capability phase 2 adds sits behind its own flag, all default False. The reason
is measurement, not caution: a live golden run is expensive -- the 2026-09-07 36-case
run took 7h39m against the throttled dev endpoint -- so a regression has to be
attributable to ONE capability from a single run's turn records, rather than by
re-running the set with things switched off one at a time.

That only works if two things hold, and both are pinned here:

  1. Every flag defaults False, so a deployment that has not thought about phase 2
     gets exactly today's behaviour (the BE Gap 402 lesson, restated).
  2. Every turn record carries the active flag set *and* the route it took -- and
     carries them even when the set is empty, so "all flags off" is distinguishable
     from "recorded before this field existed".

Plus the infra half: a flag that exists only in `config.py` is not operable, because
there is no env var on the container to flip and no way to read from Azure what the
running process believes.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from config import Settings, get_settings
from scripts.run_agent_eval import CAPABILITY_FLAGS, _active_capability_flags

_BE_ROOT = Path(__file__).resolve().parents[1]
_INFRA = _BE_ROOT.parents[1] / "infra"

_COMPUTE_MODULES = (
    _INFRA / "modules" / "compute" / "invoice-be.bicep",
    _INFRA / "modules" / "compute" / "queue-worker.bicep",
    _INFRA / "modules" / "compute" / "scheduled-job.bicep",
)
_APPS = _INFRA / "08-apps.bicep"

#: env/Settings name -> bicep param name
_FLAG_PARAMS = {
    "ENABLE_ENTITY_RESOLVER": "enableEntityResolver",
    "ENABLE_SEMANTIC_VIEWS": "enableSemanticViews",
    "ENABLE_CERTIFIED_EXAMPLES": "enableCertifiedExamples",
    "ENABLE_KNOWLEDGE_LAYER": "enableKnowledgeLayer",
    "ENABLE_RERANK": "enableRerank",
    # Feature 30 master flag (Gap 496) -- threaded exactly like the phase-2 five.
    "ENABLE_ATTACHMENT_INSIGHTS": "enableAttachmentInsights",
}

#: Founder 2026-09-08 ("Turn them all ON"): every capability flag is ON in dev,
#: rerank included (no consumer yet; on so it is not forgotten when one lands).
_DEV_ON = frozenset(_FLAG_PARAMS.values())


def _text(p: Path) -> str:
    assert p.exists(), f"missing infra file: {p}"
    return p.read_text(encoding="utf-8")


# --- 1: settings defaults ---------------------------------------------------

def test_the_registry_lists_exactly_the_six_capabilities():
    assert set(CAPABILITY_FLAGS) == set(_FLAG_PARAMS)
    assert len(CAPABILITY_FLAGS) == len(set(CAPABILITY_FLAGS)), "duplicate flag name"


@pytest.mark.parametrize("flag", sorted(_FLAG_PARAMS))
def test_every_capability_flag_exists_on_settings_and_defaults_off(flag):
    fields = Settings.model_fields
    assert flag in fields, f"Settings has no {flag}"
    assert fields[flag].annotation is bool, f"{flag} must be a bool"
    assert fields[flag].default is False, (
        f"{flag} defaults to {fields[flag].default!r}; a phase-2 capability that is on by "
        f"default cannot be attributed from a turn record, and ships untested behaviour"
    )


def test_the_live_settings_object_has_them_all_off():
    """Not the same assertion as the default: `.env` could turn one on."""
    settings = get_settings()
    on = [f for f in CAPABILITY_FLAGS if getattr(settings, f)]
    assert on == [], f"phase-2 capability flags are ON in this environment: {on}"


# --- 2: the turn record -----------------------------------------------------

def test_active_capability_flags_is_empty_when_everything_is_off():
    assert _active_capability_flags() == []


def test_active_capability_flags_reports_only_what_is_on_and_is_sorted(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "ENABLE_RERANK", True, raising=False)
    monkeypatch.setattr(settings, "ENABLE_ENTITY_RESOLVER", True, raising=False)
    assert _active_capability_flags() == ["ENABLE_ENTITY_RESOLVER", "ENABLE_RERANK"]


def test_a_flag_missing_from_settings_is_skipped_rather_than_raising(monkeypatch):
    """This runs inside a 7-hour live eval; telemetry must not be what ends it."""
    monkeypatch.setattr(
        "scripts.run_agent_eval.CAPABILITY_FLAGS",
        ("ENABLE_RERANK", "ENABLE_A_CAPABILITY_THAT_WAS_DELETED"),
    )
    assert _active_capability_flags() == []


def test_the_turn_record_carries_route_and_capability_flags():
    """Pinned against the real `run_turn` source: these two keys are what a live
    run is read back through, and dropping either silently costs a whole run."""
    src = (_BE_ROOT / "scripts" / "run_agent_eval.py").read_text(encoding="utf-8")
    # Gap 487: the route is read from `judge_evidence`, which is where the agent
    # actually writes it -- `result["route"]` does not exist and gave None on every
    # turn. See that Gap; this assertion moved with the fix.
    assert '(result.get("judge_evidence") or {}).get("route")' in src
    assert '"capability_flags": _active_capability_flags(),' in src


# --- 3: the infra half ------------------------------------------------------

@pytest.mark.parametrize("module", _COMPUTE_MODULES, ids=lambda p: p.name)
@pytest.mark.parametrize("flag", sorted(_FLAG_PARAMS))
def test_every_module_declares_the_param_and_sets_the_env_from_it(module, flag):
    param = _FLAG_PARAMS[flag]
    text = _text(module)
    assert f"param {param} bool = false" in text, (
        f"{module.name} does not declare {param}; the flag exists in code but there is "
        f"nothing an operator can flip and no way to see it from Azure (BE Gap 402)"
    )
    m = re.search(
        r"\{\s*name:\s*'" + re.escape(flag) + r"'\s*value:\s*(\w+) \? 'true' : 'false'\s*\}",
        text,
    )
    assert m, f"{module.name} does not set env {flag}"
    assert m.group(1) == param, f"{module.name} sets {flag} from {m.group(1)}, expected {param}"


@pytest.mark.parametrize("flag", sorted(_FLAG_PARAMS))
def test_08_apps_declares_each_flag_and_threads_it_to_the_three_chat_running_modules(flag):
    """backendApp, queueWorker and benchmarkEvalJob run chat turns; the billing and
    sweep jobs do not and correctly keep the module default."""
    param = _FLAG_PARAMS[flag]
    text = _text(_APPS)
    assert f"param {param} bool = false" in text, f"08-apps.bicep does not declare {param}"
    sites = len(re.findall(rf"^\s*{re.escape(param)}: {re.escape(param)}$", text, re.M))
    assert sites == 3, (
        f"08-apps.bicep threads {param} to {sites} modules, expected 3 "
        f"(backendApp, queueWorker, benchmarkEvalJob)"
    )


@pytest.mark.parametrize("flag", sorted(_FLAG_PARAMS))
def test_params_files_pin_dev_on_for_built_capabilities_and_prod_off(flag):
    """Founder 2026-09-08: every built switch is ON in dev. Prod stays off until
    the Feature 29 §10.1 rollout; rerank is off everywhere because 30.14 built nothing."""
    param = _FLAG_PARAMS[flag]
    dev = json.loads(_text(_INFRA / "params.dev.json"))["parameters"]
    prod = json.loads(_text(_INFRA / "params.prod.json"))["parameters"]
    assert param in dev and param in prod, f"a params file is missing {param}"
    assert dev[param]["value"] is (param in _DEV_ON), f"params.dev.json {param} should be {param in _DEV_ON}"
    assert prod[param]["value"] is False, f"params.prod.json sets {param} true; prod is untouched by Features 29/30"
