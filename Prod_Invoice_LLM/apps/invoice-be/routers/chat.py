from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, ConfigDict
from sqlmodel import Session, select
from uuid import UUID, uuid4
from datetime import datetime

from dependencies import get_db_session, get_tenant_context, TenantContext
from models import ChatSession, ChatMessage
from agents.query_agent import run_query_agent

router = APIRouter(prefix="/chat", tags=["chat"])

# Request/Response schemas
class SessionCreate(BaseModel):
    title: str | None = Field(default=None, max_length=255)

class SessionResponse(BaseModel):
    id: UUID
    tenant_id: UUID
    title: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)

class MessageCreate(BaseModel):
    content: str

class CitationResponse(BaseModel):
    invoice_id: str | None = None
    vendor_name: str | None = None
    page: int | None = None

class MessageResponse(BaseModel):
    id: UUID
    session_id: UUID
    role: str
    content: str
    generated_sql: str | None = None
    citations: list[CitationResponse] = []
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)

@router.get("/sessions", response_model=list[SessionResponse])
def list_sessions(
    db_session: Session = Depends(get_db_session),
    tenant_context: TenantContext = Depends(get_tenant_context)
):
    """List all previous chat sessions belonging to the requesting tenant."""
    statement = (
        select(ChatSession)
        .where(ChatSession.tenant_id == tenant_context.tenant_id)
        .order_by(ChatSession.created_at.desc())
    )
    results = db_session.exec(statement).all()
    return results

@router.post("/sessions", response_model=SessionResponse, status_code=status.HTTP_201_CREATED)
def create_session(
    payload: SessionCreate,
    db_session: Session = Depends(get_db_session),
    tenant_context: TenantContext = Depends(get_tenant_context)
):
    """Create a new chat session."""
    title = payload.title or f"Chat Session - {datetime.utcnow().strftime('%Y-%m-%d %H:%M')}"
    session_id = uuid4()
    
    db_session_obj = ChatSession(
        id=session_id,
        tenant_id=tenant_context.tenant_id,
        title=title
    )
    db_session.add(db_session_obj)
    db_session.commit()
    db_session.refresh(db_session_obj)
    return db_session_obj

@router.get("/sessions/{session_id}", response_model=list[MessageResponse])
def get_session_messages(
    session_id: UUID,
    db_session: Session = Depends(get_db_session),
    tenant_context: TenantContext = Depends(get_tenant_context)
):
    """Retrieve all historical messages for a chat session, validating tenant ownership."""
    # 1. Fetch and assert session exists and belongs to requesting tenant
    session_statement = select(ChatSession).where(ChatSession.id == session_id)
    chat_session = db_session.exec(session_statement).first()
    
    if not chat_session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Chat session not found."
        )
        
    if chat_session.tenant_id != tenant_context.tenant_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access forbidden to this chat session."
        )
        
    # 2. Fetch messages ordered by creation date
    message_statement = (
        select(ChatMessage)
        .where(ChatMessage.session_id == session_id)
        .order_by(ChatMessage.created_at.asc())
    )
    messages = db_session.exec(message_statement).all()
    return messages

@router.post("/sessions/{session_id}/message", response_model=MessageResponse)
def post_chat_message(
    session_id: UUID,
    payload: MessageCreate,
    db_session: Session = Depends(get_db_session),
    tenant_context: TenantContext = Depends(get_tenant_context)
):
    """Post a new message in a chat session and run the multi-agent RAG routing agent."""
    # 1. Assert session exists and belongs to requesting tenant
    session_statement = select(ChatSession).where(ChatSession.id == session_id)
    chat_session = db_session.exec(session_statement).first()
    
    if not chat_session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Chat session not found."
        )
        
    if chat_session.tenant_id != tenant_context.tenant_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access forbidden to this chat session."
        )
        
    # 2. Save user message to database
    user_msg = ChatMessage(
        id=uuid4(),
        session_id=session_id,
        role="user",
        content=payload.content
    )
    db_session.add(user_msg)
    db_session.commit()
    
    # 3. Invoke multi-agent Query Agent routing pipeline
    agent_output = run_query_agent(
        session_id=str(session_id),
        user_message=payload.content,
        tenant_id=str(tenant_context.tenant_id),
        db_session=db_session
    )
    
    # 4. Save assistant response to database
    assistant_msg = ChatMessage(
        id=uuid4(),
        session_id=session_id,
        role="assistant",
        content=agent_output["content"],
        generated_sql=agent_output["generated_sql"],
        citations=agent_output["citations"]
    )
    db_session.add(assistant_msg)
    db_session.commit()
    db_session.refresh(assistant_msg)
    
    return assistant_msg
