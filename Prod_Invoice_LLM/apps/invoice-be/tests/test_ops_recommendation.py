"""Gap 318 — the Feature 20/23/24 nightly recommendation pass.

Three things are pinned here, in this order:

1. **Each category's band, at its real boundary.** Every threshold in
   `services/ops_recommendation.py` is lifted from a live workbook panel's
   `thresholdsGrid`, so the tests use the exact boundary values from those grids
   (70/90 CPU%, 80/100 budget%, 0.70/0.85 faithfulness, 80% alert recall, …) —
   a band that silently drifts one point away from the tile it mirrors is the
   defect this file exists to catch, and only boundary values find it.
2. **Nightly-only wiring.** The trigger design is "a step appended to the
   existing nightly job's script", so `predeploy`/`adhoc` must not fire it —
   both because a 5-case gate run is below the n=20 sample guard and because two
   live ARM reads have no business in a deploy path.
3. **Fail-soft isolation.** A category that cannot read its data must not delete
   the other two from the run. This is the same rule `CostSnapshot.errors`
   holds to: three categories reporting, one of them saying "I could not look",
   is safe; two categories reporting is indistinguishable from "health is fine".

The Azure reads are exercised against captured response *shapes* (Resource Graph
`objectArray`, the Azure Monitor metrics envelope), not mocks of this module's own
functions — the parsing is where this can silently return zero rows.
"""
from __future__ import annotations

import json
import logging
import os
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional
from unittest.mock import MagicMock

import pytest

os.environ.setdefault("MOCK_EMBEDDINGS", "true")

_BE_ROOT = Path(__file__).resolve().parent.parent
if str(_BE_ROOT) not in sys.path:
    sys.path.insert(0, str(_BE_ROOT))

import telemetry  # noqa: E402
from services import benchmark_artifacts, ops_recommendation as rec  # noqa: E402


# ---------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------


def _app(name="ca-invoice-be-dev", **overrides) -> dict:
    app = {
        "name": name,
        "running_status": "Running",
        "min_replicas": 1,
        "max_replicas": 3,
        "cpu_pct": 18.0,
        "memory_pct": 41.0,
        "replicas": 2.0,
        "restarts_24h": 0.0,
    }
    app.update(overrides)
    return app


@dataclass
class _Budget:
    name: str = "budget-invoicellm-dev"
    amount: float = 20000.0
    current_spend: float = 4000.0
    forecast_spend: float = 9000.0
    currency: str = "INR"
    time_grain: str = "Monthly"


@dataclass
class _Slice:
    name: str = "Azure Container Apps"
    amount: float = 8490.0
    currency: str = "INR"
    dimension: str = "ServiceName"


@dataclass
class _Snapshot:
    """The parts of `azure_cost.CostSnapshot` this category actually reads."""

    currency: str = "INR"
    month_to_date_total: float = 4000.0
    budget: Optional[_Budget] = None
    by_service: Optional[list] = None
    errors: Optional[list] = None
    day_over_day_change_pct: Optional[float] = None

    def __post_init__(self):
        if self.budget is None:
            self.budget = _Budget()
        if self.by_service is None:
            self.by_service = [_Slice()]
        if self.errors is None:
            self.errors = []


def _eval_payload(
    turns: int = 35,
    *,
    drift_mean: Optional[float] = 1.0,
    drift_turns: int = 7,
    multi_turn: bool = True,
    **stats: Any,
) -> dict:
    """A `run_agent_eval.py` payload whose every scored dimension is green.

    Gap 307 (2026-08-26): a real nightly payload now carries **two** summary
    buckets — the 35-case single-turn tier under `default` and the multi-turn
    context-drift tier under `default-multiturn` — so the default builder does
    too. `multi_turn=False` reproduces a run where the tier was skipped
    (`--no-multi-turn`) or did not exist, which is a real state this module has
    to report on rather than pass over.
    """
    summary = {
        "turns": turns,
        "errors": 0,
        "pass_rate": 0.87,
        "faithfulness_mean": 0.91,
        "relevance_mean": 0.98,
        "accuracy_mean": 0.86,
        "context_mean": 0.85,
        "orchestration_mean": 0.90,
        "persona_mean": 0.80,
        "latency_ms_median": 1400,
        "cost_per_turn_usd": 0.004,
    }
    summary.update(stats)
    buckets: dict[str, Any] = {"default": summary}
    if multi_turn:
        buckets[benchmark_artifacts.MULTI_TURN_PATH] = {
            "turns": 12,
            "errors": 0,
            "pass_rate": 0.83,
            "context_drift_mean": drift_mean,
            "context_drift_scored_turns": drift_turns,
        }
    return {
        "judge_mode": "separate",
        "model_under_test": None,
        "summary": buckets,
        "turns": [],
    }


def _extraction_summary(recall=1.0, false_positive_rate=0.0, **overrides) -> dict:
    summary = {
        "mode": "live",
        "confusion_matrix": {
            "true_positive": 5,
            "false_negative": 0,
            "false_positive": 0,
            "true_negative": 4,
            "recall": recall,
            "false_positive_rate": false_positive_rate,
        },
        "field_accuracy": {"correct": 40, "total": 45, "ratio": 40 / 45},
        "missed_cases": [],
        "false_positive_documents": [],
        "errors": [],
    }
    summary.update(overrides)
    return summary


# ---------------------------------------------------------------------------
# Category 1 — container health
# ---------------------------------------------------------------------------


def test_container_health_worked_when_every_app_is_inside_its_band():
    result = rec.evaluate_container_health([_app(), _app("ca-invoice-fe-dev", cpu_pct=5.0)])

    assert result.status == rec.STATUS_WORKED
    assert result.recommendation == ""
    assert result.findings == []
    assert result.metrics["app_count"] == 2


@pytest.mark.parametrize(
    "cpu_pct, expected",
    [
        (69.9, None),
        # `container-status`'s grid is `>= 70 yellow`, `>= 90 red` — inclusive.
        (70.0, rec.SEVERITY_YELLOW),
        (89.9, rec.SEVERITY_YELLOW),
        (90.0, rec.SEVERITY_RED),
    ],
)
def test_cpu_bands_match_the_container_status_panel_exactly(cpu_pct, expected):
    result = rec.evaluate_container_health([_app(cpu_pct=cpu_pct)])

    if expected is None:
        assert result.status == rec.STATUS_WORKED
    else:
        assert result.status == rec.STATUS_RECOMMEND
        assert result.findings[0].severity == expected
        assert "CPU%" in result.findings[0].field


def test_memory_pressure_recommends_the_oom_path_not_a_scale_rule():
    result = rec.evaluate_container_health([_app(memory_pct=93.0)])

    assert result.status == rec.STATUS_RECOMMEND
    assert result.findings[0].severity == rec.SEVERITY_RED
    assert "memory limit" in result.recommendation


def test_a_container_that_is_not_running_is_red_whatever_its_metrics_say():
    """`container-scale-config` colours anything that is not exactly `Running`
    red — including states that sound benign."""
    result = rec.evaluate_container_health([_app(running_status="Degraded")])

    assert result.status == rec.STATUS_RECOMMEND
    assert result.worst_severity == rec.SEVERITY_RED
    assert "not running" in result.recommendation.lower()


def test_any_restart_at_all_is_flagged_because_that_is_the_panels_own_filter():
    """`container-restarts` filters `Restarts24h > 0` — the panel shows a row at
    all only when there was a restart, so 1 is the boundary, not 5."""
    clean = rec.evaluate_container_health([_app(restarts_24h=0.0)])
    one = rec.evaluate_container_health([_app(restarts_24h=1.0)])

    assert clean.status == rec.STATUS_WORKED
    assert one.status == rec.STATUS_RECOMMEND
    assert one.findings[0].severity == rec.SEVERITY_YELLOW
    assert one.findings[0].value == 1


def test_replica_count_is_reported_but_never_judged():
    """`container-replicas` is blue by design and its own title says it is "not
    compared against configured max here" — judging it here would be inventing a
    second definition, which this module refuses to do."""
    result = rec.evaluate_container_health([_app(replicas=3.0, max_replicas=3)])

    assert result.status == rec.STATUS_WORKED
    assert result.metrics["replica_counts"] == {"ca-invoice-be-dev": 3.0}


def test_no_container_data_is_no_data_not_a_clean_bill_of_health():
    result = rec.evaluate_container_health([], errors=["container health: HTTP 403"])

    assert result.status == rec.STATUS_NO_DATA
    assert result.errors == ["container health: HTTP 403"]
    assert "Monitoring Reader" in result.explanation


def test_container_collection_is_unconfigured_rather_than_crashing(monkeypatch):
    monkeypatch.setattr(rec.settings, "AZURE_SUBSCRIPTION_ID", "", raising=False)
    monkeypatch.setattr(rec.settings, "AZURE_COST_RESOURCE_GROUP", "", raising=False)

    apps, errors = rec.collect_container_health()

    assert apps == []
    assert errors and "AZURE_SUBSCRIPTION_ID" in errors[0]


def test_container_collection_parses_a_real_arg_and_metrics_response(monkeypatch):
    """The two Azure response shapes, end to end: Resource Graph's `objectArray`
    `data` list, and the metrics envelope's `value[].timeseries[].data[]`."""
    monkeypatch.setattr(rec.settings, "AZURE_SUBSCRIPTION_ID", "sub-1", raising=False)
    monkeypatch.setattr(rec.settings, "AZURE_COST_RESOURCE_GROUP", "rg-invoice-llm-dev", raising=False)

    resource_id = "/subscriptions/sub-1/resourceGroups/rg-invoice-llm-dev/providers/Microsoft.App/containerApps/ca-invoice-be-dev"
    calls: list[tuple[str, str]] = []

    def fake_arm_request(method, url, json_body=None):
        calls.append((method, url))
        if method == "POST":
            assert "microsoft.app/containerapps" in json_body["query"]
            assert json_body["subscriptions"] == ["sub-1"]
            return {
                "totalRecords": 1,
                "data": [
                    {
                        "name": "ca-invoice-be-dev",
                        "id": resource_id,
                        "runningStatus": "Running",
                        "minReplicas": 1,
                        "maxReplicas": 3,
                    }
                ],
            }
        return {
            "value": [
                {
                    "name": {"value": "CpuPercentage"},
                    "timeseries": [
                        {
                            "data": [
                                {"timeStamp": "2026-08-25T01:00:00Z", "average": 12.0},
                                {"timeStamp": "2026-08-25T02:00:00Z", "average": 44.5},
                                # The in-flight bucket: present, all-null.
                                {"timeStamp": "2026-08-25T03:00:00Z"},
                            ]
                        }
                    ],
                },
                {
                    "name": {"value": "RestartCount"},
                    "timeseries": [
                        {
                            "data": [
                                {"timeStamp": "2026-08-25T01:00:00Z", "total": 2.0},
                                {"timeStamp": "2026-08-25T02:00:00Z", "total": 1.0},
                            ]
                        }
                    ],
                },
            ]
        }

    monkeypatch.setattr(
        "services.azure_cost.arm_request", fake_arm_request, raising=True
    )

    apps, errors = rec.collect_container_health()

    assert errors == []
    assert len(apps) == 1
    app = apps[0]
    # Newest *non-null* average, i.e. the 1h average the panel shows — not the
    # in-flight bucket, and not the first one.
    assert app["cpu_pct"] == 44.5
    # Summed across the 24h window, as `sum(Total)` in the restart panel.
    assert app["restarts_24h"] == 3.0
    # Absent metrics stay None rather than becoming a flattering zero.
    assert app["memory_pct"] is None
    assert [method for method, _ in calls] == ["POST", "GET"]
    assert "Microsoft.Insights/metrics" in calls[1][1]


def test_a_metrics_failure_costs_one_app_not_the_whole_category(monkeypatch):
    monkeypatch.setattr(rec.settings, "AZURE_SUBSCRIPTION_ID", "sub-1", raising=False)
    monkeypatch.setattr(rec.settings, "AZURE_COST_RESOURCE_GROUP", "rg-invoice-llm-dev", raising=False)

    def fake_arm_request(method, url, json_body=None):
        if method == "POST":
            return {
                "data": [
                    {"name": "ca-a", "id": "/subscriptions/s/x/ca-a", "runningStatus": "Running"},
                    {"name": "ca-b", "id": "/subscriptions/s/x/ca-b", "runningStatus": "Running"},
                ]
            }
        if "ca-a" in url:
            raise RuntimeError("HTTP 403: Monitoring Reader is not granted")
        return {"value": []}

    monkeypatch.setattr("services.azure_cost.arm_request", fake_arm_request, raising=True)

    apps, errors = rec.collect_container_health()

    assert [a["name"] for a in apps] == ["ca-a", "ca-b"]
    assert len(errors) == 1 and "ca-a" in errors[0]


# ---------------------------------------------------------------------------
# Category 2 — cost
# ---------------------------------------------------------------------------


def test_cost_worked_when_spend_and_forecast_are_both_under_the_band():
    result = rec.evaluate_cost(_Snapshot())

    assert result.status == rec.STATUS_WORKED
    assert result.metrics["spend_pct_of_budget"] == 20.0
    assert result.metrics["forecast_pct_of_budget"] == 45.0
    assert result.metrics["currency"] == "INR"


@pytest.mark.parametrize(
    "month_to_date, expected",
    [
        (15000.0, None),
        # `cost-trend-budget`: `>= 80` yellow, `>= 100` red, on a 20,000 budget.
        (16000.0, rec.SEVERITY_YELLOW),
        (19900.0, rec.SEVERITY_YELLOW),
        (20000.0, rec.SEVERITY_RED),
    ],
)
def test_spend_bands_match_the_cost_trend_budget_panel_exactly(month_to_date, expected):
    """Note the panel bands the *rounded* percentage (its KQL rounds to one
    decimal before the tile colours it), and so does this — which is why 15,999
    of a 20,000 budget is yellow, not green: 79.995 renders as 80.0."""
    result = rec.evaluate_cost(_Snapshot(month_to_date_total=month_to_date))

    if expected is None:
        assert result.status == rec.STATUS_WORKED
    else:
        assert result.status == rec.STATUS_RECOMMEND
        assert result.findings[0].severity == expected
        assert result.findings[0].field == "MTD spend % of budget"


def test_a_breaching_forecast_recommends_acting_before_month_end():
    result = rec.evaluate_cost(_Snapshot(budget=_Budget(forecast_spend=23600.0)))

    assert result.status == rec.STATUS_RECOMMEND
    assert [f.field for f in result.findings] == ["Month-end forecast % of budget"]
    assert result.metrics["forecast_pct_of_budget"] == 118.0
    assert "before month end" in result.recommendation


def test_the_recommendation_names_the_largest_spend_line_to_start_from():
    """The sample table's cost rows all end in "start with the top service" — a
    recommendation that does not name one is not actionable."""
    result = rec.evaluate_cost(
        _Snapshot(month_to_date_total=21000.0, by_service=[_Slice(name="Azure Container Apps")])
    )

    assert "Azure Container Apps" in result.recommendation


def test_spend_percent_is_computed_from_the_same_two_fields_as_the_panel():
    """`cost-trend-budget` divides the snapshot's `month_to_date_total` by
    `budget_amount` — *not* the budget's own `currentSpend`, which lags. A tile
    and a recommendation disagreeing about one number is worse than either."""
    snapshot = _Snapshot(month_to_date_total=10000.0, budget=_Budget(current_spend=1.0))

    assert rec.evaluate_cost(snapshot).metrics["spend_pct_of_budget"] == 50.0


def test_cost_without_a_budget_resource_is_no_data_not_worked():
    result = rec.evaluate_cost(_Snapshot(budget=_Budget(amount=0.0)))

    assert result.status == rec.STATUS_NO_DATA
    assert result.metrics["month_to_date_total"] == 4000.0
    assert result.errors


def test_partial_cost_errors_ride_along_instead_of_discarding_the_verdict():
    result = rec.evaluate_cost(_Snapshot(errors=["forecast: HTTP 429"]))

    assert result.status == rec.STATUS_WORKED
    assert result.errors == ["forecast: HTTP 429"]


def test_unconfigured_cost_is_no_data_without_touching_the_api(monkeypatch):
    monkeypatch.setattr("services.azure_cost.is_configured", lambda: False, raising=True)

    def _explode(*a, **k):  # pragma: no cover - must not be reached
        raise AssertionError("collect_cost_snapshot must not be called")

    monkeypatch.setattr("services.azure_cost.collect_cost_snapshot", _explode, raising=True)

    result = rec.evaluate_cost()

    assert result.status == rec.STATUS_NO_DATA


# ---------------------------------------------------------------------------
# Category 3 — AI improvement
# ---------------------------------------------------------------------------


def test_ai_improvement_worked_on_a_clean_run_with_both_tracks():
    result = rec.evaluate_ai_improvement(_eval_payload(), _extraction_summary())

    assert result.status == rec.STATUS_WORKED
    assert result.errors == []
    assert result.metrics["extraction_supplied"] is True
    assert result.metrics["alert_recall_pct"] == 100.0


@pytest.mark.parametrize(
    "field, red_below, yellow_below",
    sorted((k, v[0], v[1]) for k, v in rec.SCORE_BANDS.items()),
)
def test_every_quality_band_fires_at_the_control_tower_grids_boundary(
    field, red_below, yellow_below
):
    """`d1`–`d3`'s grids are `< x` — so the threshold value itself is *inside*
    the better band, and one hundredth below it is not."""
    key = field if field == "pass_rate" else f"{field}_mean"

    at_threshold = rec.evaluate_ai_improvement(_eval_payload(**{key: yellow_below}))
    just_under = rec.evaluate_ai_improvement(_eval_payload(**{key: yellow_below - 0.01}))
    red = rec.evaluate_ai_improvement(_eval_payload(**{key: red_below - 0.01}))

    assert at_threshold.status == rec.STATUS_WORKED
    assert [f.severity for f in just_under.findings] == [rec.SEVERITY_YELLOW]
    assert [f.severity for f in red.findings] == [rec.SEVERITY_RED]
    assert red.findings[0].field == field


def test_a_quality_drop_says_which_component_to_look_at():
    """Feature 23's soft-metric → component map is the difference between an
    actionable recommendation and "quality dropped"."""
    result = rec.evaluate_ai_improvement(_eval_payload(faithfulness_mean=0.5))

    assert "retrieval/context" in result.recommendation


@pytest.mark.parametrize(
    "cost_per_turn, expected",
    [(0.009, None), (0.01, rec.SEVERITY_YELLOW), (0.02, rec.SEVERITY_RED)],
)
def test_cost_per_turn_band_matches_d4(cost_per_turn, expected):
    result = rec.evaluate_ai_improvement(_eval_payload(cost_per_turn_usd=cost_per_turn))

    if expected is None:
        assert result.status == rec.STATUS_WORKED
    else:
        assert [f.severity for f in result.findings] == [expected]


@pytest.mark.parametrize(
    "recall, expected",
    [(1.0, None), (0.999, rec.SEVERITY_YELLOW), (0.80, rec.SEVERITY_YELLOW), (0.799, rec.SEVERITY_RED)],
)
def test_alert_recall_band_matches_e1_including_that_80_never_reads_green(recall, expected):
    """`e1-alert-recall`'s title states it outright: 80% is real drift evidence,
    never green. Only 100% is."""
    result = rec.evaluate_ai_improvement(_eval_payload(), _extraction_summary(recall=recall))

    if expected is None:
        assert result.status == rec.STATUS_WORKED
    else:
        assert [f.field for f in result.findings] == ["Alert recall %"]
        assert result.findings[0].severity == expected


@pytest.mark.parametrize(
    "fp_rate, expected",
    [(0.0, None), (0.0001, rec.SEVERITY_YELLOW), (0.20, rec.SEVERITY_RED)],
)
def test_clean_false_positive_band_matches_e1_fp_rate(fp_rate, expected):
    result = rec.evaluate_ai_improvement(
        _eval_payload(), _extraction_summary(false_positive_rate=fp_rate)
    )

    if expected is None:
        assert result.status == rec.STATUS_WORKED
    else:
        assert [f.field for f in result.findings] == ["Clean false-positive rate %"]
        assert result.findings[0].severity == expected


def test_turn_errors_are_graded_on_the_existing_chat_turn_error_band():
    """2%/5% is `b1-error-rate`'s grid, reused rather than re-decided. 1 of 35
    turns is 2.86%."""
    result = rec.evaluate_ai_improvement(_eval_payload(errors=1))

    assert result.metrics["turn_error_rate_pct"] == 2.86
    assert [f.field for f in result.findings] == ["turn error rate %"]
    assert result.findings[0].severity == rec.SEVERITY_YELLOW


def test_a_run_below_the_minimum_sample_is_reported_not_graded():
    """The workbooks' n=20 guard, in prose. A 5-case gate run's pass rate is not
    evidence of anything — but the number is still stated, exactly as the
    `-1 → "n/a — see Detail"` sentinel keeps it in `Detail`."""
    result = rec.evaluate_ai_improvement(_eval_payload(turns=19, pass_rate=0.1))

    assert result.status == rec.STATUS_INSUFFICIENT_DATA
    assert "n=20" in result.explanation
    assert result.metrics["pass_rate"] == 0.1
    assert rec.evaluate_ai_improvement(_eval_payload(turns=20)).status == rec.STATUS_WORKED


def test_a_missing_track_1_summary_is_stated_never_treated_as_a_pass():
    result = rec.evaluate_ai_improvement(_eval_payload())

    assert result.status == rec.STATUS_WORKED
    assert result.metrics["extraction_supplied"] is False
    assert any("Track 1" in problem for problem in result.errors)
    assert "alert_recall_pct" not in result.metrics


def test_an_empty_eval_payload_is_no_data():
    result = rec.evaluate_ai_improvement({})

    assert result.status == rec.STATUS_NO_DATA


# ---------------------------------------------------------------------------
# Gap 307 — the multi-turn context-drift tier, inside category 3
# ---------------------------------------------------------------------------


def test_a_clean_drift_tier_is_reported_in_the_worked_explanation():
    result = rec.evaluate_ai_improvement(_eval_payload())

    assert result.status == rec.STATUS_WORKED
    assert result.metrics["context_drift_mean"] == 1.0
    assert result.metrics["context_drift_turns"] == 7
    assert "context drift 1.000" in result.explanation


@pytest.mark.parametrize(
    "drift_mean, expected",
    [
        # `d3-context`'s grid is (0.50 red, 0.70 yellow) and is `< x`, so the
        # threshold value itself is inside the better band.
        (0.70, None),
        (0.69, rec.SEVERITY_YELLOW),
        (0.50, rec.SEVERITY_YELLOW),
        (0.49, rec.SEVERITY_RED),
    ],
)
def test_context_drift_is_graded_on_the_context_tiles_band_not_a_new_one(drift_mean, expected):
    """Deliberately not a new pair of numbers: every band in this module is a
    live workbook tile's, and there is no drift tile. Drift is a retrieval
    failure, so it borrows `d3-context`'s band — which means the pinning test
    below already covers it."""
    result = rec.evaluate_ai_improvement(_eval_payload(drift_mean=drift_mean))

    if expected is None:
        assert result.status == rec.STATUS_WORKED
    else:
        assert [f.field for f in result.findings] == ["context_drift"]
        assert result.findings[0].severity == expected
        assert result.findings[0].value == drift_mean


def test_the_drift_band_is_literally_the_context_band():
    assert rec.SCORE_BANDS[rec.CONTEXT_DRIFT_BAND_KEY] == rec.SCORE_BANDS["context"]
    # And it is NOT its own SCORE_BANDS key: that dict is iterated against the
    # `default` bucket, where this dimension is never scored.
    assert "context_drift" not in rec.SCORE_BANDS


def test_a_drift_finding_names_where_to_look():
    result = rec.evaluate_ai_improvement(_eval_payload(drift_mean=0.4))

    assert "get_chat_history" in result.recommendation
    assert "get_prior_turn_sql" in result.recommendation


def test_the_drift_tier_is_not_subject_to_the_n_20_sample_guard():
    """7 scored turns, every night, deterministically — there is no sampling
    error to guard against, and an n=20 guard would disable the tier forever."""
    result = rec.evaluate_ai_improvement(_eval_payload(drift_mean=0.4, drift_turns=7))

    assert result.status == rec.STATUS_RECOMMEND
    assert [f.field for f in result.findings] == ["context_drift"]


def test_a_skipped_drift_tier_is_stated_never_treated_as_a_pass():
    """Same rule as a missing Track 1 handoff: the absence is on `errors`, the
    dimension is not silently green."""
    result = rec.evaluate_ai_improvement(_eval_payload(multi_turn=False))

    assert result.metrics["context_drift_mean"] is None
    assert result.findings == []
    assert any("context-drift tier did not run" in problem for problem in result.errors)
    assert "context drift" not in result.explanation


def test_a_drift_tier_that_scored_nothing_is_also_stated():
    result = rec.evaluate_ai_improvement(_eval_payload(drift_mean=None, drift_turns=0))

    assert any("scored no drift turn" in problem for problem in result.errors)
    assert result.findings == []


def test_the_drift_bucket_is_never_averaged_into_the_single_turn_numbers():
    """The two populations are different sizes and different difficulties. A
    drift mean of 0.0 must not move `context_mean`, and a single-turn tier
    below its band must not be blamed on drift."""
    clean_single_turn = rec.evaluate_ai_improvement(_eval_payload(drift_mean=0.0))

    assert [f.field for f in clean_single_turn.findings] == ["context_drift"]
    assert clean_single_turn.metrics["context"] == 0.85
    assert clean_single_turn.metrics["turns"] == 35


def test_the_drift_bucket_is_never_mistaken_for_the_baseline_bucket():
    """`_agent_eval_stats()` *chooses* a path and would return the drift bucket
    on a payload that has only that one — which would then be graded against
    every `SCORE_BANDS` key it does not have."""
    payload = _eval_payload()
    payload["summary"].pop("default")

    result = rec.evaluate_ai_improvement(payload)

    assert result.status == rec.STATUS_NO_DATA
    assert result.metrics["context_drift_mean"] == 1.0


# ---------------------------------------------------------------------------
# The pass — fail-soft isolation
# ---------------------------------------------------------------------------


def test_the_pass_returns_all_three_categories_in_order():
    result = rec.run_recommendation_pass(
        _eval_payload(),
        extraction_summary=_extraction_summary(),
        cost_snapshot=_Snapshot(),
        container_apps=[_app()],
    )

    assert [c.category for c in result.categories] == list(rec.CATEGORY_ORDER)
    assert all(c.status == rec.STATUS_WORKED for c in result.categories)
    assert result.categories_recommending == []
    assert result.run_label == "nightly"


def test_a_thrown_category_becomes_no_data_and_the_others_still_report(monkeypatch):
    """The fail-soft requirement, stated as the thing that must not happen: two
    categories reporting instead of three reads as "health is fine"."""

    def _explode(*args, **kwargs):
        raise RuntimeError("Resource Graph 403")

    monkeypatch.setattr(rec, "evaluate_container_health", _explode)

    result = rec.run_recommendation_pass(
        _eval_payload(), extraction_summary=_extraction_summary(), cost_snapshot=_Snapshot()
    )

    assert len(result.categories) == 3
    health = result.by_category(rec.CATEGORY_CONTAINER_HEALTH)
    assert health.status == rec.STATUS_NO_DATA
    assert "Resource Graph 403" in health.errors[0]
    # ...and the two categories that could be evaluated still were.
    assert result.by_category(rec.CATEGORY_AI_IMPROVEMENT).status == rec.STATUS_WORKED
    assert result.by_category(rec.CATEGORY_COST).status == rec.STATUS_WORKED


def test_unavailable_cost_and_health_leave_ai_improvement_fully_evaluated(monkeypatch):
    """The realistic version of the same failure: no Azure credential at all."""
    monkeypatch.setattr(rec.settings, "AZURE_SUBSCRIPTION_ID", "", raising=False)
    monkeypatch.setattr(rec.settings, "AZURE_COST_RESOURCE_GROUP", "", raising=False)

    result = rec.run_recommendation_pass(
        _eval_payload(faithfulness_mean=0.5), extraction_summary=_extraction_summary()
    )

    assert result.by_category(rec.CATEGORY_CONTAINER_HEALTH).status == rec.STATUS_NO_DATA
    assert result.by_category(rec.CATEGORY_COST).status == rec.STATUS_NO_DATA
    ai = result.by_category(rec.CATEGORY_AI_IMPROVEMENT)
    assert ai.status == rec.STATUS_RECOMMEND
    assert ai.recommendation


def test_the_serialised_shape_is_what_gap_319_will_persist():
    """Gap 319 mirrors one custom event per category per run, so the per-category
    dict has to carry status/explanation/recommendation on its own — the panel
    (Gap 320) renders exactly these columns."""
    result = rec.run_recommendation_pass(
        _eval_payload(faithfulness_mean=0.5),
        extraction_summary=_extraction_summary(),
        cost_snapshot=_Snapshot(),
        container_apps=[_app()],
        generated_at=datetime(2026, 8, 25, 3, 47, tzinfo=timezone.utc),
    )
    payload = result.to_dict()

    assert payload["run_label"] == "nightly"
    assert payload["generated_at"] == "2026-08-25T03:47:00+00:00"
    ai = [c for c in payload["categories"] if c["category"] == rec.CATEGORY_AI_IMPROVEMENT][0]
    assert set(ai) == {
        "category",
        "title",
        "status",
        "explanation",
        "recommendation",
        "worst_severity",
        "findings",
        "metrics",
        "errors",
    }
    assert ai["title"] == "AI improvement"
    assert ai["worst_severity"] == rec.SEVERITY_RED
    assert ai["findings"][0]["field"] == "faithfulness"
    # It has to survive a JSON round trip — the mirror serialises it.
    assert json.loads(json.dumps(payload, default=str))["categories"][0]["status"]


def test_worked_and_recommend_are_mutually_exclusive_by_construction():
    worked = rec.evaluate_container_health([_app()])
    recommend = rec.evaluate_container_health([_app(cpu_pct=95.0)])

    assert worked.status == rec.STATUS_WORKED and worked.recommendation == ""
    assert recommend.status == rec.STATUS_RECOMMEND and recommend.recommendation


def test_describe_prints_one_line_per_category_plus_its_recommendation():
    result = rec.run_recommendation_pass(
        _eval_payload(),
        extraction_summary=_extraction_summary(),
        cost_snapshot=_Snapshot(month_to_date_total=21000.0),
        container_apps=[_app()],
    )
    text = result.describe()

    assert "[worked] Container health" in text
    assert "[recommend] Cost" in text
    assert "->" in text


# ---------------------------------------------------------------------------
# Every threshold in this module is a workbook panel's, not a new one
# ---------------------------------------------------------------------------

_WORKBOOK_DIR = _BE_ROOT.parents[1] / "infra" / "monitoring"


def _threshold_grid(workbook: str, item_name: str) -> list[dict]:
    document = json.loads((_WORKBOOK_DIR / workbook).read_text(encoding="utf-8"))
    for item in document["items"]:
        if item.get("name") == item_name:
            return (
                item["content"]["tileSettings"]["leftContent"]["formatOptions"]["thresholdsGrid"]
            )
    raise AssertionError(f"{item_name} is not in {workbook}")


def _band(grid: list[dict], representation: str) -> float:
    for row in grid:
        if row.get("representation") == representation and row.get("thresholdValue") not in (
            None,
            "-1",
        ):
            return float(row["thresholdValue"])
    raise AssertionError(f"no {representation} band in {grid}")


@pytest.mark.parametrize(
    "workbook, item, constant_red, constant_yellow",
    [
        (
            "cost_health_workbook.json",
            "container-status",
            rec.CPU_MEMORY_RED_PCT,
            rec.CPU_MEMORY_YELLOW_PCT,
        ),
        (
            "cost_health_workbook.json",
            "cost-trend-budget",
            rec.BUDGET_RED_PCT,
            rec.BUDGET_YELLOW_PCT,
        ),
        (
            "ai_control_tower_workbook.json",
            "d1-latest-pass-rate",
            rec.SCORE_BANDS["pass_rate"][0],
            rec.SCORE_BANDS["pass_rate"][1],
        ),
        (
            "ai_control_tower_workbook.json",
            "d2-faithfulness",
            rec.SCORE_BANDS["faithfulness"][0],
            rec.SCORE_BANDS["faithfulness"][1],
        ),
        (
            "ai_control_tower_workbook.json",
            "d4-cost-per-turn",
            rec.COST_PER_TURN_RED_USD,
            rec.COST_PER_TURN_YELLOW_USD,
        ),
        (
            "ai_control_tower_workbook.json",
            "e1-alert-recall",
            rec.ALERT_RECALL_RED_PCT,
            rec.ALERT_RECALL_YELLOW_PCT,
        ),
        (
            "ai_control_tower_workbook.json",
            "b1-error-rate",
            rec.TURN_ERROR_RED_PCT,
            rec.TURN_ERROR_YELLOW_PCT,
        ),
    ],
)
def test_each_band_is_still_the_live_panels_band(workbook, item, constant_red, constant_yellow):
    """If someone retunes a tile, this fails — which is the point. A
    recommendation that disagrees with the tile it was derived from is worse than
    no recommendation, and nothing else in the repo would notice the drift."""
    grid = _threshold_grid(workbook, item)

    assert _band(grid, "red") == constant_red
    assert _band(grid, "yellow") == constant_yellow


# ---------------------------------------------------------------------------
# The Track 1 → Track 2 handoff
# ---------------------------------------------------------------------------


@pytest.fixture
def handoff_file(tmp_path, monkeypatch):
    path = tmp_path / "extraction_benchmark_summary.json"
    monkeypatch.setenv(benchmark_artifacts.TRACK1_HANDOFF_ENV, str(path))
    return path


def test_the_handoff_round_trips_track_1s_summary(handoff_file):
    written = benchmark_artifacts.write_track1_handoff(
        _extraction_summary(recall=0.75), run_label="nightly"
    )

    assert written == str(handoff_file)
    assert benchmark_artifacts.read_track1_handoff(run_label="nightly")["confusion_matrix"][
        "recall"
    ] == 0.75


def test_a_stale_handoff_is_ignored_rather_than_graded_as_todays_run(handoff_file):
    """A leftover file from a previous night must never be read as this run's
    Track 1 result — reporting yesterday's recall as today's is the one failure
    mode worse than reporting none."""
    benchmark_artifacts.write_track1_handoff(
        _extraction_summary(),
        run_label="nightly",
        generated_at=datetime.now(timezone.utc) - timedelta(hours=25),
    )

    assert benchmark_artifacts.read_track1_handoff(run_label="nightly") is None


def test_a_handoff_from_a_different_cadence_is_ignored(handoff_file):
    benchmark_artifacts.write_track1_handoff(_extraction_summary(), run_label="predeploy")

    assert benchmark_artifacts.read_track1_handoff(run_label="nightly") is None
    assert benchmark_artifacts.read_track1_handoff(run_label="predeploy") is not None


def test_an_absent_or_corrupt_handoff_reads_as_none(handoff_file):
    assert benchmark_artifacts.read_track1_handoff() is None

    handoff_file.write_text("{not json", encoding="utf-8")
    assert benchmark_artifacts.read_track1_handoff() is None


def test_track_1_writes_the_handoff_even_under_no_write(handoff_file):
    """The nightly job runs Track 1 with `--no-write` (a job replica's filesystem
    is discarded), and the nightly job is exactly the caller that needs this — so
    the handoff must not sit behind that flag."""
    source = (_BE_ROOT / "scripts" / "run_extraction_benchmark.py").read_text(encoding="utf-8")
    write_at = source.index("write_track1_handoff(summary")
    no_write_at = source.index("if not args.no_write:")

    assert write_at > no_write_at
    assert "if not args.no_write" not in source[no_write_at + 40 : write_at]


# ---------------------------------------------------------------------------
# Gap 319 — the pass, mirrored to telemetry (one event per category per run)
# ---------------------------------------------------------------------------


def _mirrored(caplog):
    return [
        r for r in caplog.records if r.getMessage() == telemetry.OPS_RECOMMENDATION_EVENT_NAME
    ]


def _real_pass(**overrides) -> rec.RecommendationPass:
    """A real `run_recommendation_pass()` result — not a hand-built stub, because
    what the mirror has to survive is the shape that function actually returns."""
    kwargs = {
        "extraction_summary": _extraction_summary(),
        "cost_snapshot": _Snapshot(),
        "container_apps": [_app()],
        "generated_at": datetime(2026, 8, 25, 3, 47, tzinfo=timezone.utc),
    }
    payload = overrides.pop("payload", None) or _eval_payload()
    kwargs.update(overrides)
    return rec.run_recommendation_pass(payload, **kwargs)


def test_the_mirror_emits_one_event_per_category_never_one_per_run(caplog):
    """Three rows a night, not one row carrying three. A workbook grid is a flat
    row set and the panel's columns are `Category | Status | Explanation |
    Recommendation` — one row per category by construction. The same choice
    `online_eval_signal` makes (per signal, not per window)."""
    result = _real_pass()

    with caplog.at_level(logging.INFO):
        mirrored = rec.mirror_recommendation_pass(result)

    events = _mirrored(caplog)
    assert mirrored.events == 3 and mirrored.errors == []
    assert len(events) == 3
    assert [e.category for e in events] == list(rec.CATEGORY_ORDER)
    assert [e.title for e in events] == ["Container health", "Cost", "AI improvement"]
    assert {e.status for e in events} == {rec.STATUS_WORKED}


def test_every_row_of_one_run_carries_the_same_generated_at(caplog):
    """`generated_at` is the pass's own stamp, set once — so Gap 320's "latest
    run" filter is one `arg_max` over this stream and can never return two
    categories from one run and one from another. `TimeGenerated` is ingestion
    time and is deliberately not that key."""
    with caplog.at_level(logging.INFO):
        rec.mirror_recommendation_pass(_real_pass())

    stamps = {e.generated_at for e in _mirrored(caplog)}
    assert stamps == {"2026-08-25T03:47:00+00:00"}
    assert {e.run_label for e in _mirrored(caplog)} == {"nightly"}


def test_a_recommending_category_carries_its_findings_and_counts(caplog):
    """The verdict is the row, but the fields that produced it have to ride along
    — a reader must be able to answer "why" without opening the workbook."""
    result = _real_pass(payload=_eval_payload(faithfulness_mean=0.5, accuracy_mean=0.3))

    with caplog.at_level(logging.INFO):
        rec.mirror_recommendation_pass(result)

    ai = [e for e in _mirrored(caplog) if e.category == rec.CATEGORY_AI_IMPROVEMENT][0]
    assert ai.status == rec.STATUS_RECOMMEND
    assert ai.worst_severity == rec.SEVERITY_RED
    assert ai.recommendation
    findings = json.loads(ai.findings)
    assert {f["field"] for f in findings} == {"faithfulness", "accuracy"}
    assert ai.finding_count == 2 and ai.red_count == 2 and ai.yellow_count == 0
    assert ai.findings_omitted == 0


def test_a_no_data_category_mirrors_its_errors_rather_than_going_quiet(caplog):
    """A category that could not read its data is the single most important row
    to persist: two rows where three were expected reads as "health is fine"."""
    result = _real_pass(container_apps=[])

    with caplog.at_level(logging.INFO):
        rec.mirror_recommendation_pass(result)

    health = [e for e in _mirrored(caplog) if e.category == rec.CATEGORY_CONTAINER_HEALTH][0]
    assert health.status == rec.STATUS_NO_DATA
    assert health.worst_severity == ""
    assert health.findings == "[]"
    assert "Monitoring Reader" in health.explanation


def test_a_pathological_category_is_bounded_but_still_counted(caplog):
    """A health category over a large environment can produce a finding per app
    per metric. The event caps what it serialises and says how much it dropped;
    it never drops the count."""
    apps = [_app(f"ca-app-{i:03d}", cpu_pct=95.0, memory_pct=95.0) for i in range(120)]
    result = _real_pass(container_apps=apps)

    with caplog.at_level(logging.INFO):
        rec.mirror_recommendation_pass(result)

    health = [e for e in _mirrored(caplog) if e.category == rec.CATEGORY_CONTAINER_HEALTH][0]
    assert health.finding_count == 240  # 120 apps x (CPU + memory)
    assert len(health.findings) <= telemetry.MAX_RECOMMENDATION_FINDINGS_CHARS
    assert json.loads(health.findings)  # still parses
    assert health.findings_omitted > 0
    assert len(health.explanation) <= telemetry.MAX_RECOMMENDATION_TEXT_CHARS + 40


def test_a_telemetry_failure_is_reported_and_never_propagated(caplog, monkeypatch):
    """Fail-soft, for the reason the whole pass is: this runs at the very end of
    a nightly job that has already graded every turn and committed every row.
    Losing the mirror is acceptable; turning that execution red is not."""
    monkeypatch.setattr(
        telemetry, "track_ops_recommendation", MagicMock(side_effect=RuntimeError("exporter down"))
    )

    with caplog.at_level(logging.INFO):
        mirrored = rec.mirror_recommendation_pass(_real_pass())  # must not raise

    assert mirrored.events == 0
    assert "exporter down" in mirrored.errors[0]
    assert _mirrored(caplog) == []


def test_running_the_pass_emits_nothing_on_its_own(caplog):
    """The split matters: `run_recommendation_pass()` computes, the mirror
    persists. A developer's `python -c` — and every other test in this file —
    must not push rows at Application Insights."""
    with caplog.at_level(logging.INFO):
        _real_pass()

    assert _mirrored(caplog) == []
