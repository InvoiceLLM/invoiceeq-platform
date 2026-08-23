"""Feature 24 (Ops Digest Agent) — the agent itself: tier split, LLM synthesis, rendering.

This is the piece the feature exists for. `services/ops_digest_collect.py` finds
what happened; `services/ops_digest_routing.py::classify()` decides what pages;
this module turns what is left into something a human can act on in thirty
seconds, and `services/ops_digest_delivery.py` sends it.

The three rules that make this a digest and not a dump
------------------------------------------------------
1. **Critical items are excluded, not re-sent.** Anything `classify()` returns
   ``"critical"`` for has already been paged by the existing Azure Monitor
   action group, in real time, before this job ever woke up. Re-listing it here
   would page the same incident twice, six hours late — worse than not
   mentioning it. They are counted (`OpsDigestResult.critical_count`) and named
   in a single line so the reader knows the digest is not pretending they did
   not happen, and that is all.

   The one exception this design has to be honest about: an AI-eval finding
   classified critical (a sharp quality drop, or `audit_job_failed`) has **no
   existing pager wired to it at all** — Feature 23 emits no Azure Monitor alert.
   So for those, "already handled by immediate alert routing" is currently
   false. They are therefore listed *by name* in the critical line rather than
   silently dropped, with an explicit note saying nothing else has notified
   anyone about them. Wiring a real immediate path for AI-eval criticals is a
   separate piece of work (it needs a scheduled-query alert rule over the
   telemetry mirror) and is recorded as a gap, not quietly assumed to exist.

2. **Fired-and-self-resolved items are compressed to one line each,
   deterministically, with no LLM involved.** The feature doc is explicit that
   these need no decision, so they need no analysis. Rendering them in Python
   rather than asking the model to "keep it brief" is the only way to *guarantee*
   one line — and it means the common case (a memory alert that resolved itself
   overnight, which is most of what this environment actually produces) costs
   zero tokens.

3. **Everything that does need a decision gets a written analysis** — what
   happened, likely cause, suggested action — from one structured LLM call over
   the whole set. One call, not one per item, for two reasons: cost, and because
   a spend spike and a scaling event in the same window are usually the same
   story, which a per-item call structurally cannot see.

Failure behaviour
-----------------
The LLM step is fail-open. If the model is unreachable, or returns nothing for
an item, the digest still renders — with the raw detail and the deterministic
`component_hint`, plus a line saying the analysis step failed. A digest that
arrives without commentary is degraded; a digest that does not arrive because
the judge had a bad minute is an outage nobody hears about.

What this agent may do
----------------------
Nothing but describe. Per the feature doc: *it proposes, it does not act*. There
is no code path here that changes scaling, cost, model config, data or deployed
code, and `suggested_action` is a string in a message — never a command that is
executed.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence, Tuple

from pydantic import BaseModel, Field

from services.ops_digest_collect import (
    AREA_ORDER,
    AREA_TITLES,
    SOFT_METRIC_COMPONENT_HINTS,
    DigestCollection,
    DigestItem,
)
from services.ops_digest_routing import classify

logger = logging.getLogger(__name__)


#: Cap on how many needs-decision items go into one LLM prompt. Past this, the
#: window is not a digest, it is an incident, and the right output is "23 items
#: needed a decision, here are the 12 most recent" rather than a 6,000-token
#: prompt that costs more than the incident.
MAX_ANALYSED_ITEMS = 12

#: Per-item detail sent to the model, in characters. An alert description is
#: usually one line; a cost breakdown can be long. Truncated rather than
#: dropped, same convention as `services/agent_eval.py::_truncate`.
MAX_ITEM_DETAIL_CHARS = 1200

#: Bounds the synthesis response. Three short paragraphs per item x 12 items,
#: plus a headline, fits comfortably; this stops a runaway generation from
#: producing a digest longer than the raw data it replaced.
SYNTHESIS_MAX_TOKENS = 2000

#: The agent name this module's LLM call is recorded under in Feature 23's
#: `llm_agent_call` cost telemetry. Its own namespace so the digest agent's own
#: token spend is separable from the product's — an ops agent that quietly
#: became a top-3 cost line would be a bad joke.
SYNTHESIS_AGENT_NAME = "ops_digest.synthesis"


# ---------------------------------------------------------------------------
# Tier split
# ---------------------------------------------------------------------------


def split_by_tier(items: Sequence[DigestItem]) -> Tuple[List[DigestItem], List[DigestItem]]:
    """``(critical, digest)`` — `classify()` applied to every item's signal.

    No logic of its own on purpose. The whole point of `ops_digest_routing` being
    a separate, tested module is that the decision lives in exactly one place; if
    this function ever grows an `if`, that has stopped being true.
    """
    critical: List[DigestItem] = []
    digest: List[DigestItem] = []
    for item in items:
        (critical if classify(item.signal) == "critical" else digest).append(item)
    return critical, digest


def partition_digest_items(
    items: Sequence[DigestItem],
) -> Tuple[List[DigestItem], List[DigestItem]]:
    """``(needs_decision, self_resolved)`` — rule 2 in the module docstring."""
    needs_decision = [item for item in items if not item.self_resolved]
    self_resolved = [item for item in items if item.self_resolved]
    return needs_decision, self_resolved


def compress_self_resolved(items: Sequence[DigestItem]) -> List[str]:
    """One short line per item that fired and ended on its own.

    Format: ``rule/title — fired 04:12 UTC, self-resolved after 47m``. Times are
    UTC and rendered to the minute: a digest read six hours later does not need
    seconds, and "roughly when" is what the feature doc asks for.
    """
    lines: List[str] = []
    for item in items:
        when = item.occurred_at.strftime("%d %b %H:%M UTC") if item.occurred_at else "unknown time"
        duration = item.duration_text()
        tail = f"self-resolved after {duration}" if duration else "self-resolved"
        lines.append(f"{item.title} — fired {when}, {tail}")
    return lines


# ---------------------------------------------------------------------------
# Synthesis schema
# ---------------------------------------------------------------------------


class ItemAnalysis(BaseModel):
    """The three things the feature doc requires per needs-decision item."""

    model_config = {"extra": "forbid"}

    item_key: str = Field(
        description=(
            "The exact `key` of the item this analysis is for, copied verbatim "
            "from the input. Used to match the analysis back to its item."
        )
    )
    what_happened: str = Field(
        description="One or two plain sentences. State the observation, not the metric name."
    )
    likely_cause: str = Field(
        description=(
            "The most probable cause given the evidence supplied. If the evidence "
            "does not support a specific cause, say what would distinguish the "
            "candidates rather than inventing one."
        )
    )
    suggested_action: str = Field(
        description=(
            "One concrete next step a person can take. It may be 'no action, "
            "watch the next window'. Never a command to be executed automatically."
        )
    )


class DigestSynthesis(BaseModel):
    model_config = {"extra": "forbid"}

    headline: str = Field(
        default="",
        description=(
            "One sentence covering the whole window -- what a reader should take "
            "away if they read nothing else."
        )
    )
    analyses: List[ItemAnalysis] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Prompt
# ---------------------------------------------------------------------------


def _truncate(text: str, limit: int = MAX_ITEM_DETAIL_CHARS) -> str:
    text = text or ""
    if len(text) <= limit:
        return text
    return text[:limit] + " …(truncated)"


def _one_line(text: str, limit: int = 240) -> str:
    """Collapse a multi-line error into one readable bullet.

    Not cosmetic: a psycopg2 ``OperationalError`` is six lines of host/port
    retries plus a docs URL, and dropped verbatim into a Teams card it buries
    the two other collection errors next to it. Observed on the first real run
    of `scripts/ops_digest_job.py`, not anticipated.
    """
    collapsed = " ".join((text or "").split())
    return collapsed if len(collapsed) <= limit else collapsed[:limit] + " …"


def _render_item_for_prompt(item: DigestItem) -> str:
    import json  # noqa: PLC0415 - only needed on the prompt path

    lines = [
        f"- key: {item.key}",
        f"  area: {AREA_TITLES.get(item.area, item.area)}",
        f"  title: {item.title}",
    ]
    if item.occurred_at:
        lines.append(f"  first seen: {item.occurred_at.isoformat()}")
    if item.component_hint:
        lines.append(f"  where to look (from the component map): {item.component_hint}")
    detail = _truncate(json.dumps(item.detail, default=str, sort_keys=True))
    lines.append(f"  evidence: {detail}")
    return "\n".join(lines)


def build_synthesis_prompt(
    items: Sequence[DigestItem],
    *,
    window_start: datetime,
    window_end: datetime,
    self_resolved_items: Sequence[DigestItem] = (),
    critical_count: int = 0,
) -> str:
    """The synthesis prompt. Written as a rubric, not a request for prose.

    Three things in here are deliberate and load-bearing:

    * The **anti-restatement rule**. The single most likely failure mode of this
      feature is a model that reads "memory above 85% on ca-invoice-be-dev" and
      writes back "memory was above 85% on ca-invoice-be-dev", producing a digest
      that costs tokens and adds nothing. It is called out first, with an example
      of the failure, because a rule stated as an example is obeyed and a rule
      stated as an adjective ("be insightful") is not — the same lesson
      `services/agent_eval.py`'s four judge failure modes were written up from.
    * The **"say you don't know" clause**. An ops digest that confidently
      misattributes a cause is worse than one that says the evidence is
      ambiguous, because the reader acts on it. Speculation dressed as diagnosis
      is the specific thing to avoid.
    * The **soft-metric → component map** is pasted in for the AI-quality area,
      per the feature doc's Area 3 requirement to suggest *where to look*.
    """
    component_map = "\n".join(
        f"    - {metric}: {hint}" for metric, hint in SOFT_METRIC_COMPONENT_HINTS.items()
    )
    rendered_items = "\n".join(_render_item_for_prompt(item) for item in items)

    context_lines = [
        f"Window: {window_start.isoformat()} to {window_end.isoformat()} (UTC).",
    ]
    if self_resolved_items:
        # The one-liners are handed over as *context*, not as work. The first
        # real run against live data (2026-08-23) analysed a still-firing
        # `memory-high` alert without knowing the same rule had fired and
        # self-resolved 12 times in the same 72 hours -- which is the single most
        # useful fact about it, and turns "investigate a possible leak" into
        # "this rule's threshold is wrong". Cheap to supply (one short line
        # each) and it is exactly the cross-item pattern a per-item call could
        # never see.
        context_lines.append(
            f"{len(self_resolved_items)} other item(s) fired and resolved on their own in "
            "this window. They are already summarised in one line each and you must NOT "
            "write an analysis for them -- but DO use them as context, especially if one "
            "of the items below is a repeat of something in this list:"
        )
        context_lines.extend(f"  * {line}" for line in compress_self_resolved(self_resolved_items))
    if critical_count:
        context_lines.append(
            f"{critical_count} item(s) were classified critical and paged separately -- "
            "they are not in the list below."
        )

    return (
        "You are the ops digest agent for an invoice-processing SaaS running on Azure "
        "Container Apps. You write a short internal briefing, a few times a day, for the "
        "one person who runs this system. You describe and propose; you never act.\n\n"
        + "\n".join(context_lines)
        + "\n\nFor EACH item below, write three things:\n"
        "  what_happened   -- the observation in plain words\n"
        "  likely_cause    -- the most probable explanation given the evidence\n"
        "  suggested_action-- one concrete next step (may be 'no action, watch the next window')\n\n"
        "RULES\n"
        "1. Do not restate the item. 'Memory exceeded 85% on ca-invoice-be-dev' as "
        "what_happened, for an item titled 'memory-high on ca-invoice-be-dev', is a "
        "failure -- the reader already has the title. Add the thing they do not have: "
        "what it implies, what it is consistent with, what it rules out.\n"
        "2. If the evidence does not support a specific cause, SAY SO and name what "
        "would distinguish the possibilities (a metric to check, a log to read). Do not "
        "invent a cause to fill the field. A confident wrong diagnosis is worse than an "
        "honest 'ambiguous, check X' because it will be acted on.\n"
        "3. Suggested actions are for a human to take. Never propose that anything be "
        "changed automatically, and never propose a change to production data.\n"
        "4. Cost items: explain what changed and why it plausibly changed (which service, "
        "what usually drives that service's spend here), not just the percentage.\n"
        "5. Health items: name the likely mechanism -- a restart pattern, a scaling event "
        "and its trigger, a dependency -- not just the metric.\n"
        "6. AI-quality items: use this metric-to-component map to say WHERE to look:\n"
        f"{component_map}\n"
        "   Note the confidence field where present: a 'proxy' or 'heuristic' signal must "
        "not be described with the certainty of a measured one.\n"
        "7. Two or three sentences per field. This is read on a phone.\n"
        "8. Return exactly one analysis per item key, using the key verbatim.\n\n"
        "Also write a one-sentence `headline` for the whole window.\n\n"
        "ITEMS\n"
        f"{rendered_items}\n"
    )


# ---------------------------------------------------------------------------
# The LLM call
# ---------------------------------------------------------------------------


@dataclass
class SynthesisResult:
    headline: str = ""
    analyses: Dict[str, ItemAnalysis] = field(default_factory=dict)
    llm_calls: int = 0
    error: str = ""
    #: Items that were sent but came back with no analysis. Reported rather than
    #: hidden -- an item silently losing its commentary looks identical to an
    #: item that had nothing worth saying.
    missing_keys: List[str] = field(default_factory=list)
    truncated_count: int = 0


def synthesize_digest(
    items: Sequence[DigestItem],
    *,
    window_start: datetime,
    window_end: datetime,
    llm: Any = None,
    self_resolved_items: Sequence[DigestItem] = (),
    critical_count: int = 0,
) -> SynthesisResult:
    """One structured LLM call producing an analysis per needs-decision item.

    Uses the application's own `get_llm()` / `with_structured_output()` path —
    the same one `services/agent_eval.py` and every agent in `agents/` use — so
    the digest runs on whatever model the deployment is configured for, with no
    second client, second key or second provider setting to keep in sync.

    Never raises. See the module docstring on fail-open.
    """
    result = SynthesisResult()
    if not items:
        return result

    analysed = list(items[:MAX_ANALYSED_ITEMS])
    result.truncated_count = max(0, len(items) - len(analysed))

    if llm is None:
        try:
            from utils.llm import get_llm  # noqa: PLC0415

            llm = get_llm(max_tokens=SYNTHESIS_MAX_TOKENS)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Ops digest: could not construct an LLM: %s", exc)
            result.error = f"LLM unavailable: {type(exc).__name__}: {exc}"
            result.missing_keys = [item.key for item in analysed]
            return result

    prompt = build_synthesis_prompt(
        analysed,
        window_start=window_start,
        window_end=window_end,
        self_resolved_items=self_resolved_items,
        critical_count=critical_count,
    )

    try:
        from telemetry import tracked_llm_call  # noqa: PLC0415

        structured = llm.with_structured_output(DigestSynthesis)
        with tracked_llm_call(SYNTHESIS_AGENT_NAME, llm=llm):
            response = structured.invoke(prompt)
        result.llm_calls = 1
    except Exception as exc:  # noqa: BLE001
        logger.warning("Ops digest: synthesis call failed: %s", exc)
        result.error = f"synthesis failed: {type(exc).__name__}: {exc}"
        result.missing_keys = [item.key for item in analysed]
        return result

    if response is None:
        result.error = "synthesis returned nothing"
        result.missing_keys = [item.key for item in analysed]
        return result

    result.headline = (getattr(response, "headline", "") or "").strip()
    by_key: Dict[str, ItemAnalysis] = {}
    for analysis in getattr(response, "analyses", None) or []:
        key = (getattr(analysis, "item_key", "") or "").strip()
        if key:
            by_key[key] = analysis
    result.analyses = by_key
    result.missing_keys = [item.key for item in analysed if item.key not in by_key]
    return result


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


@dataclass
class OpsDigestResult:
    """One digest run, start to finish. What the job returns and telemetry mirrors."""

    window_start: datetime
    window_end: datetime
    critical_items: List[DigestItem] = field(default_factory=list)
    needs_decision: List[DigestItem] = field(default_factory=list)
    self_resolved: List[DigestItem] = field(default_factory=list)
    synthesis: SynthesisResult = field(default_factory=SynthesisResult)
    collection_errors: List[str] = field(default_factory=list)
    subject: str = ""
    body: str = ""

    @property
    def critical_count(self) -> int:
        return len(self.critical_items)

    @property
    def item_count(self) -> int:
        return len(self.needs_decision) + len(self.self_resolved)

    @property
    def is_empty(self) -> bool:
        """True when nothing at all happened *and* nothing failed to collect.

        Collection errors count as content: a window where Resource Graph 403'd
        is not a quiet window, and must not be suppressed by a 'nothing to
        report' rule.
        """
        return not self.items_present and not self.collection_errors

    @property
    def items_present(self) -> bool:
        return bool(self.critical_items or self.needs_decision or self.self_resolved)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "window_start": self.window_start.isoformat(),
            "window_end": self.window_end.isoformat(),
            "critical_count": self.critical_count,
            "critical_keys": [item.key for item in self.critical_items],
            "needs_decision": [item.to_dict() for item in self.needs_decision],
            "self_resolved": [item.to_dict() for item in self.self_resolved],
            "headline": self.synthesis.headline,
            "analyses": {
                key: analysis.model_dump() for key, analysis in self.synthesis.analyses.items()
            },
            "synthesis_error": self.synthesis.error,
            "synthesis_missing_keys": list(self.synthesis.missing_keys),
            "llm_calls": self.synthesis.llm_calls,
            "collection_errors": list(self.collection_errors),
            "subject": self.subject,
            "body": self.body,
        }


def _critical_line(items: Sequence[DigestItem]) -> List[str]:
    """The 'already paged, not repeated here' line — plus the honest exception.

    AI-eval criticals have no immediate pager wired to them (see rule 1 in the
    module docstring), so they are named here. Azure alert criticals genuinely
    were paged by the action group, so they are only counted.
    """
    if not items:
        return []
    azure = [item for item in items if item.signal.get("source") == "azure_alert"]
    other = [item for item in items if item.signal.get("source") != "azure_alert"]

    lines: List[str] = []
    if azure:
        lines.append(
            f"{len(azure)} critical alert(s) fired in this window and were paged in real time "
            "by the Azure Monitor action group. Not repeated here."
        )
    for item in other:
        lines.append(
            f"CRITICAL, and nothing else has notified anyone about it: {item.title}"
        )
    return lines


def render_digest(result: OpsDigestResult) -> Tuple[str, str]:
    """``(subject, body)``. Markdown body, plain enough to read as text.

    One renderer, not one per channel: the Teams webhook and the email both take
    this same string. Markdown reads acceptably as plain text, which a
    channel-specific renderer would only have bought at the price of two things
    to keep in sync.
    """
    # The end date is included whenever it differs from the start date. With the
    # 6-hour production window they are usually the same day, but a manual
    # `--window-hours 72` rendered "20 Aug 10:26-10:26 UTC" on the first real
    # run, which reads as a zero-length window.
    if result.window_start.date() == result.window_end.date():
        window = (
            f"{result.window_start.strftime('%d %b %H:%M')}–"
            f"{result.window_end.strftime('%H:%M UTC')}"
        )
    else:
        window = (
            f"{result.window_start.strftime('%d %b %H:%M')}–"
            f"{result.window_end.strftime('%d %b %H:%M UTC')}"
        )

    if not result.items_present and not result.collection_errors:
        subject = f"Ops digest {window}: nothing to report"
        return subject, (
            f"**Ops digest** ({window})\n\n"
            "Nothing fired, no cost movement past the threshold, no quality change "
            "past the threshold. All three sources were collected successfully."
        )

    headline = result.synthesis.headline
    subject_bits: List[str] = []
    if result.needs_decision:
        subject_bits.append(f"{len(result.needs_decision)} to review")
    if result.self_resolved:
        subject_bits.append(f"{len(result.self_resolved)} self-resolved")
    if result.critical_count:
        subject_bits.append(f"{result.critical_count} critical (already paged)")
    subject = f"Ops digest {window}: " + (", ".join(subject_bits) or "collection issues only")

    lines: List[str] = [f"**Ops digest** ({window})", ""]
    if headline:
        lines.extend([headline, ""])

    for line in _critical_line(result.critical_items):
        lines.append(f"> {line}")
    if result.critical_items:
        lines.append("")

    for area in AREA_ORDER:
        area_needs = [item for item in result.needs_decision if item.area == area]
        area_resolved = [item for item in result.self_resolved if item.area == area]
        if not area_needs and not area_resolved:
            continue
        lines.append(f"### {AREA_TITLES.get(area, area)}")
        lines.append("")

        for item in area_needs:
            lines.append(f"**{item.title}**")
            analysis = result.synthesis.analyses.get(item.key)
            if analysis:
                lines.append(f"- What happened: {analysis.what_happened}")
                lines.append(f"- Likely cause: {analysis.likely_cause}")
                lines.append(f"- Suggested action: {analysis.suggested_action}")
            else:
                lines.append(
                    "- _No written analysis for this item "
                    f"({result.synthesis.error or 'the model returned none'})._"
                )
                if item.component_hint:
                    lines.append(f"- Where to look: {item.component_hint}")
            lines.append("")

        if area_resolved:
            lines.append(f"_Fired and self-resolved ({len(area_resolved)}):_")
            for line in compress_self_resolved(area_resolved):
                lines.append(f"- {line}")
            lines.append("")

    if result.synthesis.truncated_count:
        lines.append(
            f"_{result.synthesis.truncated_count} further item(s) needing a decision were not "
            f"analysed — more than {MAX_ANALYSED_ITEMS} in one window is itself the finding._"
        )
        lines.append("")

    if result.collection_errors:
        lines.append("### Collection health")
        lines.append("")
        lines.append(
            "_These sources did not report. Their sections above are incomplete, "
            "not quiet:_"
        )
        for error in result.collection_errors:
            lines.append(f"- {_one_line(error)}")
        lines.append("")

    lines.append(
        "_This agent proposes; it does not act. Nothing above has been changed for you._"
    )
    return subject, "\n".join(lines).rstrip() + "\n"


# ---------------------------------------------------------------------------
# One run
# ---------------------------------------------------------------------------


def build_digest(
    collection: DigestCollection,
    *,
    llm: Any = None,
    use_llm: bool = True,
) -> OpsDigestResult:
    """Collection → tier split → synthesis → rendered digest. No I/O of its own.

    Separate from `run_ops_digest()` so the whole agent (bar collection and
    delivery, which are the network-touching halves) is testable by handing it a
    `DigestCollection` built in memory.
    """
    critical, digest_items = split_by_tier(collection.items)
    needs_decision, self_resolved = partition_digest_items(digest_items)

    result = OpsDigestResult(
        window_start=collection.window_start,
        window_end=collection.window_end,
        critical_items=critical,
        needs_decision=needs_decision,
        self_resolved=self_resolved,
        collection_errors=list(collection.errors),
    )

    if needs_decision and use_llm:
        result.synthesis = synthesize_digest(
            needs_decision,
            window_start=collection.window_start,
            window_end=collection.window_end,
            llm=llm,
            self_resolved_items=self_resolved,
            critical_count=len(critical),
        )
    elif needs_decision and not use_llm:
        result.synthesis = SynthesisResult(
            error="LLM synthesis disabled for this run (--no-llm)",
            missing_keys=[item.key for item in needs_decision],
        )

    result.subject, result.body = render_digest(result)
    return result


def run_ops_digest(
    session: Any = None,
    *,
    window_hours: Optional[float] = None,
    now: Optional[datetime] = None,
    llm: Any = None,
    use_llm: bool = True,
    cost_snapshot: Any = None,
) -> OpsDigestResult:
    """Collect, classify, synthesise, render. Does **not** deliver.

    Delivery is the caller's decision (`scripts/ops_digest_job.py`), because a
    dry run has to be able to produce the exact digest that would have been sent
    without sending it.
    """
    from services.ops_digest_collect import collect_all  # noqa: PLC0415

    collection = collect_all(
        session,
        window_hours=window_hours,
        now=now or datetime.now(timezone.utc),
        cost_snapshot=cost_snapshot,
    )
    return build_digest(collection, llm=llm, use_llm=use_llm)


__all__ = [
    "MAX_ANALYSED_ITEMS",
    "SYNTHESIS_AGENT_NAME",
    "DigestSynthesis",
    "ItemAnalysis",
    "OpsDigestResult",
    "SynthesisResult",
    "build_digest",
    "build_synthesis_prompt",
    "compress_self_resolved",
    "partition_digest_items",
    "render_digest",
    "run_ops_digest",
    "split_by_tier",
    "synthesize_digest",
]
