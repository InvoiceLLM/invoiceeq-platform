# senior-dev — Gap 253: Chat SQL route line-item-level extraction

> **SUPERSEDED, 2026-08-19.** This plan is kept for its scope/boundary analysis,
> which still holds. Its *approach* does not: step 2(c) below teaches both the
> Postgres and the SQLite un-nest variant inside one prompt, with no signal for
> the model to pick between them, which is a coin flip on every line-item
> question. What actually shipped is **dialect-conditioned prompt text** —
> `_sql_dialect_name(db_session)` resolves the live engine at prompt-build time
> and `_line_item_rule()` renders exactly one variant (`_LINE_ITEM_RULE_POSTGRES`
> or `_LINE_ITEM_RULE_SQLITE`), so the model is never shown syntax the bound
> engine cannot run. That is the same mechanism rule 6(a) already used for the
> `CAST(... AS TEXT)` decision, rather than a third pattern.
>
> Other deltas from this plan, all recorded in the tracker's Gap 253 entry:
> * A short-lived intermediate implementation (regex-translating Postgres JSONB
>   syntax into SQLite inside `execute_generated_sql`) was removed, not patched.
> * Both variants now carry a **NULL / non-array `items` guard**; without it a
>   single bad row aborts the query for the whole tenant.
> * `WITH ORDINALITY` / `line_index` (step 2) was **not** built, so FE steps 7–8
>   (`Citation.line_index`, `CitationPill` rendering) are **not** done and stay
>   out of scope. Rule 6d deliberately does not select `invoice.id` either.
> * Step 4's id-harvester fix landed differently: rather than stripping the
>   projection, `_harvest_invoice_ids_via_companion_query()` now whitelists the
>   un-nest join by shape and rebuilds with `SELECT DISTINCT invoice.id`.
> * Rule 9 gained an explicit FROM-clause exception (a narrowing line-item
>   follow-up must add the join), which this plan did not anticipate.
>
> Live functional-tester follow-up (the "Owner handoff" section at the bottom) is
> still outstanding and still worth running as written.

Scope: Fix SAGE chat SQL so queries targeting one specific line item return that
line item's own `amount` (qty × unit_price) rather than silently returning the
whole invoice's `grand_total` including unrelated lines and tax.

Files touched (BE):
  - `Prod_Invoice_LLM/apps/invoice-be/agents/query_agent.py` — SQL system_prompt
    (new rule 6d + dispatch rule for rule 6 family) + answer summarization
    prompt (line-item format branch) + companion-query id-harvester (strip UNNEST
    projection from id-rebuild query so it still runs)
  - `Prod_Invoice_LLM/apps/invoice-be/tests/test_chat_sql_quality.py` — additive
    unit tests verifying the prompt reaches the LLM and the SQL executes
    correctly against the real SQLite engine (mocked LLM pattern, same as the
    existing 241/242/237 tests in this file)
  - `Prod_Invoice_LLM/apps/invoice-be/docs/be_features_tracker.md` — update
    Gap 253 from `[ ]` to `[x]` with a fix note
  - `Prod_Invoice_LLM/apps/invoice-be/docs/feature_6_rag.md` (if the SQL route
    section exists there) — document the new extraction capability

Files touched (FE, strictly additive — no breaking changes):
  - `Prod_Invoice_LLM/apps/invoice-fe/types/chat.ts` — add optional
    `line_index?: number` and `line_description?: string` to the `Citation`
    interface
  - `Prod_Invoice_LLM/apps/invoice-fe/components/chat/CitationPill.tsx` — when
    `line_index` is present, render "· Line N" after the page block (or
    instead of p.N if the SQL route has no page concept — see boundaries)

Files explicitly NOT touched (boundaries):
  - `chroma_client.py`, RAG route, CHAT route — unrelated
  - classify_query() — routing itself is correct; only the SQL *generator*
    once inside the SQL route is wrong
  - `routers/chat.py` — transport layer is correct
  - Trainer / EVOLVE / SENTINEL — untouched
  - SQLite/Postgres schema — the JSONB `items` column already supports this
    (models.py:84); no migration needed
  - SqlAuditDrawer — it already renders raw generated_sql; it works as-is

## Steps

- [ ] 1. (BE, query_agent.py) **Rule 6 family dispatch**: Insert a short preamble
      between current rule 5 and rule 6 that teaches: when the user asks for a
      *specific line item's own dollar amount / quantity / unit_price* (not
      "which invoices relate to X"), use rule 6d; for invoice-level category
      totals or document discovery, use rule 6b. Prefer 6d for any question
      that names a dollar figure and a product/service phrase together.

- [ ] 2. (BE, query_agent.py) **New Rule 6d — Line-item extraction pattern**:
      After existing rule 6c, add rule 6d with three canonical SQL shapes that
      the LLM must reuse verbatim (customized to the keyword, tenant_id, and
      date/flow filters from other rules):

        (a) Detail rows (single invoice or across invoices):
            SELECT
              invoice.id AS invoice_id,
              invoice.invoice_number,
              invoice.vendor_name,
              invoice.customer_name,
              invoice.currency,
              idx::int AS line_index,
              item->>'description'   AS line_description,
              (item->>'quantity')::FLOAT   AS qty,
              (item->>'unit_price')::FLOAT AS unit_price,
              (item->>'amount')::FLOAT     AS line_amount
            FROM invoice, jsonb_array_elements(invoice.items) WITH ORDINALITY AS t(item, idx)
            WHERE invoice.tenant_id = :tenant_id
              AND LOWER(item->>'description') LIKE LOWER('%<keyword>%')
            ORDER BY invoice.invoice_date DESC, line_index ASC

        (b) Aggregate across matching lines (user asks "total", "sum", "how much total"):
            SELECT
              SUM((item->>'amount')::FLOAT) AS total_matching_lines,
              invoice.currency
            FROM invoice, jsonb_array_elements(invoice.items) WITH ORDINALITY AS t(item, idx)
            WHERE invoice.tenant_id = :tenant_id
              AND LOWER(item->>'description') LIKE LOWER('%<keyword>%')
            GROUP BY invoice.currency

        (c) SQLite variant (replace the FROM-clause UNNEST only; everything else
            identical): use `json_each(invoice.items) AS t` and extract via
            `t.value->>'description'` etc. since `json_each` returns one row per
            array element. ORDINALITY is not supported natively; fall back to
            `ROW_NUMBER() OVER (PARTITION BY invoice.id)` or omit line_index.

      Add portable-cast and case-insensitivity notes mirroring rule 6a/6b.
      Rule 6d must still honor rules 1 (tenant_id), 4 (flow_direction split), 7
      (include `currency`), 8a (no history-as-datasource), and 9 (WHERE-clause
      preservation on follow-ups) — so reference those explicitly inside 6d.

- [ ] 3. (BE, query_agent.py) **Answer summarizer per-line format branch**: In
      the `summary_prompt` block (~line 1128), add a rule: if the SQL result
      contains `line_description`, `qty`, `unit_price`, `line_amount` columns
      (detected by string/heuristic), then format each matching row *exactly*
      as:
         `{line_description}: {qty} units × ${unit_price} = ${line_amount}`
      If more than one row, append a final line: `Total: $<sum of line_amount>`.
      If exactly one row, emit only the one line with NO "Total:" suffix.
      Use the correct currency symbol from the `currency` column per rule 7
      (never default to $). This matches the founder-required format in the
      tracker entry.

- [ ] 4. (BE, query_agent.py) **_harvest_invoice_ids_via_companion_query**: The
      existing Gap 231 companion-query rebuild (which re-runs the same
      predicates SELECTing only `id`) must handle the new UNNEST-JOIN shape.
      Specifically: when the generated SQL contains `jsonb_array_elements` or
      `json_each`, the companion query must not try to project `line_description`
      columns; strip the SELECT list to `DISTINCT invoice.id AS id` while
      keeping the full FROM + WHERE intact. (If this step is skipped, the
      id-harvester returns zero rows for any 6d query and citations are empty.)

- [ ] 5. (BE, tests) **Add unit tests** to the existing
      `tests/test_chat_sql_quality.py`, in the same style as the existing 32
      tests there (mocked `_RecordingLLM` captures prompts, scripted SQL
      responses, real SQLite engine for predicate execution):
        (a) Prompt-rule reach — assert that when `with_structured_output.invoke`
            is called, the prompt string contains both the rule-6-dispatch
            preamble and the "jsonb_array_elements" text from rule 6d.
        (b) SQLite execution — seed an invoice with items =
            `[{"description":"Cloud Storage","quantity":1,"unit_price":765.36,"amount":765.36},
              {"description":"Training & Onboarding","quantity":40,"unit_price":732.5735,"amount":29302.94}]`
            plus `grand_total=35480.59`, then execute a scripted rule-6d-style
            SQL through the real SQLite engine and assert the matching-line
            result is $29,302.94 (not 35,480.59) AND that the unrelated Cloud
            Storage line is NOT in the result.
        (c) Multi-line total rule — seed two invoices with the same line-item
            keyword across 3 matching rows, execute the aggregate shape, assert
            the SUM equals only the matching rows' amounts summed.
        (d) Citation id-harvest — confirm companion-query on a UNNEST SQL still
            returns the invoice id(s) and does not throw.

- [ ] 6. (BE, tracker) Update `docs/be_features_tracker.md` Gap 253 line 719
      from `[ ]` to `[x]`. Add a fix note naming the new rule 6d, the
      SQLite/Postgres UNNEST variants, the summarizer format branch, and the
      test pass count from step 5 plus full-suite pytest result.

- [ ] 7. (FE, types/chat.ts) Additive only: add optional fields
      `line_index?: number` and `line_description?: string` to `Citation`.
      No existing consumer breaks (both optional). Backend's SQL route already
      appends `invoice_id` via the result_invoice_ids snapshot; future work
      (after this pass) can enrich citations with line_index — for now the
      fields just exist in the type so they don't get stripped when present.

- [ ] 8. (FE, components/chat/CitationPill.tsx) Additive render: if
      `citation.line_index` is present, append ` · L{citation.line_index}`
      after the `p.{citation.page}` span. If `page` is 0 / undefined (pure SQL
      citations have no PDF page concept), replace the whole "p.N" span with
      "L{line_index}" instead of showing "p.undefined". Do not change the
      click-to-navigate target — still opens the invoice review page; a later
      nice-to-have can deep-scroll to the rendered line-item table.

- [ ] 9. (All, final check) Run the full backend test suite
      (`cd Prod_Invoice_LLM/apps/invoice-be ; pytest tests/ -q`) and confirm no
      regressions. Run the existing chat SQL quality file specifically:
      `pytest tests/test_chat_sql_quality.py -v`. For FE: run
      `npm run lint` and `npm run build` if available (check package.json
      first). Record pass counts in the tracker update note.

## Out of scope / later

  - FE SqlAuditDrawer highlighting of the matching line inside the PDF canvas
    — nice-to-have, not a blocker for correctness; drawer already shows the
    raw SQL which includes `line_description`, so auditors can manually
    correlate.
  - Deep-linking / scroll-to-line on the invoice review page — requires the
    review page to expose line-index anchors; no such anchors exist today.
  - Trainer (EVOLVE) learning from line-item-level corrections — Tracker says
    EVOLVE only suggests rules on 3+ same-field invoice-level corrections;
    extending it to line items is a separate change.
  - Any schema/migration change — `items` JSONB already has the shape.

## Owner handoff (per CONVENTIONS.md)

  - Steps 1–6, 9: **senior-dev (BE)**.
  - Steps 7–8, 9 (FE half): **senior-dev (FE)**. Can be done in parallel with
    steps 5+9 because the FE type change is additive-only and doesn't block BE.
  - After senior-dev closes, **functional-tester** runs:
      (a) the live repro from the tracker entry (Cloud Storage + Training line,
          query "amount only for training and onboarding", assert $29,302.94);
      (b) a multi-invoice aggregation ("total spent on training across all our
          invoices");
      (c) a narrowing follow-up (per rule 9) — "show me just the ones from
          vendor X" after a line-item listing, confirm the WHERE is preserved.
    Functional-tester files to: `docs/test_coverage_map.md` and
    `docs/test_evidence/gap253_line_item_sql_2026-08-XX/` per the table in
    CONVENTIONS.md.
