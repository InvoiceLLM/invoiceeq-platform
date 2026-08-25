"""Gap 294 reproduction — the SQL route leaking generated SQL / the tenant UUID.

Run with: uv run pytest tests/gap294_sql_leak_repro.py -p no:randomly -q

Scratch reproduction, kept out of the permanent suite deliberately: it asserts
the BROKEN behaviour so it is expected to FAIL once the fix lands. The permanent
assertions live in tests/test_chat_sql_quality.py.
"""
import os
import re
from contextlib import ExitStack
from unittest.mock import patch, MagicMock
from uuid import uuid4

import pytest
from sqlmodel import SQLModel, create_engine, Session
from sqlalchemy.pool import StaticPool

os.environ["MOCK_EMBEDDINGS"] = "true"

from dependencies import MOCK_TENANT_ID  # noqa: E402
from models import Invoice  # noqa: E402
from agents import query_agent  # noqa: E402

sqlite_url = "sqlite:///:memory:"
engine = create_engine(sqlite_url, connect_args={"check_same_thread": False}, poolclass=StaticPool)

UUID_RE = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.I)


@pytest.fixture(name="db_session")
def db_session_fixture():
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    SQLModel.metadata.drop_all(engine)


class _LLM:
    def __init__(self, sql_results, summary="Formatted summary."):
        self._sql_results = list(sql_results)
        self._summary = summary
        self.prompts = []
        self.summary_prompts = []

    def with_structured_output(self, schema):
        outer = self

        class _S:
            def invoke(self, prompt):
                outer.prompts.append(prompt)
                return outer._sql_results.pop(0)

        return _S()

    def invoke(self, prompt):
        self.summary_prompts.append(prompt)
        return MagicMock(content=self._summary)


def _run(db_session, llm, message, *, execute=None):
    patches = [
        patch("agents.query_agent.classify_query", return_value="SQL"),
        patch("agents.query_agent.query_invoice_chunks", return_value=[]),
        patch("agents.query_agent.get_llm", return_value=llm),
        patch("agents.query_agent.get_cached_answer", return_value=None),
        patch("agents.query_agent.set_cached_answer"),
        patch("agents.query_agent._get_tenant_stats_summary", return_value=""),
    ]
    if execute is not None:
        patches.append(patch("agents.query_agent.execute_generated_sql", side_effect=execute))
    with ExitStack() as stack:
        for p in patches:
            stack.enter_context(p)
        return query_agent.run_query_agent(
            str(uuid4()), message, str(MOCK_TENANT_ID), db_session
        )


LEAKED_SQL = (
    "SELECT invoice_number, vendor_name, items FROM invoice WHERE tenant_id = "
    f"'{MOCK_TENANT_ID}' AND flow_direction = 'INBOUND' AND "
    "(LOWER(CAST(items AS TEXT)) LIKE LOWER('%payment terms%'))"
)


def test_repro_1_declined_answer_pastes_the_query_and_tenant_uuid(db_session):
    """The live Gap 294 shape: sql: null, and the model's clarifying question
    body contains the query it says it would have run."""
    llm = _LLM([MagicMock(sql=None, explanation_or_error=(
        "I looked for payment terms but the schema has no such column. "
        "Here is what I ran:\n\n"
        f"{LEAKED_SQL}\n\n"
        "Could you tell me which vendor you mean?"
    ))])
    out = _run(db_session, llm, "what does the vendor say about payment terms")
    print("\n--- DECLINED ANSWER AS RETURNED TO THE USER ---\n" + out["content"])
    assert str(MOCK_TENANT_ID) in out["content"], "no tenant uuid leak"
    assert "SELECT invoice_number" in out["content"], "no raw sql leak"


def test_repro_2_execution_error_message_pastes_the_whole_statement(db_session):
    """Every attempt fails -> the driver's exception text (which embeds the full
    statement, tenant literal and all) is interpolated into the user's answer."""
    llm = _LLM([MagicMock(sql=LEAKED_SQL, explanation_or_error=None)] * 3)

    def _boom(sql, tenant_id, db_sess, snapshot=None):
        raise Exception(
            '(psycopg2.errors.UndefinedFunction) function lower(jsonb) does not exist\n'
            f"[SQL: {LEAKED_SQL}]\n[parameters: {{}}]"
        )

    out = _run(db_session, llm, "which invoices mention payment terms", execute=_boom)
    print("\n--- ERROR ANSWER AS RETURNED TO THE USER ---\n" + out["content"])
    assert str(MOCK_TENANT_ID) in out["content"], "no tenant uuid leak"
    assert "FROM invoice WHERE tenant_id" in out["content"], "no raw sql leak"


def test_repro_3_full_record_block_hands_the_tenant_uuid_to_the_answer_model(db_session):
    """The prose-generating prompt itself carries the tenant UUID (and the row's
    own id), defended only by a prose 'do not print raw UUIDs' sentence."""
    inv = Invoice(
        id=uuid4(), tenant_id=MOCK_TENANT_ID, file_path="mock/inv.pdf",
        flow_direction="INBOUND", status="COMPLETED", currency="INR",
        invoice_number="INV-1", vendor_name="Acme", grand_total=100.0,
    )
    db_session.add(inv)
    db_session.commit()

    def _exec(sql, tenant_id, db_sess, snapshot=None):
        if snapshot is not None:
            snapshot.append(str(inv.id))
        return "invoice_number | currency\n--- | ---\nINV-1 | INR"

    # The model restates what it was given -- exactly what the tracker recorded
    # ("the SQL it claimed to have run was fabricated"), and impossible to
    # prevent with a prompt rule.
    llm = _LLM(
        [MagicMock(sql=LEAKED_SQL, explanation_or_error=None)],
        summary=f"I answered this by running:\n{LEAKED_SQL}\nInvoice INV-1 totals INR 100.",
    )
    out = _run(db_session, llm, "give me the details of invoice INV-1", execute=_exec)
    prompt = llm.summary_prompts[0]
    print("\n--- TENANT UUID IN SUMMARY PROMPT: ---", str(MOCK_TENANT_ID) in prompt)
    print("--- ANSWER AS RETURNED TO THE USER ---\n" + out["content"])
    assert str(MOCK_TENANT_ID) in prompt, "tenant uuid not in the answering prompt"
    assert str(MOCK_TENANT_ID) in out["content"], "no tenant uuid leak in the answer"
    assert "FROM invoice WHERE tenant_id" in out["content"], "no raw sql leak"
