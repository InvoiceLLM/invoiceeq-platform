"""Feature 6.1 item A4 — the SQL system prompt has a cacheable static prefix.

Azure OpenAI prompt caching serves the longest prefix that is byte-identical to an
earlier request, if it is at least 1,024 tokens, in 128-token steps. Before A4 the
identical prefix ended at rule 1, where the tenant id was interpolated inline —
1,809 of 6,694 tokens (o200k_base, measured 2026-09-03). Every tenant shared 27%
of the prompt and paid full price for the rest.

These tests pin the two properties the cache needs, deterministically, so the
boundary cannot drift back: the text above `SQL_PROMPT_TENANT_SECTION_MARKER` is
identical across tenants and questions, and it is long enough to be cached.

What they do NOT prove: that Azure actually serves it from cache. That is
`cached_tokens` on the `chat.sql_generation` event rising on a tenant's second
turn — the B1 field — and it is recorded in `docs/test_evidence/` once real turns
exist. This file is the deterministic half; the measured half needs traffic.
"""
import os
import re

import pytest
import tiktoken
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

os.environ.setdefault("MOCK_EMBEDDINGS", "true")

from agents import query_agent  # noqa: E402
from agents.query_agent import (  # noqa: E402
    SQL_PROMPT_TENANT_SECTION_MARKER,
    _INJECTION_GUARD_INSTRUCTION,
    build_sql_system_prompt,
)

# The encoding the gpt-5 family reports token counts in.
_ENC = tiktoken.get_encoding("o200k_base")

# Azure's documented minimum for a cache hit.
AZURE_CACHE_MIN_TOKENS = 1024

# The cross-tenant shared prefix before A4, measured 2026-09-03. A4 must beat
# it by a wide margin or it changed nothing worth shipping.
PRE_A4_SHARED_PREFIX_TOKENS = 1809

T1 = "11111111-1111-1111-1111-111111111111"
T2 = "22222222-2222-2222-2222-222222222222"
Q_PLAIN = "how much did we spend with apex consulting group last quarter"
Q_ATTRIBUTE = "what is the discount amount on invoice INV-42"   # triggers the Gap 413 block
Q_TAX = "whats the CGST we paid to Rajesh Steel"               # triggers the tax block
Q_PAYMENT = "has the Titan Steel invoice been paid"             # triggers the payment block


@pytest.fixture(scope="module")
def db():
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    SQLModel.metadata.create_all(engine)
    with Session(engine) as s:
        yield s


def _render(db, question, tenant, **kw):
    return build_sql_system_prompt(question, tenant, db, **kw)


def _split(prompt: str):
    assert prompt.count(SQL_PROMPT_TENANT_SECTION_MARKER) == 1, "marker must appear exactly once"
    head, tail = prompt.split(SQL_PROMPT_TENANT_SECTION_MARKER, 1)
    return head, tail


def _tokens(text: str) -> int:
    return len(_ENC.encode(text))


# ---------------------------------------------------------------------------
# Property 1: the prefix is identical across everything a request can vary.
# ---------------------------------------------------------------------------


def test_prefix_is_byte_identical_across_tenants(db):
    a, _ = _split(_render(db, Q_PLAIN, T1, tenant_stats="Tenant has 8 invoices."))
    b, _ = _split(_render(db, Q_PLAIN, T2, tenant_stats="Tenant has 3 invoices."))
    assert a == b


def test_prefix_is_byte_identical_across_questions(db):
    """The three per-question blocks used to sit between rule 6c and rule 7."""
    plain, _ = _split(_render(db, Q_PLAIN, T1))
    for q in (Q_ATTRIBUTE, Q_TAX, Q_PAYMENT):
        other, tail = _split(_render(db, q, T1))
        assert other == plain, f"prefix differs for {q!r}"
        # And the triggered block really did land somewhere -- in the tail.
        assert len(tail) > len(_split(_render(db, Q_PLAIN, T1))[1]), (
            f"the block for {q!r} was not rendered at all"
        )


def test_prefix_is_byte_identical_across_turn_state(db):
    """Prior SQL, trainer rules, chat rules and history are all per-turn."""
    base, _ = _split(_render(db, Q_PLAIN, T1))
    loaded, _ = _split(
        _render(
            db, Q_PLAIN, T1,
            chat_history="User: hi\nAssistant: hello",
            prior_turn_sql=f"SELECT 1 FROM invoice WHERE tenant_id = '{T1}'",
            rules_block="TRAINER RULE: prefer net amounts.",
            chat_rules_block="CHAT RULE: be brief.",
            tenant_stats="Tenant has 8 invoices.",
        )
    )
    assert base == loaded


# ---------------------------------------------------------------------------
# Property 2: the prefix is long enough to be cached, and much longer than before.
# ---------------------------------------------------------------------------


def test_prefix_clears_the_azure_cache_minimum(db):
    head, _ = _split(_render(db, Q_PLAIN, T1))
    n = _tokens(head)
    assert n >= AZURE_CACHE_MIN_TOKENS, f"prefix is {n} tokens, below Azure's {AZURE_CACHE_MIN_TOKENS}"


def test_prefix_is_far_larger_than_before_a4(db):
    """If this ever drops back toward 1,809, someone moved a per-request value
    above the marker and the cache is buying 27% of the prompt again."""
    head, tail = _split(_render(db, Q_PLAIN, T1))
    n_head, n_tail = _tokens(head), _tokens(tail)
    assert n_head >= 2 * PRE_A4_SHARED_PREFIX_TOKENS, (
        f"static prefix is only {n_head} tokens; before A4 it was {PRE_A4_SHARED_PREFIX_TOKENS}"
    )
    # Record the split in the assertion message so a future failure states the numbers.
    assert n_head > n_tail, f"prefix {n_head} tokens should dominate the tail {n_tail} tokens"


# ---------------------------------------------------------------------------
# Property 3: nothing per-request leaked into the prefix, nothing static fell out.
# ---------------------------------------------------------------------------


def test_no_tenant_literal_above_the_marker(db):
    head, tail = _split(_render(db, Q_PLAIN, T1, tenant_stats="Tenant has 8 invoices."))
    assert T1 not in head, "the tenant id leaked into the static prefix"
    assert "Tenant has 8 invoices." not in head
    # And it IS below, twice: the restated rule-1 predicate, and rule 6d's example.
    assert tail.count(f"tenant_id = '{T1}'") >= 2


def test_rules_1_to_11_all_present_exactly_once_and_in_order(db):
    prompt = _render(db, Q_PLAIN, T1)
    numbers = ["1.", "2.", "3.", "4.", "4a.", "5.", "6.", "6a.", "6b.", "6c.", "6d.", "7.", "8.", "8a.", "9.", "10.", "11."]
    positions = []
    for n in numbers:
        hits = [m.start() for m in re.finditer(r"(?m)^" + re.escape(n) + r" ", prompt)]
        assert len(hits) == 1, f"rule {n} appears {len(hits)} times"
        positions.append(hits[0])
    # Rule 6d deliberately moved to the tail (its example carries the tenant
    # literal); every other rule keeps its order.
    without_6d = [p for n, p in zip(numbers, positions) if n != "6d."]
    assert without_6d == sorted(without_6d), "rules 1-11 are out of order"
    assert positions[numbers.index("6d.")] > positions[numbers.index("11.")]


def test_rule_1_names_the_tenant_section_and_the_tail_restates_the_predicate(db):
    head, tail = _split(_render(db, Q_PLAIN, T1))
    assert "1. You MUST filter by tenant_id = '<TENANT_ID>'" in head
    assert "TENANT AND REQUEST CONTEXT section" in head
    assert f"TENANT_ID for this request (rule 1): tenant_id = '{T1}'" in tail


def test_static_blocks_are_in_the_prefix(db):
    head, _ = _split(_render(db, Q_PLAIN, T1))
    assert query_agent.CHAT_PERSONA_BLOCK in head
    assert query_agent._HAND_TYPED_SCHEMA_BLOCK in head
    assert _INJECTION_GUARD_INSTRUCTION in head
    assert "CRITICAL RULES:" in head


def test_rule_6d_still_renders_for_the_bound_dialect(db):
    """Moving 6d must not have dropped it or detached it from `_line_item_rule`."""
    _, tail = _split(_render(db, Q_PLAIN, T1))
    assert "6d. LINE-ITEM LEVEL EXTRACTION" in tail
    assert query_agent._line_item_rule(T1, db) in tail
