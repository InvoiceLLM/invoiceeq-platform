import logging
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, ConfigDict
from sqlmodel import Session, select
from uuid import UUID, uuid4
from datetime import datetime

from dependencies import get_db_session, get_tenant_context, require_can_train, TenantContext
from models import ChatSession, ChatMessage, ChatFeedback, Invoice, TenantChatRule
from agents.query_agent import run_query_agent
from services.chat_rules import (
    list_chat_rule_categories,
    render_chat_rule,
    validate_chat_rule,
)

logger = logging.getLogger(__name__)


def _invalidate_chat_answer_cache(tenant_id: str) -> None:
    """Feature 18: flush the tenant's cached answers after a chat-rule change.

    Same reasoning and same best-effort contract as the Trainer's own
    `routers/trainer.py::_invalidate_chat_answer_cache` (Gap 213): the cache key
    is `chat_answer_cache:{tenant_id}:{normalized_query}` with no rule dimension,
    so a tenant-wide flush is both the correct granularity and the only available
    one. Deliberately duplicated rather than imported -- importing from
    `routers/trainer.py` would drag that module's paid-plan gate and Azure queue
    client into the chat router's import graph for four lines of Redis.
    """
    try:
        import redis
        from config import get_settings

        r = redis.Redis.from_url(get_settings().REDIS_URL, decode_responses=True)
        keys = r.keys(f"chat_answer_cache:{tenant_id}:*")
        if keys:
            r.delete(*keys)
    except Exception as e:
        logger.warning("Failed to invalidate chat answer cache for tenant %s: %s", tenant_id, e)

router = APIRouter(prefix="/chat", tags=["chat"])

# Request/Response schemas
class SessionCreate(BaseModel):
    title: str | None = Field(default=None, max_length=255)

class SessionRename(BaseModel):
    """Gap 216: rename-only payload. Deliberately carries just `title` -- the
    thread's tenant, id and created_at are never client-editable."""
    title: str = Field(min_length=1, max_length=255)

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
    # Feature 18 (Gap 232): optional so the existing signal-only thumbs-up/down
    # keeps working byte-for-byte; supplying a reason opts into the triage flow.
    reason: str | None = Field(
        default=None, description="wrong_data | wrong_interpretation | bad_tone (thumbs-down only)"
    )
    note: str | None = Field(default=None, max_length=2000)


class TriagePayload(BaseModel):
    """Step 1 of the wrong-data triage: which invoice/field is the complaint about."""
    invoice_id: UUID | None = None
    field: str | None = None
    # What the reply claimed, if the FE can capture it. Optional -- when absent the
    # diff falls back to checking whether the stored value appears in the reply.
    claimed_value: str | None = None


class SourceVerdictPayload(BaseModel):
    """Step 2: the human's answer to 'does the PDF agree with what we stored?'"""
    invoice_id: UUID
    field: str
    pdf_agrees: bool


class ChatRulePayload(BaseModel):
    category: str
    pattern: str = ""
    context_text: str = ""
    preview_token: str | None = None

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
    contexts: list[str] = []
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

@router.put("/sessions/{session_id}", response_model=SessionResponse)
def rename_session(
    session_id: UUID,
    payload: SessionRename,
    db_session: Session = Depends(get_db_session),
    tenant_context: TenantContext = Depends(get_tenant_context)
):
    """
    FE Gap 216: rename a chat thread. The FE has offered inline thread renaming
    since FE Gap 149, but there was no endpoint behind it at all -- the proxy
    route only exported GET/DELETE, so the PUT 405'd and the rename lived purely
    in React state until the next reload. Title-only by design: it never touches
    messages, feedback or ownership.

    Same 404/403 ownership shape as the sibling handlers in this router.
    """
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

    # `min_length=1` only rejects an empty string -- "   " passes it and would
    # persist a blank sidebar label, so the stripped value is checked too.
    title = payload.title.strip()
    if not title:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Title must not be blank."
        )

    chat_session.title = title
    db_session.add(chat_session)
    db_session.commit()
    db_session.refresh(chat_session)
    return chat_session

@router.delete("/sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_session(
    session_id: UUID,
    db_session: Session = Depends(get_db_session),
    tenant_context: TenantContext = Depends(get_tenant_context)
):
    """Delete a chat session and all its associated messages and feedback."""
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
        
    # Delete associated messages
    messages_statement = select(ChatMessage).where(ChatMessage.session_id == session_id)
    messages = db_session.exec(messages_statement).all()
    for msg in messages:
        # Delete associated feedback first
        feedback_statement = select(ChatFeedback).where(ChatFeedback.message_id == msg.id)
        feedbacks = db_session.exec(feedback_statement).all()
        for f in feedbacks:
            db_session.delete(f)
        db_session.delete(msg)
        
    db_session.delete(chat_session)
    db_session.commit()

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
        
    # 2. Stage the user message.
    # Gap 209: deliberately NOT committed here. It used to be, which meant a
    # true process-level crash (worker kill, OOM, mid-request redeploy) between
    # this commit and the assistant-reply commit below left the turn orphaned --
    # a user bubble in the thread with no answer and nothing to retry from.
    # Staging it instead keeps both rows in one transaction that either lands
    # whole at step 4 or never lands at all: an uncommitted transaction is
    # rolled back by the connection teardown, so a crash leaves no orphan.
    # The row is still autoflushed (not committed) by the agent's own queries
    # below, so get_chat_history() sees this turn exactly as it did before.
    user_msg = ChatMessage(
        id=uuid4(),
        session_id=session_id,
        role="user",
        content=payload.content
    )
    db_session.add(user_msg)

    # Auto-generate session title if it uses the default placeholder or timestamp format
    new_title = None
    if chat_session.title.startswith("Chat Session -") or chat_session.title == "New Chat":
        words = payload.content.strip().split()
        if words:
            new_title = " ".join(words[:6])
            if len(words) > 6:
                new_title += "..."
            chat_session.title = new_title
            db_session.add(chat_session)

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
        # Gap 209: the session may be left mid-failed-transaction (Gap 39's
        # Postgres "current transaction is aborted" case), which would make the
        # single commit at step 4 raise instead of saving the fallback answer.
        # Rolling back guarantees a usable session; the staged rows it discards
        # are re-staged just below.
        db_session.rollback()
        agent_output = {
            "content": "Sorry, something went wrong answering that — please try again.",
            "generated_sql": None,
            "citations": [],
            "result_invoice_ids": [],
        }

    # 4. Re-stage anything a rollback inside the agent discarded, then save the
    # user turn and the assistant reply together in one transaction.
    # Gap 209: run_query_agent()'s SQL repair loop calls db_session.rollback()
    # on a failed attempt (Task 6.9 / Gap 39). SQLAlchemy's rollback always
    # unwinds the topmost transaction, expunging pending rows -- so without
    # this the previously-committed user message would now be silently dropped
    # on any query that needed a repair retry. Both re-stages are no-ops when
    # no rollback happened.
    if user_msg not in db_session:
        db_session.add(user_msg)
    if new_title is not None and chat_session.title != new_title:
        chat_session.title = new_title
        db_session.add(chat_session)

    assistant_msg = ChatMessage(
        id=uuid4(),
        session_id=session_id,
        role="assistant",
        content=agent_output["content"],
        generated_sql=agent_output["generated_sql"],
        citations=agent_output["citations"],
        # Feature 18 (Gap 231): the result-set snapshot, captured at answer time.
        # `.get()` because a cached answer written before this deploy (1hr TTL)
        # legitimately has no such key.
        result_invoice_ids=agent_output.get("result_invoice_ids") or [],
    )
    db_session.add(assistant_msg)
    db_session.commit()
    db_session.refresh(assistant_msg)
    object.__setattr__(assistant_msg, "contexts", agent_output.get("contexts") or [])

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
    if payload.reason is not None and payload.reason not in TRIAGE_REASONS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"reason must be one of {sorted(TRIAGE_REASONS)}.",
        )
    if payload.reason and payload.vote != "down":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="A triage reason only applies to a thumbs-down.",
        )

    message = _get_owned_message(message_id, db_session, tenant_context)

    existing = db_session.exec(select(ChatFeedback).where(ChatFeedback.message_id == message_id)).first()
    if existing:
        existing.vote = payload.vote
        existing.reason = payload.reason
        existing.note = (payload.note or "").strip() or None
        db_session.add(existing)
    else:
        db_session.add(ChatFeedback(
            tenant_id=tenant_context.tenant_id,
            session_id=message.session_id,
            message_id=message_id,
            vote=payload.vote,
            reason=payload.reason,
            note=(payload.note or "").strip() or None,
        ))
    db_session.commit()

    response = {"success": True, "vote": payload.vote, "reason": payload.reason}
    if payload.vote == "down":
        # Feature 18: hand the FE everything it needs to open the right next step
        # without a second round-trip just to discover which step that is.
        response["triage"] = _triage_entry_point(message, payload.reason, db_session, tenant_context)
    return response


# ─────────────────────────────────────────────────────────────────────────────
# Feature 18 (Gap 232): thumbs-down triage
#
# A thumbs-down used to be signal-only (Gap 54) -- recorded, never acted on. It is
# now the entry point to a correction flow whose defining property is that the
# system does the comparison a human shouldn't have to:
#
#   wrong_data about one invoice -> diff what chat SAID against what is STORED.
#     mismatch -> chat misreported its own source data. Provably a chat bug.
#     match    -> chat reported the stored value faithfully, so the open question
#                 is whether the STORED value is right. Only a human looking at
#                 the PDF can answer that, and if the PDF disagrees this stops
#                 being a chat correction entirely and becomes an extraction one.
#   wrong_data about an aggregate, or wrong_interpretation -> structured category pick
#   bad_tone -> TenantChatSettings, not a rule at all
# ─────────────────────────────────────────────────────────────────────────────

TRIAGE_REASONS = frozenset({"wrong_data", "wrong_interpretation", "bad_tone"})

#: Fields the auto-diff can compare. Deliberately the stored scalar columns only --
#: diffing a JSON items blob against prose has no defensible definition of "match".
_DIFFABLE_FIELDS = {
    "vendor_name", "customer_name", "invoice_number", "po_number", "status",
    "grand_total", "tax_amount", "discount_amount", "currency",
    "invoice_date", "due_date",
}


def _normalize_for_diff(value) -> str:
    """Comparable form: numbers compare numerically, everything else as trimmed text.

    The numeric coercion matters and is not cosmetic: the stored column is a
    float (`110.0`) while the FE captures what the user saw as a string
    (`"110.00"`, or `"$110.00"` once stripped). Comparing those as raw strings
    reports a mismatch on two values that are plainly the same money, which
    would route a correct answer down the "chat misreported its data" branch and
    tell the user their assistant was wrong when it wasn't.
    """
    if value is None:
        return ""
    if hasattr(value, "isoformat"):
        return value.isoformat()
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return f"{float(value):.2f}".rstrip("0").rstrip(".")
    text_value = str(value).strip()
    # A string that is plainly a number is compared as one (after stripping the
    # thousands separators and currency symbols a rendered answer carries).
    candidate = text_value.replace(",", "").lstrip("$€£₹").strip()
    try:
        return f"{float(candidate):.2f}".rstrip("0").rstrip(".")
    except ValueError:
        return text_value.lower()


def _snapshot_invoices(message: ChatMessage, db_session: Session, tenant_id) -> list[dict]:
    """The invoices that fed this reply, from the Gap 231 snapshot."""
    ids = []
    for raw in (message.result_invoice_ids or []):
        try:
            ids.append(UUID(str(raw)))
        except (TypeError, ValueError):
            continue
    if not ids:
        return []
    rows = db_session.exec(
        select(Invoice).where(Invoice.tenant_id == tenant_id, Invoice.id.in_(ids))
    ).all()
    return [
        {
            "invoiceId": str(r.id),
            "invoiceNumber": r.invoice_number,
            "vendorName": r.vendor_name or r.customer_name,
            "grandTotal": r.grand_total,
            "currency": r.currency,
            "pdfUrl": f"/api/invoices/{r.id}/pdf",
        }
        for r in rows
    ]


def _triage_entry_point(message: ChatMessage, reason: str | None, db_session: Session, tenant_context) -> dict:
    """Decide which correction step this thumbs-down should open, and with what."""
    if reason == "bad_tone":
        # The lightest path by design: tone is already a first-class tenant
        # setting, so there is nothing to "learn" and no rule to create.
        return {
            "next": "chat_settings",
            "explanation": "Tone and length are tenant settings — no rule needed.",
            "settingsEndpoint": "/api/v1/trainer/chat-style",
        }

    invoices = _snapshot_invoices(message, db_session, tenant_context.tenant_id)
    if reason == "wrong_data":
        if len(invoices) == 1:
            return {
                "next": "diff_invoice",
                "explanation": "This answer came from one invoice — we can check it against what's stored.",
                "invoices": invoices,
                "diffableFields": sorted(_DIFFABLE_FIELDS),
            }
        if invoices:
            return {
                "next": "pick_invoice",
                "explanation": (
                    f"This answer drew on {len(invoices)} invoices. Pick the one that's wrong, "
                    "or continue if the problem is with the total rather than any one invoice."
                ),
                "invoices": invoices,
                "diffableFields": sorted(_DIFFABLE_FIELDS),
                "categories": list_chat_rule_categories(),
            }
        # No snapshot: never assert "no invoices were involved" -- say we don't know.
        return {
            "next": "category_pick",
            "explanation": (
                "We couldn't determine which invoices this answer used, so tell us what "
                "it got wrong about the question instead."
            ),
            "invoices": [],
            "categories": list_chat_rule_categories(),
        }

    return {
        "next": "category_pick",
        "explanation": "Tell us what the assistant got wrong about the question itself.",
        "invoices": invoices,
        "categories": list_chat_rule_categories(),
    }


@router.post("/messages/{message_id}/triage")
def triage_message(
    message_id: UUID,
    payload: TriagePayload,
    db_session: Session = Depends(get_db_session),
    tenant_context: TenantContext = Depends(get_tenant_context),
):
    """Feature 18: auto-diff what the reply said against what is actually stored.

    No human judgement is needed for this comparison -- it is a value diff -- so
    the system does it rather than asking the user "was the number right?", which
    is the question they came here unable to answer.

    Two ways to establish what chat claimed, in order of reliability:
      1. `claimed_value` supplied by the FE (what the user saw), compared directly.
      2. Otherwise: does the stored value appear verbatim in the reply text? If it
         does, chat reported its source faithfully. This is a containment check,
         not an interpretation, and it is reported as a distinct, weaker outcome
         so nothing downstream mistakes it for an exact comparison.
    """
    message = _get_owned_message(message_id, db_session, tenant_context)

    if not payload.invoice_id or not payload.field:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="invoice_id and field are both required to diff an answer against stored data.",
        )
    if payload.field not in _DIFFABLE_FIELDS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"field must be one of {sorted(_DIFFABLE_FIELDS)}.",
        )

    invoice = db_session.exec(
        select(Invoice).where(
            Invoice.id == payload.invoice_id,
            Invoice.tenant_id == tenant_context.tenant_id,
        )
    ).first()
    if not invoice:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Invoice not found or access denied.")

    stored_value = getattr(invoice, payload.field, None)
    stored_norm = _normalize_for_diff(stored_value)

    if payload.claimed_value is not None:
        claimed_norm = _normalize_for_diff(payload.claimed_value)
        outcome = "match" if claimed_norm == stored_norm else "mismatch"
        basis = "exact"
        claimed_display = payload.claimed_value
    else:
        found = bool(stored_norm) and stored_norm in (message.content or "").lower()
        outcome = "match" if found else "mismatch"
        basis = "reply_contains_stored_value"
        claimed_display = None

    diff = {
        "invoiceId": str(invoice.id),
        "field": payload.field,
        "storedValue": None if stored_value is None else str(stored_value),
        "claimedValue": claimed_display,
        "outcome": outcome,
        "basis": basis,
    }

    if outcome == "mismatch":
        # Chat misreported data it had. Provably a chat-side bug, so this routes
        # straight into the chat-behaviour rule path -- no human adjudication needed.
        return {
            "diff": diff,
            "next": "category_pick",
            "explanation": (
                "The assistant's answer doesn't match what's stored for this invoice — "
                "that's an answering bug, not a data problem."
            ),
            "categories": list_chat_rule_categories(),
        }

    # Chat reported the stored value faithfully. Whether that stored value is
    # itself correct is a question only the source document can settle.
    return {
        "diff": diff,
        "next": "confirm_against_pdf",
        "explanation": (
            "The assistant correctly reported what's stored for this invoice. Check the "
            "PDF: if the document says something different, the extraction is what needs "
            "fixing, not the assistant."
        ),
        "pdfUrl": f"/api/invoices/{invoice.id}/pdf",
        "verdictEndpoint": f"/api/v1/chat/messages/{message_id}/triage/source-verdict",
    }


@router.post("/messages/{message_id}/triage/source-verdict")
def triage_source_verdict(
    message_id: UUID,
    payload: SourceVerdictPayload,
    db_session: Session = Depends(get_db_session),
    tenant_context: TenantContext = Depends(get_tenant_context),
):
    """Feature 18: the fork where a chat complaint can become an extraction one.

    If the PDF disagrees with what's stored, this is **not a chat correction at
    all** -- teaching the chat agent anything here would paper over bad extracted
    data with a rule about how to talk about it. The response carries enough
    context (invoice id, field, the trainer endpoint) for the FE to open the
    extraction "flag as missed" flow pre-filled instead.
    """
    _get_owned_message(message_id, db_session, tenant_context)

    invoice = db_session.exec(
        select(Invoice).where(
            Invoice.id == payload.invoice_id,
            Invoice.tenant_id == tenant_context.tenant_id,
        )
    ).first()
    if not invoice:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Invoice not found or access denied.")

    if payload.pdf_agrees:
        return {
            "next": "category_pick",
            "explanation": (
                "The stored data matches the document, so the assistant had the right "
                "data and still gave you the wrong answer — tell us what it got wrong."
            ),
            "categories": list_chat_rule_categories(),
        }

    return {
        "next": "extraction_flag_missed",
        "explanation": (
            "The document disagrees with what we extracted. This is an extraction "
            "problem, not an answering one — train it on this invoice instead."
        ),
        "redirect": {
            "invoiceId": str(invoice.id),
            "field": payload.field,
            "flowDirection": invoice.flow_direction,
            "vendorName": invoice.vendor_name or invoice.customer_name,
            "sessionEndpoint": "/api/v1/trainer/sessions/from-invoice",
            "correctionEndpoint": "/api/v1/trainer/sessions/{session_id}/corrections/missed-alert",
            "alertTypesEndpoint": "/api/v1/trainer/alert-types?flaggable_only=true",
        },
    }


@router.get("/rules/categories")
def get_chat_rule_categories(
    tenant_context: TenantContext = Depends(get_tenant_context),
):
    """The closed vocabulary a chat correction is picked from (never free text)."""
    return {"categories": list_chat_rule_categories()}


@router.post("/rules/preview")
def preview_chat_rule(
    payload: ChatRulePayload,
    tenant_context: TenantContext = Depends(get_tenant_context),
):
    """Feature 18: same preview-before-commit principle as the extraction lane.

    A thumbs-down never silently saves a rule. The proposed rule is returned in
    the exact plain terms it will be injected as, and `/rules/commit` requires the
    matching token -- so what the user approved is provably what gets stored.

    No LLM is involved: `services/chat_rules.render_chat_rule()` is a deterministic
    template over a category pick, so this preview is the literal final text rather
    than a paraphrase of it.
    """
    error = validate_chat_rule(payload.category, payload.pattern)
    if error:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=error)

    rendered = render_chat_rule(payload.category, payload.pattern, payload.context_text)
    return {
        "previewToken": _chat_rule_token(payload.category, payload.pattern),
        "category": payload.category,
        "pattern": payload.pattern,
        "ruleText": rendered,
        "explanation": (
            "This will be added to the assistant's answering rules for your workspace. "
            "It affects how questions are scoped and filtered — it never changes your invoice data."
        ),
    }


def _chat_rule_token(category: str, pattern: str) -> str:
    import hashlib

    return hashlib.sha256(f"{category}|{(pattern or '').strip()}".encode("utf-8")).hexdigest()[:32]


@router.post("/rules/commit", status_code=status.HTTP_201_CREATED)
def commit_chat_rule(
    payload: ChatRulePayload,
    db_session: Session = Depends(get_db_session),
    tenant_context: TenantContext = Depends(require_can_train),
):
    """Persist a chat-behaviour rule. Gated on `can_train`.

    A `TenantChatRule` changes how every future answer for the whole workspace is
    scoped, so it is a training action even though it is reached from the Chat UI
    -- the same permission the Trainer's own rule commits require. Reading the
    triage flow and previewing a rule are deliberately NOT gated: anyone who can
    see a bad answer should be able to report it.

    Never touches `ExtractionTemplate.rules["constraints"]`.
    """
    error = validate_chat_rule(payload.category, payload.pattern)
    if error:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=error)

    expected = _chat_rule_token(payload.category, payload.pattern)
    if not payload.preview_token:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="A preview must be confirmed before a chat rule is saved.",
        )
    if payload.preview_token != expected:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This rule changed after the preview you approved. Preview it again, then confirm.",
        )

    rule = TenantChatRule(
        tenant_id=tenant_context.tenant_id,
        category=payload.category,
        pattern=(payload.pattern or "").strip(),
        context_text=(payload.context_text or "").strip(),
        created_by=tenant_context.user_id,
    )
    db_session.add(rule)
    db_session.commit()
    db_session.refresh(rule)

    # A new answering rule changes what future answers should say, and the answer
    # cache has no way to know that on its own -- same reasoning as Gap 213 on the
    # Trainer side. Best-effort: a failed flush is never a correctness problem.
    _invalidate_chat_answer_cache(str(tenant_context.tenant_id))

    return {
        "id": str(rule.id),
        "category": rule.category,
        "pattern": rule.pattern,
        "ruleText": render_chat_rule(rule.category, rule.pattern, rule.context_text),
        "enabled": rule.enabled,
    }


@router.get("/rules")
def list_chat_rules(
    db_session: Session = Depends(get_db_session),
    tenant_context: TenantContext = Depends(get_tenant_context),
):
    """The tenant's committed chat-behaviour rules, so they can be reviewed."""
    rows = db_session.exec(
        select(TenantChatRule)
        .where(TenantChatRule.tenant_id == tenant_context.tenant_id)
        .order_by(TenantChatRule.created_at.desc())
    ).all()
    return [
        {
            "id": str(r.id),
            "category": r.category,
            "pattern": r.pattern,
            "contextText": r.context_text,
            "ruleText": render_chat_rule(r.category, r.pattern, r.context_text),
            "enabled": r.enabled,
            "createdBy": r.created_by,
            "createdAt": r.created_at.isoformat() if r.created_at else None,
        }
        for r in rows
    ]


@router.delete("/rules/{rule_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_chat_rule(
    rule_id: UUID,
    db_session: Session = Depends(get_db_session),
    tenant_context: TenantContext = Depends(require_can_train),
):
    """Remove a chat-behaviour rule. Same permission as creating one."""
    rule = db_session.exec(
        select(TenantChatRule).where(
            TenantChatRule.id == rule_id,
            TenantChatRule.tenant_id == tenant_context.tenant_id,
        )
    ).first()
    if not rule:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Chat rule not found.")
    db_session.delete(rule)
    db_session.commit()
    _invalidate_chat_answer_cache(str(tenant_context.tenant_id))


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
