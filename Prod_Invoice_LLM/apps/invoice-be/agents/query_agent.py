import logging
from pydantic import BaseModel, Field
from sqlalchemy import text
from utils.llm import get_llm
from chroma_client import query_invoice_chunks

logger = logging.getLogger(__name__)

class QueryRoutingSchema(BaseModel):
    route: str = Field(description="The target route for this query. Must be exactly 'RAG', 'SQL', or 'CHAT'")
    reasoning: str = Field(description="Brief reason explaining the routing decision.")

class SQLGenerationSchema(BaseModel):
    sql: str = Field(description="The exact read-only SELECT SQL statement to execute. Must filter strictly by tenant_id.")

def classify_query(query: str) -> str:
    """Classifies user queries into RAG, SQL, or CHAT."""
    llm = get_llm(temperature=0.0)
    try:
        structured_llm = llm.with_structured_output(QueryRoutingSchema)
        result = structured_llm.invoke(
            f"Determine the routing logic for this user message: '{query}'. "
            "RAG: For semantic queries about invoice line details or items descriptions. "
            "SQL: For quantitative checks (total spent, count of invoices, averages, status filters, sums, dates). "
            "CHAT: For casual greeting, feedback, or general chats."
        )
        return result.route.upper()
    except Exception as e:
        logger.warning("Routing classification failed: %s. Using keyword fallback.", e)
        q = query.lower()
        if any(kw in q for kw in ["total", "spent", "sum", "average", "how many", "count", "mean", "min", "max", "date", "status"]):
            return "SQL"
        if any(kw in q for kw in ["hello", "hi ", "hey", "who are you", "what is your name"]):
            return "CHAT"
        return "RAG"

def execute_generated_sql(sql: str, tenant_id: str, db_session) -> str:
    """Safely execute generated SQL statement on the database session."""
    sql_clean = sql.strip().strip("`").strip()
    if sql_clean.lower().startswith("sql"):
        sql_clean = sql_clean[3:].strip()
        
    sql_lower = sql_clean.lower()
    
    # Safety Check 1: Mutating keywords
    mutating = ["insert", "update", "delete", "drop", "alter", "create", "replace", "truncate"]
    if any(kw in sql_lower for kw in mutating):
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

def run_query_agent(session_id: str, user_message: str, tenant_id: str, db_session) -> dict:
    """
    RAG Query Agent routing natural language inputs to semantic context indexers,
    safe database queries, or conversational chat saves with multi-turn short-term memory.
    """
    logger.info("Executing Query Agent for session %s, tenant %s", session_id, tenant_id)
    
    # Retrieve short-term context history
    chat_history = get_chat_history(session_id, db_session)
    
    # 1. Routing classification
    route = classify_query(user_message)
    logger.info("Selected Route: %s", route)
    
    llm = get_llm(temperature=0.0)
    response_text = ""
    generated_sql = None
    citations = []
    
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
            
            # Formulate final output matching the raw numbers
            summary_prompt = f"""Format a friendly summary explaining these database query results:
Results:
{db_result}

User Query: {user_message}
"""
            final_res = llm.invoke(summary_prompt)
            response_text = final_res.content + f"\n\n### Query Results\n{db_result}"
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
            
    return {
        "content": response_text,
        "generated_sql": generated_sql,
        "citations": citations
    }
