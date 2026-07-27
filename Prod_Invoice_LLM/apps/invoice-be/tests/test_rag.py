import os
import pytest
from unittest.mock import patch, MagicMock
from uuid import uuid4
from fastapi.testclient import TestClient
from sqlmodel import SQLModel, create_engine, Session, select
from sqlalchemy.pool import StaticPool

# Mock embeddings before importing chroma client or query agent
os.environ["MOCK_EMBEDDINGS"] = "true"

from main import app
from dependencies import get_db_session, MOCK_TENANT_ID
from models import ChatSession
from chroma_client import index_invoice_document, query_invoice_chunks

# Setup isolated in-memory test database session
sqlite_url = "sqlite:///:memory:"
engine = create_engine(
    sqlite_url,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool
)

@pytest.fixture(name="db_session")
def db_session_fixture():
    """Yields clean isolated test database session."""
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    SQLModel.metadata.drop_all(engine)

@pytest.fixture(autouse=True)
def override_db_session(db_session):
    """Overrides dependencies database session."""
    def get_db_session_override():
        yield db_session
    app.dependency_overrides[get_db_session] = get_db_session_override
    yield
    app.dependency_overrides.clear()

def test_session_lifecycle_and_tenant_isolation(db_session):
    """Verify session creation, list, retrieval, and forbidden foreign tenant checks."""
    client = TestClient(app)
    
    # 1. Create session
    create_res = client.post("/api/v1/chat/sessions", json={"title": "Session Alpha"})
    assert create_res.status_code == 201
    session_data = create_res.json()
    session_id = session_data["id"]
    assert session_data["title"] == "Session Alpha"
    assert session_data["tenant_id"] == str(MOCK_TENANT_ID)
    
    # 2. List sessions
    list_res = client.get("/api/v1/chat/sessions")
    assert list_res.status_code == 200
    sessions_list = list_res.json()
    assert len(sessions_list) >= 1
    assert any(s["id"] == session_id for s in sessions_list)
    
    # 3. foreign tenant access attempt should fail with 403
    foreign_tenant_id = uuid4()
    from dependencies import get_tenant_context, TenantContext
    app.dependency_overrides[get_tenant_context] = lambda: TenantContext(
        tenant_id=foreign_tenant_id,
        user_id="user_foreign_test",
        role="Admin",
        billing_plan="free"
    )
    try:
        get_res = client.get(f"/api/v1/chat/sessions/{session_id}")
        assert get_res.status_code == 403
    finally:
        del app.dependency_overrides[get_tenant_context]

def test_chat_message_routing_and_history_saving(db_session):
    """Verify message postings execute agent routing paths and persist thread history."""
    client = TestClient(app)
    
    # Pre-populate ChatSession
    session_id = uuid4()
    session = ChatSession(
        id=session_id,
        tenant_id=MOCK_TENANT_ID,
        title="Test Memory Session"
    )
    db_session.add(session)
    db_session.commit()
    
    # Mock LLM classifier to select CHAT route and Mock chat output
    with patch("agents.query_agent.classify_query") as mock_class, \
         patch("agents.query_agent.get_llm") as mock_get_llm:
         
        mock_class.return_value = "CHAT"
        
        # Mock LLM response
        mock_response = MagicMock(content="Hello! I am your assistant.")
        mock_llm = MagicMock()
        mock_llm.invoke.return_value = mock_response
        mock_get_llm.return_value = mock_llm
        
        # Post user message
        msg_res = client.post(
            f"/api/v1/chat/sessions/{session_id}/message",
            json={"content": "Hi there"}
        )
        assert msg_res.status_code == 200
        msg_data = msg_res.json()
        assert msg_data["role"] == "assistant"
        assert msg_data["content"] == "Hello! I am your assistant."
        
        # Retrieve chronological history and check if both user and assistant messages are saved
        history_res = client.get(f"/api/v1/chat/sessions/{session_id}")
        assert history_res.status_code == 200
        history_list = history_res.json()
        assert len(history_list) == 2
        assert history_list[0]["role"] == "user"
        assert history_list[0]["content"] == "Hi there"
        assert history_list[1]["role"] == "assistant"
        assert history_list[1]["content"] == "Hello! I am your assistant."

def test_message_feedback_upsert_and_clear(db_session):
    """Gap 54: per-answer thumbs up/down. Voting is idempotent per message (a
    second vote overwrites, not duplicates), the vote survives a reload via
    GET /chat/sessions/{id}, and DELETE clears it -- all signal-only, no
    side effect on the message/session/invoice data itself."""
    client = TestClient(app)

    session_id = uuid4()
    db_session.add(ChatSession(id=session_id, tenant_id=MOCK_TENANT_ID, title="Feedback Test"))
    db_session.commit()

    from models import ChatMessage
    message_id = uuid4()
    db_session.add(ChatMessage(
        id=message_id, session_id=session_id, role="assistant",
        content="The grand total is $500.", generated_sql="SELECT ...", citations=[]
    ))
    db_session.commit()

    # 1. Invalid vote value rejected
    bad = client.put(f"/api/v1/chat/messages/{message_id}/feedback", json={"vote": "sideways"})
    assert bad.status_code == 400

    # 2. Cast a downvote
    down = client.put(f"/api/v1/chat/messages/{message_id}/feedback", json={"vote": "down"})
    assert down.status_code == 200
    assert down.json() == {"success": True, "vote": "down"}

    # 3. Survives a reload via session history, and doesn't touch message content
    history = client.get(f"/api/v1/chat/sessions/{session_id}").json()
    assert history[0]["feedback"] == "down"
    assert history[0]["content"] == "The grand total is $500."

    # 4. Changing the vote overwrites rather than duplicating
    up = client.put(f"/api/v1/chat/messages/{message_id}/feedback", json={"vote": "up"})
    assert up.status_code == 200
    from models import ChatFeedback
    rows = db_session.exec(select(ChatFeedback).where(ChatFeedback.message_id == message_id)).all()
    assert len(rows) == 1
    assert rows[0].vote == "up"

    # 5. Clearing removes the row; re-fetch shows feedback=None again
    clear = client.delete(f"/api/v1/chat/messages/{message_id}/feedback")
    assert clear.status_code == 200
    assert clear.json() == {"success": True, "vote": None}
    history_after_clear = client.get(f"/api/v1/chat/sessions/{session_id}").json()
    assert history_after_clear[0]["feedback"] is None


def test_message_feedback_tenant_isolation(db_session):
    """Gap 54: voting on a message that belongs to another tenant's session is forbidden."""
    client = TestClient(app)
    from models import ChatMessage
    from dependencies import get_tenant_context, TenantContext

    other_tenant_id = uuid4()
    session_id = uuid4()
    db_session.add(ChatSession(id=session_id, tenant_id=other_tenant_id, title="Other Tenant"))
    message_id = uuid4()
    db_session.add(ChatMessage(id=message_id, session_id=session_id, role="assistant", content="Some answer"))
    db_session.commit()

    response = client.put(f"/api/v1/chat/messages/{message_id}/feedback", json={"vote": "up"})
    assert response.status_code == 403


def test_sql_guardrail_safety_enforcement(db_session):
    """Verify that dangerous or cross-tenant SQL generations raise validation exceptions."""
    from agents.query_agent import execute_generated_sql
    
    # 1. Reject mutating updates
    with pytest.raises(ValueError, match="forbidden"):
        execute_generated_sql("DROP TABLE invoice;", str(MOCK_TENANT_ID), db_session)
        
    with pytest.raises(ValueError, match="forbidden"):
        execute_generated_sql("UPDATE invoice SET grand_total = 0.0;", str(MOCK_TENANT_ID), db_session)
        
    # 2. Reject queries without tenant filters
    with pytest.raises(ValueError, match="isolation"):
        execute_generated_sql("SELECT * FROM invoice;", str(MOCK_TENANT_ID), db_session)
        
    # 3. Allow safe read-only query with tenant isolation filter
    safe_sql = f"SELECT id, vendor_name FROM invoice WHERE tenant_id = '{MOCK_TENANT_ID}';"
    # Should execute successfully without raising ValueError (might return empty results description)
    res = execute_generated_sql(safe_sql, str(MOCK_TENANT_ID), db_session)
    assert "No records found" in res

def test_vector_metadata_tenant_isolation(db_session):
    """Verify that Chroma indexing and chunk queries enforce strict metadata isolation."""
    # Write a small temp pdf dummy file
    temp_pdf_path = "temp_rag_test.pdf"
    import fitz
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((50, 50), "Standard RAG invoice content line details")
    doc.save(temp_pdf_path)
    doc.close()
    
    try:
        tenant_a = uuid4()
        tenant_b = uuid4()
        
        # Index document under Tenant A
        index_invoice_document(
            invoice_id="inv-a1",
            tenant_id=tenant_a,
            vendor_name="Acme",
            file_path=temp_pdf_path
        )
        
        # Index document under Tenant B
        index_invoice_document(
            invoice_id="inv-b2",
            tenant_id=tenant_b,
            vendor_name="Global Corp",
            file_path=temp_pdf_path
        )
        
        # Query under Tenant A -> should only fetch Acme chunks, no Tenant B chunks
        chunks_a = query_invoice_chunks(tenant_id=tenant_a, query_text="invoice", limit=5)
        assert len(chunks_a) >= 1
        assert all(c["metadata"]["tenant_id"] == str(tenant_a) for c in chunks_a)
        assert all(c["metadata"]["vendor_name"] == "Acme" for c in chunks_a)
        
        # Query under Tenant B -> should only fetch Global Corp chunks
        chunks_b = query_invoice_chunks(tenant_id=tenant_b, query_text="invoice", limit=5)
        assert len(chunks_b) >= 1
        assert all(c["metadata"]["tenant_id"] == str(tenant_b) for c in chunks_b)
        assert all(c["metadata"]["vendor_name"] == "Global Corp" for c in chunks_b)

        # Gap 55: isolation is now structural (separate collections), not just a metadata
        # filter — confirm the two tenants actually landed in two distinct collections.
        from chroma_client import get_chroma_client, _tenant_collection_name
        client = get_chroma_client()
        collection_a = client.get_or_create_collection(name=_tenant_collection_name(tenant_a))
        collection_b = client.get_or_create_collection(name=_tenant_collection_name(tenant_b))
        assert collection_a.name != collection_b.name
        assert collection_a.get(ids=["inv-b2_page_1"])["ids"] == []
        assert collection_b.get(ids=["inv-a1_page_1"])["ids"] == []

    finally:
        if os.path.exists(temp_pdf_path):
            os.remove(temp_pdf_path)
