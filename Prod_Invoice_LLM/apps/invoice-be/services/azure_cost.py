"""Feature 20 Area 1 — real Azure infrastructure spend, from the Cost Management API.

Why this module exists
---------------------
Until this file, the only "cost" telemetry in this application was
``telemetry.track_agent_call()``'s ``llm_agent_call`` events, which measure LLM
*token* usage and nothing else. That is a single line item. The actual Azure bill
for this product is dominated by things no LLM event can see: Container Apps
compute, PostgreSQL, Container Registry, Log Analytics ingestion, Redis, storage.
On the live dev environment, measured 2026-08-23 through this module, Container
Apps alone is ~8,490 INR month-to-date against ~462 INR of Foundry Models (the
Azure OpenAI line) — i.e. the pre-existing telemetry was watching roughly 3% of
the spend. This module reads the other 97%.

What it talks to (all three verified live on 2026-08-23, not assumed)
---------------------------------------------------------------------
Scope is a resource group: ``/subscriptions/{sub}/resourceGroups/{rg}``.

1. ``POST {scope}/providers/Microsoft.CostManagement/query?api-version=2023-03-01``
   * ``granularity: Daily`` + ``timeframe: MonthToDate`` → the daily trend.
   * ``granularity: None`` + ``grouping: [ServiceName | ResourceType]`` → the breakdowns.
   * Response is columnar: ``properties.columns`` (name/type) + ``properties.rows``
     (arrays in that column order). Column order is read by *name*, never by
     index, because it differs per query shape — the daily query returns
     ``[Cost, UsageDate, Currency]``, the grouped one ``[Cost, ServiceName, Currency]``.
   * ``UsageDate`` comes back as a *number* (``20260805``), not a date string.

2. ``POST {scope}/providers/Microsoft.CostManagement/forecast?api-version=2023-03-01``
   * ``timeframe: MonthToDate`` **is rejected** here even though the query endpoint
     accepts it — the service answers ``BadRequest: Invalid dataset grouping:
     'BillingPeriod'``. The working shape, and therefore the one below, is
     ``timeframe: Custom`` with an explicit first-of-month → last-of-month
     ``timePeriod``. Rows carry an extra ``CostStatus`` column valued
     ``Actual`` or ``Forecast``, so a month-end projection is the sum of both and
     the remaining-spend estimate is the sum of the ``Forecast`` rows only.

3. ``GET {scope}/providers/Microsoft.Consumption/budgets/{name}?api-version=2023-11-01``
   * The same budget ``infra/10-budget.bicep`` deploys. Returns ``amount``,
     ``currentSpend`` and ``forecastSpend`` in one call, which is why
     forecast-vs-budget does not depend on (2) succeeding.
   * Same api-version the bicep pins, so this cannot drift from the resource.

Currency is whatever the billing account bills in and is *not* USD here: every
call above returns ``INR``. It is therefore carried on every dataclass and every
telemetry event rather than being assumed anywhere — including in the budget
comparison, where ``budget-invoicellm-dev``'s ``amount: 150`` is 150 INR, not
150 USD (see ``BudgetStatus.percent_used``).

Authentication
--------------
This repo had **no** managed-identity code at all before this module (a
repo-wide grep for ``azure.identity`` / ``DefaultAzureCredential`` returns
nothing; ``services/storage.py`` uses a connection string, the AI clients use
API keys). Rather than add ``azure-identity`` + ``azure-mgmt-costmanagement`` to
``pyproject.toml`` — two new dependencies and a ``uv.lock`` regeneration for what
is three HTTP calls — this uses ``httpx`` (already a dependency) directly against
the documented IMDS/Container-Apps token endpoints. ``_fetch_managed_identity_token()``
is a deliberate single seam: swapping it for ``ManagedIdentityCredential`` later
is a one-function change.

``_acquire_token()`` tries, in order:

1. ``settings.AZURE_COST_ACCESS_TOKEN`` — an explicitly supplied bearer token.
   For one-off local checks and for the test suite; never set in the containers.
2. **Managed identity** — the production path. Container Apps injects
   ``IDENTITY_ENDPOINT``/``IDENTITY_HEADER``; a VM/IMDS environment exposes
   ``169.254.169.254``. Both are tried, in that order, with ``AZURE_CLIENT_ID``
   (already wired into ``modules/compute/scheduled-job.bicep``) selecting the
   user-assigned identity.
3. ``az account get-access-token`` — local developer convenience only, and
   **off by default** (``AZURE_COST_CLI_FALLBACK``). Fail-closed for the same
   reason ``ALLOW_MOCK_AUTH`` is: a deployment that forgot to configure itself
   should raise, not silently authenticate as whoever last ran ``az login``.

**Managed identity needs an RBAC grant that is not deployed yet.** The role is
``Cost Management Reader`` (``72fafb9e-0641-4937-9268-a91bfd8191a3``) at resource-group
scope: verified live, the two operations this module calls register as
``Microsoft.CostManagement/query/read`` and ``Microsoft.CostManagement/forecast/read``
(``/read``, despite being HTTP POSTs), both covered by that role's
``Microsoft.CostManagement/*/read``, and budgets by its ``Microsoft.Consumption/*/read``.
``infra/modules/security/rbac-assignments.bicep`` now declares it; until Stage 7 is
redeployed, ``id-invoicellm-dev`` holds no cost role and path (2) will 401/403.

Rate limiting is not an edge case here
--------------------------------------
The Cost Management API is aggressively throttled per-subscription — roughly half
the exploratory calls made while building this returned ``429`` — so
``_request_with_retry()`` honours ``Retry-After`` (or ``x-ms-ratelimit-microsoft.
costmanagement-*``) and backs off rather than treating a 429 as a failure. This is
also why the intended cadence is a daily scheduled job, not a per-request lookup.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import time
from calendar import monthrange
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Sequence, Tuple

import httpx

from config import settings

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# API contract constants — every one of these was confirmed against the live
# subscription on 2026-08-23 before being written down.
# ---------------------------------------------------------------------------

ARM_ENDPOINT = "https://management.azure.com"
ARM_SCOPE = "https://management.azure.com/.default"
ARM_RESOURCE = "https://management.azure.com/"

#: Cost Management query + forecast. Same version for both endpoints.
COST_MANAGEMENT_API_VERSION = "2023-03-01"

#: Budgets. Deliberately identical to `Microsoft.Consumption/budgets@2023-11-01`
#: in `infra/10-budget.bicep` so the reader and the writer of that resource
#: cannot drift apart.
CONSUMPTION_API_VERSION = "2023-11-01"

#: Container Apps / App Service style MSI endpoint (IDENTITY_ENDPOINT).
MSI_APP_SERVICE_API_VERSION = "2019-08-01"
#: IMDS style MSI endpoint (169.254.169.254).
IMDS_ENDPOINT = "http://169.254.169.254/metadata/identity/oauth2/token"
IMDS_API_VERSION = "2018-02-01"

#: Dimensions this module knows how to group by. Both verified to return rows.
DIMENSION_SERVICE_NAME = "ServiceName"
DIMENSION_RESOURCE_TYPE = "ResourceType"

DEFAULT_TREND_DAYS = 30

#: Per-request budget. A grouped query over a month of data answers in ~2-4s;
#: 60s leaves headroom without letting a scheduled job hang on a stalled call.
REQUEST_TIMEOUT_SECONDS = 60.0

#: 429 is routine on this API (see module docstring), so retries are the normal
#: path, not an exception path. Ceiling on total added wait ≈ 15+30+60 = 105s.
MAX_ATTEMPTS = 4
INITIAL_BACKOFF_SECONDS = 15.0
MAX_BACKOFF_SECONDS = 120.0

#: Refresh a cached token this far before it actually expires.
TOKEN_EXPIRY_SKEW_SECONDS = 300


class AzureCostError(Exception):
    """Base class for every failure this module raises."""


class CostConfigurationError(AzureCostError):
    """Subscription/resource group not configured — nothing to query."""


class CostAuthError(AzureCostError):
    """No usable bearer token could be obtained for management.azure.com."""


class CostApiError(AzureCostError):
    """The Cost Management / Consumption API returned an error response."""


# ---------------------------------------------------------------------------
# Result shapes
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DailySpend:
    """One day of actual spend for the whole scope."""

    usage_date: date
    amount: float
    currency: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "usage_date": self.usage_date.isoformat(),
            "amount": round(self.amount, 4),
            "currency": self.currency,
        }


@dataclass(frozen=True)
class SpendSlice:
    """Spend attributed to one value of one grouping dimension.

    ``dimension`` travels with the value so a consumer holding a mixed list (or a
    telemetry table holding rows from both breakdowns) can always tell an
    ``Azure Container Apps`` service row from a ``microsoft.app/containerapps``
    resource-type row.
    """

    dimension: str
    name: str
    amount: float
    currency: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "dimension": self.dimension,
            "name": self.name,
            "amount": round(self.amount, 4),
            "currency": self.currency,
        }


@dataclass(frozen=True)
class BudgetStatus:
    """The live `Microsoft.Consumption/budgets` resource, as read back.

    ``current_spend``/``forecast_spend`` are the service's own numbers, not
    recomputed here — they are what the budget's 80%-actual and 100%-forecasted
    notifications actually fire on, so a dashboard showing anything else would
    disagree with the emails the founder receives.
    """

    name: str
    amount: float
    current_spend: float
    forecast_spend: float
    currency: str
    time_grain: str

    @property
    def percent_used(self) -> Optional[float]:
        if not self.amount:
            return None
        return round(self.current_spend / self.amount * 100.0, 2)

    @property
    def percent_forecast(self) -> Optional[float]:
        if not self.amount:
            return None
        return round(self.forecast_spend / self.amount * 100.0, 2)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "amount": round(self.amount, 4),
            "current_spend": round(self.current_spend, 4),
            "forecast_spend": round(self.forecast_spend, 4),
            "currency": self.currency,
            "time_grain": self.time_grain,
            "percent_used": self.percent_used,
            "percent_forecast": self.percent_forecast,
        }


@dataclass(frozen=True)
class MonthEndForecast:
    """Projection for the calendar month the run happens in.

    ``projected_total`` is actual-so-far plus forecast-remaining, because that is
    the number comparable to a monthly budget; ``forecast_remaining`` is kept
    separately so a panel can shade the projected part of a trend differently
    from the measured part.
    """

    projected_total: float
    actual_to_date: float
    forecast_remaining: float
    currency: str
    month_start: date
    month_end: date

    def to_dict(self) -> Dict[str, Any]:
        return {
            "projected_total": round(self.projected_total, 4),
            "actual_to_date": round(self.actual_to_date, 4),
            "forecast_remaining": round(self.forecast_remaining, 4),
            "currency": self.currency,
            "month_start": self.month_start.isoformat(),
            "month_end": self.month_end.isoformat(),
        }


@dataclass
class CostSnapshot:
    """Everything Area 1 needs, from one collection run.

    ``errors`` is a first-class field rather than an exception: a budget that has
    not been deployed yet, or a forecast call that lost a 429 race, must not
    discard a perfectly good spend breakdown that was already fetched. A consumer
    (or the Ops Digest Agent) can then say "cost data, minus the budget" instead
    of "no cost data".
    """

    scope: str
    currency: str
    generated_at: datetime
    month_to_date_total: float = 0.0
    daily: List[DailySpend] = field(default_factory=list)
    by_service: List[SpendSlice] = field(default_factory=list)
    by_resource_type: List[SpendSlice] = field(default_factory=list)
    budget: Optional[BudgetStatus] = None
    forecast: Optional[MonthEndForecast] = None
    errors: List[str] = field(default_factory=list)

    @property
    def latest_day(self) -> Optional[DailySpend]:
        return self.daily[-1] if self.daily else None

    @property
    def day_over_day_change_pct(self) -> Optional[float]:
        """Percent change between the two most recent *complete-ish* days.

        Uses days -2 and -3 rather than -1 and -2 on purpose: Azure's most recent
        usage day is always partial and still accruing, so comparing it against a
        finished day reports a fabricated crash in spend every single morning.
        Needs three days of data before it reports anything at all.
        """
        if len(self.daily) < 3:
            return None
        previous, latest = self.daily[-3], self.daily[-2]
        if not previous.amount:
            return None
        return round((latest.amount - previous.amount) / previous.amount * 100.0, 2)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "scope": self.scope,
            "currency": self.currency,
            "generated_at": self.generated_at.isoformat(),
            "month_to_date_total": round(self.month_to_date_total, 4),
            "day_over_day_change_pct": self.day_over_day_change_pct,
            "daily": [d.to_dict() for d in self.daily],
            "by_service": [s.to_dict() for s in self.by_service],
            "by_resource_type": [s.to_dict() for s in self.by_resource_type],
            "budget": self.budget.to_dict() if self.budget else None,
            "forecast": self.forecast.to_dict() if self.forecast else None,
            "errors": list(self.errors),
        }


# ---------------------------------------------------------------------------
# Scope + configuration
# ---------------------------------------------------------------------------


def resolve_budget_name() -> str:
    """Name of the budget to read.

    Defaults to the *live* name (``budget-invoicellm-dev``) rather than deriving
    it from a naming prefix: `infra/params.dev.json` sets ``namingPrefix`` to
    ``invoice-llm``, which would produce ``budget-invoice-llm-dev``, but the
    resource actually deployed is ``budget-invoicellm-dev`` in
    ``rg-invoice-llm-dev``. Deriving would silently 404 against the real
    environment, so the real name is the default and the setting is the override.
    """
    return settings.AZURE_COST_BUDGET_NAME or "budget-invoicellm-dev"


def cost_scope() -> str:
    """ARM scope string every call in this module is made against.

    Resource-group scope, not subscription: this product owns exactly one
    resource group, and an RG-scoped query needs only an RG-scoped role
    assignment — the narrower grant of the two.
    """
    subscription_id = (settings.AZURE_SUBSCRIPTION_ID or "").strip()
    resource_group = (settings.AZURE_COST_RESOURCE_GROUP or "").strip()
    if not subscription_id or not resource_group:
        raise CostConfigurationError(
            "AZURE_SUBSCRIPTION_ID and AZURE_COST_RESOURCE_GROUP must both be set "
            "before Azure cost data can be queried."
        )
    return f"/subscriptions/{subscription_id}/resourceGroups/{resource_group}"


def is_configured() -> bool:
    """True when a scope can be built. Lets a caller skip cleanly, not crash."""
    try:
        cost_scope()
    except CostConfigurationError:
        return False
    return True


# ---------------------------------------------------------------------------
# Authentication
# ---------------------------------------------------------------------------

#: (token, absolute expiry epoch seconds). Module-level so a snapshot's three
#: calls share one token instead of minting three.
_token_cache: Optional[Tuple[str, float]] = None


def reset_token_cache() -> None:
    """Drop the cached bearer token. Used by tests and by long-lived processes."""
    global _token_cache
    _token_cache = None


def _fetch_managed_identity_token() -> Optional[Tuple[str, float]]:
    """Bearer token from the platform's managed-identity endpoint, or None.

    Two endpoints because the two hosting shapes differ: Container Apps (and App
    Service) inject ``IDENTITY_ENDPOINT`` + ``IDENTITY_HEADER`` and expect the
    secret in an ``X-IDENTITY-HEADER`` header; a plain VM exposes IMDS on the
    link-local address with ``Metadata: true``. ``AZURE_CLIENT_ID`` picks the
    user-assigned identity — this application has no system-assigned one.
    """
    client_id = os.getenv("AZURE_CLIENT_ID", "").strip()

    identity_endpoint = os.getenv("IDENTITY_ENDPOINT", "").strip()
    identity_header = os.getenv("IDENTITY_HEADER", "").strip()
    attempts: List[Tuple[str, Dict[str, Any], Dict[str, str]]] = []

    if identity_endpoint and identity_header:
        params = {"api-version": MSI_APP_SERVICE_API_VERSION, "resource": ARM_RESOURCE}
        if client_id:
            params["client_id"] = client_id
        attempts.append((identity_endpoint, params, {"X-IDENTITY-HEADER": identity_header}))

    params = {"api-version": IMDS_API_VERSION, "resource": ARM_RESOURCE}
    if client_id:
        params["client_id"] = client_id
    attempts.append((IMDS_ENDPOINT, params, {"Metadata": "true"}))

    for url, query, headers in attempts:
        try:
            # Short timeout: on a machine with no MSI at all, IMDS's link-local
            # address does not answer, and a scheduled job must not sit on it.
            response = httpx.get(url, params=query, headers=headers, timeout=5.0)
        except Exception as exc:  # pragma: no cover - network shape varies
            logger.debug("Managed identity endpoint %s unreachable: %s", url, exc)
            continue
        if response.status_code != 200:
            logger.debug(
                "Managed identity endpoint %s returned %s: %s",
                url,
                response.status_code,
                response.text[:300],
            )
            continue
        payload = response.json()
        token = payload.get("access_token")
        if not token:
            continue
        # `expires_on` is a unix timestamp on IMDS and (usually) on the App
        # Service endpoint; `expires_in` is relative seconds. Accept either, and
        # fall back to a conservative 10 minutes if neither parses.
        expires_at = _parse_token_expiry(payload)
        return token, expires_at
    return None


def _parse_token_expiry(payload: Dict[str, Any]) -> float:
    now = time.time()
    raw_on = payload.get("expires_on")
    if raw_on is not None:
        try:
            return float(raw_on)
        except (TypeError, ValueError):
            # The App Service endpoint has historically returned this as a
            # formatted local datetime string; unparseable is not fatal.
            logger.debug("Unparseable expires_on %r on MSI token", raw_on)
    raw_in = payload.get("expires_in")
    if raw_in is not None:
        try:
            return now + float(raw_in)
        except (TypeError, ValueError):
            logger.debug("Unparseable expires_in %r on MSI token", raw_in)
    return now + 600.0


def _fetch_cli_token() -> Optional[Tuple[str, float]]:
    """Bearer token from a logged-in Azure CLI. Local development only.

    Gated behind ``AZURE_COST_CLI_FALLBACK`` (default False) so a misconfigured
    deployment fails loudly instead of quietly authenticating as whichever
    principal last ran ``az login``.
    """
    if not settings.AZURE_COST_CLI_FALLBACK:
        return None
    try:
        completed = subprocess.run(
            ["az", "account", "get-access-token", "--resource", ARM_RESOURCE, "-o", "json"],
            capture_output=True,
            text=True,
            timeout=60,
            shell=os.name == "nt",  # `az` is a .cmd shim on Windows
        )
    except Exception as exc:
        logger.debug("Azure CLI token fallback unavailable: %s", exc)
        return None
    if completed.returncode != 0:
        logger.debug("Azure CLI token fallback failed: %s", (completed.stderr or "")[:300])
        return None
    try:
        payload = json.loads(completed.stdout)
    except ValueError:
        return None
    token = payload.get("accessToken")
    if not token:
        return None
    expires_at = time.time() + 1800.0
    raw = payload.get("expires_on") or payload.get("expiresOn")
    if raw is not None:
        try:
            expires_at = float(raw)
        except (TypeError, ValueError):
            try:
                expires_at = datetime.fromisoformat(str(raw)).timestamp()
            except ValueError:
                pass
    return token, expires_at


def _acquire_token() -> str:
    """A bearer token for management.azure.com. See the module docstring's order."""
    global _token_cache
    if _token_cache and _token_cache[1] - TOKEN_EXPIRY_SKEW_SECONDS > time.time():
        return _token_cache[0]

    explicit = (settings.AZURE_COST_ACCESS_TOKEN or "").strip()
    if explicit:
        # No expiry is known for a hand-supplied token; cache it briefly so one
        # snapshot's three calls reuse it, and re-read the setting after that.
        _token_cache = (explicit, time.time() + 600.0)
        return explicit

    for source in (_fetch_managed_identity_token, _fetch_cli_token):
        result = source()
        if result:
            _token_cache = result
            return result[0]

    raise CostAuthError(
        "No Azure credential available for the Cost Management API. In Azure this "
        "needs the container's managed identity (AZURE_CLIENT_ID + the "
        "'Cost Management Reader' role assignment); locally set "
        "AZURE_COST_CLI_FALLBACK=true or AZURE_COST_ACCESS_TOKEN."
    )


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------


def _retry_after_seconds(response: httpx.Response, attempt: int) -> float:
    """How long to wait after a 429, preferring what the service asked for."""
    header = response.headers.get("Retry-After")
    if header:
        try:
            return min(float(header), MAX_BACKOFF_SECONDS)
        except ValueError:
            pass
    # Cost Management also publishes remaining-quota reset hints under
    # `x-ms-ratelimit-microsoft.costmanagement-*`; any of them is better than a
    # blind guess.
    for key, value in response.headers.items():
        if key.lower().startswith("x-ms-ratelimit-microsoft.costmanagement"):
            try:
                return min(float(value), MAX_BACKOFF_SECONDS)
            except ValueError:
                continue
    return min(INITIAL_BACKOFF_SECONDS * (2 ** attempt), MAX_BACKOFF_SECONDS)


#: A 404 the Cost Management *query* endpoint returns intermittently for a
#: subscription that plainly exists — observed live on 2026-08-23 on a
#: ResourceType grouping that had succeeded minutes earlier and succeeded again
#: on retry, alongside heavy 429 activity. Retried by signature rather than by
#: status code so a genuine 404 (a budget that was never deployed) still fails
#: fast instead of costing four attempts.
_TRANSIENT_NOT_FOUND_MARKER = "GtmDimensionDataProvider"


def _request_with_retry(
    method: str,
    url: str,
    *,
    json_body: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """One ARM call, retrying throttling and transient server errors.

    Retries 429, 5xx, and the one specific transient 404 signature above. A
    401/403 (the shape a missing role assignment takes) is raised immediately —
    retrying an authorization failure just turns a clear error into a slow one.
    """
    token = _acquire_token()
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    last_error: Optional[str] = None
    for attempt in range(MAX_ATTEMPTS):
        try:
            response = httpx.request(
                method,
                url,
                headers=headers,
                json=json_body,
                timeout=REQUEST_TIMEOUT_SECONDS,
            )
        except httpx.HTTPError as exc:
            last_error = f"{type(exc).__name__}: {exc}"
            logger.warning("Cost Management request failed (%s), attempt %s", exc, attempt + 1)
            if attempt == MAX_ATTEMPTS - 1:
                break
            time.sleep(min(INITIAL_BACKOFF_SECONDS * (2 ** attempt), MAX_BACKOFF_SECONDS))
            continue

        if response.status_code == 200:
            return response.json()

        if response.status_code in (401, 403):
            raise CostApiError(
                f"Cost Management API returned {response.status_code} for {url}. The caller "
                "is authenticated but not authorized — the managed identity most likely "
                "lacks the 'Cost Management Reader' role at this scope. "
                f"Body: {response.text[:400]}"
            )

        transient_not_found = (
            response.status_code == 404 and _TRANSIENT_NOT_FOUND_MARKER in response.text
        )
        if response.status_code == 429 or response.status_code >= 500 or transient_not_found:
            last_error = f"HTTP {response.status_code}: {response.text[:300]}"
            if attempt == MAX_ATTEMPTS - 1:
                break
            wait = _retry_after_seconds(response, attempt)
            logger.info(
                "Cost Management API returned %s; retrying in %.0fs (attempt %s/%s)",
                response.status_code,
                wait,
                attempt + 1,
                MAX_ATTEMPTS,
            )
            time.sleep(wait)
            continue

        raise CostApiError(
            f"Cost Management API returned {response.status_code} for {url}: "
            f"{response.text[:400]}"
        )

    raise CostApiError(f"Cost Management API call to {url} failed after {MAX_ATTEMPTS} attempts: {last_error}")


def arm_request(
    method: str,
    url: str,
    *,
    json_body: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """One authenticated call to *any* ``management.azure.com`` endpoint.

    A public name for the private plumbing above, added 2026-08-23 for Feature
    24's Ops Digest Agent. Nothing about ``_acquire_token()`` or
    ``_request_with_retry()`` is Cost-Management-specific — both speak plain ARM
    (same ``https://management.azure.com/.default`` scope, same bearer header,
    same 429/5xx backoff) — and the digest needs two other ARM endpoints:
    Azure Resource Graph (``alertsmanagementresources``, for which alerts fired)
    and ``Microsoft.Insights/actionGroups`` (to find out where critical alerts
    are actually delivered today). Exposing this is strictly better than the two
    alternatives: a second managed-identity/CLI token chain to keep in sync, or a
    caller reaching into this module's underscore-prefixed names.

    The exception types are still the ``AzureCostError`` family, which reads
    oddly for a Resource Graph call. Renaming them would touch
    `scripts/sweep_azure_cost.py` and 40 tests for no behavioural gain, so the
    names stay and this docstring is the note: ``CostApiError`` from here means
    "an ARM call failed", not "a cost query failed".
    """
    return _request_with_retry(method, url, json_body=json_body)


# ---------------------------------------------------------------------------
# Response parsing
# ---------------------------------------------------------------------------


def _column_index(columns: Sequence[Dict[str, Any]], name: str) -> Optional[int]:
    """Position of a named column, or None. Never assume a fixed column order."""
    for index, column in enumerate(columns):
        if (column or {}).get("name") == name:
            return index
    return None


def _cell(row: Sequence[Any], index: Optional[int], default: Any = None) -> Any:
    if index is None or index >= len(row):
        return default
    return row[index]


def _parse_usage_date(raw: Any) -> Optional[date]:
    """``20260805`` (number) or ``2026-08-05T00:00:00`` (string) → a date."""
    if raw is None:
        return None
    text = str(raw).strip()
    if not text:
        return None
    if text.isdigit() and len(text) == 8:
        try:
            return date(int(text[0:4]), int(text[4:6]), int(text[6:8]))
        except ValueError:
            return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
    except ValueError:
        return None


def _parse_daily_rows(payload: Dict[str, Any]) -> List[DailySpend]:
    properties = payload.get("properties") or {}
    columns = properties.get("columns") or []
    cost_index = _column_index(columns, "Cost")
    date_index = _column_index(columns, "UsageDate")
    currency_index = _column_index(columns, "Currency")

    results: List[DailySpend] = []
    for row in properties.get("rows") or []:
        usage_date = _parse_usage_date(_cell(row, date_index))
        if usage_date is None:
            continue
        results.append(
            DailySpend(
                usage_date=usage_date,
                amount=float(_cell(row, cost_index, 0.0) or 0.0),
                currency=str(_cell(row, currency_index, "") or ""),
            )
        )
    # The API returns ascending order today; sorting makes `latest_day` and the
    # day-over-day comparison independent of that staying true.
    results.sort(key=lambda item: item.usage_date)
    return results


def _parse_grouped_rows(payload: Dict[str, Any], dimension: str) -> List[SpendSlice]:
    properties = payload.get("properties") or {}
    columns = properties.get("columns") or []
    cost_index = _column_index(columns, "Cost")
    name_index = _column_index(columns, dimension)
    currency_index = _column_index(columns, "Currency")

    results: List[SpendSlice] = []
    for row in properties.get("rows") or []:
        name = _cell(row, name_index, "")
        results.append(
            SpendSlice(
                dimension=dimension,
                name=str(name or "unattributed"),
                amount=float(_cell(row, cost_index, 0.0) or 0.0),
                currency=str(_cell(row, currency_index, "") or ""),
            )
        )
    # Largest first: a breakdown is read top-down, and this is the order every
    # consumer would otherwise re-implement.
    results.sort(key=lambda item: item.amount, reverse=True)
    return results


def dominant_currency(rows: Sequence[Any]) -> str:
    """The currency carried by the rows, or "" when there are none.

    Rows come from one billing account, so mixed currencies are not expected —
    but "expected" is not "guaranteed", so this picks the most common rather than
    trusting row zero.
    """
    counts: Dict[str, int] = {}
    for row in rows:
        currency = getattr(row, "currency", "") or ""
        if currency:
            counts[currency] = counts.get(currency, 0) + 1
    if not counts:
        return ""
    return max(counts.items(), key=lambda item: item[1])[0]


# ---------------------------------------------------------------------------
# Public queries
# ---------------------------------------------------------------------------


def _query_url(scope: Optional[str] = None) -> str:
    return (
        f"{ARM_ENDPOINT}{scope or cost_scope()}/providers/Microsoft.CostManagement/query"
        f"?api-version={COST_MANAGEMENT_API_VERSION}"
    )


def _forecast_url(scope: Optional[str] = None) -> str:
    return (
        f"{ARM_ENDPOINT}{scope or cost_scope()}/providers/Microsoft.CostManagement/forecast"
        f"?api-version={COST_MANAGEMENT_API_VERSION}"
    )


def _budget_url(budget_name: str, scope: Optional[str] = None) -> str:
    return (
        f"{ARM_ENDPOINT}{scope or cost_scope()}/providers/Microsoft.Consumption/budgets/"
        f"{budget_name}?api-version={CONSUMPTION_API_VERSION}"
    )


def _month_bounds(today: Optional[date] = None) -> Tuple[date, date]:
    today = today or datetime.now(timezone.utc).date()
    first = today.replace(day=1)
    last = today.replace(day=monthrange(today.year, today.month)[1])
    return first, last


def get_month_to_date_daily_spend(scope: Optional[str] = None) -> List[DailySpend]:
    """Actual spend per day, first of this month → today."""
    payload = _request_with_retry(
        "POST",
        _query_url(scope),
        json_body={
            "type": "ActualCost",
            "timeframe": "MonthToDate",
            "dataset": {
                "granularity": "Daily",
                "aggregation": {"totalCost": {"name": "Cost", "function": "Sum"}},
            },
        },
    )
    return _parse_daily_rows(payload)


def get_daily_spend(days: int = DEFAULT_TREND_DAYS, scope: Optional[str] = None) -> List[DailySpend]:
    """Actual spend per day over a rolling window ending today.

    Separate from ``get_month_to_date_daily_spend`` because a trend chart on the
    2nd of the month needs the previous month's tail to show anything at all,
    while the MTD total must not include it.
    """
    end = datetime.now(timezone.utc).date()
    start = end - timedelta(days=max(days, 1) - 1)
    payload = _request_with_retry(
        "POST",
        _query_url(scope),
        json_body={
            "type": "ActualCost",
            "timeframe": "Custom",
            "timePeriod": {
                "from": f"{start.isoformat()}T00:00:00+00:00",
                "to": f"{end.isoformat()}T23:59:59+00:00",
            },
            "dataset": {
                "granularity": "Daily",
                "aggregation": {"totalCost": {"name": "Cost", "function": "Sum"}},
            },
        },
    )
    return _parse_daily_rows(payload)


def get_spend_by_dimension(
    dimension: str = DIMENSION_SERVICE_NAME,
    scope: Optional[str] = None,
) -> List[SpendSlice]:
    """Month-to-date spend grouped by one dimension, largest first."""
    payload = _request_with_retry(
        "POST",
        _query_url(scope),
        json_body={
            "type": "ActualCost",
            "timeframe": "MonthToDate",
            "dataset": {
                "granularity": "None",
                "aggregation": {"totalCost": {"name": "Cost", "function": "Sum"}},
                "grouping": [{"type": "Dimension", "name": dimension}],
            },
        },
    )
    return _parse_grouped_rows(payload, dimension)


def get_month_end_forecast(scope: Optional[str] = None) -> Optional[MonthEndForecast]:
    """Azure's own projection for this calendar month.

    ``timeframe: Custom`` with explicit month bounds, not ``MonthToDate`` — the
    forecast endpoint rejects the latter (see the module docstring).
    """
    month_start, month_end = _month_bounds()
    payload = _request_with_retry(
        "POST",
        _forecast_url(scope),
        json_body={
            "type": "ActualCost",
            "timeframe": "Custom",
            "timePeriod": {
                "from": f"{month_start.isoformat()}T00:00:00+00:00",
                "to": f"{month_end.isoformat()}T23:59:59+00:00",
            },
            "dataset": {
                "granularity": "Daily",
                "aggregation": {"totalCost": {"name": "Cost", "function": "Sum"}},
            },
            "includeActualCost": True,
            "includeFreshPartialCost": False,
        },
    )
    properties = payload.get("properties") or {}
    columns = properties.get("columns") or []
    cost_index = _column_index(columns, "Cost")
    status_index = _column_index(columns, "CostStatus")
    currency_index = _column_index(columns, "Currency")

    actual = 0.0
    forecast = 0.0
    currencies: List[str] = []
    for row in properties.get("rows") or []:
        amount = float(_cell(row, cost_index, 0.0) or 0.0)
        status = str(_cell(row, status_index, "") or "")
        currencies.append(str(_cell(row, currency_index, "") or ""))
        if status.lower() == "forecast":
            forecast += amount
        else:
            actual += amount

    if not currencies:
        return None

    counts: Dict[str, int] = {}
    for currency in currencies:
        if currency:
            counts[currency] = counts.get(currency, 0) + 1
    currency = max(counts.items(), key=lambda item: item[1])[0] if counts else ""

    return MonthEndForecast(
        projected_total=actual + forecast,
        actual_to_date=actual,
        forecast_remaining=forecast,
        currency=currency,
        month_start=month_start,
        month_end=month_end,
    )


def get_budget_status(
    budget_name: Optional[str] = None,
    scope: Optional[str] = None,
) -> Optional[BudgetStatus]:
    """Read the deployed Consumption budget. None when it does not exist."""
    name = budget_name or resolve_budget_name()
    try:
        payload = _request_with_retry("GET", _budget_url(name, scope))
    except CostApiError as exc:
        if "404" in str(exc) or "NotFound" in str(exc):
            logger.warning("Budget %s not found at this scope", name)
            return None
        raise

    properties = payload.get("properties") or {}
    current = properties.get("currentSpend") or {}
    forecast = properties.get("forecastSpend") or {}
    return BudgetStatus(
        name=payload.get("name") or name,
        amount=float(properties.get("amount") or 0.0),
        current_spend=float(current.get("amount") or 0.0),
        forecast_spend=float(forecast.get("amount") or 0.0),
        # The budget's own unit is authoritative; `amount` is denominated in it.
        currency=str(current.get("unit") or forecast.get("unit") or ""),
        time_grain=str(properties.get("timeGrain") or ""),
    )


# ---------------------------------------------------------------------------
# Snapshot
# ---------------------------------------------------------------------------


def collect_cost_snapshot(
    trend_days: int = DEFAULT_TREND_DAYS,
    *,
    include_forecast: bool = True,
    include_budget: bool = True,
    scope: Optional[str] = None,
) -> CostSnapshot:
    """Everything Area 1 needs, in one object, in five API calls at most.

    Partial failure is recorded on ``snapshot.errors`` rather than raised, for
    every part except the scope itself: on a throttled API, losing the whole
    snapshot because the fifth call lost a 429 race would make the daily job
    useless exactly when spend is most worth watching. A misconfigured scope
    *does* raise — there is nothing to salvage from it.
    """
    resolved_scope = scope or cost_scope()
    snapshot = CostSnapshot(
        scope=resolved_scope,
        currency="",
        generated_at=datetime.now(timezone.utc),
    )

    def _attempt(label: str, func) -> Any:
        try:
            return func()
        except AzureCostError as exc:
            logger.warning("Azure cost collection: %s failed: %s", label, exc)
            snapshot.errors.append(f"{label}: {exc}")
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("Azure cost collection: %s failed: %s", label, exc, exc_info=True)
            snapshot.errors.append(f"{label}: {type(exc).__name__}: {exc}")
        return None

    mtd = _attempt("month_to_date", lambda: get_month_to_date_daily_spend(resolved_scope))
    if mtd:
        snapshot.month_to_date_total = sum(day.amount for day in mtd)

    daily = _attempt("daily_trend", lambda: get_daily_spend(trend_days, resolved_scope))
    snapshot.daily = daily or mtd or []

    snapshot.by_service = (
        _attempt(
            "by_service",
            lambda: get_spend_by_dimension(DIMENSION_SERVICE_NAME, resolved_scope),
        )
        or []
    )
    snapshot.by_resource_type = (
        _attempt(
            "by_resource_type",
            lambda: get_spend_by_dimension(DIMENSION_RESOURCE_TYPE, resolved_scope),
        )
        or []
    )
    if include_forecast:
        snapshot.forecast = _attempt("forecast", lambda: get_month_end_forecast(resolved_scope))
    if include_budget:
        snapshot.budget = _attempt("budget", lambda: get_budget_status(scope=resolved_scope))

    # Currency is discovered, never assumed: this billing account bills in INR.
    snapshot.currency = (
        dominant_currency(snapshot.daily)
        or dominant_currency(snapshot.by_service)
        or (snapshot.budget.currency if snapshot.budget else "")
        or (snapshot.forecast.currency if snapshot.forecast else "")
    )
    return snapshot


def emit_cost_snapshot_telemetry(snapshot: CostSnapshot, top_slices: int = 15) -> int:
    """Mirror a snapshot into Application Insights custom events.

    Returns the number of events emitted. Two event types, because one row per
    run cannot carry a variable-length breakdown in a way KQL can chart:
    ``azure_cost_snapshot`` (totals, budget, forecast) and ``azure_cost_slice``
    (one row per service and per resource type).

    ``top_slices`` bounds the per-run event count — the tail of a spend
    breakdown is a long list of exact zeros (``Bandwidth``, ``Foundry Tools``,
    ``microsoft.insights/actiongroups`` on this environment today), and paying
    Log Analytics ingestion to record that daily is the opposite of the point.
    """
    # Imported here rather than at module import: `telemetry` pulls in the
    # logging/contextvar stack, and this module is also imported by a standalone
    # script that may run with no telemetry configured at all.
    from telemetry import track_azure_cost_slice, track_azure_cost_snapshot

    latest = snapshot.latest_day
    track_azure_cost_snapshot(
        scope=snapshot.scope,
        currency=snapshot.currency,
        month_to_date_total=snapshot.month_to_date_total,
        latest_day_amount=latest.amount if latest else None,
        latest_day=latest.usage_date.isoformat() if latest else None,
        day_over_day_change_pct=snapshot.day_over_day_change_pct,
        budget_name=snapshot.budget.name if snapshot.budget else None,
        budget_amount=snapshot.budget.amount if snapshot.budget else None,
        budget_current_spend=snapshot.budget.current_spend if snapshot.budget else None,
        budget_forecast_spend=snapshot.budget.forecast_spend if snapshot.budget else None,
        budget_percent_used=snapshot.budget.percent_used if snapshot.budget else None,
        budget_percent_forecast=snapshot.budget.percent_forecast if snapshot.budget else None,
        forecast_projected_total=snapshot.forecast.projected_total if snapshot.forecast else None,
        forecast_remaining=snapshot.forecast.forecast_remaining if snapshot.forecast else None,
        collection_errors=len(snapshot.errors),
    )
    emitted = 1

    for group in (snapshot.by_service, snapshot.by_resource_type):
        for slice_ in group[:top_slices]:
            if slice_.amount <= 0:
                continue
            track_azure_cost_slice(
                dimension=slice_.dimension,
                dimension_value=slice_.name,
                amount=slice_.amount,
                currency=slice_.currency or snapshot.currency,
                scope=snapshot.scope,
            )
            emitted += 1
    return emitted
