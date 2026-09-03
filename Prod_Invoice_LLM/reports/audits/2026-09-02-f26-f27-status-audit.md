# STATUS AUDIT — Feature 26 (chat attached documents) & Feature 27 (generic extraction)

**Audit date:** 2026-09-02
**Method:** git, grep, pytest, docker inspection. Spec docs were opened only in Section 5, after the code evidence was gathered.
**Rules applied:** every claim carries evidence (`file:line`, test name, commit hash, or raw command output). "Not found" is reported as such. Nothing that modifies repo files was run.
**Paths** are relative to `Prod_Invoice_LLM/apps/invoice-be/` unless prefixed.

---

## 1. GIT TRUTH

### 1.1 `git log --oneline --since="2026-08-30" -- apps/invoice-be apps/invoice-fe docs` (as written, from repo root)

```
(empty — apps/ lives under Prod_Invoice_LLM/, so the literal paths match nothing)
```

### 1.2 Same command with corrected paths

`git log --oneline --since="2026-08-30" -- Prod_Invoice_LLM/apps/invoice-be Prod_Invoice_LLM/apps/invoice-fe Prod_Invoice_LLM/docs`

```
c211662 feat(be,fe): Gap 364/365/366 - Chat/SAGE document attach + concurrency fixes
0931088 fix(be,infra): Gap 362/363 - Google Drive OAuth account picker + custom domain
1a716ad fix(be,infra): Gap 361 - connector RBAC gap + storage TLS, from live security pass
e1d8511 fix(be): Gap 360 - Autopilot sync history grows forever, two defects
91e93e5 feat(fe,be): Gap 358/359 - external API-key access + mock-auth prod guard
```

- `git log --all -- "*feature_27*"` → **empty**
- `git log --all -i --grep="feature.26|feature.27|chat.attach|generic.extraction|doc.type|doc_type"` → **empty**
- `git log --all -- "*feature_26*"` → `c211662` only

**Feature 27 has zero commits. Feature 26 has exactly one (`c211662`, Part 1).**

### 1.3 `git status --short` (F26/F27-relevant lines; full output is 35 modified + 46 untracked)

```
 M Prod_Invoice_LLM/apps/invoice-be/agents/extraction_agent.py
 M Prod_Invoice_LLM/apps/invoice-be/agents/query_agent.py
 M Prod_Invoice_LLM/apps/invoice-be/chroma_client.py
 M Prod_Invoice_LLM/apps/invoice-be/config.py
 M Prod_Invoice_LLM/apps/invoice-be/docs/feature_26_chat_attached_documents.md
AM Prod_Invoice_LLM/apps/invoice-be/docs/feature_27_generic_extraction.md
 M Prod_Invoice_LLM/apps/invoice-be/main.py
 M Prod_Invoice_LLM/apps/invoice-be/models.py
 M Prod_Invoice_LLM/apps/invoice-be/queue_worker/handlers.py
 M Prod_Invoice_LLM/apps/invoice-be/routers/chat.py
 M Prod_Invoice_LLM/apps/invoice-be/routers/chat_attachments.py
 M Prod_Invoice_LLM/apps/invoice-be/routers/invoices.py
 M Prod_Invoice_LLM/apps/invoice-be/tests/test_chat_attachments.py
 M Prod_Invoice_LLM/apps/invoice-be/utils/llm.py
 M Prod_Invoice_LLM/apps/invoice-fe/components/chat/ChatWindow.tsx
 M Prod_Invoice_LLM/apps/invoice-fe/components/chat/MessageBubble.tsx
 M Prod_Invoice_LLM/apps/invoice-fe/components/ingestion/DropZone.tsx
 M Prod_Invoice_LLM/apps/invoice-fe/components/ingestion/StatusTable.tsx
 M Prod_Invoice_LLM/apps/invoice-fe/hooks/useChatSession.ts
 M Prod_Invoice_LLM/apps/invoice-fe/types/chat.ts
?? Prod_Invoice_LLM/apps/invoice-be/alembic/versions/d3e4f5a6b7c8_add_chat_attachment_index_columns.py
?? Prod_Invoice_LLM/apps/invoice-be/alembic/versions/e4f5a6b7c8d9_add_doc_type_and_documents_table.py
?? Prod_Invoice_LLM/apps/invoice-be/routers/documents.py
?? Prod_Invoice_LLM/apps/invoice-be/services/chat_document_search.py
?? Prod_Invoice_LLM/apps/invoice-be/services/document_type_classifier.py
?? Prod_Invoice_LLM/apps/invoice-be/tests/fixtures/doc_types/
?? Prod_Invoice_LLM/apps/invoice-be/tests/test_chat_doc_content_branch.py
?? Prod_Invoice_LLM/apps/invoice-be/tests/test_chat_document_search.py
?? Prod_Invoice_LLM/apps/invoice-be/tests/test_document_type_classifier.py
?? Prod_Invoice_LLM/apps/invoice-be/tests/test_documents_table.py
?? Prod_Invoice_LLM/apps/invoice-be/tests/test_generic_extraction.py
?? Prod_Invoice_LLM/apps/invoice-fe/app/api/chat/attachments/
?? Prod_Invoice_LLM/apps/invoice-fe/app/api/chat/sessions/[sessionId]/attachments/
?? Prod_Invoice_LLM/apps/invoice-fe/components/chat/AttachmentChip.tsx
?? Prod_Invoice_LLM/apps/invoice-fe/components/chat/AttachmentMatchConfirm.tsx
?? Prod_Invoice_LLM/apps/invoice-fe/components/chat/DocumentEvidence.tsx
?? Prod_Invoice_LLM/apps/invoice-fe/e2e/chat-attachment-contract.spec.ts
?? Prod_Invoice_LLM/apps/invoice-fe/e2e/chat-attachment-guards.spec.ts
?? Prod_Invoice_LLM/apps/invoice-fe/e2e/chat-attachment-upload.spec.ts
?? Prod_Invoice_LLM/apps/invoice-fe/e2e/feature27-doc-type.spec.ts
?? Prod_Invoice_LLM/apps/invoice-fe/lib/chatAttachments.ts
```

### 1.4 `git diff --stat HEAD~15..HEAD`

Summary line: `191 files changed, 28995 insertions(+), 1453 deletions(-)`

F26 lines within it:

```
.../apps/invoice-be/agents/query_agent.py                        |  377 ++-
.../versions/c2d3e4f5a6b7_add_chat_attachments.py                |  111 +
.../apps/invoice-be/routers/chat_attachments.py                  |  300 ++
.../invoice-be/services/document_comparison.py                   |  543 ++++
.../apps/invoice-be/tests/test_chat_attachments.py               |  549 ++++
.../docs/feature_26_chat_attached_documents.md                   |  286 ++
Prod_Invoice_LLM/apps/invoice-be/models.py                       |  367 ++-   (shared with other gaps)
```

No Feature 27 file appears in any commit.

### 1.5 Uncommitted working tree

`git diff --stat` (tracked files, F26/F27-relevant): `34 files changed, 9833 insertions(+), 256 deletions(-)`

```
.../apps/invoice-be/agents/extraction_agent.py     | 1508 ++++++++++++-
.../apps/invoice-be/agents/query_agent.py          |  487 ++++-
Prod_Invoice_LLM/apps/invoice-be/chroma_client.py  |  319 +++
Prod_Invoice_LLM/apps/invoice-be/config.py         |  146 ++
.../docs/feature_26_chat_attached_documents.md     | 2281 +++++++++++++++++++-
.../docs/feature_27_generic_extraction.md          | 1740 ++++++++++++++-
Prod_Invoice_LLM/apps/invoice-be/models.py         |  163 ++
.../apps/invoice-be/queue_worker/handlers.py       |  338 ++-
.../apps/invoice-be/routers/invoices.py            |  202 +-
.../apps/invoice-be/tests/test_chat_attachments.py |  420 +++-
.../apps/invoice-fe/components/chat/MessageBubble.tsx | 353 ++-
.../apps/invoice-fe/hooks/useChatSession.ts        |  532 ++++-
```

Untracked F26/F27 source + test files total **8,215 lines** (`wc -l`), e.g. `test_generic_extraction.py` 2885, `test_documents_table.py` 1075, `lib/chatAttachments.ts` 642, `services/document_type_classifier.py` 603.

### 1.6 Per-commit table

| Commit | Feature | Files | +/- |
|---|---|---|---|
| `c211662` | F26 Part 1 (Gap 364/365/366) | 26 | +5135 / −41 |
| *(none)* | F26 Part 2 (H1–H12) | — | uncommitted only |
| *(none)* | F27 (G1–G14, task F) | — | uncommitted only |

---

## 2. WHAT EXISTS IN CODE

### 2.1 Feature 26

| Item | EXISTS (file:line) | NOT FOUND |
|---|---|---|
| `ChatAttachment` model | `models.py:382 class ChatAttachment(SQLModel, table=True)` | |
| chatattachment alembic migration | `alembic/versions/c2d3e4f5a6b7_add_chat_attachments.py:56 op.create_table(` (committed in `c211662`); `alembic/versions/d3e4f5a6b7c8_add_chat_attachment_index_columns.py:52,56,59 op.add_column(` (untracked) | |
| `routers/chat_attachments.py` route decorators | `:124 @router.post("/sessions/{session_id}/attachments", response_model=AttachmentOut)` · `:324 @router.post("/attachments/{attachment_id}/confirm-matches", response_model=AttachmentOut)` · `:363 @router.get("/attachments/{attachment_id}", response_model=AttachmentOut)` | |
| `services/document_comparison.py` def lines | `:59 normalize_doc_number` · `:76 _to_decimal` · `:100 _normalize_currency` · `:104 _normalize_party` · `:108 _coerce_date` · `:123 find_candidate_invoices` · `:224 _compare_one` · `:325 compare_reference_to_invoices` · `:380 build_suggested_actions` · `:472 build_confirmation_payload` | |
| `_run_attached_document_turn` | `agents/query_agent.py:3102 def _run_attached_document_turn(`; called at `:3619` | |
| `attachment_id` in `routers/chat.py` `MessageCreate` / `enqueue_chat_job` | `:119 class MessageCreate(BaseModel)` · `:127 attachment_id: UUID \| None = None` · `:437 and payload.attachment_id is None` (async queue bypassed when attached) · `:540, :554, :596` threading | `ChatQueueService.enqueue_chat_job()` (`:428-458`) carries **no** attachment parameter — deliberate per in-code comment |
| `_chat_doc_collection_name` / `chat_docs_` in `chroma_client.py` | `:340 def _chat_doc_collection_name(tenant_id)` · `:358 return f"chat_docs_{tenant_id}"` · `:361 def get_chat_doc_collection(tenant_id)` | |
| `services/chat_document_search.py` | 304 lines: `:69 _header` · `:85 index_attachment_chunks` · `:175 search_attachment_chunks` · `:270 delete_attachment_chunks` | |
| `bind_tools` in `utils/llm.py` | | **NOT FOUND** in `utils/llm.py` or any app `.py` (only `.venv/…/langchain/…`). The F26 doc H1 explicitly states "No `bind_tools()`" |
| `scripts/sweep_chat_attachments.py` | | **NOT FOUND** (`scripts/` contains `sweep_azure_cost.py, sweep_billing_lifecycle.py, sweep_free_quotas.py, sweep_lapsed_billing.py, sweep_outbound_overdue.py, sweep_sandbox_tenants.py`) |
| `infra/chat-doc-ttl-job-only.bicep` | | **NOT FOUND** (18 `.bicep` files in `Prod_Invoice_LLM/infra/`, none match `chat`/`ttl`) |
| FE `grep -rn "attachment"` in `components hooks types app/api/chat` | **190 hits / 10 files:** `components/chat/AttachmentChip.tsx`, `components/chat/AttachmentMatchConfirm.tsx`, `components/chat/ChatWindow.tsx`, `components/chat/DocumentEvidence.tsx`, `components/chat/MessageBubble.tsx`, `hooks/useChatSession.ts`, `types/chat.ts`, `app/api/chat/attachments/[attachmentId]/confirm-matches/route.ts`, `app/api/chat/attachments/[attachmentId]/route.ts`, `app/api/chat/sessions/[sessionId]/attachments/route.ts` | |

### 2.2 Feature 27

| Item | EXISTS (file:line) | NOT FOUND |
|---|---|---|
| `ENABLE_GENERIC_EXTRACTION` in `config.py` | `config.py:115 ENABLE_GENERIC_EXTRACTION: bool = False`; read at `agents/extraction_agent.py:1304, :1617, :2261` | |
| `services/document_type_classifier.py` | 603 lines: `:74 DOC_TYPES` · `:166 _DOC_TYPE_SYNONYMS` · `:363 classify_doc_type_deterministic` · `:407 class DocTypeClassification(BaseModel)` · `:500 classify_doc_type` · `:587 _classify_with_llm` | |
| `DOC_TYPES` tuple | `document_type_classifier.py:74-85` — `QUOTATION, PROFORMA_INVOICE, PURCHASE_ORDER, CONTRACT, DELIVERY_NOTE, GRN, INVOICE, CREDIT_NOTE, DEBIT_NOTE, OTHER` | |
| `GenericDocumentSchema` | `agents/extraction_agent.py:311 class GenericDocumentSchema(BaseModel)`; used `:1173 schema=GenericDocumentSchema` | |
| `_VerificationRubric` / `_RUBRIC_BY_DOC_TYPE` | `extraction_agent.py:1387 class _VerificationRubric` · `:1448 _MONEY_RUBRIC` · `:1464 _QUANTITY_RUBRIC` · `:1490 _COMMITMENT_RUBRIC` · `:1509 _OTHER_RUBRIC` · `:1521 _RUBRIC_BY_FAMILY` · `:1533 _RUBRIC_BY_DOC_TYPE` · `:1640` lookup | |
| `classify_doc_type_node` | `extraction_agent.py:2039 def classify_doc_type_node(state)` · `:2214 builder.add_node("classify_doc_type", classify_doc_type_node)` (flag-conditional) | |
| `UnknownFlowDirectionError` | `extraction_agent.py:1185 class UnknownFlowDirectionError(ValueError)` · raised `:1255` | |
| `prebuilt-layout` string anywhere | Only in markdown: `Backend_Code_Layout_Document.md:25`, `docs/be_features_tracker.md:62`, `docs/feature_27_generic_extraction.md` ×8 | **NOT FOUND in any `.py`** — consistent with doc's "no layout branch" |
| `document_to_base64_images` | `extraction_agent.py:425 def document_to_base64_images(file_path)` · alias wrapper `:535-544` (`pdf_to_base64_images` → `document_to_base64_images`) | |
| `Invoice.doc_type` column + migration | `models.py:192 doc_type: str \| None` · `:193 doc_type_evidence` · `:206 class Document(SQLModel, table=True)` / `:207 __tablename__ = "documents"` · `alembic/versions/e4f5a6b7c8d9_add_doc_type_and_documents_table.py:81-100` (untracked). Alembic single head = `e4f5a6b7c8d9` (down `d3e4f5a6b7c8` → `c2d3e4f5a6b7` → `b1c2d3e4f5a6`), computed via Python API because `alembic.exe` is blocked by Application Control policy | |
| `tests/fixtures/doc_types/` | 10 type dirs: `contract/`, `credit_note/`, `debit_note/`, `delivery_note/`, `grn/`, `other/`, `proforma_invoice/`, `purchase_order/`, `quotation/` (+ INVOICE covered elsewhere); **16 PDFs** (e.g. `EU-CT-01_rahmenvertrag_no_total.pdf`, `IN-DN-01_delivery_challan_no_prices.pdf`, `US-DN-01_packing_slip_no_prices.pdf`, `IN-OTH-02_eway_bill_quoting_tax_invoice.pdf`); `MANIFEST.md`, `_generate_fixtures.py`, 9× `ground_truth_line_items.md` | |

---

## 3. WHAT IS TESTED

### 3.1 `uv run pytest tests/test_chat_attachments.py -v`

```
============================= 33 passed in 34.39s =============================
```

Test names:

```
test_normalize_doc_number_collapses_formatting_not_digits
test_tier1_exact_po_match_wins_and_skips_tier2
test_tier2_only_fires_when_tier1_empty_and_respects_window
test_tier2_caps_candidates
test_zero_match_is_reported_not_widened
test_matching_is_tenant_scoped
test_exact_match
test_over_billed_reports_invoice_higher_with_exact_delta
test_under_billed_reports_invoice_lower
test_missing_value_is_not_treated_as_zero
test_line_count_delta_reported
test_currency_mismatch_is_a_hard_stop_not_a_diff_row
test_empty_candidate_set_compares_nothing
test_suggested_actions_respect_outbound_confirm_send_precondition
test_mark_paid_only_offered_from_sent
test_no_action_is_a_mutation_and_none_invented
test_zero_candidates_offers_manual_entry_and_never_guesses
test_attachment_id_bypasses_classify_query_entirely
test_unconfirmed_attachment_returns_confirmation_not_a_number
test_confirmed_attachment_produces_the_deterministic_diff
test_the_answer_turn_calls_get_llm_with_a_signature_the_real_one_accepts
test_reference_profile_exists_and_is_additive
test_reference_schema_carries_the_doc_type_discriminator
test_mock_llm_answers_the_content_branch_marker_with_document_content
test_mock_llm_content_branch_is_checked_before_the_rag_substring_marker
test_mock_llm_without_the_marker_still_falls_through_to_the_sage_greeting
test_post_message_threads_attachment_id_to_the_attached_document_turn
test_post_message_without_attachment_id_is_unchanged
test_a_successful_upload_indexes_the_document_and_records_the_index_state
test_a_failed_extraction_never_reaches_the_indexer
test_an_indexing_failure_does_not_fail_the_upload_and_stays_visible
test_the_three_new_columns_default_safely_and_expires_at_is_stamped_at_upload
test_deleting_the_session_removes_the_attachment_row_and_its_chunks
```

### 3.2 `uv run pytest tests/test_generic_extraction.py tests/test_document_type_classifier.py -v`

```
============================ 409 passed in 17.67s =============================
```

138 + 21 `def test_` functions, heavily parametrized (e.g. `test_every_synonym_classifies_deterministically_without_an_llm_call[…]` ×47, `test_every_declared_image_suffix_is_dispatched_to_the_image_branch[…]` ×8, `test_e9_raises_with_the_flag_off_too[…]` ×4). Representative names from the `-v` output:

```
test_a_delivery_note_never_reaches_the_coordinates_gate_after_g9
test_the_valid_direction_set_is_the_profile_map_minus_generic
test_unknown_flow_direction_error_is_a_valueerror
test_generic_is_not_an_accepted_flow_direction[GENERIC|generic|Generic| GENERIC]
test_e9_raises_with_the_flag_off_too[REFERNCE|NONSENSE|GENERIC|  inbound ]
test_e9_raises_with_the_flag_on_too[...]
test_e9_is_the_only_visible_behaviour_change_with_the_flag_off
test_run_extraction_agent_still_calls_resolve_direction_profile
test_a_png_yields_one_base64_page_instead_of_an_empty_list
test_a_jpeg_is_normalised_to_png_not_relabelled
test_a_pdfs_output_is_byte_for_byte_what_the_old_function_produced
test_the_old_name_still_resolves_and_returns_the_same_thing
test_the_alias_is_a_wrapper_not_the_same_object
test_doc_types_is_the_closed_ten_value_tuple_in_lifecycle_order
test_every_doc_type_has_exactly_one_family_and_no_family_has_a_stray_key
test_no_synonym_is_claimed_by_two_document_types
test_a_purchase_order_number_quoted_on_an_invoice_is_not_a_purchase_order
test_a_title_naming_two_types_is_ambiguous_and_does_not_guess
test_an_invented_doc_type_cannot_be_constructed_at_all
test_ambiguous_document_falls_back_to_the_llm_and_an_invented_value_is_not_stored
test_low_confidence_is_never_promoted_to_a_type
test_a_failed_model_call_fails_closed_to_other
test_an_e_way_bill_quoting_its_tax_invoice_number_is_still_not_an_invoice
test_empty_ocr_text_is_other_without_paying_for_a_model_call[...]
```

### 3.3 `tests/test_extraction_flag_off_parity.py`

```
ERROR: file or directory not found: tests/test_extraction_flag_off_parity.py
```

**File not found.** Flag-off parity assertions live inside `test_generic_extraction.py` (`test_e9_is_the_only_visible_behaviour_change_with_the_flag_off`, `test_e9_raises_with_the_flag_off_too[…]`, and ~20 `assert ea.get_settings().ENABLE_GENERIC_EXTRACTION is False` guards).

### 3.4 Other new (untracked) test files, run separately

| File | Result |
|---|---|
| `tests/test_chat_doc_content_branch.py` | `39 passed in 12.82s` |
| `tests/test_chat_document_search.py` | `11 passed in 11.84s` |
| `tests/test_documents_table.py` | **hung on first test** — see 3.5 |

### 3.5 `uv run pytest -x -q` (full suite)

Literal result:

```
=================================== ERRORS ====================================
_______________ ERROR collecting tests/us/run_chat_live_test.py _______________
import file mismatch:
imported module 'run_chat_live_test' has this __file__ attribute:
  ...\invoice-be\tests\realworld_tenant\run_chat_live_test.py
which is not the same as the test file we want to collect:
  ...\invoice-be\tests\us\run_chat_live_test.py
=========================== short test summary info ===========================
ERROR tests/us/run_chat_live_test.py
!!!!!!!!!!!!!!!!!!!!!!!!!! stopping after 1 failures !!!!!!!!!!!!!!!!!!!!!!!!!!
1 error in 12.27s
```

**0 tests ran.** Both colliding files are git-ignored local files (`git check-ignore -v`: `tests/.gitignore:10  us/` and `Prod_Invoice_LLM/.gitignore:110  apps/invoice-be/tests/realworld_tenant/`), so this collection break is machine-local, not in the repo.

Re-run as `uv run pytest -q --ignore=tests/us/run_chat_live_test.py` → **hung indefinitely; killed after ~45 minutes. No full-suite pass/fail count is obtainable on this machine in its current state.** Root cause, with evidence:

- `docker ps` →
  ```
  invoice-postgres-local   Up 24 hours (Paused)   0.0.0.0:5433->5432/tcp
  invoice-redis-local      Up 24 hours (Paused)   0.0.0.0:6379->6379/tcp
  invoice-chromadb-local   Up 24 hours (Paused)   0.0.0.0:8001->8000/tcp
  invoice-azurite-local    Up 24 hours (Paused)   0.0.0.0:10000-10001->10000-10001/tcp
  ```
  **All four local containers are Paused.**
- `netstat -ano` showed the pytest processes holding `ESTABLISHED` sockets to `[::1]:5433` — docker-proxy accepts the TCP handshake, the frozen server never answers. A fresh `psycopg2.connect(url, connect_timeout=5)` → `timeout expired`.
- The `-v` log stopped at `tests/test_documents_table.py::test_t_e10_1_delivery_note_leaves_no_invoice_row_and_one_document_row`. Its harness `pg_engine_or_skip()` (`test_documents_table.py:60-79`) calls `psycopg2.connect(url)` with **no `connect_timeout`** and skips only on `OperationalError`; a reachable-but-frozen server passes the probe and then blocks forever. The same harness shape exists in `test_chat_queue.py:481 test_job_isolation_on_postgres` and `test_auth.py:1267-1276`.
- The containers were **not** unpaused by this audit (environment state is the owner's call).
- Housekeeping: one extra `pytest.exe -q --ignore=tests/us/run_chat_live_test.py` (PID 23356, parent PID 15396, started 22:14:18) was not launched by this audit session and was left running.

### 3.6 Which database, LLM, embeddings

**Database.** `tests/conftest.py` sets **no** `DATABASE_URL` — it sets only `ALLOW_MOCK_AUTH=true`, `ENVIRONMENT=test` (`:26-27`) and an in-memory `chromadb.EphemeralClient()` (`:76-86`).
- `test_chat_attachments.py:34-36`: `sqlite_url = "sqlite:///:memory:"` + `StaticPool`
- `test_generic_extraction.py:1965-1969`: `create_engine("sqlite:///:memory:", …, poolclass=StaticPool)`
- `test_documents_table.py:68`: `url = get_settings().DATABASE_URL` → from `.env`: `postgresql://<redacted>@localhost:5433/invoice_db` — the **real local dev database**.

So F26 and F27 unit suites run on **SQLite**; only `test_documents_table.py` (30 defs / 38 collected) targets Postgres, and it has **never completed a run** in this audit.

**LLM.** No suite-wide mock fixture exists. `config.py:291 LLM_PROVIDER: str = "azure"`; `.env` sets `LLM_PROVIDER`, `AZURE_OPENAI_API_KEY`, `AZURE_OPENAI_ENDPOINT`, `AZURE_OPENAI_DEPLOYMENT_NAME` (values not printed); `utils/llm.py:257` resolves the provider from settings. Mocking is per-test: `patch.object(qa, "get_llm", …)` (Section 4), and `test_document_type_classifier.py` patches the classifier's `get_llm` with `assert_not_called()`. `docs/test_coverage_map.md:57` records that the fixture-classification pass ran 3 of 16 fixtures against the **live Azure `gpt-5-mini`**, not a mock.

**Embeddings.** `config.py:284 MOCK_EMBEDDINGS: bool = False`; `.env` sets `MOCK_EMBEDDINGS` (value redacted with the other secrets); `test_chat_attachments.py:600 os.environ.setdefault("MOCK_EMBEDDINGS", "true")` — mid-file, immediately before `from main import app`; honored at `chroma_client.py:320`. conftest does not set it.

---

## 4. MOCK-MASKING CHECK

`grep -rn "MagicMock\|patch(" tests/test_chat_attachments.py tests/test_generic_extraction.py | grep -i "get_llm\|bind_tools\|run_extraction_agent"`:

```
tests/test_chat_attachments.py:415:    The test above patches `get_llm` with a bare `MagicMock`, which accepts any
tests/test_chat_attachments.py:440:        get_llm.return_value.invoke.return_value = MagicMock(
tests/test_generic_extraction.py:2359:         patch("queue_worker.handlers.run_extraction_agent") as mock_agent, \
```

| Patch site | Target | `autospec=True`? |
|---|---|---|
| `test_chat_attachments.py:392-394 patch.object(qa, "get_llm", return_value=fake_llm)` | `get_llm` | **No** — bare `MagicMock()` at `:387` |
| `test_chat_attachments.py:437-438 patch.object(qa, "get_llm", autospec=True)` | `get_llm` | **Yes** |
| `test_generic_extraction.py:2359 patch("queue_worker.handlers.run_extraction_agent")` | `run_extraction_agent` | **No** |
| `test_generic_extraction.py:2357 patch("queue_worker.handlers._run_ocr")` | `_run_ocr` | No |
| `bind_tools` | — | no patch; symbol is not in app code |
| *(outside the asked files)* `test_chat_doc_content_branch.py:204` and `:609 patch.object(qa, "get_llm", autospec=True)` | `get_llm` | Yes |

`grep -rn "autospec=True" tests/*.py | wc -l` → **6** (3 in `test_chat_attachments.py` counting docstrings, 3 in `test_chat_doc_content_branch.py`).

---

## 5. DOC vs CODE DIFF

### 5.1 `docs/feature_26_chat_attached_documents.md` (2,543 lines)

| Doc claim | Evidence | Verdict |
|---|---|---|
| C0 `[x]` spec doc + additive FE section | file exists; committed in `c211662` | VERIFIED |
| C1 `[x]` `models.py::ChatAttachment` + Alembic migration | `models.py:382`; `c2d3e4f5a6b7` in `c211662` | VERIFIED |
| C2 `[x]` `ReferenceDocExtractionSchema` + `"REFERENCE"` direction | `extraction_agent.py:237`; `test_reference_profile_exists_and_is_additive` PASSED | VERIFIED |
| C3 `[x]` `services/document_comparison.py` | defs `:59-472`; 16 comparison tests PASSED | VERIFIED |
| C4 `[x]` pre-route gate in `_run_query_agent()` | `query_agent.py:3619`; `test_attachment_id_bypasses_classify_query_entirely` PASSED | VERIFIED |
| C5 `[x]` router + `main.py` registration | `chat_attachments.py:124/324/363`; `main.py:180` | VERIFIED |
| C5b `[x]` `routers/chat.py` wiring | `chat.py:127, :437, :540, :554, :596`; `test_post_message_threads_attachment_id_…` and `…_without_attachment_id_is_unchanged` PASSED | VERIFIED |
| Tracker Gap 366 `[~]`; Phase-3 T3 "VERIFIED, real Postgres + real Azurite" | `docs/test_evidence/gap364_365_366_chat_attachments_phase3_2026-09-01/README.md:133`, committed in `c211662` (recorded run; not re-run here) | VERIFIED as a recorded run |
| H1 `[x]` content-branch marker in `MockInvoiceLLM.invoke()`; "No `bind_tools()`" | `utils/llm.py:29 CONTENT_BRANCH_PROMPT_MARKER`, `:105`; `bind_tools` NOT FOUND; 3 `test_mock_llm_*` PASSED | VERIFIED |
| H2 `[x]` `_chat_doc_collection_name()` + migrate-script fix; "4 tests in `tests/test_rag.py`" | `chroma_client.py:340, :361`; `scripts/migrate_chroma_to_per_tenant.py` modified in tree | VERIFIED (code); test claim not run in this audit |
| H3 `[x]` `services/chat_document_search.py`; "11 tests" | `:85/:175/:270`; `11 passed in 11.84s` | VERIFIED |
| H4 `[x]` embed step + `chunk_count/indexed_at/expires_at` + migration `d3e4f5a6b7c8` | `chat_attachments.py:275 _index_attachment`; migration file present (untracked); 5 upload-path tests PASSED (SQLite) | VERIFIED in code; **migration never applied to Postgres** |
| H5 `[x]` intent split + content branch; "33 tests in `tests/test_chat_doc_content_branch.py`" | `39 passed` (20 `def test_`, parametrized) | VERIFIED; count claim stale (33 ≠ 39) |
| H6, H6b, H7 `[ ]` | not built | consistent |
| H8 `[ ]` `scripts/sweep_chat_attachments.py` | NOT FOUND | consistent — doc says not built |
| H9 `[ ]` `infra/chat-doc-ttl-job-only.bicep` | NOT FOUND | consistent — doc says not built |
| H10 `[x]` composer paperclip, `AttachmentChip`, `AttachmentMatchConfirm`; "`tsc --noEmit` exit 0"; "13 tests in `e2e/chat-attachment-guards.spec.ts` pass" | files exist (216 / 245 lines); `npx tsc --noEmit` → exit 0; 13 `test(` in guards spec | VERIFIED code + tsc; Playwright **not run** in this audit |
| H11 `[x]` `MessageBubble` contract rendering; "17 Playwright tests in `e2e/chat-attachment-contract.spec.ts`" | `MessageBubble.tsx` +353; `DocumentEvidence.tsx` 121 lines; 17 `test(` in contract spec | VERIFIED code; run UNVERIFIED |
| H12 `[x]` `useChatSession` upload/confirm/reload, three proxies | `useChatSession.ts` +532; `app/api/chat/attachments/[attachmentId]/{route,confirm-matches/route}.ts`, `app/api/chat/sessions/[sessionId]/attachments/route.ts`; `lib/chatAttachments.ts` 642 lines; 12 `test(` in upload spec | VERIFIED code; run UNVERIFIED (`active-work.md:14`: "no recorded run") |
| L2168: `tests/test_chat_attachments.py:413–440` is "the **only** autospec'd patch in the whole suite" (also in the test's own docstring `:424`) | `test_chat_doc_content_branch.py:204` and `:609` also use `autospec=True` | **CONTRADICTED** (stale) |
| L1387 "33 passed"; L1009 "11 passed"; L1787 / L1919 "`tsc --noEmit` exit 0" | matches this audit's runs | VERIFIED |
| L925 `pytest tests/test_rag.py -q -k "chat_doc or cosine or migration"` → 7 passed | not run in this audit (full suite hung before reaching it) | UNVERIFIED |
| L1641 "Verified FE state 2026-09-02: zero attachment support exists" | historical, superseded by H10–H12 (10 FE files now) | consistent (dated claim) |
| `active-work.md:40` — `MessageResponse` drops every attachment key; nothing on §P2.8's contract reaches a browser from a real backend | `routers/chat.py::MessageResponse` fields: `id, session_id, role, content, generated_sql, citations, created_at, feedback, status, job_id, error_message` — no `attachment_*` key; the agent emits `attachment_clarification` (`query_agent.py:3220`), `attachment_confirmation` (`:3281`), `attachment_comparison` (`:3351`); the FE expects them at `types/chat.ts:133, :136, :152` | **VERIFIED — real end-to-end break** |
| Gap 374 note: `delete_attachment_chunks()` wired into `routers/chat.py::delete_session()` and `scripts/sweep_sandbox_tenants.py::_purge_sandbox()` | `chat.py:317, :323`; `sweep_sandbox_tenants.py:113, :118` | VERIFIED |

### 5.2 `docs/feature_27_generic_extraction.md` (2,307 lines)

| Doc claim | Evidence | Verdict |
|---|---|---|
| G1 `[x]` `config.py` flag + docstring | `config.py:115` | VERIFIED |
| G2 `[x]` classifier: taxonomy, families, deterministic pass, LLM fallback | `document_type_classifier.py:74, :363, :500, :587`; 21-def classifier file PASSED (47-synonym parametrisation, regional table, threshold both ways, transport docs → OTHER) | VERIFIED |
| G3 `[x]` `GenericDocumentSchema` + overlays + generic prompt builders | `extraction_agent.py:311, :739, :1173` | VERIFIED |
| G3b `[x]` `resolve_extraction_profile(flow_direction, doc_type)` + `GENERIC` profile | `extraction_agent.py:1353` (+ `:1138` note); direction/profile tests PASSED | VERIFIED |
| G4 `[x]` `classify_doc_type_node` + conditional graph entry | `:2039`, `:2214`, `:2261`; `test_generic_extraction.py:441 assert hasattr(ea, "classify_doc_type_node")` | VERIFIED |
| G5 `[x]` `_VerificationRubric` / `_RUBRIC_BY_DOC_TYPE` + `verify_node` | `:1387`, `:1448-1533`, `:1640` | VERIFIED |
| G6 `[ ]` — "what remains in G6 is only E9's fail-loud — `UnknownFlowDirectionError`" | **exists**: `:1185`, raised `:1255`; `test_e9_raises_with_the_flag_off_too[…]` ×4 and `…_on_too[…]` ×4, `test_generic_is_not_an_accepted_flow_direction[…]` ×4 PASSED; `test_generic_extraction.py:445` comment cites "Gap 384" | **CONTRADICTED — doc understates; built** |
| G7 `[x]` trust boundaries; coordinates gated on INVOICE family; E10 routing in `handlers.py` | `handlers.py:364 _should_persist_coordinates`, `:385 _routes_to_documents_table`, `:493 Document(`, `:936`; `test_a_delivery_note_never_reaches_the_coordinates_gate_after_g9` PASSED | VERIFIED |
| G8 `[ ]` `document_to_base64_images` + image dispatch + alias | **exists**: `:425`, alias `:535-544`; 19 G8 tests PASSED (`test_a_png_yields_one_base64_page…`, 8 suffix dispatch cases, `test_the_alias_is_a_wrapper_not_the_same_object`, …) | **CONTRADICTED — doc understates; built** |
| G9 `[x]` `Invoice.doc_type` / `doc_type_evidence` + `Document` model + one migration; down_revision `d3e4f5a6b7c8` | `models.py:192-193, :206-207`; `e4f5a6b7c8d9:69-70, :81-100`; alembic head = `e4f5a6b7c8d9` | VERIFIED in code; **not applied to the dev Postgres** — container log `2026-09-02 10:21:08 UTC ERROR: column invoice.doc_type does not exist` on a live app query (the `routers/invoices.py` search `CASE … lower(invoice.doc_type) …`) |
| G10 `[x]` `_document_collection_name()` + `get_document_collection()` | `chroma_client.py:383, :411, :428` | VERIFIED |
| G14 `[x]` `routers/documents.py` `GET /documents` + detail, registered | `documents.py:165 @router.get("")`, `:208 @router.get("/{document_id}")`; `main.py:181` | VERIFIED |
| G11 `[~]` FE partial; `DropZone` accept stays `.pdf`; "no `/config` or `/features` endpoint exists" | `DropZone.tsx:50 ACCEPTED_EXTENSIONS = [".pdf"]`, `:152`; `main.py:177-203` registers no such router; FE tracker `:909` FE Gap 378 `[~]` | VERIFIED (partial, as stated) |
| F `[ ]` fixture sourcing | `tests/fixtures/doc_types/` 10/10 types, 16 PDFs; `docs/test_coverage_map.md:57` "DONE for this dispatch's scope (10/10 doc types)… 16/16 classified correctly" | **CONTRADICTED — §10 checkbox stale; fixtures exist** |
| V `[ ]` execute §9 against Postgres | no `docs/test_evidence/` folder for F27; `test_documents_table.py` has no completed run | consistent — not done |
| L64/L90 "no `prebuilt-layout` branch" | grep: zero `.py` hits | VERIFIED |
| L1038 "Verified live against chromadb 1.5.9" | not re-verified | UNVERIFIED |
| L2243 "That endpoint does not exist. Verified repo-wide" | `main.py` router list confirms | VERIFIED |
| Tracker Gaps 369 / 371 / 372 / 375 / 377 / 379 / 381 `[x]` "built" | all corresponding code present in working tree; **none committed** | VERIFIED as code; "built" = working-tree only |

---

## 6. HONEST STATUS

### Feature 26 — chat attached documents

Part 1 (attach → Tier-1/Tier-2 match → confirm → deterministic diff; three endpoints; `ChatAttachment` model; migration `c2d3e4f5a6b7`) is **committed** in `c211662`, passes 33 SQLite/mock-LLM tests, and has a **recorded real-Postgres + Azurite run** (T3 VERIFIED in the committed evidence folder) — this is the only part of either feature that has been proven against a real database.

Part 2 (H1–H5, H10–H12: mock-LLM content marker, per-tenant `chat_docs_*` Chroma sibling, chunk index/search/delete, embed-on-upload with `chunk_count/indexed_at/expires_at` + migration `d3e4f5a6b7c8`, intent split + content branch, and the entire FE surface) exists **only in the uncommitted working tree**. Its 83 backend tests (33 + 39 + 11) pass on SQLite with `get_llm` patched; `tsc --noEmit` is clean; its 42 Playwright tests have never been recorded as run. Migration `d3e4f5a6b7c8` has never been applied to Postgres.

The docs are candid about H6–H9 and V being open — the sweeper script and TTL bicep genuinely do not exist. The most consequential defect is one the docs themselves flag but leave unfiled: `MessageResponse` in `routers/chat.py` strips every `attachment_*` key the agent produces, so **nothing H11/H12 render can arrive from a real backend** — the FE is wired to a contract the API does not emit.

### Feature 27 — generic extraction

**Zero commits.** Roughly 4,000+ lines across `extraction_agent.py` (+1508), `handlers.py` (+338), `models.py` (+163), `chroma_client.py` (+319), the classifier (603), `routers/documents.py` (215), migration `e4f5a6b7c8d9`, plus 16 fixture PDFs — all uncommitted. Behind `ENABLE_GENERIC_EXTRACTION=False` the code is complete for G1–G10 and G14, and 409 tests pass — but **exclusively on SQLite with the LLM, OCR and agent patched** (`run_extraction_agent` and `_run_ocr` are patched without autospec).

The single Postgres test file (`test_documents_table.py`, 38 tests) has **never completed a run**, and the Postgres container log shows the running dev app throwing `column invoice.doc_type does not exist` — the model, migration and the only real database are out of sync. Doc drift here runs in the *understating* direction: G6, G8 and task F are marked open in §10 while the code and fixtures exist and pass. Task V (real Postgres) is honestly marked not started.

Nothing in F27 is "doc-only" in the sense of fabricated code — but everything in it is **working-tree-only and SQLite-only**. "Built" in the tracker should be read as *written and unit-tested behind a flag, never committed, never run against Postgres*.

### Environment notes for the next run

1. The full suite cannot execute until `invoice-postgres-local` (and `invoice-redis-local`, `invoice-chromadb-local`, `invoice-azurite-local`) are unpaused: `docker unpause <name>`.
2. The git-ignored `tests/us/run_chat_live_test.py` / `tests/realworld_tenant/run_chat_live_test.py` basename collision breaks `pytest -x -q` collection outright; use `--ignore=tests/us/run_chat_live_test.py` or rename one locally.
3. `pg_engine_or_skip()` in `test_documents_table.py:60-79` (and the same shape in `test_chat_queue.py:481`, `test_auth.py:1267`) should pass `connect_timeout=` to `psycopg2.connect` so a frozen server skips instead of hanging the whole suite.
4. `alembic.exe` is blocked by the machine's Application Control policy; `uv run python -c "from alembic.script import ScriptDirectory …"` works as a read-only substitute.
