# AI Agents Architecture & Design Blueprint (`/apps/invoice-be/agents`)

This directory houses the core multi-agent execution pipeline. The system utilizes **LangChain / LangGraph** to model agents as state machines following the **ReAct (Reasoning and Action)** design pattern. 

---

## 1. Core Design Patterns

### 1.1 The ReAct Loop (Reasoning & Action)
Every agent runs in a continuous loop:
$$\text{Thought} \rightarrow \text{Action (Tool Call)} \rightarrow \text{Observation (Tool Output)} \rightarrow \text{Next Thought/Response}$$

To ensure reliability, each agent has its toolset defined with strict schema validations and precise docstrings.

### 1.2 Tool Construction Specifications
All tools must be decorated with `@tool` and must include:
1. **Precise Docstrings**: The LLM uses these descriptions to decide when and how to call a tool.
2. **Type Hints**: Ensures correct parameter parsing.
3. **Pydantic Validation**: Input arguments are validated at runtime.

Example:
```python
from langchain.tools import tool
from pydantic import BaseModel, Field

class MathValidationInput(BaseModel):
    items: list[dict] = Field(description="List of line items containing 'amount' key.")

@tool("validate_invoice_totals", args_schema=MathValidationInput)
def validate_invoice_totals(items: list[dict]) -> dict:
    """
    Computes mathematical correctness of an invoice.
    Verifies that the sum of line items matches the subtotal and grand total.
    Use this tool whenever an invoice's extracted numeric fields need validation.
    """
    # Tool execution logic
```

### 1.3 State & Memory Checkpointing
* **Short-Term Context**: Managed using LangGraph's state graph. During execution, intermediate steps (thoughts, tool arguments, tool outputs) are recorded.
* **Persistent Memory**: The **Query Agent** utilizes a Postgres-backed checkpointer (`PostgresSaver`) to persist conversation threads, allowing multi-turn RAG chat sessions.
* **Fallback Saver**: In development, `InMemorySaver` is used.

---

## 2. Agent Specifications

### 2.1 Extraction Agent (`extraction_agent.py`)
* **Role**: Ingests raw unstructured layout text and visual documents, returning structured JSON matching a strict schemas definition, and validates mathematical correctness.
* **Architecture Pattern**: Designed as a deterministic **LangGraph State Graph** featuring a **self-correcting validation loop**. It avoids free-form ReAct tool calling to ensure structure and reliability.
* **Code Location**: [extraction_agent.py](file:///c:/Users/S%20Banerjee/Desktop/Invoice_LLM/Prod_Invoice_LLM/apps/invoice-be/agents/extraction_agent.py)
* **LLM**: Azure OpenAI `gpt-4o` (or `gpt-4o-mini` for high-throughput, low-cost extraction; optionally invokes `gpt-4o` to explain discrepancies if validation fails).
* **LLM Parameters**:
  * `temperature`: `0.0` (zero variance for deterministic extraction)
  * `response_format`: Structured output enforced via Pydantic model schemas using `LLM.with_structured_output(InvoiceSchema)`.
  * `max_tokens`: `4096`
* **Multi-Modal Integration**:
  1. **Visual Path**: Accepts page-by-page invoice renderings encoded as a **base64 image stream** (`image/jpeg`).
  2. **Text Path**: Accepts structural markdown layout parsed via the `AzureAIDocumentIntelligenceLoader`.
  3. **Mapping**: The agent uses spatial visual cues (e.g. alignment of total fields) to associate line items with their values, overcoming OCR limitations on column shifts.
* **Validation & Correction Loop (LangGraph Nodes)**:
  * **Extraction Node**: Prompts the LLM with the Pydantic schema to extract invoice data.
  * **Validation Node**: Runs local validation tools (`validate_invoice_totals`) on the output.
  * **Math Check Tool (`validate_invoice_totals`)**: Checks if `sum(item_amount) == subtotal` and `subtotal + tax_amount == grand_total` locally.
  * **Correction Loop**: If validation checks fail, the graph routes execution back to the extraction node with the specific validation error messages, allowing the LLM to self-correct up to a maximum retry limit.
* **Failure Actions**: If verification fails after retries, the agent writes warning comment objects to the `alerts` array column in `invoices` and transitions the invoice status to `AUDIT_REQUIRED`. If all checks pass, status is set to `COMPLETED`.

---

### 2.2 Query Agent (`query_agent.py`)
* **Role**: Powering the RAG-based semantic chat assistant for invoice querying.
* **Architecture Pattern**: Designed as a **Router-based Node topology** in LangGraph. Instead of an open-ended ReAct loop that decides tool usage on every turn, the agent routes the incoming user question to dedicated execution paths/nodes to reduce latency and cost.
* **Code Location**: [query_agent.py](file:///c:/Users/S%20Banerjee/Desktop/Invoice_LLM/Prod_Invoice_LLM/apps/invoice-be/agents/query_agent.py)
* **LLM**: Azure OpenAI `gpt-4o`.
* **LLM Parameters**:
  * `temperature`: `0.5` (natural tone with constrained reasoning)
  * `max_tokens`: `2048`
* **Graph Node Flow**:
  1. **Query Router Node**: Classifies the query (e.g., semantic vs. quantitative database lookups).
  2. **Vector Search RAG Node**: For semantic questions, calculates embedding and queries ChromaDB (relevance threshold $\ge 0.4$ cosine distance).
  3. **Postgres Metadata Node**: For structured/database queries, executes optimized SQL lookups using Postgres tools.
  4. **Synthesis Node**: Integrates context, citations, and metadata queries to build the final response.
* **Local Embedding Layer**: 
  * Converts user questions into vector representations using local **`BAAI/bge-m3`** model (1024 dimensions).
* **Tools**:
  * `get_invoice_metadata`: Fetches direct SQL invoice statuses.
  * `generate_blob_signed_url`: Generates temporary read access links to source PDFs for citation outputs.

---

### 2.3 Trainer Agent (`trainer_agent.py`)
* **Role**: Learns template adjustments based on human corrections.
* **LLM**: Azure OpenAI `gpt-4o`.
* **LLM Parameters**:
  * `temperature`: `0.3` (low variance logic)
  * `max_tokens`: `4096`
* **Mechanisms**:
  1. **Diff Computation**: Triggered when an Auditor manually corrects extracted invoice fields in the UI (`PUT /api/v1/audit/resolve/{invoice_id}`).
  2. **Rule Synthesis**: Compares the original failed JSON output against the auditor's corrected JSON alongside the source OCR text coordinates.
  3. **Template Persistence**: Synthesizes a coordinate layout override rule and saves it to the PostgreSQL `templates` table. This is automatically applied to future invoices sharing that vendor signature.

---

## 3. Evaluation & Guardrails

### 3.1 Observability & Tracing (LangSmith)
Every agent run is traced in **LangSmith** to monitor LLM token costs, intermediate tool inputs/outputs, and graph latency.
```bash
# Environment configurations for tracing
export LANGCHAIN_TRACING_V2="true"
export LANGCHAIN_ENDPOINT="https://api.smith.langchain.com"
export LANGCHAIN_API_KEY="ls__your_key_here"
export LANGCHAIN_PROJECT="invoice-llm-be"
```

### 3.2 Evaluation Metrics
Corrected 2026-08-21: this section previously said the pipeline "is evaluated ... using the **Ragas**
framework". It was not — `ragas` has never been a dependency of this backend and nothing implemented
these metrics. Feature 23 Phase 3 implements them, following Ragas' *definitions* but not its
package (see `services/agent_eval.py`'s module docstring for why: Apache-2.0 licensing is fine, the
`datasets`/`pyarrow`/`pandas` transitive weight in a `uv sync --frozen` production image is not).

1. **Faithfulness** — verifies the response contains only information present in the retrieved
   chunks/tool results. Implemented exactly as Ragas defines it: decompose the answer into atomic
   claims, judge each against the context, score = supported / total.
   (`services/agent_eval.py::score_faithfulness`)
2. **Answer Relevance** — checks the response addresses the question without side-tracking. Ragas'
   definition, judged directly rather than via Ragas' generate-questions-and-embed estimator; a
   number from here is not comparable to a published Ragas benchmark figure.
   (`services/agent_eval.py::score_relevance`)
3. **Accuracy** — agreement with the golden set's reference answer.
   (`services/agent_eval.py::score_accuracy`)
4. **Context Precision** — Ragas' third metric, grading the *retriever's* ranking rather than the
   answer. Still **not implemented**; worth adding when retrieval tuning is the subject.

Added 2026-08-21, and **not** Ragas metrics — Feature 23's own "which stage of the pipeline is
broken" decomposition, three different mechanisms rather than one check run three times. All three
are recorded and trended; none of them feeds the pass/fail decision:

5. **Context** — did retrieval fetch the right rows at all. Deterministic F1 of fetched invoice ids
   against the golden case's known-correct set; no LLM judge is involved and none is needed. An
   expected set of `()` means "the correct retrieval is nothing" and is scored, not skipped.
   (`services/agent_eval.py::score_context`)
6. **Orchestration** — mechanical groundedness. Every figure in the answer must appear in a tool
   result or be one arithmetic operation over figures that do; score = traceable / total. Also no
   judge, so it costs nothing and cannot vary between runs. Biased toward false passes, not false
   failures — see the function's docstring.
   (`services/agent_eval.py::score_orchestration`)
7. **Persona** — domain reasoning (tax components, RCM, status semantics, category judgement). The
   one component that genuinely needs judgement. Returns "not applicable" for any turn that required
   no domain judgement, so it is NULL on most turns; **there is no dedicated domain-knowledge golden
   set in this repo**, so it is scored against the general sample with a persona rubric and its
   denominator must be read alongside its level.
   (`services/agent_eval.py::score_persona`)

Scores are persisted per run to the `agent_eval_run` table and mirrored as an `agent_eval_run`
Application Insights custom event, so quality is a trend over time rather than "the last run passed".
Runner: `scripts/run_agent_eval.py`; sample: `tests/agent_eval_golden_sample.py`.

### 3.3 System Guardrails
* **Prompt Injection Shield**: Validates user prompts before feeding them into the agent loop to prevent system instruction overrides.
* **Output Data Leak Guard**: Filters output text to ensure no records containing mismatched `tenant_id` structures are returned to the user interface.
