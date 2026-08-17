# Feature 18: Alert-Anchored Trainer & Chat Correction Lane — **EVOLVE (redesigned)**

Supersedes the rule-creation half of [feature_10_trainer.md](feature_10_trainer.md) (which is kept for historical reference and carries a pointer to this file). Session and session-mode mechanics from Feature 10 survive; how a rule comes into existence does not.

Built 2026-08-13. Backend only — a separate frontend pass follows, and the API contracts it needs are spelled out under **Frontend contract** below.

---

## Why this exists

A ground-truth investigation on 2026-08-12/13 (27 real invoices + 13 live chat prompts through the real pipeline) closed four concrete defects — **Gap 222** (credit-note sign loss), **Gap 223** (outbound math verification never ran), **Gap 224** (chat SQL false negative), **Gap 226** (fixed currency symbol). It also surfaced something none of those four individually explained.

The Trainer's rule-creation flow took **free text from a chat box**, had an **LLM interpret it** into an extraction-rule constraint, and **persisted it with no structured checkpoint** in between. Three consequences, all of which showed up in real tenant data:

1. **No grounding.** A rule was never tied to a specific invoice, a specific field, or a specific thing that went wrong. "Global" sessions had no document at all.
2. **No interpretability.** `ExtractionTemplate.rules["constraints"]` was a flat `list[str]`. Once a rule was a sentence, nothing downstream could tell what it was about, what produced it, or whether it was an extraction instruction or a threshold change. Two independent producers (Trainer, and `routers/audit.py::_apply_standing_rule` synthesising `f"For {field}, extract the value as ..."`) wrote into the same undifferentiated bag.
3. **No checkpoint.** The user typed, an LLM decided, and the rule was live. **Gap 212** was the sharpest symptom — during a provider blip, "Remove the rule requiring PO prefix" was stored verbatim *as a new rule*. That was fixed narrowly (fail closed); this redesign fixes it structurally.

Also addressed here: **Gap 217** (guardrail rejection surface), **Gap 221** (chat style stored on the Global template row), **Gap 225** (no mechanism existed for a user to report a semantically-wrong-but-correctly-transcribed field). **Gap 218** (dual-mode sessions) is *not* superseded — the QA-persistence work below builds directly on it.

---

## File Coordinates

**New modules**
* [utils/rule_schema.py](file:///c:/Users/S%20Banerjee/Desktop/Invoice_LLM/Prod_Invoice_LLM/apps/invoice-be/utils/rule_schema.py) → `normalize_constraints()` (the one shared normalizer), `render_constraint()`, `is_structured_rule()`, `rule_kind()`, `merge_constraints()`, `rules_fingerprint()`, builders `build_extraction_rule()` / `build_tolerance_rule()` / `build_confidence_threshold_rule()` / `build_alert_override_rule()` / `build_audit_correction_rule()`, extractors `tolerance_overrides()` / `confidence_threshold_override()` / `alert_overrides()`, and `apply_alert_overrides()`
* [utils/alert_registry.py](file:///c:/Users/S%20Banerjee/Desktop/Invoice_LLM/Prod_Invoice_LLM/apps/invoice-be/utils/alert_registry.py) → `ALERT_TYPES`, `AlertTypeSpec`, `get_alert_type()`, `list_alert_types()`, `TOLERANCE_OVERRIDABLE_TYPES`, `THRESHOLD_OVERRIDABLE_TYPES`, `TOLERANCE_EXCLUDED_SOURCE_TEXT_TYPES`, `VALID_SEVERITIES`
* [services/rule_impact.py](file:///c:/Users/S%20Banerjee/Desktop/Invoice_LLM/Prod_Invoice_LLM/apps/invoice-be/services/rule_impact.py) → `compute_rule_impact()`, `describe_rule()`, `new_rules()`, `_replay_invoice()`, `_recover_subtotal()`
* [services/chat_rules.py](file:///c:/Users/S%20Banerjee/Desktop/Invoice_LLM/Prod_Invoice_LLM/apps/invoice-be/services/chat_rules.py) → `CHAT_RULE_CATEGORIES`, `list_chat_rule_categories()`, `render_chat_rule()`, `validate_chat_rule()`

**Changed**
* [routers/trainer.py](file:///c:/Users/S%20Banerjee/Desktop/Invoice_LLM/Prod_Invoice_LLM/apps/invoice-be/routers/trainer.py) → `start_session_from_invoice()`, `get_session_pdf()`, `get_alert_types()`, `correct_unnecessary_tolerance_alert()`, `correct_unnecessary_confidence_alert()`, `correct_alert_severity_or_message()`, `flag_missed_alert()`, `preview_session_rules()`, `trainer_commit()`, `_handle_qa_test_turn()`, `_ensure_qa_chat_session()`, `_resolve_rule_target()`, `_session_pdf_url()`, `_serialize_alerts()`, `_get_chat_style()` / `_save_chat_style()`; `start_global_session_removed()` and `start_from_production_session_removed()` now 410
* [routers/chat.py](file:///c:/Users/S%20Banerjee/Desktop/Invoice_LLM/Prod_Invoice_LLM/apps/invoice-be/routers/chat.py) → `set_message_feedback()` (extended), `triage_message()`, `triage_source_verdict()`, `preview_chat_rule()`, `commit_chat_rule()`, `list_chat_rules()`, `delete_chat_rule()`, `get_chat_rule_categories()`, `_triage_entry_point()`, `_snapshot_invoices()`, `_normalize_for_diff()`
* [agents/query_agent.py](file:///c:/Users/S%20Banerjee/Desktop/Invoice_LLM/Prod_Invoice_LLM/apps/invoice-be/agents/query_agent.py) → `_get_chat_style_block()` (repointed), `_chat_rules_block()` (new), `_harvest_invoice_ids_from_rows()`, `_harvest_invoice_ids_via_companion_query()`, `_canonical_uuid()`, `execute_generated_sql(snapshot=)`, `run_query_agent()`
* [agents/extraction_agent.py](file:///c:/Users/S%20Banerjee/Desktop/Invoice_LLM/Prod_Invoice_LLM/apps/invoice-be/agents/extraction_agent.py) → `build_multimodal_prompt()`, `extract_node()`, `verify_node()` (now reads `state["rules"]`)
* [agents/outbound_extraction_agent.py](file:///c:/Users/S%20Banerjee/Desktop/Invoice_LLM/Prod_Invoice_LLM/apps/invoice-be/agents/outbound_extraction_agent.py) → `build_outbound_multimodal_prompt()`, `extract_node()`, `verify_node()`
* [utils/verification_tools.py](file:///c:/Users/S%20Banerjee/Desktop/Invoice_LLM/Prod_Invoice_LLM/apps/invoice-be/utils/verification_tools.py) → `verify_line_items_math(tolerances=)`, `verify_totals_math(tolerances=)`, `_tolerance_for()`, `DEFAULT_ABS_TOLERANCE`
* [routers/audit.py](file:///c:/Users/S%20Banerjee/Desktop/Invoice_LLM/Prod_Invoice_LLM/apps/invoice-be/routers/audit.py) → `_apply_standing_rule()` emits structured rules
* [routers/outbound_audit.py](file:///c:/Users/S%20Banerjee/Desktop/Invoice_LLM/Prod_Invoice_LLM/apps/invoice-be/routers/outbound_audit.py) → `_apply_standing_rule_direct()` emits structured rules
* [queue_worker/handlers.py](file:///c:/Users/S%20Banerjee/Desktop/Invoice_LLM/Prod_Invoice_LLM/apps/invoice-be/queue_worker/handlers.py) → `_get_template_rules()`, `_merge_constraints()`
* [queue_worker/outbound_handlers.py](file:///c:/Users/S%20Banerjee/Desktop/Invoice_LLM/Prod_Invoice_LLM/apps/invoice-be/queue_worker/outbound_handlers.py) → `_get_outbound_global_rules()`
* [models.py](file:///c:/Users/S%20Banerjee/Desktop/Invoice_LLM/Prod_Invoice_LLM/apps/invoice-be/models.py) → `TenantChatSettings`, `TenantChatRule`, `ChatFeedback.reason`/`.note`, `ChatMessage.result_invoice_ids`
* Migration `alembic/versions/f18a0c4b7d21_feature_18_chat_training_tables.py`

---

## Functionality

### 1. No more Global-scope rule *creation*

Every extraction rule a user creates is now tied to a real vendor. `POST /trainer/sessions/global` returns **410 Gone** with a pointer to the replacement (410 rather than a deleted route, so a stale client is told what happened instead of getting a 404 that reads like a broken deploy). `trainer_commit()` also refuses a `scope="global"` session, because the gate belongs on the write, not only on session creation — a session created before this deploy is still inside its 1-hour Redis TTL.

**Explicitly NOT removed — and covered by a regression test** (`test_committed_global_rules_are_still_read_after_creation_is_removed`):

* the Global template rows themselves, or any tenant's already-committed rules on them
* `agents/query_agent.py::_get_global_business_rules()`
* `queue_worker/handlers.py`'s first-pass Global rule resolution
* `queue_worker/outbound_handlers.py::_get_outbound_global_rules()`
* `routers/outbound_audit.py`'s Global OUTBOUND read/write

**Outbound is the one structural exception.** An outbound invoice has no `vendor_name` at all — the counterparty is `customer_name`, a different party — so outbound rules have nowhere else to live and continue to write to the Global OUTBOUND row (`vendor_name IS NULL`, `flow_direction="OUTBOUND"`). This is represented by its own scope value, `outbound_global`, so it is never confused with the Global-scope creation that was removed.

### 2. One unified session entry point

`POST /trainer/sessions/from-invoice` `{invoice_id, session_mode?}`. Two ways to reach the same landing state — that invoice's `sa_alerts` list, next to that invoice's PDF:

* **History path** — loads an already-stored extraction result for **one specific invoice**. `POST /trainer/sessions/from-production?vendor_name=X` is now 410: it resolved `order_by(created_at.desc()).first()`, so it could only ever open a vendor's *latest* invoice (an alert on any older one was simply unreachable), and it re-ran a full Document Intelligence pass on every load. The replacement does **no reprocessing at all** — `test_from_invoice_does_not_rerun_ocr` asserts `_run_ocr` is never called, because the cost of a silent regression here is a paid OCR call per session open.
* **Upload path** — `POST /trainer/upload` still runs the real OCR + extraction flow, and now returns that document's real alerts in the same session shape.

`ocr_text` is deliberately empty on the history path. Its only consumer is the legacy conversational refinement path, which already treats empty `ocr_text` as "chat-only, don't re-extract"; the correction endpoints work off stored alerts, not raw text.

**`pdfUrl` is always populated, server-side, for both paths.** Previously only an `existing_vendor` session with a `sample_invoice_id` got one, and upload-path sessions relied on the FE holding a client-side object URL for the File it had just uploaded — which survived neither a page reload nor opening the session on another device, on a screen whose whole job is "look at the alert next to the document that caused it". `_session_pdf_url()` returns `/api/invoices/{id}/pdf` for a stored invoice, or `/api/trainer/sessions/{id}/pdf` (new streaming endpoint) for a transient upload.

### 3. Structured rule schema + dual-format reads

`ExtractionTemplate.rules["constraints"]` now holds tagged objects **alongside** legacy strings. No migration was needed for this — the column is already JSON.

```json
{
  "field": "tax_amount",
  "condition": "abs_tol=5.0;rel_tol=0.01",
  "scope": "vendor" | "global" | "outbound_global",
  "source_alert_type": "tax_mismatch",
  "origin": "trainer_alert_correction",
  "text": "Treat a 'tax_mismatch' difference as acceptable when it is within 5.00 absolute or 1% relative.",
  "kind": "extraction" | "tolerance_override" | "confidence_threshold_override" | "alert_override",
  "params": {"abs_tol": 5.0, "rel_tol": 0.01}
}
```

**One shared normalizer, written once and used everywhere** — `utils.rule_schema.normalize_constraints()`. A legacy string and a structured object render into identical prompt text. Wired into every read site: `agents/extraction_agent.py` (prompt builder, both prompt branches, both `active_constraints` sites), `agents/outbound_extraction_agent.py` (both branches), `agents/query_agent.py` (`_get_global_business_rules`, `_get_vendor_business_rules`), `queue_worker/handlers.py`, `queue_worker/outbound_handlers.py`, `routers/audit.py`, `routers/outbound_audit.py`, `routers/trainer.py` (session serialization + version history).

**`for_prompt=True` is the default, and it filters.** Tolerance/threshold/severity rules are *deliberately excluded from extraction prompts*: they are consumed by `verify_node`, and feeding numeric slack into the extraction prompt would fight `GAP_46_VERBATIM_DIRECTIVE`, which exists precisely to stop the model smoothing numbers so arithmetic reconciles. Display and history surfaces pass `for_prompt=False`.

**Both auditor standing-rule producers migrated in this pass** (not deferred — leaving a second free-text producer alive would defeat the point): `routers/audit.py::_apply_standing_rule()` and `routers/outbound_audit.py::_apply_standing_rule_direct()` now emit structured objects via `build_audit_correction_rule()`. The rendered `text` is **byte-identical** to the sentence they always produced, so the extraction prompt is unchanged; the field/old/new are simply also recoverable structurally now. Their API responses keep `rules_added` as a list of plain sentences (unchanged FE contract) and add `rules_added_structured` alongside.

### 4. Alert-type registry

`utils/alert_registry.py` enumerates every alert `type` the system produces — 17 in total, each verified against its live producer, not copied from a doc. Exposed at `GET /trainer/alert-types`.

| Producer | Types |
|---|---|
| `utils/verification_tools.py` | `line_item_calculation_mismatch` (:71), `line_items_mismatch` (:87), `tax_mismatch` (:142), `total_not_verified_in_source` (:225), `line_item_not_verified_in_source` (:275), `subtotal_not_verified_in_source` (:305), `unit_price_not_verified_in_source` (:344), `tax_amount_not_verified_in_source` (:412), `low_confidence_field` (:500) |
| `agents/extraction_agent.py` | `extraction_failed` (:308, :319), `token_limit_exceeded` (:566) |
| `agents/outbound_extraction_agent.py` | `extraction_failed`, `missing_required_field` (:148), `token_limit_exceeded` |
| `queue_worker/handlers.py` / `outbound_handlers.py` | `duplicate_invoice` (:663), `duplicate_invoice_number` (:87) |
| `routers/invoices.py` | `duplicate` (:93, :137) |
| `services/invoice_reconciliation.py` | `processing_failed` (:63), `processing_timeout` (:180) |

**Correctability, deliberately narrow:**

| Correction form | Types | Why |
|---|---|---|
| `tolerance` (`abs_tol`/`rel_tol`) | `line_item_calculation_mismatch`, `line_items_mismatch`, `tax_mismatch` | The only three produced by a tolerance-taking function (`verify_line_items_math`, `verify_totals_math`) |
| `confidence_threshold` (`threshold`) | `low_confidence_field` | A **different parameter** on a **different function** (`verify_field_confidence`, default `CONFIDENCE_THRESHOLD = 0.4`). Its own form — conflating it with the tolerance one would have shipped a control whose numbers silently did nothing |
| `severity_message` | any type | Relabelling never changes whether an alert fires |
| none | the five `*_not_verified_in_source`, duplicates, failures, timeouts | See below |

> **Documented follow-up, not a silent gap.** The five `*_not_verified_in_source` types (`total_`, `line_item_`, `subtotal_`, `unit_price_`, `tax_amount_`) are **explicitly excluded from the "unnecessary alert" tolerance path in this pass**. They ask a verbatim-presence question ("does this figure appear in the OCR text?") that has no numeric band to widen — there is nothing a tolerance form could adjust. They are exposed as `TOLERANCE_EXCLUDED_SOURCE_TEXT_TYPES`, returned under `toleranceExcluded` by `GET /trainer/alert-types`, and the tolerance endpoint 400s on them with the registry's own explanation rather than accepting a write that would do nothing. **Follow-up:** decide what "this source-text alert is unnecessary" should mean — most likely a per-vendor allow-list of known-unprintable figures, or a switch to fuzzy verbatim matching — and build a form for it then. Duplicates, failures and timeouts are excluded permanently: they report facts, not thresholded judgements.

### 5. Correction endpoints — four shapes

All four **stage** a candidate rule into the session. None writes to a template; every one has to clear the preview gate and `/commit`.

1. `POST /trainer/sessions/{id}/corrections/tolerance` — restricted to the three eligible types.
2. `POST /trainer/sessions/{id}/corrections/confidence-threshold` — separate form, own rule kind. Threshold clamped to `(0, 1]`: a threshold of 0 would disable the check entirely, which is suppression, not tolerance-widening, and this flow deliberately doesn't offer it.
3. `POST /trainer/sessions/{id}/corrections/alert-override` — `severity` (`error`/`warning`/`info`) and/or `message`. Never changes *whether* an alert fires; conflating "call this a warning" with "stop telling me" is how real findings get lost. The original computed text is preserved as `original_message`.
4. `POST /trainer/sessions/{id}/corrections/missed-alert` — the user picks the expected alert type from the registry and names the field. **Both are structured picks and both are the primary input**; the optional `context` string is passed to the LLM as *secondary* colour only. The prompt is anchored on the registry pick plus the real stored value of that field on that specific invoice, so an empty context box still produces a grounded rule and a rambling one cannot become the whole input. This is the only LLM-interpreted path — there is no deterministic mapping from "I expected a tax mismatch here" to a formal constraint — and it **fails closed** exactly like Gap 212: on LLM failure or an empty draft, nothing is staged and the user is told to retry.

**Verification wiring (the actual gap).** `agents/extraction_agent.py::verify_node` **never read `state["rules"]` at all**, despite `rules` being part of `ExtractionState` and read by `extract_node` — so a committed correction had nothing downstream that consulted it. It now resolves tolerances, the confidence threshold, and severity/message overrides from the tenant's rules. The same wiring was added to `agents/outbound_extraction_agent.py::verify_node` (Gap 223 wired the *checks* in but left them on hardcoded tolerances).

`utils/verification_tools.py` gained **only** an optional `tolerances` parameter on the two relevant functions — the checks themselves are unrestructured, and omitting the parameter reproduces the previous behaviour byte-for-byte (asserted by `test_tolerance_defaults_are_byte_identical_to_pre_feature_18`). Severity/message relabelling runs as an `apply_alert_overrides()` post-pass *after* the checks, never inside them.

### 6. The preview-before-commit gate

`POST /trainer/sessions/{id}/preview` — one gate, reused by every correction path.

Returns three things:

* **The structured interpretation** of each new rule (field / condition / scope in plain terms) — so the user approves a *rule*, not a sentence.
* **Historical impact**, which is either real or absent:
  * `exact` — the rule is a pure function over already-stored columns, so `services/rule_impact.py` replays it against every historical invoice using **the same verification functions the pipeline uses** (never a reimplementation, so the preview can't drift from reality). A query and a loop; no re-extraction, no OCR, no LLM.
  * `not_computable` — a free-text extraction rule. Its effect depends on how an LLM reads a PDF, so **no number is shown**, never a fabricated zero.
  * `partial` — some of both, with the uncomputable part named explicitly.
* **A `previewToken`** (a fingerprint of the session's rules).

Only the *difference* against what is already committed is described and replayed — re-reporting live rules would inflate the number the user is being asked to approve. Replay is capped at `MAX_REPLAY_INVOICES = 500` and the response reports `invoicesExamined`, so the figure is never presented as "all of them" when it isn't.

**Gap 217's guardrail now runs at preview time**, where a rejection is cheap and the user is still editing. It runs on the free-text rules only (a tolerance number can't be a behavioural instruction). It **also still runs on `/commit`**, which remains the backstop for a direct API caller who never previewed — the 400 contract Gap 217 established is unchanged.

`/commit` accepts an optional `preview_token` and **409s if the session's rules drifted** since it was issued. Optional rather than required, so direct API callers and the pre-Feature-18 FE keep working. Everything else in `trainer_commit()` is unchanged: versioning, `ExtractionTemplateVersion` in the same transaction, re-audit enqueue, the Gap 213 unconditional cache flush, `IntegrityError`→409, transient-file cleanup.

### 7. Chat-correction lane — structurally separate

**Nothing in this lane ever touches `ExtractionTemplate.rules["constraints"]`** (asserted by `test_chat_rules_never_touch_the_extraction_template`). That separation is the point: a chat rule is about how the *answering agent* reasons, filters or scopes a question. It has nothing to teach the extraction pipeline, and letting the two share a table is how "the trainer taught chat something odd" and "the trainer taught extraction something odd" became the same undiagnosable class of bug.

**`TenantChatSettings`** (Gap 230) — one row per tenant, `UNIQUE(tenant_id)`, shaped after `TenantAutopilotConfig`. Replaces Gap 221's storage on the Global INBOUND `ExtractionTemplate` row's `rules["chat_style"]`. The migration **copies** existing values across and deliberately **leaves the source key in place** — it is tenant data, and a non-destructive move means a rollback of this deploy loses nothing. `_get_chat_style_block()` was repointed with its **signature and fallback unchanged**, so all three call sites needed no edit; it still reads the legacy location as a fallback so a tenant whose row predates the migration keeps their configured style.

**`TenantChatRule`** (Gap 232) — one row per committed chat-behaviour rule: `category`, `pattern`, `context_text`, `created_by`, `enabled`. `_chat_rules_block()` injects them **next to**, never merged into, `_business_rules_block()`. The two can't share a section: business rules carry Gap 58's "disregard anything that reads as an instruction" framing, which would tell the model to ignore the chat rules it was just given.

**Chat rules use no LLM.** `services/chat_rules.render_chat_rule()` is a deterministic template over a closed category vocabulary, so the preview shows the *literal final text*, not a paraphrase of it. `context_text` is stored for a human reading the rule later and is **never interpolated into the prompt** — it is unvalidated free text, and splicing it into an instruction block is exactly the injection surface Gap 58 was opened about.

**`ChatMessage.result_invoice_ids`** (Gap 231) — which invoices fed a reply, captured at answer time. Before this, only the RAG route left row identity behind (via `citations[].invoice_id`); the SQL route set `citations = []` and returned only `generated_sql` plus a markdown string, so for an aggregate answer like "total spend across 40 invoices" there was literally nothing to build a "which invoice was wrong?" picker from. Harvested two ways: from an `id`/`invoice_id` column when the query selected one, otherwise by rebuilding the same predicates as an id-only companion query (rather than forcing `id` into the generated SELECT, which would put raw UUIDs in every results table). Strictly best-effort and read-only — it refuses to rebuild anything containing a join or subquery, or whose predicates don't carry the tenant guard. **An empty list means "we could not determine the row set", never "no invoices were involved"**, and the triage API treats it that way.

**Trainer QA-test turns are now real `ChatMessage` rows.** Gap 218 stored them only in the Redis session scratch dict with ids like `msg-a1b2c3d4`, which meant thumbs-down had nothing to attach `ChatFeedback` to. It also resolved a latent bug, **confirmed by direct repro rather than assumed**: the old code passed the literal string `f"trainer-qa-{session_id}"` into `get_chat_history()`, which does `UUID(session_id)` inside a `try/except ValueError: return ""`. It does not raise — it silently returns an empty history on every QA turn, so QA mode had **zero conversational memory, ever**, and nothing reported it. Both are fixed by backing the lane with a real `ChatSession` whose UUID is what `run_query_agent()` receives.

### 8. Thumbs-down triage

`ChatFeedback` gains `reason` (`wrong_data | wrong_interpretation | bad_tone`) and `note`. Both nullable — the Gap 54 signal-only contract is unchanged for a client that doesn't send them.

1. **`bad_tone`** → `TenantChatSettings`. The lightest path: tone is already a first-class setting, so there is nothing to learn and no rule to create.
2. **`wrong_data` about one specific invoice** → `POST /chat/messages/{id}/triage` **automatically diffs** what chat said against the stored DB value. No human judgement — it's a value diff.
   * **mismatch** → chat misreported its own source data. Provably a chat bug → straight to the chat-rule path.
   * **match** → chat reported the stored value faithfully, so the open question is whether the *stored* value is right. The FE asks the human to check the PDF, and `POST /chat/messages/{id}/triage/source-verdict` handles the answer:
     * `pdf_agrees=false` → **this is not a chat correction at all.** Teaching the chat agent anything here would paper over bad extracted data with a rule about how to talk about it. Returns `next: "extraction_flag_missed"` plus a `redirect` block (`invoiceId`, `field`, `flowDirection`, `vendorName`, and the three trainer endpoints) so the FE can open the extraction flow pre-filled.
     * `pdf_agrees=true` → continues as a genuine chat-behaviour correction.
   * Numeric comparison is normalized on both sides — the stored column is a float (`110.0`) while the FE captures what the user saw as a string (`"110.00"`, `"$110.00"`). Comparing those as raw text would report a mismatch on two values that are plainly the same money and tell the user their assistant was wrong when it wasn't.
   * When `claimed_value` isn't supplied, the diff falls back to checking whether the stored value appears in the reply text. That weaker basis is reported as `basis: "reply_contains_stored_value"` so nothing mistakes it for an exact comparison.
3. **`wrong_data` about an aggregate, or `wrong_interpretation`** → a **structured category pick**, not free text: `should_have_included`, `should_have_excluded`, `wrong_date_range`, `search_line_item_descriptions`, `wrong_direction`, `wrong_aggregation`, `wrong_status_filter`, `missing_currency_context`.
4. **Preview before commit, here too.** `POST /chat/rules/preview` → explicit confirm → `POST /chat/rules/commit` with the matching token (409 on drift). **No silent-save straight off a thumbs-down** — commit without a token is a 400.

Permissions: reading triage and previewing a rule are open to any tenant user (anyone who can see a bad answer should be able to report it); committing or deleting a `TenantChatRule` requires `can_train`, because it changes how every future answer for the whole workspace is scoped.

---

## Frontend contract

For the FE pass that follows. `PdfViewerPanel` is already a standing, always-rendered element — the `pdfUrl` work above is data population, not new plumbing.

| Endpoint | Purpose |
|---|---|
| `POST /trainer/sessions/from-invoice` | `{invoice_id, session_mode?}` → session (always has `pdfUrl`, `alerts`, `invoiceId`, `flowDirection`) |
| `GET /trainer/sessions/{id}/pdf` | Transient upload-path PDF. **Needs a same-origin proxy route at `/api/trainer/sessions/{id}/pdf`** (mirroring the existing `/api/invoices/{id}/pdf`) — this is the one new FE plumbing item |
| `GET /trainer/alert-types?flaggable_only=` | Registry: `correctionForm`, `notCorrectableReason`, `toleranceExcluded` |
| `POST /trainer/sessions/{id}/corrections/{tolerance,confidence-threshold,alert-override,missed-alert}` | Stage a rule → `{updatedSession, stagedRule}` |
| `POST /trainer/sessions/{id}/preview` | `{previewToken, newRules[], impact}` |
| `POST /trainer/sessions/{id}/commit` | Body `{preview_token}` → 409 on drift |
| `PUT /chat/messages/{id}/feedback` | Now takes `{vote, reason?, note?}`; a thumbs-down response carries `triage.next` |
| `POST /chat/messages/{id}/triage` | `{invoice_id, field, claimed_value?}` → `{diff, next}` |
| `POST /chat/messages/{id}/triage/source-verdict` | `{invoice_id, field, pdf_agrees}` → chat rule, or the extraction redirect |
| `GET /chat/rules/categories`, `POST /chat/rules/preview`, `POST /chat/rules/commit`, `GET /chat/rules`, `DELETE /chat/rules/{id}` | Chat-behaviour rules |

Session shape additions: `invoiceId`, `flowDirection`, `alerts[]`, `activeRulesDetailed[]`. `activeRules` remains a list of plain sentences. Removed: `POST /trainer/sessions/global` and `POST /trainer/sessions/from-production` both 410.

---

## Deviations from the approved plan

Recorded rather than quietly absorbed.

1. **The upload path does not create an `Invoice` row, so it does not literally call `from-invoice`.** The plan described the upload path as "hands off to `from-invoice` once the row exists". A trainer upload deliberately creates no `Invoice` row — it would consume the tenant's free-invoice quota, appear on the dashboard, and contradict `test_new_vendor_upload_returns_session_shape`, which explicitly asserts no `Invoice` is created. Instead both paths produce the **same session shape and the same landing state** (real alerts + server-side `pdfUrl`) through shared serialization, with `GET /trainer/sessions/{id}/pdf` added to give the upload path a real server-side URL. The user-visible outcome the plan asked for is delivered; the mechanism differs.
2. **`Invoice` has no `subtotal` column.** The plan assumed the exact replay could read `Invoice.items/subtotal/tax_amount/grand_total`. Verified against `models.py`: `subtotal` is extracted but never persisted. Consequence: `line_item_calculation_mismatch` is replayable exactly (its per-line check uses only stored `items` fields), while `line_items_mismatch` and `tax_mismatch` need a subtotal, which is recovered from `Invoice.source_document_json["SubTotal"]` (Gap 178) when present. When it isn't, those two are reported **not computable for that invoice** — never estimated, and never silently counted as "no change", which would have understated exactly the rules most likely to be committed.
3. **Confidence-threshold and severity-override rules are also `exact`, not `not_computable`.** The plan said exact for "tolerance/math-class" rules. `field_confidence` and `sa_alerts` are both stored columns, so these replay exactly too. Reporting them as uncomputable would have withheld a real number for no reason.
4. **Migration revision ID collision.** The first ID chosen (`a1b2c3d4e5f6`) was already used by `a1b2c3d4e5f6_invoice_completed_at.py`; alembic reported "Revision present more than once". Renamed to `f18a0c4b7d21`.
5. **Outbound commits do not enqueue a re-audit.** `_enqueue_reaudit(tenant, None)` means "every vendor", which would fan out across the tenant's entire INBOUND history for a rule that only affects outbound invoices. Skipped rather than approximated with the wrong fan-out. **Follow-up:** an outbound-scoped re-audit task.
6. **`TenantChatSettings` / `TenantChatRule` carry no `tenant.id` foreign key.** The plan said to model them on `TenantAutopilotConfig`, which has one. The `UNIQUE(tenant_id)` shape is copied as specified, but the FK is omitted to match the closer analogues these tables actually sit alongside (`ExtractionTemplate`, `WebhookSubscription`, `ChatSession`), all of which use a plain indexed `tenant_id`.
7. **One product-code fix found by a test, not by review:** `_normalize_for_diff()` originally compared a string `claimed_value` as text against a float column, so `"110.0"` vs `110.0` reported a mismatch — which would have routed a *correct* answer into the "chat misreported its data" branch. Both sides are now coerced numerically. Similarly, harvested invoice ids are normalized through `_canonical_uuid()` because PostgreSQL returns `uuid` objects while SQLite returns dashless hex.

---

## Verification Plan

**Automated** — 552 passed / 0 failed / 5 deselected across the whole backend suite (baseline before this work: 470), verified under both `-p no:randomly` and default random ordering.

* `tests/test_rule_schema.py` (18) — the dual-format guarantee. Legacy strings and structured objects render identically; a legacy-only template still reaches every real read site (Chat prompt injection, the worker's two-stage resolution, both extraction prompt builders); malformed stored rules never raise; `for_prompt` filtering keeps numeric rules out of extraction prompts.
* `tests/test_verification_overrides.py` (9) — omitting `tolerances` is byte-identical to pre-Feature-18; overrides are per alert type; `verify_node` actually reads `state["rules"]` (inbound and outbound); legacy prose never gets parsed as config.
* `tests/test_trainer.py` (63, was 35) — the registry, all four correction shapes, the five source-text rejections (parametrized), exact vs `not_computable` preview impact, the guardrail at preview time, stale-token 409, 410s on removed endpoints, `_run_ocr` never called on the history path, specific-invoice (not latest) selection, QA turns as real `ChatMessage` rows, and the `get_chat_history` repro.
* `tests/test_chat_training.py` (29) — snapshot harvesting (both paths, plus the refusals), triage routing, the auto-diff's two outcomes, the extraction redirect, chat-rule preview/commit/409, chat rules never touching `ExtractionTemplate`, and the two prompt blocks staying separate.

**Migration** — verified on a **throwaway Postgres database** (`f18_migtest`), not SQLite: full chain upgrade → head; seeded a real `rules["chat_style"]` row; re-upgraded and confirmed it copied into `tenant_chat_settings` with the source key still present; downgraded clean with both tables dropped and the source data intact. *(The chain cannot run on SQLite at all — pre-existing migration `71d18e2c3349` uses a non-batch `ALTER`. Unrelated to this work, and consistent with `feature_12_alembic.md`'s note that the chain is verified against Postgres.)*

**Not yet done — manual/live verification.** Nothing here has been exercised against a real tenant with real Azure OCR/LLM. Specifically outstanding: the `missed-alert` drafting prompt against a real model, the preview impact numbers against a real tenant's invoice history, and the FE half of every flow above.
