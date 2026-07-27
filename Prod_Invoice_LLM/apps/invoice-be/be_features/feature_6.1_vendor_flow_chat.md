# Feature 6.1: Vendor Flow — Direction-Aware Chat

Extends [feature_6_rag.md](feature_6_rag.md). Spec only — no implementation yet, pending approval of the full Vendor Flow document set.

The one deliberate, narrow exception to "new files only" in Vendor Flow: a small additive edit to `agents/query_agent.py`, so Chat stays a single screen capable of answering inbound-only, outbound-only, *and* combined/net questions ("how much do I owe vs. how much is owed to me"). A fully separate Vendor Chat was considered and rejected — it would forfeit combined/net questions and split one smart screen into two duller ones.

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
- [ ] **Task 6.1.1:** Add `flow_direction`/`customer_name`/`customer_id` to the SQL-generation schema description + combined-question example pattern.
- [ ] **Task 6.1.2:** Extend `_get_global_business_rules()` to include the tenant's `OUTBOUND` Global template.
- [ ] **Task 6.1.3:** Wire `index_invoice_document()` into `outbound_handlers.py` on `VERIFIED`.

### Verification Plan
* **Manual Verification:**
  - Ask an inbound-only question ("who is the vendor on invoice X"); confirm identical behavior to today, no regression.
  - Ask an outbound-only question ("what's the total on the invoice I sent to Acme"); confirm it correctly filters `flow_direction='OUTBOUND'` and uses `customer_name`.
  - Ask a combined question ("how much do I owe vs. how much is owed to me"); confirm the generated SQL uses the conditional-aggregation pattern and the synthesized answer correctly separates both figures.
  - Teach an outbound standing rule (feature_7.1), then ask Chat about an affected outbound invoice; confirm the answer reflects the rule.
