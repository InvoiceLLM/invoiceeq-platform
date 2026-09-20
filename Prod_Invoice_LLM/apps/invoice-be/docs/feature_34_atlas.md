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

### 14.3.1 Amendment — BE Gap 712 (2026-09-20): the Trainer's arithmetic line is removed

The "drafted correction" line type described above no longer exists. `_arithmetic_correction()`,
`_line_items_total()` and `_ARITHMETIC_SLACK` are deleted from `services/atlas_skills.py`. The
extraction pipeline already verifies invoice arithmetic (`utils/verification_tools.py`
`verify_totals_math` / `verify_line_items_math`) and records the result in `sa_alerts`; ATLAS
re-adding the items was a second, duplicated correctness decision with its own tolerance, and the
founder ruled the line is not needed at all — not replaced by an alert-reading line, removed. The
Trainer now emits **one** line type, `low_confidence_fields`, which additionally carries
`vendor_invoice_count` in its action params so D21's consequence ordering still has a key. No
emitter produces a `Correction` block; the contract type stays (hard rule 4) and
`apply_field_correction` remains a registered suggest-only action kind with no line that offers
it. §17.4's `train-arithmetic-` ranking row and §17.11's example `act` call are history.

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

---

## 17. As built — Slice C (2026-09-18)

**Additive record, not a replacement for §1–§16** (CONVENTIONS hard rule 4). Branch
`feature/atlas`, uncommitted, on top of commit `2baf8bb`. Tasks **34.7 (a–g), 34.9, 34.10,
34.12 and 34.14**. **34.8, 34.11, escalation and every background job remain unbuilt by ruling**
(D42, D36, D37, D38) and nothing in this slice contains a skeleton of any of them.

Founder rulings this slice is written against: **D50** and **D51** (2026-09-18, the action set),
plus D30, D20/D41, D15/D44, D31/D40, D12, D24/D25 and D34.

### 17.1 What this slice changes about what ATLAS *is*

Slices A and B produced a screen that **explains and cannot act**. `PERFORMABLE_ACTION_KINDS`
was empty on both sides, every button rendered disabled saying *"I can see this and explain it,
but I cannot do it for you yet"*, and `atlas_lines()` returned skill order, which §14.8 said in
so many words is not a ranking. Until this slice ATLAS was a report.

It is now a tool, on **exactly two action kinds**, and the lines arrive ranked.

### 17.2 Files

| File | Task | What it holds |
|---|---|---|
| `services/atlas_actions.py` | 34.7a–e | `ActionDisposition`, `ACTION_DISPOSITIONS` (all ten kinds), `ACTION_CAPABILITY`, `PERFORMABLE_ACTION_KINDS`, `perform_action()`, `record_action()`, `recent_actions()` |
| `services/atlas_ranking.py` | 34.7f | `RANK_CUT`, `days_left()`, `rank_score()`, `rank()` |
| `services/atlas_collapse.py` | 34.7g | `COLLAPSE_THRESHOLD`, `UNTOUCHED_DAYS`, `CollapsedArea`, `capabilities_held_by_others()`, `collapse()` |
| `services/atlas_forecast.py` | 34.9 | `Shortfall`, `shortfalls()`, `forecast_recommendations()`, `DUE_DATE_ASSUMPTION` |
| `services/atlas_memory.py` | 34.10, 34.14 | `RuleSource`, `ID_FAMILIES`, `list_rules`/`add_rule`/`edit_rule`/`delete_rule`, `report_missed()`, `noise_suggestions()` |
| `services/atlas_orientation.py` | 34.12 | `OrientationPart`, `Orientation`, `orientation()`, `tenant_has_history()` |
| `services/atlas_contract.py` | 34.7f, 34.9 | `stake` / `fixable_until` / `since` on `Recommendation`; `Lever`, `Forecast`, `Recommendation.forecast`, and both inside `prose()` |
| `services/atlas_skills.py` · `atlas_doubt.py` | 34.7f | `_arrived_on()`, and the ranking inputs stated at each emitter |
| `models.py` | 34.7c, 34.10, 34.14 | `AtlasActionLog`, `AtlasMemoryRule`, `AtlasMissedReport` |
| `alembic/versions/c3d4e56f15a7_atlas_action_log.py` | 34.7c | One add-only table |
| `alembic/versions/d4e5f67a16b8_atlas_memory_and_missed.py` | 34.10, 34.14 | Two add-only tables |
| `routers/atlas.py` | all | `POST /lines/{id}/act`, `GET /actions`, `GET /actions/kinds`, `GET /orientation`, `GET/POST/PATCH/DELETE /memory`, `POST /missed`; ranking and collapse applied to `GET /lines` |
| `tests/test_atlas_actions.py` · `test_atlas_ranking.py` · `test_atlas_forecast.py` · `test_atlas_memory.py` | all | 64 new tests |

**Three add-only tables, no backfill, no down/up ceremony** (founder's dev-phase rule).
`alembic upgrade head` run once: `b2c3d45e14f6 → c3d4e56f15a7 → d4e5f67a16b8`.

### 17.3 34.7 — the action set, and where each ruling is enforced

**The dispatcher performs nothing itself.** Both performable kinds are wired to code that
already existed:

- `resolve_invoice` → `routers.audit.resolve_audit_invoice`, **called as a function**, not over
  HTTP and not re-implemented. It is an ordinary `async def` whose `Depends(...)` defaults FastAPI
  resolves; passing the context and session explicitly runs exactly what an auditor's own click
  runs — Gap 561's rate limiter, Gap 541's row lock, the `AuditLog` write, the alert re-check,
  the notification fan-out. A second path to the same decision is the one that drifts.
- `retry_ingestion_source` → `services.autopilot_sync.run_sync(config_id=…)`, **per source**
  (D51, possible since D43). The endpoint `POST /autopilot/sync` runs every source because a Sync
  Now that checked one would lie; an ATLAS line names one source, so it calls the per-source entry
  point. `run_sync` resolves the config out of this tenant's own sources, so tenant scoping is not
  re-implemented either.

**Every kind is in the table, including the eight that will never be performed.** A kind that is
merely absent is refused by accident; a kind present as `SUGGEST` is refused on purpose, and the
next reader can tell which. The four dispositions are `PERFORM`, `SUGGEST` (D50 — resolves to a
destination, never a write), `NAVIGATE` (never was a write) and `INSTRUCT` (`attach_witness_document`
since D47, `request_missing_invoices` because §5.3 says an outbound message is read in full and
sent by a human).

**34.7b — the capability check on acting is a second, separate decision.** `visible_to()` drops a
line the caller may not act on, so it was never on their screen; that is not a gate, because a
request naming a line id arrives regardless of what was rendered. `perform_action()` requires
`ACTION_CAPABILITY[kind]` and answers **403**. The equivalence between that check and the audit
router's own `Depends(require_actions_scope)` — which calling the handler directly does not run —
is asserted over every role in `test_acting_gate_agrees_with_the_audit_router_gate`, not left to a
docstring.

**The client's `params` are never forwarded.** `AuditResolutionPayload` also accepts `corrections`
and `apply_as_standing_rule`, so a passed-through dict would let `apply_field_correction` —
suggest-only by ruling — arrive wearing `resolve_invoice`'s name and teach a vendor-scoped standing
rule. The payload is rebuilt from a whitelist, and the status is narrowed to `PAID`/`REJECTED`:
Gap 193's Admin-only reopen and Gap 407's two deferrals are not reachable through a surface whose
lines never propose them. `test_resolve_invoice_ignores_a_smuggled_standing_rule` re-reads the
vendor name afterwards, because a status code alone would not prove the correction was dropped
rather than merely unreported.

**34.7c — the action log is a table, not a claim.** §5.3 requires that every write is visible,
attributed and timestamped and that "what ATLAS did" is a real list. `atlas_action_log` holds one
row per **attempt**: a log holding only successes answers "did ATLAS touch this invoice?" with a
confident no on exactly the occasions someone is asking because something looks wrong. Read
tenant-wide by `GET /atlas/actions` — the Admin is the superset (§2.2) and a per-user log would
hide one auditor's resolve from the person answerable for it. A logging failure never fails the
action: the underlying write has already happened, and reporting a failure for something that
succeeded is a worse lie than a missing row.

**This table is not the audit trail.** `AuditLog` is, and it is still written, because
`resolve_audit_invoice` is called unchanged — a resolve performed from the work screen appears in
`audit_logs` exactly as one from the audit queue does.

**34.7d — `PERFORMABLE_ACTION_KINDS` is now served, not transcribed.** The empty set in
`lib/atlas.ts` was Slice B's honesty mechanism and it **stays empty**: the FE reads
`GET /atlas/actions/kinds` at runtime instead. A hand-maintained copy on the client is what lets a
button be enabled ahead of its endpoint, which is the exact failure the empty set was invented to
prevent. The FE's fallback while that read is in flight or has failed is "nothing is performable",
because "I do not know whether I can do this" and "I can" must not render the same.

**34.7e — suggest-only never becomes a write, enforced twice.** The endpoint answers **409** with
D50's reason in words (not 404 — a 404 reads as "not built yet", which is the wrong expectation to
set about a ruling), and `test_a_suggest_only_kind_is_refused_and_writes_nothing` re-reads the
invoice row to prove nothing moved. The FE renders those kinds as a **link** to
`actionDestination()`, so there is no button whose `onClick` a later change could fill in.

### 17.4 34.7f — ranking, as arithmetic

`money at stake ÷ (days until it stops being fixable + 1)`, sorted descending, tie-broken on
`(-stake, id)`. Hard rule 3: ordering decides which finding a person reads first and which they
never scroll to, so a ranking a model produces differently each run is a shuffle with an
explanation attached.

The two terms are **stated by the emitter**, not inferred from prose — `Recommendation.stake` and
`.fixable_until`, plus `.since` for the aging figure. They are new contract fields and are
**never rendered**: they are inputs to arithmetic, so requiring a `Figure`'s witness for them would
be ceremony with no reader. What each emitter states, and why:

| Line | `stake` | `fixable_until` |
|---|---|---|
| `audit-approve-` | the invoice total | its due date |
| `train-arithmetic-` | **the size of the error**, not the invoice — a wrong total on a small invoice is a small problem, and ranking by the invoice would push every large invoice's rounding slip above a genuinely wrong small one | none |
| `train-lowconf-` | none — there is no computable error size, and the invoice total would be the wrong number (same reasoning that keeps `Correction` off that line) | none |
| `doubt-` | `claim.value`, the amount the doubt is *about* — a doubt about a freight line is not a doubt about the whole invoice | the invoice's due date |
| `forecast-short-` | the shortfall | the day it lands |

`fixable_until is None` ranks as far off (90 days), never as urgent: inventing urgency for a line
that stated none degrades the whole ordering every time an emitter forgets the field. `days_left`
is floored at zero, so an overdue item is maximally urgent rather than negatively urgent — a
missed deadline does not make the money stop mattering.

**Nothing is hidden.** `rank()` returns every line it was given. `rank_cut` is a display hint on
the response and the lines below it are **in the same payload**, so the FE's *Show everything*
reveals rather than fetches — "reachable" must not quietly mean "reachable when the network is up".

**One honest limit, stated rather than discovered later:** two lines in different currencies are
ordered by raw magnitude with no rate applied. No blended number is produced and nobody reads the
score, so §7.4 is not violated — but the relative order of cross-currency neighbours is arbitrary,
and that is written in the module docstring rather than left for someone to find.

### 17.5 34.7g — collapse, and what it is not

Admin only. An area collapses when **another grant-holder holds that capability** (D20) *or* when
there is simply a lot of it (D41 — `COLLAPSE_THRESHOLD`, a stated guess of 12, because §13.5 names
the real threshold as a build-time unknown to be answered by measurement and there is no customer
to measure). One row shape, two reasons, and the row says which.

- **It groups; it never removes.** The lines an area stands for are still in `lines`, and the row
  carries their ids. That is what makes "openable in place" a client-side expansion with no second
  request and no second permission decision — coverage is total by construction.
- **A solo owner collapses nothing**, and it is not special-cased: no other grant-holder and a
  small list means no reason to collapse.
- **The Admin's own position is never collapsed away from them.** `AtlasCapability.ADMIN` is
  skipped: the cash position is not somebody else's work, and §2.2's "nothing withheld" forbids it.
- **No escalation** (D37). Nothing travels anywhere after a delay; there is no clock in this module.
- **Aging is honest about what it could not measure.** A line with no `since` is counted in the
  total and **not** counted as untouched — "I do not know how old this is" and "this is fresh" are
  different facts — and the row carries `age_unknown` and says so in its headline.

### 17.6 34.9 — the forecast with levers

`shortfalls()` walks each currency's balance forward **day by day** from the last imported
statement balance and returns the first day it goes below zero. That is a different question from
"what is the net position in 30 days" and a much more useful one: a tenant can be comfortably
positive at month end and unable to pay on the 22nd. A net-position forecast would say nothing, and
`test_short_on_a_day_even_when_the_month_nets_out_fine` is that case.

Three levers, all chosen by arithmetic: the fewest receivables due *after* the short day whose
total reaches the gap; the single payable due on or before it that is large enough to cover it; and
the receivable already expected before it, which asks nothing of the user. **A chase set that
cannot cover the gap is dropped, not offered as a partial fix** — the user would find out after
doing the chasing.

- **`Forecast.assumption` is a required contract field**, and it says due dates in words. §7.5:
  "deterministic and honest are separate properties", and the honest half is the one that gets left
  out when it is optional. §7.5's better forecast — built on how people actually pay — is **not
  built**, and the line says so in its `doubt` rather than letting a due-date sum wear behaviour's
  clothes (§5.2's "right flag, wrong reason").
- **Nothing is emitted when the balance is unknown.** No statement, no starting point; a walk from
  zero would report every tenant as short on day one, and "unknown" must not render as "short" —
  the same rule that makes `runway_days` `None` rather than a large number.
- **Nothing is emitted when there is no shortfall.** A line saying "you are fine" is the
  false-positive volume §5.2 says trains a user to stop reading.
- **`AtlasCapability.AUDIT`** — D44, one forecast and one view of it, with the Admin seeing it as
  the superset. That reversal of D2 lives in one field, and a test asserts it.
- **A lever is never a button.** §5.3: ATLAS never moves money and never sends outside the company
  unseen. Chasing a customer and deferring a payment are things the person does.

### 17.7 34.10 and 34.14 — memory, and being told about a miss

**D40 removes most of what ATLAS knows from the memory store, and that is the point.** Vendor
baselines and claims are derived at check time and thrown away (D39); the line shows its working
instead. `atlas_memory_rules` holds only what ATLAS was **told** or what a user **agreed** it
should remember. That boundary is invisible — nothing would fail if a baseline were written there —
so `test_no_emitter_writes_to_the_memory_store` asserts grep-shaped that no emitter module imports
it.

A rule can be read, edited, switched off and deleted. **Delete is a hard delete**: there is no
`deleted_at`, and §7.2's own argument is why — a wrong lesson that cannot be found haunts the
system forever, and a soft-deleted rule is precisely one that cannot be found. `active=False` is a
different act: a user keeping a rule and switching it off.

**D12's noise pruning suggests and never writes.** `noise_suggestions()` counts dismissals per line
family, tenant-wide across users, and above 40 (§5.3's own figure: "one dismissal is noise, forty
are a pattern") produces a sentence the user may accept. Accepting it is them calling `add_rule`.
Writing it automatically would be the silent write §5.3 forbids, arriving through the door marked
"learning".

The family is a **registry (`ID_FAMILIES`), not a parse**, and this is the one non-obvious decision
in the module: the tail of a recommendation id is a UUID, which is full of hyphens, so splitting on
them cannot find where the family ends. A test greps every `id=f"…"` out of the four emitter
modules and asserts the registry covers them.

**34.14** is `POST /atlas/missed`. It is **not capability-gated**, deliberately: a miss is noticed
by whoever happens to be looking, and §5.2 says this evidence is already invisible and
under-reported. The user's sentence is stored **unedited** and copied into a memory rule prefixed
with a fixed label — it is the evidence ATLAS was wrong, and paraphrasing it would be the system
editing its own report card. `AtlasMissedReport.rule_id` is **not** a foreign key, so deleting a
wrong lesson does not delete the record that ATLAS missed something.

Under-reporting stays accepted and unmeasured (§13.4). There is no miss rate anywhere in this code.

### 17.8 34.12 — cold start

`GET /atlas/orientation` serves §7.1's three parts for the capabilities the caller holds, plus the
day-one findings and the historical-import offer.

- **It is data, not a prompt.** Part 3 — *"right now I do not know your vendors… in a month I will
  know each vendor's usual range. In three months I will know who pays late"* — is a **commitment
  about what the product will do**, and a sentence that varies per run is a commitment nobody can
  be held to.
- **`needed` is "has this workspace seen an invoice", not an onboarding flag.** A flag records that
  somebody clicked past a screen; the question that decides whether the explanation is still true
  is whether ATLAS has anything to go on. A tenant that goes quiet and comes back to an empty
  workspace gets the honest explanation again.
- **Not a tour** (D25). No step counter, no "next", no "skip", no completion row, nothing persisted.
- **An ungranted user gets no orientation.** D3's empty state already says the true thing;
  describing work they cannot do would be explaining a product they have no access to.
- **Grants stack into one orientation** (§2.1), the way the screen merges lines rather than tabbing.
- **The historical import is an offer and says so in its own sentence** — everything works without
  it, and a first session held hostage to a file the customer may not have is the opposite of what
  §7.1 is for.

### 17.9 The contract, extended three times

Slice C extended `services/atlas_contract.py` deliberately rather than working around it, on the
same terms §14.6 records for `Correction`:

1. **`stake`, `fixable_until`, `since`** — ranking and aging inputs, never rendered, deliberately
   not `Figure`s (§17.4).
2. **`Lever` and `Forecast`**, plus `Recommendation.forecast` — because the FE lays out a date, a
   shortfall and a list as distinct things, and prose that has to be parsed to be laid out is a
   field the two sides agree about by accident.
3. **`prose()` now covers the forecast**, so `shortfall_rendered`, the assumption and every lever's
   label and amount go through §5.3's number rules. An invented "you are about ₹1.2L short" is the
   worst case with a date attached to it.

`Action` still carries no URL. Destinations for suggest-only kinds live in the FE's own route table
(`actionDestination()`), because they are FE routes and §12.2's reason for keeping URLs off the
contract has not changed.

### 17.10 Verification

Real Postgres at `postgresql://…@127.0.0.1:5433/invoice_db` — **`127.0.0.1`, never `localhost`**
(BE Gap 697).

The eleven ATLAS test files, which is the narrow run used per task:

```
DATABASE_URL="postgresql://postgres:localpassword123@127.0.0.1:5433/invoice_db" \
  ./.venv/Scripts/python.exe -m pytest tests/test_atlas_contract.py tests/test_atlas_skills.py \
    tests/test_atlas_recon.py tests/test_atlas_doubt.py tests/test_atlas_ingestion_sources.py \
    tests/test_atlas_router.py tests/test_atlas_dismissals.py tests/test_atlas_actions.py \
    tests/test_atlas_ranking.py tests/test_atlas_forecast.py tests/test_atlas_memory.py -q
→ 149 passed          (85 before this slice; 64 of them are new)
```

The whole backend suite, at the track boundary:

```
DATABASE_URL="postgresql://postgres:localpassword123@127.0.0.1:5433/invoice_db" \
  ./.venv/Scripts/python.exe -m pytest tests/ -q
→ 4564 passed, 11 failed, 4 skipped, 5 deselected
```

**The eleven failures are pre-existing on this branch and are not this slice's.** They are
`test_a3_streaming.py` (1), `test_rag.py` (4), `test_gap426_qualified_column_normalisation.py` (2),
`test_online_quality_judge.py` (2), `test_agent_eval_multiturn.py` (1) and `test_sandbox_keys.py`
(1) — SQL normalisation (the rewriter emits `= TRIM(LOWER(…))` where the test expects
`LIKE LOWER('%…%')`), streaming partial events, and chat metering. Slice C touched no file any of
them reads: the diff is `models.py`, `routers/atlas.py`, six new `services/atlas_*.py` modules and
three emitters. **Stated honestly: no pre-change run of the whole suite was captured, so this is an
argument from the diff, not from a baseline.** Filed as **BE Gap 699** rather than carried silently.

Every §11 invariant still holds, and the Slice C ones §17.11 lists are new.

### 17.11 End-to-end evidence (2026-09-18) — **an invoice resolved from the work screen**

**This is the acceptance proof for the slice, and a unit test is not it.** Real Chromium, `next dev`
on `127.0.0.1:3077` → the FE route handler → `uvicorn` on `127.0.0.1:8077` → Postgres on
`127.0.0.1:5433`. Not a `TestClient`, not a mocked `apiClient`, not a fixture.

```
LINE RENDERED: Kumar Supplies #ATLAS-E2E-347
BUTTON LABEL:  Approve
BUTTON ENABLED: true          ← from GET /atlas/actions/kinds, not from a constant
OUTCOME:       Invoice approved.
LINE STILL PRESENT AFTER RE-READ: false
PAGE ERRORS:   none
```

Read back out of Postgres afterwards, not off the screen:

```
invoice        → ('ATLAS-E2E-347', 'PAID')
atlas_action_log → ('resolve_invoice', '5004da49-…', True, 'Invoice approved.',
                    'user_test_default', 2026-09-18 07:09:20)
```

The same live backend, driven with `curl`, refusing a suggest-only kind — **the D50 half of the
proof**, because "it performed the right thing" and "it refused the wrong thing" are two claims:

```
POST /api/v1/atlas/lines/train-arithmetic-…/act  {"kind":"apply_field_correction",…}
→ 409 "I do not do 'apply_field_correction' for you. I can show you exactly where to do it,
       but being wrong here would not stay on one record — a wrong correction teaches a rule
       that misfires on every invoice after it. Open it and decide."

GET  /api/v1/atlas/actions
→ the refusal is in the log, succeeded=false, attributed and timestamped
```

**The seeded row was removed afterwards.** It existed to give the mock tenant's screen something to
act on and is not test data anyone should find later.

### 17.12 What Slice C deliberately does not do

- **No batch endpoint, no batch action, no `assert_batch_acceptable()` caller** (D42). §12.5's and
  §14.8's caveat is unchanged: the guard is proven, the endpoint that must call it does not exist,
  and §11's "an outbound message cannot be sent by a batch endpoint" is still asserted against the
  guard rather than an endpoint.
- **No notification, channel, digest or interrupt** (D36). Nothing in this slice sends anything.
- **No escalation** (D37), **no background job, event hook, cron or absence clock** (D38). Every
  function here runs when it is called, on the open-the-app path.
- **No behaviour-based forecast.** §7.5's highest-value item is not built, and every forecast line
  states the assumption it used instead of implying otherwise.
- **No automatic false-negative detection** (D34). There is no miss rate and no detector.
- **No rule evaluation.** `atlas_memory_rules` records what ATLAS believes; nothing in this backend
  evaluates those rows automatically, and that is stated rather than implied.
- **The "you missed this" affordance is on ATLAS lines only.** D34 says "on any record"; the
  endpoint takes any `entity_kind`/`entity_id`, and the invoice, trainer and document screens do
  not carry the control yet. That is remaining FE work, not a backend gap — filed as **FE Gap 703**.

### 17.13 What this slice found to be wrong in the specs, flagged rather than rewritten (hard rule 4)

1. **§12.2's "There is no confidence number and no `actionable` flag" is still true, but §12.6's
   list of what Slice A does not do now reads as a to-do list that is finished.** Ranking, assignment
   and collapse, memory and forecast levers are built as of this section; §12.6 is left as written
   because it is the record of what Slice A's boundary was.
2. **§14.6's sentence "the endpoints that perform them do not all exist yet" is now precise in a way
   it was not meant to be.** Two of the ten exist; the other eight are ruled never to exist (D50),
   not merely unbuilt. The sentence reads as a deferral and it is a ruling. Left as written; §17.3
   is the correction.
3. **§10's task list and §13.3's revision both still show 34.7 as "assignment and collapse".** D50
   and D51 made 34.7 primarily *the action set*, with collapse as one part of it. The tasklist for
   this slice reflects that; the spec's two task tables do not, and are left alone.
4. **§7.3's "(Q5: where a list becomes a queue)" reads as open.** It was ruled by D41 and is
   recorded in §13.1; the §7.3 sentence still carries the question mark.

---

## 18. As built — what real data exposed, and what the tests were asserting instead (2026-09-18)

**Additive, per hard rule 4.** Nothing above this line is rewritten. §§1, 2.2, 5.3, 7.3 and 7.5 all
stand as written — the defects below are places where the code did not implement them, not places
where the design was wrong. Where a section's own words turned out to be what made a bug findable,
that is noted; the words did not change.

This section closes **BE Gaps 704, 705 and 706** and records four of the six defects in
`.claude/tasklists/senior-dev-atlas-real-data-fixes.md`. The founder's instruction was that these
are the feature being finished, not a separate gap pass, which is why they are recorded here and
not only in the tracker.

### 18.1 The finding that matters more than any individual defect

The VPI demo tenant — 26 invoices through real Doc Intelligence and real GPT-5.6 Luna — was loaded
and the work screen driven for three roles. **Every one of the six defects passed 149 backend tests
and 155 frontend tests.** They were found by one person looking at one screen for about ten minutes.

That is not a story about missing coverage. The coverage was there and it was dense. It is a story
about what the assertions were *about*:

| The suite asserted | Nobody asserted |
|---|---|
| `areas[]` carries the right `line_ids` | that a line appears on the screen **once** |
| `AreaRow.count == len(line_ids)` | that the count equals **the work a person has to do** |
| `Why.doubt` is a non-empty string when a line is uncertain | that the string is **a sentence** |
| every money token in prose is declared | that the declaration was **honest** |
| `CashPosition.payable_due` equals the sum of its fixture | that the fixture was **the right population** |
| the generated SQL parses and runs | that it **can return the right answer at all** |

Every row is the same mistake: **the test was written against the shape of the thing, and the defect
was in its meaning.** A shape test cannot fail for a wrong meaning, so it passed — and the passing
was then read as evidence.

Two consequences worth stating because they are actionable rather than rhetorical:

1. **A test written from the implementation inherits the implementation's misconception.** The
   cash-position test asserted `payable_due == 50000` against a fixture holding exactly one
   `AUDIT_REQUIRED` invoice. It was a correct test of the wrong rule and would have passed forever.
   Its replacement (`test_the_cash_line_sums_the_whole_open_book_not_the_decision_queue`) derives
   its expected figure from the statuses named in the test, so the test states the rule instead of
   echoing the code.
2. **A guard that can be satisfied by two different shapes is not a guard.** See §18.2.

### 18.2 BE Gap 704 — a data structure in a sentence, and a laundered guard

**What a user read**, on every duplicate-flagged invoice, on every role's screen:

> `{'id': 'ad637a2e2d924a0aa3175b6f3409b427', 'type': 'possible_duplicate', 'message': 'Possible duplicate: Rajesh Steel Corporation invoice RAJ-2008 (ID: d5869da2-...) has the same date and total (437,190.00) but a different number (RAJ-2009). Check whether this is a re-issue.', 'severity': 'warning'}`

**The source** was one expression: `alerts = [str(a) for a in (inv.sa_alerts or [])]`. `sa_alerts`
is JSONB and holds **dicts**, not strings, so `str()` produced a Python repr.

**The part worth recording is not that — it is how it got past §5.3.** The same line declared
`references` of `["#RAJ-2009", "637", "2", "2", "924", "0", "3175", ...]`: the digit runs of the
alert's UUID, produced by running the contract's own tokeniser over the stringified dict.
`assert_no_undeclared_numbers()` was therefore satisfied **by construction**. The emitter met the
letter of "never invents a number" by declaring the noise, and no strengthening of that check would
have caught the line, because the check was never failing.

This is the failure mode CONVENTIONS hard rule 3 names, in an unusual form: not a prompt rule
standing in for a control, but a real control **satisfied by a shape it was not written about**.

**Fixed in two places, deliberately:**

- **The source.** `atlas_skills._alert_prose()` takes the alert's `message` — the field a person is
  meant to read — and strips the `(ID: <uuid>)` parenthetical, which is storage, not content. This
  is the same call `agents/query_agent.render_alert_cell()` already makes for the identical column
  in a chat results table (Gap 508); the two agree and neither imports the other. The line's
  references are now `["#RAJ-2009", "2008", "437,190.00", "2009"]` — four real identifiers.
- **The guard.** `atlas_contract.assert_no_structure_in_prose()` refuses `{'`, `{"`, `':`, `":` and
  `[{` in **any** prose field on any line, and runs **before** the number checks in
  `validate_recommendation()` so a caller is told "that is a dict" rather than being told about one
  of the UUID fragments inside it — which describes the symptom and invites exactly the fix that
  shipped the defect. The marker list is narrow and literal rather than a judgement about whether a
  string "reads like prose", for the same reason every other check in that module is: a judgement is
  what a model answers differently on each run.

`test_the_line_that_shipped_is_now_refused_by_the_contract` asserts both halves. It first calls
`assert_no_undeclared_numbers()` on the exact line that shipped and asserts it **passes**, then
asserts the new guard rejects it. The old check being happy is the evidence, not a caveat.

### 18.3 BE Gap 705 — the forecast summed the wrong population

**What a user read:** *"Over the next 30 days you are committed to Rs 5,17,146.80 across 2
invoice(s), and expecting Rs 0.00 across 0."*

**What was true**, by direct SQL over the same rows: Rs 16,24,588.60 across 11 payables and
Rs 42,50,646.00 across 10 receivables.

§5.3 was already right about the cost: *"Wrong number — the most damaging. Trust in numbers is
binary and does not recover."* A CFO reading that line would have judged the month owing a third of
what they owe and being owed nothing at all.

**Two independent population bugs, one on each side:**

| Side | Was | Is | Why the old one was wrong |
|---|---|---|---|
| Payable | `status in _AWAITING_AUDIT` — `AUDIT_REQUIRED`, `REVIEW_LATER` | `status in _OPEN_PAYABLE` — plus `COMPLETED`, `NEEDS_RESUBMISSION` | "Awaiting a decision" is a queue an auditor owns. A `COMPLETED` invoice is not a decision anybody owes; it is a bill the business owes, which is the question the cash line is asked. On the VPI tenant this hid nine of the eleven payables |
| Receivable | `status == "SENT"` | `status in _OPEN_RECEIVABLE` — `VERIFIED`, `NEEDS_REVIEW`, `SENT` | `SENT` is reached only by a human pressing confirm-send in this app. Most businesses send the invoice from their own system and never record the step here, so the line reads **Rs 0.00 expected** on almost any real tenant. A receivable exists when the invoice was raised, not when a button was clicked |

**The line's own `computation` string had been describing the bug accurately for a day**: *"the 2
invoice(s) **awaiting a decision** and due within 30 days, added up"*. §12.4's requirement that a
COMPUTED figure name its computation is what made this diagnosable from the screen in seconds rather
than from a debugger — the one part of this story where the design did its job. Both strings are
updated to name the whole open book, which is what the figures beside them now sum.

`services/atlas_forecast.py::shortfalls()` held **a third** population (`_OWED`, its own tuple,
excluding `COMPLETED`), so the day-by-day walk and the position line were reading two different
books on one screen. It now imports the same two constants. Two modules each deciding what an open
payable is were two answers waiting to disagree, and they already did.

**What deliberately did not change:** the assumption. This is still a due-date forecast and still
says so (§7.5: "deterministic and honest are separate properties"). Fixing the population does not
turn it into the behaviour-based forecast §7.5 calls the highest-value item.

**One number in BE Gap 705's own text needs reading carefully**, recorded here rather than corrected
there: the gap says "real payables of INR 1,107,441.80" and "INR 3,449,780.00 of real outbound
receivables". Those are the amounts the old line **missed** — the nine `COMPLETED` payables, and the
seven receivables due on 17 Sep — not the totals. The totals, which the line now prints and which a
direct SQL sum confirms, are Rs 16,24,588.60 and Rs 42,50,646.00. The difference is the
Rs 5,17,146.80 the old line did show, plus three receivables due later in the same window.

### 18.4 §2.2 and D20 — collapse fired for a tenant with one person working

Every area on the Admin's screen read **"someone else is working this"** on a workspace where nobody
else was working anything.

**The predicate asked whether a capability existed, not whether a person held the work.**
`capabilities_held_by_others()` returned a capability whenever any other `User` row in the tenant
held the grant. D20's words are *"items another grant-holder is **actively working**"*, and §2.2
already says a solo owner collapses nothing *"because nobody else is handling anything"*. Holding a
grant is a permission; handling something is an act. The code treated them as one fact.

**What "actively working" can mean with the evidence this product actually has.** ATLAS has no
assignment and no presence — there is no "Priya has claimed this" anywhere, and D38 forbids the
background job that would maintain one. What it has is a record of what people did:
`atlas_action_log` (§5.3's never-writes-silently — attributed and timestamped) and
`atlas_dismissals` (D49, per person). So `capabilities_worked_by_others()` asks: has another user
**touched a line currently in this area**, within seven days? Nothing else in the schema knows.

**With no evidence the bias is to collapse nothing**, and that direction is the safe one. An Admin
shown a plain list sees every line, which is §2.2's "coverage is total". An Admin shown a collapsed
row is told a colleague has it in hand — and if that is false, the work quietly disappears, which is
the outcome §2.2 exists to prevent.

A smaller thing fell out of the same change: the old function compared `TenantContext.user_id`
against `User.clerk_user_id`, two identifiers not guaranteed to be the same string. The new one
compares like with like, against the same column the dismissal store already keys on.

### 18.5 §2.2's count counted lines, not work

**"Decisions — 5 pending"** on a tenant with **two** invoices awaiting a decision. The five were two
approve lines, two "attach the quotation" doubt asks *about those same two invoices*, and
`audit-cash-INR` — the cash position tile, which is not pending and is not a decision.

Two rules, both stated once in `services/atlas_collapse.py` so that the count, the threshold and the
grouping cannot each decide differently:

1. **A line about a record is work; a line whose `what.entity_kind` is `"tenant"` is not.** The
   position, the runway and the shortfall warning are standing facts — always true, never pending,
   never somebody else's job to clear. They are excluded from an area entirely and stay in the plain
   list, which is also the only reading of "nothing withheld" that survives an Admin's own cash line
   being folded away from them. The tile was swept into the decisions queue because it declares
   `AtlasCapability.AUDIT` — correctly, per D44 — and grouping by capability alone cannot tell a
   position from a decision.
2. **Two lines about one invoice are one piece of work.** The count is over distinct
   `what.entity_id`. Every line is still in `line_ids`, so the row expands to everything ATLAS has to
   say about those subjects; the count is about the sentence, not about the contents.

Aging follows the same rule — a subject is as old as its **oldest** line, and of unknown age only
when no line about it states a `since`. Per-line aging had a single invoice reporting "1 untouched,
1 of unknown age" beside itself.

The area now reads **"Decisions — 2 pending."**

### 18.6 BE Gap 706 — SQL that could not return the right answer

"Which invoices need my attention?" on the VPI tenant returned **two**. The correct answer is
**three**: `RAJ-2009` and `NAT-2007` (possible duplicates) and `VPI-OUT-2014`, whose alert reads
*"Subtotal (409500.00) + Tax (73710.00) does not match Grand Total (483850.00)"*.

The generated SQL filtered `LOWER(CAST(sa_alerts AS TEXT)) LIKE LOWER('%duplicate%')`. That query
**structurally cannot** return the third invoice, whatever the data says — so this was never a
retrieval-quality problem and never a model problem.

**Where the filter came from.** Not the model's imagination: it is the literal example the SQL
prompt's rule 6 gave for casting a JSONB column before `LIKE`. An example is the strongest
instruction in a prompt, and that one quietly taught *attention means duplicate*.

**The fix keeps correctness out of prose** (hard rule 3), using the mechanism this codebase already
has for it — `link_question_to_schema()`, the deterministic pre-pass that states facts about the
question before the model runs:

- `_ATTENTION_PATTERN` detects the question class by regex, in code.
- `_ATTENTION_PREDICATE` **is** the answer, as a WHERE clause:
  `(sa_alerts IS NOT NULL AND CAST(sa_alerts AS TEXT) NOT IN ('null','[]','{}')) OR status IN
  ('AUDIT_REQUIRED','NEEDS_REVIEW','NEEDS_RESUBMISSION')`. The `OR` is the whole fix: an invoice can
  be flagged by the pipeline **or** be sitting in a state a human must clear, and neither implies the
  other.
- Rule 6's example no longer carries a domain word at all — it reads
  `LIKE LOWER('%<the exact word the user used>%')` — and says explicitly that the shape must not be
  used for an attention question.

An execution-time SQL rewriter was considered and rejected: that is the Gap 253 pattern this repo
deleted once already, and CONVENTIONS records it as the basis of hard rule 3.

Verified two ways: `_ATTENTION_PREDICATE` run directly against the VPI tenant returns exactly the
three ground-truth invoices, and the question re-asked live through
`POST /chat/sessions/{id}/message` answers *"Three invoices need attention"* and names all three
(§18.8).

### 18.7 What did not change, and why

- **`areas[]` still carries every line it stands for.** The double-render was fixed on the frontend,
  not by making `areas` a truncation of `lines`. Collapse **groups, never removes** (D20/D41), and
  that property is exactly what makes a row openable in place with no second request. FE Feature 23
  §16 carries the argument for why the seam belongs on that side.
- **The forecast still assumes due dates.** §7.5's better forecast is unbuilt; only the population
  was wrong.
- **No new table, no new column, no migration.** The collapse predicate reads two tables that
  already exist because D49 and §5.3 required them.

### 18.8 Verification

Real Postgres (`127.0.0.1:5433/invoice_db`, BE Gap 697), real Azure OpenAI, VPI demo tenant
`00000000-0000-0000-0000-000000000000` — **not reseeded**; the same 26 invoices from the 2026-09-18
ingestion run.

| Check | Command | Result |
|---|---|---|
| Contract guard | `pytest tests/test_atlas_contract.py -q` | 39 passed |
| Emitters and the cash population | `pytest tests/test_atlas_skills.py -q` | 11 passed |
| Collapse and the predicate | `pytest tests/test_atlas_ranking.py -q` | 26 passed |
| Attention linking | `pytest tests/test_c4_schema_linking.py -q` | 23 passed |
| Payable/receivable vs. a direct SQL sum | sums over `_OPEN_PAYABLE` / `_OPEN_RECEIVABLE` on the VPI tenant | 11 / Rs 16,24,588.60 and 10 / Rs 42,50,646.00 — identical to the rendered line |
| Attention predicate on real data | `_ATTENTION_PREDICATE` run directly | 3 rows: `VPI-OUT-2014`, `NAT-2007`, `RAJ-2009` |
| The chat answer, live | `POST /chat/sessions/{id}/message` | "Three invoices need attention", all three named |

**Falsification, not just green.** Each new backend behaviour was re-run against the pre-fix code to
confirm the new test fails: reverting `_OPEN_PAYABLE`, `_OPEN_RECEIVABLE` and `_alert_prose()` turned
three of the eleven `test_atlas_skills.py` tests red, with the cash assertion reporting
`Decimal('449190.0') == Decimal('1559631.8')`. A test that passes both before and after a fix is not
evidence of the fix, and this repo has shipped that mistake before.

Live evidence — the payload, screenshots per role and the re-asked chat questions — is filed under
`docs/test_evidence/vpi_demo_atlas_2026-09-18/` alongside the original captures, so the before and
the after sit in one directory.

### 18.9 One thing recorded, not fixed — the demo script and the product have diverged

`showcase/vpi_demo/README.md` Section 8 and `docs/atlas_vpi_scenario_day1_30.md` describe
**Feature 33**: Discover firing at 10 documents, `docs_seen`/`docs_required`, five onboarding
questions, convention proposals answered inline, weekly cash-shortfall runs, FP&A cards, and
`ops`/`exec` clearance on chat.

**§8 of this document records, in its own words, that Feature 33 was never built.** Feature 34
replaced it with a different contract — `/atlas/lines`, capability-scoped skills, the claim-to-witness
rule, no clearance, no FP&A cards, no onboarding questionnaire. The demo script and the running
product therefore describe two different products, and most of Section 8's specific expectations
cannot be reproduced against what is live — not because anything is broken, but because that product
does not exist.

**Neither document is rewritten** (hard rule 4, and neither is this feature's to edit). It is flagged
because the risk is specific and near-term: the VPI README reads as a **test script**, so anyone
running it against the live system will record failures for capabilities that were deliberately never
built. Whether the scenario doc is retired as history or rewritten against Feature 34 is a founder
call; it is not a code change either way.
