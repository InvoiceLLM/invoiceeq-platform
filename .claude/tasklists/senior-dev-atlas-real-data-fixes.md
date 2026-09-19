# ATLAS — what real data exposed. Fixed as feature work, not as a gap backlog
Spec: `apps/invoice-be/docs/feature_34_atlas.md` · `apps/invoice-fe/docs/feature_23_work_screen.md`
Rulings: `atlas_discussion.md` D20, D30, D40, D41 · §1, §2.2, §5.3, §7.3, §7.5
Started: 2026-09-18
Branch: `feature/atlas`
Founder instruction: **fix these as part of the feature**, and comment the feature docs with what
real data taught. Not a separate gap-chasing pass.
Status: verification complete — 2026-09-19 (browser re-drive finished; see Final status)

## How these were found

The VPI demo tenant — 26 real invoices, real Doc Intelligence, real GPT-5.6 Luna — was loaded
locally and the work screen driven for three roles. **Every one of these passed 149 backend and
155 frontend tests.** They were found by one person looking at one screen. That is the comment
worth writing into the spec: the suite asserted payload shape, and none of it asserted what a
person actually reads.

## The five

- [x] **1. Every line renders twice.** *(done — `WorkScreen.tsx`: an area owns the lines it stands for; everything else is a plain line. Asserted by counting rendered `atlas-line` rows, collapsed and expanded.)* All 9 of 9 ids appear in `areas[].line_ids` **and** in
  `lines[]`. The screen shows "Decisions — 5 pending" and then all five beneath it. The BE is
  right to keep them (collapse **groups, never removes** — D20/D41); the FE renders both lists
  independently. **Neither side is wrong alone** — which is the exact seam FE 23 §1 exists to
  close. Fix on the FE: a line appears once, inside its area, expandable in place.
- [x] **2. Collapse fired for a solo tenant.** *(done — `capabilities_held_by_others()` replaced by `capabilities_worked_by_others()`: evidence is an `atlas_action_log` / `atlas_dismissals` row by another user on a line in that area within 7 days. `services/atlas_collapse.py`, `routers/atlas.py`.)* Every area says `reason: "someone else is working
  this"`. Nobody else is — one user, one org. D20: *"A solo owner collapses nothing, because
  nobody else is handling anything — same rule, no special case."* The predicate asks whether a
  capability **exists**, not whether another **user** holds the work. Fix the predicate.
- [x] **3. The counts are wrong.** *(done — an area counts distinct `what.entity_id` among work lines; a line whose `entity_kind` is `tenant` is a standing tile, excluded from the area entirely. Decisions now reads 2. `services/atlas_collapse.py`.)* "Decisions — 5 pending" counts `audit-cash-INR`, the cash
  position tile. That is not a decision and nothing about it is pending. Real count: 2. An area
  count must count work, not lines.
- [x] **4. BE Gap 704 — a raw Python dict on screen.** `why.doubt` on an approve line renders
  `{'id': 'ad637a2e...', 'type': 'possible_duplicate', 'message': '...'}` and `references`
  carries the UUID shredded into digit fragments (`'637','2','924','3175'...`).
  **Read why those fragments exist:** §5.3's "no undeclared number" guard was satisfied by
  **declaring the UUID's digit runs as references** rather than by not putting a dict in prose.
  The guard was laundered, not met — the failure mode hard rule 3 exists to prevent. Fix the
  source (take the alert's `message`), and make the guard reject a dict-shaped `doubt` so it
  cannot be satisfied this way again.
- [x] **5. BE Gap 705 — the forecast sums the wrong population.** The line says "committed to
  ₹5,17,146.80 across 2 invoice(s), and expecting ₹0.00 across 0". Its own `computation` strings
  admit it: *"the 2 invoice(s) **awaiting a decision**"* and *"the 0 invoice(s) **sent** and
  unpaid"*. Payables counts only invoices pending a decision; receivables counts only invoices
  taken through a manual `confirm-send`, which almost nothing has. Real figures are roughly
  **₹11L payable** and **₹34L receivable**. A CFO reads this as owing half what they owe and
  being owed nothing. §5.3 calls a wrong number the most damaging failure there is, because
  trust in numbers is binary and does not recover.

## Also fix, same pass

- [x] **6. BE Gap 706** *(done — deterministic `_ATTENTION_PATTERN` + `_ATTENTION_PREDICATE` in `link_question_to_schema()`; rule 6's `'%duplicate%'` casting example removed. Re-asked live: "Three invoices need attention", all 3 named.)* — SAGE's "which invoices need my attention" generates SQL filtering
  `sa_alerts LIKE '%duplicate%'`, so a tax-mismatch alert is structurally excluded. Returned 2
  where the README's ground truth is 3.

## Comment the feature docs (founder asked for this explicitly)

- [x] Append to **BE Feature 34** and **FE Feature 23**: *(done — BE §18, FE §16. Additive only.)* what loading real data exposed that
  every test missed, and why. Name the pattern — the suites asserted payload shape and component
  props; nobody asserted the sentence a user reads or the number they act on. Additive sections
  only (hard rule 4); do not rewrite an approved body.
- [x] Record that the VPI README *(done — BE §18.9 and the tracker; neither source document touched.)*  and `atlas_vpi_scenario_day1_30.md` describe **Feature 33**,
  which was never built (Discover, the onboarding questions, FP&A cards, `ops`/`exec` clearance).
  The demo script and the product have diverged. Flag it — do not rewrite either document.

## Verification — the bar is what a person sees, not what a payload contains

- [x] A line appears **once** on screen. Asserted by count, on a rendered screen — 9 rendered
      `atlas-line` rows for Admin (collapsed default view and after "Show everything"), 5 for
      Auditor-only, 4 for Trainer-only; no duplicates in any state. Also re-checked with a real
      colleague row present (area collapse path): 2 collapsed into the area + 5 individual
      lines, each once. Evidence: `docs/test_evidence/vpi_demo_atlas_2026-09-18/after_fixes/redrive_2026-09-19/`.
- [x] A solo tenant collapses **nothing** — Admin capture with 0 `atlas_action_log` rows shows
      zero area rows, all 9 lines flat.
- [x] An area count equals the work in it, excluding tiles like cash position — with a seeded
      colleague row, "Decisions — 2 pending" (the 2 `INVOICE_AWAITING_DECISION` lines), cash
      tile rendered separately, not counted.
- [x] No `why` field on any line contains `{'` or `':` — no structure ever reaches prose —
      `grep` across every `.txt`/`.json` capture in `after_fixes/` (root + this session's
      folder): zero matches, all three roles.
- [x] The cash line's payable and receivable figures match a direct SQL sum over the right
      population, asserted against the VPI tenant — independent SQL (not copied from the prior
      run): payable count=11 sum=1624588.6, receivable count=10 sum=4250646.0. Identical to the
      screen's "committed to ₹16,24,588.60 across 11 ... expecting ₹42,50,646.00 across 10."
- [x] "Which invoices need my attention" returns **3** on the VPI data — re-read the prior run's
      live capture (`sage_attention_answer_after.json`): NAT-2007, RAJ-2009, VPI-OUT-2014,
      matching ground truth. Not re-asked live a second time (no reason to spend another GPT-5.6
      Luna call re-proving arithmetic the capture's own `generated_sql` already shows).
- [x] BE and FE suites stay green: BE 149+, FE 155+, `tsc` clean — FE: `npm test -- --run` →
      157 passed, 4 skipped (161), `tsc --noEmit` clean. BE ATLAS-specific suite
      (`test_atlas_actions/contract/dismissals/doubt/forecast/memory/ranking/router/skills.py`):
      148 passed. **Full BE suite has 11 pre-existing failures**, none in an `atlas_*` file and
      none touched by this session's changes (none — this run made no code changes):
      `test_a3_streaming`, `test_agent_eval_multiturn`, `test_gap426_qualified_column_normalisation`
      (×2), `test_online_quality_judge` (×2), `test_rag.py` (×4), `test_sandbox_keys.py`
      (`TestChatMetering`). These are query_agent SQL-rewrite, RAG routing and sandbox-billing
      tests, unrelated to ATLAS/Feature 34 or Feature 23. Flagged to the founder in the
      hand-back; not filed as an ATLAS gap and not investigated further here — out of this
      run's scope (browser re-drive of ATLAS, not a full-suite regression hunt).
- [x] **Re-driven on the VPI tenant in a real browser**, all three roles, screenshots refiled —
      `docs/test_evidence/vpi_demo_atlas_2026-09-18/after_fixes/redrive_2026-09-19/`: admin
      (full 9-line + colleague-collapse variant), auditor, trainer, memory panel
      create/edit/hard-delete, action log Did+Refused, "you missed this" from a real invoice
      record page (not just an ATLAS line).

## Final status

Re-drive complete, 2026-09-19. All six real-data fixes (items 1–6) hold up under independent
re-verification in a real browser: one render per line, a solo tenant collapses nothing, area
counts exclude the cash tile, no dict-shaped prose anywhere, the cash line's payable/receivable
figures match a SQL sum run independently of the app, and SAGE names all three attention
invoices. Item 7 (memory panel, action log, "you missed this" from a record) all worked
end-to-end against the real backend and Postgres, hard deletes confirmed by row count. No new
ATLAS defect found this session; nothing here needed a code change. One unrelated finding
carried forward to the founder: 11 pre-existing failures in the full BE suite outside ATLAS
(query_agent SQL-rewrite, RAG routing, sandbox chat metering) — not investigated, not fixed,
flagged only. Both dev servers left running per instruction.
