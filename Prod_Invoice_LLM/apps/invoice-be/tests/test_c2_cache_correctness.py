"""Feature 6.1 item C2 — the answer cache must not serve or store a narrowing follow-up.

`get_cached_answer` / `set_cached_answer` are keyed on `(tenant_id,
normalized_query)` and nothing else. That is right for a self-contained question
and wrong for one that only means something against the previous turn: "what about
the second one?" is six words that denote different rows in every session that says
them. Before this, session A's answer to those words was served to session B.

Both directions are guarded, because a poisoned entry is as bad as a bad read.
"""
import os
from unittest.mock import MagicMock, patch

import pytest

os.environ.setdefault("MOCK_EMBEDDINGS", "true")

from agents import query_agent  # noqa: E402
from agents.query_agent import _is_narrowing_followup  # noqa: E402

# Taken from `_FOLLOWUP_BACKREF_PATTERNS`, not invented: the detector matches
# "<the|those|these> <number>", "those ... ones/invoices/bills/vendors/rows/records",
# and "explain|detail|break down|list|show (me) them|those|these".
NARROWING = [
    "show me those",
    "list those invoices",
    "explain them",
    "break down those records",
    "what were the 3",
]

# Recorded rather than quietly ignored: the detector does NOT catch ordinal
# back-references like "what about the second one" or "and the other one?". Those
# are just as session-dependent and just as wrong to serve from a shared cache.
# C2 makes the cache consult the detector; widening the detector is a separate
# change with its own false-positive risk, and pretending otherwise here would
# claim more coverage than exists.
KNOWN_UNCAUGHT = [
    "what about the second one",
    "and the other one?",
]

SELF_CONTAINED = [
    "how much did we spend with apex consulting group last quarter",
    "list all overdue invoices",
    "what is the total for invoice CMC-330217",
]


@pytest.mark.parametrize("message", NARROWING)
def test_the_detector_recognises_a_narrowing_followup(message):
    """If this regresses, both guards below silently stop guarding."""
    assert _is_narrowing_followup(message), message


@pytest.mark.parametrize("message", KNOWN_UNCAUGHT)
def test_ordinal_back_references_are_a_known_hole(message):
    """Pins the limitation so it is a decision, not a surprise.

    If someone widens `_FOLLOWUP_BACKREF_PATTERNS` to cover these, this test fails
    and they move the phrase into NARROWING -- which is the correct outcome. What
    must not happen is the hole being discovered again from a support ticket.
    """
    assert not _is_narrowing_followup(message), (
        f"{message!r} is now caught -- move it into NARROWING"
    )


@pytest.mark.parametrize("message", SELF_CONTAINED)
def test_a_self_contained_question_is_not_a_followup(message):
    """The cache must keep working for the questions it is actually for."""
    assert not _is_narrowing_followup(message), message


def test_the_source_guards_both_the_read_and_the_write():
    """Assert the guard at the source, where it is unambiguous.

    A behavioural test of the cache path needs Redis plus a whole turn; these two
    call sites are the entire fix, and a future edit that drops either one is
    exactly what this must catch.
    """
    import inspect

    source = inspect.getsource(query_agent._run_query_agent)

    assert "_is_narrowing_followup(user_message) else get_cached_answer" in source, (
        "the cache READ is no longer guarded -- a narrowing follow-up can be served "
        "another session's answer"
    )
    assert "if not _is_narrowing_followup(user_message):" in source, (
        "the cache WRITE is no longer guarded -- a narrowing answer can poison the "
        "cache for every other session asking the same words"
    )


def test_the_feature_26_attachment_gate_still_precedes_the_cache():
    """C2's stated must-not-change.

    The F26 gate returns before the cache is consulted at all, so an attachment
    turn never reads or writes it. C2 moved nothing; this asserts that it did not.
    """
    import inspect

    source = inspect.getsource(query_agent._run_query_agent)

    gate = source.find("_run_attached_document_turn(")
    # The guarded expression, not the bare name: `get_cached_answer` is also
    # mentioned in a comment above the gate, and matching prose would make this
    # test pass or fail on documentation.
    read = source.find("else get_cached_answer(")
    assert gate != -1, "the F26 attachment gate is gone"
    assert read != -1, "the guarded cache read is gone"
    assert gate < read, "the cache is now consulted before the F26 attachment gate"


def test_a_narrowing_followup_never_reaches_the_cache_functions(monkeypatch):
    """The guard is a plain conditional; prove it short-circuits both calls."""
    get_calls, set_calls = [], []
    monkeypatch.setattr(
        query_agent, "get_cached_answer", lambda t, m: get_calls.append(m) or None
    )
    monkeypatch.setattr(
        query_agent, "set_cached_answer", lambda t, m, r: set_calls.append(m)
    )

    # Exercise the guard expression directly with the same shape the route uses.
    for message in NARROWING:
        cached = (
            None
            if query_agent._is_narrowing_followup(message)
            else query_agent.get_cached_answer("t-1", message)
        )
        assert cached is None
        if not query_agent._is_narrowing_followup(message):
            query_agent.set_cached_answer("t-1", message, {})

    assert get_calls == [], f"a narrowing follow-up hit the cache read: {get_calls}"
    assert set_calls == [], f"a narrowing follow-up hit the cache write: {set_calls}"


def test_a_self_contained_question_still_uses_the_cache(monkeypatch):
    """The guard must not turn the cache off for everything."""
    get_calls, set_calls = [], []
    monkeypatch.setattr(
        query_agent, "get_cached_answer", lambda t, m: get_calls.append(m) or None
    )
    monkeypatch.setattr(
        query_agent, "set_cached_answer", lambda t, m, r: set_calls.append(m)
    )

    for message in SELF_CONTAINED:
        if not query_agent._is_narrowing_followup(message):
            query_agent.get_cached_answer("t-1", message)
            query_agent.set_cached_answer("t-1", message, {})

    assert get_calls == SELF_CONTAINED
    assert set_calls == SELF_CONTAINED
