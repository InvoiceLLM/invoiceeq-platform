"""Feature 20/23/24 — the nightly recommendation pass (Gap 318).

What this is
------------
`docs/feature_20_23_24_ops_workbook.md`, "Not yet built", item (a), and the two
decisions closed on 2026-08-25 above it:

    A step appended to the nightly job's own script (not a new scheduled
    resource): reads Track 1/2's just-produced eval results, queries current
    cost/health (reusing `azure_cost.py`), and for each of the three categories
    (container health, cost, AI improvement) either confirms "everything worked"
    or writes a recommendation.

**Check-and-flag, not a per-field dump.** The sample field-recommendation table
in that doc enumerates ~90 workbook fields; it is the *feasibility proof and the
judgement spec*, not the output schema. What one run emits is three category
verdicts, each carrying the individual field-level `Finding`s that produced it —
so a reader gets "cost: recommend, because X and Y" rather than 90 rows of
mostly-`NA`.

Where every threshold in this module comes from
-----------------------------------------------
Nothing here invents a second definition of "bad". Every band below is lifted
from the `formatter: 8` `thresholdsGrid` of the panel that already renders that
field on one of the two live workbooks, so a category that flags red here is
looking at a tile that is red there:

===============================  ======================================  ==========================
Field                            Panel (workbook JSON)                   Bands
===============================  ======================================  ==========================
CPU% / memory% per app           `container-status` (cost_health)        >=90 red, >=70 yellow
Running status                   `container-scale-config` (cost_health)  != "Running" red
Restarts, 24h                    `container-restarts` (cost_health)      >0 is the panel's filter
MTD spend % of budget            `cost-trend-budget` (cost_health)       >=100 red, >=80 yellow
Month-end forecast % of budget   `cost-trend-budget` (cost_health)       >=100 red, >=80 yellow
Golden-bank pass rate            `d1-latest-pass-rate` (control_tower)   <0.20 red, <0.30 yellow
Faithfulness                     `d2-faithfulness`                       <0.70 red, <0.85 yellow
Relevance                        `d2-relevance`                          <0.85 red, <0.95 yellow
Accuracy                         `d2-accuracy`                           <0.40 red, <0.55 yellow
Context                          `d3-context`                            <0.50 red, <0.70 yellow
Orchestration                    `d3-orchestration`                      <0.60 red, <0.80 yellow
Cost per turn (USD)              `d4-cost-per-turn`                      >=0.02 red, >=0.01 yellow
Alert recall %                   `e1-alert-recall`                       <80 red, <100 yellow
Clean false-positive rate %      `e1-fp-rate`                            >=20 red, >0 yellow
Turn error rate %                `b1-error-rate`                         >=5 red, >=2 yellow
===============================  ======================================  ==========================

Two fields the workbooks colour and this module deliberately does not judge:
**replica count** (`container-replicas` is blue by design — its own title says it
is "not compared against configured max here", so deciding min/max-replica
rightsizing here would be a new rule, not a reused one) and **persona score /
median turn latency** (`d3-persona`, `d4-median-latency`, both uncoloured on
purpose). Their values ride along in `metrics` so a later panel can show them
without this pass pretending to have graded them. The sample table's
"CPU persistently <20% → lower min replicas" row is likewise **not** implemented:
"persistently" is a trend judgement over days, and a 1-hour average cannot
support it. Those are stated here rather than quietly omitted.

The minimum-sample guard is the same one every coloured tile uses (n=20
turns/calls): a run that graded fewer turns than that reports
``STATUS_INSUFFICIENT_DATA`` with the real numbers still in `metrics`, exactly
like the workbook's `-1 → "n/a — see Detail"` sentinel. It never hides the number,
it declines to grade it.

Data sources — reused, not rebuilt
----------------------------------
* **Cost**: `services/azure_cost.py::collect_cost_snapshot()`. Nothing is
  re-queried and no second token chain exists. Note the two ratios are computed
  the way `cost-trend-budget`'s KQL computes them — spend% from the *snapshot's*
  `month_to_date_total` over `budget.amount`, forecast% from the *budget's* own
  `forecastSpend` over `budget.amount` — because a panel and a recommendation
  disagreeing about the same number is worse than either being slightly off.
* **Container health**: one Azure Resource Graph query for the apps and their
  `runningStatus` (the same `resources | where type =~ "microsoft.app/containerapps"`
  projection `container-scale-config` runs), then one Azure Monitor metrics read
  per app for CpuPercentage/MemoryPercentage/Replicas/RestartCount. Both go
  through `azure_cost.arm_request()`, which is exactly why that function was made
  public. The metrics read needs the **Monitoring Reader** grant that
  `infra/modules/security/rbac-assignments.bicep` declares and that has never
  been deployed — until it is, that half returns 403 and this category degrades
  to `no_data` with the error recorded, which is the honest answer and not a
  crash.
* **AI improvement**: Track 2's own just-computed payload (the dict
  `scripts/run_agent_eval.py` writes to `--out`), plus Track 1's summary handed
  over through `benchmark_artifacts.read_track1_handoff()`. Since 2026-08-26
  (Gap 307) that payload also carries a second summary bucket,
  `default-multiturn`, holding the multi-turn context-drift tier — read here by
  its own key and graded as its own finding, never averaged into the single-turn
  numbers (see `_multi_turn_stats()` and `CONTEXT_DRIFT_BAND_KEY`).

Fail-soft is a requirement here, not politeness
-----------------------------------------------
`run_recommendation_pass()` evaluates each category in its own try/except and
records the failure on that category. An unauthorized Resource Graph must not
delete the AI-quality verdict from the same run — a recommendation pass that
silently reports two categories instead of three reads as "nothing to say about
health", which is the single most dangerous thing this can do (the same rule
`CostSnapshot.errors` and the deleted digest's `DigestCollection.errors` were
built on).

What survives the run (Gap 319, 2026-08-25)
-------------------------------------------
`run_recommendation_pass()` still only *returns* a structure — it emits nothing
and writes nothing, so every test above it stays free of telemetry. Persistence
is one function further out: `mirror_recommendation_pass()` at the bottom of this
module turns the returned pass into **one `ops_recommendation` custom event per
category** (three a night), which is the only store a Workbook can read — it
cannot query Postgres. `scripts/run_agent_eval.py::recommendation_pass_step()`
calls it immediately after the pass, still nightly-only and still inside the
swallow-everything wrapper. Gap 320 renders those events as a panel.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from config import settings
from services.benchmark_artifacts import MULTI_TURN_PATH, RUN_LABEL_NIGHTLY, MirrorResult

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Vocabulary
# ---------------------------------------------------------------------------

CATEGORY_CONTAINER_HEALTH = "container_health"
CATEGORY_COST = "cost"
CATEGORY_AI_IMPROVEMENT = "ai_improvement"

#: Render order. Health first (an unhealthy container makes the other two
#: categories' numbers suspect), cost second, quality last — it carries the most
#: text, the same ordering the deleted digest arrived at.
CATEGORY_ORDER = (CATEGORY_CONTAINER_HEALTH, CATEGORY_COST, CATEGORY_AI_IMPROVEMENT)

CATEGORY_TITLES = {
    CATEGORY_CONTAINER_HEALTH: "Container health",
    CATEGORY_COST: "Cost",
    CATEGORY_AI_IMPROVEMENT: "AI improvement",
}

#: "Everything worked" — data was read, every field is inside its band.
STATUS_WORKED = "worked"
#: At least one field is outside its band; `recommendation` says what to do.
STATUS_RECOMMEND = "recommend"
#: The data could not be read at all (403, unconfigured scope, missing payload).
STATUS_NO_DATA = "no_data"
#: The data was read but the sample is below the workbooks' n=20 guard. Values
#: are reported, not graded — the `-1 → "n/a — see Detail"` sentinel in prose.
STATUS_INSUFFICIENT_DATA = "insufficient_data"

SEVERITY_RED = "red"
SEVERITY_YELLOW = "yellow"


# ---------------------------------------------------------------------------
# Thresholds — every one traced to a live workbook panel (see module docstring)
# ---------------------------------------------------------------------------

# `container-status`
CPU_MEMORY_RED_PCT = 90.0
CPU_MEMORY_YELLOW_PCT = 70.0
#: `container-scale-config` colours anything that is not exactly this red.
RUNNING_STATUS_HEALTHY = "Running"

# `cost-trend-budget` — the same grid colours both spend% and forecast%.
BUDGET_RED_PCT = 100.0
BUDGET_YELLOW_PCT = 80.0

# `d1`/`d2`/`d3`/`d4` — (red_below, yellow_below) on a 0-1 scale.
SCORE_BANDS: Dict[str, Tuple[float, float]] = {
    "pass_rate": (0.20, 0.30),
    "faithfulness": (0.70, 0.85),
    "relevance": (0.85, 0.95),
    "accuracy": (0.40, 0.55),
    "context": (0.50, 0.70),
    "orchestration": (0.60, 0.80),
}

#: Gap 307's `context_drift`, graded on **`d3-context`'s band** rather than on a
#: new pair of numbers. Two reasons, and the second is the one that matters:
#:
#:  1. Drift *is* a retrieval failure — "turn N is operating on the wrong rows
#:     given turns 1..N-1" is the same class of statement `context_score` makes
#:     about a single turn, so grading it on a different scale would be asserting
#:     a calibration nobody has measured.
#:  2. Every constant in this module is a live workbook panel's, and a test
#:     (`test_each_band_is_still_the_live_panels_band`) parses both workbook JSONs
#:     and fails if one drifts from the tile it mirrors. Inventing
#:     `CONTEXT_DRIFT_RED = 0.5` would be the first band here with no tile behind
#:     it. There is no drift tile today and adding one is a workbook deploy,
#:     which is deliberately outside Gap 307's scope.
#:
#: Deliberately NOT a new key in `SCORE_BANDS`: that dict is iterated to read
#: `stats["<key>_mean"]` out of the **`default`** bucket, and this dimension is
#: only ever scored in the `default-multiturn` one.
CONTEXT_DRIFT_BAND_KEY = "context"

#: `d4-cost-per-turn`, USD.
COST_PER_TURN_RED_USD = 0.02
COST_PER_TURN_YELLOW_USD = 0.01

# `e1-alert-recall` / `e1-fp-rate`, percentages.
ALERT_RECALL_RED_PCT = 80.0
ALERT_RECALL_YELLOW_PCT = 100.0
FALSE_POSITIVE_RED_PCT = 20.0

#: `b1-error-rate`. That tile measures production `chat_turn` traffic; the same
#: band is applied here to the eval run's own turn errors, because "what error
#: rate is bad" is a judgement this repo has already made once.
TURN_ERROR_RED_PCT = 5.0
TURN_ERROR_YELLOW_PCT = 2.0

#: The workbooks' minimum-sample guard, in graded turns. The nightly job runs 35
#: cases; the 5-case pre-deploy gate is below it, which is one more reason the
#: pass is nightly-only.
MIN_GRADED_TURNS = 20

#: Which soft metric points at which component. Lifted from the deleted digest's
#: `SOFT_METRIC_COMPONENT_HINTS` (git `bce9e38`) — the map itself is the whole
#: reason a quality recommendation is actionable rather than "quality dropped".
COMPONENT_HINTS = {
    "faithfulness": "retrieval/context — the answer asserted things the fetched context did not support",
    "relevance": "trace/routing — the question may be routing to the wrong path (RAG vs SQL vs CHAT)",
    "accuracy": "the golden set's reference answers, or a real regression against them",
    "context": "retrieval — which invoice records the tools fetched (deterministic, no judge)",
    "orchestration": "the tool-call chain and its arithmetic (deterministic, no judge)",
    "pass_rate": "the soft-metric map below — pass_rate is a roll-up, not a cause",
    # Gap 307. The hint names the two functions a drift finding is actually
    # actionable in, because "the conversation lost track" is not a place anyone
    # can go and look.
    "context_drift": (
        "multi-turn context — `get_chat_history()` / `get_prior_turn_sql()` in "
        "agents/query_agent.py, and the failing script's turn in the run artifact "
        "(the drift note names the leaked or lost entity)"
    ),
}


# ---------------------------------------------------------------------------
# Azure Resource Graph / Azure Monitor
# ---------------------------------------------------------------------------

RESOURCE_GRAPH_URL = (
    "https://management.azure.com/providers/Microsoft.ResourceGraph/resources"
    "?api-version=2022-10-01"
)

#: Azure Monitor metrics for one resource. The oldest GA version and the one
#: every `Microsoft.App/containerApps` metric definition is published under.
METRICS_API_VERSION = "2018-01-01"

#: The `container-scale-config` panel's own query, plus the id (needed to build
#: a metrics URL) and the configured scale bounds (reported as context, never
#: judged — see the module docstring).
ARG_CONTAINER_APPS_QUERY = """resources
| where type =~ "microsoft.app/containerapps" and resourceGroup =~ "{resource_group}"
| project name = tolower(tostring(name)),
          id,
          runningStatus = tostring(properties.runningStatus),
          minReplicas = toint(properties.template.scale.minReplicas),
          maxReplicas = toint(properties.template.scale.maxReplicas)
| order by name asc"""

#: The four metrics the three container panels read. `RestartCount` is a Total
#: aggregation, the other three are Averages — asked for in one call because the
#: metrics endpoint accepts a comma list and a per-metric call would be four
#: round trips per app for no extra information.
CONTAINER_METRIC_NAMES = ("CpuPercentage", "MemoryPercentage", "Replicas", "RestartCount")

#: `container-status`/`container-replicas` average over the last 1h;
#: `container-restarts` sums over 24h. One 24h/PT1H read serves both: the newest
#: bucket is the 1h average, the whole series is the 24h sum.
METRICS_WINDOW_HOURS = 24
METRICS_INTERVAL = "PT1H"


# ---------------------------------------------------------------------------
# Result shapes
# ---------------------------------------------------------------------------


@dataclass
class Finding:
    """One field that is outside its band, and what to do about it.

    `detail` always states the observed value *and* the threshold it crossed, so
    a rendered recommendation can be read without opening the workbook.
    """

    field: str
    value: Any
    severity: str
    detail: str
    recommendation: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "field": self.field,
            "value": self.value,
            "severity": self.severity,
            "detail": self.detail,
            "recommendation": self.recommendation,
        }


@dataclass
class CategoryRecommendation:
    """One category's verdict — the unit the Workbook panel renders (Gap 320).

    `recommendation` is empty exactly when `status == STATUS_WORKED`; the two are
    never both empty and never both populated, because "everything worked" and
    "here is what to do" are the only two outcomes the design allows for a
    category whose data was readable.
    """

    category: str
    status: str
    explanation: str
    recommendation: str = ""
    findings: List[Finding] = field(default_factory=list)
    metrics: Dict[str, Any] = field(default_factory=dict)
    errors: List[str] = field(default_factory=list)

    @property
    def title(self) -> str:
        return CATEGORY_TITLES.get(self.category, self.category)

    @property
    def worst_severity(self) -> Optional[str]:
        if any(f.severity == SEVERITY_RED for f in self.findings):
            return SEVERITY_RED
        if self.findings:
            return SEVERITY_YELLOW
        return None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "category": self.category,
            "title": self.title,
            "status": self.status,
            "explanation": self.explanation,
            "recommendation": self.recommendation,
            "worst_severity": self.worst_severity,
            "findings": [f.to_dict() for f in self.findings],
            "metrics": dict(self.metrics),
            "errors": list(self.errors),
        }


@dataclass
class RecommendationPass:
    """Everything one pass produced.

    Not persisted by the pass itself — `mirror_recommendation_pass()` below is
    what turns this into telemetry, so a run that only wants the verdict (a test,
    a developer's `python -c`) emits nothing.
    """

    run_label: str
    generated_at: datetime
    categories: List[CategoryRecommendation] = field(default_factory=list)

    def by_category(self, category: str) -> CategoryRecommendation:
        for entry in self.categories:
            if entry.category == category:
                return entry
        raise KeyError(category)

    @property
    def categories_recommending(self) -> List[CategoryRecommendation]:
        return [c for c in self.categories if c.status == STATUS_RECOMMEND]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "run_label": self.run_label,
            "generated_at": self.generated_at.isoformat(),
            "categories": [c.to_dict() for c in self.categories],
        }

    def describe(self) -> str:
        """One line per category, for the nightly job's stdout."""
        lines = []
        for entry in self.categories:
            lines.append(f"  [{entry.status}] {entry.title}: {entry.explanation}")
            if entry.recommendation:
                lines.append(f"      -> {entry.recommendation}")
            for problem in entry.errors:
                lines.append(f"      !  {problem}")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Shared banding helpers
# ---------------------------------------------------------------------------


def _severity_for_upper_bound(value: float, red_at: float, yellow_at: float) -> Optional[str]:
    """Bands where a *high* value is bad (CPU%, budget%, cost/turn, FP rate)."""
    if value >= red_at:
        return SEVERITY_RED
    if value >= yellow_at:
        return SEVERITY_YELLOW
    return None


def _severity_for_lower_bound(value: float, red_below: float, yellow_below: float) -> Optional[str]:
    """Bands where a *low* value is bad (quality scores, alert recall)."""
    if value < red_below:
        return SEVERITY_RED
    if value < yellow_below:
        return SEVERITY_YELLOW
    return None


def _as_float(raw: Any) -> Optional[float]:
    if raw is None:
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def _finalise(
    category: str,
    findings: List[Finding],
    *,
    worked_explanation: str,
    metrics: Dict[str, Any],
    errors: List[str],
) -> CategoryRecommendation:
    """Turn a category's findings into its verdict.

    One place, so the "worked ⇔ no recommendation text" invariant every category
    holds to cannot be re-implemented three different ways.
    """
    if not findings:
        return CategoryRecommendation(
            category=category,
            status=STATUS_WORKED,
            explanation=worked_explanation,
            metrics=metrics,
            errors=errors,
        )
    reds = [f for f in findings if f.severity == SEVERITY_RED]
    explanation = "; ".join(f.detail for f in findings)
    recommendation = " ".join(f.recommendation for f in findings)
    return CategoryRecommendation(
        category=category,
        status=STATUS_RECOMMEND,
        explanation=(
            f"{len(findings)} field(s) outside their workbook band"
            f"{f', {len(reds)} red' if reds else ''}: {explanation}"
        ),
        recommendation=recommendation,
        findings=findings,
        metrics=metrics,
        errors=errors,
    )


# ---------------------------------------------------------------------------
# Category 1 — container health
# ---------------------------------------------------------------------------


def _arg_rows(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Rows out of a Resource Graph response, in either result format.

    ``objectArray`` (the default the REST endpoint returns) gives ``data`` as a
    list of dicts; ``table`` gives ``columns``/``rows``. Same four lines the
    deleted digest collector used, for the same reason: a future caller passing
    ``resultFormat`` must not silently get zero rows.
    """
    data = payload.get("data")
    if isinstance(data, list):
        return [row for row in data if isinstance(row, dict)]
    if isinstance(data, dict):
        columns = [c.get("name") for c in (data.get("columns") or [])]
        return [dict(zip(columns, row)) for row in (data.get("rows") or [])]
    return []


def _metrics_url(resource_id: str, *, now: datetime) -> str:
    end = now.astimezone(timezone.utc)
    start = end - timedelta(hours=METRICS_WINDOW_HOURS)
    return (
        f"https://management.azure.com{resource_id}/providers/Microsoft.Insights/metrics"
        f"?api-version={METRICS_API_VERSION}"
        f"&metricnames={','.join(CONTAINER_METRIC_NAMES)}"
        f"&aggregation=average,total"
        f"&interval={METRICS_INTERVAL}"
        f"&timespan={start.strftime('%Y-%m-%dT%H:%M:%SZ')}/{end.strftime('%Y-%m-%dT%H:%M:%SZ')}"
    )


def parse_container_metrics(payload: Dict[str, Any]) -> Dict[str, Optional[float]]:
    """One app's metrics response → the four numbers the health panels show.

    * `CpuPercentage`/`MemoryPercentage`/`Replicas` — the **newest non-null**
      hourly average, i.e. `container-status`'s "last 1h average". Newest
      *non-null* rather than simply last, because Azure Monitor returns the
      in-flight bucket with null values for the first minutes of every hour and
      reading that as "no data" would blank the panel once an hour.
    * `RestartCount` — the sum of `total` across the whole 24h window, which is
      `container-restarts`'s `sum(Total)` over `ago(24h)`.
    """
    parsed: Dict[str, Optional[float]] = {name: None for name in CONTAINER_METRIC_NAMES}
    for metric in payload.get("value") or []:
        name = str(((metric or {}).get("name") or {}).get("value") or "")
        if name not in parsed:
            continue
        points: List[Dict[str, Any]] = []
        for series in metric.get("timeseries") or []:
            points.extend(series.get("data") or [])
        if name == "RestartCount":
            totals = [_as_float(p.get("total")) for p in points]
            present = [t for t in totals if t is not None]
            parsed[name] = float(sum(present)) if present else None
            continue
        latest: Optional[float] = None
        for point in points:
            value = _as_float(point.get("average"))
            if value is not None:
                latest = value
        parsed[name] = latest
    return parsed


def collect_container_health(
    *,
    subscription_id: Optional[str] = None,
    resource_group: Optional[str] = None,
    now: Optional[datetime] = None,
) -> Tuple[List[Dict[str, Any]], List[str]]:
    """``([{name, running_status, cpu_pct, memory_pct, replicas, restarts_24h}], errors)``.

    Never raises. One ARG call for the app inventory, then one metrics call per
    app; a metrics failure for one app costs that app's numbers and nothing else,
    because a single 403 on a chatty resource must not blank the whole category.
    """
    errors: List[str] = []
    subscription = (subscription_id or settings.AZURE_SUBSCRIPTION_ID or "").strip()
    group = (resource_group or settings.AZURE_COST_RESOURCE_GROUP or "").strip()
    if not subscription or not group:
        return [], [
            "container health: AZURE_SUBSCRIPTION_ID and AZURE_COST_RESOURCE_GROUP "
            "must both be set"
        ]

    # Imported here, not at module scope: `azure_cost` reads `config`, and this
    # module is imported by a standalone script and by the test suite with no
    # Azure configuration at all.
    from services.azure_cost import arm_request

    try:
        payload = arm_request(
            "POST",
            RESOURCE_GRAPH_URL,
            json_body={
                "subscriptions": [subscription],
                "query": ARG_CONTAINER_APPS_QUERY.format(resource_group=group),
            },
        )
    except Exception as exc:  # noqa: BLE001 - a broken health read is data, not a crash
        logger.warning("Recommendation pass: container inventory failed: %s", exc)
        return [], [f"container health: {type(exc).__name__}: {exc}"]

    apps: List[Dict[str, Any]] = []
    stamp = now or datetime.now(timezone.utc)
    for row in _arg_rows(payload):
        name = str(row.get("name") or "")
        resource_id = str(row.get("id") or "")
        app: Dict[str, Any] = {
            "name": name,
            "running_status": str(row.get("runningStatus") or ""),
            "min_replicas": row.get("minReplicas"),
            "max_replicas": row.get("maxReplicas"),
            "cpu_pct": None,
            "memory_pct": None,
            "replicas": None,
            "restarts_24h": None,
        }
        if resource_id:
            try:
                metrics = parse_container_metrics(
                    arm_request("GET", _metrics_url(resource_id, now=stamp))
                )
                app["cpu_pct"] = metrics["CpuPercentage"]
                app["memory_pct"] = metrics["MemoryPercentage"]
                app["replicas"] = metrics["Replicas"]
                app["restarts_24h"] = metrics["RestartCount"]
            except Exception as exc:  # noqa: BLE001 - see docstring
                logger.warning("Recommendation pass: metrics for %s failed: %s", name, exc)
                errors.append(f"container health: metrics for {name}: {type(exc).__name__}: {exc}")
        apps.append(app)
    return apps, errors


def evaluate_container_health(
    apps: Optional[List[Dict[str, Any]]] = None,
    *,
    errors: Optional[List[str]] = None,
    subscription_id: Optional[str] = None,
    resource_group: Optional[str] = None,
    now: Optional[datetime] = None,
) -> CategoryRecommendation:
    """Category 1. Pass `apps` to judge already-collected data, or omit to collect."""
    collected_errors = list(errors or [])
    if apps is None:
        apps, collect_errors = collect_container_health(
            subscription_id=subscription_id, resource_group=resource_group, now=now
        )
        collected_errors.extend(collect_errors)

    if not apps:
        return CategoryRecommendation(
            category=CATEGORY_CONTAINER_HEALTH,
            status=STATUS_NO_DATA,
            explanation=(
                "no container app data could be read — nothing was judged. "
                "The Monitoring Reader grant this needs is declared in "
                "rbac-assignments.bicep and has never been deployed."
            ),
            errors=collected_errors,
        )

    findings: List[Finding] = []
    for app in sorted(apps, key=lambda a: str(a.get("name") or "")):
        name = str(app.get("name") or "unnamed")
        status = str(app.get("running_status") or "")
        if status and status != RUNNING_STATUS_HEALTHY:
            findings.append(
                Finding(
                    field=f"{name} — running status",
                    value=status,
                    severity=SEVERITY_RED,
                    detail=f"{name} runningStatus is {status!r}, not {RUNNING_STATUS_HEALTHY!r}",
                    recommendation=(
                        f"Investigate why {name} is not running (revision/probe/startup "
                        "failure) before trusting any other figure from this run."
                    ),
                )
            )

        for key, label, advice in (
            (
                "cpu_pct",
                "CPU%",
                "review the scale rule's CPU threshold and the app's CPU limit",
            ),
            (
                "memory_pct",
                "memory%",
                "raise the memory limit or profile allocations — this is the OOM path",
            ),
        ):
            value = _as_float(app.get(key))
            if value is None:
                continue
            severity = _severity_for_upper_bound(
                value, CPU_MEMORY_RED_PCT, CPU_MEMORY_YELLOW_PCT
            )
            if severity:
                crossed = CPU_MEMORY_RED_PCT if severity == SEVERITY_RED else CPU_MEMORY_YELLOW_PCT
                findings.append(
                    Finding(
                        field=f"{name} — {label}",
                        value=round(value, 1),
                        severity=severity,
                        detail=f"{name} {label} is {value:.1f} (1h avg), at or above {crossed:.0f}",
                        recommendation=f"{name} {label} is {severity}: {advice}.",
                    )
                )

        restarts = _as_float(app.get("restarts_24h"))
        if restarts is not None and restarts > 0:
            findings.append(
                Finding(
                    field=f"{name} — restarts (24h)",
                    value=int(restarts),
                    severity=SEVERITY_YELLOW,
                    detail=f"{name} restarted {int(restarts)} time(s) in the last 24h",
                    recommendation=(
                        f"Check {name}'s crash logs and memory limit — the restart panel "
                        "shows a non-zero count, which is only ever deliberate after a deploy."
                    ),
                )
            )

    metrics = {
        "apps": apps,
        "app_count": len(apps),
        # Context only — `container-replicas` is uncoloured by design.
        "replica_counts": {
            str(a.get("name")): a.get("replicas") for a in apps if a.get("replicas") is not None
        },
    }
    return _finalise(
        CATEGORY_CONTAINER_HEALTH,
        findings,
        worked_explanation=(
            f"{len(apps)} container app(s) checked: all running, CPU/memory below "
            f"{CPU_MEMORY_YELLOW_PCT:.0f}% (1h avg), no restarts in 24h."
        ),
        metrics=metrics,
        errors=collected_errors,
    )


# ---------------------------------------------------------------------------
# Category 2 — cost
# ---------------------------------------------------------------------------


def evaluate_cost(snapshot: Optional[Any] = None) -> CategoryRecommendation:
    """Category 2. Pass a `CostSnapshot` to judge it, or omit to collect one.

    `snapshot.errors` is carried onto the category rather than raised — a budget
    read that lost a 429 race must not discard a perfectly good spend breakdown,
    which is the contract `collect_cost_snapshot()` already holds to.
    """
    errors: List[str] = []
    if snapshot is None:
        from services import azure_cost

        if not azure_cost.is_configured():
            return CategoryRecommendation(
                category=CATEGORY_COST,
                status=STATUS_NO_DATA,
                explanation=(
                    "cost is not configured (AZURE_SUBSCRIPTION_ID / "
                    "AZURE_COST_RESOURCE_GROUP) — nothing was judged."
                ),
                errors=["cost: scope is not configured"],
            )
        try:
            snapshot = azure_cost.collect_cost_snapshot()
        except Exception as exc:  # noqa: BLE001 - a broken cost read is data, not a crash
            logger.warning("Recommendation pass: cost collection failed: %s", exc)
            return CategoryRecommendation(
                category=CATEGORY_COST,
                status=STATUS_NO_DATA,
                explanation="the Cost Management API could not be read — nothing was judged.",
                errors=[f"cost: {type(exc).__name__}: {exc}"],
            )

    errors.extend(getattr(snapshot, "errors", None) or [])
    budget = getattr(snapshot, "budget", None)
    currency = getattr(snapshot, "currency", "") or ""
    month_to_date = _as_float(getattr(snapshot, "month_to_date_total", None)) or 0.0
    by_service = list(getattr(snapshot, "by_service", None) or [])
    top_service = by_service[0] if by_service else None

    metrics: Dict[str, Any] = {
        "currency": currency,
        "month_to_date_total": round(month_to_date, 2),
        "budget_amount": _as_float(getattr(budget, "amount", None)),
        "budget_forecast_spend": _as_float(getattr(budget, "forecast_spend", None)),
        "top_service": getattr(top_service, "name", None),
        "top_service_amount": (
            round(_as_float(getattr(top_service, "amount", 0.0)) or 0.0, 2) if top_service else None
        ),
        "day_over_day_change_pct": getattr(snapshot, "day_over_day_change_pct", None),
    }

    budget_amount = _as_float(getattr(budget, "amount", None)) or 0.0
    if not budget_amount:
        return CategoryRecommendation(
            category=CATEGORY_COST,
            status=STATUS_NO_DATA,
            explanation=(
                f"spend read ({currency} {month_to_date:.2f} month-to-date) but no budget "
                "resource was returned, so there is nothing to judge it against."
            ),
            metrics=metrics,
            errors=errors or ["cost: no budget resource at this scope"],
        )

    # Computed exactly as `cost-trend-budget`'s KQL computes them, from the same
    # two source fields, so the tile and this recommendation cannot disagree.
    spend_pct = round(100.0 * month_to_date / budget_amount, 1)
    forecast_spend = _as_float(getattr(budget, "forecast_spend", None)) or 0.0
    forecast_pct = round(100.0 * forecast_spend / budget_amount, 1)
    metrics["spend_pct_of_budget"] = spend_pct
    metrics["forecast_pct_of_budget"] = forecast_pct

    driver = (
        f" Largest line is {metrics['top_service']} at {currency} "
        f"{metrics['top_service_amount']} month-to-date — start there."
        if top_service
        else ""
    )

    findings: List[Finding] = []
    for label, value, advice in (
        (
            "MTD spend % of budget",
            spend_pct,
            "Month-to-date spend has already crossed its budget band; review the "
            "top-spend services for rightsizing.",
        ),
        (
            "Month-end forecast % of budget",
            forecast_pct,
            "The month-end projection crosses the budget band; do the cost review "
            "before month end, not after.",
        ),
    ):
        severity = _severity_for_upper_bound(value, BUDGET_RED_PCT, BUDGET_YELLOW_PCT)
        if severity:
            crossed = BUDGET_RED_PCT if severity == SEVERITY_RED else BUDGET_YELLOW_PCT
            findings.append(
                Finding(
                    field=label,
                    value=value,
                    severity=severity,
                    detail=f"{label} is {value:.1f}%, at or above {crossed:.0f}%",
                    recommendation=f"{advice}{driver}",
                )
            )

    return _finalise(
        CATEGORY_COST,
        findings,
        worked_explanation=(
            f"{currency} {month_to_date:.2f} month-to-date = {spend_pct:.1f}% of budget, "
            f"month-end forecast {forecast_pct:.1f}% — both below {BUDGET_YELLOW_PCT:.0f}%."
        ),
        metrics=metrics,
        errors=errors,
    )


# ---------------------------------------------------------------------------
# Category 3 — AI improvement
# ---------------------------------------------------------------------------


def _agent_eval_stats(payload: Dict[str, Any]) -> Tuple[str, Dict[str, Any]]:
    """The path this run measured, and its summary block.

    `summarise()` keys its output by path. `default` has been the only path since
    Gap 316 deleted SAGE, but a multi-path payload is still a legal shape, so the
    path is *chosen* (preferring `default`) and named in the output rather than
    averaged away.

    Gap 307: `MULTI_TURN_PATH` is excluded from that choice outright. It is a
    bucket in the same dict but not a candidate for "the path this run measured"
    — a run that produced only the drift tier (`--cases <script id>`) would
    otherwise have its 12 harder turns graded against every `SCORE_BANDS`
    threshold as though they were the 35-case baseline.
    """
    summary = payload.get("summary") or {}
    if not isinstance(summary, dict) or not summary:
        return "", {}
    if "default" in summary:
        return "default", summary.get("default") or {}
    candidates = sorted(key for key in summary if key != MULTI_TURN_PATH)
    if not candidates:
        return "", {}
    path = candidates[0]
    return str(path), summary.get(path) or {}


def _multi_turn_stats(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Gap 307's drift bucket out of the same payload, or `{}` if the tier did not run.

    Read by its own key rather than through `_agent_eval_stats()` on purpose:
    that function *chooses* one path and would return the drift bucket on a run
    where the single-turn tier was skipped, which would then be graded against
    `SCORE_BANDS` as if it were the baseline. These are two populations and the
    module never averages them.
    """
    summary = payload.get("summary") or {}
    if not isinstance(summary, dict):
        return {}
    return summary.get(MULTI_TURN_PATH) or {}


def evaluate_ai_improvement(
    agent_eval_payload: Optional[Dict[str, Any]] = None,
    extraction_summary: Optional[Dict[str, Any]] = None,
) -> CategoryRecommendation:
    """Category 3 — Track 2's just-graded turns plus Track 1's just-run benchmark.

    Track 1 is optional and its absence is stated, not silently treated as a
    pass: the two tracks are separate processes in the nightly job's `&&` chain,
    so Track 2 only has Track 1's numbers if the handoff file was written.

    Gap 307's multi-turn context-drift tier is graded here too, from the same
    payload's `default-multiturn` bucket, and is **not** folded into the
    single-turn numbers: it is a smaller and deliberately harder population, so
    its mean rides its own finding while every existing band keeps reading the
    `default` bucket it always read. A run where the tier did not run (or was
    skipped with `--no-multi-turn`) records that on `errors` and grades
    everything else, the same way a missing Track 1 handoff does.
    """
    errors: List[str] = []
    payload = agent_eval_payload or {}
    path, stats = _agent_eval_stats(payload)
    turns = int(_as_float(stats.get("turns")) or 0)

    metrics: Dict[str, Any] = {
        "path": path,
        "turns": turns,
        "errors": int(_as_float(stats.get("errors")) or 0),
        "judge_mode": payload.get("judge_mode"),
        "model_under_test": payload.get("model_under_test"),
        # Uncoloured on the workbook by design — carried, never judged.
        "persona_mean": stats.get("persona_mean"),
        "latency_ms_median": stats.get("latency_ms_median"),
        "extraction_supplied": bool(extraction_summary),
    }
    for key in SCORE_BANDS:
        metrics[key] = stats.get("pass_rate") if key == "pass_rate" else stats.get(f"{key}_mean")
    metrics["cost_per_turn_usd"] = stats.get("cost_per_turn_usd")

    findings: List[Finding] = []

    # --- Track 1, extraction & alerts -------------------------------------
    matrix = (extraction_summary or {}).get("confusion_matrix") or {}
    field_accuracy = (extraction_summary or {}).get("field_accuracy") or {}
    if extraction_summary:
        metrics["extraction_mode"] = extraction_summary.get("mode")
        metrics["field_accuracy_pct"] = (
            round((_as_float(field_accuracy.get("ratio")) or 0.0) * 100.0, 2)
            if field_accuracy.get("ratio") is not None
            else None
        )
        recall = _as_float(matrix.get("recall"))
        if recall is not None:
            recall_pct = round(recall * 100.0, 2)
            metrics["alert_recall_pct"] = recall_pct
            severity = _severity_for_lower_bound(
                recall_pct, ALERT_RECALL_RED_PCT, ALERT_RECALL_YELLOW_PCT
            )
            if severity:
                findings.append(
                    Finding(
                        field="Alert recall %",
                        value=recall_pct,
                        severity=severity,
                        detail=(
                            f"extraction alert recall is {recall_pct:.2f}%, below "
                            f"{ALERT_RECALL_RED_PCT if severity == SEVERITY_RED else ALERT_RECALL_YELLOW_PCT:.0f}%"
                        ),
                        recommendation=(
                            "Review the extraction alert rules against this run's missed "
                            f"cases ({len(extraction_summary.get('missed_cases') or [])} missed) — "
                            "a miss is an invoice problem that reached a customer unflagged."
                        ),
                    )
                )
        fp_rate = _as_float(matrix.get("false_positive_rate"))
        if fp_rate is not None:
            fp_pct = round(fp_rate * 100.0, 2)
            metrics["clean_false_positive_rate_pct"] = fp_pct
            severity = (
                SEVERITY_RED
                if fp_pct >= FALSE_POSITIVE_RED_PCT
                else (SEVERITY_YELLOW if fp_pct > 0 else None)
            )
            if severity:
                findings.append(
                    Finding(
                        field="Clean false-positive rate %",
                        value=fp_pct,
                        severity=severity,
                        detail=f"clean documents false-positived at {fp_pct:.2f}%",
                        recommendation=(
                            "Tighten the alert rules that fired on clean documents — every "
                            "false positive costs a human review of a correct invoice."
                        ),
                    )
                )
    else:
        errors.append(
            "ai improvement: no Track 1 (extraction benchmark) summary was handed over; "
            "recall / false-positive rate were not judged this run"
        )

    # --- Gap 307, multi-turn context drift ---------------------------------
    # Graded before the Track 2 guards below, deliberately: a run whose
    # single-turn summary is missing still has a drift verdict worth keeping,
    # and both early returns carry `findings` through.
    drift_stats = _multi_turn_stats(payload)
    drift_turns = int(_as_float(drift_stats.get("context_drift_scored_turns")) or 0)
    drift_mean = _as_float(drift_stats.get("context_drift_mean"))
    metrics["context_drift_turns"] = drift_turns
    metrics["context_drift_mean"] = drift_mean
    if not drift_stats:
        errors.append(
            "ai improvement: the multi-turn context-drift tier did not run "
            f"(no {MULTI_TURN_PATH!r} bucket in this run's summary); drift was not judged"
        )
    elif drift_mean is None or not drift_turns:
        errors.append(
            "ai improvement: the multi-turn tier ran but scored no drift turn — "
            "every script's expectations were skipped or unscoreable"
        )
    else:
        # No n=20 guard on this one, and that is not an oversight. The guard
        # exists because a *rate* over a small sample is noise; this is a fixed,
        # exhaustive, deterministic script set — the same handful of pinned
        # checks every night, with no sampling error to guard against. A drop
        # here means one named check failed, and the note says which.
        red_below, yellow_below = SCORE_BANDS[CONTEXT_DRIFT_BAND_KEY]
        severity = _severity_for_lower_bound(drift_mean, red_below, yellow_below)
        if severity:
            crossed = red_below if severity == SEVERITY_RED else yellow_below
            findings.append(
                Finding(
                    field="context_drift",
                    value=round(drift_mean, 4),
                    severity=severity,
                    detail=(
                        f"context drift is {drift_mean:.3f} over {drift_turns} scored "
                        f"multi-turn turn(s), below {crossed:.2f} "
                        f"(graded on `d3-context`'s band — see CONTEXT_DRIFT_BAND_KEY)"
                    ),
                    recommendation=(
                        "A multi-turn script lost or kept the wrong subject — look at "
                        f"{COMPONENT_HINTS['context_drift']}."
                    ),
                )
            )

    # --- Track 2, chat quality --------------------------------------------
    if not stats:
        return CategoryRecommendation(
            category=CATEGORY_AI_IMPROVEMENT,
            status=STATUS_NO_DATA,
            explanation="no Track 2 eval summary was produced — nothing was judged.",
            findings=findings,
            metrics=metrics,
            errors=errors + ["ai improvement: agent-eval payload carried no summary"],
        )

    if turns < MIN_GRADED_TURNS:
        return CategoryRecommendation(
            category=CATEGORY_AI_IMPROVEMENT,
            status=STATUS_INSUFFICIENT_DATA,
            explanation=(
                f"only {turns} graded turn(s) on path {path!r}, below the workbooks' "
                f"n={MIN_GRADED_TURNS} minimum-sample guard — values recorded, not graded "
                f"(pass_rate={stats.get('pass_rate')})."
            ),
            findings=findings,
            metrics=metrics,
            errors=errors,
        )

    for key, (red_below, yellow_below) in SCORE_BANDS.items():
        value = _as_float(
            stats.get("pass_rate") if key == "pass_rate" else stats.get(f"{key}_mean")
        )
        if value is None:
            continue
        severity = _severity_for_lower_bound(value, red_below, yellow_below)
        if severity:
            crossed = red_below if severity == SEVERITY_RED else yellow_below
            findings.append(
                Finding(
                    field=key,
                    value=round(value, 4),
                    severity=severity,
                    detail=f"{key} is {value:.3f}, below {crossed:.2f}",
                    recommendation=(
                        f"{key} is {severity} over {turns} turns — look at "
                        f"{COMPONENT_HINTS.get(key, 'the golden-bank run artifact')}."
                    ),
                )
            )

    cost_per_turn = _as_float(stats.get("cost_per_turn_usd"))
    if cost_per_turn is not None:
        severity = _severity_for_upper_bound(
            cost_per_turn, COST_PER_TURN_RED_USD, COST_PER_TURN_YELLOW_USD
        )
        if severity:
            crossed = (
                COST_PER_TURN_RED_USD if severity == SEVERITY_RED else COST_PER_TURN_YELLOW_USD
            )
            findings.append(
                Finding(
                    field="cost_per_turn_usd",
                    value=cost_per_turn,
                    severity=severity,
                    detail=f"cost per turn is ${cost_per_turn:.5f}, at or above ${crossed:.2f}",
                    recommendation=(
                        "Review prompt length and per-call-site token attribution "
                        "(`tokens_by_agent` in the run artifact) before the model choice — "
                        "the cheapest fix is usually context, not a smaller model."
                    ),
                )
            )

    turn_errors = int(_as_float(stats.get("errors")) or 0)
    if turns and turn_errors:
        error_pct = round(100.0 * turn_errors / turns, 2)
        metrics["turn_error_rate_pct"] = error_pct
        severity = _severity_for_upper_bound(error_pct, TURN_ERROR_RED_PCT, TURN_ERROR_YELLOW_PCT)
        if severity:
            findings.append(
                Finding(
                    field="turn error rate %",
                    value=error_pct,
                    severity=severity,
                    detail=f"{turn_errors} of {turns} graded turns errored ({error_pct:.2f}%)",
                    recommendation=(
                        "Read the errored turns in this run's artifact blob — a harness "
                        "error and a model failure look identical in the pass rate."
                    ),
                )
            )

    worked = (
        f"{turns} graded turn(s) on path {path!r}: pass rate {stats.get('pass_rate')}, "
        "every scored dimension inside its workbook band"
    )
    if drift_mean is not None and drift_turns:
        worked += (
            f"; context drift {drift_mean:.3f} over {drift_turns} multi-turn turn(s)"
        )
    if extraction_summary:
        worked += (
            f"; extraction recall {metrics.get('alert_recall_pct')}%, "
            f"clean FP rate {metrics.get('clean_false_positive_rate_pct')}%"
        )
    return _finalise(
        CATEGORY_AI_IMPROVEMENT,
        findings,
        worked_explanation=worked + ".",
        metrics=metrics,
        errors=errors,
    )


# ---------------------------------------------------------------------------
# The pass
# ---------------------------------------------------------------------------


def run_recommendation_pass(
    agent_eval_payload: Optional[Dict[str, Any]] = None,
    *,
    extraction_summary: Optional[Dict[str, Any]] = None,
    run_label: str = RUN_LABEL_NIGHTLY,
    generated_at: Optional[datetime] = None,
    cost_snapshot: Optional[Any] = None,
    container_apps: Optional[List[Dict[str, Any]]] = None,
) -> RecommendationPass:
    """All three categories, each isolated from the others' failures.

    Never raises. A category whose evaluator blows up becomes a `no_data` row
    carrying the exception text — because two categories reported where three
    were expected reads as "nothing to say", and this pass exists precisely to
    stop that being the default state of ops visibility here.
    """
    result = RecommendationPass(
        run_label=run_label,
        generated_at=generated_at or datetime.now(timezone.utc),
    )

    evaluators = (
        (
            CATEGORY_CONTAINER_HEALTH,
            lambda: evaluate_container_health(container_apps),
        ),
        (CATEGORY_COST, lambda: evaluate_cost(cost_snapshot)),
        (
            CATEGORY_AI_IMPROVEMENT,
            lambda: evaluate_ai_improvement(agent_eval_payload, extraction_summary),
        ),
    )
    for category, evaluate in evaluators:
        try:
            result.categories.append(evaluate())
        except Exception as exc:  # noqa: BLE001 - see docstring
            logger.warning("Recommendation pass: %s failed", category, exc_info=True)
            result.categories.append(
                CategoryRecommendation(
                    category=category,
                    status=STATUS_NO_DATA,
                    explanation=f"{CATEGORY_TITLES[category]} could not be evaluated this run.",
                    errors=[f"{category}: {type(exc).__name__}: {exc}"],
                )
            )
    return result


# ---------------------------------------------------------------------------
# Persistence — one custom event per category (Gap 319)
# ---------------------------------------------------------------------------


def mirror_recommendation_pass(result: RecommendationPass) -> MirrorResult:
    """Mirror one pass to telemetry: one ``ops_recommendation`` event per category.

    The only way a verdict survives the run that produced it. A Workbook cannot
    query Postgres, so the recommendation has to exist as a custom event for
    Gap 320's panel to render it — the same reason `agent_eval_run` and
    `online_eval_signal` are mirrored, stated at
    `telemetry.OPS_RECOMMENDATION_EVENT_NAME`.

    **Three events, not one.** A workbook grid is a flat row set and the panel's
    columns are `Category | Status | Explanation | Recommendation`, i.e. one row
    per category already. One event carrying a nested three-element array would
    force every query to `mv-expand` before it could filter or colour on
    `status`, which is exactly the shape `online_eval_signal` avoided by
    emitting per signal rather than per window.

    All three carry the *same* `generated_at`, taken from the pass rather than
    from each emission, so "the latest run" is one `arg_max` over this stream and
    can never mix two runs' categories.

    `metrics` is deliberately not mirrored — see the event's own docs. Everything
    else on `CategoryRecommendation.to_dict()` is.

    Never raises, and returns a `MirrorResult` rather than logging-and-forgetting,
    for the same reason the two benchmark mirrors do: the nightly job prints what
    the mirror actually managed, instead of a reassuring line that may not be
    true (the Gap 292/309 silent-no-op class).
    """
    from telemetry import track_ops_recommendation

    mirror = MirrorResult()
    try:
        # `timespec="seconds"` matches `mirror_extraction_run` /
        # `mirror_agent_eval_run`; the value is computed once here so the three
        # rows of one run are byte-identical on this field.
        generated_at = result.generated_at.isoformat(timespec="seconds")
        for entry in result.categories:
            payload = entry.to_dict()
            track_ops_recommendation(
                category=payload["category"],
                title=payload["title"],
                status=payload["status"],
                explanation=payload["explanation"],
                recommendation=payload["recommendation"],
                # None means "no findings", which the event carries as "" — a
                # real answer, not missing data.
                worst_severity=payload["worst_severity"] or "",
                findings=payload["findings"],
                errors=payload["errors"],
                run_label=result.run_label,
                generated_at=generated_at,
            )
            mirror.events += 1
    except Exception as exc:  # pragma: no cover - the emitter itself never raises
        mirror.errors.append(f"telemetry mirror failed ({type(exc).__name__}: {exc})")
        logger.warning("Recommendation pass telemetry mirror failed", exc_info=True)
    return mirror


__all__ = [
    "CATEGORY_AI_IMPROVEMENT",
    "CATEGORY_CONTAINER_HEALTH",
    "CATEGORY_COST",
    "CATEGORY_ORDER",
    "CategoryRecommendation",
    "Finding",
    "RecommendationPass",
    "STATUS_INSUFFICIENT_DATA",
    "STATUS_NO_DATA",
    "STATUS_RECOMMEND",
    "STATUS_WORKED",
    "collect_container_health",
    "evaluate_ai_improvement",
    "evaluate_container_health",
    "evaluate_cost",
    "mirror_recommendation_pass",
    "parse_container_metrics",
    "run_recommendation_pass",
]
