"""Feature 23 — online evaluation signals over live traffic.

What this is
------------
`feature_23_ai_control_tower.md`, "Where each tier runs":

    **Online** (live traces, no ground truth): alert on signal shapes already
    proven real in this repo's own history, not hypothetical — budget-exhaustion
    rate, clarification rate, zero-result rate (Gap 224's false-confident-zero
    shape), turns exceeding a latency threshold (Gap 278's shape), thumbs-down
    clustering.

Those five, computed against the tables that actually exist today: `ChatMessage`
(+ `ChatSession` for tenant scoping), `ChatFeedback`, and the existing columns of
`AgentEvalRun`. No schema change, no new table, no dependency on Application
Insights being wired up.

Every signal states its own confidence
--------------------------------------
This is the point of the module, not a disclaimer. Three of the five are direct
measurements; two are not, and a dashboard that presented all five as equally
solid would be worse than no dashboard:

===========================  =============  ==================================
Signal                       Confidence     Why
===========================  =============  ==================================
`zero_result_rate`           measured       Exact string the code itself emits
`thumbs_down_clustering`     measured       `ChatFeedback.vote` is the fact
`slow_turn_rate`             proxy          Row-timestamp delta, not an
                                            instrumented timer (see below)
`budget_exhaustion_rate`     offline-only   Dead as of Gap 316 — nothing writes
                                            a `stop_reason` any more (see below)
`clarification_rate`         heuristic      Live clarifications leave no marker
                                            in the DB at all
===========================  =============  ==================================

Gap 316 (2026-08-25) killed one of these outright — read before trusting the panel
---------------------------------------------------------------------------------
The SAGE orchestrator was deleted after a live head-to-head measured it slower and
dearer than the default path with no correctness benefit. That gap's tracker entry
names two signals here as casualties. **Only one of them actually died**, and the
difference decides whether a number on the panel is worth reading:

* **`budget_exhaustion_rate` is dead, permanently, and is not fixable from any
  surviving source.** Its numerator *and* its denominator come only from
  `stop_reason=` fragments in `AgentEvalRun.notes`, and `scripts/run_agent_eval.py`
  stopped writing those when the path they described was deleted (its `notes`
  assembly carries a comment saying exactly that). The measured *concept* is gone
  too, not merely unwritten: `MAX_TOOL_CALLS` and `tool_call_budget_exhausted`
  belonged to the deleted planner loop, and neither name appears in live code
  anywhere now. So the denominator is 0 on every window from here on, `value` is
  `None` and `breached` is `False` forever. Retiring the signal is a **product
  decision, not a bug fix** — it is left in place, computing honestly, until the
  founder rules on whether the five-signal set becomes four.
* **`clarification_rate` did NOT die**, despite being listed alongside it. Its
  headline `value`/`numerator`/`denominator` are computed by
  `looks_like_clarification()` over `chat_message` assistant rows and never
  touched SAGE at all. What died is the *offline exact* cross-check inside its
  `detail` (`offline_exact_clarification_turns` and its two siblings), which reads
  the same dead notes. The headline rate still measures real traffic, and the
  population is real rather than theoretical: Feature 23 Track 2's judge runs
  caught the **default** route answering with a clarifying question of its own
  accord — one that leaked raw SQL into it (Gap 294, recorded at
  `agents/query_agent.py`'s SQL-leak scrubber).

Where "a turn stopped abnormally" *is* readable today, since it is the first thing
anyone asks after the above: the `chat_turn` telemetry event carries a real
`stop_reason` on every live turn (`sql_attempts_exhausted`, `sql_declined`,
`sql_summary_failed`, `rag_answer_failed`, `chat_answer_failed`,
`route_override_followup`), set by `agents/query_agent.py` and by the queue
handler. That lives in Log Analytics, not Postgres, so it is deliberately out of
this module's reach — it is a workbook query, and the workbook already has a tile
bound to it.

The two real gaps, stated rather than papered over
--------------------------------------------------
1. **`stop_reason` never reaches the database on a live turn — and since Gap 316
   it reaches it on no turn at all.** Until 2026-08-25 the deleted
   `agents/sage_orchestrator.py` computed `tool_call_budget_exhausted` /
   `clarification_requested` / `planner_step_budget_exhausted` and returned them
   in `run_agentic_sage()`'s metadata, but `ChatMessage` never had a column for
   them and nothing wrote them anywhere durable; the only persisted copy was the
   free text `AgentEvalRun.notes` written by `scripts/run_agent_eval.py`, which
   covered *eval* turns only. With SAGE deleted, that writer is gone as well, so
   `budget_exhaustion_rate` no longer measures even the offline harness. Closing
   this on the Postgres side would need a `stop_reason` column on `ChatMessage`
   plus a migration — new design work, and a founder call, not something this
   module gets to take.
2. **Turn latency is not recorded anywhere.** `ChatMessage` has `created_at` and
   nothing else time-related. The proxy below (assistant row timestamp minus its
   own user row timestamp) is genuinely end-to-end — under Gap 280's queue
   architecture the user row is written at enqueue and the assistant row after
   the agent returns, so it includes queue wait, which is exactly what Gap 278's
   founder-reported "chat is failing then working again" actually was. It is
   still a derived figure with clock-skew and retry caveats, not a timer.

Thread-level drift (Gaps 237/276) is deliberately **not** here. The doc scopes it
as needing new design work, and no signal in this module detects it.
"""

from __future__ import annotations

import logging
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from typing import Any, Optional
from uuid import UUID

from sqlmodel import Session, select

from models import ChatFeedback, ChatMessage, ChatSession
# Gap 304 half (2): `agent_eval_run` holds production rows now, and the
# stop-reason signals below mean the golden bank. See `_eval_run_notes()`.
from telemetry import RUN_SOURCE_PRODUCTION

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Tunables — every default traced to a real observation, not a round number
# ---------------------------------------------------------------------------

DEFAULT_WINDOW_DAYS = 7

#: Gap 278 measured two real chat turns at ~177s against `ca-invoice-be-dev`,
#: and recorded that "a long tail of otherwise-'normal' chat turns already sits
#: at 20-40s even outside this bug". 45s therefore sits above the known-normal
#: tail and well below the pathological case: it fires on the shape Gap 278 was,
#: not on the everyday slowness that gap explicitly documented as pre-existing.
SLOW_TURN_THRESHOLD_SECONDS = 45.0

#: Alert thresholds. Deliberately per-signal rather than one global number —
#: a 10% clarification rate is healthy, a 10% budget-exhaustion rate is not.
BUDGET_EXHAUSTION_ALERT_RATE = 0.10
CLARIFICATION_ALERT_RATE = 0.25
ZERO_RESULT_ALERT_RATE = 0.20
SLOW_TURN_ALERT_RATE = 0.05
THUMBS_DOWN_ALERT_RATE = 0.20

#: A cluster needs enough votes to mean anything. Two thumbs-down in one day on
#: a low-traffic tenant is noise; five is a pattern worth a human looking.
MIN_CLUSTER_SIZE = 3

#: Below this many observations a rate is reported but never alerted on — the
#: single most common way a quality dashboard cries wolf.
MIN_SAMPLE_FOR_ALERT = 20


# ---------------------------------------------------------------------------
# Markers the product itself emits
# ---------------------------------------------------------------------------

#: Mirrors `agents.query_agent.NO_RECORDS_FOUND`. Duplicated rather than
#: imported so this module stays free of the LangChain import chain; a test
#: asserts the two are identical, so a drift fails loudly instead of silently
#: zeroing this signal.
NO_RECORDS_FOUND = "No records found matching the query criteria."

#: Was written into `AgentEvalRun.notes` by `scripts/run_agent_eval.py` as
#: `stop_reason=<value>`. Parsed, not queried, because there is no column — and
#: **no longer written by anything as of Gap 316** (2026-08-25), which deleted both
#: the SAGE path that produced these values and the note fragment that recorded
#: them. Kept so the two signals below still read *historical* rows correctly
#: rather than silently reporting a different number for the same past window;
#: no new row can ever match.
STOP_REASON_BUDGET_EXHAUSTED = "stop_reason=tool_call_budget_exhausted"
STOP_REASON_CLARIFICATION = "stop_reason=clarification_requested"
_STOP_REASON_ANY = re.compile(r"stop_reason=([A-Za-z_]+)")

#: The SQL route's own results-table heading. Its presence means the turn
#: answered from data, which rules out a clarifying question.
_RESULTS_TABLE_MARKER = "### Query Results"

#: A confident zero — Gap 224's shape. Matches "USD 0.00", "$0", "INR 0,00".
_ZERO_TOTAL_RE = re.compile(r"(?:USD|EUR|INR|GBP|AUD|CAD|Rs\.?|\$|₹|€|£)\s?0(?:[.,]0{1,2})?(?!\d)")

#: Clarifying-question phrasings. There has never been a marker to match on: the
#: deleted orchestrator's `ask_clarifying_question()` returned the question text
#: verbatim as the turn's answer (`_clarify_node`), and the default route that
#: replaced it has no clarification step at all — when it asks a question it is the
#: model choosing to, which leaves even less behind. So the language is all there
#: is. This is a heuristic and is labelled as one.
_CLARIFICATION_PATTERNS = (
    re.compile(r"\bdid you mean\b", re.IGNORECASE),
    re.compile(r"\bwhich (?:one|of|invoice|vendor|customer)\b", re.IGNORECASE),
    re.compile(r"\bcould you (?:clarify|confirm|specify)\b", re.IGNORECASE),
    re.compile(r"\bcan you (?:clarify|confirm|specify)\b", re.IGNORECASE),
    re.compile(r"\bto (?:make sure|be sure) I\b", re.IGNORECASE),
    re.compile(r"\bare you asking about\b", re.IGNORECASE),
    re.compile(r"\bdo you mean\b", re.IGNORECASE),
)

#: A clarifying question is short by nature. A 3,000-character essay that ends
#: in a question mark is an answer with a closing offer, not a clarification.
_MAX_CLARIFICATION_CHARS = 600


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------

CONFIDENCE_MEASURED = "measured"
CONFIDENCE_PROXY = "proxy"
CONFIDENCE_HEURISTIC = "heuristic"
CONFIDENCE_OFFLINE_ONLY = "offline_only"


@dataclass
class SignalResult:
    """One signal, with everything needed to decide whether to believe it.

    `value` is `None` — never 0.0 — when the denominator was empty. "Nothing
    happened" and "nothing went wrong" are different facts and a dashboard that
    conflated them would show a healthy green on the day ingestion stopped.
    """

    name: str
    value: Optional[float]
    numerator: int
    denominator: int
    confidence: str
    source: str
    threshold: Optional[float] = None
    breached: bool = False
    caveat: str = ""
    detail: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class OnlineEvalSignals:
    window_start: datetime
    window_end: datetime
    tenant_id: Optional[str]
    signals: list[SignalResult] = field(default_factory=list)

    def by_name(self, name: str) -> SignalResult:
        for signal in self.signals:
            if signal.name == name:
                return signal
        raise KeyError(name)

    @property
    def breaches(self) -> list[SignalResult]:
        return [signal for signal in self.signals if signal.breached]

    def as_dict(self) -> dict[str, Any]:
        return {
            "window_start": self.window_start.isoformat(),
            "window_end": self.window_end.isoformat(),
            "tenant_id": self.tenant_id,
            "signals": [signal.as_dict() for signal in self.signals],
            "breached": [signal.name for signal in self.breaches],
        }


def _rate(numerator: int, denominator: int) -> Optional[float]:
    return (numerator / denominator) if denominator else None


def _breached(value: Optional[float], threshold: float, denominator: int) -> bool:
    if value is None or denominator < MIN_SAMPLE_FOR_ALERT:
        return False
    return value >= threshold


# ---------------------------------------------------------------------------
# Shared reads
# ---------------------------------------------------------------------------


def _tenant_session_ids(session: Session, tenant_id: Optional[UUID]) -> Optional[set[UUID]]:
    """`ChatMessage` carries no `tenant_id` — only `session_id`.

    Tenant scoping therefore has to go through `ChatSession`, which is the only
    row that knows the tenant. Returning None means "no tenant filter".
    """
    if tenant_id is None:
        return None
    rows = session.exec(select(ChatSession.id).where(ChatSession.tenant_id == tenant_id)).all()
    return {row if isinstance(row, UUID) else row[0] for row in rows}


def _chat_messages(
    session: Session,
    window_start: datetime,
    window_end: datetime,
    tenant_id: Optional[UUID],
) -> list[ChatMessage]:
    statement = (
        select(ChatMessage)
        .where(ChatMessage.created_at >= window_start)
        .where(ChatMessage.created_at <= window_end)
    )
    messages = list(session.exec(statement).all())
    allowed = _tenant_session_ids(session, tenant_id)
    if allowed is not None:
        messages = [m for m in messages if m.session_id in allowed]
    messages.sort(key=lambda m: (str(m.session_id), m.created_at))
    return messages


def _eval_run_notes(
    session: Session,
    window_start: datetime,
    window_end: datetime,
    tenant_id: Optional[UUID],
) -> list[str]:
    """Free-text notes off `agent_eval_run`, existing columns only.

    Imported lazily and defensively: `AgentEvalRun` is Feature 23 Phase 3's
    table, so this module reads what is there and degrades to "no data" rather
    than assuming a shape. (It used to say "and is under concurrent Feature 21
    work" — Feature 21 was deleted by Gap 316 on 2026-08-25.)

    **Returns only historical matches for the stop-reason signals since Gap 316.**
    `scripts/run_agent_eval.py` no longer emits a `stop_reason=` fragment into
    `notes`, so rows written from 2026-08-25 onward carry none. This function is
    unchanged and still correct — its two callers simply have nothing left to
    match. See the module docstring's Gap 316 section.

    **Golden-bank rows only** (Gap 304 half (2), 2026-08-24), for the same reason
    as `services/ops_digest_collect.py::_eval_window_stats`. Checked rather than
    assumed before adding the filter: both consumers of this list
    (`budget_exhaustion_rate`, `clarification_rate`) reduce it to
    `[note for note in notes if _STOP_REASON_ANY.search(note)]` before counting
    anything, and a production row's notes are a structural summary with no
    `stop_reason=` marker in them — so neither *rate* would have moved. What
    would have moved is `budget_exhaustion_rate`'s
    `detail["eval_rows_in_window"]`, which counts the unfiltered list and is what
    a reader uses to judge whether the denominator is worth trusting; it would
    have grown with live traffic while the denominator stayed flat, which reads
    as "the eval harness ran 4000 turns and only 12 had a stop reason". Filtering
    at the query keeps that number meaning what its name says.
    """
    try:
        from models import AgentEvalRun  # noqa: PLC0415
    except ImportError:  # pragma: no cover - the table is expected to exist
        return []

    statement = (
        select(AgentEvalRun.notes)
        .where(AgentEvalRun.run_at >= window_start)
        .where(AgentEvalRun.run_at <= window_end)
        .where(AgentEvalRun.run_source != RUN_SOURCE_PRODUCTION)
    )
    if tenant_id is not None:
        statement = statement.where(AgentEvalRun.tenant_id == tenant_id)
    try:
        rows = session.exec(statement).all()
    except Exception as exc:  # pragma: no cover - missing table on a partial DB
        logger.warning("agent_eval_run unreadable, stop_reason signals skipped: %s", exc)
        return []
    return [row if isinstance(row, str) else (row[0] or "") for row in rows if row]


def _turn_pairs(messages: list[ChatMessage]) -> list[tuple[ChatMessage, ChatMessage]]:
    """(user, assistant) pairs within a session.

    Paired on `job_id` where both rows carry one — that is the queue path's own
    correlation id (Gap 280) and is exact. Falls back to "nearest preceding user
    row in the same session", which is what the synchronous path leaves behind.
    """
    by_job: dict[str, dict[str, ChatMessage]] = {}
    for message in messages:
        if message.job_id:
            by_job.setdefault(message.job_id, {})[message.role] = message

    pairs: list[tuple[ChatMessage, ChatMessage]] = []
    paired_assistants: set[Any] = set()
    for slots in by_job.values():
        user, assistant = slots.get("user"), slots.get("assistant")
        if user is not None and assistant is not None:
            pairs.append((user, assistant))
            paired_assistants.add(assistant.id)

    pending: dict[Any, ChatMessage] = {}
    for message in messages:
        if message.role == "user":
            pending[message.session_id] = message
        elif message.role == "assistant":
            if message.id in paired_assistants:
                pending.pop(message.session_id, None)
                continue
            user = pending.pop(message.session_id, None)
            if user is not None:
                pairs.append((user, message))
    return pairs


# ---------------------------------------------------------------------------
# Signal 1 — budget exhaustion
# ---------------------------------------------------------------------------


def budget_exhaustion_rate(
    session: Session,
    *,
    window_start: datetime,
    window_end: datetime,
    tenant_id: Optional[UUID] = None,
) -> SignalResult:
    """How often a turn ran out of its `MAX_TOOL_CALLS` budget mid-plan.

    A budget-exhausted turn still answers, from whatever it had managed to fetch
    — which is precisely how a confident-but-under-evidenced answer gets
    produced.

    **Dead as of Gap 316 (2026-08-25); returns a permanently empty denominator.**
    `MAX_TOOL_CALLS` was the deleted SAGE planner's budget, nothing in the product
    has a tool-call budget any more, and `scripts/run_agent_eval.py` no longer
    writes the `stop_reason=` note this parses. It is left computing rather than
    deleted because dropping a signal from the five is the founder's call (Gap
    305); against historical rows it still returns the right past number, and
    against every window from here on it returns `value=None`, which is the module's
    own way of saying "not measured" rather than "measured, nothing found".
    """
    notes = _eval_run_notes(session, window_start, window_end, tenant_id)
    with_stop_reason = [note for note in notes if _STOP_REASON_ANY.search(note or "")]
    exhausted = [note for note in with_stop_reason if STOP_REASON_BUDGET_EXHAUSTED in note]

    value = _rate(len(exhausted), len(with_stop_reason))
    return SignalResult(
        name="budget_exhaustion_rate",
        value=value,
        numerator=len(exhausted),
        denominator=len(with_stop_reason),
        confidence=CONFIDENCE_OFFLINE_ONLY,
        source="agent_eval_run.notes (free text, written by scripts/run_agent_eval.py)",
        threshold=BUDGET_EXHAUSTION_ALERT_RATE,
        breached=_breached(value, BUDGET_EXHAUSTION_ALERT_RATE, len(with_stop_reason)),
        caveat=(
            "DEAD as of Gap 316 (2026-08-25) — the denominator is permanently 0 "
            "and a null value here means 'this can never be measured', not 'a "
            "quiet window'. It read stop_reason= out of agent_eval_run.notes; the "
            "SAGE path that produced those values and the note fragment that "
            "recorded them were both deleted, and no tool-call budget exists in "
            "the product any more. Not fixable from any surviving Postgres "
            "source. Abnormal turn stops ARE readable live, but from the chat_turn "
            "telemetry event's own stop_reason field in Log Analytics, which this "
            "module cannot query. Retiring this signal is a founder decision "
            "(Gap 305), not a code fix."
        ),
        detail={
            "stop_reasons_seen": _count_stop_reasons(with_stop_reason),
            "eval_rows_in_window": len(notes),
        },
    )


def _count_stop_reasons(notes: list[str]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for note in notes:
        for reason in _STOP_REASON_ANY.findall(note or ""):
            counts[reason] = counts.get(reason, 0) + 1
    return dict(sorted(counts.items(), key=lambda item: -item[1]))


# ---------------------------------------------------------------------------
# Signal 2 — clarification rate
# ---------------------------------------------------------------------------


def looks_like_clarification(message: ChatMessage) -> bool:
    """Best-effort detector for "the answer was a question back to the user".

    Exposed rather than kept private so the heuristic is testable and reviewable
    on its own — it is the weakest of the five signals and the one most likely
    to need tuning against real traffic.
    """
    content = (message.content or "").strip()
    if not content or len(content) > _MAX_CLARIFICATION_CHARS:
        return False
    if _RESULTS_TABLE_MARKER in content:
        return False
    if message.citations:
        return False
    if not content.endswith("?"):
        # A clarification whose final sentence is a question but which ends with
        # a closing remark still counts, provided it matches a phrasing.
        if not any(pattern.search(content) for pattern in _CLARIFICATION_PATTERNS):
            return False
        return True
    return True


def clarification_rate(
    session: Session,
    *,
    window_start: datetime,
    window_end: datetime,
    tenant_id: Optional[UUID] = None,
) -> SignalResult:
    """Share of turns that ended by asking the user something instead of answering.

    Two independent readings, because they measure different populations and
    neither alone is the answer: the offline one is exact but covers only eval
    runs, the live one covers real traffic but is a language heuristic.

    **Only the offline reading died with Gap 316 — the headline rate did not.**
    Gap 316's entry lists this signal next to `budget_exhaustion_rate` as
    "permanently degenerate"; that is true of the three `offline_*` keys in
    `detail` (same dead `stop_reason=` notes) and false of `value`/`numerator`/
    `denominator`, which come from `chat_message` assistant rows via
    `looks_like_clarification()` and never had a SAGE dependency. Read the
    headline number; ignore the `offline_*` keys, which are 0 forever.
    """
    messages = _chat_messages(session, window_start, window_end, tenant_id)
    assistants = [m for m in messages if m.role == "assistant"]
    clarifications = [m for m in assistants if looks_like_clarification(m)]

    notes = _eval_run_notes(session, window_start, window_end, tenant_id)
    with_stop_reason = [note for note in notes if _STOP_REASON_ANY.search(note or "")]
    offline_clarifications = [n for n in with_stop_reason if STOP_REASON_CLARIFICATION in n]

    value = _rate(len(clarifications), len(assistants))
    return SignalResult(
        name="clarification_rate",
        value=value,
        numerator=len(clarifications),
        denominator=len(assistants),
        confidence=CONFIDENCE_HEURISTIC,
        source="chat_message (assistant rows), language heuristic",
        threshold=CLARIFICATION_ALERT_RATE,
        breached=_breached(value, CLARIFICATION_ALERT_RATE, len(assistants)),
        caveat=(
            "Heuristic. Nothing in the row marks a clarification, so there is "
            "nothing to match on but the wording. CORRECTED 2026-08-26 (Gap 305): "
            "this caveat used to say a near-zero rate was expected because the "
            "SAGE path behind ENABLE_AGENTIC_SAGE was off, i.e. that a low number "
            "was a configuration fact rather than a quality result. Gap 316 "
            "deleted SAGE and that flag outright, so that reading no longer "
            "applies and must not be used to wave this number away: the default "
            "route has no clarification step, so any turn counted here is the "
            "model choosing to ask rather than answer, and a rise is a real "
            "quality signal. The offline_* keys in detail are dead (Gap 316) and "
            "stay 0 regardless of what the headline rate does."
        ),
        detail={
            "offline_exact_clarification_turns": len(offline_clarifications),
            "offline_turns_with_a_stop_reason": len(with_stop_reason),
            "offline_exact_rate": _rate(len(offline_clarifications), len(with_stop_reason)),
        },
    )


# ---------------------------------------------------------------------------
# Signal 3 — zero-result rate, and Gap 224's false-confident-zero shape
# ---------------------------------------------------------------------------


def zero_result_rate(
    session: Session,
    *,
    window_start: datetime,
    window_end: datetime,
    tenant_id: Optional[UUID] = None,
) -> SignalResult:
    """Share of answers that found nothing — plus the sub-shape that matters more.

    An honest "no matching records" is correct behaviour and Gap 224 was
    ultimately re-closed *because* the honest zero was right. The dangerous
    shape is its opposite: an answer stating a confident `USD 0.00` total
    **without** saying nothing was found. That is reported separately in
    `detail`, because rolling the two together would make a fleet of correct
    refusals look like a fleet of fabrications.
    """
    messages = _chat_messages(session, window_start, window_end, tenant_id)
    assistants = [m for m in messages if m.role == "assistant"]

    honest_zero = [m for m in assistants if NO_RECORDS_FOUND in (m.content or "")]
    confident_zero = [
        m
        for m in assistants
        if NO_RECORDS_FOUND not in (m.content or "")
        and _ZERO_TOTAL_RE.search(m.content or "")
    ]

    value = _rate(len(honest_zero), len(assistants))
    return SignalResult(
        name="zero_result_rate",
        value=value,
        numerator=len(honest_zero),
        denominator=len(assistants),
        confidence=CONFIDENCE_MEASURED,
        source="chat_message.content contains agents.query_agent.NO_RECORDS_FOUND",
        threshold=ZERO_RESULT_ALERT_RATE,
        breached=_breached(value, ZERO_RESULT_ALERT_RATE, len(assistants)),
        caveat=(
            "A zero result is not automatically a defect — Gap 224 was re-closed "
            "because 'no records found' was the correct answer. Read this as a "
            "*rate change*, not as an error count."
        ),
        detail={
            "false_confident_zero_turns": len(confident_zero),
            "false_confident_zero_rate": _rate(len(confident_zero), len(assistants)),
            "false_confident_zero_note": (
                "Gap 224's shape: a confident zero currency total with no "
                "'no records found' anywhere in the answer. Each one is worth "
                "reading by hand; this is a triage queue, not a verdict."
            ),
            "example_message_ids": [str(m.id) for m in confident_zero[:5]],
        },
    )


# ---------------------------------------------------------------------------
# Signal 4 — slow turns (Gap 278's shape)
# ---------------------------------------------------------------------------


def slow_turn_rate(
    session: Session,
    *,
    window_start: datetime,
    window_end: datetime,
    tenant_id: Optional[UUID] = None,
    threshold_seconds: float = SLOW_TURN_THRESHOLD_SECONDS,
) -> SignalResult:
    """Share of turns whose user->assistant gap exceeded `threshold_seconds`.

    Gap 278 was never a backend error — zero 4xx/5xx on the chat path across 48h
    — it was two ~177s turns that any browser timeout reads as "broken". A rate
    of slow turns is therefore the only shape that catches it; an error rate
    never would.
    """
    messages = _chat_messages(session, window_start, window_end, tenant_id)
    pairs = _turn_pairs(messages)

    latencies: list[float] = []
    slow: list[tuple[ChatMessage, float]] = []
    for user, assistant in pairs:
        seconds = (assistant.created_at - user.created_at).total_seconds()
        if seconds < 0:
            continue  # clock skew or a re-ordered write; not a measurement
        latencies.append(seconds)
        if seconds > threshold_seconds:
            slow.append((assistant, seconds))

    value = _rate(len(slow), len(latencies))
    ordered = sorted(latencies)
    return SignalResult(
        name="slow_turn_rate",
        value=value,
        numerator=len(slow),
        denominator=len(latencies),
        confidence=CONFIDENCE_PROXY,
        source="chat_message.created_at delta (assistant row minus its user row)",
        threshold=SLOW_TURN_ALERT_RATE,
        breached=_breached(value, SLOW_TURN_ALERT_RATE, len(latencies)),
        caveat=(
            "Proxy, not a timer. ChatMessage records no duration; this is the gap "
            "between two row timestamps. Under Gap 280's queue path that gap is "
            "genuinely end-to-end (user row written at enqueue, assistant row "
            "after the agent returns), so it includes queue wait — which is what "
            "the user experiences. Negative deltas are discarded rather than "
            "clamped to zero. GAP: a real per-turn latency column or the Phase 1 "
            "telemetry event is needed for an authoritative number."
        ),
        detail={
            "threshold_seconds": threshold_seconds,
            "p50_seconds": _percentile(ordered, 0.50),
            "p95_seconds": _percentile(ordered, 0.95),
            "max_seconds": ordered[-1] if ordered else None,
            "slowest_message_ids": [
                str(message.id) for message, _ in sorted(slow, key=lambda x: -x[1])[:5]
            ],
        },
    )


def _percentile(ordered: list[float], fraction: float) -> Optional[float]:
    if not ordered:
        return None
    index = min(len(ordered) - 1, max(0, int(round(fraction * (len(ordered) - 1)))))
    return ordered[index]


# ---------------------------------------------------------------------------
# Signal 5 — thumbs-down clustering
# ---------------------------------------------------------------------------


def thumbs_down_clustering(
    session: Session,
    *,
    window_start: datetime,
    window_end: datetime,
    tenant_id: Optional[UUID] = None,
) -> SignalResult:
    """Overall thumbs-down rate, plus where the downs bunch up.

    The rate alone is close to useless: `ChatFeedback` only records what someone
    happened to vote on, so its absolute level says more about who was clicking
    than about answer quality. What is informative is *clustering* — five downs
    in one session, or one day's votes all carrying `reason='wrong_data'` — which
    points at a specific broken thing rather than a mood.
    """
    statement = (
        select(ChatFeedback)
        .where(ChatFeedback.created_at >= window_start)
        .where(ChatFeedback.created_at <= window_end)
    )
    if tenant_id is not None:
        statement = statement.where(ChatFeedback.tenant_id == tenant_id)
    votes = list(session.exec(statement).all())

    downs = [vote for vote in votes if (vote.vote or "").lower() == "down"]
    value = _rate(len(downs), len(votes))

    by_day: dict[str, int] = {}
    by_session: dict[str, int] = {}
    by_reason: dict[str, int] = {}
    by_tenant: dict[str, int] = {}
    for vote in downs:
        by_day[vote.created_at.date().isoformat()] = (
            by_day.get(vote.created_at.date().isoformat(), 0) + 1
        )
        by_session[str(vote.session_id)] = by_session.get(str(vote.session_id), 0) + 1
        by_reason[vote.reason or "unspecified"] = by_reason.get(vote.reason or "unspecified", 0) + 1
        by_tenant[str(vote.tenant_id)] = by_tenant.get(str(vote.tenant_id), 0) + 1

    clusters = [
        {"dimension": dimension, "key": key, "down_votes": count}
        for dimension, bucket in (
            ("day", by_day),
            ("session", by_session),
            ("reason", by_reason),
            ("tenant", by_tenant),
        )
        for key, count in bucket.items()
        if count >= MIN_CLUSTER_SIZE
    ]
    clusters.sort(key=lambda item: -item["down_votes"])

    rate_breached = _breached(value, THUMBS_DOWN_ALERT_RATE, len(votes))
    return SignalResult(
        name="thumbs_down_clustering",
        value=value,
        numerator=len(downs),
        denominator=len(votes),
        confidence=CONFIDENCE_MEASURED,
        source="chat_feedback.vote / .reason / .session_id",
        threshold=THUMBS_DOWN_ALERT_RATE,
        # A cluster is worth surfacing even when the overall rate is calm, and
        # even below the sample floor — that is the entire point of clustering.
        breached=rate_breached or bool(clusters),
        caveat=(
            "ChatFeedback records only what a user chose to vote on, so the "
            "absolute rate reflects who clicked, not overall quality. The "
            "clusters are the signal; the rate is context for them."
        ),
        detail={
            "down_votes": len(downs),
            "up_votes": len(votes) - len(downs),
            "clusters": clusters[:10],
            "min_cluster_size": MIN_CLUSTER_SIZE,
            "by_reason": dict(sorted(by_reason.items(), key=lambda item: -item[1])),
            "rate_alert_breached": rate_breached,
        },
    )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def compute_online_signals(
    session: Session,
    *,
    window_days: int = DEFAULT_WINDOW_DAYS,
    tenant_id: Optional[UUID] = None,
    now: Optional[datetime] = None,
    slow_turn_threshold_seconds: float = SLOW_TURN_THRESHOLD_SECONDS,
) -> OnlineEvalSignals:
    """All five signals over one window.

    `now` is injectable so a caller (or a test) can compute a historical window
    without monkeypatching the clock. `tenant_id=None` computes across all
    tenants, which is the right default for a platform-health view and the wrong
    one for anything shown to a customer.
    """
    window_end = now or datetime.utcnow()
    window_start = window_end - timedelta(days=window_days)
    common = {
        "window_start": window_start,
        "window_end": window_end,
        "tenant_id": tenant_id,
    }

    signals = [
        budget_exhaustion_rate(session, **common),
        clarification_rate(session, **common),
        zero_result_rate(session, **common),
        slow_turn_rate(session, threshold_seconds=slow_turn_threshold_seconds, **common),
        thumbs_down_clustering(session, **common),
    ]
    return OnlineEvalSignals(
        window_start=window_start,
        window_end=window_end,
        tenant_id=str(tenant_id) if tenant_id else None,
        signals=signals,
    )


def emit_online_signals(
    signals: OnlineEvalSignals, *, window_days: Optional[float] = None
) -> int:
    """Mirror a computed window onto Application Insights, one event per signal.

    Added 2026-08-21 so the workbook's online-signals panel has a data source at
    all. Everything in this module is computed in SQL over Postgres, and an Azure
    Monitor workbook cannot query Postgres — its data sources are Logs, Azure
    Resource Graph, ARM and ADX. Same mirror pattern, and the same reason, as
    `telemetry.track_eval_result()` mirroring an `agent_eval_run` row.

    Postgres stays the durable record. This is fire-and-forget: it never raises,
    and a telemetry outage must not lose a computed window.

    **This function has a caller (Gap 305).** It is
    `scripts/emit_online_signals_job.py::main()`, whose default window is six
    hours. That job emits after its own `configure_telemetry()`, because these
    events reach `customEvents` only once the Azure Monitor exporter is attached
    to the `invoice_be_telemetry` logger. Before that wiring this function had
    zero callers and the panel rendered empty forever, which reads as "nothing is
    wrong" while actually meaning "nothing has run".

    The caller was originally written inside Feature 24's ops-digest job on
    2026-08-24; that feature was superseded and deleted on 2026-08-25 (Gap 311)
    and the caller was extracted into the standalone script above. It still has
    no `Microsoft.App/jobs` resource, so nothing runs it on a schedule in Azure
    yet — which is why Gap 305 remains `[~]`.

    `window_days` is a float and is expected to be fractional here: a six-hour
    window is 0.25 days.

    Returns the number of signals emitted, so a caller/test can assert it did
    something.
    """
    from telemetry import track_online_signal  # noqa: PLC0415 - keeps this module import-light

    emitted = 0
    for signal in signals.signals:
        track_online_signal(
            signal.name,
            value=signal.value,
            numerator=signal.numerator,
            denominator=signal.denominator,
            confidence=signal.confidence,
            threshold=signal.threshold,
            breached=signal.breached,
            window_days=window_days,
            tenant_id=signals.tenant_id or "",
            # The two sub-shapes that are the actual point of their signals and
            # would be lost if only the headline rate were emitted.
            false_confident_zero_turns=signal.detail.get("false_confident_zero_turns"),
            cluster_count=len(signal.detail.get("clusters") or []) or None,
            p50_seconds=signal.detail.get("p50_seconds"),
            p95_seconds=signal.detail.get("p95_seconds"),
        )
        emitted += 1
    return emitted


__all__ = [
    "CONFIDENCE_HEURISTIC",
    "CONFIDENCE_MEASURED",
    "CONFIDENCE_OFFLINE_ONLY",
    "CONFIDENCE_PROXY",
    "MIN_CLUSTER_SIZE",
    "MIN_SAMPLE_FOR_ALERT",
    "NO_RECORDS_FOUND",
    "OnlineEvalSignals",
    "SLOW_TURN_THRESHOLD_SECONDS",
    "SignalResult",
    "budget_exhaustion_rate",
    "clarification_rate",
    "compute_online_signals",
    "emit_online_signals",
    "looks_like_clarification",
    "slow_turn_rate",
    "thumbs_down_clustering",
    "zero_result_rate",
]
