"""Feature 24 (Ops Digest Agent) — the collection step.

What this module does, and what it deliberately does not
--------------------------------------------------------
It answers one question: *what changed since the last digest run?* It turns
three independent sources into one flat list of `DigestItem`s, each carrying a
`Signal` in exactly the shape `services/ops_digest_routing.py::classify()`
already expects. It does **not** classify, summarise, or deliver anything —
those are `services/ops_digest.py` and `services/ops_digest_delivery.py`. The
split is deliberate: collection talks to the network and the database and is the
part that fails in interesting ways, so it is testable on its own without an LLM
anywhere near it.

The three sources
-----------------
1. **Azure Monitor alerts that fired** — Azure Resource Graph over
   ``alertsmanagementresources``, the same table (and the same
   ``properties.essentials.*`` projection) that the Feature 23 workbook's alert
   panels were validated against live. Reached through
   ``azure_cost.arm_request()`` so there is one managed-identity/CLI token chain
   in this codebase, not two.

   **Four things about the real response shape, checked live against
   subscription ``2ae37d8b-…`` on 2026-08-23 rather than assumed** — the first
   three contradict what the workbook query's column names imply:

   * ``properties.essentials.alertRule`` is the **full resource ID** of the rule
     (``/subscriptions/…/metricAlerts/alert-ca-invoice-be-dev-memory-high``), not
     a friendly name. ``rule_display_name()`` takes the last segment.
   * ``severity`` is the string ``"Sev2"``, not the integer ``2``.
   * ``monitorConditionResolvedDateTime`` is ``""`` (empty string, not null)
     while an alert is still firing.
   * ``alertState`` (``New``/``Acknowledged``/``Closed``) is *not* whether the
     alert is over — that is ``monitorCondition`` (``Fired``/``Resolved``). A
     real live row has ``monitorCondition: Resolved`` and ``alertState: New``
     simultaneously, because nobody ever clicked "close" in the portal. The
     self-resolved test therefore reads ``monitorCondition``.

   **Where `action_group` comes from.** ARG does not return which action group a
   fired alert notified, so it is derived from severity: Sev 0/1 → ``critical``,
   Sev 2/3 → ``info``. That is not a guess — every one of the 16 rules in
   ``infra/modules/monitoring/alert-rules.bicep`` was read one by one and the
   mapping holds without exception (Sev 1 restart-loop/5xx/PG-storage/DLQ/KV →
   ``criticalActionGroupId``; Sev 2/3 CPU/memory/connections/Redis/availability/
   egress/AI-client-errors → ``infoActionGroupId``; the CAE resource-health
   activity-log alert carries no severity field and is always critical, so it is
   special-cased by name). `classify()`'s contract is to *trust* the alert's own
   action-group assignment; this function reconstructs that assignment from the
   only field ARG actually returns.

2. **Azure cost** — ``services/azure_cost.py::collect_cost_snapshot()``, already
   built and verified live. Nothing is re-queried here.

3. **AI-eval findings** — read from **Postgres** (`agent_eval_run`), not from the
   Application Insights ``agent_eval_run`` / ``online_eval_signal`` custom
   events, and the reason is worth stating because the task framing pointed at
   the telemetry: those events are a *mirror* of the Postgres rows written for
   the benefit of Azure Workbooks (which cannot query Postgres —
   ``telemetry.py``'s own comment says exactly this). This agent runs *inside*
   this codebase with a live DB session, so reading the mirror instead of the
   record would add a Log Analytics dependency, a KQL round-trip and an
   ingestion delay to get strictly less data. Gap 292's `AppRequests` fix is
   real but orthogonal — it restored *request* telemetry, and is not deployed to
   any container yet in any case.

   Online-eval signals come from ``services/online_eval_signals.py::
   compute_online_signals()``, which is also pure SQL over Postgres.

Honest limitations, carried forward rather than papered over
------------------------------------------------------------
* **The full-outage exception has no data source, and this module does not
  invent one.** `classify()` documents that nothing computes "0 of N replicas
  running"; that is still true. No collector here emits `replica_count` /
  `expected_min_replicas`, so that exception stays dormant exactly as the
  routing module says it is. The nearest real signal that exists today is the
  CAE resource-health alert (`alert-cae-…-resource-health`), which is a
  different thing — the whole environment being unavailable, not one app's
  replicas — and it already routes critical on its own.
* **Budget-breach items default to off.** Gap 295: `budget-invoicellm-dev` is
  denominated in INR while its amount (150) was set as if it were USD, so the
  budget has been in a permanently-breached state (≈10,935% actual) for as long
  as it has existed. Emitting a budget item every run would put a guaranteed,
  meaningless line in every single digest from day one. ``include_budget_items``
  is therefore False by default with `OPS_DIGEST_BUDGET_ITEMS` as the override —
  flip it once the budget is denominated correctly, which is a founder decision
  and not something to guess at here.
* **`audit_job_failed` needs a baseline to fire at all.** The named exception is
  "the audit/benchmark job itself failing to run", and the naive implementation —
  "no eval rows in this window" — would fire on literally every run today,
  because Feature 23's nightly eval job was deleted on 2026-08-23 and nothing
  currently schedules one. So it only fires when the *baseline* window had runs
  and the current window has none, i.e. a job that was running and stopped. A
  job that has never run is not a silent failure, it is an unbuilt job.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from config import settings
from services.ops_digest_routing import Signal

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Areas — the three the feature doc names, kept as constants so the renderer
# and the LLM prompt cannot drift from the collectors.
# ---------------------------------------------------------------------------

AREA_COST = "cost"
AREA_HEALTH = "health"
AREA_AI_EVAL = "ai_eval"

AREA_TITLES = {
    AREA_COST: "Cost",
    AREA_HEALTH: "Health / performance",
    AREA_AI_EVAL: "AI quality",
}

#: Order the digest renders areas in. Cost first because it is the shortest and
#: most often empty; AI quality last because its items carry the most text.
AREA_ORDER = (AREA_COST, AREA_HEALTH, AREA_AI_EVAL)


# ---------------------------------------------------------------------------
# Azure Resource Graph
# ---------------------------------------------------------------------------

RESOURCE_GRAPH_URL = (
    "https://management.azure.com/providers/Microsoft.ResourceGraph/resources"
    "?api-version=2022-10-01"
)

#: Lifted from the Feature 23 workbook's alert-timeline query (git `b3233d9`),
#: which was executed live against this subscription before it was filed — so
#: the projection is known to parse, rather than being written from the docs.
#: Extended here with `monitorConditionResolvedDateTime` (needed to tell a
#: fired-and-self-resolved alert from one still firing) and `description`.
ARG_ALERTS_QUERY = """alertsmanagementresources
| where type =~ 'microsoft.alertsmanagement/alerts'
| extend fired = todatetime(properties.essentials.startDateTime),
         sev = tostring(properties.essentials.severity),
         alertState = tostring(properties.essentials.alertState),
         monitorCondition = tostring(properties.essentials.monitorCondition),
         rule = tostring(properties.essentials.alertRule),
         target = tostring(properties.essentials.targetResourceName),
         targetType = tostring(properties.essentials.targetResourceType),
         monitorService = tostring(properties.essentials.monitorService),
         resolvedAt = tostring(properties.essentials.monitorConditionResolvedDateTime),
         description = tostring(properties.essentials.description)
| where fired > todatetime('{window_start}')
| project fired, sev, alertState, monitorCondition, rule, target, targetType,
          monitorService, resolvedAt, description, resourceGroup, name
| order by fired desc
| limit {limit}"""

#: A digest that tried to analyse 500 alerts would be useless and would blow the
#: LLM prompt budget. The window is 6 hours; more than 200 alerts in 6 hours is
#: itself the finding, and the count is reported even when the list is truncated.
ARG_ALERT_LIMIT = 200

#: The one alert rule that carries no `severity` field at all (it is an
#: `activityLogAlerts` resource, not a `metricAlerts`/`scheduledQueryRules` one)
#: and is wired to the critical action group unconditionally in alert-rules.bicep.
_ALWAYS_CRITICAL_RULE_SUFFIX = "-resource-health"


# ---------------------------------------------------------------------------
# Thresholds — module constants, not settings, following the precedent in
# `services/online_eval_signals.py`. These are judgements about the data, not
# per-deployment configuration.
# ---------------------------------------------------------------------------

#: Absolute drop in a 0-1 quality metric that counts as a *cliff* rather than
#: drift. `classify()` pages on a sharp drop and digests a gradual one, so this
#: number is the only thing standing between "quality moved" and "wake someone".
#: 0.20 on a 0-1 scale is a fifth of the whole range — large enough that it
#: cannot be judge noise on a sample of `MIN_EVAL_RUNS_FOR_COMPARISON` turns.
SHARP_DROP_THRESHOLD = 0.20

#: Below this, a metric moving is not reported at all. Between this and
#: SHARP_DROP_THRESHOLD it is reported as drift, in the digest.
DRIFT_DROP_THRESHOLD = 0.05

#: Both windows need at least this many scored runs before their means are
#: compared. Two turns against three turns is not a trend.
MIN_EVAL_RUNS_FOR_COMPARISON = 5

#: Pass-rate drop (fraction, not percentage points of a percentage) that gets an
#: item. Deliberately looser than the score thresholds: `passed` is already a
#: thresholded quantity, so it moves in bigger steps.
PASS_RATE_DROP_THRESHOLD = 0.15

#: How far back to look for the comparison baseline, as a multiple of the digest
#: window. 4x a 6-hour window is a day — long enough to have runs in it, short
#: enough that it is still "recently", and it deliberately does not overlap the
#: current window.
BASELINE_WINDOW_MULTIPLIER = 4

#: Feature 23's soft-metric → component map, as the feature_24 doc requires
#: Area 3 to use: say *where to look*, not just that quality dropped. Fed to the
#: LLM prompt, and also rendered next to the item so the hint survives an LLM
#: failure.
SOFT_METRIC_COMPONENT_HINTS = {
    "faithfulness_score": "retrieval/context — the answer asserted things the fetched context did not support",
    "relevance_score": "trace/routing — the question may be routing to the wrong path (RAG vs SQL vs CHAT)",
    "accuracy_score": "the golden set's reference answers, or a real regression against them",
    "context_score": "retrieval — which invoice records the tools fetched (deterministic F1, no judge)",
    "orchestration_score": "the tool-call chain and its arithmetic (deterministic, no judge)",
    "persona_score": "persona wording and domain-reasoning prompts",
}

#: The `agent_eval_run` columns compared window-over-window.
EVAL_SCORE_COLUMNS = (
    "faithfulness_score",
    "relevance_score",
    "accuracy_score",
    "context_score",
    "orchestration_score",
    "persona_score",
)


# ---------------------------------------------------------------------------
# Item shape
# ---------------------------------------------------------------------------


@dataclass
class DigestItem:
    """One thing that happened, in the shape everything downstream expects.

    `signal` is what goes to `classify()` verbatim — collectors are responsible
    for building a signal the routing module already understands, so that adding
    a source never means editing the routing module.

    `self_resolved` is the field the whole "compress this to one line" rule turns
    on. It means *it fired and it ended on its own, with nothing to decide* — not
    merely "it is not currently firing".
    """

    key: str
    area: str
    title: str
    signal: Signal
    detail: Dict[str, Any] = field(default_factory=dict)
    occurred_at: Optional[datetime] = None
    resolved_at: Optional[datetime] = None
    self_resolved: bool = False
    #: Rendered next to the item even when the LLM is unavailable, so a digest
    #: with a failed synthesis step is still actionable rather than a raw dump.
    component_hint: str = ""

    @property
    def duration(self) -> Optional[timedelta]:
        if self.occurred_at and self.resolved_at:
            return self.resolved_at - self.occurred_at
        return None

    def duration_text(self) -> str:
        delta = self.duration
        if delta is None:
            return ""
        minutes = int(delta.total_seconds() // 60)
        if minutes < 60:
            return f"{minutes}m"
        hours, minutes = divmod(minutes, 60)
        return f"{hours}h{minutes:02d}m"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "key": self.key,
            "area": self.area,
            "title": self.title,
            "signal": dict(self.signal),
            "detail": dict(self.detail),
            "occurred_at": self.occurred_at.isoformat() if self.occurred_at else None,
            "resolved_at": self.resolved_at.isoformat() if self.resolved_at else None,
            "self_resolved": self.self_resolved,
            "component_hint": self.component_hint,
        }


@dataclass
class DigestCollection:
    """Everything one collection pass found, plus how the pass itself went.

    `errors` is a first-class field for the same reason `CostSnapshot.errors` is:
    a digest that silently omitted the alert section because Resource Graph 403'd
    would read as "a quiet six hours", which is the single most dangerous thing
    an ops digest can do. Every failure is carried through to the rendered
    output.
    """

    window_start: datetime
    window_end: datetime
    items: List[DigestItem] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    #: Set when a source was truncated (see ARG_ALERT_LIMIT) so the digest can
    #: say "200 of 431" rather than quietly showing 200.
    counts: Dict[str, int] = field(default_factory=dict)

    def by_area(self, area: str) -> List[DigestItem]:
        return [item for item in self.items if item.area == area]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "window_start": self.window_start.isoformat(),
            "window_end": self.window_end.isoformat(),
            "items": [item.to_dict() for item in self.items],
            "errors": list(self.errors),
            "counts": dict(self.counts),
        }


# ---------------------------------------------------------------------------
# Alerts
# ---------------------------------------------------------------------------


def rule_display_name(rule: str) -> str:
    """``/subscriptions/…/metricAlerts/alert-ca-invoice-be-dev-memory-high`` → the last segment.

    ARG returns the alert rule as a full resource ID (verified live). Rendering
    that into a Teams message would produce a 200-character line per alert.
    """
    if not rule:
        return "(unnamed rule)"
    return rule.rstrip("/").rsplit("/", 1)[-1]


def severity_number(severity: str) -> Optional[int]:
    """``"Sev2"`` → ``2``. Returns None for anything unparseable."""
    text = str(severity or "").strip().lower()
    if text.startswith("sev"):
        text = text[3:]
    try:
        return int(text)
    except (TypeError, ValueError):
        return None


def action_group_for_alert(severity: str, rule_name: str = "") -> str:
    """Which action group `alert-rules.bicep` wires this alert to.

    See the module docstring for why this is a reconstruction and not a guess:
    the mapping was read rule by rule out of the bicep, and ARG does not return
    the action group itself.

    Anything with an unparseable severity falls to ``"info"`` — the quieter
    tier — rather than ``"critical"``, matching `classify()`'s own preference for
    not paging on a signal it could not identify.
    """
    if rule_name and rule_name.endswith(_ALWAYS_CRITICAL_RULE_SUFFIX):
        # The CAE resource-health activity-log alert: no `severity` field exists
        # on it at all, and it is unconditionally on the critical group.
        return "critical"
    number = severity_number(severity)
    if number is None:
        return "info"
    return "critical" if number <= 1 else "info"


def _parse_arg_datetime(raw: Any) -> Optional[datetime]:
    """ARG datetimes, tolerating the empty-string-means-null case seen live."""
    text = str(raw or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _arg_rows(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Rows out of a Resource Graph response, in either result format.

    ``objectArray`` (the default, and what both ``az graph query`` and the REST
    endpoint return today) gives ``data`` as a list of dicts. ``table`` gives a
    dict of ``columns``/``rows``. Handling both is four lines and means a future
    caller passing ``resultFormat`` does not silently get zero alerts.
    """
    data = payload.get("data")
    if isinstance(data, list):
        return [row for row in data if isinstance(row, dict)]
    if isinstance(data, dict):
        columns = [c.get("name") for c in (data.get("columns") or [])]
        return [dict(zip(columns, row)) for row in (data.get("rows") or [])]
    return []


def collect_alert_items(
    window_start: datetime,
    *,
    subscription_id: Optional[str] = None,
    resource_group: Optional[str] = None,
    limit: int = ARG_ALERT_LIMIT,
) -> Tuple[List[DigestItem], List[str], int]:
    """Alerts that fired since ``window_start``, as digest items.

    Returns ``(items, errors, total_seen)``. Never raises: an unreachable or
    unauthorized Resource Graph produces an error string, and the digest says so
    out loud rather than rendering a falsely quiet health section.
    """
    errors: List[str] = []
    subscription = (subscription_id or settings.AZURE_SUBSCRIPTION_ID or "").strip()
    if not subscription:
        return [], ["alerts: AZURE_SUBSCRIPTION_ID is not set, no alerts collected"], 0

    query = ARG_ALERTS_QUERY.format(
        window_start=window_start.astimezone(timezone.utc).isoformat(),
        limit=int(limit),
    )
    body: Dict[str, Any] = {"subscriptions": [subscription], "query": query}

    try:
        # Imported here, not at module import: `azure_cost` reads `config` and is
        # also pulled in by a standalone script, and this module is imported by
        # the test suite with no Azure configuration at all.
        from services.azure_cost import arm_request  # noqa: PLC0415

        payload = arm_request("POST", RESOURCE_GRAPH_URL, json_body=body)
    except Exception as exc:  # noqa: BLE001 - deliberately broad, see docstring
        logger.warning("Ops digest: alert collection failed: %s", exc)
        return [], [f"alerts: {type(exc).__name__}: {exc}"], 0

    rows = _arg_rows(payload)
    total = int(payload.get("totalRecords") or len(rows))

    wanted_group = (resource_group or settings.AZURE_COST_RESOURCE_GROUP or "").strip().lower()

    items: List[DigestItem] = []
    for row in rows:
        row_group = str(row.get("resourceGroup") or "").strip().lower()
        if wanted_group and row_group and row_group != wanted_group:
            # The subscription holds exactly one resource group for this product
            # today, but the query is subscription-scoped (alerts are), so an
            # unrelated RG appearing later must not leak into this digest.
            continue

        rule_name = rule_display_name(str(row.get("rule") or ""))
        severity = str(row.get("sev") or "")
        monitor_condition = str(row.get("monitorCondition") or "")
        fired_at = _parse_arg_datetime(row.get("fired"))
        resolved_at = _parse_arg_datetime(row.get("resolvedAt"))
        target = str(row.get("target") or "")
        self_resolved = monitor_condition.strip().lower() == "resolved"

        signal: Signal = {
            "source": "azure_alert",
            "action_group": action_group_for_alert(severity, rule_name),  # type: ignore[typeddict-item]
        }

        items.append(
            DigestItem(
                # `name` is the alert instance GUID -- unique per firing, which
                # is what a per-item key has to be (the same rule can fire
                # twice in one window).
                key=f"alert:{row.get('name') or rule_name}",
                area=AREA_HEALTH,
                title=f"{rule_name} on {target}" if target else rule_name,
                signal=signal,
                detail={
                    "rule": rule_name,
                    "severity": severity,
                    "target": target,
                    "target_type": str(row.get("targetType") or ""),
                    "monitor_condition": monitor_condition,
                    "alert_state": str(row.get("alertState") or ""),
                    "monitor_service": str(row.get("monitorService") or ""),
                    "description": str(row.get("description") or ""),
                    "resource_group": str(row.get("resourceGroup") or ""),
                },
                occurred_at=fired_at,
                resolved_at=resolved_at,
                self_resolved=self_resolved,
            )
        )

    if total > len(rows):
        errors.append(
            f"alerts: {total} alerts fired in this window, only the {len(rows)} most recent "
            "were collected (ARG_ALERT_LIMIT)"
        )
    return items, errors, total


# ---------------------------------------------------------------------------
# Cost
# ---------------------------------------------------------------------------


def collect_cost_items(
    snapshot: Any,
    *,
    spike_pct_threshold: float,
    include_budget_items: bool,
    now: Optional[datetime] = None,
) -> Tuple[List[DigestItem], List[str]]:
    """Cost items from an already-collected `CostSnapshot`.

    Takes the snapshot rather than fetching it so this is testable without a
    network and so a caller that already has one (a future dashboard endpoint)
    does not pay for a second throttled round-trip.

    The feature doc's Area 1 requirement is "what changed and why, not just the
    number", so the item's `detail` carries the top spend slices alongside the
    delta — that is the "why" material the LLM step needs, and without it the
    synthesis has nothing to reason from.
    """
    items: List[DigestItem] = []
    errors = [f"cost: {message}" for message in (getattr(snapshot, "errors", None) or [])]
    occurred = now or datetime.now(timezone.utc)

    change = getattr(snapshot, "day_over_day_change_pct", None)
    currency = getattr(snapshot, "currency", "") or ""
    top_services = [
        slice_.to_dict() for slice_ in (getattr(snapshot, "by_service", None) or [])[:5]
    ]

    if change is not None and abs(change) >= spike_pct_threshold:
        direction = "up" if change > 0 else "down"
        latest = getattr(snapshot, "latest_day", None)
        items.append(
            DigestItem(
                key="cost:day_over_day",
                area=AREA_COST,
                title=f"Daily spend {direction} {abs(change):.1f}% day over day",
                # No `source` field: this is neither an azure_alert nor an
                # ai_eval finding, so `classify()` falls through its two source
                # branches, finds no replica data, and returns "digest" -- which
                # is the correct and intended tier for a cost trend. Inventing a
                # third source just to reach the same answer would mean editing
                # the routing module for no behavioural change.
                signal={},
                detail={
                    "day_over_day_change_pct": change,
                    "latest_day_amount": getattr(latest, "amount", None),
                    "latest_day": latest.usage_date.isoformat() if latest else None,
                    "month_to_date_total": getattr(snapshot, "month_to_date_total", None),
                    "currency": currency,
                    "top_services": top_services,
                },
                occurred_at=occurred,
            )
        )

    forecast = getattr(snapshot, "forecast", None)
    budget = getattr(snapshot, "budget", None)
    if include_budget_items and budget is not None:
        percent_forecast = getattr(budget, "percent_forecast", None)
        percent_used = getattr(budget, "percent_used", None)
        if (percent_forecast or 0) >= 100 or (percent_used or 0) >= 80:
            items.append(
                DigestItem(
                    key="cost:budget",
                    area=AREA_COST,
                    title=(
                        f"Budget {budget.name}: {percent_used}% spent, "
                        f"{percent_forecast}% forecast"
                    ),
                    signal={},
                    detail={
                        "budget": budget.to_dict(),
                        "forecast": forecast.to_dict() if forecast else None,
                        "currency": currency,
                        "top_services": top_services,
                    },
                    occurred_at=occurred,
                )
            )

    return items, errors


# ---------------------------------------------------------------------------
# AI eval
# ---------------------------------------------------------------------------


def _as_naive_utc(value: datetime) -> datetime:
    """`agent_eval_run.run_at` is written by `datetime.utcnow()` — naive UTC.

    Comparing a tz-aware bound against a naive column raises on Postgres and
    silently compares wrong on SQLite, so the boundary conversion happens once,
    here, rather than at four query sites.
    """
    if value.tzinfo is None:
        return value
    return value.astimezone(timezone.utc).replace(tzinfo=None)


def _eval_window_stats(session: Any, start: datetime, end: datetime) -> Dict[str, Any]:
    """Mean of each score column plus the pass rate, over one window.

    Means are computed in Python over the fetched rows rather than in SQL
    because every score column is nullable-means-not-scored (see
    `models.AgentEvalRun`) and each column therefore has its own denominator —
    a single `AVG()` per column would be correct but a single row count would
    not, and mixing the two is exactly how a "quality dropped" alert gets fired
    by a column that simply was not scored that day.
    """
    from sqlmodel import select  # noqa: PLC0415

    from models import AgentEvalRun  # noqa: PLC0415

    rows = session.exec(
        select(AgentEvalRun).where(
            AgentEvalRun.run_at >= _as_naive_utc(start),
            AgentEvalRun.run_at < _as_naive_utc(end),
        )
    ).all()

    stats: Dict[str, Any] = {"run_count": len(rows), "metrics": {}}
    for column in EVAL_SCORE_COLUMNS:
        values = [
            float(getattr(row, column))
            for row in rows
            if getattr(row, column, None) is not None
        ]
        stats["metrics"][column] = {
            "mean": (sum(values) / len(values)) if values else None,
            "n": len(values),
        }
    if rows:
        stats["pass_rate"] = sum(1 for row in rows if row.passed) / len(rows)
    else:
        stats["pass_rate"] = None
    stats["agents"] = sorted({str(row.agent_name) for row in rows})
    return stats


def collect_ai_eval_items(
    session: Any,
    *,
    window_start: datetime,
    window_end: datetime,
    baseline_multiplier: int = BASELINE_WINDOW_MULTIPLIER,
) -> Tuple[List[DigestItem], List[str]]:
    """Quality findings: what moved since the preceding baseline window.

    Three kinds of finding, in the order they can page:

    1. ``audit_job_failed`` — rows in the baseline, none in this window. Always
       critical per the feature doc; see the module docstring for why the
       baseline precondition is load-bearing and not defensive padding.
    2. ``quality_score_drop`` / ``quality_score_drift`` — one item per score
       column that moved down by at least ``DRIFT_DROP_THRESHOLD``, flagged
       ``is_sharp_drop`` past ``SHARP_DROP_THRESHOLD`` so `classify()` can page
       on the cliff and digest the drift.
    3. Online-eval signal breaches — one item per breached signal, all of which
       fall through `classify()`'s unrecognized-finding_type branch to digest.
    """
    items: List[DigestItem] = []
    errors: List[str] = []

    window_length = window_end - window_start
    baseline_end = window_start
    baseline_start = baseline_end - (window_length * max(baseline_multiplier, 1))

    try:
        current = _eval_window_stats(session, window_start, window_end)
        baseline = _eval_window_stats(session, baseline_start, baseline_end)
    except Exception as exc:  # noqa: BLE001 - a missing table must not kill the digest
        logger.warning("Ops digest: agent_eval_run unreadable: %s", exc)
        return [], [f"ai_eval: agent_eval_run unreadable: {type(exc).__name__}: {exc}"]

    if current["run_count"] == 0 and baseline["run_count"] > 0:
        items.append(
            DigestItem(
                key="ai_eval:audit_job_failed",
                area=AREA_AI_EVAL,
                title="The eval/benchmark job produced no runs in this window",
                signal={"source": "ai_eval", "finding_type": "audit_job_failed"},
                detail={
                    "runs_in_window": 0,
                    "runs_in_baseline": baseline["run_count"],
                    "baseline_start": baseline_start.isoformat(),
                    "baseline_end": baseline_end.isoformat(),
                },
                occurred_at=window_end,
                component_hint="the scheduler itself, not any single metric",
            )
        )

    for column in EVAL_SCORE_COLUMNS:
        current_metric = current["metrics"][column]
        baseline_metric = baseline["metrics"][column]
        if (
            current_metric["mean"] is None
            or baseline_metric["mean"] is None
            or current_metric["n"] < MIN_EVAL_RUNS_FOR_COMPARISON
            or baseline_metric["n"] < MIN_EVAL_RUNS_FOR_COMPARISON
        ):
            continue
        delta = current_metric["mean"] - baseline_metric["mean"]
        if delta > -DRIFT_DROP_THRESHOLD:
            continue
        is_sharp = delta <= -SHARP_DROP_THRESHOLD
        finding_type = "quality_score_drop" if is_sharp else "quality_score_drift"
        pretty = column.replace("_score", "").replace("_", " ")
        items.append(
            DigestItem(
                key=f"ai_eval:{column}",
                area=AREA_AI_EVAL,
                title=(
                    f"{pretty} {'dropped' if is_sharp else 'drifting'} "
                    f"{abs(delta):.2f} ({baseline_metric['mean']:.2f} → {current_metric['mean']:.2f})"
                ),
                signal={
                    "source": "ai_eval",
                    "finding_type": finding_type,
                    "is_sharp_drop": is_sharp,
                },
                detail={
                    "metric": column,
                    "current_mean": current_metric["mean"],
                    "baseline_mean": baseline_metric["mean"],
                    "delta": delta,
                    "current_n": current_metric["n"],
                    "baseline_n": baseline_metric["n"],
                    "agents": current["agents"],
                },
                occurred_at=window_end,
                component_hint=SOFT_METRIC_COMPONENT_HINTS.get(column, ""),
            )
        )

    current_pass, baseline_pass = current["pass_rate"], baseline["pass_rate"]
    if (
        current_pass is not None
        and baseline_pass is not None
        and current["run_count"] >= MIN_EVAL_RUNS_FOR_COMPARISON
        and baseline["run_count"] >= MIN_EVAL_RUNS_FOR_COMPARISON
        and (current_pass - baseline_pass) <= -PASS_RATE_DROP_THRESHOLD
    ):
        items.append(
            DigestItem(
                key="ai_eval:pass_rate",
                area=AREA_AI_EVAL,
                title=(
                    f"Eval pass rate {baseline_pass:.0%} → {current_pass:.0%}"
                ),
                # Not one of the named exceptions: a pass-rate move is a
                # thresholded view of the same scores above, so it digests.
                signal={"source": "ai_eval", "finding_type": "pass_rate_drop"},
                detail={
                    "current_pass_rate": current_pass,
                    "baseline_pass_rate": baseline_pass,
                    "current_runs": current["run_count"],
                    "baseline_runs": baseline["run_count"],
                },
                occurred_at=window_end,
                component_hint="check which dimension's floor is being missed before the level",
            )
        )

    online_items, online_errors = _collect_online_signal_items(
        session, window_start=window_start, window_end=window_end
    )
    items.extend(online_items)
    errors.extend(online_errors)
    return items, errors


def _collect_online_signal_items(
    session: Any, *, window_start: datetime, window_end: datetime
) -> Tuple[List[DigestItem], List[str]]:
    """Breached online-eval signals for the window, one item each.

    `compute_online_signals()` takes a window *length* in days and an end
    instant, so a 6-hour digest window becomes 0.25 days. It accepts a float
    fine (`timedelta(days=...)`), and passing the real fraction is better than
    rounding up to a day and reporting yesterday's clarification rate as if it
    were this morning's.
    """
    try:
        from services.online_eval_signals import compute_online_signals  # noqa: PLC0415

        window_days = max((window_end - window_start).total_seconds() / 86400.0, 0.01)
        signals = compute_online_signals(
            session,
            window_days=window_days,
            now=_as_naive_utc(window_end),
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Ops digest: online signals unavailable: %s", exc)
        return [], [f"ai_eval: online signals unavailable: {type(exc).__name__}: {exc}"]

    items: List[DigestItem] = []
    for signal in signals.breaches:
        items.append(
            DigestItem(
                key=f"ai_eval:online:{signal.name}",
                area=AREA_AI_EVAL,
                title=f"Online signal breached: {signal.name} = {signal.value:.2f}"
                if signal.value is not None
                else f"Online signal breached: {signal.name}",
                signal={
                    "source": "ai_eval",
                    # Deliberately not one of the named exception types -- these
                    # fall through `classify()`'s default to digest, which is
                    # what the feature doc wants for a live-traffic proxy metric.
                    "finding_type": f"online_signal_{signal.name}",
                },
                detail={
                    "signal": signal.name,
                    "value": signal.value,
                    "threshold": signal.threshold,
                    "numerator": signal.numerator,
                    "denominator": signal.denominator,
                    # Carried onto the item because three of the five signals are
                    # a proxy/heuristic measurement, and a digest that presented
                    # a heuristic with the same weight as a measured number would
                    # be actively misleading.
                    "confidence": signal.confidence,
                    "caveat": signal.caveat,
                },
                occurred_at=window_end,
                component_hint=signal.caveat or signal.source,
            )
        )
    return items, []


# ---------------------------------------------------------------------------
# One pass over all three sources
# ---------------------------------------------------------------------------


def collect_all(
    session: Any = None,
    *,
    window_hours: Optional[float] = None,
    now: Optional[datetime] = None,
    include_alerts: bool = True,
    include_cost: bool = True,
    include_ai_eval: bool = True,
    cost_snapshot: Any = None,
) -> DigestCollection:
    """Everything that changed in the window, from all three sources.

    Each source is independently guarded: an unauthorized Resource Graph, a
    throttled Cost Management API and a missing `agent_eval_run` table produce
    three error strings and whatever the other two sources managed to collect.
    Nothing here raises.

    `session` may be None, in which case the AI-eval source is skipped with an
    explicit error rather than silently omitted — "no DB session" and "no quality
    findings" must not render identically.
    """
    window_end = now or datetime.now(timezone.utc)
    if window_end.tzinfo is None:
        window_end = window_end.replace(tzinfo=timezone.utc)
    hours = window_hours if window_hours is not None else float(settings.OPS_DIGEST_WINDOW_HOURS)
    window_start = window_end - timedelta(hours=max(hours, 0.1))

    collection = DigestCollection(window_start=window_start, window_end=window_end)

    if include_alerts:
        items, errors, total = collect_alert_items(window_start)
        collection.items.extend(items)
        collection.errors.extend(errors)
        collection.counts["alerts_total"] = total
        collection.counts["alerts_collected"] = len(items)

    if include_cost:
        snapshot = cost_snapshot
        if snapshot is None:
            try:
                from services.azure_cost import collect_cost_snapshot, is_configured  # noqa: PLC0415

                if is_configured():
                    snapshot = collect_cost_snapshot()
                else:
                    collection.errors.append(
                        "cost: AZURE_SUBSCRIPTION_ID/AZURE_COST_RESOURCE_GROUP not set, "
                        "no cost data collected"
                    )
            except Exception as exc:  # noqa: BLE001
                logger.warning("Ops digest: cost collection failed: %s", exc)
                collection.errors.append(f"cost: {type(exc).__name__}: {exc}")
        if snapshot is not None:
            items, errors = collect_cost_items(
                snapshot,
                spike_pct_threshold=float(settings.OPS_DIGEST_COST_SPIKE_PCT),
                include_budget_items=bool(settings.OPS_DIGEST_BUDGET_ITEMS),
                now=window_end,
            )
            collection.items.extend(items)
            collection.errors.extend(errors)

    if include_ai_eval:
        if session is None:
            collection.errors.append(
                "ai_eval: no database session supplied, quality findings not collected"
            )
        else:
            items, errors = collect_ai_eval_items(
                session, window_start=window_start, window_end=window_end
            )
            collection.items.extend(items)
            collection.errors.extend(errors)

    return collection


__all__ = [
    "AREA_AI_EVAL",
    "AREA_COST",
    "AREA_HEALTH",
    "AREA_ORDER",
    "AREA_TITLES",
    "ARG_ALERTS_QUERY",
    "DRIFT_DROP_THRESHOLD",
    "MIN_EVAL_RUNS_FOR_COMPARISON",
    "PASS_RATE_DROP_THRESHOLD",
    "SHARP_DROP_THRESHOLD",
    "SOFT_METRIC_COMPONENT_HINTS",
    "DigestCollection",
    "DigestItem",
    "action_group_for_alert",
    "collect_ai_eval_items",
    "collect_alert_items",
    "collect_all",
    "collect_cost_items",
    "rule_display_name",
    "severity_number",
]
