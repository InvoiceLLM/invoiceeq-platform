"""Feature 34 (ATLAS) task 34.3 — the Auditor, Trainer and Loader skill sets.

Spec: `docs/feature_34_atlas.md` §2.3, §3.1, §11 · decisions D43, D44, D45.

Every test here writes real rows to the dev Postgres, reads them back through
the skills, and deletes them again (hard rule 2 -- a SQLite run is not
evidence). The three rulings Slice B added are each asserted directly:

* the Auditor's lines carry the **full cash position, forecast and runway**
  (D44) and declare `AUDIT`, so an Auditor sees them -- the whole of that
  reversal of D2 is the capability on the line;
* a Trainer's correction line carries the invoice **before and after** the fix
  (D45), and the "after" is held to the same number rules as the prose;
* the Loader's lines are **per ingestion source** (D43) -- asserted in
  `tests/test_atlas_ingestion_sources.py`, which is kept separate because every
  Loader query reads `tenant_autopilot_logs.source_config_id` and that column
  does not exist on the dev Postgres until task 34.13's migration runs. See BE
  Gap 698.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest

from models import Invoice, Tenant
from services.atlas_capabilities import AtlasCapability, GrantSet, visible_to
from services.atlas_contract import (
    InventedNumberError,
    assert_no_undeclared_numbers,
    validate_recommendation,
)
from services.atlas_skills import (
    SkillContext,
    auditor_lines,
    cash_position,
    trainer_lines,
)
from tests.atlas_pg import open_session, postgres_only, unique_tag

TODAY = date(2026, 9, 17)


# ═════════════════════════════════════════════════════════════════════════════
# Fixture — one throwaway tenant per module, every row of it deleted afterwards
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
    """A **fresh tenant per test**, and every row it writes deleted afterwards.

    Per test rather than per module on purpose: these skills read *everything*
    the tenant has, so one test's invoice is another test's cash position. A
    shared tenant makes each test's assertion depend on which tests ran before
    it, which is how a suite starts passing for the wrong reason.
    """
    tag = unique_tag()
    tenant = Tenant(name=f"atlas-skills-{tag}", domain=f"atlas-skills-{tag}.test")
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


def _ctx(tenant, **overrides) -> SkillContext:
    base = dict(
        tenant_id=tenant.id,
        today=TODAY,
        now=datetime(2026, 9, 17, 12, 0, 0),
    )
    base.update(overrides)
    return SkillContext(**base)


def _invoice(session, written, tenant, **fields) -> Invoice:
    defaults = dict(
        tenant_id=tenant.id,
        file_path=f"tests/{uuid4().hex}.pdf",
        status="AUDIT_REQUIRED",
        flow_direction="INBOUND",
        currency="INR",
    )
    defaults.update(fields)
    inv = Invoice(**defaults)
    session.add(inv)
    session.commit()
    session.refresh(inv)
    written.append(inv)
    return inv


# ═════════════════════════════════════════════════════════════════════════════
# The Auditor (§2.3, D44)
# ═════════════════════════════════════════════════════════════════════════════

@postgres_only
def test_an_invoice_awaiting_a_decision_becomes_one_audit_line(pg):
    session, tenant, written = pg
    inv = _invoice(
        session, written, tenant,
        vendor_name="Kumar Supplies",
        invoice_number="1041",
        grand_total=241300.0,
        due_date=TODAY + timedelta(days=3),
    )
    lines = [
        line for line in auditor_lines(session, _ctx(tenant))
        if line.what.entity_id == str(inv.id)
    ]
    assert len(lines) == 1
    line = lines[0]
    assert line.capability is AtlasCapability.AUDIT
    assert line.action.kind == "resolve_invoice"
    # §5.3: the exact number, never a rounded one.
    assert "2,41,300.00" in line.why.text
    assert "2.4" not in line.why.text


@postgres_only
def test_the_auditor_sees_the_full_position_forecast_and_runway(pg):
    """D44, and the reversal of D2 for this role.

    The cash line declares `AUDIT`, so a user holding only `can_audit` receives
    it. Before this ruling it would have declared `ADMIN` and been dropped by
    `visible_to()` for exactly that user.
    """
    session, tenant, written = pg
    _invoice(
        session, written, tenant,
        vendor_name="Shree Packaging", invoice_number="7001",
        grand_total=50000.0, due_date=TODAY + timedelta(days=5),
    )
    _invoice(
        session, written, tenant,
        vendor_name="A Customer", invoice_number="OUT-1",
        grand_total=80000.0, due_date=TODAY + timedelta(days=10),
        status="SENT", flow_direction="OUTBOUND",
    )

    positions = cash_position(session, _ctx(tenant))
    assert [p.currency for p in positions] == ["INR"]
    position = positions[0]
    assert position.payable_due == Decimal("50000.00")
    assert position.receivable_due == Decimal("80000.00")
    assert position.assumption  # §7.5: the forecast states its assumption

    cash = [
        line for line in auditor_lines(session, _ctx(tenant))
        if line.skill == "cash_position_and_runway"
    ]
    assert len(cash) == 1
    assert cash[0].capability is AtlasCapability.AUDIT

    auditor = GrantSet(can_audit=True)
    assert [line.id for line in visible_to(cash, auditor)] == [cash[0].id]
    # And a Loader, who holds no audit grant, never sees it.
    assert visible_to(cash, GrantSet(can_load=True)) == []
    # Nor does a Trainer. D44 widened the audience by exactly one grant.
    assert visible_to(cash, GrantSet(can_train=True)) == []


@postgres_only
def test_the_cash_line_never_blends_currencies(pg):
    """§7.4 / D32: one position per currency, never one total."""
    session, tenant, written = pg
    _invoice(
        session, written, tenant, vendor_name="A Rupee Vendor",
        invoice_number="INR-1", grand_total=10000.0, currency="INR",
        due_date=TODAY + timedelta(days=2),
    )
    _invoice(
        session, written, tenant, vendor_name="A Dollar Vendor",
        invoice_number="USD-1", grand_total=500.0, currency="USD",
        due_date=TODAY + timedelta(days=2),
    )
    positions = {p.currency: p for p in cash_position(session, _ctx(tenant))}
    assert set(positions) == {"INR", "USD"}
    assert positions["INR"].payable_due == Decimal("10000.00")
    assert positions["USD"].payable_due == Decimal("500.00")
    for line in auditor_lines(session, _ctx(tenant)):
        # Contract-level check, run again here because the skill is the thing
        # that could have assembled a mixed line in the first place.
        validate_recommendation(line)


# ═════════════════════════════════════════════════════════════════════════════
# The Trainer (§2.3, D21, D45)
# ═════════════════════════════════════════════════════════════════════════════

@postgres_only
def test_a_correction_line_shows_the_invoice_before_and_after(pg):
    """D45 — the concrete form of D21's "proof the teaching worked"."""
    session, tenant, written = pg
    inv = _invoice(
        session, written, tenant,
        vendor_name="Bad Arithmetic Ltd", invoice_number="9001",
        grand_total=9000.0, tax_amount=0.0,
        items=[{"total": 4000}, {"total": 4500}],
    )
    lines = [
        line for line in trainer_lines(session, _ctx(tenant))
        if line.what.entity_id == str(inv.id)
        and line.skill == "invoice_total_disagrees_with_its_items"
    ]
    assert len(lines) == 1
    line = lines[0]
    assert line.capability is AtlasCapability.TRAIN
    assert line.correction is not None
    assert line.correction.field_name == "grand_total"
    assert line.correction.before_rendered == "9,000.00"
    assert line.correction.after_rendered == "8,500.00"
    # Both halves of the pair are prose the user reads, so both are covered by
    # the §5.3 number checks.
    assert line.correction.before_rendered in " ".join(line.prose())
    assert line.correction.after_rendered in " ".join(line.prose())


@postgres_only
def test_a_rounded_after_value_is_rejected_like_any_other_invented_number(pg):
    """The `Correction` block is not a hole in §5.3.

    A correction whose "after" does not match the figure the line declares is
    refused -- and this is the worst place for a rounded number to reach, because
    the "after" is the value the click writes.
    """
    session, tenant, written = pg
    inv = _invoice(
        session, written, tenant,
        vendor_name="Bad Arithmetic Ltd", invoice_number="9002",
        grand_total=9000.0, tax_amount=0.0,
        items=[{"total": 4000}, {"total": 4500}],
    )
    line = next(
        line for line in trainer_lines(session, _ctx(tenant))
        if line.what.entity_id == str(inv.id) and line.correction is not None
    )
    rounded = line.model_copy(
        update={"correction": line.correction.model_copy(update={"after_rendered": "8,500.99"})}
    )
    with pytest.raises(InventedNumberError):
        assert_no_undeclared_numbers(rounded)


@postgres_only
def test_a_field_with_no_computable_fix_carries_no_before_after(pg):
    """An "after" ATLAS cannot compute is one it must not print."""
    session, tenant, written = pg
    inv = _invoice(
        session, written, tenant,
        vendor_name="Blurry Scan Co", invoice_number="9100",
        grand_total=1200.0,
        field_confidence={"vendor_name": 0.41, "invoice_number": 0.55},
    )
    line = next(
        line for line in trainer_lines(session, _ctx(tenant))
        if line.what.entity_id == str(inv.id) and line.skill == "low_confidence_fields"
    )
    assert line.correction is None
    assert line.certainty.value == "uncertain"
    assert line.why.doubt  # §5.1: the doubt is in words


# ═════════════════════════════════════════════════════════════════════════════
# The three together (§2.1)
# ═════════════════════════════════════════════════════════════════════════════

@postgres_only
def test_a_user_with_no_grants_receives_zero_lines_from_the_skills(pg):
    """§11's first invariant, now against lines a skill actually emitted."""
    session, tenant, written = pg
    _invoice(
        session, written, tenant, vendor_name="Anyone", invoice_number="1",
        grand_total=1000.0, due_date=TODAY,
        field_confidence={"vendor_name": 0.3},
    )
    emitted = auditor_lines(session, _ctx(tenant)) + trainer_lines(session, _ctx(tenant))
    assert emitted, "the fixture must produce lines, or this proves nothing"
    assert visible_to(emitted, GrantSet()) == []


@postgres_only
def test_every_line_every_skill_emits_passes_the_whole_contract(pg):
    """The seam test: no skill may emit a line the contract would refuse.

    `validate_recommendation` is already called inside each emitter, so this
    asserts that it is called on **every** path rather than on the ones the other
    tests happen to walk.
    """
    session, tenant, written = pg
    _invoice(
        session, written, tenant, vendor_name="Everything Co", invoice_number="4242",
        grand_total=12345.67, due_date=TODAY + timedelta(days=1),
        items=[{"total": 1000}], field_confidence={"tax_amount": 0.2},
        sa_alerts=["Possible duplicate of #4241"],
    )
    emitted = auditor_lines(session, _ctx(tenant)) + trainer_lines(session, _ctx(tenant))
    lines = visible_to(emitted, GrantSet(is_admin=True))
    assert lines == emitted, "the admin is the superset and should see every line type"
    for line in lines:
        validate_recommendation(line)
        assert line.what.headline and line.why.text
        assert line.action.label and line.verify.question
        # D42: nothing is batchable in v1 by ruling; the contract's own rule is
        # what this asserts -- an uncertain or irreversible line never batches.
        if line.batchable:
            assert line.certainty.value == "certain"
            assert line.reversibility.value == "reversible"
