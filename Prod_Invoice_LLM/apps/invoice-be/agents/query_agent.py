import json
import logging
import re
from pydantic import BaseModel, Field
from sqlalchemy import text
from utils.llm import get_llm
from chroma_client import query_invoice_chunks

logger = logging.getLogger(__name__)

# Task 6.11: semantic/result caching. Repeated or near-identical questions get served
# instantly from Redis instead of re-running retrieval + LLM synthesis, keyed on
# (tenant_id, normalized_query) — same key shape originally planned for the
# chat_qa_shortcuts Postgres table (Database_Schema_Document.md), but this
# supersedes that approach per feature_6_rag.md's own decision. Only SQL/RAG route
# results are cached (real retrieval+synthesis work); CHAT route (casual chat) and
# failed lookups are never cached, so a transient error doesn't get served for an hour.
CACHE_TTL_SECONDS = 3600


def _get_redis_client():
    import redis
    from config import get_settings
    return redis.Redis.from_url(get_settings().REDIS_URL, decode_responses=True)


def _normalize_query(user_message: str) -> str:
    return re.sub(r"\s+", " ", user_message.strip().lower())


def _cache_key(tenant_id: str, user_message: str) -> str:
    return f"chat_answer_cache:{tenant_id}:{_normalize_query(user_message)}"


def get_cached_answer(tenant_id: str, user_message: str) -> dict | None:
    try:
        raw = _get_redis_client().get(_cache_key(tenant_id, user_message))
        return json.loads(raw) if raw else None
    except Exception as e:
        logger.warning("Chat answer cache lookup failed, proceeding without cache: %s", e)
        return None


def set_cached_answer(tenant_id: str, user_message: str, result: dict) -> None:
    try:
        _get_redis_client().set(_cache_key(tenant_id, user_message), json.dumps(result), ex=CACHE_TTL_SECONDS)
    except Exception as e:
        logger.warning("Chat answer cache write failed: %s", e)

class QueryRoutingSchema(BaseModel):
    model_config = {"extra": "forbid"}
    route: str = Field(description="The target route for this query. Must be exactly 'RAG', 'SQL', or 'CHAT'")
    reasoning: str = Field(description="Brief reason explaining the routing decision.")

class SQLGenerationSchema(BaseModel):
    model_config = {"extra": "forbid"}
    sql: str = Field(description="The exact read-only SELECT SQL statement to execute. Must filter strictly by tenant_id.")

def classify_query(query: str) -> str:
    """Classifies user queries into RAG, SQL, or CHAT."""
    llm = get_llm()
    try:
        structured_llm = llm.with_structured_output(QueryRoutingSchema)
        result = structured_llm.invoke(
            f"Determine the routing logic for this user message: '{query}'. "
            "SQL: For ANY lookup of a structured invoice field on the 'invoice' table - "
            "this includes not just quantitative checks (total spent, count of invoices, "
            "averages, sums) but also plain field lookups like vendor name, invoice/due "
            "date, PO number, or status, even when phrased as 'who'/'what' questions "
            "(e.g. 'who is the vendor on invoice X' is SQL, not RAG - vendor_name is a "
            "column, not free-text document content). "
            "RAG: For semantic queries about content that is NOT a structured column - "
            "line-item descriptions, what a document says about something, or anything "
            "requiring reading the actual invoice text rather than a database field. "
            "CHAT: For casual greeting, feedback, or general chats."
        )
        return result.route.upper()
    except Exception as e:
        logger.warning("Routing classification failed: %s. Using keyword fallback.", e)
        q = query.lower()
        if any(kw in q for kw in ["total", "spent", "sum", "average", "how many", "count", "mean", "min", "max", "date", "status", "vendor", "po number", "purchase order"]):
            return "SQL"
        if any(kw in q for kw in ["hello", "hi ", "hey", "who are you", "what is your name"]):
            return "CHAT"
        return "RAG"

# Columns sourced from OCR/LLM extraction, where the LLM-generated SQL's exact-match
# equality is prone to case/whitespace drift against the stored value (e.g. the model
# writes `invoice_number = 'uk-20260722-007'` while the stored value has different
# casing, or picks up incidental whitespace). `status` is deliberately excluded — it's
# an enum our own code writes, not something sourced from a document, so exact match
# is correct and loosening it would risk matching the wrong status.
_FUZZY_STRING_COLUMNS = ("invoice_number", "vendor_name", "po_number")

# Matches an invoice-number-shaped token in a user's question, e.g. "US-20260722-001",
# "INDIA-20260722-003" — used only as a deterministic fallback when the LLM-generated
# SQL finds nothing, not as the primary lookup mechanism.
_INVOICE_NUMBER_PATTERN = re.compile(r"\b[A-Za-z]{2,}-\d{4,}-\d{2,}\b")


def _normalize_string_equality(sql: str) -> str:
    """Rewrite `column = 'value'` to a case-insensitive, trimmed comparison for
    OCR/LLM-sourced text columns, so exact-match SQL generated by the LLM doesn't
    silently miss rows over incidental case/whitespace differences."""
    for column in _FUZZY_STRING_COLUMNS:
        pattern = re.compile(rf"\b{column}\s*=\s*'([^']*)'", re.IGNORECASE)
        sql = pattern.sub(
            lambda m, col=column: f"TRIM(LOWER({col})) = TRIM(LOWER('{m.group(1)}'))",
            sql,
        )
    return sql


def _find_invoice_number_candidate(user_message: str) -> str | None:
    match = _INVOICE_NUMBER_PATTERN.search(user_message)
    return match.group(0) if match else None


def lookup_invoice_by_number_fallback(candidate: str, tenant_id: str, db_session) -> str | None:
    """Deterministic, non-LLM safety net: a direct case-insensitive/trimmed lookup by
    invoice_number, used only when the LLM-generated SQL found zero rows for a question
    that plainly names a specific invoice. Bypasses free-form SQL generation entirely,
    so it isn't subject to whatever formatting quirk caused the miss."""
    result = db_session.execute(
        text(
            "SELECT invoice_number, vendor_name, grand_total, status, invoice_date "
            "FROM invoice WHERE tenant_id = :tenant_id "
            "AND TRIM(LOWER(invoice_number)) = TRIM(LOWER(:candidate))"
        ),
        {"tenant_id": str(tenant_id), "candidate": candidate},
    )
    rows = result.fetchall()
    if not rows:
        return None

    keys = list(result.keys())
    header = " | ".join(keys)
    separator = " | ".join(["---"] * len(keys))
    markdown_rows = [
        " | ".join(str(val) if val is not None else "" for val in row) for row in rows
    ]
    return f"\n\n{header}\n{separator}\n" + "\n".join(markdown_rows)


def execute_generated_sql(sql: str, tenant_id: str, db_session) -> str:
    """Safely execute generated SQL statement on the database session."""
    sql_clean = sql.strip().strip("`").strip()
    if sql_clean.lower().startswith("sql"):
        sql_clean = sql_clean[3:].strip()

    sql_clean = _normalize_string_equality(sql_clean)
    sql_lower = sql_clean.lower()
    
    # Safety Check 1: Mutating keywords (word-boundary match, not substring — a bare substring
    # check false-positives on read-only SELECTs referencing a matching column name, e.g.
    # Invoice.created_at contains "create". Gap 32.)
    mutating = ["insert", "update", "delete", "drop", "alter", "create", "replace", "truncate"]
    if any(re.search(rf"\b{kw}\b", sql_lower) for kw in mutating):
        raise ValueError("Mutating SQL operations are strictly forbidden.")
        
    # Safety Check 2: Must be a SELECT query
    if not sql_lower.startswith("select"):
        raise ValueError("Only read-only SELECT queries are permitted.")
        
    # Safety Check 3: Tenant UUID must be present in query text
    if str(tenant_id) not in sql_clean:
        raise ValueError("Access Denied: SQL query does not contain tenant isolation filter.")
        
    result = db_session.execute(text(sql_clean))
    rows = result.fetchall()
    
    if not rows:
        return "No records found matching the query criteria."
        
    # Format rows as Markdown Table
    keys = list(result.keys())
    header = " | ".join(keys)
    separator = " | ".join(["---"] * len(keys))
    markdown_rows = []
    for row in rows:
        markdown_rows.append(" | ".join(str(val) if val is not None else "" for val in row))
        
    return f"\n\n{header}\n{separator}\n" + "\n".join(markdown_rows)

def get_chat_history(session_id: str, db_session, limit: int = 10) -> str:
    """Retrieve short-term conversational context from the database."""
    from models import ChatMessage
    from sqlmodel import select
    from uuid import UUID
    
    try:
        sess_uuid = UUID(session_id)
    except ValueError:
        return ""

    try:
        statement = (
            select(ChatMessage)
            .where(ChatMessage.session_id == sess_uuid)
            .order_by(ChatMessage.created_at.desc())
            .limit(limit)
        )
        messages = db_session.exec(statement).all()
        messages.reverse()

        history_str = ""
        for m in messages:
            history_str += f"{m.role.capitalize()}: {m.content}\n"
        return history_str
    except Exception as e:
        # Gap 37: this query previously had no failure guard at all, so any
        # transient DB hiccup here (unlike every LLM-call branch below, which
        # already has its own try/except) propagated all the way up through
        # run_query_agent as a raw, unhandled 500 instead of degrading
        # gracefully. Missing history is recoverable — proceed without it
        # rather than fail the whole request.
        logger.warning("Failed to load chat history for session %s: %s", session_id, e)
        return ""

def run_query_agent(session_id: str, user_message: str, tenant_id: str, db_session) -> dict:
    """
    RAG Query Agent routing natural language inputs to semantic context indexers,
    safe database queries, or conversational chat saves with multi-turn short-term memory.
    """
    logger.info("Executing Query Agent for session %s, tenant %s", session_id, tenant_id)

    cached = get_cached_answer(tenant_id, user_message)
    if cached is not None:
        logger.info("Serving cached answer for tenant %s (Task 6.11 semantic cache hit)", tenant_id)
        return cached

    # Retrieve short-term context history
    chat_history = get_chat_history(session_id, db_session)

    # 1. Routing classification
    route = classify_query(user_message)
    logger.info("Selected Route: %s", route)

    llm = get_llm()
    response_text = ""
    generated_sql = None
    citations = []
    route_succeeded = False

    if route == "SQL":
        system_prompt = f"""You are a database SQL query expert.
Given the 'invoice' table schema:
- id: UUID (Primary Key)
- tenant_id: UUID
- batch_id: UUID
- file_path: VARCHAR(1024)
- vendor_name: VARCHAR
- grand_total: FLOAT
- invoice_number: VARCHAR
- invoice_date: DATE
- due_date: DATE
- tax_amount: FLOAT
- po_number: VARCHAR
- status: VARCHAR (e.g. 'COMPLETED', 'AUDIT_REQUIRED', 'PROCESSING')
- created_at: DATETIME

Write a SQL query to answer the user's question. 
CRITICAL RULES:
1. You MUST filter by tenant_id = '{tenant_id}'.
2. You MUST only generate a read-only SELECT statement.

Conversation History for Context:
{chat_history}
"""
        try:
            structured_sql = llm.with_structured_output(SQLGenerationSchema)
            res = structured_sql.invoke(f"{system_prompt}\nUser Question: {user_message}")
            generated_sql = res.sql
            logger.info("Generated SQL: %s", generated_sql)
            
            # Execute SQL
            db_result = execute_generated_sql(generated_sql, tenant_id, db_session)

            # Deterministic fallback: if the LLM-generated SQL found nothing but the
            # question plainly names a specific invoice, try a direct trimmed/
            # case-insensitive lookup before giving up. Catches whatever formatting
            # quirk (extra clause, wrong join, subtly malformed literal) caused the
            # generated SQL to miss an invoice that does exist.
            if db_result == "No records found matching the query criteria.":
                candidate = _find_invoice_number_candidate(user_message)
                if candidate:
                    fallback_result = lookup_invoice_by_number_fallback(candidate, tenant_id, db_session)
                    if fallback_result:
                        logger.info("SQL route found 0 rows; direct invoice_number fallback matched '%s'", candidate)
                        db_result = fallback_result

            # Formulate final output matching the raw numbers
            summary_prompt = f"""Format a friendly summary explaining these database query results:
Results:
{db_result}

User Query: {user_message}
"""
            final_res = llm.invoke(summary_prompt)
            response_text = final_res.content + f"\n\n### Query Results\n{db_result}"
            route_succeeded = True
        except Exception as e:
            logger.error("SQL path execution failed: %s", e)
            response_text = f"Failed to execute database check: {str(e)}"
            
    elif route == "RAG":
        # Vector search (Long-term semantic facts)
        chunks = query_invoice_chunks(tenant_id, user_message, limit=5)
        
        context_str = ""
        for chunk in chunks:
            context_str += f"--- CHUNK ---\n{chunk['document']}\n"
            citations.append({
                "invoice_id": chunk["metadata"].get("invoice_id"),
                "vendor_name": chunk["metadata"].get("vendor_name"),
                "page": chunk["metadata"].get("page")
            })
            
        system_prompt = f"""You are an assistant answering questions about invoice documents.
Use the following extracted context chunks and short-term conversation history to answer the user's query.

Extracted Document Context (Long-term Facts):
{context_str}

Conversation History (Short-term context):
{chat_history}
"""
        try:
            res = llm.invoke(f"{system_prompt}\nUser Query: {user_message}")
            response_text = res.content
            
            # Append clean formatted citations list to answer text
            if citations:
                unique_citations = []
                seen = set()
                for c in citations:
                    key = (c["invoice_id"], c["page"])
                    if key not in seen:
                        seen.add(key)
                        unique_citations.append(c)
                
                citation_links = []
                for uc in unique_citations:
                    link = f"[Source: {uc['vendor_name']} (Page {uc['page']})](file:///api/v1/invoices/{uc['invoice_id']}/pdf)"
                    citation_links.append(link)
                
                response_text += "\n\n**Citations:**\n" + ", ".join(citation_links)
            route_succeeded = True
        except Exception as e:
            logger.error("RAG path execution failed: %s", e)
            response_text = f"Failed to run document lookup: {str(e)}"
            
    else:  # CHAT
        system_prompt = f"""You are a helpful assistant for an AI Invoice Processing platform. Keep your conversation brief, polite, and directly address the user's message.

Conversation History:
{chat_history}
"""
        try:
            res = llm.invoke(f"{system_prompt}\nUser Message: {user_message}")
            response_text = res.content
        except Exception as e:
            logger.error("Chat path execution failed: %s", e)
            response_text = f"Error generating message response: {str(e)}"
            
    result = {
        "content": response_text,
        "generated_sql": generated_sql,
        "citations": citations
    }

    if route in ("SQL", "RAG") and route_succeeded:
        set_cached_answer(tenant_id, user_message, result)

    return result
