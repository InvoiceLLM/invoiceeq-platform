"""Tests for services/extraction_quality_rollup.py (Feature 23, 2026-08-23)."""
from datetime import datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from models import AuditLog
from services.extraction_quality_rollup import (
    alert_precision_rollup,
    field_correction_rollup,
)


@pytest.fixture
def db_session():
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    SQLModel.metadata.create_all(engine)
    session = Session(engine)
    yield session
    session.close()


def _resolve_log(tenant_id, action="RESOLVE_INVOICE", details=None, timestamp=None):
    return AuditLog(
        tenant_id=tenant_id,
        invoice_id=uuid4(),
        actor_user_id=uuid4(),
        actor_role="Admin",
        action=action,
        details=details or {},
        timestamp=timestamp or datetime.utcnow(),
    )


def test_field_correction_rollup_counts_only_corrected_fields(db_session):
    tenant_id = uuid4()
    db_session.add_all(
        [
            _resolve_log(tenant_id, details={"corrections": {"grand_total": {"old": 100, "new": 120}}}),
            _resolve_log(tenant_id, details={"corrections": {"grand_total": {"old": 50, "new": 55}, "vendor_name": {"old": "A", "new": "B"}}}),
            _resolve_log(tenant_id, details={"corrections": {}}),  # resolved clean, no correction
        ]
    )
    db_session.commit()

    rollup = field_correction_rollup(db_session, tenant_id)
    by_field = {r["field"]: r for r in rollup}

    assert by_field["grand_total"]["correction_count"] == 2
    assert by_field["grand_total"]["total_resolves"] == 3
    assert by_field["grand_total"]["correction_rate"] == round(2 / 3, 4)
    assert by_field["vendor_name"]["correction_count"] == 1


def test_field_correction_rollup_respects_since_window(db_session):
    tenant_id = uuid4()
    old = datetime.utcnow() - timedelta(days=30)
    recent = datetime.utcnow()
    db_session.add_all(
        [
            _resolve_log(tenant_id, details={"corrections": {"grand_total": {"old": 1, "new": 2}}}, timestamp=old),
            _resolve_log(tenant_id, details={"corrections": {"grand_total": {"old": 3, "new": 4}}}, timestamp=recent),
        ]
    )
    db_session.commit()

    rollup = field_correction_rollup(db_session, tenant_id, since=recent - timedelta(hours=1))
    assert len(rollup) == 1
    assert rollup[0]["correction_count"] == 1
    assert rollup[0]["total_resolves"] == 1


def test_field_correction_rollup_empty_window_returns_no_rate_not_crash(db_session):
    tenant_id = uuid4()
    rollup = field_correction_rollup(db_session, tenant_id)
    assert rollup == []


def test_alert_precision_distinguishes_corrected_from_uncorrected_dismissal(db_session):
    tenant_id = uuid4()
    # Dismissed WITH a matching field correction -> true positive
    db_session.add(
        _resolve_log(
            tenant_id,
            details={
                "previous_alerts": [{"type": "tax_amount_not_verified_in_source", "message": "m1", "field": "tax_amount"}],
                "dismissed_alerts_input": ["tax_amount_not_verified_in_source"],
                "corrections": {"tax_amount": {"old": 100, "new": 118}},
            },
        )
    )
    # Dismissed with NO correction -> likely false positive
    db_session.add(
        _resolve_log(
            tenant_id,
            details={
                "previous_alerts": [{"type": "tax_amount_not_verified_in_source", "message": "m2", "field": "tax_amount"}],
                "dismissed_alerts_input": ["tax_amount_not_verified_in_source"],
                "corrections": {},
            },
        )
    )
    # Not dismissed at all (still open) -> excluded from precision entirely
    db_session.add(
        _resolve_log(
            tenant_id,
            action="REOPEN_INVOICE",
            details={
                "previous_alerts": [{"type": "tax_amount_not_verified_in_source", "message": "m3", "field": "tax_amount"}],
                "dismissed_alerts_input": [],
                "corrections": {},
            },
        )
    )
    db_session.commit()

    rollup = alert_precision_rollup(db_session, tenant_id)
    assert len(rollup) == 1
    row = rollup[0]
    assert row["alert_type"] == "tax_amount_not_verified_in_source"
    assert row["dismissed_with_correction"] == 1
    assert row["dismissed_without_correction"] == 1
    assert row["total_dismissed"] == 2
    assert row["precision"] == pytest.approx(0.5)


def test_alert_precision_matches_by_type_when_id_and_message_absent(db_session):
    tenant_id = uuid4()
    db_session.add(
        _resolve_log(
            tenant_id,
            details={
                "previous_alerts": [{"type": "missing_required_field", "message": "customer_name missing"}],
                "dismissed_alerts_input": ["missing_required_field"],
                "corrections": {"customer_name": {"old": None, "new": "Acme"}},
            },
        )
    )
    db_session.commit()

    rollup = alert_precision_rollup(db_session, tenant_id)
    assert rollup[0]["alert_type"] == "missing_required_field"
    # No "field" key on the alert itself -> can't confirm the correction link,
    # so it's counted as uncorrected rather than assumed matched.
    assert rollup[0]["dismissed_without_correction"] == 1
    assert rollup[0]["dismissed_with_correction"] == 0


def test_alert_precision_ignores_other_tenants(db_session):
    tenant_a, tenant_b = uuid4(), uuid4()
    db_session.add(
        _resolve_log(
            tenant_b,
            details={
                "previous_alerts": [{"type": "x", "message": "m", "field": "f"}],
                "dismissed_alerts_input": ["x"],
                "corrections": {"f": {"old": 1, "new": 2}},
            },
        )
    )
    db_session.commit()

    assert alert_precision_rollup(db_session, tenant_a) == []
    assert field_correction_rollup(db_session, tenant_a) == []
