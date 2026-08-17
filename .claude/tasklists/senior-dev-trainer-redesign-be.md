# senior-dev — Trainer/Chat redesign (BE half)

Scope: `Prod_Invoice_LLM/apps/invoice-be/` only (+ two documentation single-block exceptions).
Tracker entries start at **BE Gap 228**. New spec doc: `docs/feature_18_trainer_alert_anchored_training.md`.

## Part 1 — Foundations (shared modules)
- [x] 1.1 Read CONVENTIONS, tracker gaps 209–227, feature_10_trainer.md, and every File Coordinate in the brief (verified against live code, not the doc)
- [x] 1.2 `utils/rule_schema.py` — structured rule object (`field/condition/scope/source_alert_type/origin/text` + `kind`/`params`), `render_constraint()`, `normalize_constraints()` single shared normalizer, override extractors (`tolerance_overrides`, `confidence_threshold_override`, `alert_overrides`), `apply_alert_overrides()`. **Design call:** `normalize_constraints(for_prompt=True)` filters out tolerance/threshold/severity kinds — feeding numeric slack into the extraction prompt would fight `GAP_46_VERBATIM_DIRECTIVE`.
- [x] 1.3 `utils/alert_registry.py` — 17 types, full verified vocabulary with label / producer / tolerance-overridable / threshold-overridable, plus `TOLERANCE_EXCLUDED_SOURCE_TEXT_TYPES` for the five `*_not_verified_in_source` types

## Part 2 — Dual-format reads (highest regression risk)
- [x] 2.1 `agents/extraction_agent.py` (:181-183, :280-282, :305, :316) → normalizer
- [x] 2.2 `agents/outbound_extraction_agent.py` (:81-83, :115-117) → normalizer
- [x] 2.3 `agents/query_agent.py` (:304, :330) → normalizer
- [x] 2.4 `queue_worker/handlers.py` (:321, :614, :636 — `_get_template_rules`, `_merge_constraints`) → normalizer-safe
- [x] 2.5 `queue_worker/outbound_handlers.py` (:27, :58) → normalizer-safe
- [x] 2.6 `routers/audit.py` (:239-293) → normalizer + `_apply_standing_rule()` emits structured objects
- [x] 2.7 `routers/outbound_audit.py` (:110-137) → normalizer + `_apply_standing_rule_direct()` emits structured objects
- [x] 2.8 `routers/trainer.py` constraint reads → normalizer
- [x] 2.9 Explicit regression test: legacy free-text rules still render identically end-to-end

## Part 3 — Verification parameterization
- [x] 3.1 `utils/verification_tools.py` — add `tolerances=` parameterization to `verify_line_items_math` / `verify_totals_math` (additive only, defaults byte-identical). No restructuring of the checks.
- [x] 3.2 `agents/extraction_agent.py::verify_node` — actually read `state["rules"]` (it never did) → tolerance, confidence threshold, severity/message overrides
- [x] 3.3 `agents/outbound_extraction_agent.py::verify_node` — same wiring (Gap 223 wired checks but not parameterization)

## Part 4 — Schema + migration
- [x] 4.1 `models.py`: `TenantChatSettings`, `TenantChatRule`, `ChatFeedback.reason`/`note`, `ChatMessage.result_invoice_ids`
- [x] 4.2 One Alembic migration `f18a0c4b7d21` (head `fe6371baa50d`; first ID collided with an existing `a1b2c3d4e5f6`, renamed) incl. non-destructive data migration of `rules["chat_style"]` → `TenantChatSettings`
- [x] 4.3 Verified on a throwaway **Postgres** DB (`f18_migtest`), not SQLite: full chain upgrade -> head, seeded a real `rules['chat_style']` row, re-upgraded and confirmed it copied into `tenant_chat_settings` with the source key left in place, then downgraded clean. (SQLite can't run the chain at all — pre-existing migration `71d18e2c3349` uses a non-batch ALTER; unrelated to this work.)

## Part 5 — Trainer session redesign
- [x] 5.1 `POST /trainer/sessions/from-invoice` — specific invoice picker (not latest-only), **no OCR re-run**, lands on that invoice's `sa_alerts`, server-side `pdfUrl`
- [x] 5.2 Upload path: server-side `pdfUrl` + alerts on `/trainer/upload`, same session shape (shared builder)
- [x] 5.3 `GET /trainer/sessions/{id}/pdf` for the transient upload-path PDF
- [x] 5.4 Remove Global-scope rule **creation** (410 on `/sessions/global`, commit rejects global scope). Global row + every existing read left untouched.
- [x] 5.5 `GET /trainer/alert-types` — registry endpoint

## Part 6 — Correction endpoints (3 shapes + missed)
- [x] 6.1 Unnecessary → tolerance override (3 eligible types only)
- [x] 6.2 Unnecessary → `low_confidence_field` threshold override (separate form)
- [x] 6.3 Wrong severity/message override
- [x] 6.4 Flag-as-missed (registry pick + field; free text secondary only) → LLM-interpreted constraint

## Part 7 — Preview-before-commit gate
- [x] 7.1 `POST /trainer/sessions/{id}/preview` — structured interpretation + **exact** historical replay for math-class rules (pure functions over stored columns, no re-extraction/LLM), `not_computable` for text rules
- [x] 7.2 `_validate_rule_text()` runs at preview; Gap 217 400-contract kept on `/commit` as backstop
- [x] 7.3 `/commit` accepts preview token, 409 on drift; everything else in `trainer_commit()` byte-for-byte unchanged

## Part 8 — Chat-correction lane (never touches `ExtractionTemplate.rules`)
- [x] 8.1 `_get_chat_style_block()` repointed to `TenantChatSettings` (signature + fallback unchanged, 3 call sites untouched)
- [x] 8.2 New `_chat_rules_block()` injected **next to** `_business_rules_block()`
- [x] 8.3 `ChatMessage` result-set snapshot populated at answer time (SQL route + RAG)
- [x] 8.4 Trainer QA-mode turns persist as real `ChatMessage` rows. **Latent bug confirmed by direct repro, not assumed:** `get_chat_history('trainer-qa-<uuid>')` does not crash — `UUID()` raises `ValueError`, is caught, and returns `""`, so QA mode silently had zero multi-turn memory on every turn. Fixed by backing the lane with a real `ChatSession`. persist as real `ChatMessage` rows; verify/fix the non-UUID `session_id` → `get_chat_history()` latent bug
- [x] 8.5 Triage backend: reason, auto-diff, PDF-verdict redirect into extraction flow, category pick, `bad_tone` → settings
- [x] 8.6 Chat-rule preview → explicit confirm → commit

## Part 9 — Tests + verification
- [x] 9.1 New tests in `tests/test_trainer.py` (63 total, was 35)
- [x] 9.2 New tests for the chat lane (`tests/test_chat_training.py`, 29)
- [x] 9.3 Dual-format regression tests (`tests/test_rule_schema.py` 18 + `tests/test_verification_overrides.py` 9)
- [x] 9.4 Full backend suite green: **552 passed, 0 failed, 5 deselected** (baseline before this work: 470 passed). Verified under both `-p no:randomly` and default random ordering. (no new failures vs. baseline)

## Part 10 — Documentation
- [x] 10.1 `feature_10_trainer.md` — verified by diff: **4 insertions, 0 deletions**. The `[!CAUTION]` block + one appended sentence on Task 10.11. Nothing else changed.
- [x] 10.2 New `docs/feature_18_trainer_alert_anchored_training.md` — includes the alert-type registry table, the explicit Gap 229 follow-up for the five excluded types, a Frontend-contract section for the FE pass, and a "Deviations from the approved plan" section (7 items).
- [x] 10.3 Tracker: **Gaps 228–232** added. Append-only notes on Gaps 217 / 221 / 225 after reading their real logged text — verified by diff (15 insertions / 3 "deletions", all 3 being the same lines appended to). Gap 225 left `[ ]`. Gap 218 NOT marked superseded.
- [x] 10.4 `docs/test_coverage_map.md` — 7 new rows, incl. the migration's real-Postgres verification and an explicit **NOT DONE** row for live/manual verification.

---
## Final status — COMPLETE (2026-08-13)

**Built:** 4 new modules (`utils/rule_schema.py`, `utils/alert_registry.py`, `services/rule_impact.py`, `services/chat_rules.py`), 1 migration (`f18a0c4b7d21`, confirmed single alembic head), 4 new model/column additions, ~20 new/changed endpoints, 3 new test files.

**Tests:** 552 passed / 0 failed / 5 deselected (baseline before this work: 470). Verified under both `-p no:randomly` and default random ordering. `ruff check` clean on all changed modules.

**Migration:** verified on a throwaway **Postgres** DB (upgrade → seed real `chat_style` → re-upgrade → confirm non-destructive copy → clean downgrade). SQLite can't run the chain at all due to pre-existing `71d18e2c3349`.

**Not done (declared, not hidden):** no live/manual verification against real Azure OCR/LLM — filed as part of BE Gap 229.

**7 deviations from the approved plan**, all recorded in `feature_18_trainer_alert_anchored_training.md` § "Deviations from the approved plan". The two that most affect the design: (1) the upload path does **not** create an `Invoice` row so it can't literally call `from-invoice` — both paths instead produce the same session shape and landing state; (2) `Invoice` has **no `subtotal` column**, so `line_items_mismatch`/`tax_mismatch` replay falls back to `source_document_json` and is reported `not_computable` when unavailable, rather than estimated.

**Changes left uncommitted** per repo convention.
