# ATLAS — what real data exposed. Fixed as feature work, not as a gap backlog
Spec: `apps/invoice-be/docs/feature_34_atlas.md` · `apps/invoice-fe/docs/feature_23_work_screen.md`
Rulings: `atlas_discussion.md` D20, D30, D40, D41 · §1, §2.2, §5.3, §7.3, §7.5
Started: 2026-09-18
Branch: `feature/atlas`
Founder instruction: **fix these as part of the feature**, and comment the feature docs with what
real data taught. Not a separate gap-chasing pass.
Status: in progress

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

- [ ] A line appears **once** on screen. Asserted by count, on a rendered screen
- [ ] A solo tenant collapses **nothing**
- [ ] An area count equals the work in it, excluding tiles like cash position
- [ ] No `why` field on any line contains `{'` or `':` — no structure ever reaches prose
- [ ] The cash line's payable and receivable figures match a direct SQL sum over the right
      population, asserted against the VPI tenant
- [ ] "Which invoices need my attention" returns **3** on the VPI data
- [ ] BE and FE suites stay green: BE 149+, FE 155+, `tsc` clean
- [ ] **Re-driven on the VPI tenant in a real browser**, all three roles, screenshots refiled

## Final status

_(one line, written when the run ends)_
