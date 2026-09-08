"""Gap 481 (Feature 29 phase-2 P0.4) -- the chat_summary model role is wired end to end.

Task 29.1 added the `chat_summary` (and, until Gap 489 removed it, `long_doc`) role and
its setting, but the containers were never given the environment variable, so in Azure
the role resolved by *fallback* (chat_summary -> judge -> primary) and the deployment
actually in force could not be read off the infrastructure. This file pins the wiring,
and (test 4) that the removed `long_doc` role has not crept back into infra.

The invariant that actually bites is #3. `Settings` is a pydantic-settings model, so an
environment variable whose name does not exactly match a field is **silently ignored** --
a typo in bicep produces no error anywhere, just a role that keeps falling back while the
params file claims otherwise. Comparing the bicep env names against the real `Settings`
fields is the only thing that catches it, and it is cheap.

  1. Each of the three compute modules declares the param and emits the env var.
  2. `08-apps.bicep` declares the param and threads it to every module invocation
     that already threads the judge param -- no module left behind.
  3. Every `AZURE_OPENAI_*_DEPLOYMENT_NAME` env name set in bicep is a real `Settings`
     field, and the new role's setting is among them.
  4. `params.dev.json` pins chat_summary to gpt-5-mini (Feature 29 decision 2);
     `params.prod.json` carries the same key empty -- prod is untouched by Feature 29 by
     design. Neither file, and no bicep module, still carries the removed long_doc param.
  5. The values those params carry resolve through the registry to the roles they name,
     so the infrastructure and `utils/model_registry` cannot drift apart.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from config import Settings
from utils import model_registry as reg

_BE_ROOT = Path(__file__).resolve().parents[1]
_INFRA = _BE_ROOT.parents[1] / "infra"

_COMPUTE_MODULES = (
    _INFRA / "modules" / "compute" / "invoice-be.bicep",
    _INFRA / "modules" / "compute" / "queue-worker.bicep",
    _INFRA / "modules" / "compute" / "scheduled-job.bicep",
)
_APPS = _INFRA / "08-apps.bicep"

#: role -> (bicep param name, env var name / Settings field)
_ROLES = (
    ("chat_summary", "azureOpenAiChatSummaryDeploymentName",
     "AZURE_OPENAI_CHAT_SUMMARY_DEPLOYMENT_NAME"),
)

_ROLE_IDS = [r[0] for r in _ROLES]


def _text(p: Path) -> str:
    assert p.exists(), f"missing infra file: {p}"
    return p.read_text(encoding="utf-8")


# --- 1: the compute modules -------------------------------------------------

@pytest.mark.parametrize("module", _COMPUTE_MODULES, ids=lambda p: p.name)
@pytest.mark.parametrize("role, param, env", _ROLES, ids=_ROLE_IDS)
def test_each_compute_module_declares_the_param_and_sets_the_env_var(module, role, param, env):
    text = _text(module)
    assert f"param {param} string = ''" in text, (
        f"{module.name} does not declare {param}; the role would resolve by fallback with no "
        f"way to see it from the infrastructure"
    )
    # the env entry must reference the param, not a hardcoded literal
    block = re.search(
        r"\{\s*name:\s*'" + re.escape(env) + r"'\s*value:\s*(\S+)\s*\}",
        text,
    )
    assert block, f"{module.name} does not set env {env}"
    assert block.group(1) == param, (
        f"{module.name} sets {env} from {block.group(1)!r}, expected the param {param!r}"
    )


# --- 2: the stage threads them to every module ------------------------------

@pytest.mark.parametrize("role, param, env", _ROLES, ids=_ROLE_IDS)
def test_08_apps_threads_the_param_to_every_module_that_takes_the_judge_param(role, param, env):
    text = _text(_APPS)
    assert f"param {param} string = ''" in text, f"08-apps.bicep does not declare {param}"
    judge_sites = len(re.findall(
        r"^\s*azureOpenAiJudgeDeploymentName: azureOpenAiJudgeDeploymentName$", text, re.M))
    role_sites = len(re.findall(
        r"^\s*" + re.escape(param) + r": " + re.escape(param) + r"$", text, re.M))
    assert judge_sites > 0, "no judge pass-through sites found -- has 08-apps.bicep been restructured?"
    assert role_sites == judge_sites, (
        f"08-apps.bicep passes the judge deployment to {judge_sites} modules but {param} to "
        f"{role_sites}; a module was left behind and that role silently falls back there"
    )


# --- 3: the env names are real Settings fields ------------------------------

def test_every_openai_deployment_env_name_in_bicep_is_a_real_settings_field():
    """A name pydantic does not recognise is ignored in silence -- no error, no log."""
    fields = set(Settings.model_fields)
    seen = set()
    for path in (*_COMPUTE_MODULES, _APPS):
        for env in re.findall(r"name: '(AZURE_OPENAI_\w*DEPLOYMENT_NAME)'", _text(path)):
            seen.add(env)
            assert env in fields, (
                f"{path.name} sets {env}, which is not a field on Settings -- pydantic would "
                f"ignore it and the role would keep falling back"
            )
    for _, _, env in _ROLES:
        assert env in seen, f"{env} is set by no bicep file at all"


@pytest.mark.parametrize("role, param, env", _ROLES, ids=_ROLE_IDS)
def test_the_two_new_roles_settings_exist_and_default_to_empty(role, param, env):
    fields = Settings.model_fields
    assert env in fields, f"Settings has no {env}"
    assert fields[env].default == "", (
        f"{env} must default to empty so the role falls back when the container is not given one"
    )


# --- 4: the params files ----------------------------------------------------

def _params(name: str) -> dict:
    return json.loads(_text(_INFRA / name))["parameters"]


@pytest.mark.parametrize("role, param, env", _ROLES, ids=_ROLE_IDS)
def test_both_params_files_carry_both_keys(role, param, env):
    for name in ("params.dev.json", "params.prod.json"):
        assert param in _params(name), f"{name} is missing {param}"


def test_dev_pins_chat_summary_to_gpt_5_mini_and_has_no_long_doc_param():
    dev = _params("params.dev.json")
    # decision 2: gpt-5-mini narrates the full-record route, Luna keeps the attachment branches
    assert dev["azureOpenAiChatSummaryDeploymentName"]["value"] == "gpt-5-mini"
    # task 29.10 / Gap 489: the long_doc role was removed, so the param must be gone everywhere
    assert "azureOpenAiLongDocDeploymentName" not in dev
    assert "azureOpenAiLongDocDeploymentName" not in _params("params.prod.json")
    for path in (*_COMPUTE_MODULES, _APPS):
        assert "LongDoc" not in _text(path) and "LONG_DOC" not in _text(path), path.name


def test_prod_carries_the_keys_empty_because_feature_29_does_not_touch_prod():
    prod = _params("params.prod.json")
    for _, param, _ in _ROLES:
        assert prod[param]["value"] == "", (
            f"params.prod.json sets {param}; Feature 29 is dev-only until its rollout gates pass"
        )


# --- 5: the values resolve to the roles they name ---------------------------

def test_the_dev_param_values_resolve_through_the_registry_to_those_roles():
    dev = _params("params.dev.json")
    settings = Settings(
        # pinned: `resolve_model` short-circuits to the "mock" spec on any non-azure
        # provider, and the unit suite runs with LLM_PROVIDER=mock
        LLM_PROVIDER="azure",
        AZURE_OPENAI_DEPLOYMENT_NAME=dev["azureOpenAiDeploymentName"]["value"],
        AZURE_OPENAI_FAST_DEPLOYMENT_NAME=dev["azureOpenAiFastDeploymentName"]["value"],
        AZURE_OPENAI_JUDGE_DEPLOYMENT_NAME=dev["azureOpenAiJudgeDeploymentName"]["value"],
        AZURE_OPENAI_CHAT_SUMMARY_DEPLOYMENT_NAME=dev["azureOpenAiChatSummaryDeploymentName"]["value"],
    )
    assert reg.resolve_model("chat_summary", settings).deployment == "gpt-5-mini"
    assert reg.resolve_model("fast", settings).deployment == "gpt-5.6-luna"
