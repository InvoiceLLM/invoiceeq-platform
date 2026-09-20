"""Feature 35 (ATLAS Intelligence) task 35.5 — the briefing guards themselves.

Spec: `docs/feature_35_atlas_intelligence.md` §3.3, §6 (task 35.5's row).

`tests/test_atlas_agent.py` proves the loop *calls* these guards and drops what
they reject. This file proves the guards are right about what to reject, one
rule at a time, and that the set they test against is built from rows a real
tool returned rather than from a literal in a test.

Most of the file needs no database: a guard is a pure function of a paragraph
and two sets, and pretending otherwise would slow the suite for nothing. The
one property that *is* about the database — that `run_tool()` fills
`run.rendered_tokens` from the figures a real adapter rendered — runs on real
Postgres (hard rule 2, BE Gap 697), because a token set assembled from a stub
would prove nothing about the rows the model is actually shown.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest

from models import Invoice, Tenant
from services.atlas_capabilities import GrantSet
from services.atlas_contract import (
    BriefingEvent,
    BriefingParagraph,
    BriefingQuestion,
    Citation,
    InventedNumberError,
    StructureInProseError,
    UncitedParagraphError,
    assert_briefing_no_undeclared_numbers,
    assert_paragraph_cited,
    assert_paragraph_no_structure,
    rendered_tokens_of,
    validate_briefing_paragraph,
)
from services.atlas_skills import SkillContext
from services.atlas_tools import BriefingRun, ToolContext, run_tool
from tests.atlas_pg import open_session, postgres_only, unique_tag

TODAY = date(2026, 9, 18)
ADMIN = GrantSet(can_audit=True, can_train=True, can_load=True, is_admin=True)


def _paragraph(text: str, *citations: Citation) -> BriefingParagraph:
    return BriefingParagraph(text=text, citations=list(citations))


def _cite(record_id: str, tool: str = "list_lines", kind: str = "recommendation"):
    return Citation(tool=tool, record_kind=kind, record_id=record_id)


# ═════════════════════════════════════════════════════════════════════════════
# 1. assert_paragraph_cited
# ═════════════════════════════════════════════════════════════════════════════

def test_a_paragraph_with_citations_the_run_emitted_passes():
    assert_paragraph_cited(_paragraph("A bill is due.", _cite("rec-1")), {"rec-1", "rec-2"})


def test_a_paragraph_with_no_citations_is_rejected():
    """An uncited sentence about someone's money is an opinion."""
    with pytest.raises(UncitedParagraphError):
        assert_paragraph_cited(_paragraph("Things look calm."), {"rec-1"})


def test_a_paragraph_citing_an_id_the_run_never_emitted_is_rejected():
    with pytest.raises(UncitedParagraphError):
        assert_paragraph_cited(_paragraph("A bill is due.", _cite("rec-9")), {"rec-1"})


def test_one_bad_citation_among_good_ones_still_rejects_the_paragraph():
    """Partial evidence is not evidence: the sentence rests on all of them."""
    with pytest.raises(UncitedParagraphError):
        assert_paragraph_cited(
            _paragraph("Two bills are due.", _cite("rec-1"), _cite("rec-9")),
            {"rec-1"},
        )


def test_a_paragraph_resting_only_on_orientation_is_rejected():
    """§3.2: orientation is comprehension, not evidence.

    Tested with the orientation id *present* in the emitted set — the natural
    case (orientation rows carry no id) is already covered by the id-membership
    rule, and this pins the rule that would survive orientation gaining one.
    """
    with pytest.raises(UncitedParagraphError):
        assert_paragraph_cited(
            _paragraph("ATLAS watches your invoices.", _cite("o-1", "orientation", "orientation")),
            {"o-1"},
        )


def test_orientation_alongside_real_evidence_is_allowed():
    """The rule is "not *only* orientation" — background beside a fact is fine."""
    assert_paragraph_cited(
        _paragraph(
            "ATLAS watches your invoices, and one needs you.",
            _cite("o-1", "orientation", "orientation"),
            _cite("rec-1"),
        ),
        {"o-1", "rec-1"},
    )


# ═════════════════════════════════════════════════════════════════════════════
# 2. assert_briefing_no_undeclared_numbers
# ═════════════════════════════════════════════════════════════════════════════

def test_a_figure_copied_from_a_tool_row_passes():
    assert_briefing_no_undeclared_numbers(
        _paragraph("One invoice is 2,41,300.00 and it is due."), {"2,41,300.00"}
    )


def test_a_number_no_tool_rendered_is_rejected():
    with pytest.raises(InventedNumberError):
        assert_briefing_no_undeclared_numbers(
            _paragraph("Together they come to 5,00,000.00."), {"2,41,300.00"}
        )


def test_a_rounded_figure_is_rejected_even_though_it_reads_well():
    """The exact failure the line-level rule was written for, on model prose."""
    with pytest.raises(InventedNumberError):
        assert_briefing_no_undeclared_numbers(
            _paragraph("About 2.4 lakh is outstanding."), {"2,41,300.00"}
        )


def test_a_bare_count_is_also_checked_here():
    """Stricter than the line-level rule, deliberately.

    A skill that writes "12 days late" derived the 12 in code. A model that
    writes "3 invoices" may have counted the rows itself, which is arithmetic,
    so the count has to come from a row too.
    """
    with pytest.raises(InventedNumberError):
        assert_briefing_no_undeclared_numbers(_paragraph("There are 3 invoices."), set())
    assert_briefing_no_undeclared_numbers(_paragraph("There are 3 invoices."), {"3"})


def test_prose_with_no_numbers_needs_no_declaration():
    assert_briefing_no_undeclared_numbers(_paragraph("This vendor is new to you."), set())


# ═════════════════════════════════════════════════════════════════════════════
# 3. rendered_tokens_of — what counts as "a tool rendered it"
# ═════════════════════════════════════════════════════════════════════════════

def test_nested_figures_are_collected_not_just_top_level_fields():
    """The amounts live inside `figures`; a flat pass would miss every one."""
    row = {
        "record_kind": "recommendation",
        "record_id": "rec-1",
        "headline": "One invoice needs you",
        "figures": [{"rendered": "2,41,300.00", "currency": "INR"}],
        "payable_count": 3,
    }
    tokens = rendered_tokens_of(row)
    assert "2,41,300.00" in tokens
    assert "3" in tokens


def test_ids_and_timestamps_do_not_declare_numbers():
    """BE Gap 704's lesson: a rule satisfiable by noise is not a rule.

    A UUID is full of digit runs. If those counted, a model could state almost
    any short number and have it pass.
    """
    row = {
        "record_kind": "action",
        "record_id": str(uuid4()),
        "invoice_id": "11112222-3333-4444-5555-666677778888",
        "as_of": TODAY.isoformat(),
        "summary": "Resolved from the work screen.",
    }
    assert rendered_tokens_of(row) == set()


def test_decimals_and_booleans_are_handled():
    tokens = rendered_tokens_of({"amount": Decimal("1200.50"), "agrees": True})
    assert tokens == {"1200.50"}


# ═════════════════════════════════════════════════════════════════════════════
# 4. Structure, the question, and the single entry point
# ═════════════════════════════════════════════════════════════════════════════

def test_a_data_structure_in_a_sentence_is_rejected():
    with pytest.raises(StructureInProseError):
        assert_paragraph_no_structure(
            _paragraph("The alert says {'field': 'grand_total'} which is wrong.")
        )


def test_a_question_goes_through_exactly_the_same_guards():
    """§3.1 step 6: a question that invents a number is no better than a sentence."""
    question = BriefingQuestion(
        text="Does this vendor usually bill 2,41,300.00?",
        citations=[_cite("rec-1")],
    )
    validate_briefing_paragraph(question, {"rec-1"}, {"2,41,300.00"})

    with pytest.raises(InventedNumberError):
        validate_briefing_paragraph(question, {"rec-1"}, set())
    with pytest.raises(UncitedParagraphError):
        validate_briefing_paragraph(
            BriefingQuestion(text="Is this right?"), {"rec-1"}, set()
        )


def test_the_entry_point_reports_the_citation_failure_first():
    """A paragraph that is both uncited and invented is uncited, first.

    Order is the difference between an operator being told the fundamental
    problem and being told its shadow.
    """
    with pytest.raises(UncitedParagraphError):
        validate_briefing_paragraph(_paragraph("It totals 5,00,000.00."), set(), set())


def test_the_event_type_set_is_closed():
    """§3.3: six event types, and nothing else reaches the wire."""
    for kind in ("welcome", "paragraph", "question", "truncated", "error", "done"):
        assert BriefingEvent(type=kind, data={}).type == kind
    with pytest.raises(Exception):
        BriefingEvent(type="advice", data={})


# ═════════════════════════════════════════════════════════════════════════════
# 5. The set the guards test against, built by a real tool on real Postgres
# ═════════════════════════════════════════════════════════════════════════════

@pytest.fixture(scope="module")
def pg_session():
    session = open_session()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def pg(pg_session):
    tag = unique_tag()
    tenant = Tenant(name=f"atlas-guard-{tag}", domain=f"atlas-guard-{tag}.test")
    pg_session.add(tenant)
    pg_session.commit()
    pg_session.refresh(tenant)
    written: list = []
    try:
        yield pg_session, tenant, written
    finally:
        pg_session.rollback()
        for row in written:
            pg_session.delete(row)
        pg_session.commit()
        pg_session.delete(tenant)
        pg_session.commit()


@postgres_only
def test_a_real_tool_run_declares_the_figures_its_rows_rendered(pg):
    """The two sets the guards use are populated by `run_tool()`, not by a test.

    Whatever this tenant's lines say, a paragraph that copies one of their
    rendered figures and cites one of their ids must pass, and the same
    paragraph with a digit added to the figure must not. That is the whole
    contract, stated without naming a single expected number.
    """
    session, tenant, written = pg
    vendor = "Vendor " + uuid4().hex[:6].translate(str.maketrans("0123456789", "abcdefghij"))
    invoice = Invoice(
        tenant_id=tenant.id, file_path=f"tests/{uuid4().hex}.pdf",
        status="AUDIT_REQUIRED", flow_direction="INBOUND", currency="INR",
        vendor_name=vendor, invoice_number=uuid4().hex[:8],
        grand_total=50000.0, due_date=TODAY + timedelta(days=4),
    )
    session.add(invoice)
    written.append(invoice)
    session.commit()

    ctx = ToolContext(
        db=session,
        skill=SkillContext(
            tenant_id=tenant.id, today=TODAY, now=datetime(2026, 9, 18, 9, 0, 0)
        ),
        grants=ADMIN,
        user_id="user-" + uuid4().hex[:8],
    )
    run = BriefingRun(tenant_id=tenant.id, user_id=ctx.user_id)
    rows = run_tool("list_lines", {}, ctx, run).rows
    assert rows, "the fixture produced no lines — the property would be vacuous"

    rendered = next(
        (f["rendered"] for row in rows for f in row.get("figures") or []), None
    )
    assert rendered, "no line rendered a figure — the property would be vacuous"
    assert rendered in run.rendered_tokens or any(
        tok in run.rendered_tokens for tok in rendered.split()
    )

    cited = _cite(next(iter(run.emitted_ids)))
    good = _paragraph("One invoice shows " + rendered + " and needs you.", cited)
    validate_briefing_paragraph(good, run.emitted_ids, run.rendered_tokens)

    invented = _paragraph("One invoice shows " + rendered + "9 and needs you.", cited)
    with pytest.raises(InventedNumberError):
        validate_briefing_paragraph(invented, run.emitted_ids, run.rendered_tokens)


@postgres_only
def test_a_refused_tool_call_declares_nothing(pg):
    """A refusal explains; it does not license a number or an id.

    Without this, a model could ask for a tool it cannot have and cite the
    refusal's own prose as evidence.
    """
    session, tenant, written = pg
    ctx = ToolContext(
        db=session,
        skill=SkillContext(
            tenant_id=tenant.id, today=TODAY, now=datetime(2026, 9, 18, 9, 0, 0)
        ),
        grants=GrantSet(can_train=True),
        user_id="user-" + uuid4().hex[:8],
    )
    run = BriefingRun(tenant_id=tenant.id, user_id=ctx.user_id)
    result = run_tool("cash_position", {}, ctx, run)

    assert result.refused
    assert run.emitted_ids == set()
    assert run.rendered_tokens == set()
