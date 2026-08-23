"""Feature 21 Phase 2 — the orchestrator against the REAL configured LLM.

Why this exists as a script rather than a test: tool *selection* is a property of
the model, not of the loop. `tests/test_agentic_sage.py` can prove the call cap,
the clarification short-circuit and the arithmetic grounding exactly, because
those are rule-following behaviours of this code. It cannot prove that a real
model reaches for `ask_clarifying_question` on rule 4a's Titan Steel phrasing --
a mocked test asserting that would be asserting that the script says so. This
harness runs the real Azure deployment and prints what the model actually did,
including when it does different things on different runs.

WHAT IS REAL HERE AND WHAT IS NOT, stated plainly because the difference matters:

  * REAL: the configured Azure OpenAI deployment (no mocking at the LLM
    boundary), the real orchestrator graph, the real `identify_invoices` /
    `get_full_record` / `aggregate` / `compute` / `ask_clarifying_question`
    tools, their real prompts, and real SQL execution against a real database.
  * NOT real: the database is a seeded in-memory SQLite, not the live Postgres
    tenant -- the local docker stack (Postgres 5433, Chroma) was down when this
    was written, so `tests/realworld_tenant/`'s pattern was not available.
    `search_invoices` is fed a fixed chunk set for the same reason (no Chroma,
    so `get_full_record`'s per-invoice page fetch returns nothing either),
    and the tenant-stats snapshot is hand-written to match the seeded rows
    rather than computed, because SQLite stores UUIDs dashless and the ORM
    snapshot query would otherwise report an empty tenant and mislead the
    planner. Running the same questions against the live tenant is Phase 3's
    job, and this file does not substitute for it.

  Rows are inserted with raw SQL, deliberately: SQLite stores a UUID column as
  32-char dashless hex, while every generated query carries the dashed tenant
  literal that rule 1 and the tenant-isolation safety check require. Inserting
  the dashed form directly is what lets the real generated SQL actually match
  rows here.

Run:  python tests/run_agentic_sage_live.py [--repeats N]
Out:  tests/agentic_sage_live_output.json  (+ a printed transcript)
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch
from uuid import UUID, uuid4

_BE_ROOT = Path(__file__).resolve().parent.parent
if str(_BE_ROOT) not in sys.path:
    sys.path.insert(0, str(_BE_ROOT))

os.environ.setdefault("MOCK_EMBEDDINGS", "true")

from sqlalchemy.pool import StaticPool  # noqa: E402
from sqlmodel import Session, SQLModel, create_engine  # noqa: E402

import models  # noqa: E402,F401 -- registers every table on SQLModel.metadata

# Data moved to benchmarks/sage_seed_fixtures.py on 2026-08-23 so
# scripts/run_agent_eval.py (which ships inside the deployed image, see
# .dockerignore's tests/ exclusion) can import the same seed rows without
# reaching into tests/. Re-imported here rather than duplicated so this file's
# own CLI run and the scheduled job seed from one copy, not two that can drift.
from benchmarks.sage_seed_fixtures import (  # noqa: E402
    _CHUNKS,
    _ROWS,
    _TENANT_STATS,
    TENANT_ID,
    _seed,
)

OUTPUT_PATH = _BE_ROOT / "tests" / "agentic_sage_live_output.json"


# (id, why this question is on file, the phrasing, how many repeats)
QUESTIONS = [
    (
        "gap270_titan_steel_ambiguous_direction",
        "Gap 270 / rule 4a: names a real INBOUND vendor with no direction cue AND asks "
        "about payment status, which this schema does not track for INBOUND at all. The "
        "old pipeline guessed OUTBOUND, matched zero rows and reported a real invoice as "
        "not found. Does the loop ask instead of guessing?",
        "has the Titan Steel Distributors invoice been paid",
        3,
    ),
    (
        "gap270_redwood_ambiguous_direction",
        "Gap 270, the other half: same ambiguous shape, no payment term, so only rule 4a "
        "is in play.",
        "when is the Redwood Facilities Group invoice due",
        3,
    ),
    (
        "gap263_cgst_rajesh_steel",
        "Gaps 263/264: this schema stores one combined tax_amount and no per-component "
        "breakdown, so a CGST line-item search is guaranteed zero rows.",
        "whats the CGST we paid to Rajesh Steel",
        1,
    ),
    (
        "gap268_datapipe_vs_stratedge",
        "Gap 268 / rule 10: the comparison that generated ORDER BY ... LIMIT 1 and "
        "silently truncated the losing vendor's real row.",
        "Between DataPipe Solutions and StratEdge Partners, whose invoice to us had the bigger total?",
        1,
    ),
    (
        "gap271_freight_per_vendor",
        "Gap 271 / rule 6b-vs-6d: the per-vendor freight figure that came back as whole "
        "invoice totals, 10-40x too large.",
        "which vendors billed us for freight, delivery, or shipping charges, and how much per vendor",
        1,
    ),
    (
        "gap269_reconciliation_false_equation",
        "Gap 269: the live false equation, '5000.00 units x USD 0.08 = USD 420.00'.",
        "does the bolts line on invoice US-20260722-001 actually add up?",
        1,
    ),
    (
        "zero_result_then_broaden",
        "The multi-call shape the spec asks about by name: does the loop make a second "
        "call after a zero-result first one, or stop?",
        "what did we spend with Nonexistent Holdings last quarter",
        1,
    ),
    (
        "greeting_needs_no_tool",
        "A turn that should cost zero tool calls.",
        "hello there",
        1,
    ),
]


# `_seed()` now lives in benchmarks/sage_seed_fixtures.py, imported above.


def run_once(question: str, session) -> dict:
    from agents.sage_orchestrator import run_agentic_sage

    with ExitStack() as stack:
        stack.enter_context(
            patch("agents.sage_orchestrator._get_tenant_stats_summary", return_value=_TENANT_STATS)
        )
        stack.enter_context(patch("agents.query_tools.query_invoice_chunks", return_value=list(_CHUNKS)))
        # No Redis locally; the chat-style lookup is a DB read that returns the
        # default block, which is what an untrained tenant gets in production too.
        out = run_agentic_sage(str(uuid4()), question, TENANT_ID, session)
    return out


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--repeats", type=int, default=None, help="override every question's repeat count")
    parser.add_argument("--only", default=None, help="run just one question id")
    args = parser.parse_args()

    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    SQLModel.metadata.create_all(engine)

    records = []
    with Session(engine) as session:
        _seed(session)
        for qid, why, question, repeats in QUESTIONS:
            if args.only and args.only != qid:
                continue
            for run_index in range(args.repeats or repeats):
                print(f"\n{'=' * 78}\n{qid}  (run {run_index + 1})\nQ: {question}\n{'=' * 78}")
                try:
                    out = run_once(question, session)
                except Exception as e:  # a harness failure is data too
                    print(f"  RAISED: {type(e).__name__}: {e}")
                    records.append({"id": qid, "run": run_index + 1, "question": question, "error": repr(e)})
                    continue

                agentic = out.get("agentic") or {}
                print(f"  tools called   : {agentic.get('tools_called')}")
                print(f"  tool calls made: {agentic.get('tool_calls_made')}")
                print(f"  stop reason    : {agentic.get('stop_reason')}")
                print(f"  clarification  : {agentic.get('clarification_reason')}")
                print(f"  generated SQL  : {out.get('generated_sql')}")
                print(f"  ANSWER: {out.get('content')}")
                records.append(
                    {
                        "id": qid,
                        "why_on_file": why,
                        "run": run_index + 1,
                        "question": question,
                        "tools_called": agentic.get("tools_called"),
                        "tool_calls_made": agentic.get("tool_calls_made"),
                        "stop_reason": agentic.get("stop_reason"),
                        "clarification_reason": agentic.get("clarification_reason"),
                        "generated_sql": out.get("generated_sql"),
                        "content": out.get("content"),
                    }
                )

    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(records, f, indent=2, ensure_ascii=False)
    print(f"\nWrote {len(records)} live records to {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
