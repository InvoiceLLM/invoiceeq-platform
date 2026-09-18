# Feature 34 — ATLAS: the analyst that recommends

**App:** invoice-be · **Status:** spec approved; **Slice A (tasks 34.1–34.2) built 2026-09-17 on
branch `feature/atlas`, uncommitted — see §12. 34.3–34.12 not started; 34.8 blocked on Q6.**
· lives in `be_features_tracker.md`
· **Counterpart:** FE Feature 23 (`apps/invoice-fe/docs/feature_23_work_screen.md`) — the surface.
**Supersedes:** BE Feature 33 (`feature_33_analyst_agent.md`) and, with FE Feature 23, FE Feature 22.
Both files are kept, not deleted: they hold the reasoning this spec reverses.
**Decision record:** `atlas_discussion.md` (D1–D33, Q1–Q14). Every `D##` below cites it.

**This spec owns every contract between the two apps** — payload shapes, event names, field
lists, enum values. FE Feature 23 references them and never restates them. The seam between
BE Feature 33 and FE Feature 22 is where this session's worst defects lived: a live event
promised by two specs and published by neither, a field the FE read that the BE never emitted,
capabilities in the registry that no surface emitted. One contract, one owner.

---

## 1. What ATLAS is

**A guide that sits beside each role.** It notices, recommends the next action, explains why,
does it on one click, and teaches the person to verify it themselves (D7).

It is **not** an automation engine. It does not act on its own (D8). It does not produce
reports (D15, D16). Its output is not findings — it is **recommendations**.

**Every line ATLAS produces carries four things** (D7). A line missing any of them is a defect:

| | |
|---|---|
| **What** | the invoice, the alert, the correction |
| **Why** | the reason in the user's terms — "this vendor has never billed above ₹20,000" |
| **Action** | a single click, batchable when certain |
| **Verify** | opens chat with the document attached and the question pre-seeded |

**Why the fourth matters.** Trust is not built by telling a user ATLAS is reliable. It is built
by letting them check it once, cheaply, on the line in front of them. A user who verifies once
in their first session relates to ATLAS differently from one who was told to trust it (D24).

**The completeness test for "why":** if a user has to go and look something up to judge the
line, the line was incomplete. "4× their usual ₹40–60k" *is* the history (D33).

---

## 2. Who each line is for

### 2.1 Capability, not clearance

The `ops` / `exec` clearance binary is **removed** (D1). It was one line —
`clearance = "exec" if role == "Admin" else "ops"` — and it collapsed a four-flag permission
model into Admin-or-not, so Trainer, Auditor and no-role users received byte-identical screens.

**Every recommendation declares the capability required to act on it.** The work screen filters
on that. The existing flags are the model:

| Grant | Sees |
|---|---|
| `can_audit` | invoices to approve / reject / query · payment mismatches · duplicates · amount discrepancies · **outbound to send or chase** (D6) |
| `can_train` | extraction wrong · vendor unmapped · rule misfiring · low-confidence fields |
| `can_load` | missing documents · failed uploads · unreadable scans · connector errors |
| Admin only | cash position · forecast · runway · FP&A (D2) |
| no grants | nothing. "No tasks assigned" (D3) |

**Grants stack.** `can_audit` + `can_load` produces one merged list, not tabs — filtering is
per line, so this needs no special handling.

**D3 is about grants, not roles.** A user with no assigned role but `can_load` granted is a
Loader and sees document work. Only genuinely ungranted users get the empty state.

**`can_send_invoices` folds into `can_audit`** (D6). This reverses BE Gap 405, which defaulted it
False for every role on least-privilege grounds. Deliberate, recorded, not drift. The DB column
may stay; ATLAS stops treating it as a separate audience.

### 2.2 Assignment and collapse

**Work is assigned, not only filtered.** A line belongs to whoever holds the capability. It
returns to the Admin only when it goes unhandled.

**The Admin is the superset** — every line type, nothing withheld. But items another
grant-holder is actively working **collapse to one row per area** (D20):

> Corrections — 34 pending, 3 untouched for a week.

Openable for the full list. **Coverage is total; volume is not.** A solo owner collapses
nothing, because nobody else is handling anything — same rule, no special case.

### 2.3 Per-role substance

| Role | ATLAS provides |
|---|---|
| **Admin** | Four needs and no others (D14): **don't lose money** · **don't run out** · **don't let it stall** · **keep the setup right**. If a line maps to none of the four it is analytics, not work |
| **Auditor** | Routine grouped for one approval · what is odd and why · **the document that settles it** (§4) · **the cash consequence of saying yes** — "approving this commits ₹2.4L on the 20th, when you are already tight" |
| **Trainer** (D21) | Fixes **ranked by consequence** ("fixes 60 invoices a month" vs a one-off) · the correction **already drafted** · **proof the teaching worked** · **bad rules surfaced**, not only missing ones |
| **Loader** (D22, D13) | **Stuck vs in flight** · why it failed **and the fix**, not the fault · **what should have arrived and didn't** · the way out of the job. **The role is designed toward elimination** |

**The Auditor's cash line is bounded.** "This commits ₹2.4L on the 20th, and the 20th is tight"
is decision context and theirs. "You have six weeks of runway" is company health and the
owner's. Same forecast, different question asked of it.

---

## 3. Skills

### 3.1 What changes

Feature 33 shipped 16 capabilities: 10 read, 6 action. **Seven of the ten reads are CFO
analytics.** There is no Auditor skill and no Trainer skill — which is why those roles'
lists were thin. Not a filtering bug; an empty skill set.

| | |
|---|---|
| **Keep on the screen** | `forecast_cashflow`, `detect_recurrence` (D16) |
| **Move off the screen** | `pnl_by_period`, `margin_per_customer`, `margin_per_item`, `budget_variance_per_account`, `expense_category_trend`, `forecast_scenario` — asked for in chat, never shown unprompted. **Not deleted** (D16) |
| **Build** | Auditor skills · Trainer skills · Loader skills · **reconciliation** (D18) |

Every skill declares the capability required to act on its output (§2.1).

### 3.2 Reconciliation (D18)

There is no recon capability among the 16. The plumbing exists; nothing exposes recon as
something ATLAS offers to do.

| Recon | Note |
|---|---|
| **Vendor statement vs ledger** | **First to build.** Attach the statement in chat → matched · they show and we do not · we show and they do not · amount differs |
| Bank vs invoices | Payment with no invoice; invoice paid with no payment |
| **Short payments** | ₹48,000 against ₹50,000 — **name the likely reason** (TDS, early-payment discount, disputed line), do not just flag a gap |
| Lump-sum receipts | One payment covering six invoices — propose the allocation, confirm |
| Three-way match | Invoice vs PO vs delivery note |

**Why recon before anything else:** it is work a person is definitely doing today, by hand, on
a schedule, with documents they already hold, and it has a definite answer.

### 3.3 The claim → witness rule (D19)

Every invoice makes claims; each claim has exactly one external witness.

| The invoice claims | Only this settles it |
|---|---|
| "the rate is ₹1,200/unit" | the quotation or contract |
| "you ordered 200 units" | the purchase order |
| "we delivered them" | the delivery note / GRN |
| "you have not paid" | the bank statement |
| "your balance is ₹4.2L" | the vendor statement |

**ATLAS never asks "shall we reconcile."** The ask is always: a specific claim is in doubt, and
one document settles it. The decision rule, in order:

1. **Is a claim in doubt?** Outside the vendor's historical range · first invoice from a new
   vendor · rate changed · possible duplicate · large enough to matter
2. **Do I already hold the witness?** If yes — **check silently, say nothing unless it disagrees**
3. **If not — is the answer worth the interruption?** ₹2.4L at 4× normal: ask.
   ₹4,500 matching twelve months of history: never ask

**Step 2 is what stops it nagging.** Most checks happen invisibly; the user hears only failures.

**Anti-pattern:** asking for documents on a schedule, at onboarding, or per invoice. That turns
ATLAS into a form. The ask must be earned by a specific doubt and **must carry its reason**, or
the user cannot judge whether attaching the document is worth two minutes.

**This needs something that does not exist:** invoices carrying checkable assertions — rate,
quantity, period — not just extracted field values, plus a vendor baseline to deviate from (Q10).

---

## 4. Hooks (D23)

Feature 33 has **two entry points total**: a weekly cron and `POST /today/run`. ATLAS never
wakes when an invoice arrives, a payment lands, extraction fails or a due date passes. It is a
batch job with a manual override, and a batch job cannot keep a work screen true.

Three triggers, three mechanisms:

| Trigger | Mechanism |
|---|---|
| **Something happened** — document arrived, payment landed, extraction finished, statement imported | Event. Run the **cheap checks** immediately, stop |
| **Something did not happen** — the vendor did not bill, the queue has not moved, ingestion stopped | **A clock. No event fires for absence** — and this is the highest-value category in every role |
| **Someone showed up** | Recompute the **expensive** work — forecast, ranking, recon — on arrival |

A customer who does not sign in for a week costs almost nothing; one who signs in daily gets a
current screen rather than a Monday batch.

---

## 5. Trust, and being wrong

### 5.1 Uncertainty (D26)

**Stated in words, never a number, and never batched.**

> This might be a duplicate — same amount and vendor, different invoice number.

"87% confident" is meaningless to a finance user. **Batching is a claim of certainty**, so only
confident items may be batched; anything uncertain gets its own line with the doubt in words.

### 5.2 The five failure modes

| Failure | Cost |
|---|---|
| **False positive** | Cheap individually. In aggregate it kills the product — a user who dismisses twenty flags dismisses the twenty-first unread, and that is how the real one is missed |
| **False negative** | Real money, and **invisible**. No feedback, no correction, no signal (Q13) |
| **Wrong recommendation, accepted** | The dangerous one — the batch click *means* the user delegated judgment |
| **Wrong number** | The most damaging. **Trust in numbers is binary and does not recover** |
| **Right flag, wrong reason** | Erodes credibility quietly, and is visible without anyone clicking |

**The asymmetry:** false positives are visible and self-correcting; false negatives are invisible
and permanent. The bias therefore **depends on the stake** — a wasted minute costs the same at
any amount, a miss scales with the money (Q14).

**After being wrong:** acknowledge plainly and stop. *"You were right — I flagged that wrongly
and I will not again."* Not an apology, an adjustment. The dismissal feeds §7.

### 5.3 Boundaries (D28, D29)

These are what make one-click acceptance safe. Without them, D8 is a faster way to make mistakes.

**ATLAS never:**

- **Moves money.** No payment initiation, ever — not with approval, not with configuration.
  ATLAS prepares the decision; a human executes it in their banking system.
  **The worst outcome of an ATLAS error is a wrong record, never a wrong transfer**
- **Sends outside the company unseen.** Every outbound message is **read in full and sent
  individually** — including every chase email. A wrong email costs a relationship, and the
  draft already removed the expensive part
- **Deletes.** Not records, not documents, not history. Propose, mark, hide — never remove
- **Invents a number.** Every figure traces to a document or a computation. If the invoice says
  ₹2,41,300, ATLAS says ₹2,41,300 — never "about ₹2.4 lakh". **The easiest rule to break by
  accident, because prose comes from a model and models round**
- **Writes silently.** Every write is visible, attributed and timestamped. "What ATLAS did" is a
  real list
- **Claims certainty it lacks** (§5.1)
- **Learns a permanent rule from one instance.** One dismissal is noise; forty are a pattern

**The organising principle (D29), which decides every future case without a new ruling:**

> **Reversible may be batched. Irreversible is individual. Anything leaving the company is
> individual and read in full.**

**Q6 gates this:** if it cannot be undone as a batch, it cannot be accepted as one.

---

## 6. Notifications (D27)

**The wrong test is "is this important."** Most of the screen is important.
**The right test is: is there a window, and is it closing?**

A duplicate matters *before* the payment run; afterwards it is a recovery problem costing ten
times more. So **notify when action is still possible and the window is closing — not when
ATLAS noticed.** Discovery time and notification time are different things, and conflating them
produces alerts nobody can act on.

**Two tiers, and resist a third:** a rare urgent interrupt, and an optional digest.

**ATLAS caps its own interrupts.** If five qualify in a day it sends the two that genuinely
cannot wait. An urgent channel that fires often stops being one — and once muted, the one that
mattered is gone too. **Self-limiting is the feature.**

**The notification carries the decision, not a summons.** Never "you have a new finding, log in"
— that spends the interruption and delivers nothing.

> ₹47,000 to Kumar Supplies looks like a duplicate of #1041 paid on the 3rd.
> Your payment run is tomorrow.

**Escalation** is the notification form of D20: the grant-holder is notified; after a delay the
Admin is, because "nobody is doing this" is an Admin problem (Q12). Channel is Q11.

---

## 7. Cold start, memory, ranking, scope

### 7.1 Cold start (D24, D25)

**The trap:** almost everything here needs history — vendor baselines, payment behaviour,
recurrence, dismissals. So ATLAS's first month is its weakest, and that is the month a customer
decides whether it was worth buying.

**Day one is comprehension, not findings.** Teach the working relationship per role, not the
screens (FE Feature 23 §5 renders this):

1. **What your job looks like with ATLAS** — per role, in their terms
2. **How to verify me** — *"attach the document and ask 'is this right?' — I will show you
   exactly what I compared. Try it on this one now."*
3. **What I will be able to do as I learn** — *"right now I do not know your vendors, so I cannot
   tell you ₹2.4L is unusual. In a month I will. In three months I will know who pays late and
   forecast around behaviour rather than due dates."* A stated plan, not a disappointment

**Teach once, then keep teaching in place** (D25) — capabilities are explained the first time
they become relevant, never dumped on day one.

**What day one finds with zero history:** arithmetic (line items not summing, tax on the wrong
base), validity (malformed GSTIN, due date before invoice date), duplicates within the batch,
and cross-document matching within the batch.

**The historical import is an offer, never a gate:** *"If you have last year's bank statements I
can check them now — I usually find a duplicate payment or two, and it teaches me your vendors
much faster."* Reconciling the past produces real findings in the first session **and silently
builds every baseline**.

### 7.2 Memory (D31)

**Everything ATLAS learns becomes a visible, editable rule in plain language** — whether it came
from a direct answer, a dismissal, a correction or something said in chat. This follows from
never-write-silently: if ATLAS believes something about the business, the user can read it,
change it or delete it. **A wrong lesson that cannot be found haunts the system forever.**

### 7.3 Ranking (D30)

**Money at stake × how soon it stops being fixable** — §6's test applied to the screen. A ₹2.4L
duplicate before tomorrow's payment run beats a ₹4,000 one from last month. Everything below the
cut stays reachable. **ATLAS ranks; it does not hide.** (Q5: where a list becomes a queue.)

### 7.4 Scope (D32)

**Multi-currency, single entity.** Cash and forecast are **per currency, never blended** — a
mixed-currency total is a wrong number under §5.3. No entity switcher.

### 7.5 Forecast (D15)

**A warning with levers, never a chart.** *"On the 22nd you are ₹1.2L short — chasing these two
invoices covers it, or delaying this payment covers it, or it resolves itself if Sharma pays on
time."* A date, a number, and actions.

Four things forecastable from data already held:

1. **What will actually arrive, not what is due.** Forecasts are wrong because they treat due
   dates as real. A customer who pays 12 days late every time is knowable. **A forecast built on
   promised dates is fiction.** Highest-value item here
2. **What is coming that nobody typed in** — rent, insurance, subscriptions
3. **Where costs are drifting** — vendor price rises compounding quietly
4. **The shortfall with its levers**

**The forecast states its assumption.** On-time payment and historical behaviour are different
numbers, and a user making a decision needs to know which they are looking at. **Deterministic
and honest are separate properties;** Feature 33's forecast is the first and silent on the second.

---

## 8. What Feature 33 loses

| Removed | Why |
|---|---|
| `ops` / `exec` clearance | D1. `services/clearance.py`, the rank comparison, the stream filter, the column's meaning on six tables (Q3: whether the columns are dropped) |
| The dual analyst run | D1. One run per tenant — halves analyst LLM cost |
| Non-actionable lines | D4. The `actionable` flag, the server-side splice into `findings`/`summary` |
| `ScenarioControl` on the screen | D5 |
| The upfront questionnaire | D17 — never ask before the data shows it |
| Private sessions / `clearance="exec"` chat | D1 |
| `can_send_invoices` as its own audience | D6 |

**Resolved by removal:** BE Gaps 629, 640, 647, 649, 651, 657, 661, 665 are all defects in
mechanisms this spec deletes.

> **Added 2026-09-17 at the start of the Slice A build — this whole section is a no-op, and the
> table above is kept as written because it records the reasoning.** Feature 33 was never
> implemented. There is no `services/clearance.py`, no `agents/atlas_prompts.py`, no
> `services/analyst*`, no `routers/today.py`, no capability registry and no `AnalystScope`
> anywhere in `apps/invoice-be` (repo-wide grep over `*.py` for `ATLAS|analyst|AnalystScope|/today`
> hits only `benchmarks/extraction/*`, `routers/dashboard.py` and
> `scripts/run_extraction_benchmark.py`, all unrelated). So there is no clearance service to
> delete, no dual analyst run to halve, no `actionable` flag to remove and no `ScenarioControl` to
> take off a screen that does not exist. **Task 34.1's "remove clearance" half is satisfied by
> never building it** — see §12. By the same finding, §3.1's "keep 2, move 6 off screen, build the
> rest" reduces to *build all of it*: the 16 capabilities it describes are not in the repo either.

**The loop itself.** `observe → plan → act → investigate → say → ask → learn` is shaped to
produce a *report*: gather, analyse, narrate, ask, record. The job here is
**notice → recommend → explain → offer → verify → learn**. `investigate` and `say` exist to make
prose; `plan` exists because the model chooses its own steps. Neither is obviously needed when
the output is "approve these 8, here is why." **Scope this before rewriting it.**

---

## 9. Open questions

| id | Question | Blocks |
|---|---|---|
| Q5 | Where does a list become a queue? Customers run ~20/month to thousands | §7.3 |
| **Q6** | **How is a batch acceptance undone?** | **§5.3, and D8 cannot ship without it** |
| **Q7** | `uq_autopilot_config_tenant` is UNIQUE on `tenant_id` — **one ingestion source per tenant** | **D13 / §2.3 Loader** |
| Q10 | What is a "claim" concretely, and where does the vendor baseline live? | §3.3 |
| Q11 / Q12 | Notification channel; escalation delay | §6, deferred |
| **Q13** | **How is a false negative ever detected?** No feedback loop exists | §5.2. The hardest question here |
| Q14 | The stake floor below which ATLAS stays quiet when uncertain | §5.1 |

---

## 10. Tasks

To be numbered once Q6 and Q7 are answered. Ordered by dependency:

1. Capability declaration on every recommendation; remove clearance (§2.1, §8)
2. The recommendation contract — what / why / action / verify (§1) — **owned here, consumed by FE 23**
3. Auditor skills · Trainer skills · Loader skills (§3.1)
4. **Vendor statement recon** (§3.2) — first recon, and the first thing a customer will value
5. The claim → witness rule and the vendor baseline (§3.3, Q10)
6. Hooks: events, the absence clock, on-arrival recompute (§4)
7. Assignment, collapse, escalation (§2.2, §6)
8. Batch accept + undo (§5.3, Q6)
9. Forecast as a warning with levers, stating its assumption (§7.5)
10. Memory as visible editable rules (§7.2)
11. Notifications (§6)
12. Cold-start orientation content per role (§7.1)

---

## 11. Verification plan

Per repo hard rule: **real Postgres at `localhost:5433/invoice_db`, never SQLite.** BE Gap 666
is the standing warning — a skip guard reading an env var the app never exports hid 23 tests
behind a green report, so every guard in new tests reads `get_settings()`.

Each task states its invariant as a sentence and turns that sentence into a test. Tests span
**two runs, or a run plus a request** — the six semantic collisions in this session's parallel
work were all invisible to single-run tests.

Specific invariants worth naming now:

- A user with no grants receives **zero** lines (§2.1)
- A line whose capability the user lacks is **absent**, not disabled (§2.1)
- An uncertain recommendation is **never** in a batch (§5.1)
- No response blends currencies (§7.4)
- Every figure in a rendered line appears verbatim in a document or a computed value (§5.3)
- An outbound message cannot be sent by a batch endpoint (§5.3)

---

## 12. As built — Slice A (2026-09-17)

**Additive record, not a replacement for §1–§11.** Branch `feature/atlas`, uncommitted. Tasks
34.1 and 34.2 only; 34.3–34.12 are not started and **34.8 does not start** — it is blocked on Q6,
and D8 cannot ship without it. Tracker entry: `be_features_tracker.md`, Feature 34, marker `[~]`.

### 12.1 Files

| File | Task | What it holds |
|---|---|---|
| `services/atlas_capabilities.py` | 34.1 | `AtlasCapability`, `GrantSet`, `CapabilityDeclaring`, `visible_to()` |
| `services/atlas_contract.py` | 34.2 | `Recommendation` and its four parts, `Figure`, the enums, the six assertions |
| `tests/test_atlas_contract.py` | both | 31 tests; every §11 invariant, plus grant resolution from real `users` rows |

No migration. Slice A persists nothing — the skills that emit recommendations are 34.3–34.5 —
and a table with no writer would be speculative.

### 12.2 The wire contract

**Owned here; FE Feature 23 consumes these names and never restates them.**

```
Recommendation
  id           str
  capability   "audit" | "train" | "load" | "admin"
  skill        str
  what         { headline, entity_kind, entity_id }
  why          { text, figures[], references[], doubt? }
  action       { kind, label, target_id, params }
  verify       { question, document_id? }
  certainty    "certain" | "uncertain"
  reversibility "reversible" | "irreversible" | "leaves_company"
  currency     ISO 4217, uppercase
  batchable    bool — COMPUTED, read-only

Figure  { rendered, value, currency, source: "document"|"computed",
          document_id?, quote?, computation? }
```

Three shapes that are deliberate and would otherwise look like omissions:

- **`Action` carries no URL.** `kind` is what the FE dispatches on; the endpoint is declared by
  the skill that emits the line, in Slice B. Declaring routes now would be inventing them, and
  "a field the FE reads that the BE never emits" is the exact defect class this spec's header
  exists to end.
- **`batchable` is computed, never supplied** — `certainty is CERTAIN and reversibility is
  REVERSIBLE`. Batching is a claim of certainty (§5.1, D26) and a batch click means the user
  delegated judgment (§5.2), so the claim cannot be an emitter's to make.
- **There is no confidence number and no `actionable` flag.** §5.1 and D4 respectively.

### 12.3 The capability declaration (34.1)

`AtlasCapability` is `audit` / `train` / `load` / `admin` — a closed set, **never a rank**. The
grants are the real Feature 1.1 / Gap 73 columns; `GrantSet.from_user()` goes through
`RoleMapper.resolve_permissions()`, the same call a request makes, so a grant resolved for an
ATLAS line and one resolved for an API route cannot disagree.

- **Absent, not disabled** (§2.1): `visible_to()` drops lines, never annotates them. A greyed-out
  row still leaks the vendor, the amount and the fact that something is wrong with it.
- **Zero grants, zero lines** (D3) falls out of the per-line test; it is not special-cased. D3 is
  about grants, so a no-role user with `can_load` is a Loader.
- **`can_send_invoices` has no field on `GrantSet`** (D6). An unused field is an invitation to
  branch on it; the column keeps its meaning for the Feature 2.1 / 7.1 outbound surfaces, and
  ATLAS simply stops treating it as an audience.
- **Clearance is removed by never being built** — see §8's 2026-09-17 note. No `ops`/`exec` value
  exists in the vocabulary, asserted by a test rather than left to reviewer memory.
- `is_admin` is carried beside the three flags, not derived from them: §2.2's superset ("every
  line type, nothing withheld") is a different question from any one grant, and D2's Admin-only
  cash/forecast/runway/FP&A audience is what `AtlasCapability.ADMIN` is for. Volume is reduced by
  the collapse rule (D20, task 34.7); coverage never is.

### 12.4 The boundaries as code, not prompt rules (§5.3)

CONVENTIONS hard rule 3 — anything deciding correctness is deterministic code:

| Boundary | Enforcement |
|---|---|
| Never invents a number | `assert_no_undeclared_numbers()` — every money-shaped token in *any* rendered string must be a declared `Figure.rendered` or a declared reference · `assert_figures_are_witnessed()` — a declared figure must actually appear, so declaring cannot become a way to widen the whitelist · `Figure`'s own validator — a DOCUMENT figure must occur verbatim in its quote, a COMPUTED figure must name its computation |
| Never blends currencies | `assert_single_currency()` per line · `sum_figures()` raises across currencies instead of returning a plausible wrong total |
| Never claims certainty it lacks | `Certainty.UNCERTAIN` requires `why.doubt` in words; `CERTAIN` forbids it |
| Reversible may be batched | `batchable` computed; `assert_batch_acceptable()` is the one guard a batch endpoint calls |
| Anything leaving the company is individual | `Reversibility.LEAVES_COMPANY` never batches, even when certain — a chase email cannot reach a batch through a future emitter's mistake |

**"Money-shaped" is defined, not guessed:** a number counts as a figure when a currency mark
precedes it, or it carries a grouping separator or decimal point, or it is four or more digits.
"the 20th", "12 days late" and "fixes 60 invoices a month" are prose a recommendation is supposed
to contain; forcing each through a `Figure` would make the rule noisy enough that emitters route
around it, which is how a control stops being one. Invoice numbers and GSTINs go in
`why.references` — identifiers, not figures.

### 12.5 Verification

`31 passed` against real Postgres at `localhost:5433/invoice_db` (hard rule 2):

```
DATABASE_URL="postgresql://postgres:localpassword123@localhost:5433/invoice_db" \
  ./.venv/Scripts/python.exe -m pytest tests/test_atlas_contract.py -rs -v
```

All six §11 invariants are covered. One is covered with a caveat worth stating plainly: **"an
outbound message cannot be sent by a batch endpoint" is asserted against `assert_batch_acceptable`,
because there is no batch endpoint** — 34.8 is blocked on Q6. The guard is proven; the endpoint
that must call it does not exist yet, and this line must be re-verified end-to-end when it does.

**BE Gap 697 filed from this run.** One run of the file reported `31 passed`; an immediate re-run
reported the single Postgres test SKIPPED on a transient `::1` connection error, on the same
healthy container. The copied fixture shape in 31 test files turns "Postgres did not answer" into
a green report — BE Gap 666's failure mode. The new file's fixture retries once and then fails
rather than skipping; the other 31 files are untouched and out of this feature's scope.

### 12.6 What Slice A deliberately does not do

Ranking (§7.3), the absence clock (§4), assignment and collapse (§2.2 / D20), memory (§7.2),
notifications (§6), forecast levers (§7.5) and every skill (§3) are Slices B and C. Nothing here
emits a recommendation yet — this is the contract those emitters are written against, so that the
F33/F22 seam (a field one side reads and the other never sends) cannot recur.

---

## 13. Rulings — 2026-09-17. Every open question closed

**§9's table is closed and §10's task list is superseded by §13.3 below.** Neither is
rewritten: they hold the reasoning that produced the questions. Decision ids are
`atlas_discussion.md` D34–D46.

### 13.1 The rulings

| § | Was open | Ruled |
|---|---|---|
| §2.3 | Q1 — does the Auditor see that cash is tight? | **Yes — the full position, forecast and runway.** D44 **reverses D2 for the Auditor**. The bounded cash line (consequence without position) is removed: one forecast, one view of it. FP&A and margin analytics are unaffected and stay chat-only (D16) |
| §2.1 | Q2 — does BE Gap 665's tenant-wide record access stand? | **It stands** (D45). Lookup is a search box, not a permission system (D33). **Plus a new requirement:** a Trainer's correction line shows the invoice **before and after** the fix |
| §8 | Q3 — drop the `clearance` columns or leave them? | **Moot.** No `clearance` column exists in `models.py` or any migration |
| §7.3 | Q5 — where a list becomes a queue | **Collapse by area above a threshold** (D41), reusing §2.2 / D20's existing mechanism, expanding in place. No queue mode, no second concept |
| §5.3 | Q6 — how a batch acceptance is undone | **Nothing is batchable in v1** (D42). Individual accept only; batch accept and undo deferred until usage shows which line types are safe. **Narrows D8**; D29 governs when batching returns |
| §2.3 | Q7 — one ingestion source per tenant | **Many sources per tenant** (D43). Drop `uq_autopilot_config_tenant`; ingestion paths carry a source id. **Unblocks D13** |
| — | Q8 — `ENABLE_ANALYST_ACTIONS` defaults False | **Moot.** No such flag exists in the codebase |
| §4 | Q9 — per-event, or recompute on sign-in? | **Everything computes on open** (D38). **Reverses D23** — no event hooks, no absence clock, no cron |
| §3.3 | Q10 — where claims and the vendor baseline live | **Derived at check time** (D39). No new tables. The line **shows its own working** (D40) |
| §6 | Q11 — which channel carries the urgent tier | **No channel. ATLAS speaks only when the app is opened** (D36). **Reverses D27** |
| §6 | Q12 — escalation delay | **No escalation** (D37). §2.2 / D20 already makes the Admin the superset |
| §5.2 | Q13 — how a false negative is detected | **The user reports it** (D34) — a "you missed this" affordance feeding §7.2's memory. Under-reporting explicitly accepted |
| §5.1 | Q14 — the quiet-when-uncertain floor | **No floor** (D35). Never suppress on amount; §7.3's ranking pushes small uncertain items down, reachable |

### 13.2 What this removes from the spec

- **§6 in almost its entirety**, and task 34.11 with it. There is no notification, no channel,
  no urgent tier, no digest, no interrupt cap and no escalation. D27's reasoning is kept in the
  decision record because it is the argument that would have to be beaten to bring push back.
- **§4's event hooks and absence clock.** Task 34.6 collapses to a sign-in recompute. Absence —
  the vendor who stopped billing, the queue that stopped moving — is a **query run on open**,
  not a clock. It is still built; it just has no independent trigger.
- **§5.3's batch endpoint**, task 34.8, off the critical path entirely.
- **§2.3's bounded Auditor cash line**, per D44.

**Twelve tasks become nine.**

### 13.3 The task list, revised

Slice A (34.0–34.2) is built — see §12. What remains:

| # | Task | Changed by |
|---|---|---|
| 34.3 | Auditor · Trainer · Loader skills (§3.1) — **the Auditor's lines carry the full position** (D44), **the Trainer's carry before/after** (D45), **the Loader's are per ingestion source** (D43) | D43, D44, D45 |
| 34.4 | Vendor statement recon (§3.2) — unchanged, and still the first thing a customer will value | — |
| 34.5 | The claim → witness rule (§3.3) — **claims and baseline derived at check time** (D39), **each line showing its working** (D40) | D39, D40 |
| 34.6 | ~~Hooks: events, the absence clock, on-arrival recompute~~ → **recompute on sign-in.** Absence is a query, not a clock | D38 |
| 34.7 | Assignment and collapse (§2.2) — **escalation removed** (D37); collapse also serves §7.3's volume threshold (D41) | D37, D41 |
| ~~34.8~~ | ~~Batch accept + undo~~ — **not built in v1** | D42 |
| 34.9 | Forecast as a warning with levers, stating its assumption (§7.5) — **visible to Auditors too** (D44) | D44 |
| 34.10 | Memory as visible editable rules (§7.2) — **bounded by D40**: derived observations show their working rather than becoming stored rules | D40 |
| ~~34.11~~ | ~~Notifications~~ — **not built.** ATLAS speaks only on open | D36 |
| 34.12 | Cold-start orientation per role (§7.1) — unchanged | — |
| **34.13** | **New:** drop `uq_autopilot_config_tenant`; ingestion paths carry a source id | D43 |
| **34.14** | **New:** the "you missed this" affordance on any record, feeding §7.2's memory | D34 |

### 13.4 Consequences accepted, not overlooked

Three were put back to the founder as risks and accepted as stated. They are recorded here so
that nobody later reads them as oversights:

1. **A derived baseline cannot be corrected** (D39 vs §7.2). Answered by D40 — the line states
   its basis, "4× their usual ₹40–60k across 14 invoices". Provenance without persistence, which
   §12's contract already carries as a COMPUTED `Figure` with its `computation` named.
2. **Absence is noticed only when someone signs in** (D46). A vendor who stops billing goes
   unnoticed until a visit. Accepted as the same trade D36 already makes — a user who does not
   open the app cannot be told anything.
3. **A user-reported miss under-reports badly** (D34). The miss rate stays unknown, including
   whether it is worsening. Accepted: getting better matters more than measuring, and a reported
   miss names a real pattern that then protects every future invoice.

### 13.5 What is still unknown

Nothing in the design register. The two remaining unknowns are build-time and will be answered
by measurement, not by ruling:

- the volume threshold at which D41's collapse-by-area kicks in;
- whether D39's check-time derivation is fast enough for a customer with thousands of invoices,
  given D38 puts every computation on the sign-in path.

---

## 14. As built — Slice B (2026-09-17)

**Additive record, not a replacement for §1–§13.** Branch `feature/atlas`, uncommitted. Tasks
**34.13, 34.3, 34.4 and 34.5** in that order. Slice C (34.6, 34.7, 34.9, 34.10, 34.12, 34.14) is
not started; **34.8 and 34.11 are not built at all** (D42, D36) and nothing in this slice contains
a skeleton of either — there is no batch endpoint and no notification channel.

### 14.1 Files

| File | Task | What it holds |
|---|---|---|
| `alembic/versions/a1b2c34d13e5_atlas_many_ingestion_sources.py` | 34.13 | Drops `uq_autopilot_config_tenant`; adds `tenant_autopilot_logs.source_config_id` + its index; adds `UNIQUE(tenant_id, source_type, source_ref)` |
| `models.py` | 34.13 | `TenantAutopilotConfig.__table_args__` and `TenantAutopilotLog.source_config_id` match the migration |
| `services/autopilot_sync.py` | 34.13 | `list_ingestion_sources()`, `run_sync(config_id=…)`, `run_sync_all_sources()`, per-source watermark, `_write_log` stamps the source |
| `routers/autopilot.py` | 34.13 | `POST /autopilot/sync` covers every source |
| `services/atlas_figures.py` | 34.3–34.5 | The one place a number becomes a rendered string: `render_amount`, `computed_figure`, `document_figure`, `integer_multiple`, `count_reference` |
| `services/atlas_skills.py` | 34.3 | `auditor_lines`, `trainer_lines`, `loader_lines`, `cash_position`, `atlas_lines` |
| `services/atlas_recon.py` | 34.4 | `StatementLine`, `LedgerLine`, `reconcile()`, `ReconResult`, `recon_recommendations()` |
| `services/atlas_doubt.py` | 34.5 | `ClaimKind`, `Witness`, `CLAIM_WITNESS`, `claims_for_invoice`, `vendor_baseline`, `witnesses_held`, `doubts_for_invoice`, `doubt_recommendations` |
| `tests/atlas_pg.py` | all | One Postgres guard for the whole slice (BE Gap 697's rule: fail, never skip, on a configured-but-unreachable Postgres) |
| `tests/test_atlas_skills.py` · `test_atlas_recon.py` · `test_atlas_doubt.py` · `test_atlas_ingestion_sources.py` | 34.3–34.5, 34.13 | 34 new tests |

**No new tables.** D39 is honoured literally: claims and vendor baselines are derived when a check
runs and thrown away. The only schema change in the whole slice is 34.13's, which the rulings
required.

### 14.2 34.13 — many ingestion sources (D43)

`uq_autopilot_config_tenant` is dropped. What replaces it is narrower and is the part that was
actually load-bearing: **`UNIQUE(tenant_id, source_type, source_ref)`** — the same folder may not
be registered twice, because that would double-ingest every file in it. No existing row can
violate it, since the dropped constraint guaranteed at most one row per tenant.

Three consequences were found and handled rather than discovered later:

1. **The incremental watermark had to become per source.** It filtered on `source_type`, so with
   two Drive folders a success against folder B would move folder A's `since` forward and every
   file added to A before that instant would never be listed again — a silent, permanent miss.
   It now filters on `source_config_id`. **Legacy rows (`source_config_id IS NULL`) are
   deliberately not counted for any source:** the cost is one full re-list on the first run after
   the migration, where both dedup layers already stop a re-import; the cost of claiming them
   would be the silent miss.
2. **`run_sync_for_all_due_tenants` was already looping per config row but called
   `run_sync(config.tenant_id)`**, which re-resolved to the tenant's *first* config. Correct while
   a tenant had one source; with two it would sync the first twice and the second never. It now
   names the source it is iterating.
3. **Retention (`prune_autopilot_history`) deletes tenant-wide** while each source carries its own
   `history_retention_days`. It now makes one pass per tenant at the **longest** of that tenant's
   windows: retention is a floor, and a shorter window on one source must not delete history
   another source is still keeping.

**`GET`/`PUT /autopilot/config` are unchanged and still single-source** (`.first()` / upsert). That
is the boundary of this task, stated rather than hidden: the backend supports many sources and the
settings surface that would let a user *add* a second one is FE work. `POST /autopilot/sync` does
cover every source, because a Sync Now that silently checked one of them would be a button that
lies about what it did.

### 14.3 34.3 — the three skill sets

**The Auditor (D44).** `auditor_lines()` emits the invoices awaiting a decision and then the cash
picture: `cash_position()` returns one `CashPosition` per currency carrying balance, payables due,
receivables due, the projection and `runway_days`. The whole of D44's reversal of D2 is one word —
these lines declare **`AtlasCapability.AUDIT`**, so an Auditor receives them and the Admin still
does as the superset (§2.2). FP&A and margin analytics are not here; they stay chat-only (D16).
The forecast **states its assumption** on the line (§7.5) and the assumption is due dates, said
plainly, because §7.5's behaviour-based forecast is task 34.9 and claiming its accuracy from a
due-date sum would be §5.2's "right flag, wrong reason". `runway_days` is `None` when it cannot be
computed rather than a large number, because "unknown" and "comfortable" must not render the same.

**The Trainer (D45).** Two line types. A **drafted correction** where the invoice's own arithmetic
disagrees with its total — the line items, plus tax, less discount — carrying the new
`Correction` block with `before_rendered` and `after_rendered`. And a **low-confidence field**
line, which carries **no** `Correction` at all: there is no computable "after", and an invented one
would be the worst possible number to print, since it is the value the click writes. Consequence
ranking (D21) is applied as ordering — the vendor ATLAS sees most often first — not as a score on
the line, because §7.3's ranking belongs to task 34.9.

**The Loader (D43).** Per ingestion source, and each line names its source: files that failed with
**the fix, not the fault** (`_FIX_FOR_ERROR`, matched on the error text ingestion actually
records), and a source that **has gone quiet**. Absence is a query run on open (D38) — two
timestamps compared at read time, no clock anywhere in the module — and D46's accepted cost stands.
Stuck-vs-in-flight is deliberately **tenant-wide, not per source**: an invoice reaches a tenant
through any door, so attributing a stuck invoice to a source would be a guess.

### 14.4 34.4 — vendor statement recon

`reconcile()` is the comparison and it is ordinary `Decimal` arithmetic (hard rule 3): every
statement row lands in exactly one of **matched · they show and we do not · we show and they do
not · amount differs**, plus `unmatchable` for rows whose invoice number could not be read. No
model sees two amounts and offers an opinion; a model may phrase the resulting line, and by then
the bucket is already decided.

- **Matching is on the invoice number, never the amount.** Two invoices for the same round amount
  in a month are common, and a match made on amount would pair the wrong two and then report
  agreement — a wrong answer wearing the costume of a right one.
- **Two passes.** The normalised key first ("INV #001041" → `inv1041`), then the **digits alone,
  only where exactly one unmatched row on each side carries them** ("INV-01041" on their template
  against "1041" in our extraction). Ambiguity stays unmatched: a guessed pair that then reports
  agreement is the worst output this module could produce.
- **No line is emitted for `matched`.** Agreement is not work; a line saying "41 invoices agree" is
  the false-positive volume §5.2 says trains a user to dismiss the twenty-first item unread. The
  matched count appears *inside* the lines that are emitted, as context.
- **Short payments name a likely reason** (§3.2) from a fixed arithmetic table — about 1%, 2%, 5%
  or 10% of the invoice read as TDS, an early-payment discount or a retention — each phrased as a
  candidate, because naming an unproven reason as established is §5.2's quiet credibility loss.
- **"They show and we do not" is `Reversibility.LEAVES_COMPANY`**: its action drafts a message to
  the vendor, so it can never be batched, by construction rather than by a reviewer noticing.
- A statement in another currency raises `CurrencyBlendError` rather than being converted (§7.4).

### 14.5 34.5 — the claim → witness rule

§3.3's three steps, as code, with **no new tables** (D39):

1. `claims_for_invoice()` derives claims from extracted fields only — a claim for a field that was
   never read would turn a missing extraction into a request for paperwork, which is §3.3's
   anti-pattern arriving by the back door. `CLAIM_WITNESS` is §3.3's table verbatim and is fixed,
   never learned: a witness chosen per invoice by a model makes the ask unfalsifiable.
2. `witnesses_held()` answers "do we already hold it" off `documents.doc_type`. **Holding it means
   `CHECK_SILENTLY`, and `doubt_recommendations()` emits nothing for it** — "check silently, say
   nothing unless it disagrees" is the step that stops ATLAS nagging. The answer is tenant-wide and
   conservative *in the direction of asking*, because a wrong "we hold it" silences a question that
   should have been asked while a wrong "we do not" merely asks for a document the user can decline.
3. Materiality is measured against the **vendor's own scale**, never an absolute amount (§3.3's
   large-versus-small rule).

`vendor_baseline()` is computed at check time from that vendor's own invoices, **excluding the
invoice being checked** — comparing a number against a range it is inside makes every invoice
normal, which is how an anomaly check quietly stops working — and per currency, because a blended
range is a wrong number with a range around it.

**D40's working is the whole substitute for a stored, editable rule**, so the line carries it:
*"₹2,40,000.00 is over 4x their usual ₹40,000.00–₹60,000.00 across 4 invoices."* Every amount in
that sentence is a `Figure(source=COMPUTED, computation=…)` naming what was computed — Slice A's
mechanism, used rather than duplicated. The multiple is rendered as a **floored integer** ("over
4x"): 4.9x printed as "5x" is a number ATLAS invented, and the direction of an exaggeration does
not make it true.

### 14.6 The contract extension, and one addition to its public surface

Slice B extended `services/atlas_contract.py` twice, deliberately, rather than working around it:

1. **`Correction`** — `field_label`, `field_name`, `before_rendered` (nullable), `after_rendered` —
   plus the optional `Recommendation.correction`. D45 requires the before/after pair, and it is a
   typed block rather than two sentences in `why.text` because the FE lays it out as a pair; prose
   that has to be parsed to be rendered is a field the two sides agree about by accident, which is
   the defect class this contract exists to prevent. **Both halves go through
   `Recommendation.prose()`**, so §5.3's number rules cover the value the click writes.
2. **`numeric_tokens()`** made public. Used for one narrow job: declaring the numbers inside a
   string ATLAS reproduces **verbatim** rather than composes — an extraction alert copied character
   for character onto an approval line ("Possible duplicate of #4241"). Those numbers are declared
   as `Why.references`, and the exception is bounded and stated: the failure §5.3 guards against is
   prose from a model that rounded, which cannot occur on a byte-for-byte copy. Everything ATLAS
   *composes* still declares its numbers as figures with a document or a computation behind them.

**No other field was added, and `Action` still carries no URL.** The action `kind` values this
slice introduces (`resolve_invoice`, `apply_field_correction`, `open_field_review`,
`retry_ingestion_source`, `requeue_invoices`, `open_upcoming_payments`,
`request_missing_invoices`, `review_unlisted_invoices`, `open_invoice_against_statement`,
`attach_witness_document`) are the FE's dispatch vocabulary; **the endpoints that perform them do
not all exist yet**, and inventing routes for them here would be the F33/F22 seam again.

### 14.7 Verification

Against real Postgres at `postgresql://…@127.0.0.1:5433/invoice_db` — **`127.0.0.1`, never
`localhost`**, which resolves to `::1` first and is BE Gap 697:

```
DATABASE_URL="postgresql://postgres:localpassword123@127.0.0.1:5433/invoice_db" \
  ./.venv/Scripts/python.exe -m pytest tests/test_atlas_contract.py tests/test_atlas_skills.py \
    tests/test_atlas_recon.py tests/test_atlas_doubt.py -q
→ 59 passed
```

```
DATABASE_URL=… ./.venv/Scripts/python.exe -m pytest tests/test_autopilot.py -q
→ 40 passed, 3 failed — all three on `column "source_config_id" does not exist`, i.e. BE Gap 698
```

```
DATABASE_URL=… ./.venv/Scripts/python.exe -m pytest tests/test_atlas_ingestion_sources.py -q
→ 6 errors, by design — the fixture fails with the Gap 698 message rather than skipping
```

**34.13's migration has not been applied, and that is filed as BE Gap 698, not worked around.**
`alembic upgrade head` fails with `Can't locate revision identified by 'a1b2c3f33003'`: the dev
database's `alembic_version` names a revision that exists in no branch of this repo, and two
migrations on the current chain (`e6f7a8b9c0d1`'s `chatmessage.turn_metadata` and
`auto_golden_cases.generated_sql`) are unapplied as a result. Applying the DDL by hand was refused
by the harness as a shared-resource change, and re-stamping `alembic_version` is a founder
decision, not a build step. **So 34.13 is code-complete and unverified on the database**, and the
tests that prove it are written, red, and name the gap.

### 14.8 What Slice B deliberately does not do

- **No batch endpoint and no batch action of any kind** (D42). `assert_batch_acceptable()` from
  Slice A still has no caller, and §11's "an outbound message cannot be sent by a batch endpoint"
  remains asserted against the guard rather than an endpoint — §12.5's caveat is unchanged.
- **No notification, channel, digest or interrupt** (D36). Nothing in this slice sends anything.
- **No background job, event hook or clock** (D38). Every function here runs when it is called.
- **No ranking, no collapse, no cold-start content, no "you missed this"** — 34.7, 34.9, 34.10,
  34.12 and 34.14 are Slice C, and `atlas_lines()` returns skill order, which is explicitly not a
  ranking.
- **No endpoint at all.** Slice B is services and tests; the router that serves the work screen is
  Slice C's, and FE Feature 23 remains unstarted and gated.

### 14.9 One thing in the spec that is wrong, flagged rather than rewritten (hard rule 4)

**§3.3's "This needs something that does not exist: invoices carrying checkable assertions … plus
a vendor baseline to deviate from (Q10)."** Q10 was ruled by D39 — derive both at check time — and
the sentence now reads as if a build step is still outstanding. Nothing is: `claims_for_invoice()`
and `vendor_baseline()` are that "something", and they exist without a table. §13.1 already records
the ruling; the §3.3 sentence is left as written because it holds the reasoning that produced Q10.

---

## 15. As built — the HTTP surface (2026-09-18, BE Gap 691)

**Additive record, not a replacement for §1–§14.** Branch `feature/atlas`, uncommitted. Built as
task 23.0 of FE Feature 23, because that build could not start without it: Slices A and B produced
`Recommendation`s that **nothing could serve** — `grep -rn "atlas" routers/ main.py` returned 0
hits on 2026-09-18. §14.8's "the router that serves the work screen is Slice C's" left a hole
rather than a deferral, and building the FE against a contract no endpoint serves is the F33/F22
seam exactly. Filed as **BE Gap 691** before any code was written.

### 15.1 Files

| File | What it holds |
|---|---|
| `routers/atlas.py` | `GET /api/v1/atlas/lines`, `POST /api/v1/atlas/recon`, the two envelopes below |
| `main.py` | One `include_router(atlas.router, prefix="/api/v1")` |
| `services/atlas_recon.py` | **One additive function**, `statement_lines_from_items()`, + `_invoice_number_in()` |
| `tests/test_atlas_router.py` | 8 tests: the empty state, the whole line on the wire, absent-not-disabled, the doubt cap, and four recon cases |

### 15.2 The two envelopes

**Owned here. FE Feature 23 consumes these names and never restates them**, exactly as §12.2's
`Recommendation` is consumed.

```
GET /api/v1/atlas/lines  -> AtlasLinesResponse
  ungranted            bool          — D3's empty state, as a field
  capabilities         str[]         — the caller's AtlasCapability values, for naming only
  lines                Recommendation[]   — §12.2, verbatim, `batchable` included
  doubt_checks_run     int
  doubt_checks_skipped int

POST /api/v1/atlas/recon  { document_id, vendor_name? }  -> ReconResponse
  vendor_name     str
  currency        str
  document_id     str
  agrees          bool
  groups          { matched[], they_show_we_do_not[], we_show_they_do_not[],
                    amount_differs[], unmatchable[] }   — §6's four groups, plus unreadable rows
  unreadable_rows int
  lines           Recommendation[]

ReconRow { invoice_number?, invoice_id?, amount_rendered,
           theirs_rendered?, ours_rendered?, difference_rendered? }
```

Four shapes that are deliberate:

- **`ungranted` is a field, not `len(lines) == 0`.** "No tasks assigned. Ask your admin for
  access." (D3) and "nothing needs you right now" are different sentences, and a client that
  inferred between them would tell a busy Auditor they have no access on the morning they are
  clear.
- **`ReconRow` carries no `value`, only `amount_rendered`.** FE §2 says no arithmetic
  client-side, ever; a number a client *can* add up is a number a client eventually does add up.
  Every amount on a recon row is a string this server formatted with `render_amount()`.
- **`doubt_checks_run` / `doubt_checks_skipped` exist because the doubt checks are capped** at 50
  awaiting-audit invoices per request. §13.5 names check-time derivation at scale as an unknown to
  be answered by measurement; the cap keeps the unknown off the sign-in path, and reporting it
  means a screen missing checks can say so instead of looking complete.
- **Still no action endpoint.** `resolve_invoice`, `apply_field_correction`,
  `retry_ingestion_source` and the rest of §14.6's dispatch vocabulary remain Slice C and remain
  absent. This router reads; it writes nothing. The FE knows a `kind` it cannot yet perform, which
  is a visible state, rather than discovering a 404 at the worst moment.

### 15.3 Two decisions inside the recon route

1. **A statement row's invoice number is read out of `description`, and refused when ambiguous.**
   A vendor statement arrives through Feature 27's generic extraction and `GenericLineItem` has no
   `invoice_number` column — it has `description`, `quantity`, `unit_price`, `amount`. So
   `_invoice_number_in()` takes the tokens carrying a digit, drops the date-shaped and
   amount-shaped ones (both appear in the same string on most templates), and accepts the result
   **only when exactly one candidate remains**. Zero or several means the row is `unmatchable` —
   a row we could not read — never a key that might pair with the wrong invoice and then report
   agreement. Same standard `reconcile()`'s second pass already holds itself to.
2. **A row with `amount is None` is counted, never read as zero.** Gap 283's lesson, and a zero
   here would be reported *to a vendor* as a disagreement. `unreadable_rows` carries the count.

Both refusals surface as stated positions rather than silence: no vendor name on the document →
422 "tell me whose statement it is"; no readable amount anywhere → 422; another currency →
`CurrencyBlendError` → 409, never converted (§7.4).

### 15.4 Verification

Against real Postgres at `postgresql://…@127.0.0.1:5433/invoice_db` (**`127.0.0.1`, never
`localhost`** — BE Gap 697):

```
DATABASE_URL="postgresql://postgres:localpassword123@127.0.0.1:5433/invoice_db" \
  ./.venv/Scripts/python.exe -m pytest tests/test_atlas_router.py -q
→ 8 passed

… -m pytest tests/test_atlas_contract.py tests/test_atlas_skills.py tests/test_atlas_recon.py \
    tests/test_atlas_doubt.py tests/test_atlas_ingestion_sources.py -q
→ 65 passed
```

**That second run is also new information about BE Gap 698**, reported rather than acted on:
`tests/test_atlas_ingestion_sources.py` was 6 errors on 2026-09-17 and is now **6 passed**, so
migration `a1b2c34d13e5` is applied on this machine and `source_config_id` exists. Whether Gap 698
is closed everywhere is a founder call — the tracker entry is left as written.

### 15.5 What this router deliberately does not do

- **No write of any kind**, so no action endpoint and no batch endpoint (D42 — there is still no
  batch anything, and `assert_batch_acceptable()` still has no caller).
- **No new auth path.** `get_tenant_context` + `GrantSet.from_context()`; no ATLAS-specific
  permission check exists anywhere in the file.
- **No filtering the FE can undo.** `visible_to()` drops server-side (§2.1); the response carries
  no disabled/hidden marker for a client to render by mistake.
- **No ranking, no collapse, no cold start** — 34.7, 34.9, 34.12 are still Slice C, so `lines` is
  skill order, which is explicitly not a ranking.

### 15.6 What the first live call found — BE Gap 692

**The endpoint was built, the tests were green, and the first real request 500'd.** Filed as
**BE Gap 692** and fixed in the same change, never silently.

`POST /atlas/recon` against an ordinary four-row statement failed inside its own contract:

```
InventedNumberError: recommendation recon-missing-theirs-… renders '1043,' in
'…that their statement does not list: #1043, #1044.', which no figure declares
```

Every number on that line **was** declared — `references == ["#1043", "#1044"]`. §12.4's tokeniser
allowed a grouping separator in trailing position, so it read `1043,` (with the comma that ends the
clause) while the declared reference read `1043`. The fix is one character class:
`\d[\d,' ]*(?:\.\d+)?` becomes `\d(?:[\d,' ]*\d)?(?:\.\d+)?` — a number may **contain** separators
but must **end** on a digit.

Two things worth keeping from this:

1. **59 passing Slice A/B tests did not catch it**, because every one of them asserts on a single
   figure or a single reference. `recon_recommendations()`'s list branch was tested with exactly
   one unmatched invoice per side, where no comma is printed. The defect needed two. This is the
   §11 invariant "never invents a number" failing in the *other* direction — rejecting a correct
   line — which no test was written for.
2. **It was found by a live call, not a test run**, which is the whole argument for FE Feature 23's
   end-to-end requirement.

### 15.7 End-to-end evidence (2026-09-18)

Not a fixture and not a test double. `next dev` → the FE route handler → this router → Postgres,
in a real Chromium browser on `/work`:

- **6 lines rendered, 0 defects, 0 page errors** — four invoices awaiting a decision, the cash
  position and runway line (D44 — the Auditor's, and the Admin sees it as the superset), and one
  §3.3 doubt line asking for the quotation.
- The doubt line's attach affordance opened the recon panel, and a real statement `Document`
  compared through `POST /atlas/recon` to **matched 1 · they show and we do not 1 · we show and
  they do not 2 · amount differs 1 · unreadable 1**, with the difference printed as the server
  rendered it (`-2,000.00`).
- The Verify link opened `/chat?seed=…` with the line's own question in the composer, and sent
  nothing.

**The seeded rows were removed afterwards.** They existed to make the mock tenant's screen
non-empty for the run and are not test data anyone should find later.

---

## 16. As built — D47 and D49 (2026-09-18)

**Additive record, not a replacement for §1–§15.** Branch `feature/atlas`, uncommitted.
Founder rulings **D47** and **D49** of 2026-09-18 (`atlas_discussion.md`). **D48 is FE-only**
and has no backend at all — deliberately, see §16.4. Tracker entries: **BE Gap 693** (D47) and
**BE Gap 695** (D49).

### 16.1 Files

| File | Ruling | What changed |
|---|---|---|
| `services/atlas_contract.py` | D47 | `AttachmentPromiseError`, `_ATTACHMENT_ALREADY_MADE`, `assert_verify_does_not_promise_attachment()`, called by `validate_recommendation()`. `Verify`'s docstring no longer says "opens chat with the document attached" |
| `services/atlas_skills.py` · `atlas_doubt.py` · `atlas_recon.py` | D47 | The seven `Verify.question` strings that carry a `document_id` now begin with the attach instruction |
| `models.py` | D49 | `AtlasDismissal` |
| `alembic/versions/b2c3d45e14f6_atlas_dismissals.py` | D49 | One add-only table; `a1b2c34d13e5` → `b2c3d45e14f6` |
| `services/atlas_dismissals.py` | D49 | `dismissed_ids()`, `drop_dismissed()`, `dismiss()` |
| `routers/atlas.py` | D49 | `POST /atlas/lines/{recommendation_id}/dismiss`, and the filter on **every** line-producing path |
| `tests/test_atlas_dismissals.py` | D49 | 7 tests |
| `tests/test_atlas_contract.py` | D47 | 4 tests added, and the module's one document-bearing fixture rephrased |

### 16.2 D47 — Verify stops promising what it cannot do

**FE Gap 640 closes as a wording and expectation change. Neither endpoint it proposed was
built**, and nothing re-uploads a copy of a document the tenant already holds. The founder ruled
the promise changes, not the plumbing.

The wording is not left to the emitters. `assert_verify_does_not_promise_attachment()` runs on
every line inside `validate_recommendation()`, and holds two halves of one rule:

1. **No question may claim the document is already attached** — a fixed phrase list, matched
   case-insensitively. It never is attached, so any such sentence is a promise the product
   cannot keep.
2. **A question that names a `document_id` must contain the attach instruction.** The document
   id is the only thing naming *which* document settles the question; a line carrying one and
   never mentioning attaching leaves the user to guess the step.

A question with no `document_id` is unconstrained beyond rule 1 — the cash position, a stuck
ingestion source and a quiet Drive folder are checkable without paperwork, and `audit-cash-INR`
still reads *"Which invoices make up this number, and what did you assume about when they are
paid?"*

Hard rule 3 is why this is a function and not a phrasing convention: "does this sentence
over-promise" is exactly the judgement a model makes differently on each run.

**What the seven lines now say**, e.g. *"Attach #1041 here and show me how you read it — is the
total right?"* and *"Attach their statement here — which of our invoices are missing from it, and
what did you match the rest on?"* The question is still the string seeded into the chat composer,
so the user attaches, then sends what is already written.

### 16.3 D49 — a dismissed line does not come back

**The problem.** D38 recomputes everything on open; nothing is stored. So a user who handles a
line — by doing exactly what D47 now tells them, attaching the document in chat and comparing —
changes nothing the recompute can see, and the line **returns forever**.

**The store.** `atlas_dismissals`, keyed on `(tenant_id, user_id, recommendation_id)`, unique on
all three. `user_id` is `TenantContext.user_id`, the identity string every request already
carries (`db_user_id` is nullable, so it is not the key). **Per user as well as per tenant**:
the Admin is the superset (§2.2), so one Auditor marking their line done must not blind them.

**Why the id is enough.** `Recommendation.id` is deterministic at every emitter —
`audit-approve-<invoice id>`, `train-arithmetic-<invoice id>`, `doubt-rate-<invoice id>`,
`recon-differs-<invoice number>` — with no per-run UUIDs anywhere. That property is load-bearing
and invisible: an emitter added later that put a `uuid4()` in an id would silently break
dismissal for that line type and nothing would fail, so
`test_recommendation_ids_are_stable_across_recomputes` asserts it directly rather than trusting
this paragraph.

**The filter is server-side, before the response is assembled** (founder, 2026-09-18). A
dismissed line is **absent from the payload, not flagged in it** — `drop_dismissed()` drops, the
same rule as `visible_to()`'s "absent, not disabled" (§2.1). It is applied to **every**
line-producing path, not only the skills: the §3.3 doubt asks are lines too and were the exact
case D49 was raised about, and `POST /atlas/recon`'s lines get it as well. One `dismissed_ids()`
read per request serves all of them.

**Not a snooze and not an automatic resolution** (D49, explicitly). There is no expiry parameter,
no `until` column and no code path that returns a dismissed line. Nothing infers that the
underlying problem was solved; the honest reading of that cost is in the decision entry, not
softened here. D12's noise pruning is the natural reader of these rows and is still unbuilt.

**The endpoint is idempotent and does not validate the id.** A repeat click from a stale screen
writes no second row (a duplicate would make any future count of dismissals wrong). An unknown id
is accepted: validating it would mean running every skill on a dismiss click, on the
open-the-app path, to reject something that suppresses nothing — and it would make the click fail
precisely when someone else had just fixed the underlying problem, which is the worst moment to
argue with the user.

### 16.4 What was deliberately not built

- **No per-user preference store.** D48's toggle is localStorage only, in the browser. The
  backend gained nothing for it — no `user.ui_prefs`, no `PATCH /me/preferences`. The stated
  consequence is that **nobody can see which mode people actually use**.
- **No by-id chat attachment endpoint** (D47). FE Gap 640's two proposals are not built.
- **Still no action endpoint, no batch endpoint, no notification and no background job** (Slice
  C, D42, D36, D38). `POST /atlas/lines/{id}/dismiss` is now the router's one write, and it is a
  dismissal, not an action on the underlying invoice.

### 16.5 Verification

Real Postgres at `postgresql://…@127.0.0.1:5433/invoice_db` — **`127.0.0.1`, never `localhost`**
(BE Gap 697). Migration applied once, `alembic upgrade head`, `a1b2c34d13e5 → b2c3d45e14f6`; no
backfill, no down/up ceremony.

```
DATABASE_URL="postgresql://postgres:localpassword123@127.0.0.1:5433/invoice_db" \
  ./.venv/Scripts/python.exe -m pytest tests/test_atlas_dismissals.py \
    tests/test_atlas_router.py tests/test_atlas_contract.py tests/test_atlas_skills.py \
    tests/test_atlas_recon.py tests/test_atlas_doubt.py tests/test_atlas_ingestion_sources.py -q
→ 85 passed
```

**Live, at the wire.** `uvicorn main:app` on `127.0.0.1:8077` against that Postgres, driven with
`curl` — not a `TestClient`, not a fixture:

```
GET  /api/v1/atlas/lines
  audit-approve-d74ac94c-…   audit-approve-89584e3e-…   audit-cash-INR
  doubt-rate-89584e3e-…      doubt-rate-d74ac94c-…

POST /api/v1/atlas/lines/audit-approve-d74ac94c-…/dismiss
  {"recommendation_id":"audit-approve-d74ac94c-…","dismissed":true,"created":true}
POST /api/v1/atlas/lines/doubt-rate-89584e3e-…/dismiss
  {"recommendation_id":"doubt-rate-89584e3e-…","dismissed":true,"created":true}

GET  /api/v1/atlas/lines          ← a full recompute, D38
  audit-approve-89584e3e-…   audit-cash-INR   doubt-rate-d74ac94c-…
```

Both dismissed ids are **absent from the raw response body**, checked by grepping the bytes, not
by reading the screen. One is a skill line and one is a §3.3 doubt ask, so both producing paths
are covered. **The backend process was then killed and restarted, and the two lines were still
gone** — the dismissal is in Postgres, not in a process.

The same run shows D47's wording as served:
*"Attach #D49B here and show me how you read it — is the total right?"*

**The seeded rows were removed afterwards.** They existed to make the mock tenant's screen
non-empty and are not test data anyone should find later.
