"""Feature 21 Phase 2 — the flag-off parity harness.

Phase 1 proved its refactor was a true refactor by keeping the pre-refactor
module and running both versions side by side over the same DB and the same
scripted LLM, comparing every prompt and every returned dict byte-for-byte.
Phase 2 needs the same proof for a different claim: that with
`ENABLE_AGENTIC_SAGE` off -- the default, and the only state any real tenant is
in today -- `run_query_agent()` behaves exactly as it did before the orchestrator
existed.

The mechanism here is a recorded golden rather than a second copy of the module.
The scripted cases below were run against the **pre-Phase-2** `query_agent.py`
and their full output (the returned result dict, every SQL-generation prompt, and
every synthesis prompt, verbatim) written to
`tests/fixtures/query_agent_flag_off_parity.json`. `test_agentic_sage.py` replays
the identical cases against the current code with the flag off and asserts an
exact match. A golden survives future commits, which a `git show HEAD:` diff
against a moving ref would not.

Regenerate deliberately, never casually -- rewriting the golden is exactly how a
parity check stops proving anything:

    python tests/agentic_sage_parity_cases.py --write

Regeneration log -- every entry states what changed and how it was checked
--------------------------------------------------------------------------
  * **2026-08-24, Gap 310.** The flag-off SQL route now hands the identified
    invoice's whole ORM row to its answering step, and two pieces of prompt prose
    that asserted the opposite were corrected: rule 6d's "the schema has NO
    concept of tax-component breakdown at all -- it stores exactly one combined
    `tax_amount` field per invoice, full stop", and `_tax_term_block_for()`'s
    "This schema has no breakdown by tax type; select tax_amount directly". Both
    were true when written and had been false since extraction started populating
    `Invoice.taxes`.

    Before rewriting, the old golden was diffed against the new run field by
    field. Exactly two lines of `sql_prompts` differ across all eight cases (rule
    6d's tax paragraph, and the tax-term NOTE on the one case whose question
    contains "CGST"). **`result` and `summary_prompts` were byte-identical on
    every case** -- the same answers, the same SQL, the same citations, the same
    synthesis prompts -- which is what makes this a recorded prompt correction
    rather than undetected pipeline drift. The new full-record block interpolates
    directly after `{db_result}` with no separating newline precisely so that a
    turn which identified no invoice (all eight of these do) renders a summary
    prompt that is unchanged to the byte.

Every case is a real historical phrasing from this repo's own tracker, matching
the five Phase 1 used plus one per remaining route: rule 4a's Titan Steel
Distributors question (Gap 270), the Rajesh Steel CGST question (Gaps 263/264), a
rule 9 narrowing follow-up with a prior SQL turn (Gap 237), a first-attempt
failure that exercises the repair loop, a null-SQL follow-up that exercises the
retry-once path, a rule 8 decline, and one RAG-route and one CHAT-route turn.
"""
from __future__ import annotations

import json
import os
import sys
from contextlib import ExitStack
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch
from uuid import UUID

os.environ.setdefault("MOCK_EMBEDDINGS", "true")

_BE_ROOT = Path(__file__).resolve().parent.parent
if str(_BE_ROOT) not in sys.path:
    sys.path.insert(0, str(_BE_ROOT))

from sqlalchemy.pool import StaticPool  # noqa: E402
from sqlmodel import Session, SQLModel, create_engine  # noqa: E402

from dependencies import MOCK_TENANT_ID  # noqa: E402
from models import ChatMessage, Invoice  # noqa: E402

GOLDEN_PATH = _BE_ROOT / "tests" / "fixtures" / "query_agent_flag_off_parity.json"

# Every id is fixed, never uuid4(): the golden is compared byte-for-byte, so a
# random id would make the harness fail against itself on the second run.
_SESSION_ID = UUID("11111111-1111-1111-1111-111111111111")
_INVOICE_ID = UUID("22222222-2222-2222-2222-222222222222")
_PRIOR_MSG_ID = UUID("33333333-3333-3333-3333-333333333333")
_FIXED_TIME = datetime(2026, 8, 21, 12, 0, 0)

_PRIOR_SQL = (
    f"SELECT invoice_number, grand_total, currency FROM invoice "
    f"WHERE tenant_id = '{MOCK_TENANT_ID}' AND currency = 'USD'"
)


class _RecordingLLM:
    """Same shape as `test_chat_sql_quality.py`'s and `test_query_tools.py`'s.

    SQL-generation prompts and synthesis prompts are kept in separate lists
    because the golden compares both, and a route that stops making one of the
    two calls has to show up as a difference rather than silently shifting an
    index.
    """

    def __init__(self, sql_results, summary="Formatted summary."):
        self._sql_results = list(sql_results)
        self._summary = summary
        self.prompts: list[str] = []
        self.summary_prompts: list[str] = []

    def with_structured_output(self, schema):
        outer = self

        class _Structured:
            def invoke(self, prompt):
                outer.prompts.append(prompt)
                if not outer._sql_results:
                    raise AssertionError("SQL generation called more times than scripted")
                return outer._sql_results.pop(0)

        return _Structured()

    def invoke(self, prompt):
        self.summary_prompts.append(prompt)
        return MagicMock(content=self._summary)


def _sql(select_list="grand_total, currency", where_extra=""):
    return (
        f"SELECT {select_list} FROM invoice WHERE tenant_id = '{MOCK_TENANT_ID}'{where_extra}"
    )


def _seed(session, *, with_prior_turn: bool):
    session.add(
        Invoice(
            id=_INVOICE_ID,
            tenant_id=MOCK_TENANT_ID,
            file_path="mock/inv.pdf",
            flow_direction="INBOUND",
            status="COMPLETED",
            currency="USD",
            vendor_name="Titan Steel Distributors",
            invoice_number="US-20260722-001",
            grand_total=1000.0,
        )
    )
    if with_prior_turn:
        session.add(
            ChatMessage(
                id=_PRIOR_MSG_ID,
                session_id=_SESSION_ID,
                role="assistant",
                content="You have 3 USD invoices totaling USD 2,655,637.56.",
                generated_sql=_PRIOR_SQL,
                result_invoice_ids=[],
                created_at=_FIXED_TIME,
            )
        )
    session.commit()


_RAG_CHUNKS = [
    {
        "id": "chunk-1",
        "document": "Training & Onboarding 40 units at USD 732.57",
        "distance": 0.12,
        "matched_by": "semantic",
        "metadata": {
            "invoice_id": str(_INVOICE_ID),
            "vendor_name": "Titan Steel Distributors",
            "page": 1,
        },
    }
]


# name -> (question, classified_route, scripted SQL results, needs a prior turn?)
CASES = [
    (
        "rule_4a_titan_steel",
        "has the Titan Steel Distributors invoice been paid",
        "SQL",
        [MagicMock(sql=_sql("status, currency"), explanation_or_error=None)],
        False,
    ),
    (
        "rule_6d_cgst_rajesh_steel",
        "whats the CGST we paid to Rajesh Steel",
        "SQL",
        [MagicMock(sql=_sql("tax_amount, currency"), explanation_or_error=None)],
        False,
    ),
    (
        "rule_9_narrowing_followup",
        "Can you explain the 3 USD ones in detail?",
        "SQL",
        [MagicMock(sql=_sql("invoice_number, grand_total, currency"), explanation_or_error=None)],
        True,
    ),
    (
        "repair_loop_first_attempt_fails",
        "how much did we spend on freight last quarter",
        "SQL",
        [
            # No tenant predicate -> execute_generated_sql raises -> the error is
            # fed back into the prompt and attempt 2 runs. The repaired prompt is
            # part of the golden.
            MagicMock(sql="SELECT grand_total, currency FROM invoice", explanation_or_error=None),
            MagicMock(sql=_sql(), explanation_or_error=None),
        ],
        False,
    ),
    (
        "null_sql_followup_retry_once",
        "Can you explain the 3 USD ones in detail?",
        "SQL",
        [
            MagicMock(sql=None, explanation_or_error="I already answered this above."),
            MagicMock(sql=_sql("invoice_number, currency"), explanation_or_error=None),
        ],
        True,
    ),
    (
        "rule_8_decline_no_prior_sql",
        "which of my invoices were approved by Sandra in accounting",
        "SQL",
        [MagicMock(sql=None, explanation_or_error="The schema has no approver column.")],
        False,
    ),
    (
        "rag_route_document_question",
        "what does the vendor say about payment terms",
        "RAG",
        [],
        False,
    ),
    (
        "chat_route_greeting",
        "hello there",
        "CHAT",
        [],
        False,
    ),
]


def run_case(name: str, question: str, route: str, sql_results, with_prior_turn: bool) -> dict:
    """One scripted turn through `run_query_agent()`, with everything nondeterministic
    (routing, Redis, Chroma, the LLM, the tenant-stats snapshot) pinned."""
    from agents import query_agent

    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    try:
        with Session(engine) as session:
            _seed(session, with_prior_turn=with_prior_turn)
            llm = _RecordingLLM(sql_results)
            with ExitStack() as stack:
                for p in (
                    patch("agents.query_agent.classify_query", return_value=route),
                    patch("agents.query_agent.query_invoice_chunks", return_value=list(_RAG_CHUNKS)),
                    patch("agents.query_agent.get_llm", return_value=llm),
                    patch("agents.query_agent.get_cached_answer", return_value=None),
                    patch("agents.query_agent.set_cached_answer"),
                    patch("agents.query_agent._get_tenant_stats_summary", return_value=""),
                ):
                    stack.enter_context(p)
                result = query_agent.run_query_agent(
                    str(_SESSION_ID), question, str(MOCK_TENANT_ID), session
                )
            # Gap 304 half (2), 2026-08-24: `run_query_agent()` now also returns
            # `judge_evidence` — the turn's own tool output, for the online
            # quality judge. Split out of `result` here rather than regenerating
            # the golden, deliberately: the golden's claim is that the *pipeline*
            # is unchanged (same answer, same SQL, same citations, same prompts),
            # and rewriting it to absorb an additive key would also silently
            # absorb anything else that had drifted since it was recorded. It is
            # returned as its own record field instead, so the parity test can
            # still assert the new payload is present on every route.
            judge_evidence = result.pop("judge_evidence", None)
            # Gap 302, 2026-08-24: same treatment, same reasoning, for the Trace
            # payload `run_query_agent()` now also returns. Split out rather than
            # folded into the golden — and additionally *not* kept as a record
            # field, because unlike `judge_evidence` it is not deterministic: it
            # carries a fresh `turn_id` UUID and a wall-clock
            # `seconds_since_prev_turn` per run, so a golden containing it could
            # never match twice. The parity test asserts its presence and shape
            # separately instead.
            turn_telemetry = result.pop("turn_telemetry", None)
            return {
                "case": name,
                "question": question,
                "route": route,
                "result": json.loads(json.dumps(result, default=str)),
                "judge_evidence": judge_evidence,
                "turn_telemetry_present": turn_telemetry is not None,
                "turn_telemetry_route": (turn_telemetry or {}).get("route"),
                "turn_telemetry_status": (turn_telemetry or {}).get("status"),
                "sql_prompts": list(llm.prompts),
                "summary_prompts": list(llm.summary_prompts),
            }
    finally:
        SQLModel.metadata.drop_all(engine)
        engine.dispose()


def run_all() -> list[dict]:
    return [run_case(*case) for case in CASES]


def load_golden() -> list[dict]:
    with open(GOLDEN_PATH, encoding="utf-8") as f:
        return json.load(f)


if __name__ == "__main__":
    if "--write" not in sys.argv:
        print(__doc__)
        print("Refusing to overwrite the golden without --write.")
        raise SystemExit(1)
    records = run_all()
    GOLDEN_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(GOLDEN_PATH, "w", encoding="utf-8") as f:
        json.dump(records, f, indent=2, ensure_ascii=False)
    print(f"Wrote {len(records)} parity records to {GOLDEN_PATH}")
