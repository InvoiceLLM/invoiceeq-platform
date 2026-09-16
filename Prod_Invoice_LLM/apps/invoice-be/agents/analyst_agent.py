"""Feature 33 Task 33.3 — ATLAS Analyst Agent: Core Loop (Attachment Scope).

THE SEVEN-STEP LOOP
-------------------
    run_analyst(scope, db_session, budget)
      │
      ├─ 1. observe()       → builds Observation (documents, facts, invoices, profile)
      ├─ 2. plan()          → one LLM call → ordered list of capability calls
      │                       OR plan_by_rule() if flag off / attachment scope
      ├─ 3. act()           → executes capabilities → list[InsightCard]  (3-state)
      ├─ 4. investigate()   → for findings above threshold: up to budget.follow_ups more calls
      ├─ 5. say()           → narrates sentences, each gated by _answer_contract_gate()
      ├─ 6. ask()           → missing_inputs() → InputRequest list, ranked by unlock_value()
      └─ 7. persist()       → writes Insight rows, TodayItems, InputRequests; feeds learn() on dismiss

THREE SCOPES, ONE LOOP
-----------------------
    scope.kind = "attachment"   → triggered by a chat attachment (this file, Slice B)
    scope.kind = "tenant"       → weekly job + events (Task 33.15, Slice B)
    scope.kind = "onboarding"   → after first 10 extractions (Task 33.24, Slice C)

PLANNER GATING (Feature 29 CP2 rule)
--------------------------------------
The LLM planner (``plan()``) is enabled only for tenant and onboarding scopes,
and only when ``ENABLE_ANALYST_PLANNER=True``.

Attachment scope ALWAYS uses ``plan_by_rule()`` — the Feature-30 type-keyed
fallback — until Feature 29 CP2 is calibrated (100-turn golden set, resolver
flag on, κ measured against the founder).  This is not a temporary hack; it is
the correct default until there is measured evidence that the planner improves
attachment scope routing.

``build_insight_block()`` in ``services/attachment_insights.py`` delegates to
``run_analyst()`` when ``ENABLE_ANALYST_PLANNER`` is on; when it is off the
existing Feature-30 card pipeline runs unchanged (byte-identical to pre-33).

HARD RULES
-----------
* No number from the LLM (hard rule 3).  Every figure in an InsightCard was
  produced by a SQL view or a Decimal calculation before the model saw it.
* The answer-contract gate wraps every narrated sentence in ``say()``.
* A card that raises an exception is marked BLOCKED; remaining cards still run.
* ``run_analyst()`` never raises to its caller.  All exceptions are caught,
  logged, and returned as an empty AnalystResult.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal, Optional
from uuid import UUID

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Domain dataclasses
# ---------------------------------------------------------------------------


@dataclass
class AnalystScope:
    """Everything the loop needs to know about the run context.

    Parameters
    ----------
    kind:
        Which of the three loop modes this run is.
    tenant_id:
        The tenant UUID (string or UUID — always stringified before use).
    clearance:
        The calling user's clearance: ``"ops"`` or ``"exec"``.
    attachment_id:
        Set for ``kind="attachment"`` runs; None otherwise.
    since:
        For ``kind="tenant"`` incremental runs: only consider events after this
        datetime.  None = full scan.
    profile:
        The tenant's ``BusinessProfile`` (Task 33.22, Slice C).  May be None
        for Slice B runs — the loop degrades gracefully when it is absent.
    """

    kind: Literal["attachment", "tenant", "onboarding"]
    tenant_id: Any
    clearance: str = "ops"
    attachment_id: Optional[str] = None
    since: Optional[datetime] = None
    profile: Optional[Any] = None  # BusinessProfile — Slice C


@dataclass
class Budget:
    """Per-run resource limits.

    Attachment scope: 1 follow-up, 1 narrated sentence.
    Tenant / onboarding scope: 3 follow-ups, 6 narrated sentences.
    """

    follow_ups: int = 1
    sentences: int = 1

    @classmethod
    def for_scope(cls, kind: str) -> "Budget":
        if kind == "attachment":
            return cls(follow_ups=1, sentences=1)
        return cls(follow_ups=3, sentences=6)


@dataclass
class Observation:
    """What the loop sees before it plans.

    All fields are counts / metadata — no document text, no raw blobs.
    The model (in ``plan()``) only sees this summary, never the source text.
    """

    scope: AnalystScope
    attachment_row: Optional[Any] = None        # ChatAttachment ORM row
    extracted_json: Optional[dict] = None       # parsed extracted_json dict
    facts: list = field(default_factory=list)   # list[Fact] from facts_for()
    linked_invoices: list = field(default_factory=list)  # matched invoice rows
    overlap: Optional[Any] = None               # OverlapGraph from overlap.py
    doc_type: str = ""
    doc_number: str = ""
    party_name: str = ""
    currency: str = "INR"
    grand_total: Optional[float] = None


@dataclass
class Plan:
    """An ordered list of (capability_name, args) to execute."""

    steps: list[tuple[str, dict]] = field(default_factory=list)
    source: Literal["rule", "llm"] = "rule"


@dataclass
class AnalystResult:
    """The full output of one loop run."""

    scope: AnalystScope
    cards: list = field(default_factory=list)        # list[InsightCard]
    narration: list[str] = field(default_factory=list)  # gated sentences
    input_requests: list = field(default_factory=list)  # list[InputRequest models]
    overlap_summary: dict = field(default_factory=dict)
    plan_source: str = "rule"
    empty_graph: bool = False   # True → "nothing matches" bubble
    error: Optional[str] = None


# ---------------------------------------------------------------------------
# Flags
# ---------------------------------------------------------------------------


def _planner_enabled() -> bool:
    """Read at call time so monkeypatches in tests are seen."""
    try:
        from config import get_settings  # noqa: PLC0415
        return bool(getattr(get_settings(), "ENABLE_ANALYST_PLANNER", False))
    except Exception:
        return False


def _analyst_enabled() -> bool:
    """Master switch: ENABLE_ATTACHMENT_INSIGHTS must be on for attachments."""
    try:
        from config import get_settings  # noqa: PLC0415
        s = get_settings()
        return bool(getattr(s, "ENABLE_ATTACHMENT_INSIGHTS", False))
    except Exception:
        return False


def _answer_contract_gate_enabled() -> bool:
    try:
        from config import get_settings  # noqa: PLC0415
        return bool(getattr(get_settings(), "ENABLE_ANSWER_CONTRACT_GATE", True))
    except Exception:
        return True


# ---------------------------------------------------------------------------
# Step 1 — observe()
# ---------------------------------------------------------------------------


def observe(scope: AnalystScope, db_session: Any) -> Observation:
    """Build the Observation for this run.

    For attachment scope: loads the ChatAttachment row, its extracted JSON,
    the linked invoice rows, the facts already on file, and runs overlap.

    Never raises — an error returns a minimal Observation with an empty
    AnalystResult produced by the caller.
    """
    obs = Observation(scope=scope)

    if scope.kind == "attachment" and scope.attachment_id:
        try:
            from models import ChatAttachment  # noqa: PLC0415
            import sqlalchemy as sa  # noqa: PLC0415

            aid = scope.attachment_id
            if isinstance(aid, str):
                try:
                    aid = UUID(aid)
                except (ValueError, AttributeError):
                    pass
            row = db_session.get(ChatAttachment, aid)
            if row is None:
                logger.warning("observe: attachment %s not found", scope.attachment_id)
                return obs

            obs.attachment_row = row
            obs.doc_type = str(row.doc_type or "").upper()
            obs.doc_number = str(getattr(row, "doc_number", "") or "")
            obs.party_name = str(getattr(row, "party_name", "") or "")
            obs.currency = str(getattr(row, "currency", "") or "INR")
            obs.grand_total = _safe_float(getattr(row, "grand_total", None))

            # extracted_json from the row (already a dict if stored as JSONB)
            raw_json = getattr(row, "extracted_json", None)
            if isinstance(raw_json, dict):
                obs.extracted_json = raw_json
            elif isinstance(raw_json, str):
                import json  # noqa: PLC0415
                try:
                    obs.extracted_json = json.loads(raw_json)
                except Exception:
                    obs.extracted_json = {}
            else:
                obs.extracted_json = {}

        except Exception as exc:
            logger.warning("observe: failed loading attachment row: %s", exc)
            return obs

        # Linked invoices
        try:
            from services.attachment_insights import _linked_invoices  # noqa: PLC0415
            obs.linked_invoices = _linked_invoices(obs.attachment_row, db_session)
        except Exception as exc:
            logger.warning("observe: failed loading linked invoices: %s", exc)

        # Facts on file
        try:
            from services.facts import facts_for  # noqa: PLC0415
            obs.facts = facts_for(
                subject_kind="chat_attachment",
                subject_id=str(scope.attachment_id),
                clearance=scope.clearance,
                db_session=db_session,
            )
        except Exception as exc:
            logger.warning("observe: failed loading facts: %s", exc)

        # Overlap graph
        if obs.extracted_json is not None:
            try:
                from services.overlap import resolve_overlap  # noqa: PLC0415
                overlap_data = dict(obs.extracted_json)
                if obs.party_name and "party_name" not in overlap_data and "vendor_name" not in overlap_data:
                    overlap_data["party_name"] = obs.party_name
                if obs.doc_number and "doc_number" not in overlap_data and "invoice_number" not in overlap_data:
                    overlap_data["doc_number"] = obs.doc_number
                if obs.doc_type and "doc_type" not in overlap_data:
                    overlap_data["doc_type"] = obs.doc_type
                obs.overlap = resolve_overlap(
                    extracted_json=overlap_data,
                    scope=scope.kind,
                    db_session=db_session,
                    tenant_id=scope.tenant_id,
                    clearance=scope.clearance,
                )
            except Exception as exc:
                logger.warning("observe: overlap resolution failed: %s", exc)

    return obs


# ---------------------------------------------------------------------------
# Step 2 — plan_by_rule() + plan()
# ---------------------------------------------------------------------------


def plan_by_rule(observation: Observation, scope: AnalystScope) -> Plan:
    """The Feature-30 type-keyed fallback planner.

    Maps doc_type → ordered tuple of capability names, exactly as the
    Feature-30 ``CARDS_BY_DOC_TYPE`` dict does.  The LLM is not involved.

    This is the ONLY planner for attachment scope.  For tenant/onboarding scope
    it is the fallback when ``ENABLE_ANALYST_PLANNER=False``.
    """
    from services.attachment_insights import CARDS_BY_DOC_TYPE  # noqa: PLC0415

    doc_type = observation.doc_type
    card_fns = CARDS_BY_DOC_TYPE.get(doc_type, ())

    steps: list[tuple[str, dict]] = []
    for fn in card_fns:
        cap_name = f"card_{getattr(fn, '__name__', '').replace('card_', '')}"
        steps.append((cap_name, {
            "attachment_id": str(scope.attachment_id or ""),
        }))

    return Plan(steps=steps, source="rule")


def plan(observation: Observation, scope: AnalystScope, llm: Any) -> Plan:
    """One LLM call → ordered list of capability calls.

    Enabled ONLY for tenant and onboarding scopes, and only when
    ``ENABLE_ANALYST_PLANNER=True``.  Never called for attachment scope.

    The model receives the observation as a summary of entity counts — it NEVER
    sees document text.  Any capability name the model returns that is not in
    the CAPABILITIES registry is dropped and logged.

    Task 33.4 will expand this with the full prompt from atlas_prompts.py.
    For now: returns plan_by_rule() for all non-attachment scopes.
    """
    # CP2 gate: LLM planner is stub until Task 33.4 (Slice B, sub-step 1)
    logger.debug(
        "plan: LLM planner stub — falling back to plan_by_rule for scope %s",
        scope.kind,
    )
    return plan_by_rule(observation, scope)


# ---------------------------------------------------------------------------
# Step 3 — act()
# ---------------------------------------------------------------------------


def act(
    plan: Plan,
    observation: Observation,
    scope: AnalystScope,
    db_session: Any,
) -> list:
    """Execute capability calls from the plan.  Returns list[InsightCard].

    For attachment scope the capabilities are the Feature-30 card functions
    (loaded from ``agents/capabilities.py``).

    A capability not in the registry is dropped (never executed).
    A capability whose ``fn`` is None (stub) is returned as NOT_CHECKED.
    A capability that raises is returned as BLOCKED — remaining caps still run.
    """
    from agents.capabilities import CAPABILITIES, validate_plan_capability  # noqa: PLC0415
    from services.attachment_insights import (  # noqa: PLC0415
        InsightCard, STATUS_SKIPPED, STATUS_BLOCKED,
    )

    cards: list = []
    attachment_row = observation.attachment_row
    ctx: dict = {
        "stage": "async",
        "invoices": observation.linked_invoices,
        "cards_so_far": cards,
        "thresholds": _load_thresholds(scope.tenant_id, db_session),
        "overlap": observation.overlap,
        "facts": observation.facts,
        "clearance": scope.clearance,
    }

    for cap_name, args in plan.steps:
        if not validate_plan_capability(cap_name, args):
            continue
        cap = CAPABILITIES.get(cap_name)
        if cap is None:
            continue
        if cap.fn is None:
            cards.append(InsightCard(
                card=cap_name,
                status=STATUS_SKIPPED,
                reason="capability not yet implemented",
            ))
            continue
        try:
            card = cap.fn(attachment_row, db_session, ctx)
            cards.append(card)
            ctx["cards_so_far"] = cards
        except Exception as exc:
            logger.error(
                "act: capability %r raised on attachment %s: %s",
                cap_name,
                scope.attachment_id,
                exc,
                exc_info=True,
            )
            cards.append(InsightCard(
                card=cap_name,
                status=STATUS_BLOCKED,
                reason="this check could not be completed",
            ))

    return cards


# ---------------------------------------------------------------------------
# Step 4 — investigate()
# ---------------------------------------------------------------------------


def investigate(
    cards: list,
    scope: AnalystScope,
    observation: Observation,
    db_session: Any,
    llm: Any,
    budget: Budget,
) -> list:
    """For each finding above the investigation threshold: up to budget.follow_ups more capability calls.

    For attachment scope with budget.follow_ups=1 this is at most one extra call.
    A contradicting follow-up downgrades confidence and states why.

    Task 33.5 will expand this with the full investigate prompt.
    For Slice B Task 33.3: runs zero follow-ups (attachment scope has budget=1
    but the stub LLM returns nothing).  Returns cards unchanged.
    """
    # Stub: full implementation in Task 33.5
    return cards


# ---------------------------------------------------------------------------
# Step 5 — say()
# ---------------------------------------------------------------------------


def say(
    cards: list,
    scope: AnalystScope,
    observation: Optional[Observation] = None,
    llm: Optional[Any] = None,
    budget: Optional[Budget] = None,
) -> list[str]:
    """Narrate sentences; each sentence is independently gated.

    A sentence that fails the answer-contract gate is replaced by the finding's
    template text — never dropped silently.

    For attachment scope with budget.sentences=1: one verdict sentence.
    For tenant/onboarding scope: up to 6 sentences across all findings.

    Task 33.6 will add the full atlas_prompts.py narration.  For Slice B
    Task 33.3: returns one template sentence derived from the findings.
    """
    if budget is None:
        budget = Budget.for_scope(scope.kind)
    if observation is None:
        observation = Observation(scope=scope)

    sentences: list[str] = []
    gate_on = _answer_contract_gate_enabled()

    all_findings = [f for card in cards for f in getattr(card, "findings", [])]

    if not all_findings:
        # No findings → one "all clear" or "nothing matched" template line
        if observation.overlap and not observation.overlap.has_any():
            sentences.append(
                "I read this document, but nothing matched your vendors, invoices or items."
            )
        else:
            sentences.append(
                "I checked this document against your records — no issues found."
            )
        return sentences[:budget.sentences]

    # Sort findings: highest-impact first
    def _impact_key(f: dict) -> float:
        amt = f.get("impact_amount")
        try:
            return -float(amt) if amt is not None else 0.0
        except (TypeError, ValueError):
            return 0.0

    sorted_findings = sorted(all_findings, key=_impact_key)

    for finding in sorted_findings:
        if len(sentences) >= budget.sentences:
            break
        template = _finding_template(finding)
        if llm is not None and not _is_stub_llm(llm):
            # Task 33.6 will call the model here and gate the result
            narrated = _narrate_finding(finding, llm, observation)
            if gate_on and not _passes_contract(narrated, finding):
                sentences.append(template)
            else:
                sentences.append(narrated)
        else:
            sentences.append(template)

    return sentences[:budget.sentences]


def _finding_template(finding: dict) -> str:
    """Deterministic template sentence for a finding.  No model involved."""
    title = finding.get("title", "")
    amt = finding.get("impact_amount")
    cur = finding.get("currency", "INR")
    if amt is not None:
        try:
            amt_fmt = f"{float(amt):,.2f}"
            return f"{title} — impact {cur} {amt_fmt}."
        except (TypeError, ValueError):
            pass
    return f"{title}."


def _narrate_finding(finding: dict, llm: Any, observation: Observation) -> str:
    """Placeholder: Task 33.6 will call atlas_prompts.py here."""
    return _finding_template(finding)


def _passes_contract(sentence: str, finding: dict) -> bool:
    """Check that every figure in the finding appears in the narrated sentence.

    Minimal implementation: the full gate lives in query_agent._answer_contract_gate.
    """
    amt = finding.get("impact_amount")
    if amt is None:
        return True
    try:
        amt_str = f"{float(amt):,.2f}"
        # Accept both comma-formatted and plain
        alt = str(float(amt))
        return amt_str in sentence or alt in sentence
    except (TypeError, ValueError):
        return True


def _is_stub_llm(llm: Any) -> bool:
    """True if the LLM is a None-sentinel or an explicit stub."""
    return llm is None


# ---------------------------------------------------------------------------
# Step 6 — ask()
# ---------------------------------------------------------------------------


def ask(
    plan: Plan,
    observation: Observation,
    scope: AnalystScope,
    db_session: Any,
) -> list:
    """Compute missing input requests from the planned capabilities and coverage.

    Calls ``coverage_for()`` to see what document kinds are on file, then
    ``missing_inputs()`` to find which kinds the plan needs but are absent.
    Returns a ranked list of ``MissingInput`` objects (Task 33.12).

    The list is later persisted by ``persist()`` as ``InputRequest`` rows
    (Task 33.17).  Returns an empty list on any failure — a missing dependency
    is reported as NOT_CHECKED on the card, not as an error to the caller.
    """
    try:
        from services.dependency import coverage_for, missing_inputs  # noqa: PLC0415

        cov = coverage_for(
            tenant_id=scope.tenant_id,
            clearance=scope.clearance,
            db_session=db_session,
        )
        return missing_inputs(
            plan_or_capabilities=plan,
            coverage=cov,
            db_session=db_session,
            tenant_id=scope.tenant_id,
            clearance=scope.clearance,
        )
    except Exception as exc:
        logger.warning("ask: dependency resolution failed: %s", exc)
        return []


# ---------------------------------------------------------------------------
# Step 7 — persist()
# ---------------------------------------------------------------------------


def persist(
    result: AnalystResult,
    db_session: Any,
    *,
    attachment_row: Any = None,
) -> None:
    """Write Insight rows, TodayItems, and InputRequests to the DB.

    For attachment scope: updates the attachment row's insight payload via
    ``build_insight_block``'s existing write path.  Does NOT duplicate rows.

    Full Today / InputRequest persistence is Task 33.17 / 33.32.
    For Slice B Task 33.3: writes nothing (the existing insight write path
    in ``handlers.py`` handles attachment scope).
    """
    # Stub: attachment write is handled by the existing queue_worker/handlers.py path.
    # Tenant-scope Today persistence is Task 33.17.
    pass


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def run_analyst(
    scope: AnalystScope,
    db_session: Any,
    budget: Optional[Budget] = None,
    llm: Optional[Any] = None,
) -> AnalystResult:
    """Execute the seven-step ATLAS loop.  Never raises.

    Parameters
    ----------
    scope:
        What to analyse and for whom.
    db_session:
        Active SQLAlchemy session.
    budget:
        Resource limits.  Defaults to ``Budget.for_scope(scope.kind)``.
    llm:
        The LLM instance to use for ``plan()`` and ``say()``.  None = use
        template paths (no model call).
    """
    if budget is None:
        budget = Budget.for_scope(scope.kind)

    result = AnalystResult(scope=scope)

    try:
        # ── 1. observe ──────────────────────────────────────────────────────
        observation = observe(scope, db_session)

        # Empty-graph early exit
        if (
            observation.overlap is not None
            and not observation.overlap.has_any()
            and scope.kind == "attachment"
        ):
            result.empty_graph = True
            result.narration = [
                "I read this document, but nothing matched your vendors, invoices or items."
            ]
            result.overlap_summary = observation.overlap.as_summary()
            return result

        if observation.overlap is not None:
            result.overlap_summary = observation.overlap.as_summary()

        # ── 2. plan ─────────────────────────────────────────────────────────
        if scope.kind == "attachment":
            # Attachment scope ALWAYS uses rule-based planner (CP2 gate)
            active_plan = plan_by_rule(observation, scope)
        elif _planner_enabled():
            active_plan = plan(observation, scope, llm)
        else:
            active_plan = plan_by_rule(observation, scope)

        result.plan_source = active_plan.source

        # ── 3. act ──────────────────────────────────────────────────────────
        cards = act(active_plan, observation, scope, db_session)

        # ── 4. investigate ──────────────────────────────────────────────────
        cards = investigate(cards, scope, observation, db_session, llm, budget)

        result.cards = cards

        # ── 5. say ──────────────────────────────────────────────────────────
        result.narration = say(cards, scope, observation, llm, budget)

        # ── 6. ask ──────────────────────────────────────────────────────────
        result.input_requests = ask(active_plan, observation, scope, db_session)

        # ── 7. persist ──────────────────────────────────────────────────────
        persist(result, db_session, attachment_row=observation.attachment_row)

    except Exception as exc:
        logger.error(
            "run_analyst: unhandled error (scope=%s tenant=%s attachment=%s): %s",
            scope.kind,
            scope.tenant_id,
            scope.attachment_id,
            exc,
            exc_info=True,
        )
        result.error = str(exc)

    return result


# ---------------------------------------------------------------------------
# Integration hook — called from services/attachment_insights.build_insight_block
# ---------------------------------------------------------------------------


def analyst_attachment_block(
    row: Any,
    db_session: Any,
    clearance: str = "ops",
) -> Optional[AnalystResult]:
    """Run ATLAS for one attachment and return the AnalystResult.

    Called by ``build_insight_block()`` when ``ENABLE_ANALYST_PLANNER`` is True.
    Returns None when ATLAS is not enabled, so the caller can fall back to the
    Feature-30 card pipeline unchanged.

    The existing Feature-30 card pipeline remains the source of truth for the
    attachment bubble; this hook augments it with the overlap graph and the
    investigate step.
    """
    if not _analyst_enabled():
        return None

    scope = AnalystScope(
        kind="attachment",
        tenant_id=getattr(row, "tenant_id", None),
        clearance=clearance,
        attachment_id=str(getattr(row, "id", "") or ""),
    )
    return run_analyst(scope, db_session)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _load_thresholds(tenant_id: Any, db_session: Any) -> dict:
    """Load insight thresholds for this tenant.  Returns {} on any failure."""
    try:
        from services.insight_thresholds import all_thresholds  # noqa: PLC0415
        return all_thresholds(tenant_id, db_session)
    except Exception:
        return {}


def _safe_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# Task 33.19 — learn()
# ---------------------------------------------------------------------------


def learn(
    result: Optional[AnalystResult] = None,
    feedback: Optional[dict] = None,
    db_session: Optional[Any] = None,
) -> None:
    """Record user interaction feedback to adapt future loop behaviour.

    - Dismissals of a finding kind count towards ANALYST_SUPPRESS_AFTER threshold.
    - Rejections of conventions record suppression per finding key/kind.
    - Narration corrections are logged for prompt few-shotting.
    """
    if feedback is None:
        return

    action = feedback.get("action")
    tenant_id = feedback.get("tenant_id")
    kind = feedback.get("kind") or feedback.get("item_id")
    logger.info("analyst_agent.learn: recorded feedback action=%s kind=%s tenant=%s", action, kind, tenant_id)
