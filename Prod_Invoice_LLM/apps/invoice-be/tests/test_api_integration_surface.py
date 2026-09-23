"""BE Gaps 723-727: the read surface an integration needs.

Five changes, one theme: everything this workspace already shows on screen
should be reachable by the credential a customer integrates with. Nothing here
adds a write, and nothing here widens a tenant boundary -- each test that
matters below is the one proving exactly that.

The API-key cases drive the dependency directly rather than minting a real key:
`resolve_api_key_context` is covered in tests/test_api_keys.py, and what these
tests are about is what the HANDLER does once a key-shaped context arrives.
"""
from datetime import date, datetime
from uuid import uuid4

import pytest
from fastapi import HTTPException, status
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from dependencies import (
    API_KEY_USER_ID,
    MOCK_TENANT_ID,
    TenantContext,
    get_db_session,
    get_tenant_context,
    get_tenant_or_api_key_context,
)
from main import app
from models import ChatSession, Document, Invoice

client = TestClient(app)

engine = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)


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


def _key_context(tenant_id=None) -> TenantContext:
    """A context shaped exactly as `resolve_api_key_context` returns one."""
    return TenantContext(
        tenant_id=tenant_id or MOCK_TENANT_ID,
        user_id=API_KEY_USER_ID,
        role="Restricted",
        billing_plan="pro",
        can_audit=True,
        can_load=True,
        auth_method="api_key",
        key_scope="actions",
    )


def _as_api_key(tenant_id=None):
    """Make the request look like a key-ONLY caller, both halves of it.

    Overriding the dual dependency alone is not enough: this suite runs with
    mock auth on, so a handler that depends on `get_tenant_context` (the
    Clerk-only one) would happily resolve a mock ADMIN and the test would pass
    for the wrong reason -- which is exactly what the delete case caught. In
    production a key sends only `X-API-Key` and that dependency 401s, so the
    override below models that rather than the test harness's convenience.
    """
    ctx = _key_context(tenant_id)

    def _clerk_only_refuses():
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required.",
        )

    app.dependency_overrides[get_tenant_or_api_key_context] = lambda: ctx
    app.dependency_overrides[get_tenant_context] = _clerk_only_refuses
    return ctx


def _invoice(tenant_id, *, direction="INBOUND", completed=None, number="INV-1") -> Invoice:
    return Invoice(
        id=uuid4(),
        tenant_id=tenant_id,
        file_path=f"mock/{uuid4()}.pdf",
        invoice_number=number,
        vendor_name="Vendor A",
        grand_total=100.0,
        status="COMPLETED",
        flow_direction=direction,
        invoice_date=date(2026, 9, 1),
        created_at=datetime(2026, 9, 1, 12, 0, 0),
        completed_at=completed,
    )


# ═══════════════════════════════════════════════════════════════════════════
# BE Gap 723 — one list endpoint for both directions
# ═══════════════════════════════════════════════════════════════════════════

def test_default_is_still_inbound_only(db_session):
    """The compatibility promise. Every caller that exists today -- this app's
    own Invoices screen, and any integration written against the old behaviour
    -- sends no `flow_direction` and must keep seeing exactly what it saw."""
    db_session.add(_invoice(MOCK_TENANT_ID, direction="INBOUND", number="IN-1"))
    db_session.add(_invoice(MOCK_TENANT_ID, direction="OUTBOUND", number="OUT-1"))
    db_session.commit()

    numbers = [i["invoice_number"] for i in client.get("/api/v1/invoices").json()]
    assert numbers == ["IN-1"]


def test_outbound_can_be_asked_for(db_session):
    db_session.add(_invoice(MOCK_TENANT_ID, direction="INBOUND", number="IN-1"))
    db_session.add(_invoice(MOCK_TENANT_ID, direction="OUTBOUND", number="OUT-1"))
    db_session.commit()

    response = client.get("/api/v1/invoices", params={"flow_direction": "OUTBOUND"})
    assert response.status_code == 200
    assert [i["invoice_number"] for i in response.json()] == ["OUT-1"]


def test_all_returns_both_sides(db_session):
    db_session.add(_invoice(MOCK_TENANT_ID, direction="INBOUND", number="IN-1"))
    db_session.add(_invoice(MOCK_TENANT_ID, direction="OUTBOUND", number="OUT-1"))
    db_session.commit()

    numbers = {
        i["invoice_number"]
        for i in client.get("/api/v1/invoices", params={"flow_direction": "ALL"}).json()
    }
    assert numbers == {"IN-1", "OUT-1"}


def test_unknown_direction_is_refused_not_ignored(db_session):
    """422, not a silent fallback to INBOUND. A typo in an integration must
    fail loudly rather than quietly return the wrong half of the ledger."""
    response = client.get("/api/v1/invoices", params={"flow_direction": "SIDEWAYS"})
    assert response.status_code == 422


def test_another_tenants_invoices_are_never_returned(db_session):
    """The boundary, asserted on the widest case this gap opens: ALL."""
    other_tenant = uuid4()
    db_session.add(_invoice(MOCK_TENANT_ID, direction="OUTBOUND", number="MINE"))
    db_session.add(_invoice(other_tenant, direction="OUTBOUND", number="THEIRS"))
    db_session.commit()

    numbers = [
        i["invoice_number"]
        for i in client.get("/api/v1/invoices", params={"flow_direction": "ALL"}).json()
    ]
    assert numbers == ["MINE"]


# ═══════════════════════════════════════════════════════════════════════════
# BE Gap 724 — completed_since
# ═══════════════════════════════════════════════════════════════════════════

def test_completed_since_returns_only_what_finished_after_it(db_session):
    db_session.add(
        _invoice(MOCK_TENANT_ID, completed=datetime(2026, 9, 1, 10, 0, 0), number="OLD")
    )
    db_session.add(
        _invoice(MOCK_TENANT_ID, completed=datetime(2026, 9, 5, 10, 0, 0), number="NEW")
    )
    db_session.commit()

    response = client.get(
        "/api/v1/invoices", params={"completed_since": "2026-09-03T00:00:00"}
    )
    assert response.status_code == 200
    assert [i["invoice_number"] for i in response.json()] == ["NEW"]


def test_completed_since_is_inclusive_of_the_watermark(db_session):
    """`>=`, on purpose. A caller re-sending its last watermark gets the
    boundary row again -- harmless, the row is identical -- whereas `>` would
    drop anything completing inside the same microsecond."""
    moment = datetime(2026, 9, 5, 10, 0, 0)
    db_session.add(_invoice(MOCK_TENANT_ID, completed=moment, number="EDGE"))
    db_session.commit()

    response = client.get("/api/v1/invoices", params={"completed_since": moment.isoformat()})
    assert [i["invoice_number"] for i in response.json()] == ["EDGE"]


def test_invoices_still_processing_are_not_returned(db_session):
    """`completed_at` is NULL until extraction finishes. A sync asking "what is
    new" must not be handed rows with no result on them yet."""
    db_session.add(_invoice(MOCK_TENANT_ID, completed=None, number="INFLIGHT"))
    db_session.add(
        _invoice(MOCK_TENANT_ID, completed=datetime(2026, 9, 5, 10, 0, 0), number="DONE")
    )
    db_session.commit()

    response = client.get(
        "/api/v1/invoices", params={"completed_since": "2026-09-01T00:00:00"}
    )
    assert [i["invoice_number"] for i in response.json()] == ["DONE"]


def test_completed_since_combines_with_direction(db_session):
    """The two new filters are independent predicates, not alternatives."""
    when = datetime(2026, 9, 5, 10, 0, 0)
    db_session.add(_invoice(MOCK_TENANT_ID, direction="INBOUND", completed=when, number="IN"))
    db_session.add(_invoice(MOCK_TENANT_ID, direction="OUTBOUND", completed=when, number="OUT"))
    db_session.commit()

    response = client.get(
        "/api/v1/invoices",
        params={"flow_direction": "OUTBOUND", "completed_since": "2026-09-01T00:00:00"},
    )
    assert [i["invoice_number"] for i in response.json()] == ["OUT"]


# ═══════════════════════════════════════════════════════════════════════════
# BE Gap 725 — documents are readable by a key
# ═══════════════════════════════════════════════════════════════════════════

def _document(tenant_id, *, number="DN-1", doc_type="DELIVERY_NOTE") -> Document:
    return Document(
        id=uuid4(),
        tenant_id=tenant_id,
        file_path=f"mock/{uuid4()}.pdf",
        doc_type=doc_type,
        doc_number=number,
        status="EXTRACTED",
    )


def test_api_key_can_list_documents(db_session):
    """The point of the gap: the classification work was visible only on screen."""
    _as_api_key()
    db_session.add(_document(MOCK_TENANT_ID, number="DN-1"))
    db_session.commit()

    response = client.get("/api/v1/documents")
    assert response.status_code == 200
    assert [d["doc_number"] for d in response.json()] == ["DN-1"]


def test_api_key_can_read_one_document(db_session):
    _as_api_key()
    doc = _document(MOCK_TENANT_ID, number="PO-9", doc_type="PURCHASE_ORDER")
    db_session.add(doc)
    db_session.commit()

    response = client.get(f"/api/v1/documents/{doc.id}")
    assert response.status_code == 200
    assert response.json()["doc_type"] == "PURCHASE_ORDER"


def test_api_key_never_sees_another_tenants_document(db_session):
    _as_api_key()
    theirs = _document(uuid4(), number="THEIRS")
    db_session.add(theirs)
    db_session.commit()

    assert client.get("/api/v1/documents").json() == []
    assert client.get(f"/api/v1/documents/{theirs.id}").status_code in (403, 404)


def test_api_key_cannot_delete_a_document(db_session):
    """A key reads; it does not destroy. `delete_document` keeps the Clerk-only
    dependency, so the key context never even resolves for it."""
    _as_api_key()
    doc = _document(MOCK_TENANT_ID)
    db_session.add(doc)
    db_session.commit()

    response = client.delete(f"/api/v1/documents/{doc.id}")
    assert response.status_code == 401
    assert db_session.get(Document, doc.id) is not None


# ═══════════════════════════════════════════════════════════════════════════
# BE Gap 726 — a key reads the chat it created, and only that
# ═══════════════════════════════════════════════════════════════════════════

def test_key_created_session_is_stamped_not_left_null(db_session):
    """NULL used to mean two different things -- "made by a key" and "made by a
    human before Gap 572". Keeping them apart is what makes the read below
    safe."""
    _as_api_key()
    response = client.post("/api/v1/chat/sessions", json={"title": "integration"})
    assert response.status_code == 201

    stored = db_session.get(ChatSession, uuid4().__class__(response.json()["id"]))
    assert stored.user_id == API_KEY_USER_ID


def test_key_lists_its_own_sessions_only(db_session):
    """The isolation Gap 572 built, kept. A key sees what it made; a human's
    thread and a legacy NULL-owner thread both stay out of reach."""
    _as_api_key()
    mine = ChatSession(id=uuid4(), tenant_id=MOCK_TENANT_ID, user_id=API_KEY_USER_ID, title="mine")
    human = ChatSession(id=uuid4(), tenant_id=MOCK_TENANT_ID, user_id="user_priya", title="hers")
    legacy = ChatSession(id=uuid4(), tenant_id=MOCK_TENANT_ID, user_id=None, title="legacy")
    db_session.add(mine)
    db_session.add(human)
    db_session.add(legacy)
    db_session.commit()

    titles = [s["title"] for s in client.get("/api/v1/chat/sessions").json()]
    assert titles == ["mine"]


def test_key_cannot_read_a_humans_session(db_session):
    _as_api_key()
    human = ChatSession(id=uuid4(), tenant_id=MOCK_TENANT_ID, user_id="user_priya", title="hers")
    db_session.add(human)
    db_session.commit()

    assert client.get(f"/api/v1/chat/sessions/{human.id}").status_code == 403


def test_key_can_read_the_session_it_created(db_session):
    """The whole reason for the gap: an integration could ask a question and
    never fetch the answer."""
    _as_api_key()
    mine = ChatSession(id=uuid4(), tenant_id=MOCK_TENANT_ID, user_id=API_KEY_USER_ID, title="mine")
    db_session.add(mine)
    db_session.commit()

    assert client.get(f"/api/v1/chat/sessions/{mine.id}").status_code == 200


def test_key_still_cannot_rename_or_delete_a_session(db_session):
    """Read-only. The write paths keep their refusals."""
    _as_api_key()
    mine = ChatSession(id=uuid4(), tenant_id=MOCK_TENANT_ID, user_id=API_KEY_USER_ID, title="mine")
    db_session.add(mine)
    db_session.commit()

    assert client.put(f"/api/v1/chat/sessions/{mine.id}", json={"title": "x"}).status_code == 403
    assert client.delete(f"/api/v1/chat/sessions/{mine.id}").status_code == 403


# ═══════════════════════════════════════════════════════════════════════════
# BE Gap 727 — every event we send is documented
# ═══════════════════════════════════════════════════════════════════════════

def test_openapi_documents_every_event_the_platform_sends():
    """The two that were missing were being DELIVERED, so a subscriber reading
    the docs would have written a handler that silently ignored them."""
    schema = app.openapi()
    documented = set(schema.get("webhooks", {}))
    assert {
        "invoice.processing",
        "invoice.completed",
        "invoice.audit_required",
        "invoice.approved",
        "invoice.rejected",
        "invoice.duplicate",
        "outbound_invoice.sent",
        "outbound_invoice.approved",
        "outbound_invoice.overdue",
    } <= documented
