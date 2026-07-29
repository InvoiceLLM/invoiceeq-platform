# Feature 6.1: Service Flow — Direction-Aware Chat — **SAGE Agent**

**SAGE** (Invoice Intelligence Chat) powers this flow. Extends [feature_6_rag.md](feature_6_rag.md). **Built 2026-07-29** — see Tasks below.

The one deliberate, narrow exception to "new files only" in Service Flow: a small additive edit to `agents/query_agent.py`, so Chat stays a single screen capable of answering inbound-only, outbound-only, *and* combined/net questions ("how much do I owe vs. how much is owed to me"). A fully separate Vendor Chat was considered and rejected — it would forfeit combined/net questions and split one smart screen into two duller ones.

### File Coordinates
* Edited (narrow, additive only): `apps/invoice-be/agents/query_agent.py` — the SQL-generation schema-description text, `_get_global_business_rules()`/`_get_vendor_business_rules()`.
* Existing, imported-not-edited: `apps/invoice-be/chroma_client.py::index_invoice_document()` — called from the new `outbound_handlers.py` (see [feature_2.1](feature_2.1_vendor_flow_ingestion.md)) once an outbound invoice reaches `VERIFIED`, mirroring inbound's `COMPLETED` trigger. No change to `chroma_client.py` itself.

### Functionality

**Schema-description edit:** the inline SQL-generation prompt in `run_query_agent()` gains awareness of `flow_direction`, `customer_name`, `customer_id` as real columns (same treatment Gap 45 already gave `sa_alerts`/`status` — list them explicitly, don't let the LLM guess). One added example pattern for combined questions:

```
-- Combined/net question pattern:
SELECT
  SUM(CASE WHEN flow_direction='INBOUND'  THEN grand_total ELSE 0 END) AS total_owed_by_us,
  SUM(CASE WHEN flow_direction='OUTBOUND' THEN grand_total ELSE 0 END) AS total_owed_to_us
FROM invoice WHERE tenant_id = '{tenant_id}'
```

This keeps the existing single-query architecture completely intact — the LLM still generates one `SELECT`, still runs through the same isolation-regex check (Gap 20), the same 3-attempt self-repair loop (Gap 11), the same execution path. No structural change, just a richer schema description.

**Business rules injection extended:** `_get_global_business_rules()` also fetches the tenant's `OUTBOUND` Global `ExtractionTemplate` row (the standing rules from [feature_7.1](feature_7.1_vendor_flow_auditor.md)) when the question concerns outbound data, so Chat's explanation of an outbound invoice reflects however that invoice was actually processed — same principle as Gap 48's original fix, just extended to the new direction.

**RAG route:** outbound invoices get indexed into the same Chroma collection on `VERIFIED` (imported call, not a `chroma_client.py` edit), so semantic questions about outbound documents work through the existing RAG path unchanged.

### Explicitly out of scope
- Any change to `classify_query()`'s RAG/SQL/CHAT routing logic itself — direction-awareness lives entirely in the SQL-generation prompt and business-rules fetch, not in routing.
- A persisted "net position" view anywhere outside Chat — stays a Chat-only capability, consistent with the Dashboard split-screen decision.

### Tasks
- [x] **Task 6.1.1:** Done 2026-07-29 — schema description in `run_query_agent()`'s SQL prompt now lists `flow_direction`/`customer_name`/`customer_id`, plus the combined-question conditional-aggregation example and an explicit rule telling the LLM never to mix vendor/customer filters for the wrong direction.
- [x] **Task 6.1.2:** Done 2026-07-29 — `_get_global_business_rules()` now unions both the `INBOUND` and `OUTBOUND` Global templates. **Found and fixed a real bug along the way**: the old query used `.first()` with no `flow_direction` filter, which was correct only because a tenant could never have more than one Global row before this feature. Now that two can coexist, `.first()` would have non-deterministically returned either one — fixed by fetching all matching rows and returning the union.
- [x] **Task 6.1.3:** Done 2026-07-29 — `queue_worker/outbound_handlers.py` calls the imported `index_invoice_document()` when status reaches `VERIFIED` (not `NEEDS_REVIEW`), passing `customer_name` through the function's `vendor_name` parameter. **Known cosmetic gap**: `chroma_client.py`'s chunk header literally prints `"[Vendor: {name}]"`, so outbound chunks will show `"Vendor: <customer name>"` — left as-is since the doc explicitly forbids editing `chroma_client.py`.

### Verification Plan
* **Automated Tests**: `uv run pytest tests/test_direction_aware_chat.py` — 8 new tests (Global rules union, INBOUND-only regression check, OUTBOUND-only, dedup, empty case, schema-prompt content assertion confirming the new columns/pattern actually reach the LLM call, RAG indexing fires on `VERIFIED`/skips on `NEEDS_REVIEW`). Re-ran the full existing `tests/test_rag.py` suite (9 tests, including `test_sql_guardrail_safety_enforcement` — Gap 20's tenant-isolation regex check) to confirm zero regression to the security-critical execution path, which this feature never touches. Also confirmed live connectivity to real Azure OpenAI (`gpt-5-mini`) from this dev environment, though the automated tests above still run against a mocked LLM.
* **Manual Verification** (not yet done — no live DB/real invoice data seeded in this pass):
  - Ask an inbound-only question ("who is the vendor on invoice X"); confirm identical behavior to today, no regression.
  - Ask an outbound-only question ("what's the total on the invoice I sent to Acme"); confirm it correctly filters `flow_direction='OUTBOUND'` and uses `customer_name`.
  - Ask a combined question ("how much do I owe vs. how much is owed to me"); confirm the generated SQL uses the conditional-aggregation pattern and the synthesized answer correctly separates both figures.
  - Teach an outbound standing rule (feature_7.1), then ask Chat about an affected outbound invoice; confirm the answer reflects the rule.
