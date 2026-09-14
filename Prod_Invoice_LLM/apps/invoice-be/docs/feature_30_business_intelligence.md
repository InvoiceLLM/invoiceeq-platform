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
| 30.14 | Reranker behind `ENABLE_RERANK`, only if Feature 29 recall instrumentation shows ranking is the limit — **closed as not needed, founder 2026-09-08; nothing built** | 29.18 |
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
| R4 | Actions | ~~All five … hold / dispute / paid write `Invoice.status`~~ **Corrected 2026-09-08 (Gap 492), founder: "intelligence is just information, no act to be taken by system, user need to take action offline."** The bubble offers **add note, Discuss, dismiss** (and snooze). No action ever reads or writes an invoice; the note is the user's own record of what they did offline. |
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
4. **Actions** — add note, Discuss, dismiss (R4 as corrected by Gap 492: information only, nothing touches an invoice).
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
5. **Actions.** `POST /insights/{id}/transition` with `{status, outcome?, note?, snoozed_until?}` — note / snooze / dismiss only; Discuss returns the finding as a seeded user-turn prefix. Nothing reads or writes `Invoice` (Gap 492).
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
| 30.17 | Bubble actions: note; Discuss seed; dismiss (~~hold / dispute / paid → invoice status~~ removed, Gap 492) |
| 30.18 | Async per-type cards: open PO value, cash-out timing, over-invoicing history, quote drift, partial-delivery balance, repeat short delivery, contract deviations — each behind its R9 threshold |
| 30.19 | **Three-state check result** (`PASS` / `FAIL` / `NOT_CHECKED(reason, subjects)`) — a check that could not be evaluated is never rendered as clean; card titles read "N checked, M not checked". Design review §11.2 |
| 30.20 | **Cards emit claims, not prose** — `{kind, entity, figures, subjects, severity}` through one renderer; `money(value, currency)` is the only number-to-text path. Design review §11.3 |

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

---

## 9. Build note — 2026-09-08 (phase 0 + the sync/async bubble)

What was actually built, against real Postgres (`localhost:5433/invoice_db`), all
behind `ENABLE_ATTACHMENT_INSIGHTS = False`. Written after the fact; where it
deviates from §8 the deviation is stated, not smoothed over.

### 9.1 Schema — one migration for the whole of phase 0

`alembic/versions/a1b2c3f30001_feature_30_phase_0.py` (`down_revision`
`e7f8a9b0c1d2`, applied once with `alembic upgrade head`). One file rather than
the four §8.7 implies: the dev rule is add-only with a single upgrade, and four
files that must all be applied to leave a working schema is four chances to
apply three.

* `chat_attachments`: `retained` (bool, default false), `region`,
  `statement_date`, `insights_version` (int, default 0), `insights` (JSONB).
* `insight` — the lifecycle table, with **`UNIQUE (attachment_id, finding_key)`**.
  That constraint is what makes the async stage idempotent: it updates the
  finding the user may already have acted on instead of opening a second copy.
* `bank_statement_line` — the 30.0c ledger. Table only; the extractor output that
  fills it is **not built** (see 9.6).
* `vendor` + `vendor_alias` (`UNIQUE (tenant_id, alias)`).
* `tenant_insight_setting` (`UNIQUE (tenant_id, name)`) — the R9 override store.
  §8.4 says "tenant_setting"; no such table exists in this codebase, so one was
  added rather than overloading `TenantChatSettings`, which is chat *persona*
  configuration.

### 9.2 `services/insight_thresholds.py` (30.0g)

`THRESHOLDS` holds R9's three counts and R5's two bank tolerances.
`threshold(name, tenant_id, db_session)` returns the override if a row exists and
the shipped constant otherwise — with no session it does not query at all, and any
query failure falls back to the constant and logs. An unknown NAME raises
`UnknownThresholdError`: a typo'd threshold silently returning 0 would open every
gated card at once. `set_threshold()` upserts; `all_thresholds()` is what the
"checks not run" card renders, so the user sees the number their gate used.

### 9.3 `services/insights.py` (30.0e) and the lifecycle surface

`open_insight()` (upsert on `finding_key`; **never** changes a status, so a
dismissed finding stays dismissed through every later update),
`transition_insight()` (tenant-scoped in the WHERE clause; validates against
`ALLOWED_TRANSITIONS` and `ALLOWED_OUTCOMES`; DISMISSED is terminal),
`is_effectively_open()` (SNOOZED wakes at `snoozed_until` **at read time**, so no
job has to run for the state to be true), `list_insights()`,
`rank_open_insights()` (impact × confidence weight; an unquantified finding still
ranks, below every quantified one), `_sync_retained()` and
`unresolved_insights_for_attachment()`, and `notify_insight_update()`, which
publishes `step: "insight_update"` on the job's existing Redis channel rather
than opening a second SSE stream.

HTTP (`routers/chat.py`): `GET /chat/insights`, `POST
/chat/insights/{id}/transition`, `GET /chat/insights/{id}/discuss`. Not
flag-gated at the route level, deliberately: a finding opened while the flag was
on must stay actionable after it is turned off.

### 9.4 30.0a, 30.0d, 30.0f

* **30.0a** — `scripts/sweep_chat_attachments.py::expired_attachments()` now also
  filters `retained IS NOT TRUE`. Retention follows OPEN **or SNOOZED** findings,
  which is wider than §8.4's literal "while any insight is OPEN": a snooze defers
  a finding, and sweeping the document underneath a sleeping finding would leave
  a claim about money with no evidence behind it.
* **30.0d** — `services/region.py::detect_region()`: GSTIN → IN, EU/EEA VAT
  prefix allow-list (including `EL` and `XI`) → EU, EIN or state+ZIP → US, else
  **None**. None never falls back to US; a rule card that fires by default fires
  on the wrong documents. `set_attachment_region()` persists it.
* **30.0f** — `services/vendor_master.py`: `normalise_vendor_name()` (casefold,
  depunctuate, strip legal form), `resolve_vendor()` →
  `canonical | alias | proposed | none`, `get_or_create_vendor()`,
  `propose_alias()`, `confirm_alias()`, `vendor_invoice_names()`. **A fuzzy match
  never binds** — it proposes, and `POST /chat/vendors/aliases/confirm` is where
  the tenant answers. `agents/entity_resolver.py::_vendor_master_candidates()`
  consults it first, and `ResolutionResult.vendor_names` was widened from
  `candidates[0]` to every bound spelling (identical output for the keyword path,
  where a bound vendor had exactly one candidate by construction).

### 9.5 `services/attachment_insights.py` (30.1, 30.2, 30.12, 30.17)

`INSIGHT_DOC_TYPES` is the eight R2 types in the Feature 27 classifier's own
vocabulary, with R2's two folds (ORDER_CONFIRMATION → PO, GRN → challan).
**Deviation:** R2 says "bank statement"; the classifier emits
`STATEMENT_OF_ACCOUNT` and the taxonomy is frozen in `active-work.md`, so §5's
"REFERENCE discriminator extended to the nine types" was **not** done and the
existing value is used instead. Nothing downstream keys on the spelling.

Cards, all pure Python/SQL: `card_what_this_is`, `card_agreed_vs_billed`
(`document_comparison.compare_reference_to_invoices()` verbatim, so the bubble
and the chat answer cannot disagree), `card_terms_check` (payment window from the
printed terms vs `due_date - invoice_date`), `card_net_position`
(`compute_amount_owed()`, Gap 475's signed arithmetic), `card_delivery_vs_order`
(quantity only, never price), `card_confidence_gaps` (30.12 — built from what the
other cards reported, so a new skip reason needs no edit here).
`CARDS_BY_DOC_TYPE` is the per-type render order; `BUBBLE_ACTIONS` is note / Discuss / dismiss (Gap 492 removed hold / dispute / paid).

`build_insight_block(row, db, tenant_id, stage)` runs them, never raises, refuses
a tenant mismatch, and returns `{stage, doc_type, cards[], findings[], figures{},
checks_not_run[], actions[], verdict}`. A card that raises is `blocked` and the
rest still run. `verdict_template()` repeats the top finding's own words and
figure. `narrate_insight_block()` makes **one** `chat_summary` call and passes the
result through Feature 29's `_answer_contract_gate()`; a figure that is not in the
facts JSON means the template text stands, with **no retry** — the sync bubble is
already on screen and true, so a second call is only a second chance to invent a
number. `_linked_invoices()` honours Feature 26 D4: confirmed ids alone when any
exist, candidates only otherwise, and every card that used a candidate says so in
its confidence reason.

### 9.6 Runtime (30.2) and what is not built

`services/attachment_extraction.py::insight_attachment()` runs after
`match_attachment()` (before it, every card would report "no invoice on file"),
posts the sync bubble, then calls `ChatQueueService.enqueue_insight_job()`.
`queue_worker/handlers.py::handle_insight_job()` rebuilds at `stage="async"`,
narrates, **replaces the payload on the same message**, bumps `insights_version`
and pushes `insight_update`. `MessageResponse.insights` and
`ATTACHMENT_CONTRACT_KEYS` carry it to the browser and back through a reload.

**Not built in this pass, and why:** 30.0b (`doc_linking.py` + first-link
confirmation — the sync cards use Feature 26's existing `candidate_invoice_ids`,
which is what 30.0b was going to refine), 30.0c's extractor output and
`bank_matching.py` (30.5), and 30.3, 30.4, 30.6–30.11, 30.13–30.15, 30.18. The
statement card list is therefore header + "checks not run" only, which is an
honest "not checked" rather than a reconciliation that did not happen.

### 9.7 Verification

Real Postgres, no live model (narration driven by a stub `invoke()`):

| file | result |
|---|---|
| `tests/test_insight_thresholds.py` | 6 passed |
| `tests/test_insight_lifecycle.py` | 22 passed |
| `tests/test_vendor_master.py` | 18 passed |
| `tests/test_insight_retention.py` | 4 passed |
| `tests/test_region_detection.py` | 13 passed |
| `tests/test_attachment_insights.py` | 26 passed |

**Gap 491 withdrawn, Gap 492 applied (2026-09-08).** The founder ruled the bubble is
information only, so the hold / dispute / paid outcomes, the `invoice_id` on the transition
payload and the status mapping were removed; `ALLOWED_OUTCOMES` is `note | dismissed | snoozed`
and the endpoint never touches `Invoice`. `tests/test_insight_lifecycle.py` now asserts the
three outcomes are refused with 400 and the invoice row is unchanged.

---

## 10. Build note — 2026-09-08, pass 2 (everything else)

Pass 1 (§9) landed phase 0 and the sync/async bubble. Pass 2 finished the
feature. Everything below is behind `ENABLE_ATTACHMENT_INSIGHTS = False` and its
own Feature 29 capability flag where one applies.

**Ruling correction carried through everything here: Gap 492 — the bubble is
information only.** `hold` / `dispute` / `paid` were removed from
`BUBBLE_ACTIONS`, `ALLOWED_OUTCOMES` is `note | dismissed | snoozed`, the
transition endpoint no longer takes an `invoice_id`, and Gap 491 is withdrawn.
No code written in pass 2 writes to `invoice`; three test files assert it
directly (`test_doc_linking`, `test_bank_matching`, `test_chat_corrections`).

### 10.1 30.0b — doc linking with first-link confirmation

`services/doc_linking.py`. `find_candidate_invoices()` is CALLED, not
reimplemented; what this adds is (a) the vendor master decides who the supplier
is, so a candidate belonging to a different confirmed vendor is rejected
(`LinkResult.rejected`), and (b) the first link per vendor needs a human
(`vendor_link_policy()` → `requires_confirmation`), after which links
auto-confirm. A tier-1 exact document-number match skips the question entirely:
that is an identifier both documents were meant to share, not an inference.
`confirm_link()` also writes the confirmed vendor alias, which is what stops the
same question being asked on every later document. Endpoints:
`GET /chat/attachments/{id}/links`, `POST …/links/confirm` — Feature 26's
`confirm-matches` is untouched.

### 10.2 30.0c — the bank ledger, and the schema defect it exposed (Gap 493)

Landing statement rows needed fields the REFERENCE schema did not have, and
looking for them found that `card_terms_check` had been reading a
`payment_terms` field that could never arrive on the real path — correct
arithmetic that was structurally dead. **BE Gap 493**: six additive optional
fields on `ReferenceDocExtractionSchema` (`payment_terms`, `delivery_terms`,
`notes`, `referenced_documents`, `statement_lines`, `statement_date`), a new
`BankStatementLineItem` model, and `REFERENCE_DOC_FAMILY_DIRECTIVE` telling the
model which apply to which document type. A2's invoice-only spine is still
absent from REFERENCE and the pin test now asserts that rule rather than a field
count.

`services/bank_ledger.py` lands the rows: `parse_statement_lines()` (with a
fallback to `referenced_documents` for statements extracted before the field
existed, marked by `source`), `detect_statement_date()` (printed date → doc date
→ latest row; **never today**), `land_statement_lines()` (replace, carrying
user-confirmed matches forward on `(date, amount, reference)`),
`closing_balance()` (read, never summed).

### 10.3 30.3 / 30.4 — semantic views and the metric layer

Migration `a1b2c3f30002` creates `v_vendor_spend`, `v_overdue`,
`v_tax_summary`, `v_3way_match`. Every view exposes `tenant_id` as a COLUMN,
excludes `deleted_at IS NOT NULL` and `status = 'DUPLICATE'`, and derives OVERDUE
from `due_date`/`paid_at` because no invoice ever stores that status.

`services/semantic_views.py` is the only way to query them: `METRICS`,
`query_metric()` (raises `MetricError` without a tenant, on an unknown metric or
on an undeclared filter — never an empty list, which is a legitimate answer),
`_validate_registry()` at import (a metric whose SQL lacks `:tenant_id` fails
process start), `metric_definitions()`, `preferred_metric_for()` (a keyword map,
not a model call). Every filter value is a bind parameter; nothing concatenates.

### 10.4 30.5 / 30.6 / 30.18 — the remaining cards

`services/bank_matching.py`: R5's three rules are conjunctive (amount within
`bank_amount_tolerance`, date within `bank_date_tolerance_days` **of the due
date**, vendor name present in the narration) and all three read through
`threshold()`, so the per-tenant override works end to end. Four verdicts, and
the fourth is the valuable one: `POSSIBLE_DUPLICATE` fires when the single match
is an invoice already marked paid, or when two statement rows match the same
bill — "have we paid this twice?" is the question a statement is best at
answering. `apply_matches()` writes `bank_statement_line` and nothing else.
`cash_cover()` buckets 7/30/60 days from the STATEMENT date.

Ten new cards, all in `CARDS_BY_DOC_TYPE` (one list per document type, not a
second registry), each async card skipping ITSELF at the sync stage with a
stated reason so the sync bubble stays fast: `card_bank_reconcile`,
`card_cash_cover`, `card_cash_impact`, `card_open_po_value`,
`card_cash_out_timing`, `card_over_invoicing_history` (≥ 3 pairs),
`card_quote_drift` (≥ 2 invoices), `card_partial_delivery_balance`,
`card_repeat_short_delivery` (≥ 3 challans), `card_contract_deviations` (≥ 2
invoices), plus `card_compliance` and `card_suggested_questions`. Every gated
card reports the threshold it used, so "not enough history yet" comes with the
number that "enough" means for that tenant.

### 10.5 30.7 / 30.8 — knowledge and certified examples

`services/knowledge.py`: `knowledge_{tenant}` (structural isolation, Gap 55's
pattern) holding two kinds behind one `kind` filter — glossary and rule.
`lookup_glossary()` is an EXACT match, not a vector search: a glossary is a
lookup table, and a nearest-neighbour answer would put a word in the tenant's
mouth. `index_knowledge()` REFUSES a rule with no `source_url`. The narration
now receives the tenant's glossary with a note that it is vocabulary, not
figures.

`services/certified_examples.py` + migration `a1b2c3f30003`: only `certified`
rows are ever retrieved; a tenant example outranks a global one on a tie;
similarity is stopword-free Jaccard over content words (the first version used
`SequenceMatcher` over raw strings and matched "who signed the contract?" to
"how much did we spend on packaging last year?" on shared function words — its
own test caught it). `card_suggested_questions` offers three questions per
document type and opens no `insight` row, because a question is not a finding.

### 10.6 30.9 / 30.10 / 30.11 — rule cards

`services/rule_cards.py` is the framework: front-matter parsing, `CHECKS` (eight
deterministic checks), `verify_checks_for()` (a card naming a missing check
reports `not_applicable`, **never** a pass; a raising check is contained),
`run_compliance_checks()`. No check asks a model whether a document complies.

**Cards actually written, and their provenance (hard rule 8).**

| region | cards | source, fetched 2026-09-08 |
|---|---|---|
| EU | 3 — credit/debit-note reference, supplier VAT id, "reverse charge" wording | European Commission, VAT invoicing rules |
| US | 2 — supporting documents (`verify: null`, guidance, because there IS no federal content rule for a PO), document number | IRS Publication 583 |
| **IN** | **3 skeletons, `status: unverified`, NO rule text** | every CBIC/GSTN source was attempted and none was reachable — see below |

India is a real gap, not an omission. `cbic-gst.gov.in` serves its act/rules
through JavaScript (seven direct paths → 404 while its homepage and unrelated
PDFs load), `taxinformation.cbic.gov.in` fails TLS verification, `gst.gov.in`
returns a WAF rejection, and no CGST Act PDF could be found on `indiacode.nic.in`
or `gstcouncil.gov.in`. The three skeletons name the source they must be checked
against and the `verify` check they will use, carry no rule text, and are
filtered out of every display path by `load_rule_cards()`. The attempt log is in
`knowledge/rule_cards/README.md`; a per-file test asserts that a `verified` card
HAS text and an `unverified` card has NONE. **Founder call: fetch the CBIC pages
by hand, or accept a secondary source.**

### 10.7 30.13 — the flywheel

`services/chat_corrections.py` + `chat_correction` (migration `a1b2c3f30003`).
A correction is per CARD and per FINDING, not per turn, and is PENDING until a
human promotes it — learning from every thumbs-down would let one confused user
reshape every later answer invisibly. `promote_to_example()` produces a
**certified** example, so the loop closes on the same gate 30.8 starts from.
Endpoints: `POST /chat/messages/{id}/insight-feedback`,
`POST /chat/corrections/{id}/promote` (behind `require_can_train`),
`GET /chat/corrections/stats`.

Monitoring: `telemetry.track_insight_bubble()` / `track_insight_feedback()` emit
counts, a document type and the narration gate's outcome — never finding text or
a party name, because these land in a shared workspace — and two panels
("Open insights", "Chat quality trend") were added to
`ai_control_tower_workbook.json`. The KQL cannot be executed without a Log
Analytics workspace; what IS asserted is that every field each panel parses out
of `Properties` is a field the emitter actually writes.

### 10.8 30.15 — the eval harness (built, not run live)

`benchmarks/insight_golden.json`: 20 synthetic attachments in §5's exact mix
across IN/EU/US, with `expected_figures` (exact match), `expected_cards`,
`expected_skip_reasons`, `expected_findings` and `must_not_contain` — the two
Gap 475 regression numbers (144800.0 and 475.2) are pinned as forbidden, and
four cases are deliberately clean so a card that flags everything fails the bank.

`scripts/run_insight_eval.py` grades figures deterministically; narration is
graded only under an opt-in `--narrate` that warns first. **Deterministic run,
real Postgres, no LLM: 20/20 cases passed, 21/21 figures exact (100%, target
≥ 90%), 0 fabricated figures (target 0)**, and the database was left as found.

### 10.9 30.14 — not done, by its own precondition

The spec gates the reranker on "only if Feature 29 recall instrumentation shows
ranking is the limit". That instrumentation does not exist; `ENABLE_RERANK`'s own
docstring additionally gates it on a Cohere spend go/no-go and on CP2, which has
not been run. Building it now would add a paid dependency on a hunch. No code was
written.

### 10.10 Verification (pass 2)

Real Postgres (`localhost:5433/invoice_db`), no live model anywhere:

| file | result |
|---|---|
| `tests/test_doc_linking.py` | 11 passed |
| `tests/test_bank_ledger.py` | 15 passed |
| `tests/test_semantic_views.py` | 21 passed |
| `tests/test_bank_matching.py` | 14 passed |
| `tests/test_insight_async_cards.py` | 24 passed |
| `tests/test_knowledge_layer.py` | 11 passed |
| `tests/test_certified_examples.py` | 12 passed |
| `tests/test_rule_cards.py` | 51 passed |
| `tests/test_chat_corrections.py` | 16 passed |
| `tests/test_insight_eval.py` | 14 passed |
| **all 16 Feature 30 files together** | **278 passed** |
| `tests/test_generic_extraction.py` (Gap 493's neighbour) | 380 passed, 2 skipped |

Defects found and fixed during pass 2, each filed: **Gap 493** (REFERENCE schema
could not carry the fields the cards read) and **Gap 494** (a card reading a
semantic view put `UUID`/`date`/`Decimal` into the block and the bubble failed at
COMMIT; `jsonable()` now converts once, centrally).

### 10.11 Full-suite result and one neighbour test

`pytest tests/ -q --ignore=tests/us --ignore=tests/realworld_tenant` →
**6 failed, 3738 passed, 13 skipped** (168.7 s). The two ignored directories
cannot be collected together at all: they contain two files named
`run_chat_live_test.py` with no `__init__.py`, which aborts collection —
pre-existing and unrelated (recorded in **Gap 495**).

One of the six failures was Feature 30's own and is fixed:
`test_invoice_builder.py::test_the_notes_column_is_a_migrated_column_on_a_single_head`
pinned the Alembic head to `e7f8a9b0c1d2` **by name**, so it failed on any later
migration rather than on the thing its docstring says it protects — a SECOND
head, i.e. two agents branching off the same parent. It now asserts
`len(heads) == 1` plus `e7f8a9b0c1d2` in the head's ancestry, which catches the
branch and survives a legitimate migration. The other five are environment-
dependent and untouched by this change (**Gap 495**): a missing Google Drive
credential, two workflow tests whose fixture invoice 404s, and two autopilot
tests that processed 0 rows from the shared dev database.

### 10.12 Migrations applied (three, one `upgrade head` each)

`a1b2c3f30001` (phase 0) → `a1b2c3f30002` (semantic views) → `a1b2c3f30003`
(certified examples + corrections). Single head, add-only, no backfill, no
downgrade ceremony — the dev rule.


## 11. Design review — 2026-09-09 (two missing abstractions, from the vpi_demo dry run)

Founder-directed review after a static dry run of all ten `showcase/vpi_demo` README §5 attachment
scenarios. Thirteen defects were found across Gaps 509-519. **Not one of them is an arithmetic
error** — every layer that computes a number in this feature is correct. They cluster instead in the
layer that turns a computed number into a sentence or a status, and that layer was never given an
owner, so each card improvised its own.

### 11.1 The split, stated honestly

| bucket | count | items | how they get fixed |
|---|---|---|---|
| Plain wiring misses | ~5 | 510 (argument never passed), 511 (wrong word), 515.1 (bucket never rendered), 517.2 (figure keys), 519 | as gaps, individually |
| Missing abstractions | ~6 | 509, 512, 513, 515.2, 517.1, 480 | **tasks 30.19 and 30.20 below**, plus Feature 29's L3 |
| Never built | ~3 | 517.3, 518, 516.1 | scope decisions in §11.4 |

Fixing all thirteen as gaps would be the third repetition of a pattern this repo has already paid for
three times (Gap 471 fixing 1 of 18 identical tests and Gap 477 carrying the other 17; Gaps
474/497/500 as three passes at one bug; Gap 52's substring matcher standing untouched since July).
The two tasks below exist so the fix lands once instead of once per card.

### 11.2 Task 30.19 — three-state check result

**The defect class.** A check inside a card has no way to say "not evaluated". `InsightCard` has
`STATUS_OK / SKIPPED / BLOCKED` at the CARD level, but an individual comparison that cannot be made
simply `continue`s, and the card still returns `STATUS_OK`. So **"we compared nothing" and
"everything matches" are the same output**. This is Gap 517.1 (a delivery line whose description does
not pair is skipped silently), Gap 515.2 (an unmatched bank row reported as a problem rather than as
an unknown), Gap 510 (zero compliance rules run, reported as a plausible reason) and — on the eval
side, in Feature 29 — Gap 480 (a correct abstention scored 0.0).

**The change.** Every check returns `PASS | FAIL | NOT_CHECKED(reason, subjects)`. `NOT_CHECKED` is
never rendered as clean, is counted separately from `FAIL` in the card title, and names what it could
not evaluate ("2 delivered lines could not be paired with a billed line: 'M.S. Round Bar 25mm',
'Hex Bolt M10'"). A card's title becomes "N checked, M not checked" rather than "N checked".

**Why this is generic.** It is a type, not a rule. It fixes cards that do not exist yet, and it needs
no edit when a new vendor, language, item description or document type arrives.

**Explicitly rejected** (founder ruling, 2026-09-09, "we will not add specific handling of some clause
or cases"): an item-synonym table, a fuzzy-match threshold, or a list of ignorable bank narrations
("salary", "GST", "electricity"). Each solves today's case and creates the next miss. The test for any
proposed fix: *would this line need editing when a new vendor, language, item or bank arrives?* If
yes, it is the wrong fix.

### 11.3 Task 30.20 — cards emit claims, not prose

**The defect class.** Every card writes its own f-strings, so every formatting and wording bug is paid
for once per card: raw floats in sentences while the figure column formats correctly (Gap 509, in at
least four cards plus all three of `card_bank_reconcile`'s), a correct computation described with the
wrong words (Gap 511, "due in" for a payment term), and two cards asserting contradictory things in
one bubble because neither can see the other's conclusion (Gap 512).

**The change.** A card emits a structured claim — `{kind, entity, figures, subjects, severity}` —
and a single renderer turns claims into sentences. `money(value, currency)` lives there and is the
only path from a number to text. Contradiction becomes detectable, because claims about the same
entity are comparable objects rather than independent strings.

**Note on `money()`**: four helpers already exist (`invoice_builder.money`, `query_agent._money`,
`query_tools._money`, `document_comparison._money2`). Pick one and reuse it; do not add a fifth.

**Guard test (generic, not per-card):** no finding title contains a bare `\d+\.\d` where a currency
amount is meant.

### 11.4 Scope decisions for the founder — not defects

1. **No duplicate card for `DELIVERY_NOTE`** (Gap 517.3). The demo README expects the bubble to flag
   RAJ-2009 / NAT-2007 when a challan is attached; no card in that registry entry can. Add one, or
   correct the README's expectation.
2. **No payment-application card for `REMITTANCE_ADVICE`** (Gap 518). The bubble answers "what is the
   net owed" when the document asks "which invoice did this settle". Needs a new card that resolves
   the advice's own printed reference through the Gap 490 entity resolver.
3. **`STATEMENT_OF_ACCOUNT` carries two meanings** (Gap 516.1). Splitting it means touching the frozen
   taxonomy, which is blocked on Feature 27's ledger closing — so this is a decision to defer
   deliberately, not an oversight to fix now.

### 11.5 One spec violation, recorded

§8.8's verification row for task **30.5** requires a 6-line statement fixture to render "1 unmatched
credit". `card_bank_reconcile()` loops findings over `possible_duplicates`, `unmatched_debits` and
`ambiguous` only — the credit bucket is computed by the matcher, counted in `figures`, and never
turned into a sentence. **This is not missing scope; the spec asked for it and the code does not do
it** (Gap 515.1), which also means the 30.5 verification cannot have been run as written.

### 11.6 What is NOT wrong

Stated because the review could be read as a verdict on the whole feature, and it is not.

- **The architecture is sound.** Deterministic cards compute every figure; a template verdict that
  cannot be false; exactly one model call, restricted to wording; an answer-contract gate that
  discards the model's sentence when any figure is not already in the block; no retry. Nothing in
  §11 asks for that to change.
- **`services/bank_matching.match_statement_lines()` is careful work** — tolerances read through
  `threshold()`, vendor-must-match, direction enforced, `claimed` tracked across rows for the
  paid-twice case, `ambiguous` separated from unmatched, and pure computation with `apply_matches()`
  persisting separately. It returns five correct buckets. Gap 515 is entirely in the card that renders
  three of them.
- **The domain-specific work is already in the right place.** `card_terms_check` declares discount and
  tax-rate deviation as "checks not run" pending the 30.11 rule cards rather than guessing them from
  prose — which is exactly the instinct §11.2 generalises. Tax and discount rules belong in the rule-card
  registry as data, added without touching any card.

### 11.7 Sequence

1. Fix **Gap 477** first (18 tests still make live Azure calls; the failure baseline is stale). Until
   that is clean, no result below is provable — and three gaps closed on 2026-09-09 turned out to be
   work that had already been done without anyone knowing.
2. **30.19**, then **30.20**. Between them they retire 509, 511, 515.2, 517.1 and prevent the next six.
3. The plain wiring misses ride on top: 510, 515.1, 517.2, 519.
4. Then the founder's call on Feature 29's **L1** — the answer-contract gate validates that figures
   are real, never that the claim about them is true. Gap 512 and Gap 480 are both that hole. Feature
   29 §4.3 puts the verifier stage at "not yet" and notes "we are at router"; this review is the
   evidence for revisiting that.


## 12. Build note — 2026-09-13/14 (tasks 30.19, 30.20, L1; Tracks B–D of the completion plan)

Founder go 2026-09-13 ("go"), then 2026-09-14 ("develop, test, review and verify … 1 hr is hard stop").
Everything below is behind `ENABLE_ATTACHMENT_INSIGHTS` as before. Nothing writes `Invoice` (Gap 492 stands).

### 12.1 What §11 asked for, as built

| §11 item | Built as | Where |
|---|---|---|
| 30.19 three-state check | `CheckLog(card)` with `check_passed / check_failed(finding) / check_not_checked(subject, reason)`; `title(noun)` → "N checked, M not checked"; `as_card()` puts `evidence["not_checked"]` (grouped by reason, naming subjects) on the card and `build_insight_block()` copies it into `checks_not_run` | `services/attachment_insights.py` |
| 30.20 claims not prose | `Claim(kind, entity, figures, subjects, severity, currency, asserts)`; `@claim_template(kind)` registry; `render_claim()`; `claim_finding()` keeps the claim on the finding. `money_text()`, `days_text()`, `count_text()` are the only number-to-text paths; locals holding rendered text end in `_text` (both guards look for that) | same |
| §11.3 "reuse a money(), do not add a fifth" | **Deviation, recorded:** the four named helpers all QUANTIZE and none formats to text — the text step did not exist. `money_text()` delegates quantisation to `invoice_builder.money()`; no fifth quantizer | same |
| §11.7 step 4 — L1 | `verify_claims(block)`: two claims about the same entity asserting different values for one fact → `block["contradictions"]`. No table of incompatible card pairs; a card participates by declaring `asserts` | same |
| Gap 519 | `rank_findings()` primary key is `SEVERITY_RANK[claim.severity]`, money second | same |

Cards on the new shape: `terms_check`, `bank_reconcile`, `agreed_vs_billed`, `cash_cover`, `open_po_value`, `cash_out_timing`, `delivery_vs_order`, `compliance`. New: `payment_application` (REMITTANCE_ADVICE, before `net_position`), `linked_duplicates` (DELIVERY_NOTE, GRN). Not yet migrated (still `finding()` + f-strings, no money in them): `what_this_is`, `net_position`, `cash_impact`, `over_invoicing_history`, `quote_drift`, `partial_delivery_balance`, `repeat_short_delivery`, `contract_deviations`, `suggested_questions`, `confidence_gaps`.

### 12.2 Decisions taken inside the build (founder to overrule if wrong)

1. **Unmatched bank rows are unknowns, not findings** (Gap 515.2). Only a payment against an already-settled bill is a finding. The user still sees every unmatched row, under "checks not run", with its amount, date and narration.
2. **A full settlement is spoken** (Gap 518): `payment_settles_in_full` is emitted as an `info` finding even though the check PASSED — it is the answer the document asks for.
3. **Gap 513 rule shape**: substring removed; whole-name word-boundary match with longest-name-wins, plus resolver bindings; ambiguous mentions select nothing. Pure resolver binding alone was rejected because `_vendor_mentions()` needs a capitalised name after a lead word and the protected legacy question ("what did we pay acme corporation") has neither.
4. **30.9**: India cards remain `unverified` — every primary source probed 2026-09-14 was unreachable (ECONNRESET / 404 / JS shell / TLS). `card_compliance` now renders them as `NOT_CHECKED` naming rule and source, so the bubble says a check is missing rather than "no IN rule card applies". No rule text was written from memory.

### 12.3 Verification (real Postgres, `localhost:5433/invoice_db`)

`tests/test_insight_claims.py` 22 (incl. the fixture-mutation test), `tests/test_insight_track_b.py` 16, `tests/test_no_hardcoding.py` 4; Feature 30 file set + guards **210 passed**; Track C/D with chat neighbours (`test_rule_schema`, `test_trainer`, `test_entity_resolver`, `test_chat_sql_quality`) **272 passed**. Re-baselined with the reason in the body: `test_bank_matching.py::test_the_sync_bubble_reports_the_match_and_the_as_of_date` (plus the unmatched-credit row §11.5 said was missing). The full 1h23m suite was last run before Tracks B–D (3787 passed, Gaps 520/521 fixed since) and was **not** re-run inside the hour.

### 12.4 Still open on this feature

30.15 live narration run; Track E (FE Gaps 470/471/472, Gap 514 + FE Gap 478 — renumber FE 478 first); the ten cards listed above still on f-strings (no money in them, so the guard is silent, but §11.3's "one renderer" is not yet true for them); Gap 516 parked.

### 12.5 Task 30.15 — first live narration run, 2026-09-14 12:01–12:06

`scripts/run_insight_eval.py --narrate` (one gpt-5-mini `chat_summary` call per case, real Postgres):
**18/20 cases passed · figures exact 21/21 (100%, target ≥ 90%) · fabricated figures 0 (target 0) ·
model-narrated 20/20 · answer-contract gate held 20/20.**

Two failures, both golden expectations that describe the bubble BEFORE tasks 30.19/30.20 — the golden
bank is ground truth and is **not** edited without a founder ruling:

| case | expects | now | why |
|---|---|---|---|
| `statement_four_matches_in` | finding `bank_reconcile:unmatched_debit:*` | NOT_CHECKED entry | Gap 515.2 — an unmatched row is an unknown, not a problem |
| `credit_note_net_position_in` | `compliance` skipped | `compliance` ok, "0 IN rules checked, N not checked" | §12.2(4) — unverified IN cards are surfaced, not hidden |

**New finding — Gap 522.** 17 of the 20 model verdicts print raw floats ("overbilled by 23200.0",
"across 2.0 bills", "allows 45.0 days"). 30.20 gave the cards one number-to-text path and left the
narration step out: the model is shown `_f()` floats, repeats them faithfully, and the contract gate —
which checks presence, not spelling — holds. The deterministic eval grades figures by value and so could
never see this; only the live run could. Proposed fixes are in the Gap entry; none applied.

### 12.6 Gap 522 closed — 2026-09-14 12:43–12:51 (founder: option (a))

The narration model no longer sees a number. `narration_payload()` hands it `figures_text` and
`impact_text`, rendered through the same `money_text()` / `days_text()` / `count_text()` the cards
use, with the shape chosen by the figure's KEY (`figure_text()`); the prompt says to copy that
spelling character for character. The contract gate keeps the raw figures in its allowed set, so
nothing that passed before fails now. Second live run: **20/20 · 21/21 exact · 0 fabricated · gate
20/20 · raw-float verdicts 0/20** (was 17/20). §11.3's "one renderer" is now true end to end —
cards, bubble titles, and the model's sentence.

### 12.7 Still open on this feature after 2026-09-14

Nothing in Tracks A–E. Gap 516 (STATEMENT_OF_ACCOUNT overload) stays parked on Feature 27's frozen
taxonomy; Feature 33 / FE Feature 22 / Feature 31 parked by ruling. The full 1h23m suite has not been
re-run since Tracks B–E landed — the F30 file set, guards, chat neighbours and the FE suite have.
