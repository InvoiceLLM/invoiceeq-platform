"""Feature 18: the chat-correction lane.

Structurally separate from the extraction lane, and these tests assert that
separation explicitly (`TenantChatRule` writes must never touch
`ExtractionTemplate.rules["constraints"]`), because the whole reason the two are
split is that "the trainer taught chat something odd" and "the trainer taught
extraction something odd" had become the same undiagnosable class of bug.

Covers:
  * the result-set snapshot (Gap 231) that makes the wrong-data triage possible
  * the auto-diff and its two outcomes, including the redirect out of chat and
    into the extraction flow when the PDF disagrees with the stored data
  * chat style moving off the Global ExtractionTemplate row (Gap 230)
  * `_chat_rules_block()` sitting next to, never inside, `_business_rules_block()`
"""
import pytest
from unittest.mock import patch
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlmodel import SQLModel, create_engine, Session, select
from sqlalchemy.pool import StaticPool

from main import app
from dependencies import get_db_session, MOCK_TENANT_ID
from models import (
    ChatFeedback,
    ChatMessage,
    ChatSession,
    ExtractionTemplate,
    Invoice,
    TenantChatRule,
    TenantChatSettings,
)

engine = create_engine(
    "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
)
client = TestClient(app)


@pytest.fixture(name="db_session")
def db_session_fixture():
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    SQLModel.metadata.drop_all(engine)


@pytest.fixture(autouse=True)
def override_db_session(db_session):
    def _override():
        yield db_session
    app.dependency_overrides[get_db_session] = _override
    yield
    app.dependency_overrides.clear()


@pytest.fixture(autouse=True)
def no_redis():
    """The chat-rule commit flushes the answer cache best-effort; stub Redis so a
    missing local server doesn't make these tests depend on the environment."""
    with patch("redis.Redis.from_url") as m:
        m.return_value.keys.return_value = []
        yield m


def _seed_thread(db_session, content="ACME billed you 110.0 in total.", invoice_ids=None):
    chat_session = ChatSession(id=uuid4(), tenant_id=MOCK_TENANT_ID, title="T")
    db_session.add(chat_session)
    message = ChatMessage(
        id=uuid4(), session_id=chat_session.id, role="assistant", content=content,
        result_invoice_ids=[str(i) for i in (invoice_ids or [])],
    )
    db_session.add(message)
    db_session.commit()
    return chat_session, message


def _seed_invoice(db_session, **overrides):
    defaults = dict(
        id=uuid4(), tenant_id=MOCK_TENANT_ID, file_path="blob/acme.pdf", status="COMPLETED",
        vendor_name="ACME Corporation", invoice_number="INV-9", grand_total=110.0,
        currency="USD", flow_direction="INBOUND",
    )
    defaults.update(overrides)
    invoice = Invoice(**defaults)
    db_session.add(invoice)
    db_session.commit()
    return invoice


# ── Result-set snapshot (Gap 231) ────────────────────────────────────────────

# SQLAlchemy's `Uuid` type stores UUIDs as native `uuid` on PostgreSQL (where a
# `tenant_id = '<dashed uuid>'` literal matches) but as 32-char dashless hex on
# SQLite, which these tests run on. That is a storage-format difference in the
# test engine, not a product behaviour -- the same class of thing
# `query_agent._get_tenant_stats_summary()` already documents in its own comment.
# So the SQL below carries BOTH forms: the dashed one satisfies the tenant
# isolation predicate the production safety check requires, and the hex one is
# what actually matches a row under SQLite.
_TENANT_HEX = MOCK_TENANT_ID.hex


def _tenant_predicate() -> str:
    return f"tenant_id = '{MOCK_TENANT_ID}' OR tenant_id = '{_TENANT_HEX}'"


def test_sql_route_captures_invoice_ids_when_the_query_selected_them(db_session):
    from agents.query_agent import execute_generated_sql

    invoice = _seed_invoice(db_session)
    snapshot = []
    execute_generated_sql(
        f"SELECT id, grand_total FROM invoice WHERE {_tenant_predicate()}",
        str(MOCK_TENANT_ID), db_session, snapshot=snapshot,
    )
    assert snapshot == [str(invoice.id)]


def test_snapshot_is_empty_when_the_query_selected_no_identity(db_session):
    """An aggregate SELECT has no id column, so the row-level harvest finds
    nothing -- which is precisely why the companion query below exists."""
    from agents.query_agent import execute_generated_sql

    _seed_invoice(db_session)
    snapshot = []
    execute_generated_sql(
        f"SELECT SUM(grand_total) FROM invoice WHERE {_tenant_predicate()}",
        str(MOCK_TENANT_ID), db_session, snapshot=snapshot,
    )
    assert snapshot == []


def test_aggregate_query_recovers_its_row_set_via_the_companion_query(db_session):
    """A `SELECT SUM(...)` selects no id at all — which is exactly the case the
    triage picker needs, and exactly the case the old code left with nothing."""
    from agents.query_agent import _harvest_invoice_ids_via_companion_query

    a = _seed_invoice(db_session, invoice_number="A")
    b = _seed_invoice(db_session, invoice_number="B")
    ids = _harvest_invoice_ids_via_companion_query(
        f"SELECT SUM(grand_total) FROM invoice WHERE {_tenant_predicate()}",
        str(MOCK_TENANT_ID), db_session,
    )
    assert set(ids) == {str(a.id), str(b.id)}


def test_companion_query_refuses_sql_it_cannot_safely_rebuild(db_session):
    """Best-effort means returning nothing, never guessing or widening scope."""
    from agents.query_agent import _harvest_invoice_ids_via_companion_query

    _seed_invoice(db_session)
    # No tenant predicate in the rebuilt tail -> refuse.
    assert _harvest_invoice_ids_via_companion_query(
        "SELECT SUM(grand_total) FROM invoice", str(MOCK_TENANT_ID), db_session
    ) == []
    # Subquery -> refuse rather than reconstruct something different.
    assert _harvest_invoice_ids_via_companion_query(
        f"SELECT SUM(grand_total) FROM invoice WHERE {_tenant_predicate()} "
        "AND id IN (SELECT id FROM invoice)",
        str(MOCK_TENANT_ID), db_session,
    ) == []


def test_snapshot_is_persisted_on_the_assistant_message(db_session, monkeypatch):
    # Gap 390: this asserts `200`, which is only true on the synchronous
    # path. With the async queue on the endpoint returns `202 Accepted`.
    # State the path rather than inherit it from whether Redis is running.
    import config

    monkeypatch.setattr(config.settings, "ENABLE_ASYNC_CHAT_QUEUE", False)

    invoice = _seed_invoice(db_session)
    chat_session = ChatSession(id=uuid4(), tenant_id=MOCK_TENANT_ID, title="T")
    db_session.add(chat_session)
    db_session.commit()

    with patch("routers.chat.run_query_agent") as m_agent:
        m_agent.return_value = {
            "content": "Total is $110.00", "generated_sql": "SELECT ...",
            "citations": [], "result_invoice_ids": [str(invoice.id)],
        }
        res = client.post(
            f"/api/v1/chat/sessions/{chat_session.id}/message", json={"content": "total spend"}
        )
    assert res.status_code == 200

    stored = db_session.exec(
        select(ChatMessage).where(ChatMessage.role == "assistant")
    ).first()
    assert stored.result_invoice_ids == [str(invoice.id)]


# ── Thumbs-down triage routing ───────────────────────────────────────────────

def test_feedback_reason_is_persisted_and_routes(db_session):
    invoice = _seed_invoice(db_session)
    _, message = _seed_thread(db_session, invoice_ids=[invoice.id])

    res = client.put(
        f"/api/v1/chat/messages/{message.id}/feedback",
        json={"vote": "down", "reason": "wrong_data", "note": "total looked off"},
    )
    assert res.status_code == 200
    assert res.json()["triage"]["next"] == "diff_invoice"

    row = db_session.exec(select(ChatFeedback)).first()
    assert row.reason == "wrong_data"
    assert row.note == "total looked off"


def test_bad_tone_routes_to_settings_not_a_rule(db_session):
    _, message = _seed_thread(db_session)
    res = client.put(
        f"/api/v1/chat/messages/{message.id}/feedback",
        json={"vote": "down", "reason": "bad_tone"},
    )
    triage = res.json()["triage"]
    assert triage["next"] == "chat_settings"
    assert "chat-style" in triage["settingsEndpoint"]
    assert db_session.exec(select(TenantChatRule)).all() == []


def test_wrong_data_over_many_invoices_asks_the_user_to_pick(db_session):
    ids = [_seed_invoice(db_session, invoice_number=f"I-{i}").id for i in range(3)]
    _, message = _seed_thread(db_session, invoice_ids=ids)

    triage = client.put(
        f"/api/v1/chat/messages/{message.id}/feedback",
        json={"vote": "down", "reason": "wrong_data"},
    ).json()["triage"]
    assert triage["next"] == "pick_invoice"
    assert len(triage["invoices"]) == 3


def test_missing_snapshot_never_claims_no_invoices_were_involved(db_session):
    """An empty snapshot means 'we couldn't tell', not 'no invoices'. Saying the
    latter would be the same class of confident-but-wrong answer this whole
    feature exists to stop."""
    _, message = _seed_thread(db_session, invoice_ids=[])
    triage = client.put(
        f"/api/v1/chat/messages/{message.id}/feedback",
        json={"vote": "down", "reason": "wrong_data"},
    ).json()["triage"]
    assert triage["next"] == "category_pick"
    assert "couldn't determine" in triage["explanation"]


def test_reason_is_rejected_on_a_thumbs_up(db_session):
    _, message = _seed_thread(db_session)
    res = client.put(
        f"/api/v1/chat/messages/{message.id}/feedback",
        json={"vote": "up", "reason": "wrong_data"},
    )
    assert res.status_code == 400


# ── The auto-diff ────────────────────────────────────────────────────────────

def test_diff_mismatch_means_chat_misreported_its_own_data(db_session):
    invoice = _seed_invoice(db_session, grand_total=110.0)
    _, message = _seed_thread(db_session, invoice_ids=[invoice.id])

    res = client.post(
        f"/api/v1/chat/messages/{message.id}/triage",
        json={"invoice_id": str(invoice.id), "field": "grand_total", "claimed_value": "999.99"},
    )
    body = res.json()
    assert body["diff"]["outcome"] == "mismatch"
    assert body["diff"]["storedValue"] == "110.0"
    # Provably a chat bug -> straight to the chat-behaviour rule path.
    assert body["next"] == "category_pick"


def test_diff_match_asks_the_human_to_check_the_pdf(db_session):
    invoice = _seed_invoice(db_session, grand_total=110.0)
    _, message = _seed_thread(db_session, invoice_ids=[invoice.id])

    body = client.post(
        f"/api/v1/chat/messages/{message.id}/triage",
        json={"invoice_id": str(invoice.id), "field": "grand_total", "claimed_value": "110.0"},
    ).json()
    assert body["diff"]["outcome"] == "match"
    assert body["next"] == "confirm_against_pdf"
    assert body["pdfUrl"] == f"/api/invoices/{invoice.id}/pdf"


def test_diff_falls_back_to_containment_when_no_claimed_value_is_supplied(db_session):
    invoice = _seed_invoice(db_session, vendor_name="ACME Corporation")
    _, message = _seed_thread(
        db_session, content="The vendor is ACME Corporation.", invoice_ids=[invoice.id]
    )
    body = client.post(
        f"/api/v1/chat/messages/{message.id}/triage",
        json={"invoice_id": str(invoice.id), "field": "vendor_name"},
    ).json()
    assert body["diff"]["outcome"] == "match"
    # The weaker basis is reported, so nothing mistakes it for an exact comparison.
    assert body["diff"]["basis"] == "reply_contains_stored_value"


def test_diff_rejects_a_field_it_cannot_meaningfully_compare(db_session):
    invoice = _seed_invoice(db_session)
    _, message = _seed_thread(db_session, invoice_ids=[invoice.id])
    res = client.post(
        f"/api/v1/chat/messages/{message.id}/triage",
        json={"invoice_id": str(invoice.id), "field": "items"},
    )
    assert res.status_code == 400


def test_diff_is_tenant_scoped(db_session):
    other = _seed_invoice(db_session, tenant_id=uuid4())
    _, message = _seed_thread(db_session)
    res = client.post(
        f"/api/v1/chat/messages/{message.id}/triage",
        json={"invoice_id": str(other.id), "field": "grand_total"},
    )
    assert res.status_code == 404


# ── The redirect out of chat and into extraction ─────────────────────────────

def test_pdf_disagreeing_redirects_into_the_extraction_flow(db_session):
    """This is the important one: when the stored data is what's wrong, teaching
    the chat agent anything would paper over bad extraction with a rule about how
    to talk about it."""
    invoice = _seed_invoice(db_session)
    _, message = _seed_thread(db_session, invoice_ids=[invoice.id])

    body = client.post(
        f"/api/v1/chat/messages/{message.id}/triage/source-verdict",
        json={"invoice_id": str(invoice.id), "field": "grand_total", "pdf_agrees": False},
    ).json()

    assert body["next"] == "extraction_flag_missed"
    redirect = body["redirect"]
    assert redirect["invoiceId"] == str(invoice.id)
    assert redirect["field"] == "grand_total"
    assert redirect["sessionEndpoint"] == "/api/v1/trainer/sessions/from-invoice"
    assert "flaggable_only=true" in redirect["alertTypesEndpoint"]
    # No chat rule was created on this path.
    assert db_session.exec(select(TenantChatRule)).all() == []


def test_pdf_agreeing_continues_as_a_chat_correction(db_session):
    invoice = _seed_invoice(db_session)
    _, message = _seed_thread(db_session, invoice_ids=[invoice.id])
    body = client.post(
        f"/api/v1/chat/messages/{message.id}/triage/source-verdict",
        json={"invoice_id": str(invoice.id), "field": "grand_total", "pdf_agrees": True},
    ).json()
    assert body["next"] == "category_pick"
    assert body["categories"]


# ── Chat rule preview -> confirm -> commit ───────────────────────────────────

def test_chat_rule_requires_a_preview_before_it_can_be_saved(db_session):
    """No silent-save straight off a thumbs-down."""
    res = client.post(
        "/api/v1/chat/rules/commit",
        json={"category": "should_have_included", "pattern": "credit notes"},
    )
    assert res.status_code == 400
    assert db_session.exec(select(TenantChatRule)).all() == []


def test_chat_rule_preview_returns_the_literal_final_text(db_session):
    preview = client.post(
        "/api/v1/chat/rules/preview",
        json={"category": "should_have_included", "pattern": "credit notes"},
    ).json()
    assert "credit notes" in preview["ruleText"]
    assert preview["previewToken"]

    commit = client.post("/api/v1/chat/rules/commit", json={
        "category": "should_have_included", "pattern": "credit notes",
        "preview_token": preview["previewToken"],
    })
    assert commit.status_code == 201
    # What was approved is exactly what got stored -- no paraphrase in between.
    assert commit.json()["ruleText"] == preview["ruleText"]


def test_chat_rule_commit_409s_if_the_rule_changed_after_preview(db_session):
    token = client.post(
        "/api/v1/chat/rules/preview",
        json={"category": "should_have_included", "pattern": "credit notes"},
    ).json()["previewToken"]

    res = client.post("/api/v1/chat/rules/commit", json={
        "category": "should_have_included", "pattern": "something else entirely",
        "preview_token": token,
    })
    assert res.status_code == 409
    assert db_session.exec(select(TenantChatRule)).all() == []


def test_chat_rule_validates_its_category_and_required_pattern(db_session):
    assert client.post(
        "/api/v1/chat/rules/preview", json={"category": "not_a_real_category"}
    ).status_code == 400
    # This category needs a pattern to mean anything.
    assert client.post(
        "/api/v1/chat/rules/preview", json={"category": "should_have_included", "pattern": "   "}
    ).status_code == 400
    # This one doesn't.
    assert client.post(
        "/api/v1/chat/rules/preview", json={"category": "search_line_item_descriptions"}
    ).status_code == 200


def test_chat_rules_never_touch_the_extraction_template(db_session):
    """The structural separation, asserted rather than assumed."""
    preview = client.post(
        "/api/v1/chat/rules/preview",
        json={"category": "wrong_aggregation", "pattern": "group by currency"},
    ).json()
    client.post("/api/v1/chat/rules/commit", json={
        "category": "wrong_aggregation", "pattern": "group by currency",
        "preview_token": preview["previewToken"],
    })

    assert len(db_session.exec(select(TenantChatRule)).all()) == 1
    assert db_session.exec(select(ExtractionTemplate)).all() == []


def test_chat_rules_can_be_listed_and_deleted(db_session):
    preview = client.post(
        "/api/v1/chat/rules/preview", json={"category": "wrong_direction"}
    ).json()
    rule_id = client.post("/api/v1/chat/rules/commit", json={
        "category": "wrong_direction", "preview_token": preview["previewToken"],
    }).json()["id"]

    assert len(client.get("/api/v1/chat/rules").json()) == 1
    assert client.delete(f"/api/v1/chat/rules/{rule_id}").status_code == 204
    assert client.get("/api/v1/chat/rules").json() == []


# ── Prompt injection: next to, never merged into, business rules ─────────────

def test_chat_rules_block_is_separate_from_the_business_rules_block(db_session):
    from agents.query_agent import _business_rules_block, _chat_rules_block

    db_session.add(TenantChatRule(
        tenant_id=MOCK_TENANT_ID, category="should_have_included", pattern="credit notes",
    ))
    db_session.commit()

    chat_block = _chat_rules_block(str(MOCK_TENANT_ID), db_session)
    business_block = _business_rules_block(["tax_amount is CGST+SGST summed"])

    assert "credit notes" in chat_block
    assert "Chat Answering Rules" in chat_block
    # The two blocks are genuinely distinct sections with different framing.
    assert "credit notes" not in business_block
    assert "Tenant Business Rules" not in chat_block


def test_disabled_chat_rules_are_not_injected(db_session):
    from agents.query_agent import _chat_rules_block

    db_session.add(TenantChatRule(
        tenant_id=MOCK_TENANT_ID, category="should_have_included",
        pattern="credit notes", enabled=False,
    ))
    db_session.commit()
    assert _chat_rules_block(str(MOCK_TENANT_ID), db_session) == ""


def test_no_chat_rules_means_no_block_at_all(db_session):
    from agents.query_agent import _chat_rules_block

    assert _chat_rules_block(str(MOCK_TENANT_ID), db_session) == ""


# ── Chat style: new home, legacy fallback (Gap 230) ──────────────────────────

def test_chat_style_block_reads_the_new_table(db_session):
    from agents.query_agent import _get_chat_style_block

    db_session.add(TenantChatSettings(
        tenant_id=MOCK_TENANT_ID, response_length="brief", tone="formal",
        custom_instructions="Use AP terminology.",
    ))
    db_session.commit()

    block = _get_chat_style_block(str(MOCK_TENANT_ID), db_session)
    assert "1–2 short sentences" in block
    assert "formal" in block
    assert "Use AP terminology." in block


def test_chat_style_block_falls_back_to_the_legacy_template_location(db_session):
    """A tenant whose row predates the migration keeps their configured style
    rather than silently reverting to defaults."""
    from agents.query_agent import _get_chat_style_block

    db_session.add(ExtractionTemplate(
        id=uuid4(), tenant_id=MOCK_TENANT_ID, vendor_name=None, flow_direction="INBOUND",
        rules={"constraints": [], "chat_style": {
            "response_length": "detailed", "tone": "technical", "custom_instructions": "",
        }},
        version=1,
    ))
    db_session.commit()

    block = _get_chat_style_block(str(MOCK_TENANT_ID), db_session)
    assert "technical" in block


def test_chat_style_block_defaults_when_nothing_is_configured(db_session):
    from agents.query_agent import _CONCISENESS_INSTRUCTION, _get_chat_style_block

    assert _get_chat_style_block(str(MOCK_TENANT_ID), db_session) == _CONCISENESS_INSTRUCTION
