import logging
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, ConfigDict
from sqlmodel import Session, select
from uuid import UUID, uuid4
from datetime import datetime

from dependencies import get_db_session, get_tenant_context, TenantContext
from models import ChatSession, ChatMessage, ChatFeedback
from agents.query_agent import run_query_agent

logger = logging.getLogger(__name__)

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

class FeedbackCreate(BaseModel):
    vote: str = Field(description="Must be exactly 'up' or 'down'")

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
    feedback: str | None = None  # Gap 54: "up" / "down" / None, so votes survive a reload

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

    # Gap 54: attach each message's current vote (if any) so it survives a
    # reload -- one query for the whole session rather than N+1 per message.
    feedback_rows = db_session.exec(
        select(ChatFeedback).where(ChatFeedback.session_id == session_id)
    ).all()
    feedback_by_message = {f.message_id: f.vote for f in feedback_rows}

    return [
        MessageResponse.model_validate(m).model_copy(update={"feedback": feedback_by_message.get(m.id)})
        for m in messages
    ]

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
    
    # Auto-generate session title if it uses the default placeholder or timestamp format
    if chat_session.title.startswith("Chat Session -") or chat_session.title == "New Chat":
        words = payload.content.strip().split()
        if words:
            new_title = " ".join(words[:6])
            if len(words) > 6:
                new_title += "..."
            chat_session.title = new_title
            db_session.add(chat_session)
            
    db_session.commit()
    
    # 3. Invoke multi-agent Query Agent routing pipeline.
    # Gap 37: the SQL/RAG/CHAT routes inside run_query_agent() each already
    # have their own try/except, but the call itself was unguarded here -
    # any exception outside those three branches (routing classification,
    # chat-history lookup, cache access) surfaced as a raw, unhandled 500
    # instead of a graceful chat response. Found via the benchmark's Day 1
    # RAG chat sample (a 500 on an audit_status question).
    try:
        agent_output = run_query_agent(
            session_id=str(session_id),
            user_message=payload.content,
            tenant_id=str(tenant_context.tenant_id),
            db_session=db_session
        )
    except Exception as e:
        logger.error("run_query_agent failed unexpectedly for session %s: %s", session_id, e)
        agent_output = {
            "content": "Sorry, something went wrong answering that — please try again.",
            "generated_sql": None,
            "citations": [],
        }
    
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


def _get_owned_message(message_id: UUID, db_session: Session, tenant_context: TenantContext) -> ChatMessage:
    """Gap 54 helper: fetch a message and confirm it belongs to the requesting
    tenant via its parent session -- same ownership-check shape used by the
    two handlers above, just entered from a message id instead of a session id."""
    message = db_session.exec(select(ChatMessage).where(ChatMessage.id == message_id)).first()
    if not message:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Message not found.")

    chat_session = db_session.exec(select(ChatSession).where(ChatSession.id == message.session_id)).first()
    if not chat_session or chat_session.tenant_id != tenant_context.tenant_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access forbidden to this message.")

    return message


@router.put("/messages/{message_id}/feedback")
def set_message_feedback(
    message_id: UUID,
    payload: FeedbackCreate,
    db_session: Session = Depends(get_db_session),
    tenant_context: TenantContext = Depends(get_tenant_context)
):
    """
    Gap 54: per-answer thumbs up/down, tied to that turn's generated_sql/
    citations via message_id. Deliberately signal-only -- this just records
    the vote, it never triggers any auto-fix or retraining. Voting again
    on the same message overwrites the previous vote (upsert on message_id)
    rather than accumulating duplicate rows.
    """
    if payload.vote not in ("up", "down"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="vote must be 'up' or 'down'.")

    message = _get_owned_message(message_id, db_session, tenant_context)

    existing = db_session.exec(select(ChatFeedback).where(ChatFeedback.message_id == message_id)).first()
    if existing:
        existing.vote = payload.vote
        db_session.add(existing)
    else:
        db_session.add(ChatFeedback(
            tenant_id=tenant_context.tenant_id,
            session_id=message.session_id,
            message_id=message_id,
            vote=payload.vote,
        ))
    db_session.commit()
    return {"success": True, "vote": payload.vote}


@router.delete("/messages/{message_id}/feedback")
def clear_message_feedback(
    message_id: UUID,
    db_session: Session = Depends(get_db_session),
    tenant_context: TenantContext = Depends(get_tenant_context)
):
    """Gap 54: clears a previously-cast vote (e.g. clicking the same thumb
    again to un-vote). No-op, not an error, if there was nothing to clear."""
    _get_owned_message(message_id, db_session, tenant_context)

    existing = db_session.exec(select(ChatFeedback).where(ChatFeedback.message_id == message_id)).first()
    if existing:
        db_session.delete(existing)
        db_session.commit()
    return {"success": True, "vote": None}
