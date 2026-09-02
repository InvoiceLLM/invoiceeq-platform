# Feature 27 — G4: `classify_doc_type_node` + the conditional graph entry point

Spec: `Prod_Invoice_LLM/apps/invoice-be/docs/feature_27_generic_extraction.md` §3 E7,
§2A/A1's sequence, §5 steps 2–6, §10 G4. Continues G1/G2 (Gap 369), G3 (Gap 371),
G3b (Gap 372). Includes **one narrow slice of G6** — moving `extract_node`/`verify_node`
onto `resolve_extraction_profile` — because G3b is dead code until something calls it
with a real `doc_type`. The rest of G6 (E9's fail-loud) and G5's `_VerificationRubric` /
G7's `run_field_confidence` / `run_di_tax_backfill` are NOT in this task.

- [x] Read CONVENTIONS.md, the spec (§2A/A1, §3 E3/E7, §5, §10 + all four build notes)
- [x] Check in-flight work (`.claude/tasklists/`, hard rule 5) — G3b is the direct
      predecessor; F26 Part 2 H2/H3/H4 touch `chroma_client.py`, a new service module,
      `routers/chat_attachments.py`, `models.py`, `config.py` — no file overlap
- [x] Read the real code: `ExtractionState`, `classify_node`, `dynamic_qa_node`,
      `extract_node`, `verify_node`, the graph assembly block, `run_extraction_agent`,
      and `services/document_type_classifier.py::classify_doc_type`'s return shape
- [x] Confirm where `tracked_llm_call("extraction.classify_doc_type")` already lives —
      G2's `_classify_with_llm`, so G4 adds **no** second event (would emit on the
      deterministic path and double-count the fallback)
- [x] Confirm the compiled-graph introspection API in langgraph 1.2.6 (`graph.nodes`,
      `graph.get_graph().edges`) so the flag-OFF absence test asserts on real structure
- [x] Widen `ExtractionState` with `doc_type` / `doc_type_evidence` / `doc_type_confidence`
      (method/reason logged only — no persistence target in E10's column list)
- [x] Add `classify_doc_type_node` (no telemetry of its own; failure degrades to
      unclassified, never to a failed extraction)
- [x] Conditional entry point **at graph-build time** — `_build_extraction_graph(
      include_doc_type_classifier=…)` + `@lru_cache(maxsize=2)` + `resolve_extraction_graph()`;
      `graph` stays the flag-OFF object, returned by identity
- [x] Wire `extract_node` / `verify_node` onto `resolve_extraction_profile` (the G6 slice)
      and bind the classified `doc_type` into the generic multimodal prompt (`functools.partial`)
- [x] Collision-check the Gap number fresh immediately before writing — max was 373 at
      dispatch, 374 filed by the parallel F26 H4 build → **375**
- [x] Extend `tests/test_generic_extraction.py` — flag-OFF graph structure + a full run
      that never calls the classifier; flag-ON node order, deterministic pass with no LLM
      call, ambiguous → fallback under the right telemetry key, doc_type reaching both nodes
- [x] Run the tests — **144 passed in 6.51s** (120 before this change)
- [x] Negative controls ×2 — unconditional entry point (node always in the graph) → exactly
      4 failures / 140 green; both nodes reverted to `resolve_direction_profile` → exactly
      5 failures / 139 green; restored from backup after each, re-run → 144 passed
- [x] Regression sweep — extraction_agent importers + this file → **278 passed**;
      `test_chat_attachments.py test_sse.py test_trainer.py test_audit.py` → **118 passed**
- [x] File Gap 375 in `be_features_tracker.md`
- [x] Update the spec: G4 `[x]`, G6 marked partly-done with what remains, additive
      "Build note — G4, 2026-09-02"
- [x] Leave everything uncommitted (`git diff --numstat agents/extraction_agent.py`:
      **822 insertions / 24 deletions** vs HEAD for G3+G3b+G4 together; all 24 deletions
      are moves)

**Final status: complete.** The flag-ON path now runs end to end for the first time — a
delivery challan is classified deterministically, extracted on `GenericDocumentSchema` and
verified to `EXTRACTED`. The flag stays OFF: `verify_node` still runs the money rubric for
every type (G5) and the DI Critic is still ungated (G7), so the founder's original symptom
survives by its second route until those land, and nothing persists `doc_type` yet (G9).
Evidence caveat: pure Python, fake LLM, no Postgres; T-OFF-1/T-R-6 remain task V, blocked
on §7 task F's fixtures.
