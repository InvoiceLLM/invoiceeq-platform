"""Score a real production chat turn with the golden bank's own judge.

Feature 23 / **Gap 304 half (2)**. Until this module existed, `agent_eval_run`
was written from exactly one place — `scripts/run_agent_eval.py`, against the
fixed golden bank — so production traffic had no quality measurement of any
kind. Every quality tile in the AI Control Tower was single-sourced, and the one
comparison the design exists to make ("is live quality drifting away from the
bank?") could not be made from either side.

What this does
--------------
One completed turn in, one `agent_eval_run` row out, tagged
`run_source=production`, plus the matching `agent_eval_run` telemetry event. The
judge is *not* a new one: it is `services/agent_eval.py`'s
`score_soft_metrics_combined()` — the same reference-free five-metric judge the
golden bank uses — plus `score_persona()` and the deterministic
`score_orchestration()`. Nothing here re-implements a rubric.

Reference-free is what makes this possible at all. `faithfulness`, `relevance`,
`helpfulness`, `tone`, `completeness`, `persona` and `orchestration` all grade an
answer against the evidence the turn actually retrieved. `accuracy_score` and
`context_score` grade it against a *reference* — an expected answer and a known-
correct invoice set — which real traffic does not have and never will. They stay
NULL on every production row. That is the correct outcome, not a missing
feature: recording 0.0 there would read as "scored, and terrible" in the same
trend chart the golden bank plots.

`pass` on a production row
--------------------------
Decided by the same `decide_pass()` the bank uses, which only grades the
dimensions that produced a number — so in practice a production row's pass is
**faithfulness + relevance**, where a golden row's is faithfulness + relevance +
accuracy. Two consequences, both deliberate:

  * The two pass rates are not comparable and must never be averaged together.
    `models.AgentEvalRun.passed` says so at the column, and
    `services/online_eval_signals.py` filters `run_source` for the same reason so
    the online signals cannot blend them by accident.
  * If neither faithfulness nor relevance produced a number — an unreachable
    judge, an empty answer — **no row is written at all**. `decide_pass()`
    returns False for "nothing could be graded", which is right for a nightly
    harness (going green when the judge breaks is worse) but wrong here: a judge
    outage across live traffic would render as a production quality collapse.
    Writing nothing makes an outage show up as missing volume instead, which is
    what it is.

What is deliberately NOT stored
-------------------------------
The customer's question and the assistant's answer. `question`/`actual_answer`
are NULL on production rows and `message_id` points at the `chatmessage` row
that already holds both. Same rule applies to `notes`: the judge's own note text
quotes claims lifted out of the answer ("unsupported: <claim>"), so it is
dropped and replaced with a structural summary. A score row is not a second copy
of a customer's data.

`llm_call_count` is 0 on production rows and means "not counted", not "zero
calls" — counting a turn's model round-trips needs the eval harness's
`_counting_llm_calls()` patch, which is not something to install in a request
path. Production cost and per-call latency already come from `llm_agent_call`
events (Feature 23 Phase 1); `latency_ms` here is the turn's wall clock as
measured by the caller.

Cost, stated plainly
--------------------
Two extra billable model calls per judged turn (the combined soft judge, and
persona). `settings.ENABLE_PRODUCTION_QUALITY_JUDGE` is the switch, default off.
Both judge calls go through `tracked_llm_call()` under the names
`eval.combined_soft` and `eval.persona`, so they land in `customEvents` with
`run_source=production` alongside the traffic they are grading — any production
cost rollup that does not filter `agent_name !startswith "eval."` will attribute
judge cost to the product. This is the same caveat Gap 304 half (1) already
documented for golden runs.

Failure contract
----------------
Never raises. The turn this scores has already been committed and already
returned to the user before anything here runs; a judge failure, a DB failure or
a telemetry failure must be invisible to it. Same `except Exception` swallow as
every other telemetry path in this codebase.
"""

from __future__ import annotations

import logging
from typing import Any, Optional
from uuid import UUID

import telemetry
from services.agent_eval import (
    EvalScores,
    decide_pass,
    score_orchestration,
    score_persona,
    score_soft_metrics_combined,
)

logger = logging.getLogger(__name__)

__all__ = ["judge_turn", "submit_turn_judgement", "PRODUCTION_AGENT_NAME"]

#: Same name the golden bank records for a whole default-path turn
#: (`scripts/run_agent_eval.py::AGENT_DEFAULT_PATH`), so live and bank rows for
#: the same agent line up on one name and differ only in `run_source` — which is
#: the entire point of Gap 304. Duplicated rather than imported: `services/`
#: importing from `scripts/` would put the eval CLI's argparse and Azure
#: dependencies into the request path's import graph.
PRODUCTION_AGENT_NAME = "chat.default_path"

#: Blocks `run_query_agent()` appends to the model's own prose after it has
#: finished writing. Stripped before judging for the same reason the golden
#: harness strips them (`scripts/run_agent_eval.py::_split_appended_blocks`): the
#: results table and the citation links are code output, and grading the model on
#: text it did not write measures the formatter.
_RESULTS_TABLE_MARKER = "\n\n### Query Results\n\n"
_CITATIONS_MARKER = "\n\n**Citations:**\n"


def _answer_prose(content: str) -> str:
    prose = content or ""
    for marker in (_RESULTS_TABLE_MARKER, _CITATIONS_MARKER):
        if marker in prose:
            prose = prose.split(marker, 1)[0]
    return prose.strip()


def _open_session():
    """A session of this module's own — the caller's is committed and gone.

    This runs on a background thread after the request (or queue job) has
    finished with its session, so reusing it would be a use-after-close at best
    and a cross-thread session at worst.
    """
    from sqlmodel import Session  # noqa: PLC0415

    from database import engine  # noqa: PLC0415

    return Session(engine)


def submit_turn_judgement(**payload: Any) -> None:
    """Fire-and-forget `judge_turn()` on the chat background pool.

    The flag check lives here rather than inside `judge_turn()` so that with the
    flag off nothing is submitted, nothing is imported, and no thread is touched
    — the turn pays literally nothing.

    `routers/chat.py::_chat_background_pool` is reused rather than given a
    sibling: it is already the pool this application runs post-response chat work
    on, and a second executor would double the thread budget for the same class
    of work. The known trade-off, stated rather than discovered later: judging
    occupies one of those eight workers for the duration of two model calls, so
    with the queue path also enabled a burst of traffic can leave queued chat
    jobs waiting behind judge calls. The flag is the mitigation.

    Imported lazily, inside the function, because `routers/chat.py` imports this
    module — at module scope this would be a cycle.

    `payload` is forwarded verbatim, so the `trace_id`/`request_id` both call
    sites now pass reach `judge_turn()` and get bound onto the pool thread there
    (Gap 302/304 attribution fix). Nothing is read out of the submitting
    thread's contextvars *here* — by the time the pool runs the callable, this
    frame is long gone.
    """
    try:
        from config import get_settings  # noqa: PLC0415

        if not get_settings().ENABLE_PRODUCTION_QUALITY_JUDGE:
            return
        from routers.chat import _chat_background_pool  # noqa: PLC0415

        _chat_background_pool.submit(judge_turn, **payload)
    except Exception:  # pragma: no cover - a scoring hook must never break a turn
        logger.debug("Could not submit production quality judging", exc_info=True)


def judge_turn(
    *,
    question: str,
    answer: str,
    evidence: Optional[dict] = None,
    tenant_id: Any,
    message_id: Any,
    generated_sql: Optional[str] = None,
    latency_ms: float = 0.0,
    agent_name: str = PRODUCTION_AGENT_NAME,
    trace_id: Optional[str] = None,
    request_id: Optional[str] = None,
    llm: Any = None,
    session_factory: Any = None,
) -> None:
    """Score one completed production turn. Never raises, never returns a value.

    `evidence` is `run_query_agent()`'s `judge_evidence` payload — the turn's own
    tool output (`context`) and the SQL it ran (`executed_queries`). A turn with
    no evidence payload at all is **not judged**: that is a cache hit, the SAGE
    path, or the router's error fallback, none of which is a freshly generated
    answer with retrievable evidence. Judging them would grade real claims
    against an empty context, which `score_soft_metrics_combined()` correctly
    treats as a hard 0.00 faithfulness — a harness defect, not a model result.

    `trace_id`/`request_id` are the originating turn's correlation IDs, bound
    onto *this* thread's contextvars for the duration (Gap 302/304 attribution
    fix, 2026-08-24). Without them the two judge calls this makes —
    `eval.combined_soft` and `eval.persona`, both through `tracked_llm_call()` —
    emitted `llm_agent_call` events with `trace_id=""`, `tenant_id=""` and
    `request_id=""` on every production turn, because
    `ThreadPoolExecutor.submit()` copies no context and this always runs on
    `routers/chat.py::_chat_background_pool`. The scores were therefore
    unjoinable to the turn that produced them, which is the one thing this
    module exists to make possible. `tenant_id` is bound from the argument it
    already took.

    `session_factory` and `llm` exist for tests; production passes neither.
    """
    from utils.logging_config import correlation_context  # noqa: PLC0415

    with correlation_context(
        tenant_id=str(tenant_id or ""), trace_id=trace_id, request_id=request_id
    ):
        _judge_turn(
            question=question,
            answer=answer,
            evidence=evidence,
            tenant_id=tenant_id,
            message_id=message_id,
            generated_sql=generated_sql,
            latency_ms=latency_ms,
            agent_name=agent_name,
            llm=llm,
            session_factory=session_factory,
        )


def _judge_turn(
    *,
    question: str,
    answer: str,
    evidence: Optional[dict] = None,
    tenant_id: Any,
    message_id: Any,
    generated_sql: Optional[str] = None,
    latency_ms: float = 0.0,
    agent_name: str = PRODUCTION_AGENT_NAME,
    llm: Any = None,
    session_factory: Any = None,
) -> None:
    """The scoring itself. See `judge_turn()` for the correlation binding."""
    try:
        if evidence is None:
            return
        prose = _answer_prose(answer)
        if not prose:
            return

        context = str(evidence.get("context") or "")
        executed_queries = str(evidence.get("executed_queries") or "")
        route = str(evidence.get("route") or "")

        if llm is None:
            from utils.llm import get_llm  # noqa: PLC0415

            llm = get_llm()

        soft, _claims, _notes, _calls = score_soft_metrics_combined(
            question, prose, context, llm, executed_queries
        )
        persona, _persona_notes, _persona_calls = score_persona(question, prose, None, llm)
        orchestration, _orchestration_notes = score_orchestration(prose, context, executed_queries)

        scores = EvalScores(
            judge_mode="combined",
            faithfulness_score=soft.get("faithfulness"),
            relevance_score=soft.get("relevance"),
            # accuracy_score/context_score stay None: both need a reference the
            # live turn does not have. See the module docstring.
            orchestration_score=orchestration,
            persona_score=persona,
            helpfulness_score=soft.get("helpfulness"),
            completeness_score=soft.get("completeness"),
            tone_score=soft.get("tone"),
        )
        if scores.faithfulness_score is None and scores.relevance_score is None:
            # Nothing gradeable came back. Writing a row here would record a
            # judge outage as a quality collapse -- see the module docstring.
            logger.debug("Online judge produced no gradeable score for message %s", message_id)
            return
        passed = decide_pass(scores)

        _persist(
            agent_name=agent_name,
            message_id=message_id,
            tenant_id=tenant_id,
            scores=scores,
            passed=passed,
            route=route,
            generated_sql=generated_sql,
            latency_ms=latency_ms,
            session_factory=session_factory,
        )
    except Exception:  # pragma: no cover - defended by test_a_judge_failure_is_swallowed
        logger.debug("Online quality judging failed for message %s", message_id, exc_info=True)


def _notes(route: str, generated_sql: Optional[str], message_id: Any) -> str:
    """A structural summary, with no customer text in it.

    The judge's own `note_text()` is deliberately discarded: it quotes claims
    extracted from the answer, which is exactly the text this row exists not to
    duplicate. What is left is what a human reading one row needs to know about
    how it was produced.
    """
    return "; ".join(
        part
        for part in (
            "run_source=production",
            f"message_id={message_id}",
            f"route={route}" if route else None,
            f"sql={'yes' if generated_sql else 'no'}",
            "judge_mode=combined",
            "pass_basis=faithfulness+relevance (accuracy needs a reference answer)",
            "llm_call_count=0 means not counted on production rows",
        )
        if part
    )


def _coerce_uuid(value: Any) -> Optional[UUID]:
    if value is None:
        return None
    if isinstance(value, UUID):
        return value
    try:
        return UUID(str(value))
    except (ValueError, AttributeError, TypeError):
        return None


def _persist(
    *,
    agent_name: str,
    message_id: Any,
    tenant_id: Any,
    scores: EvalScores,
    passed: bool,
    route: str,
    generated_sql: Optional[str],
    latency_ms: float,
    session_factory: Any,
) -> None:
    """Write the row, then mirror it as telemetry.

    In that order and in separate `try` blocks on purpose: the row is the durable
    record the ops digest reads, and losing the event when the DB is fine (or the
    row when Application Insights is unreachable) is better than losing both.
    """
    from models import AgentEvalRun  # noqa: PLC0415

    message_uuid = _coerce_uuid(message_id)
    tenant_uuid = _coerce_uuid(tenant_id)
    if message_uuid is None or tenant_uuid is None:
        # Without a message id there is nothing to point at, and the row would
        # violate `ck_agent_eval_run_text_or_message` (it carries no text either).
        logger.debug("Online judge skipped: unusable message_id/tenant_id")
        return

    factory = session_factory or _open_session
    try:
        with factory() as session:
            session.add(
                AgentEvalRun(
                    agent_name=agent_name,
                    run_source=telemetry.RUN_SOURCE_PRODUCTION,
                    message_id=message_uuid,
                    # No question, no actual_answer. The whole point.
                    question=None,
                    expected_answer=None,
                    actual_answer=None,
                    passed=passed,
                    faithfulness_score=scores.faithfulness_score,
                    relevance_score=scores.relevance_score,
                    accuracy_score=None,
                    context_score=None,
                    orchestration_score=scores.orchestration_score,
                    persona_score=scores.persona_score,
                    latency_ms=float(latency_ms or 0.0),
                    llm_call_count=0,
                    tenant_id=tenant_uuid,
                    notes=_notes(route, generated_sql, message_uuid)[:4000],
                )
            )
            session.commit()
    except Exception:
        logger.debug("Online judge could not persist a row for %s", message_uuid, exc_info=True)

    # `case_id` is the message id: the event needs a stable per-turn identifier
    # and this is the only one that is not customer text.
    telemetry.track_eval_result(
        agent_name,
        str(message_uuid),
        passed,
        faithfulness_score=scores.faithfulness_score,
        relevance_score=scores.relevance_score,
        orchestration_score=scores.orchestration_score,
        persona_score=scores.persona_score,
        latency_ms=float(latency_ms or 0.0),
        llm_call_count=0,
        tenant_id=str(tenant_uuid),
        run_source=telemetry.RUN_SOURCE_PRODUCTION,
        # The three soft metrics with no column, same as the golden path: they
        # ride `**extra_attributes` so the workbook can chart them without a
        # migration, and None values are dropped by the emitter.
        helpfulness_score=scores.helpfulness_score,
        completeness_score=scores.completeness_score,
        tone_score=scores.tone_score,
        judge_mode="combined",
        route=route,
        message_id=str(message_uuid),
    )
