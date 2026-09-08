"""Gap 484 (Feature 29 phase-2 P1.1/P1.2) -- run isolation and the SQL denominator.

Two harness defects that both corrupt a published number.

**P1.1, `--fresh-tenants`.** The task was written as "so cache and prior answers cannot
leak between runs". Read against the code, three mechanisms already stop that: a new
in-memory SQLite database per run, `get_cached_answer` stubbed to return None, and Chroma
stubbed with fixtures. What fixed tenant ids still cost is the **persist path** -- every
run in history lands under the same tenant id in `agent_eval_run`, so one run cannot be
separated from the next -- and any future run made without those stubs. The tests below
pin the mapping and the seeding, and the docstring in `fresh_tenant_map()` says which of
those two it is for, so nobody later cites it as a cache fix.

**P1.2, the SQL denominator.** Two defects, and the second is the serious one:

  1. The denominator floated. Errored turns were dropped, turns without `generated_sql`
     were dropped, and ungraded turns were dropped -- so a timeout left the denominator
     instead of scoring zero. The five-model matrix reports n = 31/27/27/25/27 for one
     36-case set, which is that leak made visible.
  2. `expected_invoice_numbers` was **never written into a turn record**, so the
     deterministic `set(expected) <= set(fetched)` branch had never executed once and
     every "SQL exec-correct %" ever published silently came from the fallback: the
     judge's accuracy score >= 0.8. A deterministic metric was being graded by a model
     (hard rule 3), and by the model Gap 479 measured at kappa 0.151.
"""
from __future__ import annotations

import os
import uuid

import pytest
from sqlalchemy import create_engine, text

from benchmarks.agent_eval_golden_sample import CASES, TENANT_ID
from benchmarks.region_seed_fixtures import REGION_TENANTS
from benchmarks.sage_seed_fixtures import _ROWS, _seed
from scripts.run_agent_eval import fresh_tenant_map
from scripts.run_model_matrix import digest_eval


# ---------------------------------------------------------------------------
# P1.1 -- the mapping
# ---------------------------------------------------------------------------

def test_every_tenant_gets_a_distinct_fresh_uuid():
    originals = [TENANT_ID, *REGION_TENANTS]
    mapping = fresh_tenant_map(originals)
    assert set(mapping) == {str(t) for t in originals}
    fresh = list(mapping.values())
    assert len(set(fresh)) == len(fresh), "two tenants were given the same id"
    for value in fresh:
        uuid.UUID(value)  # raises if it is not a real uuid


def test_a_repeated_id_is_mapped_once_and_order_is_kept():
    mapping = fresh_tenant_map(["a", "b", "a", "c"])
    assert list(mapping) == ["a", "b", "c"]


def test_two_runs_never_share_a_tenant_id():
    """The whole point: run N's rows cannot be confused with run N+1's."""
    first = fresh_tenant_map([TENANT_ID])
    second = fresh_tenant_map([TENANT_ID])
    assert first[str(TENANT_ID)] != second[str(TENANT_ID)]


def test_no_fresh_id_collides_with_a_fixture_id():
    mapping = fresh_tenant_map([TENANT_ID, *REGION_TENANTS])
    fixture_ids = {str(TENANT_ID), *(str(t) for t in REGION_TENANTS)}
    assert not (set(mapping.values()) & fixture_ids)


# ---------------------------------------------------------------------------
# P1.1 -- seeding, on real Postgres (CONVENTIONS hard rule 2)
# ---------------------------------------------------------------------------

def _postgres_engine():
    url = os.environ.get("DATABASE_URL") or ""
    if not url:
        from config import get_settings

        url = get_settings().DATABASE_URL or ""
    if not url.startswith("postgresql"):
        pytest.skip("DATABASE_URL is not PostgreSQL")
    try:
        engine = create_engine(url)
        with engine.connect():
            pass
    except Exception as exc:  # pragma: no cover - environment
        pytest.skip(f"local Postgres not reachable: {exc}")
    return engine


def test_a_fresh_tenant_is_created_seeded_counted_and_torn_down():
    """Create, seed, count, delete -- against the real database, not SQLite."""
    engine = _postgres_engine()
    fresh = fresh_tenant_map([TENANT_ID])[str(TENANT_ID)]
    from sqlmodel import Session

    with Session(engine) as session:
        # nothing there to begin with
        before = session.execute(
            text("SELECT count(*) FROM invoice WHERE tenant_id = :t"), {"t": fresh}
        ).scalar_one()
        assert before == 0, "a freshly generated tenant id already had rows"

        # This database is shared and already carries these invoice numbers under
        # other tenants from earlier runs -- which is precisely the condition the
        # flag exists for. So the assertion is not "these numbers are unique in the
        # database"; it is "seeding under a fresh tenant changes no other tenant".
        others_before = session.execute(
            text("SELECT count(*) FROM invoice WHERE tenant_id <> :t"), {"t": fresh}
        ).scalar_one()

        try:
            seeded = _seed(session, _ROWS, tenant_id=fresh)
            session.commit()
            assert len(seeded) == len(_ROWS)

            counted = session.execute(
                text("SELECT count(*) FROM invoice WHERE tenant_id = :t"), {"t": fresh}
            ).scalar_one()
            assert counted == len(_ROWS), f"seeded {len(_ROWS)} rows, found {counted}"

            others_after = session.execute(
                text("SELECT count(*) FROM invoice WHERE tenant_id <> :t"), {"t": fresh}
            ).scalar_one()
            assert others_after == others_before, (
                f"seeding a fresh tenant changed another tenant's row count "
                f"({others_before} -> {others_after})"
            )
        finally:
            session.rollback()
            session.execute(
                text("DELETE FROM invoice WHERE tenant_id = :t"), {"t": fresh}
            )
            session.commit()

        assert session.execute(
            text("SELECT count(*) FROM invoice WHERE tenant_id = :t"), {"t": fresh}
        ).scalar_one() == 0, "teardown left rows behind"


# ---------------------------------------------------------------------------
# P1.2 -- the denominator
# ---------------------------------------------------------------------------

def _turn(case_id, *, expected=None, fetched=(), sql="SELECT 1", error=None, accuracy=None):
    return {
        "case_id": case_id,
        "expected_invoice_numbers": expected,
        "fetched_invoice_numbers": list(fetched),
        "generated_sql": sql,
        "error": error,
        "accuracy_score": accuracy,
        "tokens_in": 10,
        "tokens_out": 5,
        "llm_call_count": 1,
        "latency_ms": 100.0,
        "llm_events": [],
    }


def test_a_timeout_counts_as_wrong_instead_of_leaving_the_denominator():
    """The defect in one assertion: two cases, one correct, one dead -> 50%, not 100%."""
    turns = [
        _turn("ok", expected=["A-1"], fetched=["A-1"]),
        _turn("died", expected=["B-2"], fetched=[], sql=None, error="timeout"),
    ]
    c, _d = digest_eval({"turns": turns}, "gpt-5-mini")
    assert c["n"] == 2, "the errored turn left the denominator"
    assert c["sql_pass_pct"] == 50.0
    assert c["errored"] == 1
    assert c["no_statement"] == 1


def test_the_denominator_is_the_case_set_not_the_turns_that_answered():
    turns = [_turn(f"c{i}", expected=["X"], fetched=["X"]) for i in range(3)]
    turns.append(_turn("dead", expected=["Y"], fetched=[], sql=None, error="boom"))
    c, _ = digest_eval({"turns": turns}, "gpt-5-mini")
    assert c["n"] == 4
    assert c["sql_pass_pct"] == 75.0


def test_grading_is_the_deterministic_set_comparison_not_the_judge():
    """A turn the judge loved but that fetched the wrong invoice must score 0."""
    turns = [_turn("wrong_rows", expected=["A-1"], fetched=["Z-9"], accuracy=1.0)]
    c, _ = digest_eval({"turns": turns}, "gpt-5-mini")
    assert c["sql_pass_pct"] == 0.0, "the judge's accuracy score is grading exec-correctness"
    assert c["graded_by"].startswith("deterministic")


def test_a_superset_of_the_expected_rows_still_passes():
    turns = [_turn("extra", expected=["A-1"], fetched=["A-1", "A-2"])]
    c, _ = digest_eval({"turns": turns}, "gpt-5-mini")
    assert c["sql_pass_pct"] == 100.0


def test_an_empty_expectation_is_gradeable_and_a_missing_one_is_not():
    """`()` means 'fetch nothing' and is a real expectation; `None` means the case
    declares none and must leave the turn unscored rather than scored as perfect."""
    turns = [
        _turn("expects_nothing", expected=[], fetched=[]),
        _turn("declares_none", expected=None, fetched=["A-1"]),
    ]
    c, _ = digest_eval({"turns": turns}, "gpt-5-mini")
    assert c["n"] == 1, "a case with no declared expectation was graded anyway"
    assert c["sql_pass_pct"] == 100.0


def test_n_is_reported_beside_the_percentage():
    turns = [_turn("a", expected=["A"], fetched=["A"])]
    c, _ = digest_eval({"turns": turns}, "gpt-5-mini")
    assert c["n"] == c["scored"] == 1
    assert c["metric"] == c["sql_pass_pct"]


# ---------------------------------------------------------------------------
# P1.2 -- the ground truth actually reaches the record
# ---------------------------------------------------------------------------

def test_run_turn_writes_the_expected_invoice_numbers_into_the_record():
    """Without this the deterministic branch above is unreachable, which is exactly
    the state every published SQL exec-correct % was measured in."""
    src = (
        __import__("pathlib").Path(__file__).resolve().parents[1]
        / "scripts" / "run_agent_eval.py"
    ).read_text(encoding="utf-8")
    assert '"expected_invoice_numbers": (' in src
    assert "case.expected_invoice_numbers is None" in src


def test_the_golden_cases_still_declare_expectations_to_grade_on():
    declared = [c for c in CASES if c.expected_invoice_numbers is not None]
    assert len(declared) >= 20, (
        f"only {len(declared)} of {len(CASES)} golden cases declare an expected "
        f"retrieval set; the SQL metric's denominator is that number"
    )
