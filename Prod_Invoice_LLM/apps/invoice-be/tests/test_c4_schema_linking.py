"""Feature 6.1 item C4, part 1 — schema linking before generation.

Rule 6d has been amended by ten gaps, each a new prose exception for a class of
word the previous prose missed. The question every amendment answers is the same
one: is this word a thing you buy, or a property of the invoice? C4.1 answers it
deterministically, BEFORE the model runs, and hands the result to the model as
facts in the request tail. Hard rule 3 is untouched: this links terms to columns
and computes nothing.

The one case rule 6d was written for must survive the inverted default: "the
amount only for training and onboarding" links to no column and still reaches
the line-item join. That is the last test here, and the reason the fallback
exists at all.
"""
import os

import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

os.environ.setdefault("MOCK_EMBEDDINGS", "true")

from agents.query_agent import (  # noqa: E402
    _DETAILS_PROJECTION,
    _NAMED_METRICS,
    SQL_PROMPT_TENANT_SECTION_MARKER,
    _schema_linking_block_for,
    build_sql_system_prompt,
    link_question_to_schema,
)

T = "11111111-1111-1111-1111-111111111111"


@pytest.fixture(scope="module")
def db():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    with Session(engine) as s:
        yield s


# ---------------------------------------------------------------------------
# Linking: the golden shapes
# ---------------------------------------------------------------------------


def test_an_invoice_attribute_links_to_its_column_and_never_to_line_items():
    """The Gap 413 shape."""
    link = link_question_to_schema("discount amount for apex consulting group")
    assert link["attribute"] == ("discount amount", "discount_amount")
    assert link["line_item_fallback"] is False


def test_a_tax_component_links_to_tax_amount():
    """The Gap 310 shape (rajesh_steel_cgst)."""
    link = link_question_to_schema("whats the CGST we paid to Rajesh Steel")
    assert link["tax_term"] == "CGST"
    assert "tax" in link["metrics"]
    assert link["line_item_fallback"] is False


@pytest.mark.parametrize(
    "question, metric",
    [
        ("what did we spend with DataPipe Solutions", "spend"),
        ("how much do we owe Titan Steel", "spend"),
        ("what is owed to us by Anand Distributors", "revenue"),
        ("what's the subtotal on the Ganesh Hardware invoice", "subtotal"),
        ("how many invoices do we have from Blue Ridge", "count"),
        ("which invoices are overdue", "outstanding"),
    ],
)
def test_named_metrics_link(question, metric):
    link = link_question_to_schema(question)
    assert metric in link["metrics"], link


def test_a_payment_status_question_links_to_outstanding_and_keeps_the_detector():
    """The Gap 267 shape: the direction-aware note about INBOUND rows must reach
    the block, because this has been answered wrong live in both directions."""
    link = link_question_to_schema("has the Titan Steel Distributors invoice been paid")
    assert link["payment_status"] == "been paid"
    assert "outstanding" in link["metrics"]
    block = _schema_linking_block_for("has the Titan Steel Distributors invoice been paid")
    assert "INBOUND rows: this table holds NO payment signal" in block


def test_a_details_question_links_to_the_named_projection():
    """Rule 11, as a fact instead of a paragraph."""
    link = link_question_to_schema("give me the details of invoice TSD-620458")
    assert link["details"] is True
    block = _schema_linking_block_for("give me the details of invoice TSD-620458")
    assert _DETAILS_PROJECTION in block


def test_the_genuine_line_item_case_links_to_no_column_and_keeps_the_join():
    """What rule 6d was written for. The inverted default must not lose it."""
    link = link_question_to_schema("I want the amount only for training and onboarding from the total invoice")
    assert link["attribute"] is None
    assert link["tax_term"] is None
    assert link["details"] is False
    assert link["line_item_fallback"] is True, "a product phrase with a money word must still be a line-item search"
    block = _schema_linking_block_for("I want the amount only for training and onboarding from the total invoice")
    assert "rule 6d" in block and "no SUM" in block


def test_nothing_links_on_a_greeting_or_a_text_question():
    assert link_question_to_schema("hello there")["line_item_fallback"] is False
    assert _schema_linking_block_for("hello there") == ""
    assert _schema_linking_block_for("what does the vendor say about payment terms") != "", (
        "'payment terms' is an invoice attribute (payment_instructions) and must link"
    )


def test_every_metric_names_a_real_column_or_count():
    for name, m in _NAMED_METRICS.items():
        assert m["column"], name
        assert m["note"], name


# ---------------------------------------------------------------------------
# Placement: in the tail, never in the cacheable prefix
# ---------------------------------------------------------------------------


def test_the_block_lands_below_the_marker_and_the_prefix_is_unchanged(db):
    plain = build_sql_system_prompt("what did titan bill us", T, db)
    linked = build_sql_system_prompt("discount amount for apex consulting group", T, db)
    head_p, tail_p = plain.split(SQL_PROMPT_TENANT_SECTION_MARKER, 1)
    head_l, tail_l = linked.split(SQL_PROMPT_TENANT_SECTION_MARKER, 1)
    assert head_p == head_l, "C4.1 must not disturb A4's cacheable prefix"
    # The block header, not the bare phrase: the static rules may *mention* the
    # SCHEMA LINK section by name, and that mention is legitimately in the prefix.
    assert "SCHEMA LINK (computed" in tail_l
    assert "SCHEMA LINK (computed" not in head_l
    assert "discount_amount" in tail_l


def test_the_block_precedes_rule_6d_in_the_tail(db):
    """Facts first, then the rule they may override."""
    prompt = build_sql_system_prompt("discount amount for apex consulting group", T, db)
    tail = prompt.split(SQL_PROMPT_TENANT_SECTION_MARKER, 1)[1]
    assert tail.index("SCHEMA LINK") < tail.index("6d. LINE-ITEM LEVEL EXTRACTION")
