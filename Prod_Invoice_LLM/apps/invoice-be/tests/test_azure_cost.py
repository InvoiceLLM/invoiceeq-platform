"""Feature 20 Area 1 — unit tests for `services/azure_cost.py`.

Scope note, stated up front the same way `test_telemetry.py` does: these prove
the *mechanics* — that the request bodies this module sends are the exact shapes
that were confirmed to work against the live Cost Management API, that a
columnar response is parsed by column name rather than position, that throttling
is retried and an authorization failure is not, and that a partial collection
still yields the parts that succeeded. They do not prove Azure returns data;
that was verified separately by running `scripts/sweep_azure_cost.py` against the
real subscription (see `docs/feature_20_observability_monitoring_alerts.md`).

The recorded payloads below are trimmed copies of genuine 2026-08-23 responses
from `rg-invoice-llm-dev`, not invented shapes — including the details that are
easy to get wrong from the docs alone: `UsageDate` arrives as the *number*
20260805, `Cost` is column 0 rather than last, and the currency is INR.
"""
import logging
from datetime import date, datetime, timezone

import httpx
import pytest

import telemetry
from services import azure_cost
from services.azure_cost import (
    BudgetStatus,
    CostApiError,
    CostAuthError,
    CostConfigurationError,
    CostSnapshot,
    DailySpend,
    MonthEndForecast,
    SpendSlice,
)

SUBSCRIPTION = "2ae37d8b-3189-474c-9508-4b3d7ceec4dd"
RESOURCE_GROUP = "rg-invoice-llm-dev"
SCOPE = f"/subscriptions/{SUBSCRIPTION}/resourceGroups/{RESOURCE_GROUP}"


# Recorded 2026-08-23: POST .../Microsoft.CostManagement/query, Daily/MonthToDate.
DAILY_PAYLOAD = {
    "properties": {
        "columns": [
            {"name": "Cost", "type": "Number"},
            {"name": "UsageDate", "type": "Number"},
            {"name": "Currency", "type": "String"},
        ],
        "rows": [
            [276.177094783451, 20260805, "INR"],
            [799.760232442323, 20260806, "INR"],
            [617.854138504822, 20260807, "INR"],
        ],
    }
}

# Recorded 2026-08-23: same endpoint, grouped by ServiceName, granularity None.
SERVICE_PAYLOAD = {
    "properties": {
        "columns": [
            {"name": "Cost", "type": "Number"},
            {"name": "ServiceName", "type": "String"},
            {"name": "Currency", "type": "String"},
        ],
        "rows": [
            [3123.64205000001, "Azure Database for PostgreSQL", "INR"],
            [8490.33513780003, "Azure Container Apps", "INR"],
            [0.0, "Bandwidth", "INR"],
        ],
    }
}

# Recorded 2026-08-23: same endpoint, grouped by ResourceType. Deliberately a
# separate fixture from SERVICE_PAYLOAD — the grouping column is named after the
# dimension, so reusing the ServiceName payload here would parse every row as
# "unattributed" and quietly pass a test that proves nothing.
RESOURCE_TYPE_PAYLOAD = {
    "properties": {
        "columns": [
            {"name": "Cost", "type": "Number"},
            {"name": "ResourceType", "type": "String"},
            {"name": "Currency", "type": "String"},
        ],
        "rows": [
            [3123.64205000001, "microsoft.dbforpostgresql/flexibleservers", "INR"],
            [8490.30615585003, "microsoft.app/containerapps", "INR"],
            [0.0289819500000001, "microsoft.app/jobs", "INR"],
        ],
    }
}

# Recorded 2026-08-23: POST .../forecast with timeframe Custom. Note the extra
# CostStatus column, which the query endpoint does not return.
FORECAST_PAYLOAD = {
    "properties": {
        "columns": [
            {"name": "Cost", "type": "Number"},
            {"name": "UsageDate", "type": "Number"},
            {"name": "CostStatus", "type": "String"},
            {"name": "Currency", "type": "String"},
        ],
        "rows": [
            [1000.0, 20260821, "Actual", "INR"],
            [500.0, 20260822, "Actual", "INR"],
            [250.0, 20260823, "Forecast", "INR"],
            [250.0, 20260824, "Forecast", "INR"],
        ],
    }
}

# Recorded 2026-08-23: GET .../Microsoft.Consumption/budgets/budget-invoicellm-dev.
BUDGET_PAYLOAD = {
    "name": "budget-invoicellm-dev",
    "properties": {
        "amount": 150.0,
        "category": "Cost",
        "timeGrain": "Monthly",
        "currentSpend": {"amount": 16403.79877989607, "unit": "INR"},
        "forecastSpend": {"amount": 24601.013305754674, "unit": "INR"},
    },
}


@pytest.fixture(autouse=True)
def _configured(monkeypatch):
    """A configured scope and a canned bearer token for every test.

    `azure_cost` does `from config import settings`, so patching attributes on
    that singleton is enough — the same approach `conftest.py::mock_auth_disabled`
    uses for `dependencies.settings`.
    """
    monkeypatch.setattr(azure_cost.settings, "AZURE_SUBSCRIPTION_ID", SUBSCRIPTION)
    monkeypatch.setattr(azure_cost.settings, "AZURE_COST_RESOURCE_GROUP", RESOURCE_GROUP)
    monkeypatch.setattr(azure_cost.settings, "AZURE_COST_BUDGET_NAME", "")
    monkeypatch.setattr(azure_cost.settings, "AZURE_COST_ACCESS_TOKEN", "unit-test-token")
    monkeypatch.setattr(azure_cost.settings, "AZURE_COST_CLI_FALLBACK", False)
    azure_cost.reset_token_cache()
    yield
    azure_cost.reset_token_cache()


def _response(status: int, *, json_body=None, text: str = "", headers=None) -> httpx.Response:
    """A real httpx.Response, not a mock — `.json()`/`.text`/`.headers` behave."""
    if json_body is not None:
        return httpx.Response(status, json=json_body, headers=headers or {})
    return httpx.Response(status, text=text, headers=headers or {})


class _Recorder:
    """Stands in for `httpx.request`, recording every call it is handed.

    Replays the given responses in order, repeating the last one once the list
    runs out — fine for single-call tests, but see `_Router` for anything that
    involves retries.
    """

    def __init__(self, *responses):
        self._responses = list(responses)
        self.calls = []

    def __call__(self, method, url, **kwargs):
        self.calls.append({"method": method, "url": url, **kwargs})
        if len(self._responses) == 1:
            return self._responses[0]
        return self._responses.pop(0)


class _Router:
    """Stands in for `httpx.request`, answering by *what was asked for*.

    A positional queue is wrong for `collect_cost_snapshot()`: a retried call
    consumes the next queued response, so injecting one failure silently
    corrupts every later call's answer and the test asserts on nonsense. (That
    is not hypothetical — the first version of this file did exactly that, and
    the "resource type" assertions were passing against ServiceName data.)
    Routing on the request itself keeps a retry a retry.
    """

    def __init__(self, overrides=None):
        self.calls = []
        self.overrides = dict(overrides or {})

    @staticmethod
    def _classify(url, body):
        if "/budgets/" in url:
            return "budget"
        if "/forecast?" in url:
            return "forecast"
        grouping = ((body or {}).get("dataset") or {}).get("grouping") or []
        if grouping:
            return f"group:{grouping[0]['name']}"
        if (body or {}).get("timeframe") == "MonthToDate":
            return "mtd"
        return "trend"

    _DEFAULTS = {
        "budget": BUDGET_PAYLOAD,
        "forecast": FORECAST_PAYLOAD,
        "group:ServiceName": SERVICE_PAYLOAD,
        "group:ResourceType": RESOURCE_TYPE_PAYLOAD,
        "mtd": DAILY_PAYLOAD,
        "trend": DAILY_PAYLOAD,
    }

    def __call__(self, method, url, **kwargs):
        kind = self._classify(url, kwargs.get("json"))
        self.calls.append({"method": method, "url": url, "kind": kind, **kwargs})
        override = self.overrides.get(kind)
        if override is not None:
            return override
        return _response(200, json_body=self._DEFAULTS[kind])

    def kinds(self):
        return [call["kind"] for call in self.calls]


# ---------------------------------------------------------------------------
# Scope / configuration
# ---------------------------------------------------------------------------


def test_cost_scope_builds_a_resource_group_scope():
    assert azure_cost.cost_scope() == SCOPE
    assert azure_cost.is_configured() is True


def test_cost_scope_refuses_to_guess_when_unconfigured(monkeypatch):
    monkeypatch.setattr(azure_cost.settings, "AZURE_COST_RESOURCE_GROUP", "")
    with pytest.raises(CostConfigurationError):
        azure_cost.cost_scope()
    assert azure_cost.is_configured() is False


def test_budget_name_defaults_to_the_live_resource_not_a_derived_name():
    # `params.dev.json`'s namingPrefix would derive `budget-invoice-llm-dev`,
    # which does not exist. The deployed resource is this one.
    assert azure_cost.resolve_budget_name() == "budget-invoicellm-dev"


def test_budget_name_setting_overrides_the_default(monkeypatch):
    monkeypatch.setattr(azure_cost.settings, "AZURE_COST_BUDGET_NAME", "budget-other")
    assert azure_cost.resolve_budget_name() == "budget-other"


# ---------------------------------------------------------------------------
# Response parsing
# ---------------------------------------------------------------------------


def test_daily_rows_parse_the_numeric_usage_date_azure_actually_returns():
    rows = azure_cost._parse_daily_rows(DAILY_PAYLOAD)
    assert [r.usage_date for r in rows] == [date(2026, 8, 5), date(2026, 8, 6), date(2026, 8, 7)]
    assert rows[0].amount == pytest.approx(276.177094783451)
    assert {r.currency for r in rows} == {"INR"}


def test_daily_rows_are_parsed_by_column_name_not_position():
    """A different column order must not silently swap cost and date."""
    reordered = {
        "properties": {
            "columns": [
                {"name": "UsageDate", "type": "Number"},
                {"name": "Currency", "type": "String"},
                {"name": "Cost", "type": "Number"},
            ],
            "rows": [[20260810, "INR", 42.5]],
        }
    }
    rows = azure_cost._parse_daily_rows(reordered)
    assert rows == [DailySpend(usage_date=date(2026, 8, 10), amount=42.5, currency="INR")]


def test_daily_rows_are_sorted_ascending_regardless_of_response_order():
    scrambled = {
        "properties": {
            "columns": DAILY_PAYLOAD["properties"]["columns"],
            "rows": [[3.0, 20260807, "INR"], [1.0, 20260805, "INR"], [2.0, 20260806, "INR"]],
        }
    }
    assert [r.amount for r in azure_cost._parse_daily_rows(scrambled)] == [1.0, 2.0, 3.0]


def test_daily_rows_skip_rows_with_an_unparseable_date():
    broken = {
        "properties": {
            "columns": DAILY_PAYLOAD["properties"]["columns"],
            "rows": [[1.0, "not-a-date", "INR"], [2.0, 20260806, "INR"]],
        }
    }
    rows = azure_cost._parse_daily_rows(broken)
    assert len(rows) == 1 and rows[0].usage_date == date(2026, 8, 6)


def test_grouped_rows_sort_largest_first_and_carry_their_dimension():
    slices = azure_cost._parse_grouped_rows(SERVICE_PAYLOAD, azure_cost.DIMENSION_SERVICE_NAME)
    assert [s.name for s in slices] == [
        "Azure Container Apps",
        "Azure Database for PostgreSQL",
        "Bandwidth",
    ]
    assert {s.dimension for s in slices} == {"ServiceName"}


def test_grouped_rows_label_an_empty_dimension_value():
    payload = {
        "properties": {
            "columns": SERVICE_PAYLOAD["properties"]["columns"],
            "rows": [[5.0, "", "INR"]],
        }
    }
    assert azure_cost._parse_grouped_rows(payload, "ServiceName")[0].name == "unattributed"


def test_iso_usage_dates_also_parse():
    assert azure_cost._parse_usage_date("2026-08-05T00:00:00") == date(2026, 8, 5)
    assert azure_cost._parse_usage_date(None) is None
    assert azure_cost._parse_usage_date("") is None


# ---------------------------------------------------------------------------
# Authentication
# ---------------------------------------------------------------------------


def test_explicit_token_setting_short_circuits_every_other_credential(monkeypatch):
    def _explode():  # pragma: no cover - must never be reached
        raise AssertionError("managed identity should not be consulted")

    monkeypatch.setattr(azure_cost, "_fetch_managed_identity_token", _explode)
    assert azure_cost._acquire_token() == "unit-test-token"


def test_managed_identity_token_is_read_from_the_container_apps_endpoint(monkeypatch):
    monkeypatch.setattr(azure_cost.settings, "AZURE_COST_ACCESS_TOKEN", "")
    monkeypatch.setenv("IDENTITY_ENDPOINT", "http://localhost:42356/msi/token")
    monkeypatch.setenv("IDENTITY_HEADER", "secret-header-value")
    monkeypatch.setenv("AZURE_CLIENT_ID", "1c0e1f4c-a832-4c06-8d5b-41942aa09e93")

    captured = {}

    def fake_get(url, params=None, headers=None, timeout=None):
        captured["url"] = url
        captured["params"] = params
        captured["headers"] = headers
        return _response(200, json_body={"access_token": "msi-token", "expires_in": 3600})

    monkeypatch.setattr(azure_cost.httpx, "get", fake_get)

    assert azure_cost._acquire_token() == "msi-token"
    assert captured["url"] == "http://localhost:42356/msi/token"
    # The user-assigned identity must be selected explicitly: this app has no
    # system-assigned identity, so an unqualified request would fail.
    assert captured["params"]["client_id"] == "1c0e1f4c-a832-4c06-8d5b-41942aa09e93"
    assert captured["params"]["resource"] == azure_cost.ARM_RESOURCE
    assert captured["headers"]["X-IDENTITY-HEADER"] == "secret-header-value"


def test_managed_identity_token_is_cached_across_calls(monkeypatch):
    monkeypatch.setattr(azure_cost.settings, "AZURE_COST_ACCESS_TOKEN", "")
    monkeypatch.setenv("IDENTITY_ENDPOINT", "http://localhost:42356/msi/token")
    monkeypatch.setenv("IDENTITY_HEADER", "secret")
    calls = {"n": 0}

    def fake_get(url, params=None, headers=None, timeout=None):
        calls["n"] += 1
        return _response(200, json_body={"access_token": "msi-token", "expires_in": 3600})

    monkeypatch.setattr(azure_cost.httpx, "get", fake_get)
    azure_cost._acquire_token()
    azure_cost._acquire_token()
    assert calls["n"] == 1


def test_no_credential_raises_a_message_naming_the_missing_role(monkeypatch):
    monkeypatch.setattr(azure_cost.settings, "AZURE_COST_ACCESS_TOKEN", "")
    monkeypatch.delenv("IDENTITY_ENDPOINT", raising=False)
    monkeypatch.delenv("IDENTITY_HEADER", raising=False)
    monkeypatch.setattr(azure_cost, "_fetch_managed_identity_token", lambda: None)

    with pytest.raises(CostAuthError) as excinfo:
        azure_cost._acquire_token()
    assert "Cost Management Reader" in str(excinfo.value)


def test_cli_fallback_is_off_by_default(monkeypatch):
    """Fail-closed: never authenticate as whoever last ran `az login`."""
    called = {"n": 0}
    monkeypatch.setattr(
        azure_cost.subprocess,
        "run",
        lambda *a, **k: called.__setitem__("n", called["n"] + 1),
    )
    assert azure_cost._fetch_cli_token() is None
    assert called["n"] == 0


# ---------------------------------------------------------------------------
# HTTP behaviour
# ---------------------------------------------------------------------------


def test_throttling_is_retried_and_honours_retry_after(monkeypatch):
    recorder = _Recorder(
        _response(429, text="throttled", headers={"Retry-After": "7"}),
        _response(200, json_body=DAILY_PAYLOAD),
    )
    slept = []
    monkeypatch.setattr(azure_cost.httpx, "request", recorder)
    monkeypatch.setattr(azure_cost.time, "sleep", slept.append)

    payload = azure_cost._request_with_retry("POST", "https://example/query", json_body={})
    assert payload == DAILY_PAYLOAD
    assert slept == [7.0]
    assert len(recorder.calls) == 2


def test_authorization_failure_is_raised_immediately_not_retried(monkeypatch):
    recorder = _Recorder(_response(403, text='{"error":{"code":"AuthorizationFailed"}}'))
    monkeypatch.setattr(azure_cost.httpx, "request", recorder)
    monkeypatch.setattr(azure_cost.time, "sleep", lambda _s: None)

    with pytest.raises(CostApiError) as excinfo:
        azure_cost._request_with_retry("POST", "https://example/query", json_body={})
    # The message has to say what to actually do about it — this is the exact
    # failure a missing role assignment produces.
    assert "Cost Management Reader" in str(excinfo.value)
    assert len(recorder.calls) == 1


def test_the_transient_gtm_404_is_retried_but_a_real_404_is_not(monkeypatch):
    """Observed live 2026-08-23 on a ResourceType grouping that worked minutes earlier."""
    transient = _response(
        404,
        text='{"error":{"code":"NotFound","message":"GtmDimensionDataProvider.'
        'GetAzureSubscriptionsById returns null or empty list"}}',
    )
    recorder = _Recorder(transient, _response(200, json_body=SERVICE_PAYLOAD))
    monkeypatch.setattr(azure_cost.httpx, "request", recorder)
    monkeypatch.setattr(azure_cost.time, "sleep", lambda _s: None)
    assert azure_cost._request_with_retry("POST", "https://example/query") == SERVICE_PAYLOAD
    assert len(recorder.calls) == 2

    plain = _Recorder(_response(404, text='{"error":{"code":"NotFound","message":"no budget"}}'))
    monkeypatch.setattr(azure_cost.httpx, "request", plain)
    with pytest.raises(CostApiError):
        azure_cost._request_with_retry("GET", "https://example/budgets/x")
    assert len(plain.calls) == 1


def test_retries_are_bounded(monkeypatch):
    recorder = _Recorder(_response(429, text="throttled"))
    monkeypatch.setattr(azure_cost.httpx, "request", recorder)
    monkeypatch.setattr(azure_cost.time, "sleep", lambda _s: None)
    with pytest.raises(CostApiError):
        azure_cost._request_with_retry("POST", "https://example/query", json_body={})
    assert len(recorder.calls) == azure_cost.MAX_ATTEMPTS


# ---------------------------------------------------------------------------
# Request shapes — these guard the payloads verified against the live API
# ---------------------------------------------------------------------------


def test_month_to_date_query_sends_the_verified_request_shape(monkeypatch):
    recorder = _Recorder(_response(200, json_body=DAILY_PAYLOAD))
    monkeypatch.setattr(azure_cost.httpx, "request", recorder)

    rows = azure_cost.get_month_to_date_daily_spend()
    call = recorder.calls[0]
    assert call["method"] == "POST"
    assert call["url"].endswith(
        f"{SCOPE}/providers/Microsoft.CostManagement/query"
        f"?api-version={azure_cost.COST_MANAGEMENT_API_VERSION}"
    )
    body = call["json"]
    assert body["timeframe"] == "MonthToDate"
    assert body["dataset"]["granularity"] == "Daily"
    assert body["dataset"]["aggregation"]["totalCost"] == {"name": "Cost", "function": "Sum"}
    assert call["headers"]["Authorization"] == "Bearer unit-test-token"
    assert len(rows) == 3


def test_grouped_query_sends_a_dimension_grouping_with_no_granularity(monkeypatch):
    recorder = _Recorder(_response(200, json_body=SERVICE_PAYLOAD))
    monkeypatch.setattr(azure_cost.httpx, "request", recorder)

    azure_cost.get_spend_by_dimension(azure_cost.DIMENSION_RESOURCE_TYPE)
    body = recorder.calls[0]["json"]
    assert body["dataset"]["granularity"] == "None"
    assert body["dataset"]["grouping"] == [{"type": "Dimension", "name": "ResourceType"}]


def test_rolling_window_query_uses_a_custom_timeframe(monkeypatch):
    recorder = _Recorder(_response(200, json_body=DAILY_PAYLOAD))
    monkeypatch.setattr(azure_cost.httpx, "request", recorder)

    azure_cost.get_daily_spend(days=7)
    body = recorder.calls[0]["json"]
    assert body["timeframe"] == "Custom"
    start = datetime.fromisoformat(body["timePeriod"]["from"]).date()
    end = datetime.fromisoformat(body["timePeriod"]["to"]).date()
    assert (end - start).days == 6  # 7 days inclusive


def test_forecast_never_uses_month_to_date(monkeypatch):
    """Regression guard for a real API rejection.

    The forecast endpoint answers `BadRequest: Invalid dataset grouping:
    'BillingPeriod'` for `timeframe: MonthToDate`, even though the query endpoint
    accepts it. Confirmed live 2026-08-23; `Custom` is the shape that works.
    """
    recorder = _Recorder(_response(200, json_body=FORECAST_PAYLOAD))
    monkeypatch.setattr(azure_cost.httpx, "request", recorder)

    forecast = azure_cost.get_month_end_forecast()
    call = recorder.calls[0]
    assert "/forecast?api-version=" in call["url"]
    assert call["json"]["timeframe"] == "Custom"
    assert call["json"]["includeActualCost"] is True
    assert forecast is not None
    # Actual and Forecast rows are separated, and the projection is their sum.
    assert forecast.actual_to_date == pytest.approx(1500.0)
    assert forecast.forecast_remaining == pytest.approx(500.0)
    assert forecast.projected_total == pytest.approx(2000.0)
    assert forecast.currency == "INR"
    assert forecast.month_start.day == 1


def test_forecast_returns_none_when_the_response_has_no_rows(monkeypatch):
    empty = {"properties": {"columns": FORECAST_PAYLOAD["properties"]["columns"], "rows": []}}
    monkeypatch.setattr(azure_cost.httpx, "request", _Recorder(_response(200, json_body=empty)))
    assert azure_cost.get_month_end_forecast() is None


# ---------------------------------------------------------------------------
# Budget
# ---------------------------------------------------------------------------


def test_budget_status_reads_the_services_own_spend_and_forecast(monkeypatch):
    recorder = _Recorder(_response(200, json_body=BUDGET_PAYLOAD))
    monkeypatch.setattr(azure_cost.httpx, "request", recorder)

    budget = azure_cost.get_budget_status()
    assert recorder.calls[0]["method"] == "GET"
    assert "budget-invoicellm-dev" in recorder.calls[0]["url"]
    # Pinned to the same api-version `infra/10-budget.bicep` writes with.
    assert f"api-version={azure_cost.CONSUMPTION_API_VERSION}" in recorder.calls[0]["url"]
    assert budget.amount == 150.0
    assert budget.current_spend == pytest.approx(16403.79877989607)
    assert budget.forecast_spend == pytest.approx(24601.013305754674)
    # The unit is INR, not USD — the budget's `amount: 150` is 150 *rupees*,
    # which is why this reads as 10,935% used against a $300-shaped intent.
    assert budget.currency == "INR"
    assert budget.percent_used == pytest.approx(10935.87, rel=1e-4)
    assert budget.percent_forecast == pytest.approx(16400.68, rel=1e-4)


def test_budget_status_is_none_when_the_budget_does_not_exist(monkeypatch):
    monkeypatch.setattr(
        azure_cost.httpx,
        "request",
        _Recorder(_response(404, text='{"error":{"code":"NotFound","message":"no such budget"}}')),
    )
    assert azure_cost.get_budget_status() is None


def test_budget_percentages_are_none_when_the_budget_amount_is_zero():
    budget = BudgetStatus("b", 0.0, 10.0, 20.0, "INR", "Monthly")
    assert budget.percent_used is None and budget.percent_forecast is None


# ---------------------------------------------------------------------------
# Snapshot
# ---------------------------------------------------------------------------


def test_collect_cost_snapshot_assembles_everything(monkeypatch):
    router = _Router()
    monkeypatch.setattr(azure_cost.httpx, "request", router)

    snapshot = azure_cost.collect_cost_snapshot()
    assert router.kinds() == [
        "mtd",
        "trend",
        "group:ServiceName",
        "group:ResourceType",
        "forecast",
        "budget",
    ]
    assert snapshot.scope == SCOPE
    assert snapshot.currency == "INR"
    assert snapshot.month_to_date_total == pytest.approx(276.177094783451 + 799.760232442323 + 617.854138504822)
    assert snapshot.by_service[0].name == "Azure Container Apps"
    assert snapshot.by_resource_type[0].name == "microsoft.app/containerapps"
    assert snapshot.by_resource_type[0].dimension == "ResourceType"
    assert snapshot.budget.name == "budget-invoicellm-dev"
    assert snapshot.forecast.projected_total == pytest.approx(2000.0)
    assert snapshot.errors == []
    assert snapshot.to_dict()["daily"][0]["usage_date"] == "2026-08-05"


def test_a_failed_call_costs_one_section_not_the_whole_snapshot(monkeypatch):
    """The reason `errors` is a field and not an exception."""
    router = _Router({"group:ResourceType": _response(500, text="server error")})
    monkeypatch.setattr(azure_cost.httpx, "request", router)
    monkeypatch.setattr(azure_cost.time, "sleep", lambda _s: None)

    snapshot = azure_cost.collect_cost_snapshot()
    assert snapshot.by_resource_type == []
    assert any("by_resource_type" in error for error in snapshot.errors)
    # Everything else still made it — including the two calls that come *after*
    # the failing one.
    assert snapshot.by_service and snapshot.month_to_date_total > 0
    assert snapshot.budget is not None and snapshot.forecast is not None
    assert snapshot.currency == "INR"


def test_a_missing_budget_still_yields_a_usable_snapshot(monkeypatch):
    """The live shape before the Cost Management Reader role is deployed."""
    router = _Router(
        {"budget": _response(404, text='{"error":{"code":"NotFound","message":"no budget"}}')}
    )
    monkeypatch.setattr(azure_cost.httpx, "request", router)

    snapshot = azure_cost.collect_cost_snapshot()
    assert snapshot.budget is None
    assert snapshot.errors == []  # a missing budget is not an error, it is None
    assert snapshot.month_to_date_total > 0


def test_collect_cost_snapshot_raises_only_on_an_unusable_scope(monkeypatch):
    monkeypatch.setattr(azure_cost.settings, "AZURE_SUBSCRIPTION_ID", "")
    with pytest.raises(CostConfigurationError):
        azure_cost.collect_cost_snapshot()


def _snapshot_with_days(amounts):
    return CostSnapshot(
        scope=SCOPE,
        currency="INR",
        generated_at=datetime.now(timezone.utc),
        daily=[
            DailySpend(usage_date=date(2026, 8, 10 + i), amount=amount, currency="INR")
            for i, amount in enumerate(amounts)
        ],
    )


def test_day_over_day_ignores_the_still_accruing_latest_day():
    # 100 -> 150 between the last two *complete* days is +50%; the trailing 5.0
    # is today's partial figure and must not be treated as a 97% crash.
    assert _snapshot_with_days([100.0, 150.0, 5.0]).day_over_day_change_pct == pytest.approx(50.0)


def test_day_over_day_needs_three_days_before_it_reports_anything():
    assert _snapshot_with_days([100.0, 150.0]).day_over_day_change_pct is None
    assert _snapshot_with_days([]).day_over_day_change_pct is None


def test_day_over_day_is_none_when_the_baseline_day_is_zero():
    assert _snapshot_with_days([0.0, 10.0, 5.0]).day_over_day_change_pct is None


# ---------------------------------------------------------------------------
# Telemetry emission
# ---------------------------------------------------------------------------


def _events(caplog, name):
    return [r for r in caplog.records if r.getMessage() == name]


def _full_snapshot():
    snapshot = _snapshot_with_days([100.0, 150.0, 5.0])
    snapshot.month_to_date_total = 255.0
    snapshot.by_service = [
        SpendSlice("ServiceName", "Azure Container Apps", 8490.34, "INR"),
        SpendSlice("ServiceName", "Bandwidth", 0.0, "INR"),
    ]
    snapshot.by_resource_type = [
        SpendSlice("ResourceType", "microsoft.app/containerapps", 8490.31, "INR"),
    ]
    snapshot.budget = BudgetStatus("budget-invoicellm-dev", 150.0, 16403.8, 24601.01, "INR", "Monthly")
    snapshot.forecast = MonthEndForecast(2000.0, 1500.0, 500.0, "INR", date(2026, 8, 1), date(2026, 8, 31))
    return snapshot


def test_emit_cost_snapshot_telemetry_emits_one_snapshot_and_one_row_per_slice(caplog):
    with caplog.at_level(logging.INFO):
        emitted = azure_cost.emit_cost_snapshot_telemetry(_full_snapshot())

    # 1 snapshot + 1 service (the 0.00 Bandwidth row is skipped) + 1 resource type
    assert emitted == 3
    snapshots = _events(caplog, telemetry.AZURE_COST_SNAPSHOT_EVENT_NAME)
    slices = _events(caplog, telemetry.AZURE_COST_SLICE_EVENT_NAME)
    assert len(snapshots) == 1 and len(slices) == 2

    record = snapshots[0]
    # The attribute the Azure Monitor exporter branches on to route this to
    # customEvents rather than traces.
    assert getattr(record, "microsoft.custom_event.name") == telemetry.AZURE_COST_SNAPSHOT_EVENT_NAME
    assert record.month_to_date_total == 255.0
    assert record.currency == "INR"
    assert record.budget_amount == 150.0
    assert record.budget_current_spend == 16403.8
    assert record.forecast_projected_total == 2000.0
    assert record.day_over_day_change_pct == pytest.approx(50.0)
    assert record.latest_day == "2026-08-12"
    assert record.collection_errors == 0
    assert record.extra_fields["scope"] == SCOPE

    # Both dimensions are distinguishable, so a KQL sum() cannot double-count
    # the service view against the resource-type view.
    assert {r.dimension for r in slices} == {"ServiceName", "ResourceType"}
    # `name` is a reserved LogRecord attribute — emitting the slice label under
    # that key makes `logging` raise inside an emitter that swallows by
    # contract, i.e. the event vanishes silently. This assertion is the guard.
    assert {r.dimension_value for r in slices} == {
        "Azure Container Apps",
        "microsoft.app/containerapps",
    }


def test_zero_cost_slices_are_not_paid_for_in_log_analytics_ingestion(caplog):
    with caplog.at_level(logging.INFO):
        azure_cost.emit_cost_snapshot_telemetry(_full_snapshot())
    names = {r.dimension_value for r in _events(caplog, telemetry.AZURE_COST_SLICE_EVENT_NAME)}
    assert "Bandwidth" not in names


def test_top_slices_bounds_the_per_run_event_count(caplog):
    snapshot = _full_snapshot()
    snapshot.by_service = [SpendSlice("ServiceName", f"svc-{i}", float(i + 1), "INR") for i in range(30)]
    with caplog.at_level(logging.INFO):
        emitted = azure_cost.emit_cost_snapshot_telemetry(snapshot, top_slices=5)
    assert emitted == 1 + 5 + 1


def test_an_absent_budget_is_absent_from_the_event_not_reported_as_zero(caplog):
    snapshot = _full_snapshot()
    snapshot.budget = None
    snapshot.forecast = None
    snapshot.errors = ["budget: throttled"]
    with caplog.at_level(logging.INFO):
        azure_cost.emit_cost_snapshot_telemetry(snapshot)

    record = _events(caplog, telemetry.AZURE_COST_SNAPSHOT_EVENT_NAME)[0]
    # A 0 here would render "well under budget" on a panel with no data behind it.
    assert not hasattr(record, "budget_amount")
    assert not hasattr(record, "forecast_projected_total")
    assert record.collection_errors == 1


def test_a_broken_telemetry_emitter_cannot_break_a_collection_run(monkeypatch, caplog):
    def _explode(**kwargs):
        raise RuntimeError("exporter down")

    monkeypatch.setattr(telemetry, "_emit_event", lambda *a, **k: _explode())
    # Must not raise: cost collection is instrumentation, never a critical path.
    telemetry.track_azure_cost_snapshot(scope=SCOPE, currency="INR", month_to_date_total=1.0)
    telemetry.track_azure_cost_slice(
        dimension="ServiceName", dimension_value="x", amount=1.0, currency="INR"
    )
