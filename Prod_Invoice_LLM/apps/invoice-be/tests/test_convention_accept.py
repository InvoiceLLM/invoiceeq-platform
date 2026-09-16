"""Tests for GAP-03: Real suggested_rule persistence and custom body support in convention accept."""
from uuid import uuid4
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, create_engine, select
from sqlmodel.pool import StaticPool

from routers.today import router as today_router
from dependencies import get_db_session, get_tenant_context, TenantContext
from models import TenantChatRule
from services.chat_rules import render_chat_rule


@pytest.fixture
def test_db():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


def build_test_client(db_session, role="Admin", clearance="exec"):
    app = FastAPI()
    app.include_router(today_router)

    tenant_id = uuid4()

    def override_get_db():
        return db_session

    def override_tenant_context():
        return TenantContext(
            tenant_id=tenant_id,
            user_id="test_admin_user",
            role=role,
            clearance=clearance,
            billing_plan="free",
            is_authenticated=True,
            can_edit=True,
            can_train=True,
        )

    app.dependency_overrides[get_db_session] = override_get_db
    app.dependency_overrides[get_tenant_context] = override_tenant_context
    client = TestClient(app)
    return client, tenant_id


def test_accept_convention_resolves_real_suggested_rule_without_body(test_db):
    client, tenant_id = build_test_client(test_db)

    # Calling accept without body on auto_apply_credit_notes
    resp = client.post("/today/auto_apply_credit_notes/accept")
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    # Must NOT be the old placeholder "Convention rule for auto_apply_credit_notes"
    assert "Convention rule for" not in data["rule_text"]
    assert "credit note" in data["rule_text"].lower()

    # Verify persisted TenantChatRule
    rules = test_db.exec(
        select(TenantChatRule).where(TenantChatRule.tenant_id == tenant_id)
    ).all()
    assert len(rules) == 1
    assert rules[0].source == "atlas"
    assert "credit note" in rules[0].pattern.lower()
    assert rules[0].category == "auto_apply_credit_notes"


def test_accept_convention_with_explicit_rule_text_in_body(test_db):
    client, tenant_id = build_test_client(test_db)

    custom_rule = "Always apply 2% early payment discount for Acme if paid within 10 days."
    resp = client.post(
        "/today/prop-custom-123/accept",
        json={"rule_text": custom_rule, "title": "Acme Discount Convention"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["rule_text"] == custom_rule

    rules = test_db.exec(
        select(TenantChatRule).where(TenantChatRule.tenant_id == tenant_id)
    ).all()
    assert len(rules) == 1
    assert rules[0].pattern == custom_rule
    assert rules[0].context_text == "Acme Discount Convention"
    assert rules[0].source == "atlas"


def test_edit_convention_route_stores_edited_rule(test_db):
    client, tenant_id = build_test_client(test_db)

    edited_rule = "Edited rule text for NET 45 vendor terms."
    resp = client.post(
        "/today/default_terms/edit",
        json={"rule_text": edited_rule, "target": "tenant_chat_rule"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["rule_text"] == edited_rule

    rules = test_db.exec(
        select(TenantChatRule).where(TenantChatRule.tenant_id == tenant_id)
    ).all()
    assert len(rules) == 1
    assert rules[0].pattern == edited_rule
    assert rules[0].source == "atlas"


def test_render_chat_rule_renders_convention_pattern():
    rendered = render_chat_rule("auto_apply_credit_notes", "Pay Acme 2% in 10 days", "Context")
    assert rendered == "Pay Acme 2% in 10 days"

    rendered_empty = render_chat_rule("auto_apply_credit_notes", "", "Fallback Title")
    assert rendered_empty == "Fallback Title"
