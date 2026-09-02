import json
import logging
import time
from fastapi import APIRouter, Depends, HTTPException, status, BackgroundTasks
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field, ConfigDict
from sqlmodel import Session, select
from uuid import UUID, uuid4
from datetime import datetime

import telemetry
from dependencies import (
    get_db_session,
    get_tenant_context,
    require_can_train,
    # Feature 25 (Gap 335): chat is reachable with an `inv_live_` key at either
    # scope. Asking a question about your own invoices is not a financial
    # action -- nothing here approves, sends or pays anything. The training
    # routes at the bottom of this file stay on require_can_train, consistent
    # with `actions` scope deliberately NOT granting can_train.
    get_tenant_or_api_key_context,
    TenantContext,
)
from models import ChatAttachment, ChatSession, ChatMessage, ChatFeedback, Invoice, TenantChatRule
from agents.query_agent import run_query_agent
from services.online_quality_judge import submit_turn_judgement
from utils.logging_config import request_id_ctx, trace_id_ctx
from services.chat_rules import (
    list_chat_rule_categories,
    render_chat_rule,
    validate_chat_rule,
)

import concurrent.futures

logger = logging.getLogger(__name__)
_chat_background_pool = concurrent.futures.ThreadPoolExecutor(max_workers=8, thread_name_prefix="chat-worker")


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


def charge_sandbox_chat_or_402(db_session: Session, tenant_id: UUID) -> dict | None:
    """Feature 25 (Gap 340): meter one chat turn for an unclaimed sandbox tenant.

    The HTTP half of `services/sandbox.py::charge_sandbox_chat_message()`, kept
    here rather than in the service so that module stays importable from the
    bare sweep process without dragging FastAPI's exception types into it -- the
    same split `services/billing_quota.py` does NOT make, and the reason it does
    not is that quota is only ever charged from a request. This one is not.

    WHY THIS EXISTS AT ALL. `services/billing_quota.py`'s free-tier charge meters
    **ingestion** and nothing else -- there is no quota anywhere in this backend
    covering chat or LLM calls. That was fine while every chat caller was an
    authenticated, paying-or-free tenant who had signed up. A sandbox key is
    handed to an anonymous visitor, so without this it is an unmetered path to
    real Azure OpenAI spend, funded by us, available to anyone who can click a
    button on the marketing site.

    Returns None for an ordinary tenant (nothing to meter), a dict for a sandbox
    one, and raises 402 when the sandbox allowance is spent. 402 rather than 429:
    this is an exhausted allowance, not a rate limit -- waiting does not help,
    signing up does, and the message says so.
    """
    from services.sandbox import charge_sandbox_chat_message

    result = charge_sandbox_chat_message(db_session, tenant_id)
    if result is not None and not result["allowed"]:
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail=(
                f"This sandbox workspace has used its {result['limit']} included "
                "chat messages. Sign up for a free workspace to keep going -- you "
                "can claim this sandbox and keep the invoices you have already "
                "uploaded."
            ),
        )
    return result

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
    # Feature 26 (Gap 366): an optional reference document (PO/quotation) the
    # user attached to this turn, uploaded beforehand via
    # POST /chat/sessions/{id}/attachments. Optional with a None default so
    # every existing caller and every existing test body stays valid unchanged.
    # Ownership/tenant scoping of the id is resolved in the agent's attachment
    # path against the DB -- this router does not widen it.
    attachment_id: UUID | None = None

class ChatJobResponse(BaseModel):
    """Gap 280: Async job enqueue response."""
    job_id: str
    message_id: str
    status: str = "queued"
    created_at: str | None = None

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
    created_at: datetime
    feedback: str | None = None  # Gap 54: "up" / "down" / None, so votes survive a reload
    status: str = "completed"  # Gap 280: 'queued' | 'processing' | 'completed' | 'failed'
    job_id: str | None = None  # Gap 280
    error_message: str | None = None  # Gap 280

    # Feature 26 task H16 / amendment B12 (Gap 386): the attached-document answer
    # contract (P2.8). Every key is Optional and every one defaults to None, so a
    # turn that is not an attachment turn serialises byte-identically to before
    # this change -- `exclude_none=True` on the model_dump below drops them
    # entirely rather than emitting a wall of nulls.
    #
    # These are FLATTENED out of `ChatMessage.attachment_payload` by
    # `_with_attachment_payload()` rather than nested under one key, because the
    # FE types were written against P2.8's wire shape months before the column
    # existed (`apps/invoice-fe/types/chat.ts:133/136/152`) and nesting would have
    # forced an FE change for a backend storage decision.
    attachment_confirmation: dict | None = None
    attachment_comparison: dict | None = None
    attachment_clarification: dict | None = None
    suggested_actions: list | None = None
    evidence: list | None = None
    needs_confirmation: bool | None = None
    # B10's three, declared now so the shape does not change again when H6b/H6c
    # land. The agent does not emit them yet; they stay absent until it does.
    line_items: list | None = None
    unmatched: dict | None = None
    reconciliation: dict | None = None

    model_config = ConfigDict(from_attributes=True)


# Feature 26 H16 (Gap 386). The keys the agent may put on an attachment turn.
# Kept as one tuple so the persist side and the serialise side cannot drift --
# a key added to the agent and to only one of these two lists is exactly how the
# contract silently loses a field again.
ATTACHMENT_CONTRACT_KEYS: tuple[str, ...] = (
    "attachment_confirmation",
    "attachment_comparison",
    "attachment_clarification",
    "suggested_actions",
    "evidence",
    "needs_confirmation",
    "line_items",
    "unmatched",
    "reconciliation",
)


def extract_attachment_payload(agent_output: dict) -> dict | None:
    """Pull the answer-contract keys out of an agent result, or None.

    None rather than {} when the turn produced no attachment keys: the column
    means "not an attachment turn" in that case, and an empty dict would read as
    "an attachment turn that answered nothing", which P2.8 defines as a bug
    rather than a state. Keys the agent did not emit are ABSENT rather than null
    -- P2.8's contract rule turns on absence (`attachment_comparison` absent on
    the content branch is the assertion that no comparison ran).
    """
    payload = {k: agent_output[k] for k in ATTACHMENT_CONTRACT_KEYS if k in agent_output}
    return payload or None


def _with_attachment_payload(msg: ChatMessage) -> dict:
    """Row -> MessageResponse kwargs, with the contract flattened back out."""
    data = {
        "id": msg.id,
        "session_id": msg.session_id,
        "role": msg.role,
        "content": msg.content,
        "generated_sql": msg.generated_sql,
        "citations": msg.citations or [],
        "created_at": msg.created_at,
        "feedback": getattr(msg, "feedback", None),
        "status": msg.status,
        "job_id": msg.job_id,
        "error_message": msg.error_message,
    }
    data.update(getattr(msg, "attachment_payload", None) or {})
    return data

@router.get("/sessions", response_model=list[SessionResponse])
def list_sessions(
    db_session: Session = Depends(get_db_session),
    tenant_context: TenantContext = Depends(get_tenant_or_api_key_context)
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
    tenant_context: TenantContext = Depends(get_tenant_or_api_key_context)
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
    tenant_context: TenantContext = Depends(get_tenant_or_api_key_context)
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
    tenant_context: TenantContext = Depends(get_tenant_or_api_key_context)
):
    """Delete a chat session and all its associated messages, feedback and attachments."""
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

    # Feature 26: attachments carry a real FK to `chatsession.id`, so they have
    # to go before the session does -- on Postgres, leaving them is a
    # ForeignKeyViolation and the delete fails outright; on SQLite it is a silent
    # orphan, which is worse. This is the ONE place in the product where a
    # ChatAttachment row is deleted today (task H8's TTL sweeper will be the
    # second), so it is also where the vector chunks have to be removed: the row
    # and its chunks in `chat_docs_{tenant_id}` are the same object stored twice,
    # and deleting only the row leaves a searchable document nothing can ever
    # reach or clean up (the reembed script scans `invoice_chunks_*` only and is
    # structurally blind to chat-doc collections).
    #
    # Chunk deletion is best-effort by design: `delete_attachment_chunks()` logs
    # and swallows its own errors, so an unreachable Chroma cannot turn "delete
    # my conversation" into a 500 on a request whose real subject is Postgres
    # rows. The residue in that case is orphaned chunks, which the sweeper can
    # still remove; the alternative residue is a session the user cannot delete.
    from services.chat_document_search import delete_attachment_chunks

    attachments = db_session.exec(
        select(ChatAttachment).where(ChatAttachment.session_id == session_id)
    ).all()
    for attachment in attachments:
        delete_attachment_chunks(attachment.id, attachment.tenant_id)
        db_session.delete(attachment)

    db_session.delete(chat_session)
    db_session.commit()

@router.get("/sessions/{session_id}", response_model=list[MessageResponse])
def get_session_messages(
    session_id: UUID,
    db_session: Session = Depends(get_db_session),
    tenant_context: TenantContext = Depends(get_tenant_or_api_key_context)
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

    # Feature 26 H16 (Gap 386): `_with_attachment_payload()` rather than
    # `model_validate(m)` -- the contract is stored as one `attachment_payload`
    # dict on the row but serialises FLAT, per P2.8's wire shape, so it has to be
    # spread back out here. `model_validate` reads attributes and would find no
    # `attachment_confirmation` on the row, silently returning a reload with no
    # confirmation card: the exact symptom Gap 386 exists to fix, reintroduced one
    # layer down. This is the reload path P2.6.6 depends on.
    return [
        MessageResponse(**{**_with_attachment_payload(m), "feedback": feedback_by_message.get(m.id)})
        for m in messages
    ]

@router.post("/sessions/{session_id}/message")
def post_chat_message(
    session_id: UUID,
    payload: MessageCreate,
    background_tasks: BackgroundTasks,
    sync: bool = False,
    db_session: Session = Depends(get_db_session),
    tenant_context: TenantContext = Depends(get_tenant_or_api_key_context)
):
    """Post a new message in a chat session.

    Gap 280 added an async queue path (enqueue, return HTTP 202 + job_id
    immediately, worker processes in the background). Gated behind
    settings.ENABLE_ASYNC_CHAT_QUEUE (default False) rather than being the
    unconditional default -- see that setting's docstring in config.py for
    why. sync=True forces the synchronous path even when the flag is on,
    kept for the legacy test suites that already relied on it.
    """
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

    # Feature 25 (Gap 340): meter the turn if this is an unclaimed sandbox
    # workspace. Charged BEFORE anything is generated -- see
    # services/sandbox.py::charge_sandbox_chat_message() for why metering after
    # the model call is the wrong order. Costs one indexed lookup and returns
    # None for every ordinary tenant, which is all of them.
    charge_sandbox_chat_or_402(db_session, tenant_context.tenant_id)

    # Auto-generate session title if it uses the default placeholder or timestamp format
    new_title = None
    original_title = chat_session.title  # Gap 364: restored if the turn is rejected
    if chat_session.title.startswith("Chat Session -") or chat_session.title == "New Chat":
        words = payload.content.strip().split()
        if words:
            new_title = " ".join(words[:6])
            if len(words) > 6:
                new_title += "..."
            chat_session.title = new_title
            db_session.add(chat_session)

    from config import get_settings
    # Feature 26 (Gap 366): an attached-document turn runs synchronously. The
    # queue path carries only (session_id, user_msg_id, content, tenant_id,
    # job_id) -- `ChatQueueService.enqueue_chat_job()` and
    # `handle_process_chat_job()` have no attachment parameter -- so enqueuing
    # one would drop the attachment on the floor and answer the question as an
    # ordinary chat turn, which is worse than answering it a bit more slowly.
    # Threading the id through the worker is its own change to those two files
    # and is deliberately not done here.
    use_async_queue = (
        get_settings().ENABLE_ASYNC_CHAT_QUEUE
        and not sync
        and payload.attachment_id is None
    )
    if use_async_queue:
        # Gap 280: Asynchronous Queue-based Dispatch
        from services.chat_queue import ChatQueueCapacityError, ChatQueueService
        from queue_worker.handlers import handle_process_chat_job

        job_id = str(uuid4())
        user_msg = ChatMessage(
            id=uuid4(),
            session_id=session_id,
            role="user",
            content=payload.content,
            status="queued",
            job_id=job_id,
        )
        db_session.add(user_msg)
        db_session.commit()
        db_session.refresh(user_msg)

        try:
            ChatQueueService.enqueue_chat_job(
                session_id=str(session_id),
                user_msg_id=str(user_msg.id),
                content=payload.content,
                tenant_id=str(tenant_context.tenant_id),
                job_id=job_id,
            )
        except ChatQueueCapacityError as exc:
            # Gap 364: the tenant is at PER_TENANT_MAX_ACTIVE_CHAT. Undo the row
            # staged a few lines up before answering, so a rejected turn leaves
            # no `queued` ChatMessage that no worker will ever finish -- the
            # session list renders those as a turn stuck thinking forever.
            #
            # Deviation from the task's preferred shape, stated rather than
            # hidden: the row is still written *before* the enqueue and deleted
            # on rejection, not written after a successful enqueue. Writing it
            # afterwards would open a real race on the other call path --
            # `queue_worker/main_worker.py` runs in a different process and can
            # pop the job off `chat_tasks_queue` between the `lpush` and this
            # process's commit, and `handle_process_chat_job` would then find no
            # user row to move off `queued` (handlers.py L1059-1068 logs and
            # continues), producing the exact orphan this is meant to prevent.
            # Net effect on the rejection path is identical: no orphan row.
            db_session.delete(user_msg)
            # The title was rewritten from this message's text further up; a
            # turn that was never accepted should not have renamed the session.
            if new_title:
                chat_session.title = original_title
                db_session.add(chat_session)
            db_session.commit()

            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=(
                    f"You already have {exc.limit} chat turns running in this "
                    "workspace. Wait for one to finish and try again."
                ),
                headers={"Retry-After": str(exc.retry_after_seconds)},
            )

        # Immediate asynchronous background executor (sub-millisecond handoff).
        #
        # Gap 302/304 attribution fix: `ThreadPoolExecutor.submit()` does not
        # copy contextvars, so before this the whole queued turn ran on a pool
        # thread where `trace_id_ctx`/`tenant_id_ctx`/`request_id_ctx` were all
        # empty -- every `llm_agent_call` it emitted, and every judge call it
        # went on to submit, landed in `customEvents` with `trace_id=""`. The
        # IDs are passed explicitly and re-bound inside the handler, the same
        # shape `queue_worker/main_worker.py::_process_message` uses for the
        # real queue path, rather than `copy_context().run(...)`: copying the
        # whole context would also carry the OpenTelemetry span context, which
        # would silently re-parent this turn's dependency spans under an HTTP
        # request that has already returned 202.
        _chat_background_pool.submit(
            handle_process_chat_job,
            job_id=job_id,
            session_id=str(session_id),
            user_msg_id=str(user_msg.id),
            content=payload.content,
            tenant_id=str(tenant_context.tenant_id),
            trace_id=trace_id_ctx.get(),
            request_id=request_id_ctx.get(),
        )

        return JSONResponse(
            status_code=status.HTTP_202_ACCEPTED,
            content={
                "job_id": job_id,
                "message_id": str(user_msg.id),
                "status": "queued",
                "created_at": user_msg.created_at.isoformat() if user_msg.created_at else None,
            },
        )

    # Synchronous Execution Path (for legacy/sync callers)
    assistant_msg = run_sync_chat_turn(
        session_id=session_id,
        content=payload.content,
        tenant_id=tenant_context.tenant_id,
        db_session=db_session,
        chat_session=chat_session,
        new_title=new_title,
        attachment_id=str(payload.attachment_id) if payload.attachment_id else None,
    )

    # Feature 26 H16 (Gap 386): flatten the stored contract back onto the wire,
    # exactly as the reload path does. `model_validate(assistant_msg)` reads
    # attributes off the row and would find no `attachment_confirmation` there --
    # the contract lives in the row's `attachment_payload` dict -- so it returned
    # every key as null. That is Gap 386 surviving its own fix, one layer down,
    # and it is why V-27 asserts on the response body rather than on the agent.
    return MessageResponse(**_with_attachment_payload(assistant_msg))


def run_sync_chat_turn(
    *,
    session_id: UUID,
    content: str,
    tenant_id: UUID,
    db_session: Session,
    chat_session: ChatSession | None = None,
    new_title: str | None = None,
    attachment_id: str | None = None,
) -> ChatMessage:
    """One complete synchronous chat turn: persist, answer, persist, observe.

    Extracted verbatim out of `post_chat_message()`'s synchronous branch by Gap
    341 so the widget chat route (`routers/widget.py`) runs the **same** turn
    rather than a second copy of it. Two copies is how the quality judge, the
    turn telemetry, and the agent's error-path fallback drift apart between the
    dashboard and the widget -- and a widget turn that emits no telemetry is
    invisible in exactly the surface where an anonymous end user is talking to
    the product.

    Nothing about the behaviour changed in the extraction: the ordering (commit
    before judging and before `track_chat_turn`, so `message_id` names a row
    that exists), the rollback-and-re-add on an agent exception, and the
    conditional title write are all as they were. `chat_session`/`new_title` are
    optional because the widget path has no title to auto-generate.

    Feature 26 (Gap 366): `attachment_id` is likewise optional and is passed
    straight through to `run_query_agent()`, whose pre-route gate takes the
    attached-document branch when it is set. Nothing about the turn's own
    ordering or persistence changes.
    """
    user_msg = ChatMessage(
        id=uuid4(),
        session_id=session_id,
        role="user",
        content=content,
        status="completed",
    )
    db_session.add(user_msg)

    # Gap 304 half (2): the turn's own wall clock, so a production
    # `agent_eval_run` row carries a real `latency_ms` instead of a 0.0 that
    # would average into the golden bank's latency series as a free turn.
    turn_started = time.perf_counter()
    try:
        agent_output = run_query_agent(
            session_id=str(session_id),
            user_message=content,
            tenant_id=str(tenant_id),
            db_session=db_session,
            attachment_id=attachment_id,
        )
    except Exception as e:
        logger.error("run_query_agent failed unexpectedly for session %s: %s", session_id, e)
        db_session.rollback()
        agent_output = {
            "content": "Sorry, something went wrong answering that — please try again.",
            "generated_sql": None,
            "citations": [],
            "result_invoice_ids": [],
            # Gap 302: a turn that blew up inside the agent still has to appear
            # in the turn stream -- this is the one outcome that previously
            # produced no telemetry of any kind, and an error rate cannot be
            # computed from events that were never emitted. `run_query_agent()`
            # raised, so its own accumulator never reached the caller; this is
            # the minimum honest record of what happened.
            "turn_telemetry": {
                "status": telemetry.TURN_STATUS_ERROR,
                "route": "unknown",
                "error_type": type(e).__name__,
                "stop_reason": "agent_raised",
                "session_id": str(session_id),
                "tenant_id": str(tenant_id),
            },
        }

    turn_latency_ms = (time.perf_counter() - turn_started) * 1000.0

    if user_msg not in db_session:
        db_session.add(user_msg)
    if new_title is not None and chat_session is not None and chat_session.title != new_title:
        chat_session.title = new_title
        db_session.add(chat_session)

    assistant_msg = ChatMessage(
        id=uuid4(),
        session_id=session_id,
        role="assistant",
        content=agent_output["content"],
        generated_sql=agent_output["generated_sql"],
        citations=agent_output["citations"],
        result_invoice_ids=agent_output.get("result_invoice_ids") or [],
        status="completed",
        # Feature 26 H16 (Gap 386): persist the answer contract with the turn that
        # produced it. Before this, every attachment key the agent computed was
        # dropped here and again at serialisation.
        attachment_payload=extract_attachment_payload(agent_output),
    )
    db_session.add(assistant_msg)
    db_session.commit()
    db_session.refresh(assistant_msg)

    # Gap 304 half (2): score this turn with the golden bank's own judge, off the
    # response path. After the commit, so `message_id` points at a row that
    # exists; on the background pool, so the two judge model calls happen after
    # the user already has their answer. Fire and forget by construction -- the
    # future is not held, and `submit_turn_judgement()` is a no-op with
    # `ENABLE_PRODUCTION_QUALITY_JUDGE` off (the default) and never raises.
    submit_turn_judgement(
        question=content,
        answer=assistant_msg.content,
        evidence=agent_output.get("judge_evidence"),
        generated_sql=agent_output.get("generated_sql"),
        tenant_id=str(tenant_id),
        message_id=str(assistant_msg.id),
        latency_ms=turn_latency_ms,
        # Gap 304 attribution fix: the judge's two model calls run on the same
        # pool and inherit no contextvars, so without these `eval.combined_soft`
        # and `eval.persona` landed in `customEvents` with empty trace/tenant/
        # request ids on every judged turn -- a score that could not be joined
        # back to the turn it scored.
        trace_id=trace_id_ctx.get(),
        request_id=request_id_ctx.get(),
    )

    # Gap 302/303: the Trace. Same hook point and same reasoning as the judging
    # call above -- after the commit, so `message_id` points at a row that
    # exists. Unlike judging this is *not* flag-gated and fires on every outcome
    # including declined, errored and cache-hit turns, because those three are
    # exactly the ones that had no telemetry before and are the whole point.
    telemetry.track_chat_turn(
        **(agent_output.get("turn_telemetry") or {}),
        message_id=str(assistant_msg.id),
        latency_ms=turn_latency_ms,
    )

    return assistant_msg


def _require_owned_chat_job(
    job_id: str, db_session: Session, tenant_context: TenantContext
) -> None:
    """Confirm `job_id` belongs to the requesting tenant, or 404/403.

    -----------------------------------------------------------------------
    Gap 341 (the item found while security-reviewing the widget token).
    -----------------------------------------------------------------------
    `get_chat_job_status()` and `stream_chat_job()` both took a `tenant_context`
    dependency and then **never used it**. They authenticated the caller and
    checked nothing else, so any authenticated caller who learned a `job_id`
    could read another tenant's chat answer -- the generated SQL, the citations
    and the assistant's full reply, all of which are that tenant's invoice data.
    Every other handler in this router does the ownership check (see
    `_get_owned_message()` and the session handlers); these two were the
    exception.

    It was dormant, not exploited: `ENABLE_ASYNC_CHAT_QUEUE` defaults False, so
    no job ids exist to guess in a default deployment. It is fixed now anyway
    and **before** anything to do with the widget lands, because a widget token
    is a credential that lives in a customer's public page source -- the
    threshold for "an authenticated caller" drops to "anyone who viewed the
    page", and a dormant cross-tenant read is not something to leave sitting
    behind a flag once that is true.

    Ownership is resolved through the database rather than through the Redis
    status payload. `enqueue_chat_job()` does put `tenant_id` in that payload,
    but `complete_job()` and `fail_job()` overwrite the cached blob with one
    that has no tenant in it, so a finished job's cache entry cannot answer this
    question at all. `ChatMessage.job_id` -> `session_id` -> `ChatSession.
    tenant_id` is written before the enqueue and is authoritative.

    An unknown job id is a 404, not a 403: a caller must not be able to probe
    which job ids exist on other tenants by reading the status code.
    """
    message = db_session.exec(
        select(ChatMessage).where(ChatMessage.job_id == job_id)
    ).first()
    if message is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Chat job not found.",
        )

    chat_session = db_session.exec(
        select(ChatSession).where(ChatSession.id == message.session_id)
    ).first()
    if chat_session is None or chat_session.tenant_id != tenant_context.tenant_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access forbidden to this chat job.",
        )


@router.get("/jobs/{job_id}/status")
def get_chat_job_status(
    job_id: str,
    db_session: Session = Depends(get_db_session),
    tenant_context: TenantContext = Depends(get_tenant_or_api_key_context),
):
    """Gap 280: Polling endpoint for checking the status and result of a chat turn."""
    from services.chat_queue import ChatQueueService

    # Gap 341: this handler took `tenant_context` and never used it. See
    # _require_owned_chat_job().
    _require_owned_chat_job(job_id, db_session, tenant_context)

    return ChatQueueService.get_job_status(job_id, db_session=db_session)


@router.get("/jobs/{job_id}/stream")
async def stream_chat_job(
    job_id: str,
    db_session: Session = Depends(get_db_session),
    tenant_context: TenantContext = Depends(get_tenant_or_api_key_context),
):
    """Gap 280: Server-Sent Events (SSE) stream for real-time chat progress and result.
    Yields events: data: {"job_id": "...", "status": "processing", "step": "...", "details": ...}\n\n
    """
    import asyncio

    # Gap 341: same missing ownership check as the status endpoint above, and
    # the more serious of the two -- this one streams the full result payload.
    # Raised BEFORE the StreamingResponse is constructed, deliberately: an
    # HTTPException raised inside `event_generator()` would arrive after the 200
    # and the response headers were already on the wire, i.e. as a broken stream
    # rather than as a 403.
    _require_owned_chat_job(job_id, db_session, tenant_context)

    from services.chat_queue import (
        get_redis_client,
        CHAT_JOB_CHANNEL_PREFIX,
        ChatQueueService,
    )

    async def event_generator():
        r = get_redis_client()
        # 1. First check if job is already finished
        cur_status = ChatQueueService.get_job_status(job_id, db_session=db_session)
        if cur_status.get("status") in ("completed", "failed"):
            yield f"data: {json.dumps(cur_status)}\n\n"
            return

        yield f"data: {json.dumps({'job_id': job_id, 'status': 'queued', 'step': 'queued'})}\n\n"

        if not r:
            # Polling fallback if Redis client is unavailable
            for _ in range(40):
                await asyncio.sleep(1.5)
                st = ChatQueueService.get_job_status(job_id, db_session=db_session)
                yield f"data: {json.dumps(st)}\n\n"
                if st.get("status") in ("completed", "failed"):
                    return
            return

        # 2. Redis Pub/Sub listener
        pubsub = r.pubsub()
        channel_name = f"{CHAT_JOB_CHANNEL_PREFIX}{job_id}"
        pubsub.subscribe(channel_name)

        try:
            timeout_seconds = 120
            start_time = asyncio.get_event_loop().time()

            while True:
                message = pubsub.get_message(ignore_subscribe_messages=True, timeout=0.4)
                if message and message.get("data"):
                    raw_data = message["data"]
                    yield f"data: {raw_data}\n\n"
                    try:
                        parsed = json.loads(raw_data)
                        if parsed.get("status") in ("completed", "failed"):
                            break
                    except Exception:
                        pass

                # Check Redis status cache periodically in case event was missed
                cur = ChatQueueService.get_job_status(job_id)
                if cur.get("status") in ("completed", "failed"):
                    yield f"data: {json.dumps(cur)}\n\n"
                    break

                if asyncio.get_event_loop().time() - start_time > timeout_seconds:
                    yield f"data: {json.dumps({'job_id': job_id, 'status': 'failed', 'error': 'Stream timeout'})}\n\n"
                    break

                await asyncio.sleep(0.2)
        finally:
            try:
                pubsub.unsubscribe(channel_name)
                pubsub.close()
            except Exception:
                pass

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


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
