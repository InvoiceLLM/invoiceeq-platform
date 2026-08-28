"""Gap 324 (BE): online, live-traffic turn-sequence drift detection.

Gap 303 built turn-sequence *reconstruction* (where a turn sits in its
session — `agents/query_agent.py::_session_turn_position()`) and split
*drift detection* out. Gap 307 built the offline half of drift detection
(`services/agent_eval.py::score_context_drift()`, scored against a golden
multi-turn script's pinned expectations). This module is the online half —
scoring real production turns, where there is no golden script and no pinned
expectation to check against. That absence is a real, unsolved hard problem
for a judge-based check; this module deliberately does not attempt one.

Instead it is a small, deterministic, explainable heuristic over the two
concrete failure shapes the gap names:

  * "dropped_filter" (Gap 237-shaped): the previous turn's SQL carried a
    numeric filter (e.g. `grand_total > 20000`), the current question reads
    as a pronoun-referencing follow-up ("which of those", "the oldest"), and
    the current turn's SQL no longer carries that filter at all.
  * "stale_entity" (Gap 276-shaped): the previous turn's SQL named a specific
    entity (a quoted string literal, e.g. `vendor_name = 'Acme Corp'`), the
    current question names what looks like a different proper noun, and the
    current turn's SQL still carries the OLD entity unchanged.

Both are approximate on purpose — regex over SQL text and question text, no
LLM call, no new scheduled job. That is what lets this ride the request path
that already emits the live `chat_turn` telemetry event (deployed, live,
flowing into Application Insights today) instead of inheriting Gap 305's
"coded but never deployed" trap. A flag here is a candidate for a human to
look at on the AI Control Tower workbook, never a blocking or corrective
action on the turn itself.
"""
from __future__ import annotations

import re
from typing import Optional

DROPPED_FILTER = "dropped_filter"
STALE_ENTITY = "stale_entity"

# Small, explicit, case-insensitive. A real NL follow-up detector would need
# far more than this; this is deliberately just enough to gate the
# dropped_filter heuristic away from a genuinely fresh question (which
# legitimately carries no prior filter forward).
_FOLLOWUP_PHRASES = (
    "those", "them", "that one", "it", "the oldest", "the newest",
    "the latest", "the highest", "the lowest", "the biggest", "the smallest",
    "which of", "same ", "again",
)

_NUMERIC_FILTER_RE = re.compile(r"(>=|<=|>|<|=)\s*(\d+(?:\.\d+)?)")
_QUOTED_LITERAL_RE = re.compile(r"'([^']+)'")
# A run of 2+ capitalized words -- a rough proper-noun stand-in (vendor/
# customer names in this corpus are almost always Title Case multi-word).
_PROPER_NOUN_RE = re.compile(r"\b[A-Z][a-zA-Z]*(?:\s+[A-Z][a-zA-Z]*)+\b")


def _numeric_filters(sql: str) -> set[tuple[str, str]]:
    return set(_NUMERIC_FILTER_RE.findall(sql or ""))


def _quoted_literals(sql: str) -> set[str]:
    return {v.strip() for v in _QUOTED_LITERAL_RE.findall(sql or "") if v.strip()}


def _reads_as_followup(question: str) -> bool:
    q = (question or "").lower()
    return any(phrase in q for phrase in _FOLLOWUP_PHRASES)


def detect_turn_drift(
    *,
    prev_sql: Optional[str],
    curr_sql: Optional[str],
    curr_question: str,
) -> list[str]:
    """Returns the drift flags found on this turn, `[]` if none.

    `prev_sql` is the previous turn's `generated_sql` in the same session
    (`ChatMessage.generated_sql` on the last assistant row), `curr_sql` this
    turn's own. Either being empty (no prior SQL turn, or this turn took the
    RAG route) short-circuits to no flags -- there is nothing to compare.
    """
    prev_sql = prev_sql or ""
    curr_sql = curr_sql or ""
    if not prev_sql or not curr_sql:
        return []

    flags: list[str] = []

    dropped = _numeric_filters(prev_sql) - _numeric_filters(curr_sql)
    if dropped and _reads_as_followup(curr_question):
        flags.append(DROPPED_FILTER)

    carried_over = _quoted_literals(prev_sql) & _quoted_literals(curr_sql)
    if carried_over:
        mentioned = _PROPER_NOUN_RE.findall(curr_question or "")
        new_entity_named = any(
            not any(m.lower() in literal.lower() or literal.lower() in m.lower() for literal in carried_over)
            for m in mentioned
        )
        if new_entity_named:
            flags.append(STALE_ENTITY)

    return flags
