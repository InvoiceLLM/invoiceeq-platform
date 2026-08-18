# senior-dev — RAG retrieval group (BE Gaps 244, 240, 243, 239)

Scope approved by founder via architect. BE gaps only — invoice-fe untouched.
Bundled deliberately: Gap 244 forces a full re-embed, Gaps 240/243 change what gets indexed.

## Steps

- [x] 1. Read CONVENTIONS + the four tracker gap entries (244, 240, 243, 239)
- [x] 2. Read current code: `chroma_client.py`, `queue_worker/handlers.py`, `queue_worker/outbound_handlers.py`, `routers/audit.py`, `routers/outbound_audit.py`
- [x] 3. Gap 239 origin hunt — **DONE, result: there is no such path.** Exhaustive grep of `routers/`, `services/`, `queue_worker/`, `scripts/`, `agents/`, `utils/`, `models.py`: zero hard-deletes of an `Invoice` row anywhere in product code (only `admin.py` User, `chat.py` ChatSession/Message/Rule, `connectors.py`, `email_ingestion.py`, `webhooks.py`). Both invoice delete endpoints (`routers/invoices.py::delete_invoice` L770, `::rollback_batch` L650) are **soft** deletes (`deleted_at = now`), Gap 192 by design. `chroma_client.delete_invoice_chunks()` has **zero call sites in product code** — nothing ever removes chunks. Real origin found instead (see step 3b).
- [x] 3b. Gap 239 real origin **confirmed by direct measurement**: local Chroma holds **41** `invoice_chunks_*` collections; local Postgres has **7** tenants, only **3** of which have a collection. 38 collections belong to tenant ids that no longer exist at all → the desync is produced by Postgres schema teardown (every `tests/test_*.py` fixture calls `SQLModel.metadata.drop_all(engine)`) / DB resets against a Chroma volume that outlives them, exactly the "test-environment artifact" hypothesis the gap listed as one of two options. Not a product deletion path.
- [x] 4. Baseline measurement (BEFORE) — **found a material correction to the tracker's Gap 244 root cause**: real `BAAI/bge-m3` loaded live (2.2 GB, downloaded to HF cache) returns vectors with L2 norm **1.0**, not 1.82 — its `modules.json` already includes a `sentence_transformers.models.Normalize` module (idx 2) after Transformer+Pooling. The tracker's "measured 1.82" figure is the signature of the **mock** embedding path (`MOCK_EMBEDDINGS=true` is set in this repo's local `.env`; `get_embeddings()`'s mock branch returns `random.uniform(-0.1, 0.1)` over 1024 dims → measured mean norm **1.847**, range 1.814–1.942, and mock-vs-mock squared-L2 distance **6.55**, squarely inside the reported 5.8–7.3 band). Verified numerically both ways.
- [x] 5. Gap 244 (a): `normalize_embeddings=True` on `get_embeddings()`'s `model.encode()` — done; **also normalized the mock branch**, since unnormalized mock vectors are precisely what made this gap's original investigation misread mock data as a real-model measurement.
- [x] 6. Gap 244 (b): `metadata={"hnsw:space": "cosine"}` on all three `get_or_create_collection()` call sites (via `_collection_metadata()`), plus the two new ones added by `has_invoice_chunks()`. **Verified live against chromadb 1.5.9**: passing cosine metadata to an existing `l2` collection silently returns it still on `l2` — no error, no warning — so re-embedding is mandatory, not optional. Added `_collection_space()` / `_to_cosine_distance()` so the threshold means the same thing on a not-yet-migrated collection (for unit-norm vectors squared-L2 = 2x cosine distance exactly; confirmed in the measurements, every l2 figure is exactly 2x its cosine twin).
- [x] 8. Gap 244 (c): threshold re-derived empirically → **0.49 cosine** (was 0.4 in an unbounded raw-L2 space). See step 4/§Measurements.
- [x] 9. Gap 240: `handlers.py` now gates on the shared `should_index_status()` instead of `status == "COMPLETED"`; `routers/audit.py::resolve_audit_invoice` backstop added after commit, keyed on the resolution itself (correct — `target_status` is validated against exactly PAID/REJECTED/AUDIT_REQUIRED, and is `None` for a plain dismiss/correction, so nothing about "reaching COMPLETED" would ever fire). Backstop probes `has_invoice_chunks()` first so the normal already-indexed case costs one cheap Chroma `get`, not a re-embed.
- [x] 10. Gap 243: `outbound_handlers.py` gates on the same `should_index_status()`; `routers/outbound_audit.py::resolve_outbound_alert` got the twin backstop. Note that endpoint never mutates `invoice.status` at all, which is why "index on resolution" is the only workable trigger there.
- [x] 7. Gap 244 migration: `scripts/reembed_chroma_collections.py` finished + verified running against the real local stack (dry run, `--prune-only` audit, and a real `--apply --tenant <tenant-us>` with `MOCK_EMBEDDINGS=false`). Added since session 1: chunk-level orphan scan (`_orphan_chunk_invoice_ids()`), a `--prune-only` audit mode that never loads the model (so it's safe with `MOCK_EMBEDDINGS` on), before/after HNSW-space reporting (`_current_space()`), and a post-rebuild assertion that the collection really came back as `cosine` rather than assuming it. Documented procedure written into `docs/feature_6_rag.md` §"Gap 244 re-embed migration procedure".
- [x] 7b. **Blast-radius finding, answers the founder's question 2 directly.** Measured the L2 norm of every vector actually stored in every live local collection *before* migrating: IEQ-India 5 chunks mean **1.8604**, IEQ-US 9 chunks mean **1.8570**, IEQ-Europe 7 chunks mean **1.8557** — all three the mock random-vector signature (~1.85), none anywhere near unit norm; all three on `space=l2`. **Not one real-model embedding existed in the local Chroma stack.** Real-model RAG retrieval had therefore never been exercised locally at all, through any test, before this pass. See §Blast radius below.
- [x] 11. Gap 239: no product deletion path exists to fix (step 3) — delivered orphan detection/pruning in the re-embed script at **both** granularities (orphan collections, and orphan *chunks* inside a live tenant's collection, which is the shape the gap was actually filed for), and documented on `delete_invoice_chunks()` itself why it must stay out of the soft-delete paths. **The chunk-level scanner reproduced the reported symptom exactly**: tenant-us held 2 chunks whose `invoice_id` matches no `Invoice` row, both with `vendor_name: Blue Ridge Logistics` — precisely the "cited 3 ids, 2 return zero rows" the gap reported. Pruned by the migration rebuild; a re-scan after migration reports 0.
- [x] 12. Tests: 26 added in `tests/test_rag.py` (unit-norm embeddings, `_to_cosine_distance` rescaling, cosine-space creation, `matched_by` channel reporting, threshold pinned to 0.49, `should_index_status()` both directions ×17 params, and 4 resolve-backstop tests covering inbound backfill / already-indexed skip / failure tolerance / outbound twin). Also **inverted an existing test that asserted the Gap 243 bug**: `tests/test_direction_aware_chat.py::test_needs_review_outbound_invoice_skips_rag_indexing` locked in the `status == "VERIFIED"` gate — renamed to `..._also_triggers_rag_indexing` and paired with a new `test_unextracted_outbound_invoice_is_not_rag_indexed` so widening the gate is still bounded. To make `chroma_client.query_invoice_chunks()` assertable at all, each returned chunk now also carries `keyword_score` and `matched_by` (`vector` / `keyword` / `vector+keyword`) — purely additive; `agents/query_agent.py` reads only `document`/`metadata` (verified, not assumed) and was not touched.
- [x] 13. Full BE suite green against the real local Postgres/Redis/Chroma stack: **609 passed, 0 failed, 5 deselected**, run three times. Fixed a **pre-existing, order-dependent** failure surfaced (not caused) by this work: `test_rag_citations_drop_ids_with_no_matching_invoice_row` asks a fixed question as the fixed `MOCK_TENANT_ID`, and the Task 6.11 answer cache lives in the *real shared* local Redis with a 1hr TTL and no per-test namespace — a `chat_answer_cache:00000000-…:which vendors have freight charges?` entry left by an earlier run was served instead of the mocked RAG path, so the test asserted against a stranger's citations. Confirmed by reading the live key out of Redis. Fixed hermetically (`patch("agents.query_agent.get_cached_answer", return_value=None)`) rather than by clearing shared state.
- [x] 14. Gap 244 (d): category-browsing test re-run **live through the shipped `query_invoice_chunks()`**, with a real before/after on the real stack. See §Step 14 results.
- [x] 15. Spec bodies updated. `feature_6_rag.md`: File Coordinates extended, RAG-route narrative rewritten (0.49 cosine, `_to_cosine_distance()`, `matched_by`), Tasks 6.3/6.4/6.7 updated in place, four new Recent-Fixes entries (244/240/243/239), a **Root-cause correction** subsection, a **Gap 244 re-embed migration procedure** subsection (6 steps incl. rollback), and a Verification Plan that explicitly labels the unit tests structural-only. `feature_2_pipeline_extraction.md`: the `if status == COMPLETED` indexing line corrected to `should_index_status()` with the Gap 240 reasoning. `feature_2.1_vendor_flow_ingestion.md`: Task 2.1.3's **stale** "No RAG indexing — out of scope for ingestion" claim corrected (indexing was added by Feature 6.1 Task 6.1.3) plus the Gap 243 fix and its regression coverage.
- [x] 16. Tracker updated: **239 `[~]`→`[x]`, 240 `[ ]`→`[x]`, 243 `[ ]`→`[x]`, 244 `[ ]`→`[x]`**, each with measured evidence. Gap 244 carries a ⚠️ **ROOT-CAUSE CORRECTION** banner at the top of the entry naming items 2 and 4 as mock-path artifacts, plus a full "Corrected root cause" block including the blast-radius measurement. Gap 240 records the correction that its own suggested backstop ("any row that reaches COMPLETED") would never have fired. Gap 239 records the live 38→84 orphan growth. Nothing was marked closed on a description now known to be wrong.
- [x] 17. Cleanup: `_gap244_measurements.json` / `_gap244_wide.json` folded into `docs/test_evidence/gap244_rag_retrieval_2026-08-17/` (renamed to say what they are) alongside the step-14 output and a README; the 8 stray `tests/_*` scratch files removed. `tests/gap237_sql_repro.py` and `tests/gap242_reseed_blue_ridge.py` left untouched (another agent's).
- [x] 18. `docs/test_coverage_map.md` deliberately **not** touched — it is functional-tester's file per CONVENTIONS, and a functional-tester was concurrently adding rows to it during this pass. The row for this work is theirs to add.

## Step 14 results — live, real model, real stack

Evidence: `docs/test_evidence/gap244_rag_retrieval_2026-08-17/`.

**BEFORE** (control: tenant IEQ-Europe, deliberately left unmigrated — `space=l2`, 7 stored chunks all mock random vectors), queried through the shipped code path with the real model:

| question | result |
|---|---|
| "Do we have any industrial or machinery invoices?" | Rhein Industrietechnik, dist **2.3610**, `matched_by=keyword` |
| "What about catering or food costs?" | **NO MATCHES** |
| "Show me manufacturing or tooling charges" | **NO MATCHES** |

2.3610 is **4.8× the 0.49 threshold**. The vector channel contributes nothing; the single match is carried entirely by literal keyword overlap — exactly the state Gap 244 described.

**AFTER** (tenant-us, migrated: `space=cosine`, 10 chunks, every stored vector L2 norm exactly 1.000000):

| # | question | top expected match | dist | kw | carried by |
|---|---|---|---|---|---|
| 1 | How much did we spend on office supplies? | Summit Office Supplies | 0.4132 | 2 | vector+keyword |
| 2 | And logistics or freight costs? | Blue Ridge Logistics | 0.4299 | 2 | vector+keyword |
| 3 | Show me manufacturing or tooling charges | Cascade Manufacturing Co | 0.3848 | 2 | vector+keyword |
| 4 | Any janitorial or cleaning services? | Redwood Facilities Group | 0.4749 | 2 | vector+keyword |
| 5 | What about printing costs? | Apex Print Solutions | 0.3924 | **0** | **vector only** |
| 6 | Do we have any steel or materials related invoices? | Titan Steel Distributors | 0.3823 | 1 | **vector only** |
| 7 | Do we have any legal or attorney fees? | *(none exist)* | — | — | **NO MATCHES** ✓ |
| 8 | Any airline or travel bookings? | *(none exist)* | — | — | **NO MATCHES** ✓ |

6/6 real categories retrieved; 2/2 absent categories honestly returned nothing.

**Turn 5 is the single most load-bearing data point in this whole pass.** "What about printing costs?" matched Apex Print Solutions with `keyword_score=0` — the document says "Print", the question says "printing", so there is *zero* literal overlap and the old keyword fallback could not have carried it under any threshold. It was retrieved purely by semantic similarity. It is also an `AUDIT_REQUIRED` invoice, so before this pass it wasn't in the index at all (Gap 240). Turn 5 therefore proves Gap 240 and Gap 244 simultaneously, on real data. Turn 6 (Titan Steel, also `AUDIT_REQUIRED`, kw=1 < min_k_score=2) is the same proof a second time.

Honest caveat: at 0.49 several turns also admit non-expected chunks under the threshold (turn 6 admits 5). That is recall-oriented by design — the LLM filters the passed chunks afterwards — and it is strictly better than the old state where those questions returned only keyword hits or nothing. It is not a regression, but it is the reason 0.49 was set at the midpoint of the separation band rather than at its top.

## Migration actually run

`--apply --tenant 3511ae3e-…` (tenant-us) with `MOCK_EMBEDDINGS=false`. Before: `space=l2`, 9 chunks — 7 real + **2 orphans**. After: `space=cosine`, 10 chunks, 10 distinct invoice ids, 0 orphans, all norms 1.000000.

The before-state arithmetic independently confirms Gaps 240 and 243 at once: tenant-us has 4 COMPLETED + 3 VERIFIED + 2 AUDIT_REQUIRED + 1 NEEDS_REVIEW, and exactly **7 = |COMPLETED| + |VERIFIED|** invoices were indexed. The 3 missing were precisely the 2 AUDIT_REQUIRED (Gap 240) and the 1 NEEDS_REVIEW (Gap 243). Nothing else was migrated — the other tenants were left as-is on purpose, both to preserve the before-state control and to avoid touching a concurrently-used stack.

## Blast radius — was real-model RAG ever exercised locally? (founder question 2)

**No. Not once, before this pass.** Measured norms of every vector stored in every live local collection, before migrating anything: IEQ-India 1.8604, IEQ-US 1.8570, IEQ-Europe 1.8557 — all the mock random-vector signature, all on `space=l2`. Zero real-model vectors existed anywhere in the local Chroma stack.

Consequences for previously-filed evidence:
- **Gap 244's "5.8–7.3 measured L2 distances" — 100% mock artifact.** Mock-vs-mock squared-L2 is ~6.55, dead centre of that band. No real-model distance was ever in it.
- **Gap 240's Chroma-vs-Postgres diff — survives intact.** That finding is about *which invoice ids are present*, which is independent of vector content, and it is corroborated by the code gate and re-confirmed by the 7 = COMPLETED+VERIFIED arithmetic above.
- **The category-browsing test's "every correct answer came via keyword overlap" — survives, and is now fully explained.** With random vectors the vector channel carries no signal by construction, so the keyword fallback was mathematically the only thing that could ever have worked.
- Gaps 241/242 are SQL-route findings and never involved embeddings.

Stopping here per instruction; not chasing further.

## Constraints

- No model change (keep `BAAI/bge-m3`), no new embedding vendor.
- Do NOT touch `agents/query_agent.py` (concurrent edit by another pass).
- Do NOT touch invoice-fe / invoice-website.
- Do NOT reset/wipe shared DBs — a functional-tester is concurrently running a read-only repro (BE Gap 237) against the same local Postgres and seeding its own tenant.

## Status

Started 2026-08-17. **Session 1 ended mid-step-7 (API limit, not a work problem). Session 2 resumed 2026-08-17** from this list — steps 1-6, 8, 9, 10 accepted as done (independently spot-checked against `git diff`), continuing at 7 / 11-16.

**COMPLETE, 2026-08-17.** All 18 steps done. All four gaps (244, 240, 243, 239) closed `[x]` in the tracker with measured evidence. Full BE suite green — 609 passed, 0 failed, run three times against the real local Postgres/Redis/Chroma stack. The tracker's stated Gap 244 root cause was found to be factually wrong (mock-path measurement read as real-model) and is corrected explicitly rather than shipped under. `agents/query_agent.py` untouched; invoice-fe and invoice-website untouched; no shared database reset. Two open items handed to the founder, both deliberate: **(a)** only tenant-us was migrated — the other three tenants still hold mock vectors and need `--apply` run per tenant; **(b)** the test suite manufactures orphan Chroma collections on every run (38→84 during this pass), which needs a fixture-teardown fix or an ephemeral Chroma path.
