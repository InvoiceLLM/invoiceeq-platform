# Feature 30 — Business Intelligence (chat-attachment intelligence bubble for non-invoice financial documents)

**App:** invoice-be · **Status:** lives in `be_features_tracker.md` · **Counterpart:** FE Feature 21 (`apps/invoice-fe/docs/feature_21_business_intelligence.md`)
**Split from:** Feature 29 LLM Optimisation, founder 2026-09-07: "the separate spec is for giving additional intelligence to end user while a document is uploaded … by upload I mean the chat area document upload only … the insight block should be shown in the chat screen and if needed can be stored for future use … temp intelligence only when a financial document is attached in chat which are not invoice type." Tasks 29.13–29.19 move here as building blocks (29.13 deferred as 30.16) (hard rule 4: Feature 29's spec is not rewritten; it carries a scope note pointing here).

## 1. Overview

**Trigger.** A user attaches a **non-invoice financial document** in the chat composer (`POST /chat/sessions/{id}/attachments`, Feature 26): purchase order, quotation, order confirmation, contract, credit note, debit note, statement of account, remittance advice, delivery note. Invoices attached in chat, and every upload through the ingestion pipeline (Feature 2), are out of scope and behave exactly as today.

**Behaviour.** After extraction and matching, the system speaks first: a deterministic **insight block** for that document is computed and posted into the chat as an assistant turn, before any question is asked. The block is **temporary**: it lives on the chat message and the `ChatAttachment` row for the life of the session and is removed by the existing chat-document TTL job (`caj-chat-doc-ttl-dev`) with the attachment. Nothing is written to `invoice`, no aggregate moves, no billing counter moves (Feature 26 D2/D3). "If needed can be stored for future use": a user may **pin** the block, which copies it to a durable table for reuse across sessions; unpinned blocks expire.

**Cards, by document type.** Every figure is computed in code; the model narrates (hard rule 3).

| card | shown for | what the user sees | computed by |
|---|---|---|---|
| What this is | all | doc type, number, party, date, currency, total, and which invoices / POs on file it relates to (Tier 1/2 match) | Feature 26 match + `_compare_one` |
| Agreed vs billed | PO, quotation, order confirmation, contract | every invoice already billed against it, header and line deltas, over/under-billing, remaining commitment | Feature 29 compare + `compute_amount_owed(agreed=…)` |
| Terms check | contract, PO | tax rate, discount, late fee, payment days extracted from the document vs what the related invoices carry | Feature 29 `extract_contract_terms` / `compare_contract_terms_to_invoice` |
| Net position | credit note, debit note, remittance, statement | amount owed after applying this document; which invoices it settles or adjusts; unapplied balance | Feature 29 ledger (`owed_sign`, `compute_amount_owed`) |
| Statement reconcile | statement of account | line-by-line match of the vendor's statement against our invoices and payments; missing on our side, missing on theirs | new `reconcile_statement()` over `v_3way_match` / `v_overdue` (30.3) |
| Delivery vs order | delivery note | quantities delivered vs ordered vs invoiced per line; short / over deliveries | Feature 29 line matching + `check_line_arithmetic` |
| Compliance of the document | all, region-aware | rule-card checks that apply to this doc type (PO/contract: GST registration + place of supply; credit note: GST credit-note conditions; EU: VAT id format, reverse-charge wording) with the citing rule | 30.9–30.11 rule cards + verify |
| Cash impact | PO, contract, credit note, statement | expected outflow by month, discount window, what is already overdue with this party | 30.6 over `v_overdue`, `v_vendor_spend` |
| Suggested questions | all | three certified questions relevant to this doc type ("what has been billed against this PO?", "what do we owe after this credit note?") | 30.8 certified examples |
| Confidence & gaps | all | low-confidence extracted fields; cards skipped and why (no related invoice, no HSN, flag off) | 30.12 |
| Feedback | all | thumbs per card; a thumbs-down with a correction feeds the flywheel | 30.13 |

**What this is not.** Not invoice insights (an invoice attached in chat gets today's Feature 26/29 behaviour, no block). Not the ingestion pipeline. Not a dashboard or Workbook page. Not chat answering (Feature 29 owns model roles, the entity resolver and the planner). Not the FE rendering (FE Feature 21).

## 2. File coordinates

| path | named function / component | new or edit | what it does |
|---|---|---|---|
| `services/attachment_insights.py` | `INSIGHT_DOC_TYPES` (frozenset of the nine non-invoice types), `is_insight_doc_type(doc_type)` | new | The trigger gate; INVOICE and OTHER never qualify |
| `services/attachment_insights.py` | `InsightCard` (dataclass: `card`, `status` ok/skipped/blocked, `figures`, `evidence`, `reason`), `CARDS_BY_DOC_TYPE`, `build_insight_block(row, db_session, tenant_id) -> dict` | new | Runs the cards registered for the doc type in fixed order; never raises; a card whose inputs are missing returns `skipped` with a reason |
| `services/attachment_insights.py` | `card_what_this_is()`, `card_agreed_vs_billed()`, `card_terms_check()`, `card_net_position()`, `card_statement_reconcile()`, `card_delivery_vs_order()`, `card_compliance()`, `card_cash_impact()`, `card_suggested_questions()`, `card_confidence_gaps()` | new | One function per card; pure Python + SQL, no model call |
| `services/attachment_insights.py` | `narrate_insight_block(block, llm) -> str` | new | Single gpt-5-mini call (`resolve_model("chat_summary")`); the prompt states every figure is given and must not be recomputed |
| `services/attachment_insights.py` | `post_insight_turn(row, block, narration, db_session) -> ChatMessage` | new | Writes the assistant `ChatMessage` with `attachment_payload["insights"] = block`; `ChatAttachment.insights = block` |
| `services/document_comparison.py` | `reconcile_statement(statement_lines, invoices, payments)` | new | Statement-of-account matching: number, amount, date tolerance; returns matched / ours-only / theirs-only |
| `services/attachment_extraction.py` | `extract_attachment()` | edit | After `match_attachment()`: if `ENABLE_ATTACHMENT_INSIGHTS` and `is_insight_doc_type(row.doc_type)`, build → narrate → post; failure recorded on the row, never a 500 |
| `queue_worker/handlers.py` | `handle_extract_attachment()` | edit | Same hook on the async path |
| `models.py` | `ChatAttachment.insights: dict \| None` | edit | Temporary block, removed with the row by the TTL job |
| `models.py` | `PinnedInsight(id, tenant_id, source_attachment_id, doc_type, doc_number, party_name, block, pinned_by, pinned_at)` | new | Durable copy, only on pin |
| `alembic/versions/<rev>_add_chat_attachment_insights.py` | `upgrade()` | new | Add-only: column + `pinned_insight` table |
| `routers/chat_attachments.py` | `AttachmentOut.insights`; `GET /attachments/{id}/insights` → `get_attachment_insights()`; `POST /attachments/{id}/insights/pin` → `pin_insight()` | edit | Reload and pin |
| `routers/chat.py` | `MessageResponse.insights: dict \| None` | edit | Additive, defaults None (`exclude_none` keeps old turns byte-identical); the widening Gap 474 asks for |
| `routers/chat.py` | `POST /messages/{id}/insight-feedback` → `insight_feedback()` | edit | Card-level thumbs; writes `chat_correction` |
| `config.py` | `ENABLE_ATTACHMENT_INSIGHTS: bool = False` | edit | Master flag; the Feature 29 capability flags (Gap 482) gate their cards |
| `services/semantic_views.py` + `alembic/versions/<rev>_add_semantic_views.py` | `METRICS`, `query_metric(name, tenant_id, **filters)`; views `v_vendor_spend`, `v_overdue`, `v_tax_summary`, `v_3way_match` | new | 29.14: used by statement-reconcile, cash-impact, agreed-vs-billed |
| `services/certified_examples.py` + `alembic/versions/<rev>_add_certified_sql_example.py` | `certify_example()`, `retrieve_examples(question, k=5)`, `seed_from_golden()` | new | 29.15: feeds suggested questions and the SQL prompt |
| `services/knowledge.py` | `KnowledgeDoc`, `index_knowledge()`, `lookup_glossary()`, `lookup_rule()` | new | 29.16: `knowledge_{tenant}` collection; glossary terms used in narration |
| `services/rule_cards.py` + `knowledge/rule_cards/{in,eu,us}/*.md` | `load_rule_cards()`, `RuleCard(source_url, effective_from, owner, review_at, applies_to_doc_types)`, `verify_checks_for(card)` | new | 29.17: cards from fetched primary sources; each declares which doc types it applies to |
| `services/rerank.py` | `rerank(query, chunks, k)` | new | 29.18: behind `ENABLE_RERANK`, only if recall instrumentation shows ranking is the limit |
| `services/chat_corrections.py` + `alembic/versions/<rev>_add_chat_correction.py` | `record_correction()`, `promote_to_example()` | new | 29.19 flywheel |
| `infra/monitoring/ai_control_tower_workbook.json` | panel "Chat quality trend" | edit | 29.19 |
| `benchmarks/insight_golden.json`, `scripts/run_insight_eval.py` | `run_insight_eval()` | new | 20 non-invoice attachments × expected cards |

## 3. Functionality

1. **Upload.** `upload_chat_attachment()` stores the file and runs `extract_attachment()` synchronously (Feature 26). Unchanged.
2. **Gate.** The extractor's `doc_type` decides. `INVOICE` and `OTHER` → no block, today's behaviour. One of the nine non-invoice types → continue. Doc types not yet in the extractor's discriminator (credit note, statement, delivery note…) are added to the REFERENCE profile in 30.1; until then they classify as OTHER and get no block.
3. **Match.** `match_attachment()` fills `candidate_invoice_ids`. Unchanged.
4. **Block.** `build_insight_block()` looks up `CARDS_BY_DOC_TYPE[doc_type]` and runs those cards in order. Each returns an `InsightCard`; missing inputs → `skipped` with reason; an exception inside a card → `blocked`, logged with the attachment id, and the remaining cards still run. Every query carries the request's `tenant_id`; `query_metric()` refuses a call without it.
5. **Narration.** One gpt-5-mini call with the block as JSON and the Feature 29 rule: figures are given, the model must not compute. Glossary terms from `lookup_glossary()` are supplied so the narration uses the tenant's vocabulary.
6. **Post.** `post_insight_turn()` writes the assistant `ChatMessage` with `attachment_payload["insights"]` and citations to the related invoices; `ChatAttachment.insights` holds the same block. The FE renders the cards under the bubble (FE Feature 21).
7. **Temporary by default.** The block lives with the attachment and message; the TTL job removes both. A later turn in the same session sees the block in `judge_evidence` and the full-record context (Feature 29 29.5), so "what did you flag on this?" answers from the block.
8. **Pin.** `POST /attachments/{id}/insights/pin` copies the block into `pinned_insight`. Pinned blocks are retrievable by doc number / party in later sessions through the entity resolver (Feature 29 29.11) and are the only durable trace.
9. **Feedback.** Thumbs-down on a card → `insight_feedback()` → `record_correction()`; an approved correction becomes a certified example (suggested questions) or a rule-card review flag (compliance).

## 4. Data & schema changes (all add-only, no backfill)

| change | migration |
|---|---|
| `chat_attachments.insights` JSON nullable; table `pinned_insight` | `<rev>_add_chat_attachment_insights` |
| views `v_vendor_spend`, `v_overdue`, `v_tax_summary`, `v_3way_match` | `<rev>_add_semantic_views` |
| table `certified_sql_example(id, tenant_id nullable, question, sql, certified_by, certified_at)` | `<rev>_add_certified_sql_example` |
| table `chat_correction(id, tenant_id, message_id, card, corrected_text, corrected_sql, promoted_example_id, created_by, created_at)` | `<rev>_add_chat_correction` |

## 5. Tasks

| id | task | was |
|---|---|---|
| 30.1 | `ENABLE_ATTACHMENT_INSIGHTS`; `INSIGHT_DOC_TYPES` gate; REFERENCE profile discriminator extended to the nine types; `attachment_insights.py` skeleton (`InsightCard`, `CARDS_BY_DOC_TYPE`, `build_insight_block`, `narrate_insight_block`, `post_insight_turn`); hooks in both extraction paths; **cards "what this is" + "agreed vs billed" + "terms check" + "net position" + "delivery vs order"** reusing Feature 29 code as-is | new |
| 30.2 | Temporary storage: `ChatAttachment.insights`; `pinned_insight` table + pin endpoint; `AttachmentOut.insights`; `GET …/insights`; `MessageResponse.insights` (additive); TTL job removes unpinned blocks with the attachment | new, settles Gap 474's shape |
| 30.3 | Semantic views migration (4 views, each with `tenant_id`) | 29.14a |
| 30.4 | `METRICS` + `query_metric()` with the parameterised tenant guard; SQL schema link prefers a metric | 29.14b |
| 30.5 | `reconcile_statement()` + statement-reconcile card | new |
| 30.6 | Cash-impact card over `v_overdue`, `v_vendor_spend` | new |
| 30.7 | Knowledge layer + glossary-aware narration | 29.16 |
| 30.8 | Certified examples table + retrieval + `seed_from_golden()`; suggested-questions card (top-3 by doc type) | 29.15 |
| 30.9 | India rule cards (CBIC/GSTN primary sources) with `applies_to_doc_types` | 29.17a |
| 30.10 | EU + US cards | 29.17b |
| 30.11 | Compliance card: deterministic `verify` checks per card and doc type | 29.17c |
| 30.12 | Confidence & gaps card | new |
| 30.13 | Flywheel: `chat_correction`, `insight-feedback`, `record_correction()`, `promote_to_example()`; workbook panel | 29.19 |
| 30.14 | Reranker behind `ENABLE_RERANK`, only if Feature 29 recall instrumentation shows ranking is the limit | 29.18 |
| 30.16 | Planner + capability registry (`plan_turn()`, `CAPABILITIES`), flag-gated behind `ENABLE_CHAT_PLANNER`; **deferred** — moved out of Feature 29 on 2026-09-07 (founder: "29.11 only, then close"); needs the 100-turn calibration (Feature 29 CP2) first | 29.13 |
| 30.15 | `insight_golden.json` (20 non-invoice attachments: 4 PO, 3 quotation, 3 contract, 3 credit note, 2 debit note, 2 statement, 2 remittance, 1 delivery note; IN/EU/US mix) + `run_insight_eval.py`; live checkpoint on gpt-5-mini narration | new |

## 6. Verification plan

| id | proof |
|---|---|
| 30.1 | `tests/test_attachment_insights.py` on real Postgres, `LLM_PROVIDER=mock`: INVOICE and OTHER attachments → no turn, rows byte-identical; PO with billed invoices → one assistant turn, `agreed_vs_billed.status == ok` with exact figures; credit note → `net_position` figures equal `compute_amount_owed`; a card that raises → `blocked`, turn still posts; flag off → nothing |
| 30.2 | `alembic upgrade head` once on `localhost:5433/invoice_db`; `GET …/insights` returns the block; pin creates a `pinned_insight` row; TTL job run on a fixture removes the attachment block and leaves the pinned copy; old `MessageResponse` serialises unchanged (contract test) |
| 30.3–30.4 | Views created; row counts equal base-table aggregates on the seeded tenant; `query_metric()` without `tenant_id` raises; AST guard rejects metric SQL missing the parameter |
| 30.5 | Fixture statement with 6 lines: 4 match, 1 ours-only, 1 theirs-only, exact figures |
| 30.6 | Fixture party with two overdue invoices and a PO: card names both and the month outflow |
| 30.7 | `lookup_glossary("total")` → `grand_total`; another tenant's collection not readable |
| 30.8 | Uncertified row never retrieved; three questions returned, all tagged for the doc type |
| 30.9–30.10 | Every card file has all fields and a reachable `source_url`; founder spot-checks each card against its source |
| 30.11 | Fixtures per check (credit note without original invoice reference; EU PO without VAT id; RCM contract without flag) → `verify` fails with the citing rule id; compliant fixtures pass |
| 30.12 | Lists every skipped card's reason and every low-confidence field |
| 30.13 | Thumbs-down writes `chat_correction`; `promote_to_example()` creates a certified row; workbook KQL dry-runs |
| 30.14 | Mocked rerank reorders; flag off path byte-identical |
| 30.15 | 20-attachment eval: card figures graded deterministically (exact match), narration by the Feature 29 checklist judge; target ≥ 90% figures exact, 0 fabricated figures |

Hard rule 3: any number the user sees is computed in `attachment_insights.py`, `document_comparison.py` or the views; the model narrates a JSON block it is told not to recompute.

## 7. Open decisions (as of 2026-09-07 morning — see §8 for the rulings)

1. Post automatically on every qualifying attachment (spec assumes), or only after the user clicks "Analyse"?
2. Pin is the only durable path (spec assumes) — or auto-pin for contracts, since they outlive sessions?
3. Doc types: the nine listed, or also bank advice / payment receipt?
4. Does the narration call count against the tenant's chat quota? (Spec assumes no; one gpt-5-mini call per attachment.)
5. Statement tolerance: exact amount, or ±0.5% / ±1 currency unit?
6. Rule-card review cadence (`review_at`): quarterly?

---

## 8. Amendment — Chat-Attachment Intelligence Spec, founder 2026-09-07 (evening)

Appended, not a rewrite (hard rule 4). Where this section and §1–§7 disagree, this section
wins. It absorbs the founder's "Chat-Attachment Intelligence Spec (2026-09-07)" and the ten
rulings taken in chat the same evening.

### 8.1 Rulings

| # | question | ruling |
|---|---|---|
| R1 | Durability | **Insight lifecycle for every finding** (open → acted / snoozed / dismissed, with outcome). Supersedes §1 "temporary unless pinned" and §7 Q2. `pinned_insight` and the pin endpoint are **dropped**; 30.2 is rewritten below. |
| R2 | Doc types | **PO, quotation, challan / GRN (delivery note), credit note, debit note, bank statement, contract / rate agreement, remittance advice.** Order confirmation folds into PO; "statement of account" becomes bank statement backed by a ledger table. Supersedes §7 Q3. |
| R3 | Delivery | **Two-stage.** Sync bubble (deterministic, target < 3 s) posted at extraction; async second update from a queue job pushed over the existing chat SSE channel. Supersedes §3 steps 4–6 as one pass. |
| R4 | Actions | **All five** on the bubble: mark hold / dispute / paid on the linked invoice, add note, Discuss (seeds the chat with the finding), dismiss. Hold / dispute / paid write `Invoice.status`. |
| R5 | Bank match tolerance | **± 1 currency unit, ± 5 days, vendor must match; per-tenant override.** Settles §7 Q5. |
| R6 | Vendor normalisation | **Per-tenant vendor master** (aliases confirmed once per tenant); no cross-tenant sharing. |
| R7 | Chat pin | **No pin.** The bubble scrolls like any message; open findings live in the lifecycle and on the dashboard. |
| R8 | Prerequisites | **Inside this feature as phase 0** (30.0a–30.0g), ahead of the cards. |
| R9 | Gating thresholds | **Constants in code with per-tenant override**: over-invoicing history ≥ 3 linked pairs, quote drift ≥ 2 invoices after the quote, repeat short delivery ≥ 3 challans. |
| R10 | Write-up | Amend in place (this section); FE Feature 21 amended to match. |

Still open from §7: Q1 (auto-post vs "Analyse" click — spec keeps auto-post), Q4 (quota — spec keeps "not counted"), Q6 (review cadence — spec keeps quarterly).

### 8.2 Persona and wording

SMB owner. Rendered text in the tenant's currency (₹ for Indian tenants) and plain verbs: "overbilled", "short delivered", "paid twice?". Internal names (3-way match, delta, tier) stay in code and never reach the bubble.

### 8.3 Bubble anatomy (replaces the §1 card table as the rendered shape; cards stay as the compute units)

1. **Verdict line** — one sentence, written by the model from the facts JSON: "Hold Shree Packaging invoice — overbilled ₹23,200 vs this PO."
2. **Findings** — max 3 shown, rest collapsed. Each: currency impact, confidence (high / med / low + the reason), evidence links to the document fields and invoice rows compared. Findings are ranked by the model inside the bubble; the figures are not.
3. **Checks not run + why** — no PO on file, HSN missing, statement has no narration, flag off.
4. **Actions** — hold / dispute / paid, add note, Discuss, dismiss (R4).
5. **Feedback** — thumbs-down or correction → flywheel (30.13): certified example or rule-card review flag.

### 8.4 Prerequisites — phase 0 (R8)

| id | prerequisite | what exists today | what is built |
|---|---|---|---|
| 30.0a | Persistent attachment store | `ChatAttachment` (Feature 26) with `extracted_json`, `doc_type`, tenant scope; removed by the TTL job | `ChatAttachment.retained: bool` — an attachment that produced findings is exempt from the TTL job while any finding is open |
| 30.0b | Doc linking with first-link confirmation | `candidate_invoice_ids` / `confirmed_invoice_ids` / `match_tier` (Feature 26) | `services/doc_linking.py::link_attachment(row, tenant_id, db) -> LinkResult` — vendor (via the vendor master) + PO / reference number + amount / date fuzzy match; **first link per vendor requires user confirmation** (`POST /attachments/{id}/links/confirm`), later links auto-confirm; `vendor_link_policy(tenant_id, vendor_id)` |
| 30.0c | Bank ledger table | none | `bank_statement_line(id, tenant_id, attachment_id, statement_date, line_date, narration, debit, credit, balance, utr_ref, matched_invoice_id, match_status, match_confidence)`; `statement_date` on the attachment row for "as of" staleness |
| 30.0d | Region detection per document | `regional_ids` on the invoice profile (Feature 27) | `services/region.py::detect_region(extracted_json) -> "IN" / "EU" / "US" / None` — GSTIN → IN, VAT-ID → EU, else US / none; stored as `ChatAttachment.region` |
| 30.0e | Insight lifecycle + notification hook | none | `insight(id, tenant_id, attachment_id, doc_type, card, finding_key, impact_amount, currency, confidence, confidence_reason, evidence json, status OPEN / ACTED / SNOOZED / DISMISSED, outcome, acted_by, acted_at, snoozed_until, created_at)`; `services/insights.py::open_insight()`, `transition_insight()`; a notification hook that posts the async bubble update over SSE and, when the session is closed, leaves the finding for the dashboard |
| 30.0f | Vendor master (R6) | `vendor_name` free text on `invoice` | `vendor(id, tenant_id, canonical_name)` + `vendor_alias(vendor_id, alias, confirmed_by, confirmed_at)`; `services/vendor_master.py::resolve_vendor(name, tenant_id)`; the entity resolver (Feature 29 29.11) reads it |
| 30.0g | Threshold constants (R9) | none | `services/insight_thresholds.py::THRESHOLDS` (`over_invoicing_pairs = 3`, `quote_drift_invoices = 2`, `repeat_short_delivery_challans = 3`, `bank_amount_tolerance = 1`, `bank_date_tolerance_days = 5`) + `tenant_setting` override read through `threshold(name, tenant_id)` |

All migrations add-only, one `alembic upgrade head` (no backfill — dev rule).

### 8.5 Per-document-type intelligence (R2)

| doc type | sync — deterministic, < 3 s, shown first | async — seconds later or dashboard | gating (R9) | source |
|---|---|---|---|---|
| **PO** | link to invoices already received from the vendor; any invoice > PO (qty / rate / total); duplicate PO number | open PO value not yet invoiced; expected cash-out timing from PO terms; vendor's over-invoicing history | history needs ≥ 3 linked pairs | Feature 29 compare, `v_3way_match` |
| **Quotation** | link to PO / invoice from the same vendor; quoted rate vs PO rate vs invoice rate per line | "vendor has drifted +7 % from quote across N invoices" | drift needs ≥ 2 invoices after the quote | `v_vendor_spend` |
| **Challan / GRN** | qty delivered vs PO vs invoice per line; short / excess delivery in currency; invoice received before delivery | partial-delivery balance still due; repeat short delivery by vendor | repeat needs ≥ 3 challans | `v_3way_match` |
| **Credit / debit note** | which invoice it adjusts; net payable now; duplicate note; GST / ITC reversal amount (India cards) | updated cash calendar for that vendor | — | rule cards, `v_overdue` |
| **Bank statement** | auto-match debits / credits to invoices (amount ± 1, vendor, date ± 5 d); N marked paid / received; M unmatched debits (possible unrecorded or duplicate payment); closing balance + statement date | cash cover: due in 7 / 30 / 60 days vs balance, labelled "as of <statement date>"; AR receipts → customer overdue refresh | match confidence low until the user confirms the first match per vendor | 30.0c ledger, `v_overdue` |
| **Contract / rate agreement** | payment days, discount, tax rate vs what invoices from that vendor actually show | contract-term deviations over time | ≥ 2 invoices | `v_vendor_spend`, glossary |
| **Remittance advice** | which invoices it settles; unapplied balance; amount vs invoice total | customer overdue refresh | — | Feature 29 ledger |
| **Any** | compliance checks from regional rule cards for the doc type, each citing its primary source; low-confidence fields; checks not run | glossary-aware plain summary (last, never blocks); 3 certified click-questions | — | 30.7–30.11 |

### 8.6 Runtime (R3)

1. **Trigger.** `extract_attachment()` completes → `is_insight_doc_type(doc_type)` → `enqueue_insight_job(tenant_id, attachment_id, doc_type)` (new task type `"insight"` in `services/chat_queue.py`, handled in `queue_worker/main_worker.py`).
2. **Sync stage** (inline, before the enqueue returns): rules + views only, no model. `build_insight_block(stage="sync")` emits the facts JSON; findings are written to `insight` rows (30.0e); the bubble is posted as an assistant `ChatMessage` with `attachment_payload["insights"]`. The verdict line at this stage is **template text** from the top finding.
3. **Narration** (in the job): one fast-tier call, minimal reasoning effort (`resolve_model("chat_summary")`), verdict + finding text from the facts JSON. **Answer-contract gate:** every currency figure in the output must exist in the facts JSON, else the template text stands (Feature 29 `_answer_contract_gate()` reused).
4. **Async stage** (same job): heavier views + narration; `insight` rows appended; the bubble is **updated in place** (`ChatMessage.attachment_payload["insights"]` replaced, `insights_version += 1`) and an `insight_update` event is pushed over the chat SSE channel so an open session redraws the bubble. A closed session sees the findings on the dashboard.
5. **Actions.** `POST /insights/{id}/transition` with `{status, outcome?, note?}`; hold / dispute / paid also call the existing invoice status update; Discuss returns the finding as a seeded user-turn prefix; dismiss closes the row.
6. **Dashboard.** The nightly job ranks open insights per tenant by `impact_amount` × confidence; the control-tower workbook gets an "Open insights" panel (Azure Workbook, never an in-app page).

### 8.7 File coordinates — additions and changes to §2

| path | named function / component | new or edit | what it does |
|---|---|---|---|
| `models.py` | `Insight`, `BankStatementLine`, `Vendor`, `VendorAlias`; `ChatAttachment.retained`, `.region`, `.statement_date`, `.insights_version` | new / edit | 30.0a–30.0f |
| `alembic/versions/<rev>_add_insight_lifecycle.py`, `<rev>_add_bank_statement_line.py`, `<rev>_add_vendor_master.py` | `upgrade()` | new | add-only |
| `services/insights.py` | `open_insight()`, `transition_insight()`, `rank_open_insights(tenant_id)`, `notify_insight_update(session_id, attachment_id)` | new | 30.0e |
| `services/doc_linking.py` | `link_attachment()`, `LinkResult`, `vendor_link_policy()` | new | 30.0b |
| `services/vendor_master.py` | `resolve_vendor()`, `confirm_alias()` | new | 30.0f |
| `services/region.py` | `detect_region()` | new | 30.0d |
| `services/bank_matching.py` | `match_statement_lines(lines, invoices, tolerance)` → matched / unmatched-debit / unmatched-credit | new | bank-statement sync card; replaces `reconcile_statement()` for bank statements |
| `services/insight_thresholds.py` | `THRESHOLDS`, `threshold(name, tenant_id)` | new | 30.0g |
| `services/attachment_insights.py` | `build_insight_block(row, db, tenant_id, stage)`, `verdict_template(top_finding)`, `rank_findings(block, llm)` | edit | two stages; template verdict; model ranks, never computes |
| `services/chat_queue.py` / `queue_worker/main_worker.py` | `enqueue_insight_job()`, `handle_insight_job()` | new | R3 |
| `routers/chat.py` | SSE event `insight_update`; `POST /insights/{id}/transition`; `GET /insights?status=OPEN` | edit | R3, R4 |
| `routers/chat_attachments.py` | `POST /attachments/{id}/links/confirm` | edit | 30.0b |
| ~~`models.PinnedInsight`, `POST …/insights/pin`~~ | — | **dropped** | R1 / R7 |
| `infra/monitoring/ai_control_tower_workbook.json` | panel "Open insights" | edit | 8.6 step 6 |

### 8.8 Tasks — phase 0 added, 30.2 and 30.5 rewritten, the rest as in §5

| id | task |
|---|---|
| 30.0a | `ChatAttachment.retained`; TTL job skips retained rows while any `insight` is OPEN |
| 30.0b | `doc_linking.py` + first-link confirmation endpoint + `vendor_link_policy()` |
| 30.0c | `bank_statement_line` table + extractor output for bank statements (date, narration, debit, credit, balance, UTR) + `statement_date` |
| 30.0d | `detect_region()` + `ChatAttachment.region`; rule cards select by region |
| 30.0e | `insight` table, `open_insight()` / `transition_insight()`, transition endpoint, SSE `insight_update`, nightly `rank_open_insights()` |
| 30.0f | Vendor master + aliases + `resolve_vendor()`; entity resolver reads it |
| 30.0g | `insight_thresholds.py` + tenant override |
| 30.2 (rewritten) | Two-stage runtime: `enqueue_insight_job()` / `handle_insight_job()`; sync block + template verdict posted inline; async update in place + SSE push; `MessageResponse.insights` additive. **No pin.** |
| 30.5 (rewritten) | `bank_matching.py` over the ledger (R5 tolerances) + bank-statement sync card + cash-cover async card |
| 30.17 | Bubble actions: hold / dispute / paid → invoice status; note; Discuss seed; dismiss |
| 30.18 | Async per-type cards: open PO value, cash-out timing, over-invoicing history, quote drift, partial-delivery balance, repeat short delivery, contract deviations — each behind its R9 threshold |

### 8.9 Verification — additions

| id | proof |
|---|---|
| 30.0a | TTL job fixture: attachment with an OPEN insight survives; after DISMISSED it is removed on the next run |
| 30.0b | First PO from a new vendor → `LinkResult.requires_confirmation`; after confirm, the second links automatically; wrong-vendor never links |
| 30.0c | Fixture statement PDF → N ledger rows with exact debit / credit / balance; `statement_date` set |
| 30.0d | GSTIN fixture → IN; VAT-ID fixture → EU; neither → None |
| 30.0e | Transition matrix test (OPEN→ACTED/SNOOZED/DISMISSED, SNOOZED→OPEN at `snoozed_until`); another tenant's insight not transitionable; SSE event recorded in the progress test harness |
| 30.0f | "Shree Packaging Pvt Ltd" and "SHREE PACKAGING" resolve to one vendor after one confirmation; an unconfirmed alias never auto-binds |
| 30.0g | Override for one tenant changes only that tenant's threshold |
| 30.2 | Sync bubble posted before the job runs (mock queue); job updates the same message, `insights_version` 1→2; answer-contract gate rejects a narration with a figure not in the facts JSON and the template text stands |
| 30.5 | 6-line statement fixture: 4 matched within ±1 / ±5 d, 1 unmatched debit flagged "possible duplicate payment" when the invoice is already PAID, 1 unmatched credit; closing balance and "as of" date rendered |
| 30.17 | Hold from the bubble sets `Invoice.status`; dismiss closes the row; Discuss returns the seed text; every write is tenant-scoped |
| 30.18 | Each threshold card returns `skipped` with reason below its threshold and `ok` with exact figures at or above it |

Hard rule 3 unchanged: every figure is computed in code or a view; the model writes the verdict sentence, the finding prose and the ranking, and is gated on the figures it repeats.
