"""Feature 33 Task 33.1 — ATLAS Capability Registry.

Every capability ATLAS may call — both investigation cards (kind="read") and
confirmed user actions (kind="action") — is declared here as a ``Capability``
dataclass.  The analyst loop validates every model-proposed capability name
against this registry before executing it; anything not present is dropped and
logged, never silently run.

DESIGN RULES
------------
* ``kind="read"``   — deterministic read-only calls (Feature 30 cards, metrics,
  forecast, FP&A).  Safe to run without user confirmation.
* ``kind="action"`` — side-effecting calls that require a user confirmation step.
  Gated by ``ENABLE_ANALYST_ACTIONS`` at the call site, not here.
* ``needs``         — tuple of ``InputKind`` strings the capability requires.  If
  any needed kind is absent from the tenant's ``Coverage``, the capability
  returns ``NOT_CHECKED`` with a generated ``InputRequest``, never an error.
* ``scopes``        — which loop scopes this capability may be planned into.
* ``roles``         — which Clerk roles may see this capability's output.  Maps to
  clearance at runtime via ``role_allows()``.
* ``deterministic`` — True means every figure the capability returns was produced
  by a SQL view or a Decimal calculation, never by the model.  Hard rule 3.

FP&A CAPABILITIES (Task 33.14a)
--------------------------------
The five FP&A capability functions are forward-declared here as ``None`` stubs.
``agents/analyst_agent.py`` calls ``_wire_fpna_capabilities()`` once the concrete
implementations exist; until then the stubs remain in ``CAPABILITIES`` but are
not callable (the dispatch in ``act()`` guards with ``cap.fn is not None``).

INPUT KINDS (Task 33.12 preview)
---------------------------------
``INPUT_KINDS`` is the canonical list used by both this registry and
``services/dependency.py``.  Define it once here so the two files share the same
source of truth.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Literal, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Input kinds — canonical list (also consumed by services/dependency.py)
# ---------------------------------------------------------------------------

INPUT_KINDS: tuple[str, ...] = (
    "invoices_in",
    "invoices_out",
    "purchase_orders",
    "delivery_notes",
    "bank_statements",
    "remittances",
    "contracts",
    "period_accounts",
    "tax_returns",
    "loan_schedules",
    "budgets",
)

# ---------------------------------------------------------------------------
# Roles
# ---------------------------------------------------------------------------

# All roles understood by the system (mirrors Clerk metadata values).
# The `clearance` field on TenantContext maps Admin -> "exec", others -> "ops".
_ALL_ROLES: frozenset[str] = frozenset({"Admin", "Auditor", "Trainer"})

# ---------------------------------------------------------------------------
# Capability dataclass
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Capability:
    """A single ATLAS capability entry.

    Parameters
    ----------
    name:
        Unique snake_case identifier.  Must match the key in ``CAPABILITIES``
        or ``ACTIONS``.
    fn:
        The callable that implements this capability.  Signature:
            ``fn(row_or_ctx: Any, db_session: Any, ctx: dict) -> InsightCard``
        for ``kind="read"``, or a coroutine for ``kind="action"``.
        May be ``None`` for forward-declared stubs (FP&A — Task 33.14a).
    kind:
        ``"read"`` for deterministic read-only calls; ``"action"`` for
        side-effecting calls that need a user confirmation step.
    input_schema:
        JSON-serialisable dict describing the arguments the model must supply
        when invoking this capability.  Validated at plan time.
    output_schema:
        JSON-serialisable dict describing the output shape for structured
        consumption by ``say()`` and the FE bubble renderer.
    deterministic:
        True ↔ every figure in the output was produced by SQL / Decimal, not
        the model.  Hard rule 3 (CONVENTIONS.md §8.9).
    needs:
        Input kinds required.  An absent kind → ``NOT_CHECKED`` + InputRequest.
    scopes:
        Loop scopes this capability may be planned into: any subset of
        ``{"attachment", "tenant", "onboarding"}``.
    roles:
        Clerk roles that are permitted to see this capability's findings.
        Empty tuple means all roles (public).
    """

    name: str
    fn: Optional[Callable[..., Any]]
    kind: Literal["read", "action"]
    input_schema: dict = field(default_factory=dict, compare=False, hash=False)
    output_schema: dict = field(default_factory=dict, compare=False, hash=False)
    deterministic: bool = True
    needs: tuple[str, ...] = field(default_factory=tuple)
    scopes: tuple[str, ...] = field(default_factory=tuple)
    roles: tuple[str, ...] = field(default_factory=tuple)


# ---------------------------------------------------------------------------
# Registry helpers
# ---------------------------------------------------------------------------


def role_allows(capability: str, role: str) -> bool:
    """Return True if ``role`` is permitted to execute / see ``capability``.

    Rules:
    * If the capability is not in ``CAPABILITIES`` or ``ACTIONS`` → False
      (unknown capabilities must never be executed — hard guard).
    * If the capability's ``roles`` tuple is empty → True (all roles allowed).
    * Otherwise, the role must appear in the capability's ``roles`` tuple.
    """
    cap = CAPABILITIES.get(capability) or ACTIONS.get(capability)
    if cap is None:
        logger.warning(
            "role_allows: unknown capability %r — denying", capability
        )
        return False
    if not cap.roles:
        return True
    return role in cap.roles


def validate_plan_capability(name: str, args: dict) -> bool:
    """Return True if ``name`` is a known, callable read capability and ``args``
    satisfy its ``input_schema`` (currently: required keys present).

    Any capability the model invents that is NOT in ``CAPABILITIES`` is rejected
    here.  Callers log the rejection; this function never raises.
    """
    cap = CAPABILITIES.get(name)
    if cap is None:
        logger.warning(
            "validate_plan_capability: unknown capability %r dropped", name
        )
        return False
    if cap.fn is None:
        logger.warning(
            "validate_plan_capability: capability %r has no implementation yet",
            name,
        )
        return False
    required_keys = {
        k for k, v in cap.input_schema.items() if v.get("required", False)
    }
    missing = required_keys - args.keys()
    if missing:
        logger.warning(
            "validate_plan_capability: capability %r missing required args %s",
            name,
            missing,
        )
        return False
    return True


# ---------------------------------------------------------------------------
# Lazy imports — attachment_insights card functions are imported here to avoid
# a circular import at module load time.  CAPABILITIES is populated at the
# bottom of this module after all helpers are defined.
# ---------------------------------------------------------------------------


def _load_card(fn_name: str) -> Optional[Callable]:
    """Import a Feature 30 card function by name from attachment_insights.

    Returns None if the card is not yet implemented (forward-declared stub).
    This is the only location that touches attachment_insights at import time;
    any failure is logged and the capability is registered as a stub.
    """
    try:
        from services import attachment_insights as _ai  # noqa: PLC0415

        fn = getattr(_ai, fn_name, None)
        if fn is None:
            logger.debug("_load_card: %r not found in attachment_insights", fn_name)
        return fn
    except Exception as exc:  # pragma: no cover
        logger.warning("_load_card: could not import %r: %s", fn_name, exc)
        return None


# ---------------------------------------------------------------------------
# CAPABILITIES registry
# ---------------------------------------------------------------------------
# Each key is the capability ``name``.  Order within the dict is the default
# planner hint order (lower index = tried earlier in a budget-limited run).
#
# Feature 30 cards — attachment scope
# ------------------------------------
# All Feature 30 cards are deterministic reads.  They are registered against
# the attachment scope only; the tenant-scope planner never plans individual
# card calls — it uses the `tenant_briefing` capability which fans out.

CAPABILITIES: dict[str, Capability] = {}


def _build_capabilities() -> dict[str, Capability]:
    """Build and return the CAPABILITIES registry.

    Called once at module load time.  Separated into a function so that tests
    can call it again after monkeypatching ``services.attachment_insights``.
    """
    caps: dict[str, Capability] = {}

    # ------------------------------------------------------------------
    # Feature 30 attachment-scope cards
    # ------------------------------------------------------------------

    _feature30_cards: list[tuple[str, str, tuple[str, ...], tuple[str, ...]]] = [
        # (capability_name, attachment_insights_fn_name, needs, roles)
        (
            "card_what_this_is",
            "card_what_this_is",
            (),
            ("Admin", "Auditor", "Trainer"),
        ),
        (
            "card_agreed_vs_billed",
            "card_agreed_vs_billed",
            ("invoices_in",),
            ("Admin", "Auditor", "Trainer"),
        ),
        (
            "card_terms_check",
            "card_terms_check",
            ("invoices_in",),
            ("Admin", "Auditor", "Trainer"),
        ),
        (
            "card_net_position",
            "card_net_position",
            ("invoices_in",),
            ("Admin", "Auditor", "Trainer"),
        ),
        (
            "card_delivery_vs_order",
            "card_delivery_vs_order",
            ("delivery_notes", "purchase_orders"),
            ("Admin", "Auditor", "Trainer"),
        ),
        (
            "card_payment_application",
            "card_payment_application",
            ("invoices_in",),
            ("Admin", "Auditor", "Trainer"),
        ),
        (
            "card_linked_duplicates",
            "card_linked_duplicates",
            ("invoices_in",),
            ("Admin", "Auditor", "Trainer"),
        ),
        (
            "card_bank_reconcile",
            "card_bank_reconcile",
            ("bank_statements",),
            # bank cards are exec-clearance (Admin only) per spec §8.clearance
            ("Admin",),
        ),
        (
            "card_cash_cover",
            "card_cash_cover",
            ("bank_statements",),
            ("Admin",),
        ),
        (
            "card_cash_impact",
            "card_cash_impact",
            ("bank_statements", "invoices_in"),
            ("Admin",),
        ),
        (
            "card_open_po_value",
            "card_open_po_value",
            ("purchase_orders", "invoices_in"),
            ("Admin", "Auditor"),
        ),
        (
            "card_cash_out_timing",
            "card_cash_out_timing",
            ("bank_statements", "invoices_in"),
            ("Admin",),
        ),
        (
            "card_over_invoicing_history",
            "card_over_invoicing_history",
            ("invoices_in",),
            ("Admin", "Auditor"),
        ),
        (
            "card_quote_drift",
            "card_quote_drift",
            ("invoices_in",),
            ("Admin", "Auditor"),
        ),
        (
            "card_partial_delivery_balance",
            "card_partial_delivery_balance",
            ("delivery_notes", "purchase_orders"),
            ("Admin", "Auditor"),
        ),
        (
            "card_repeat_short_delivery",
            "card_repeat_short_delivery",
            ("delivery_notes",),
            ("Admin", "Auditor"),
        ),
        (
            "card_contract_deviations",
            "card_contract_deviations",
            ("contracts",),
            ("Admin", "Auditor"),
        ),
        (
            "card_compliance",
            "card_compliance",
            (),
            ("Admin", "Auditor"),
        ),
        (
            "card_suggested_questions",
            "card_suggested_questions",
            (),
            ("Admin", "Auditor", "Trainer"),
        ),
        (
            "card_confidence_gaps",
            "card_confidence_gaps",
            (),
            ("Admin", "Auditor", "Trainer"),
        ),
    ]

    for cap_name, fn_name, needs, roles in _feature30_cards:
        caps[cap_name] = Capability(
            name=cap_name,
            fn=_load_card(fn_name),
            kind="read",
            input_schema={
                "attachment_id": {"type": "string", "required": True},
            },
            output_schema={
                "card": {"type": "string"},
                "status": {"type": "string"},
                "findings": {"type": "array"},
                "figures": {"type": "object"},
            },
            deterministic=True,
            needs=needs,
            scopes=("attachment",),
            roles=roles,
        )

    # ------------------------------------------------------------------
    # Metrics / semantic views — tenant scope
    # ------------------------------------------------------------------
    # These call query_metric() from services/semantic_views.py.  They are
    # read-only, deterministic (SQL views), and may appear in both tenant and
    # attachment scopes.

    _metric_caps: list[tuple[str, tuple[str, ...], tuple[str, ...]]] = [
        ("metric_vendor_spend", ("invoices_in",), ("Admin", "Auditor")),
        ("metric_overdue", ("invoices_out",), ("Admin", "Auditor")),
        ("metric_3way_match", ("invoices_in", "purchase_orders", "delivery_notes"), ("Admin", "Auditor")),
        ("metric_commitments", ("purchase_orders", "contracts"), ("Admin", "Auditor")),
        ("metric_delivery_events", ("delivery_notes",), ("Admin", "Auditor")),
        ("metric_payment_events", ("bank_statements", "remittances"), ("Admin",)),
        ("metric_period_accounts", ("period_accounts",), ("Admin",)),
        ("metric_budgets", ("budgets", "period_accounts"), ("Admin",)),
    ]

    for cap_name, needs, roles in _metric_caps:
        caps[cap_name] = Capability(
            name=cap_name,
            fn=None,  # wired in Task 33.2/33.3 when analyst_agent.py is built
            kind="read",
            input_schema={
                "metric": {"type": "string", "required": True},
                "clearance": {"type": "string", "required": True},
            },
            output_schema={
                "rows": {"type": "array"},
                "columns": {"type": "array"},
            },
            deterministic=True,
            needs=needs,
            scopes=("tenant", "attachment"),
            roles=roles,
        )

    # ------------------------------------------------------------------
    # Forecast capabilities — tenant scope (Task 33.13 / 33.14)
    # ------------------------------------------------------------------

    caps["forecast_cashflow"] = Capability(
        name="forecast_cashflow",
        fn=None,  # wired when services/forecast.py is built (Task 33.13)
        kind="read",
        input_schema={
            "horizon_days": {"type": "integer", "required": False},
        },
        output_schema={
            "tiers": {"type": "object"},
            "currencies": {"type": "array"},
            "runway_days": {"type": "object"},
        },
        deterministic=True,
        needs=("invoices_out", "bank_statements"),
        scopes=("tenant", "onboarding"),
        roles=("Admin",),
    )

    caps["forecast_scenario"] = Capability(
        name="forecast_scenario",
        fn=None,  # wired in Task 33.13
        kind="read",
        input_schema={
            "change": {"type": "object", "required": True},
            "horizon_days": {"type": "integer", "required": False},
        },
        output_schema={
            "tiers": {"type": "object"},
            "currencies": {"type": "array"},
            "runway_days": {"type": "object"},
        },
        deterministic=True,
        needs=("invoices_out", "bank_statements"),
        scopes=("tenant",),
        roles=("Admin",),
    )

    caps["detect_recurrence"] = Capability(
        name="detect_recurrence",
        fn=None,  # wired in Task 33.14
        kind="read",
        input_schema={},
        output_schema={
            "recurrences": {"type": "array"},
        },
        deterministic=True,
        needs=("bank_statements",),
        scopes=("tenant", "onboarding"),
        roles=("Admin",),
    )

    # ------------------------------------------------------------------
    # FP&A capabilities — Task 33.14a (stub registrations)
    # ------------------------------------------------------------------
    # All five are registered now so the model can reference them; their ``fn``
    # fields are None until ``_wire_fpna_capabilities()`` is called from
    # analyst_agent.py after the concrete implementations exist.

    caps["pnl_by_period"] = Capability(
        name="pnl_by_period",
        fn=None,
        kind="read",
        input_schema={
            "periods": {"type": "integer", "required": False},
        },
        output_schema={
            "rows": {"type": "array"},
            "currencies": {"type": "array"},
        },
        deterministic=True,
        needs=("period_accounts",),
        scopes=("tenant", "onboarding"),
        roles=("Admin",),
    )

    caps["margin_per_customer"] = Capability(
        name="margin_per_customer",
        fn=None,
        kind="read",
        input_schema={},
        output_schema={
            "rows": {"type": "array"},
        },
        deterministic=True,
        needs=("invoices_out", "invoices_in"),
        scopes=("tenant",),
        roles=("Admin",),
    )

    caps["margin_per_item"] = Capability(
        name="margin_per_item",
        fn=None,
        kind="read",
        input_schema={},
        output_schema={
            "rows": {"type": "array"},
        },
        deterministic=True,
        needs=("invoices_out", "invoices_in"),
        scopes=("tenant",),
        roles=("Admin",),
    )

    caps["budget_variance_per_account"] = Capability(
        name="budget_variance_per_account",
        fn=None,
        kind="read",
        input_schema={
            "periods": {"type": "integer", "required": False},
        },
        output_schema={
            "rows": {"type": "array"},
        },
        deterministic=True,
        needs=("budgets", "period_accounts"),
        scopes=("tenant",),
        roles=("Admin",),
    )

    caps["expense_category_trend"] = Capability(
        name="expense_category_trend",
        fn=None,
        kind="read",
        input_schema={
            "months": {"type": "integer", "required": False},
        },
        output_schema={
            "rows": {"type": "array"},
        },
        deterministic=True,
        needs=("period_accounts",),
        scopes=("tenant",),
        roles=("Admin",),
    )

    # ------------------------------------------------------------------
    # Tenant-scope composite capabilities
    # ------------------------------------------------------------------
    # ``tenant_briefing`` is what the planner emits for a full weekly run;
    # ``act()`` fans it out into the individual metric/card calls.

    caps["tenant_briefing"] = Capability(
        name="tenant_briefing",
        fn=None,  # wired in analyst_agent.py Task 33.3
        kind="read",
        input_schema={},
        output_schema={
            "cards": {"type": "array"},
            "today_items": {"type": "array"},
        },
        deterministic=True,
        needs=(),
        scopes=("tenant", "onboarding"),
        roles=("Admin", "Auditor", "Trainer"),
    )

    # ------------------------------------------------------------------
    # Convention proposal capability — Task 33.23/33.36
    # ------------------------------------------------------------------

    caps["auto_apply_credit_notes"] = Capability(
        name="auto_apply_credit_notes",
        fn=None,  # wired in Task 33.36
        kind="read",
        input_schema={},
        output_schema={
            "proposal": {"type": "object"},
        },
        deterministic=True,
        needs=("invoices_in",),
        scopes=("attachment", "tenant"),
        roles=("Admin", "Auditor"),
    )

    return caps


CAPABILITIES = _build_capabilities()


# ---------------------------------------------------------------------------
# ACTIONS registry (Task 33.25) — kind="action", gated by ENABLE_ANALYST_ACTIONS
# ---------------------------------------------------------------------------
# Actions are side-effecting and require a user confirmation step before
# ``act()`` calls their ``fn``.  Seeded here as stubs (fn=None) until
# Task 33.25 wires the concrete endpoint proxies.

ACTIONS: dict[str, Capability] = {
    "setup_inbound_email": Capability(
        name="setup_inbound_email",
        fn=None,  # → existing email-setup endpoint (Task 33.25)
        kind="action",
        input_schema={},
        output_schema={"ok": {"type": "boolean"}},
        deterministic=False,
        needs=(),
        scopes=("tenant", "onboarding"),
        roles=("Admin",),
    ),
    "enable_auto_load_inbox": Capability(
        name="enable_auto_load_inbox",
        fn=None,  # → existing connector endpoint (Task 33.25)
        kind="action",
        input_schema={},
        output_schema={"ok": {"type": "boolean"}},
        deterministic=False,
        needs=(),
        scopes=("tenant",),
        roles=("Admin",),
    ),
    "set_outbound_email_sender": Capability(
        name="set_outbound_email_sender",
        fn=None,  # → existing email-settings endpoint (Task 33.25)
        kind="action",
        input_schema={
            "email": {"type": "string", "required": True},
            "name": {"type": "string", "required": False},
        },
        output_schema={"ok": {"type": "boolean"}},
        deterministic=False,
        needs=(),
        scopes=("tenant",),
        roles=("Admin",),
    ),
    "hold_invoice": Capability(
        name="hold_invoice",
        fn=None,  # → existing invoice-hold service (Task 33.25)
        kind="action",
        input_schema={
            "invoice_id": {"type": "string", "required": True},
            "reason": {"type": "string", "required": False},
        },
        output_schema={"ok": {"type": "boolean"}},
        deterministic=False,
        needs=("invoices_in",),
        scopes=("tenant", "attachment"),
        roles=("Admin", "Auditor"),
    ),
    "dismiss_finding": Capability(
        name="dismiss_finding",
        fn=None,  # → Insight transition (Task 33.25)
        kind="action",
        input_schema={
            "insight_id": {"type": "string", "required": True},
        },
        output_schema={"ok": {"type": "boolean"}},
        deterministic=False,
        needs=(),
        scopes=("tenant", "attachment"),
        roles=("Admin", "Auditor"),
    ),
    "write_rule": Capability(
        name="write_rule",
        fn=None,  # → ExtractionTemplate / TenantChatRule (Task 33.25)
        kind="action",
        input_schema={
            "rule_text": {"type": "string", "required": True},
            "target": {
                "type": "string",
                "enum": ["extraction_template", "tenant_chat_rule"],
                "required": True,
            },
        },
        output_schema={"ok": {"type": "boolean"}},
        deterministic=False,
        needs=(),
        scopes=("tenant",),
        roles=("Trainer",),
    ),
}


# ---------------------------------------------------------------------------
# FP&A wiring hook (called from analyst_agent.py once forecast.py exists)
# ---------------------------------------------------------------------------


def _wire_fpna_capabilities(
    *,
    pnl_by_period_fn: Optional[Callable] = None,
    margin_per_customer_fn: Optional[Callable] = None,
    margin_per_item_fn: Optional[Callable] = None,
    budget_variance_fn: Optional[Callable] = None,
    expense_category_trend_fn: Optional[Callable] = None,
    forecast_cashflow_fn: Optional[Callable] = None,
    forecast_scenario_fn: Optional[Callable] = None,
    detect_recurrence_fn: Optional[Callable] = None,
) -> None:
    """Wire concrete FP&A / forecast implementations into the registry.

    Called once from ``agents/analyst_agent.py`` at import time, after
    ``services/forecast.py`` is available.  Each argument is optional so this
    can be called incrementally as tasks land.

    Because ``Capability`` is frozen, we replace the dict entry entirely.
    """
    _wire_map = {
        "pnl_by_period": pnl_by_period_fn,
        "margin_per_customer": margin_per_customer_fn,
        "margin_per_item": margin_per_item_fn,
        "budget_variance_per_account": budget_variance_fn,
        "expense_category_trend": expense_category_trend_fn,
        "forecast_cashflow": forecast_cashflow_fn,
        "forecast_scenario": forecast_scenario_fn,
        "detect_recurrence": detect_recurrence_fn,
    }
    for cap_name, fn in _wire_map.items():
        if fn is None:
            continue
        existing = CAPABILITIES.get(cap_name)
        if existing is None:
            logger.warning("_wire_fpna_capabilities: unknown cap %r", cap_name)
            continue
        # Reconstruct with the concrete fn — dataclass(frozen=True) requires
        # object.__setattr__ to bypass the immutability check.
        import dataclasses  # noqa: PLC0415

        new_cap = dataclasses.replace(existing, fn=fn)
        CAPABILITIES[cap_name] = new_cap
        logger.debug("wired capability %r → %s", cap_name, fn.__qualname__)


try:
    from services.forecast import (
        cap_pnl_by_period,
        cap_margin_per_customer,
        cap_margin_per_item,
        cap_budget_variance,
        cap_expense_category_trend,
        cap_forecast_cashflow,
        cap_forecast_scenario,
        cap_detect_recurrence,
    )
    _wire_fpna_capabilities(
        pnl_by_period_fn=cap_pnl_by_period,
        margin_per_customer_fn=cap_margin_per_customer,
        margin_per_item_fn=cap_margin_per_item,
        budget_variance_fn=cap_budget_variance,
        expense_category_trend_fn=cap_expense_category_trend,
        forecast_cashflow_fn=cap_forecast_cashflow,
        forecast_scenario_fn=cap_forecast_scenario,
        detect_recurrence_fn=cap_detect_recurrence,
    )
except ImportError:
    pass
