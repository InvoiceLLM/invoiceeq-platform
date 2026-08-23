"""Feature 24 (Ops Digest Agent) — tests for collection, synthesis, rendering and delivery.

`tests/test_ops_digest_routing.py` already covers `classify()` itself; nothing
here re-tests that decision, it tests the machinery around it.

What is real and what is mocked, stated up front so nobody has to infer it
--------------------------------------------------------------------------
**Real, not mocked, because it is the logic worth testing:**

* Every collector's parsing and thresholding. The alert rows below are trimmed
  copies of a genuine Azure Resource Graph response from subscription
  ``2ae37d8b-…`` on 2026-08-23 — including the three details that are easy to get
  wrong from the docs (``alertRule`` is a full resource ID, ``severity`` is the
  string ``"Sev2"``, ``monitorConditionResolvedDateTime`` is ``""`` rather than
  null while an alert is still firing), and the fourth that a naive
  implementation gets wrong: a row can be ``monitorCondition: Resolved`` and
  ``alertState: New`` at the same time, so "did it self-resolve" must read
  ``monitorCondition``.
* The AI-eval collector runs against a **real SQLite database** with real
  `AgentEvalRun` rows, not a stubbed query — the window/baseline arithmetic and
  the per-column denominators are the parts most likely to be subtly wrong.
* The whole tier split, the self-resolved compression, and the renderer.
* The delivery module's action-group parsing and payload construction.

**Mocked, and only at the process boundary:**

* The LLM. Same `_ScriptedLLM` shape as `tests/test_agent_eval.py::_ScriptedJudge`
  and `test_chat_sql_quality.py::_RecordingLLM` — a `with_structured_output()`
  that returns a canned pydantic object and records the prompt it was given.
  Asserting real model output is not a unit test's job.
* `services.azure_cost.arm_request` — the single HTTP seam for Resource Graph
  and the action-group read.
* `httpx.Client.post` for the webhook, and `services.outbound_email.send_email`.

Nothing here posts to a real Teams channel or sends a real email.
"""
import logging
from datetime import datetime, timedelta, timezone
from unittest.mock import patch
from uuid import uuid4

import pytest
from sqlmodel import Session, SQLModel, create_engine
from sqlalchemy.pool import StaticPool

from models import AgentEvalRun
from services import ops_digest_collect, ops_digest_delivery
from services.ops_digest import (
    MAX_ANALYSED_ITEMS,
    DigestSynthesis,
    ItemAnalysis,
    build_digest,
    build_synthesis_prompt,
    compress_self_resolved,
    partition_digest_items,
    render_digest,
    split_by_tier,
    synthesize_digest,
)
from services.ops_digest_collect import (
    AREA_AI_EVAL,
    AREA_COST,
    AREA_HEALTH,
    DigestCollection,
    DigestItem,
    action_group_for_alert,
    collect_ai_eval_items,
    collect_alert_items,
    collect_all,
    collect_cost_items,
    rule_display_name,
    severity_number,
)
from services.ops_digest_delivery import (
    DELIVERY_AUTO,
    DELIVERY_NONE,
    CriticalChannel,
    build_common_alert_schema_payload,
    deliver_digest,
    resolve_critical_channel,
)
from telemetry import OPS_DIGEST_EVENT_NAME, track_ops_digest_run

SUBSCRIPTION = "2ae37d8b-3189-474c-9508-4b3d7ceec4dd"
RESOURCE_GROUP = "rg-invoice-llm-dev"
RULE_PREFIX = (
    f"/subscriptions/{SUBSCRIPTION}/resourcegroups/{RESOURCE_GROUP}"
    "/providers/Microsoft.Insights/metricAlerts"
)

NOW = datetime(2026, 8, 23, 12, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# Recorded fixtures — trimmed from real 2026-08-23 responses
# ---------------------------------------------------------------------------

# `az graph query -q "alertsmanagementresources | ..."` against the live
# subscription. Rows 1 and 2 are verbatim (bar the description field, which the
# live rows carry empty); row 3 is the same shape with a Sev1 severity, taken
# from the same result set's website-5xx entry.
ARG_ALERTS_PAYLOAD = {
    "totalRecords": 3,
    "count": 3,
    "data": [
        {
            "fired": "2026-08-23T06:08:02.073327Z",
            "sev": "Sev2",
            "alertState": "New",
            "monitorCondition": "Fired",
            "rule": f"{RULE_PREFIX}/alert-ca-invoice-be-dev-memory-high",
            "target": "ca-invoice-be-dev",
            "targetType": "microsoft.app/containerapps",
            "monitorService": "Platform",
            "resolvedAt": "",
            "description": "",
            "resourceGroup": RESOURCE_GROUP,
            "name": "11111111-1111-1111-1111-111111111111",
        },
        {
            "fired": "2026-08-22T06:48:54.4818202Z",
            "sev": "Sev2",
            "alertState": "New",
            "monitorCondition": "Resolved",
            "rule": f"{RULE_PREFIX}/alert-ca-queue-worker-dev-memory-high",
            "target": "ca-queue-worker-dev",
            "targetType": "microsoft.app/containerapps",
            "monitorService": "Platform",
            "resolvedAt": "2026-08-23T05:58:52.8423665Z",
            "description": "",
            "resourceGroup": RESOURCE_GROUP,
            "name": "22222222-2222-2222-2222-222222222222",
        },
        {
            "fired": "2026-08-21T10:40:42.5292941Z",
            "sev": "Sev1",
            "alertState": "New",
            "monitorCondition": "Fired",
            "rule": f"{RULE_PREFIX}/alert-ca-invoice-website-dev-http-5xx-rate",
            "target": "ca-invoice-website-dev",
            "targetType": "microsoft.app/containerapps",
            "monitorService": "Platform",
            "resolvedAt": "",
            "description": "",
            "resourceGroup": RESOURCE_GROUP,
            "name": "33333333-3333-3333-3333-333333333333",
        },
    ],
}

# `az monitor action-group show -g rg-invoice-llm-dev -n ag-invoice-llm-dev`,
# 2026-08-23, with the webhook's `sig=` value replaced.
ACTION_GROUP_PAYLOAD = {
    "name": "ag-invoice-llm-dev",
    "properties": {
        "groupShortName": "invllmalrt",
        "enabled": True,
        "emailReceivers": [
            {
                "name": "primary-email",
                "emailAddress": "application@infinevocloud.com",
                "useCommonAlertSchema": True,
            }
        ],
        "webhookReceivers": [
            {
                "name": "teams-alert-channel",
                "serviceUri": (
                    "https://defaultadc862b3adfe4de4a4126ff4ed979c.c6.environment.api"
                    ".powerplatform.com:443/powerautomate/automations/direct/cu/31/workflows"
                    "/c710321ec3ae4f4ea96f73e7690f0e67/triggers/manual/paths/invoke"
                    "?api-version=1&sig=REDACTED-TEST-VALUE"
                ),
                "useAadAuth": False,
                "useCommonAlertSchema": True,
            }
        ],
    },
}


# ---------------------------------------------------------------------------
# Doubles
# ---------------------------------------------------------------------------


class _ScriptedLLM:
    """Canned structured output, recording every prompt it is handed.

    Same shape as `tests/test_agent_eval.py::_ScriptedJudge` and
    `test_chat_sql_quality.py::_RecordingLLM` — this codebase's standard LLM
    double, not a new one.
    """

    def __init__(self, response=None, raises: bool = False):
        self._response = response
        self._raises = raises
        self.prompts: list[str] = []
        self.calls = 0

    def with_structured_output(self, schema):
        outer = self

        class _Structured:
            def invoke(self, prompt, **_kwargs):
                outer.calls += 1
                outer.prompts.append(prompt)
                if outer._raises:
                    raise RuntimeError("model unavailable")
                return outer._response

        return _Structured()


class _FakeSlice:
    def __init__(self, name, amount):
        self.dimension = "ServiceName"
        self.name = name
        self.amount = amount
        self.currency = "INR"

    def to_dict(self):
        return {
            "dimension": self.dimension,
            "name": self.name,
            "amount": self.amount,
            "currency": self.currency,
        }


class _FakeDay:
    def __init__(self, amount):
        self.amount = amount
        self.usage_date = NOW.date()
        self.currency = "INR"


class _FakeBudget:
    name = "budget-invoicellm-dev"
    percent_used = 10935.0
    percent_forecast = 16400.0

    def to_dict(self):
        return {"name": self.name, "percent_used": self.percent_used}


class _FakeSnapshot:
    """Only the attributes `collect_cost_items()` actually reads."""

    def __init__(self, change_pct, *, budget=None, errors=None):
        self.day_over_day_change_pct = change_pct
        self.currency = "INR"
        self.by_service = [_FakeSlice("Azure Container Apps", 8490.34)]
        self.latest_day = _FakeDay(617.85)
        self.month_to_date_total = 16513.97
        self.budget = budget
        self.forecast = None
        self.errors = errors or []


@pytest.fixture(name="db_session")
def db_session_fixture():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    SQLModel.metadata.drop_all(engine)


def _eval_row(run_at, **scores):
    defaults = dict(
        agent_name="chat.default_path",
        question="q",
        actual_answer="a",
        tenant_id=uuid4(),
        run_at=run_at,
        passed=scores.pop("passed", True),
    )
    defaults.update(scores)
    return AgentEvalRun(**defaults)


# ---------------------------------------------------------------------------
# Alert parsing
# ---------------------------------------------------------------------------


def test_rule_display_name_reduces_a_full_resource_id_to_the_rule_name():
    # ARG returns the whole resource ID (verified live) -- rendering that into a
    # Teams message would be a 200-character line per alert.
    assert (
        rule_display_name(f"{RULE_PREFIX}/alert-ca-invoice-be-dev-memory-high")
        == "alert-ca-invoice-be-dev-memory-high"
    )
    assert rule_display_name("") == "(unnamed rule)"


def test_severity_is_a_string_not_a_number_in_the_real_response():
    assert severity_number("Sev2") == 2
    assert severity_number("Sev0") == 0
    assert severity_number("") is None
    assert severity_number("nonsense") is None


@pytest.mark.parametrize(
    "severity,expected",
    [("Sev0", "critical"), ("Sev1", "critical"), ("Sev2", "info"), ("Sev3", "info")],
)
def test_action_group_mirrors_alert_rules_bicep_severity_split(severity, expected):
    assert action_group_for_alert(severity) == expected


def test_unparseable_severity_falls_to_the_quieter_tier():
    # Same preference `classify()` itself has: never page on a signal we could
    # not identify.
    assert action_group_for_alert("") == "info"


def test_cae_resource_health_alert_is_critical_despite_carrying_no_severity():
    # It is an activityLogAlerts resource -- no `severity` field exists on it at
    # all -- and alert-rules.bicep wires it to the critical action group.
    assert action_group_for_alert("", "alert-cae-invoice-llm-dev-resource-health") == "critical"


def test_collect_alert_items_parses_the_real_resource_graph_shape(monkeypatch):
    monkeypatch.setattr("services.azure_cost.arm_request", lambda *a, **k: ARG_ALERTS_PAYLOAD)
    monkeypatch.setattr(ops_digest_collect.settings, "AZURE_SUBSCRIPTION_ID", SUBSCRIPTION)
    monkeypatch.setattr(ops_digest_collect.settings, "AZURE_COST_RESOURCE_GROUP", RESOURCE_GROUP)

    items, errors, total = collect_alert_items(NOW - timedelta(hours=6))

    assert errors == []
    assert total == 3
    assert [item.title for item in items] == [
        "alert-ca-invoice-be-dev-memory-high on ca-invoice-be-dev",
        "alert-ca-queue-worker-dev-memory-high on ca-queue-worker-dev",
        "alert-ca-invoice-website-dev-http-5xx-rate on ca-invoice-website-dev",
    ]
    assert all(item.area == AREA_HEALTH for item in items)
    assert items[0].signal == {"source": "azure_alert", "action_group": "info"}
    assert items[2].signal == {"source": "azure_alert", "action_group": "critical"}


def test_self_resolved_reads_monitor_condition_not_alert_state(monkeypatch):
    # The real row that motivates this: monitorCondition "Resolved" while
    # alertState is still "New", because nobody closed it in the portal. Reading
    # alertState would report a self-resolved alert as still open.
    monkeypatch.setattr("services.azure_cost.arm_request", lambda *a, **k: ARG_ALERTS_PAYLOAD)
    monkeypatch.setattr(ops_digest_collect.settings, "AZURE_SUBSCRIPTION_ID", SUBSCRIPTION)
    monkeypatch.setattr(ops_digest_collect.settings, "AZURE_COST_RESOURCE_GROUP", RESOURCE_GROUP)

    items, _, _ = collect_alert_items(NOW - timedelta(hours=6))

    resolved = items[1]
    assert resolved.detail["alert_state"] == "New"
    assert resolved.self_resolved is True
    assert resolved.resolved_at == datetime(
        2026, 8, 23, 5, 58, 52, 842366, tzinfo=timezone.utc
    )
    # And an empty-string resolvedAt is a null, not a parse error.
    assert items[0].self_resolved is False
    assert items[0].resolved_at is None


def test_alerts_from_another_resource_group_are_not_pulled_in(monkeypatch):
    payload = {
        "totalRecords": 1,
        "data": [dict(ARG_ALERTS_PAYLOAD["data"][0], resourceGroup="rg-somebody-else")],
    }
    monkeypatch.setattr("services.azure_cost.arm_request", lambda *a, **k: payload)
    monkeypatch.setattr(ops_digest_collect.settings, "AZURE_SUBSCRIPTION_ID", SUBSCRIPTION)
    monkeypatch.setattr(ops_digest_collect.settings, "AZURE_COST_RESOURCE_GROUP", RESOURCE_GROUP)

    items, _, _ = collect_alert_items(NOW - timedelta(hours=6))
    assert items == []


def test_the_query_carries_the_window_start_so_a_run_only_sees_new_alerts(monkeypatch):
    captured = {}

    def _capture(method, url, *, json_body=None):
        captured["body"] = json_body
        return {"data": []}

    monkeypatch.setattr("services.azure_cost.arm_request", _capture)
    monkeypatch.setattr(ops_digest_collect.settings, "AZURE_SUBSCRIPTION_ID", SUBSCRIPTION)

    window_start = NOW - timedelta(hours=6)
    collect_alert_items(window_start)

    assert captured["body"]["subscriptions"] == [SUBSCRIPTION]
    assert window_start.isoformat() in captured["body"]["query"]
    assert "alertsmanagementresources" in captured["body"]["query"]


def test_an_unauthorized_resource_graph_produces_an_error_not_a_quiet_window(monkeypatch):
    # The realistic failure: the managed identity has no Monitoring Reader role
    # (not deployed). A digest that rendered an empty health section here would
    # read as "a quiet six hours", which is the worst possible outcome.
    def _boom(*_a, **_k):
        raise RuntimeError("403 Forbidden")

    monkeypatch.setattr("services.azure_cost.arm_request", _boom)
    monkeypatch.setattr(ops_digest_collect.settings, "AZURE_SUBSCRIPTION_ID", SUBSCRIPTION)

    items, errors, total = collect_alert_items(NOW - timedelta(hours=6))
    assert items == []
    assert total == 0
    assert len(errors) == 1 and "403" in errors[0]


def test_no_subscription_configured_is_reported_rather_than_silently_skipped(monkeypatch):
    monkeypatch.setattr(ops_digest_collect.settings, "AZURE_SUBSCRIPTION_ID", "")
    items, errors, _ = collect_alert_items(NOW - timedelta(hours=6))
    assert items == []
    assert "AZURE_SUBSCRIPTION_ID" in errors[0]


# ---------------------------------------------------------------------------
# Cost
# ---------------------------------------------------------------------------


def test_a_spend_move_past_the_threshold_becomes_an_item_carrying_the_why():
    items, errors = collect_cost_items(
        _FakeSnapshot(41.2), spike_pct_threshold=25.0, include_budget_items=False, now=NOW
    )
    assert errors == []
    assert len(items) == 1
    item = items[0]
    assert item.area == AREA_COST
    assert "up 41.2%" in item.title
    # "what changed and why", per the feature doc -- the breakdown has to travel
    # with the delta or the synthesis step has nothing to reason from.
    assert item.detail["top_services"][0]["name"] == "Azure Container Apps"


def test_a_spend_move_below_the_threshold_is_not_reported():
    items, _ = collect_cost_items(
        _FakeSnapshot(9.0), spike_pct_threshold=25.0, include_budget_items=False, now=NOW
    )
    assert items == []


def test_budget_items_are_off_by_default_because_of_the_gap_295_currency_bug():
    # `budget-invoicellm-dev` is permanently breached (INR amount set as if USD),
    # so emitting this would put one guaranteed meaningless line in every digest.
    items, _ = collect_cost_items(
        _FakeSnapshot(0.0, budget=_FakeBudget()),
        spike_pct_threshold=25.0,
        include_budget_items=False,
        now=NOW,
    )
    assert items == []

    items, _ = collect_cost_items(
        _FakeSnapshot(0.0, budget=_FakeBudget()),
        spike_pct_threshold=25.0,
        include_budget_items=True,
        now=NOW,
    )
    assert len(items) == 1 and items[0].key == "cost:budget"


def test_a_partial_cost_snapshot_still_yields_its_items_and_reports_the_failure():
    items, errors = collect_cost_items(
        _FakeSnapshot(50.0, errors=["forecast: HTTP 429"]),
        spike_pct_threshold=25.0,
        include_budget_items=False,
        now=NOW,
    )
    assert len(items) == 1
    assert errors == ["cost: forecast: HTTP 429"]


# ---------------------------------------------------------------------------
# AI eval
# ---------------------------------------------------------------------------


def test_a_sharp_quality_drop_is_flagged_as_a_cliff_so_classify_can_page(db_session):
    window_start = NOW - timedelta(hours=6)
    for _ in range(6):
        db_session.add(_eval_row(window_start - timedelta(hours=5), faithfulness_score=0.90))
        db_session.add(_eval_row(window_start + timedelta(hours=1), faithfulness_score=0.55))
    db_session.commit()

    items, errors = collect_ai_eval_items(
        db_session, window_start=window_start, window_end=NOW
    )
    assert errors == []
    drop = [i for i in items if i.key == "ai_eval:faithfulness_score"]
    assert len(drop) == 1
    assert drop[0].signal["finding_type"] == "quality_score_drop"
    assert drop[0].signal["is_sharp_drop"] is True
    assert drop[0].area == AREA_AI_EVAL
    # Area 3's requirement: say where to look, not just that quality dropped.
    assert "retrieval" in drop[0].component_hint


def test_a_gradual_move_is_drift_and_stays_in_the_digest(db_session):
    window_start = NOW - timedelta(hours=6)
    for _ in range(6):
        db_session.add(_eval_row(window_start - timedelta(hours=5), relevance_score=0.90))
        db_session.add(_eval_row(window_start + timedelta(hours=1), relevance_score=0.82))
    db_session.commit()

    items, _ = collect_ai_eval_items(db_session, window_start=window_start, window_end=NOW)
    drift = [i for i in items if i.key == "ai_eval:relevance_score"]
    assert len(drift) == 1
    assert drift[0].signal["finding_type"] == "quality_score_drift"
    assert drift[0].signal["is_sharp_drop"] is False


def test_too_few_runs_reports_nothing_rather_than_a_two_sample_trend(db_session):
    window_start = NOW - timedelta(hours=6)
    for _ in range(2):
        db_session.add(_eval_row(window_start - timedelta(hours=5), faithfulness_score=0.95))
        db_session.add(_eval_row(window_start + timedelta(hours=1), faithfulness_score=0.10))
    db_session.commit()

    items, _ = collect_ai_eval_items(db_session, window_start=window_start, window_end=NOW)
    assert [i for i in items if i.key.startswith("ai_eval:faithfulness")] == []


def test_a_column_that_was_simply_not_scored_does_not_look_like_a_quality_drop(db_session):
    # Every score column is nullable-means-not-scored. `persona_score` is NULL on
    # most turns by design, and a shared denominator would read that as a crash.
    window_start = NOW - timedelta(hours=6)
    for _ in range(6):
        db_session.add(
            _eval_row(window_start - timedelta(hours=5), faithfulness_score=0.9, persona_score=0.9)
        )
        db_session.add(
            _eval_row(window_start + timedelta(hours=1), faithfulness_score=0.9, persona_score=None)
        )
    db_session.commit()

    items, _ = collect_ai_eval_items(db_session, window_start=window_start, window_end=NOW)
    assert [i for i in items if "persona" in i.key] == []


def test_audit_job_failed_fires_only_when_a_running_job_stops(db_session):
    window_start = NOW - timedelta(hours=6)
    for _ in range(3):
        db_session.add(_eval_row(window_start - timedelta(hours=5), faithfulness_score=0.9))
    db_session.commit()

    items, _ = collect_ai_eval_items(db_session, window_start=window_start, window_end=NOW)
    failure = [i for i in items if i.key == "ai_eval:audit_job_failed"]
    assert len(failure) == 1
    assert failure[0].signal == {"source": "ai_eval", "finding_type": "audit_job_failed"}


def test_a_job_that_has_never_run_is_not_reported_as_a_silent_failure(db_session):
    # Nothing schedules an eval job today (Feature 23's was deleted), so a naive
    # "no rows this window" check would fire on every single digest.
    items, _ = collect_ai_eval_items(
        db_session, window_start=NOW - timedelta(hours=6), window_end=NOW
    )
    assert [i for i in items if i.key == "ai_eval:audit_job_failed"] == []


def test_a_pass_rate_collapse_is_reported_but_does_not_page(db_session):
    window_start = NOW - timedelta(hours=6)
    for _ in range(6):
        db_session.add(_eval_row(window_start - timedelta(hours=5), passed=True))
        db_session.add(_eval_row(window_start + timedelta(hours=1), passed=False))
    db_session.commit()

    items, _ = collect_ai_eval_items(db_session, window_start=window_start, window_end=NOW)
    rate = [i for i in items if i.key == "ai_eval:pass_rate"]
    assert len(rate) == 1
    critical, digest = split_by_tier(rate)
    assert critical == [] and len(digest) == 1


def test_an_unreadable_eval_table_degrades_to_an_error_not_an_exception():
    class _BrokenSession:
        def exec(self, *_a, **_k):
            raise RuntimeError("relation \"agent_eval_run\" does not exist")

    items, errors = collect_ai_eval_items(
        _BrokenSession(), window_start=NOW - timedelta(hours=6), window_end=NOW
    )
    assert items == []
    assert len(errors) == 1 and "agent_eval_run" in errors[0]


def test_collect_all_without_a_session_says_so_instead_of_omitting_the_section(monkeypatch):
    monkeypatch.setattr(ops_digest_collect.settings, "AZURE_SUBSCRIPTION_ID", "")
    collection = collect_all(None, window_hours=6, now=NOW, include_cost=False)
    assert any("no database session" in error for error in collection.errors)


# ---------------------------------------------------------------------------
# Tier split and compression
# ---------------------------------------------------------------------------


def _item(key, *, signal=None, area=AREA_HEALTH, self_resolved=False, title=None, **kwargs):
    return DigestItem(
        key=key,
        area=area,
        title=title or key,
        signal=signal if signal is not None else {},
        self_resolved=self_resolved,
        occurred_at=kwargs.pop("occurred_at", NOW - timedelta(hours=2)),
        **kwargs,
    )


def test_critical_items_are_split_out_and_never_appear_in_the_digest_body():
    items = [
        _item("a", signal={"source": "azure_alert", "action_group": "critical"}, title="5xx storm"),
        _item("b", signal={"source": "azure_alert", "action_group": "info"}, title="cpu high"),
    ]
    critical, digest = split_by_tier(items)
    assert [i.key for i in critical] == ["a"]
    assert [i.key for i in digest] == ["b"]

    result = build_digest(
        DigestCollection(window_start=NOW - timedelta(hours=6), window_end=NOW, items=items),
        use_llm=False,
    )
    # Paging the same incident twice, six hours late, is worse than once.
    assert "5xx storm" not in result.body
    # ...but the reader is told they happened, so the digest is not pretending.
    assert "1 critical alert(s) fired" in result.body
    assert "cpu high" in result.body


def test_an_ai_eval_critical_is_named_because_nothing_else_has_paged_it():
    items = [
        _item(
            "ai",
            area=AREA_AI_EVAL,
            title="faithfulness dropped 0.35",
            signal={"source": "ai_eval", "finding_type": "quality_score_drop", "is_sharp_drop": True},
        )
    ]
    result = build_digest(
        DigestCollection(window_start=NOW - timedelta(hours=6), window_end=NOW, items=items),
        use_llm=False,
    )
    assert "nothing else has notified anyone" in result.body
    assert "faithfulness dropped 0.35" in result.body


def test_self_resolved_items_compress_to_exactly_one_line_each():
    items = [
        _item(
            "x",
            title="alert-ca-invoice-be-dev-memory-high on ca-invoice-be-dev",
            self_resolved=True,
            occurred_at=datetime(2026, 8, 23, 4, 12, tzinfo=timezone.utc),
            resolved_at=datetime(2026, 8, 23, 4, 59, tzinfo=timezone.utc),
        )
    ]
    lines = compress_self_resolved(items)
    assert len(lines) == 1
    assert lines[0] == (
        "alert-ca-invoice-be-dev-memory-high on ca-invoice-be-dev — "
        "fired 23 Aug 04:12 UTC, self-resolved after 47m"
    )


def test_partition_separates_needs_decision_from_self_resolved():
    needs, resolved = partition_digest_items(
        [_item("a"), _item("b", self_resolved=True)]
    )
    assert [i.key for i in needs] == ["a"]
    assert [i.key for i in resolved] == ["b"]


def test_self_resolved_items_never_reach_the_llm():
    llm = _ScriptedLLM(DigestSynthesis(headline="", analyses=[]))
    collection = DigestCollection(
        window_start=NOW - timedelta(hours=6),
        window_end=NOW,
        items=[_item("a", self_resolved=True), _item("b", self_resolved=True)],
    )
    build_digest(collection, llm=llm)
    # Nothing needed a decision, so the model was never called at all.
    assert llm.calls == 0


# ---------------------------------------------------------------------------
# Synthesis
# ---------------------------------------------------------------------------


def test_one_call_covers_every_item_rather_than_one_call_per_item():
    items = [_item("a"), _item("b"), _item("c")]
    llm = _ScriptedLLM(
        DigestSynthesis(
            headline="Three things moved.",
            analyses=[
                ItemAnalysis(
                    item_key=key,
                    what_happened="w",
                    likely_cause="c",
                    suggested_action="s",
                )
                for key in ("a", "b", "c")
            ],
        )
    )
    result = synthesize_digest(items, window_start=NOW - timedelta(hours=6), window_end=NOW, llm=llm)
    assert llm.calls == 1
    assert result.llm_calls == 1
    assert set(result.analyses) == {"a", "b", "c"}
    assert result.missing_keys == []
    assert result.headline == "Three things moved."


def test_the_prompt_carries_the_rules_that_stop_it_becoming_a_raw_dump():
    prompt = build_synthesis_prompt(
        [_item("a", component_hint="retrieval/context")],
        window_start=NOW - timedelta(hours=6),
        window_end=NOW,
        self_resolved_items=[_item("r", title="cpu-high on ca-x", self_resolved=True)],
        critical_count=1,
    )
    # The anti-restatement rule, with its worked example -- the single most
    # likely way this feature degrades into a costlier alert forwarder.
    assert "Do not restate the item" in prompt
    # The "say you don't know" clause.
    assert "invent a cause" in prompt
    # The component map (Area 3's "where to look").
    assert "faithfulness_score" in prompt
    # Self-resolved and critical items are accounted for but not analysed.
    assert "must NOT" in prompt and "write an analysis for them" in prompt
    assert "paged separately" in prompt


def test_self_resolved_one_liners_are_supplied_as_cross_item_context():
    # The first live run analysed a still-firing memory-high alert without
    # knowing the same rule had self-resolved 12 times in the same window --
    # which is the most useful fact about it, and the one thing a per-item call
    # could never see.
    prompt = build_synthesis_prompt(
        [_item("a", title="memory-high on ca-invoice-be-dev")],
        window_start=NOW - timedelta(hours=6),
        window_end=NOW,
        self_resolved_items=[
            _item(
                "r",
                title="memory-high on ca-invoice-be-dev",
                self_resolved=True,
                occurred_at=datetime(2026, 8, 23, 4, 12, tzinfo=timezone.utc),
                resolved_at=datetime(2026, 8, 23, 5, 12, tzinfo=timezone.utc),
            )
        ],
    )
    assert "use them as context" in prompt
    assert "self-resolved after 1h00m" in prompt
    # And it must not be asked to act.
    assert "never act" in prompt.lower() or "never propose" in prompt.lower()


def test_an_unreachable_model_still_produces_a_deliverable_digest():
    llm = _ScriptedLLM(raises=True)
    items = [_item("a", title="memory high", component_hint="a restart pattern")]
    collection = DigestCollection(
        window_start=NOW - timedelta(hours=6), window_end=NOW, items=items
    )
    result = build_digest(collection, llm=llm)

    assert result.synthesis.error.startswith("synthesis failed")
    assert result.synthesis.missing_keys == ["a"]
    # Degraded, but still actionable and still sent.
    assert "memory high" in result.body
    assert "No written analysis" in result.body
    assert "a restart pattern" in result.body


def test_an_item_the_model_skipped_is_reported_not_silently_uncommented():
    items = [_item("a"), _item("b")]
    llm = _ScriptedLLM(
        DigestSynthesis(
            headline="",
            analyses=[
                ItemAnalysis(item_key="a", what_happened="w", likely_cause="c", suggested_action="s")
            ],
        )
    )
    result = synthesize_digest(items, window_start=NOW - timedelta(hours=6), window_end=NOW, llm=llm)
    assert result.missing_keys == ["b"]


def test_a_flood_of_items_is_truncated_and_the_truncation_is_stated():
    items = [_item(f"k{n}") for n in range(MAX_ANALYSED_ITEMS + 5)]
    llm = _ScriptedLLM(DigestSynthesis(headline="", analyses=[]))
    collection = DigestCollection(
        window_start=NOW - timedelta(hours=6), window_end=NOW, items=items
    )
    result = build_digest(collection, llm=llm)

    assert result.synthesis.truncated_count == 5
    assert "further item(s) needing a decision were not" in result.body


def test_no_llm_mode_makes_no_call_at_all():
    llm = _ScriptedLLM(DigestSynthesis(headline="x", analyses=[]))
    collection = DigestCollection(
        window_start=NOW - timedelta(hours=6), window_end=NOW, items=[_item("a")]
    )
    result = build_digest(collection, llm=llm, use_llm=False)
    assert llm.calls == 0
    assert "--no-llm" in result.synthesis.error


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def test_a_genuinely_quiet_window_says_nothing_to_report():
    result = build_digest(
        DigestCollection(window_start=NOW - timedelta(hours=6), window_end=NOW), use_llm=False
    )
    assert result.is_empty is True
    assert "nothing to report" in result.subject
    assert "Nothing fired" in result.body


def test_a_failed_collection_is_not_a_quiet_window():
    collection = DigestCollection(
        window_start=NOW - timedelta(hours=6),
        window_end=NOW,
        errors=["alerts: 403 Forbidden"],
    )
    result = build_digest(collection, use_llm=False)
    assert result.is_empty is False
    assert "Collection health" in result.body
    assert "403 Forbidden" in result.body
    assert "incomplete, not quiet" in result.body


def test_a_multiline_driver_error_becomes_one_bullet():
    # Found on the first real run: a psycopg2 OperationalError is six lines of
    # host/port retries plus a docs URL, which buried the two collection errors
    # next to it.
    collection = DigestCollection(
        window_start=NOW - timedelta(hours=6),
        window_end=NOW,
        errors=[
            "ai_eval: agent_eval_run unreadable: OperationalError: connection to server\n"
            'at "localhost" (::1), port 5433 failed: Connection refused\n\n'
            "(Background on this error at: https://sqlalche.me/e/20/e3q8)"
        ],
    )
    result = build_digest(collection, use_llm=False)
    error_bullets = [
        line for line in result.body.splitlines() if line.startswith("- ai_eval:")
    ]
    assert len(error_bullets) == 1
    assert "\n" not in error_bullets[0]


def test_the_body_renders_the_three_analysis_fields_under_their_area():
    items = [
        _item("cost:x", area=AREA_COST, title="Daily spend up 41.2% day over day"),
    ]
    llm = _ScriptedLLM(
        DigestSynthesis(
            headline="Spend moved on Container Apps.",
            analyses=[
                ItemAnalysis(
                    item_key="cost:x",
                    what_happened="Container Apps spend rose after a scale-out.",
                    likely_cause="More replicas held for longer after the 85% CPU rule engaged.",
                    suggested_action="Check whether the load was real before raising maxReplicas.",
                )
            ],
        )
    )
    result = build_digest(
        DigestCollection(window_start=NOW - timedelta(hours=6), window_end=NOW, items=items),
        llm=llm,
    )
    assert "Spend moved on Container Apps." in result.body
    assert "### Cost" in result.body
    assert "- What happened: Container Apps spend rose after a scale-out." in result.body
    assert "- Likely cause:" in result.body
    assert "- Suggested action:" in result.body
    # The agent proposes, it does not act -- said in the message itself.
    assert "proposes; it does not act" in result.body


def test_the_subject_counts_each_bucket_separately():
    items = [
        _item("a", signal={"source": "azure_alert", "action_group": "critical"}),
        _item("b", signal={"source": "azure_alert", "action_group": "info"}),
        _item("c", signal={"source": "azure_alert", "action_group": "info"}, self_resolved=True),
    ]
    result = build_digest(
        DigestCollection(window_start=NOW - timedelta(hours=6), window_end=NOW, items=items),
        use_llm=False,
    )
    assert "1 to review" in result.subject
    assert "1 self-resolved" in result.subject
    assert "1 critical (already paged)" in result.subject


def test_a_window_spanning_days_shows_both_dates():
    # A 72-hour manual run rendered "20 Aug 10:26-10:26 UTC" on the first real
    # run, which reads as a zero-length window.
    collection = DigestCollection(
        window_start=NOW - timedelta(hours=72), window_end=NOW, items=[_item("a")]
    )
    result = build_digest(collection, use_llm=False)
    assert "20 Aug 12:00–23 Aug 12:00 UTC" in result.subject


def test_render_digest_is_deterministic_for_the_same_result():
    collection = DigestCollection(
        window_start=NOW - timedelta(hours=6), window_end=NOW, items=[_item("a")]
    )
    result = build_digest(collection, use_llm=False)
    assert render_digest(result) == (result.subject, result.body)


# ---------------------------------------------------------------------------
# Delivery
# ---------------------------------------------------------------------------


def test_the_channel_is_read_off_the_deployed_action_group(monkeypatch):
    monkeypatch.setattr(ops_digest_delivery.settings, "OPS_DIGEST_TEAMS_WEBHOOK_URL", "")
    monkeypatch.setattr(ops_digest_delivery.settings, "OPS_DIGEST_EMAIL", "")
    monkeypatch.setattr(ops_digest_delivery.settings, "OPS_DIGEST_ACTION_GROUP", "ag-invoice-llm-dev")
    monkeypatch.setattr("services.azure_cost.arm_request", lambda *a, **k: ACTION_GROUP_PAYLOAD)
    monkeypatch.setattr("services.azure_cost.cost_scope", lambda: f"/subscriptions/{SUBSCRIPTION}")

    channel = resolve_critical_channel()
    assert channel.source == "action_group"
    assert channel.action_group_name == "ag-invoice-llm-dev"
    assert channel.email_addresses == ["application@infinevocloud.com"]
    assert len(channel.webhook_urls) == 1
    assert "powerautomate" in channel.webhook_urls[0]


def test_an_explicit_setting_overrides_the_action_group_lookup(monkeypatch):
    monkeypatch.setattr(
        ops_digest_delivery.settings, "OPS_DIGEST_TEAMS_WEBHOOK_URL", "https://example.test/hook"
    )
    monkeypatch.setattr(ops_digest_delivery.settings, "OPS_DIGEST_EMAIL", "")

    def _should_not_be_called(*_a, **_k):
        raise AssertionError("ARM must not be called when an override is set")

    monkeypatch.setattr("services.azure_cost.arm_request", _should_not_be_called)
    channel = resolve_critical_channel()
    assert channel.source == "settings"
    assert channel.webhook_urls == ["https://example.test/hook"]


def test_an_unreadable_action_group_returns_a_reason_not_an_exception(monkeypatch):
    monkeypatch.setattr(ops_digest_delivery.settings, "OPS_DIGEST_TEAMS_WEBHOOK_URL", "")
    monkeypatch.setattr(ops_digest_delivery.settings, "OPS_DIGEST_EMAIL", "")
    monkeypatch.setattr(ops_digest_delivery.settings, "OPS_DIGEST_ACTION_GROUP", "")

    def _boom(*_a, **_k):
        raise RuntimeError("403")

    monkeypatch.setattr("services.azure_cost.arm_request", _boom)
    monkeypatch.setattr("services.azure_cost.cost_scope", lambda: f"/subscriptions/{SUBSCRIPTION}")

    channel = resolve_critical_channel()
    assert channel.is_empty
    assert "403" in channel.error


def test_the_webhook_payload_is_the_common_alert_schema_the_receiver_expects():
    # The live receiver is registered with useCommonAlertSchema: true, so the
    # Power Automate flow on the other end parses data.essentials.*.
    payload = build_common_alert_schema_payload("Ops digest 23 Aug", "body text", now=NOW)
    assert payload["schemaId"] == "azureMonitorCommonAlertSchema"
    essentials = payload["data"]["essentials"]
    assert essentials["alertRule"] == "Ops digest 23 Aug"
    assert essentials["description"] == "body text"
    # A digest must not look like a page in the shared channel -- that is the
    # whole point of the two-tier split.
    assert essentials["severity"] == "Sev4"
    assert essentials["monitorCondition"] == "Resolved"


def test_delivery_sends_to_every_receiver_the_channel_holds(monkeypatch):
    channel = CriticalChannel(
        action_group_name="ag-invoice-llm-dev",
        webhook_urls=["https://example.test/hook?sig=SECRET"],
        email_addresses=["ops@example.test"],
        source="action_group",
    )
    posted = {}

    def _fake_post(url, payload):
        posted["url"] = url
        posted["payload"] = payload

    sent = {}

    def _fake_email(**kwargs):
        sent.update(kwargs)
        return {"status_code": 202}

    monkeypatch.setattr(ops_digest_delivery, "post_to_webhook", _fake_post)
    with patch("services.outbound_email.send_email", _fake_email):
        result = deliver_digest("subject", "body", channel=channel, mode=DELIVERY_AUTO)

    assert result.any_delivered
    assert posted["url"] == "https://example.test/hook?sig=SECRET"
    assert sent["subject"] == "subject"
    assert sent["to_addresses"] == ["ops@example.test"]
    # The credential in the URL never reaches the result object (and so never
    # reaches logs or telemetry).
    assert all("SECRET" not in entry for entry in result.delivered)


def test_a_failed_webhook_does_not_cost_the_email(monkeypatch):
    channel = CriticalChannel(
        webhook_urls=["https://example.test/hook"],
        email_addresses=["ops@example.test"],
        source="action_group",
    )

    def _boom(*_a, **_k):
        raise RuntimeError("flow returned 500")

    sent = {}
    monkeypatch.setattr(ops_digest_delivery, "post_to_webhook", _boom)
    with patch("services.outbound_email.send_email", lambda **kw: sent.update(kw)):
        result = deliver_digest("subject", "body", channel=channel, mode=DELIVERY_AUTO)

    assert any("flow returned 500" in error for error in result.errors)
    assert result.delivered == ["email:1"]
    assert sent["subject"] == "subject"


def test_mode_none_resolves_the_channel_but_posts_nothing(monkeypatch):
    channel = CriticalChannel(webhook_urls=["https://example.test/hook"], source="action_group")

    def _should_not_post(*_a, **_k):
        raise AssertionError("mode 'none' must not deliver")

    monkeypatch.setattr(ops_digest_delivery, "post_to_webhook", _should_not_post)
    result = deliver_digest("s", "b", channel=channel, mode=DELIVERY_NONE)
    assert result.delivered == []
    assert result.skipped


def test_a_channel_with_no_receivers_reports_rather_than_pretending_to_send():
    result = deliver_digest("s", "b", channel=CriticalChannel(), mode=DELIVERY_AUTO)
    assert result.delivered == []
    assert "no receivers resolved" in result.skipped[0]


# ---------------------------------------------------------------------------
# Telemetry
# ---------------------------------------------------------------------------


def test_the_run_event_is_the_only_durable_evidence_the_job_ran(caplog):
    with caplog.at_level(logging.INFO):
        track_ops_digest_run(
            window_hours=6.0,
            items_collected=5,
            critical_count=1,
            needs_decision_count=2,
            self_resolved_count=2,
            collection_errors=0,
            llm_calls=1,
            delivered_to="webhook:https://example.test/hook,email:1",
        )
    records = [r for r in caplog.records if r.getMessage() == OPS_DIGEST_EVENT_NAME]
    assert len(records) == 1
    record = records[0]
    assert getattr(record, "microsoft.custom_event.name") == OPS_DIGEST_EVENT_NAME
    assert record.critical_count == 1
    assert record.needs_decision_count == 2
    assert record.llm_calls == 1
    assert record.status == "success"


def test_a_run_that_could_not_deliver_is_recorded_as_an_error(caplog):
    with caplog.at_level(logging.INFO):
        track_ops_digest_run(
            window_hours=6.0,
            items_collected=1,
            critical_count=0,
            needs_decision_count=1,
            self_resolved_count=0,
            collection_errors=1,
            delivery_errors=1,
        )
    record = [r for r in caplog.records if r.getMessage() == OPS_DIGEST_EVENT_NAME][-1]
    assert record.status == "error"
