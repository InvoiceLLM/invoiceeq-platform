"""Feature 6.1 item C4, part 3 — retrieved few-shot examples from the curated set.

An example that resembles the question is worth more than a rule describing its
class. The curated set is embedded once per process, the question once per turn,
and the nearest examples are rendered in the request tail for the bound dialect.

Two things these tests hold the line on, because the design named them as the
risks: the examples come from the curated module ONLY (never a tenant's prior
turns — cross-tenant leakage by example), and a failure anywhere in retrieval
leaves the prompt exactly as it was before C4 rather than failing the turn.
"""
import os
from unittest.mock import patch

import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

os.environ.setdefault("MOCK_EMBEDDINGS", "true")

from agents import query_agent  # noqa: E402
from agents.query_agent import (  # noqa: E402
    SQL_PROMPT_TENANT_SECTION_MARKER,
    _retrieve_sql_examples,
    _sql_examples_block_for,
    build_sql_system_prompt,
)
from benchmarks.golden_sql_examples import GOLDEN_SQL_EXAMPLES  # noqa: E402

T = "11111111-1111-1111-1111-111111111111"


@pytest.fixture(autouse=True)
def fresh_cache():
    query_agent._sql_example_vectors_cache = None
    yield
    query_agent._sql_example_vectors_cache = None


def _one_hot_embedder(target_case_id: str):
    """Deterministic embeddings: the target example and the query share a vector;
    everything else is orthogonal. Mock-mode embeddings are random, so a test that
    used them would be asserting on chance."""
    ids = [e["case_id"] for e in GOLDEN_SQL_EXAMPLES]
    dim = len(ids) + 1

    def embed(texts):
        out = []
        for t in texts:
            v = [0.0] * dim
            match = next((i for i, e in enumerate(GOLDEN_SQL_EXAMPLES) if e["question"] == t), None)
            if match is not None:
                v[match] = 1.0
            else:
                # the query: identical to the target example's vector
                v[ids.index(target_case_id)] = 1.0
            out.append(v)
        return out

    return embed


@pytest.fixture(scope="module")
def db():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    with Session(engine) as s:
        yield s


def test_the_nearest_example_is_retrieved_first():
    with patch("chroma_client.get_embeddings", side_effect=_one_hot_embedder("bolts_reconciliation")):
        got = _retrieve_sql_examples("does the bolts line add up", "postgresql")
    assert got and got[0]["case_id"] == "bolts_reconciliation"
    # Orthogonal examples score 0, below the floor: only the true neighbour comes back.
    assert [g["case_id"] for g in got] == ["bolts_reconciliation"]


def test_the_bound_dialect_picks_the_matching_sql_shape():
    with patch("chroma_client.get_embeddings", side_effect=_one_hot_embedder("bolts_reconciliation")):
        pg = _retrieve_sql_examples("bolts line", "postgresql")[0]["sql"]
        lite = _retrieve_sql_examples("bolts line", "sqlite")[0]["sql"]
    assert "jsonb_array_elements" in pg and "json_each" not in pg
    assert "json_each" in lite and "jsonb_array_elements" not in lite


def test_the_block_never_carries_a_literal_tenant_id():
    with patch("chroma_client.get_embeddings", side_effect=_one_hot_embedder("rajesh_steel_cgst")):
        block = _sql_examples_block_for("cgst paid to rajesh", "postgresql")
    assert "<TENANT_ID>" in block
    assert "{tenant_id}" not in block


def test_nothing_above_the_floor_means_no_block():
    n = len(GOLDEN_SQL_EXAMPLES)

    def orthogonal(texts):
        # The curated set gets one unit axis each; the lone query gets an axis none
        # of them use, so every similarity is exactly 0 -- below the floor.
        if len(texts) == n:
            return [[1.0 if j == i else 0.0 for j in range(n + 1)] for i in range(n)]
        return [[1.0 if j == n else 0.0 for j in range(n + 1)] for _ in texts]

    with patch("chroma_client.get_embeddings", side_effect=orthogonal):
        assert _sql_examples_block_for("hello there", "postgresql") == ""


def test_an_embedding_failure_leaves_the_prompt_without_examples_not_dead():
    with patch("chroma_client.get_embeddings", side_effect=RuntimeError("model not loaded")):
        assert _retrieve_sql_examples("what did we spend", "postgresql") == []
        assert _sql_examples_block_for("what did we spend", "postgresql") == ""


def test_curated_questions_are_embedded_once_per_process():
    calls = []

    def counting(texts):
        calls.append(len(texts))
        return [[1.0] + [0.0] * 8 for _ in texts]

    with patch("chroma_client.get_embeddings", side_effect=counting):
        _retrieve_sql_examples("q1", "postgresql")
        _retrieve_sql_examples("q2", "postgresql")
    # First call embeds the whole set (N) plus the query (1); the second only the query.
    assert calls[0] == len(GOLDEN_SQL_EXAMPLES)
    assert calls[1:] == [1, 1]


def test_examples_land_in_the_tail_and_the_prefix_is_unchanged(db):
    with patch("chroma_client.get_embeddings", side_effect=_one_hot_embedder("titan_steel_payment_status")):
        with_ex = build_sql_system_prompt("has the titan invoice been paid", T, db)
    with patch("chroma_client.get_embeddings", side_effect=lambda texts: [[0.0] * 40 for _ in texts]):
        without = build_sql_system_prompt("has the titan invoice been paid", T, db)
    head_a, tail_a = with_ex.split(SQL_PROMPT_TENANT_SECTION_MARKER, 1)
    head_b, tail_b = without.split(SQL_PROMPT_TENANT_SECTION_MARKER, 1)
    assert head_a == head_b, "C4.3 must not disturb A4's cacheable prefix"
    assert "EXAMPLES (retrieved" in tail_a and "EXAMPLES (retrieved" not in tail_b


def test_examples_come_only_from_the_curated_module():
    """The risk the design named: cross-tenant leakage by example."""
    import inspect

    src = inspect.getsource(query_agent._curated_sql_examples) + inspect.getsource(query_agent._sql_example_vectors)
    assert "benchmarks.golden_sql_examples" in src
    for forbidden in ("ChatMessage", "get_prior_turn_sql", "get_chat_history", "session_id"):
        assert forbidden not in src, f"example retrieval must never read {forbidden}"


def test_every_curated_example_has_the_fields_the_prompt_needs():
    ids = set()
    for ex in GOLDEN_SQL_EXAMPLES:
        assert ex["case_id"] not in ids, f"duplicate {ex['case_id']}"
        ids.add(ex["case_id"])
        assert ex["question"].strip() and ex["sql"].strip()
        assert "{tenant_id}" in ex["sql"], f"{ex['case_id']}: the tenant predicate must be templated"
        assert ex["sql"].lstrip().upper().startswith("SELECT")
        if "sql_sqlite" in ex:
            assert "{tenant_id}" in ex["sql_sqlite"]
