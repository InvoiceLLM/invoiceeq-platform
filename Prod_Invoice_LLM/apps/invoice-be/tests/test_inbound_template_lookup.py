"""BE Gap 568: inbound extraction and the Trainer read INBOUND templates only.

Since Feature 7.1 a tenant can hold one Global template (`vendor_name IS NULL`) per direction.
`queue_worker/handlers.py::_get_template_rules` and `routers/trainer.py::_get_template` asked only for
`vendor_name IS NULL`, so a tenant whose only Global template was OUTBOUND had those rules applied to
inbound extraction and shown as the Trainer's Global context.
"""
from uuid import uuid4

import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from models import ExtractionTemplate
from queue_worker.handlers import _get_template_rules
from routers.trainer import _get_template, _global_constraints


@pytest.fixture
def session():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    with Session(engine) as db_session:
        yield db_session


def _add_template(session, tenant_id, flow_direction, rule, vendor_name=None):
    session.add(ExtractionTemplate(
        tenant_id=tenant_id, vendor_name=vendor_name, flow_direction=flow_direction, rules={"constraints": [rule]},
    ))
    session.commit()


def test_an_outbound_only_tenant_has_no_inbound_global_rules(session):
    tenant_id = uuid4()
    _add_template(session, tenant_id, "OUTBOUND", "OUTBOUND-only rule")

    assert _get_template_rules(session, str(tenant_id), None) == []
    assert _get_template(session, tenant_id, None) is None
    assert _global_constraints(session, tenant_id) == []


def test_the_inbound_global_template_is_used_whichever_row_was_written_first(session):
    tenant_id = uuid4()
    _add_template(session, tenant_id, "OUTBOUND", "OUTBOUND-only rule")
    _add_template(session, tenant_id, "INBOUND", "INBOUND Global rule")

    assert _get_template_rules(session, str(tenant_id), None) == ["INBOUND Global rule"]
    assert _get_template(session, tenant_id, None).flow_direction == "INBOUND"
    assert _global_constraints(session, tenant_id) == ["INBOUND Global rule"]


def test_vendor_templates_are_found_as_before(session):
    tenant_id = uuid4()
    _add_template(session, tenant_id, "INBOUND", "ACME rule", vendor_name="ACME Corp")

    assert _get_template_rules(session, str(tenant_id), "ACME Corp") == ["ACME rule"]
    assert _get_template(session, tenant_id, "ACME Corp").rules == {"constraints": ["ACME rule"]}
