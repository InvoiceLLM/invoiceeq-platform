# ATLAS — discussion and decisions

**A running doc.** ATLAS design decisions are taken in conversation and land here
before any code is written. Nothing in this file is built unless an update says so.

**How to use it**
- **Decisions index** and **open questions** are the live registers — read these first.
- **Update log** is append-only, newest last. One entry per surface or topic discussed.
- A decision that is later reversed is **struck through in the index and kept**, with
  the reversing decision's id beside it. Decisions are not deleted.
- When an update becomes buildable it is converted to a tracker Gap pair
  (`be_features_tracker.md` / `fe_features_tracker.md`) and the entry records the ids.

**Related:** `feature_33_analyst_agent.md` (the spec these decisions change),
FE Feature 22 spec (the four surfaces).

---

## Decisions index

| id | Date | Surface | Decision | Built? |
|---|---|---|---|---|
| D1 | 2026-09-17 | Today | Filter findings by the capability needed to act, not by `ops`/`exec` clearance | No |
| D2 | 2026-09-17 | Today | Cash, forecast, runway and FP&A are Admin-only | No |
| D3 | 2026-09-17 | Today | Zero **grants** → empty Today. Not zero *role* — a no-role user with `can_load` is a Loader and sees document work | No |
| D4 | 2026-09-17 | Today | Non-actionable lines are cut. If it needs no action, it is not Today | No |
| D5 | 2026-09-17 | Today | ScenarioControl cut from the cash section | No |
| D6 | 2026-09-17 | Today | `can_send_invoices` merges into `can_audit`. **Reverses BE Gap 405** (least-privilege default) — deliberate, not drift | No |
| D7 | 2026-09-17 | ATLAS | **ATLAS is a per-role guide, not an automation engine.** Every line is a *recommendation* carrying a reason, a one-click action, and a way to verify it — not a finding | No |
| D8 | 2026-09-17 | ATLAS | **ATLAS never acts alone.** One click accepts, and a click may accept a batch. Anything offered must therefore be reversible | No |
| D9 | 2026-09-17 | Structure | **One work screen per role, chat attached to every line.** Records and Settings are reachable from a menu, not permanent furniture | No |
| D10 | 2026-09-17 | Structure | **The four-surfaces project is superseded by D9.** PrimaryNav, the redirect table and `NEXT_PUBLIC_FOUR_SURFACES` are to be deleted. Supersedes the FE Gap 501 ruling (Records detail view) taken earlier the same day | No |
| D11 | 2026-09-17 | ATLAS | ATLAS runs **setup and autopilot configuration as a conversation**, not a form | No |
| D12 | 2026-09-17 | ATLAS | ATLAS **prunes its own noise**: an alert dismissed repeatedly becomes a recommendation to remove it | No |
| D13 | 2026-09-17 | Roles | The **Loader role is designed toward elimination**. A human whose job is uploading documents is a symptom of failed ingestion, not a user to serve | No |
| D14 | 2026-09-17 | Admin | An Admin's screen serves **four needs and no others**: don't lose money · don't run out of money · don't let it stall · keep the setup right | No |
| D15 | 2026-09-17 | Admin | Forecasting appears as **a warning with levers**, never a chart — a date, a number, and the actions that close the gap. The forecast must **state what it assumed** (on-time payment vs historical behaviour) | No |
| D16 | 2026-09-17 | Skills | Keep `forecast_cashflow` and `detect_recurrence` on the daily screen. The other seven FP&A skills (P&L, both margins, budget variance, expense trend, scenario) **move off it** — asked for in chat, not shown unprompted. Not deleted | No |
| D17 | 2026-09-17 | Settings | Settings are **maintained by ATLAS from the data**, never an upfront wizard. A setting change is proposed when the pattern is visible in the customer's own data, with one click to accept | No |
| D18 | 2026-09-17 | Skills | **Reconciliation becomes a first-class skill set** — there is currently no recon capability among the 16. Vendor statement recon is the first to build | No |
| D19 | 2026-09-17 | Skills | **The claim → witness rule** governs every document request: ATLAS asks for a document only when a specific claim is in doubt, it lacks the witness, and the answer is worth the interruption | No |
| D20 | 2026-09-17 | Admin | **The collapse rule.** The Admin sees everything, but items another grant-holder is working collapse to **one row per area** ("Corrections — 34 pending, 3 untouched for a week"), openable for detail. Coverage is total; volume is not. A solo owner collapses nothing, because nobody else is handling anything | No |
| D21 | 2026-09-17 | Trainer | Trainer gets four: **impact-ranked** fixes · the **correction already drafted** · **proof the teaching worked** · **bad rules surfaced**, not only missing ones | No |
| D22 | 2026-09-17 | Loader | Loader gets four: **stuck vs in flight** · **why it failed and the fix**, not the fault · **what should have arrived and didn't** · **the way out of the job**, with the automatic share as the scoreboard | No |
| ~~D23~~ | 2026-09-17 | Hooks | **Three triggers, three mechanisms.** Events run the cheap checks immediately · a **clock** catches absence, because nothing fires for a thing that did not happen · expensive work (forecast, ranking, recon) recomputes **when the user arrives** | **Reversed by D38**, kept |
| D24 | 2026-09-17 | Cold start | Day one teaches the **working relationship per role**, not the screens: what your job looks like with ATLAS · **how to verify me** · what I will be able to do as I learn. The historical import becomes an **offer with a stated payoff**, never an onboarding gate | No |
| D25 | 2026-09-17 | Cold start | **Teach once, then keep teaching in place** — capabilities are explained at the moment they first become relevant, not dumped on day one | No |
| D26 | 2026-09-17 | Trust | **Uncertainty is stated in words, never a number, and never batched.** "This might be a duplicate — same amount and vendor, different invoice number." **Batching is a claim of certainty**, so only confident items may be batched | No |
| ~~D27~~ | 2026-09-17 | Notifications | **Money at risk AND a closing window** earns an interrupt — nothing else. Two tiers only: rare urgent, plus an optional digest. **ATLAS caps its own interrupts**; the notification carries the decision, never a summons to log in | **Reversed by D36**, kept |
| D28 | 2026-09-17 | Boundaries | ATLAS **never**: moves money · sends outside the company unseen · deletes · invents a number · writes silently · claims certainty it lacks · learns a permanent rule from one instance | No |
| D29 | 2026-09-17 | Boundaries | **Reversible may be batched. Irreversible is individual. Anything leaving the company is individual and read in full** — including every chase email | No |
| D30 | 2026-09-17 | Ranking | Rank by **money at stake × how soon it stops being fixable** — the same test as D27, applied to the screen. Everything below the cut stays reachable, never deleted | No |
| D31 | 2026-09-17 | Memory | **Everything ATLAS learns becomes a visible, editable rule** in plain language — from an answer, a dismissal, a correction or a chat reply. **Nothing is remembered invisibly**, so a wrong lesson can be found and removed rather than haunting the system | No |
| D32 | 2026-09-17 | Scope | **Multi-currency, single entity.** Cash and forecast are per currency and **never blended** — a total in mixed currency is a wrong number (D28). No entity switcher | No |
| D33 | 2026-09-17 | Structure | **Records and Settings stay exactly as they are, behind a menu.** No redesign, no chat integration, nothing rebuilt. **Lookup is a search box, not an agent's job** | No |
| D34 | 2026-09-17 | Trust | **Q13 ruled: a miss is detected by the user reporting it.** A "you missed this" affordance on any record, feeding D31's memory. Accepted that this under-reports badly — a false negative is invisible by definition — because the signal is high quality when it does arrive, and it costs no LLM spend on quiet invoices. No sampling job, no self-audit | No |
| D35 | 2026-09-17 | Ranking | **Q14 ruled: no quiet floor.** ATLAS never suppresses on amount. D30's ranking pushes small uncertain items to the bottom where they stay reachable — the literal reading of "ATLAS ranks, it does not hide" | No |
| D36 | 2026-09-17 | Notifications | **Q11 ruled: no push channel of any kind. ATLAS speaks only when the user opens the app.** Reverses D27 — the urgent tier, the digest, the self-limiting interrupt cap and the channel question all go with it | No |
| D37 | 2026-09-17 | Admin | **Q12 ruled: no escalation mechanism.** D20 already makes the Admin the superset, so an unhandled line is visible without one; the aging figure on the collapsed row ("3 untouched for a week") carries the signal | No |
| D38 | 2026-09-17 | Hooks | **Q9 ruled: everything computes when the user opens the app.** Reverses D23 — no event hooks, no absence clock, no background job. Absence becomes a query run on sign-in, not a clock | No |
| D39 | 2026-09-17 | Skills | **Q10 ruled: claims and the vendor baseline are derived at check time**, not stored. No new tables. Claims come off extracted fields via the fixed field→witness mapping (D19); the baseline is computed from that vendor's own invoice history when a check runs | No |
| D40 | 2026-09-17 | Memory | **Bounds D31.** A derived baseline is made visible by **showing its working on the line** — "4× their usual ₹40–60k across 14 invoices" — rather than stored as an editable rule. D31 governs lessons ATLAS was *told* or inferred as a rule; an observation recomputed from the customer's own invoices is not one, and fixing the invoices fixes it | No |
| D41 | 2026-09-17 | Structure | **Q5 ruled: above a volume threshold the work screen collapses by area**, using D20's existing mechanism, expanding in place. No separate queue mode and no second concept | No |
| D42 | 2026-09-17 | Boundaries | **Q6 ruled: nothing is batchable in v1.** Individual accept only. Batch accept and its undo are deferred until real usage shows which line types are safe. **Narrows D8** — the one-click promise stands, the batch half does not ship. D29's principle is unchanged and governs when batching returns | No |
| D43 | 2026-09-17 | Loader | **Q7 ruled: a tenant may have many ingestion sources.** `uq_autopilot_config_tenant` is dropped and ingestion paths carry a source id. **Unblocks D13** — "most invoices arrive by themselves" was unreachable for a customer receiving in both Drive and a shared mailbox | No |
| D44 | 2026-09-17 | Today | **Q1 ruled: Auditors see the full cash position, forecast and runway.** **Reverses D2 for the Auditor.** §2.3's bounded cash line — decision consequence without the position — is removed; there is one forecast and one view of it. FP&A and margin analytics are untouched and stay chat-only (D16) | No |
| D45 | 2026-09-17 | Structure | **Q2 ruled: records stay tenant-wide**, upholding BE Gap 665 and D33 — lookup is a search box, not a permission system. **Adds a requirement:** a Trainer's correction line shows the invoice **before and after** the fix, which is the concrete single-document form of D21's "proof the teaching worked" | No |
| D46 | 2026-09-17 | Hooks | **Accepted consequence of D36 + D38:** a customer who does not sign in is told nothing at all, including absence — which D23 called the highest-value category in every role. A vendor who stops billing goes unnoticed until someone looks. Recorded as a deliberate trade, not an oversight | No |
| D47 | 2026-09-18 | Trust | **Verify does not attach the document — it tells the user to attach and compare in chat.** Closes FE Gap 640 without a new attachment endpoint: the line opens chat with its question seeded and says to attach the document there. The FE never re-uploads a copy of a document the tenant already holds to make a promise look kept | **Yes** (2026-09-18; BE Gap 693, FE Gap 640 closed) |
| D48 | 2026-09-18 | Structure | **A toggle beside the notification bell switches between the existing tabbed screen and ATLAS mode.** **Partially reverses D10**, which deleted the classic-layout toggle on the grounds that there was no longer a duality to toggle between — there is one again, because ATLAS is an added surface, not a replacement. The existing screens are not removed | **Yes** (2026-09-18; FE Gap 694) |
| D49 | 2026-09-18 | Today | **Every line carries a dismiss button, and a dismissal persists.** Lines are recomputed on every open (D38), so without this a line the user has already handled — for example by doing the comparison in chat per D47 — returns on the next sign-in. Dismissal is keyed on the recommendation id, which is deterministic (`audit-approve-<invoice id>`), so it matches the same line across recomputes | **Yes** (2026-09-18; BE Gap 695, FE Gap 696) |
| D50 | 2026-09-18 | Boundaries | **ATLAS suggests corrections and requeues; it never performs them.** `apply_field_correction` and `requeue_invoices` open the right screen with the context, and the person does it. **Narrows D8 further** — one-click acceptance is for the Auditor's decision, not for teaching the extractor or moving work through the pipeline. A wrong correction teaches a rule that then misfires on every future invoice, and a wrong requeue costs pipeline work nobody asked for | No |
| D51 | 2026-09-18 | Loader | **`retry_ingestion_source` is performable — one click retries.** Re-running a sync is idempotent: it re-reads the folder or mailbox and both dedup layers absorb anything already ingested, so a second run writes nothing new. The Loader's job is unsticking ingestion, and D22 designs that role toward elimination, so this is the one action that actually shortens their work | No |

## Open questions

| id | Raised | Question | Current thinking |
|---|---|---|---|
| ~~Q1~~ | 2026-09-17 | ~~Does an Auditor need to know cash is tight when chasing an overdue invoice?~~ | **Ruled: the Auditor sees the full position.** D2 reversed for that role (D44) |
| ~~Q2~~ | 2026-09-17 | ~~BE Gap 665 under the new model: if an Auditor never sees cash findings, should they still fetch any invoice PDF directly?~~ | **Ruled: records stay tenant-wide**, plus the Trainer's before/after view (D45) |
| ~~Q3~~ | 2026-09-17 | ~~Do the `clearance` columns get dropped, or left unused?~~ | **Moot.** No `clearance` column exists in `models.py` or any migration — Feature 33 was never built (—) |
| ~~Q4~~ | 2026-09-17 | ~~What does "ATLAS does it for the user" mean concretely?~~ | **Resolved by D7 / D8** — it does not act for the user. It recommends, explains, and acts on one click |
| ~~Q5~~ | 2026-09-17 | ~~At what volume does a list become a queue? Customers range from ~20 invoices/month to thousands~~ | **Ruled: collapse by area above a threshold**, reusing D20's mechanism (D41) |
| ~~Q6~~ | 2026-09-17 | ~~How is a batch acceptance undone? D8 requires reversibility, and "approve all 8" is eight actions~~ | **Ruled: nothing batchable in v1.** Individual accept only; batching deferred (D42) |
| ~~Q7~~ | 2026-09-17 | ~~`uq_autopilot_config_tenant` is UNIQUE on `tenant_id` — **one ingestion source per tenant**. Deliberate, or where it stopped?~~ | **Ruled: many ingestion sources per tenant.** The unique constraint is dropped (D43) |
| ~~Q8~~ | 2026-09-17 | ~~`ENABLE_ANALYST_ACTIONS` defaults False, so all six action capabilities are dead. Caution, or unfinished?~~ | **Moot.** No `ENABLE_ANALYST_ACTIONS` flag exists in the codebase — Feature 33 was never built (—) |
| ~~Q9~~ | 2026-09-17 | ~~Does ATLAS run per-event, or recompute when a user signs in?~~ | **Ruled: everything computes on open.** No background work of any kind (D38) |
| ~~Q10~~ | 2026-09-17 | ~~What is a "claim" concretely, and where does the vendor baseline live?~~ | **Ruled: derive both at check time.** No new tables; the working is shown on the line (D40) (D39) |
| ~~Q11~~ | 2026-09-17 | ~~Which channel carries the urgent tier — WhatsApp, email, or both?~~ | **Moot: no push channel.** ATLAS speaks only when the app is opened (D36) |
| ~~Q12~~ | 2026-09-17 | ~~How long before unhandled work escalates from the grant-holder to the Admin?~~ | **Ruled: no escalation.** The Admin is already the superset (D20) (D37) |
| ~~Q13~~ | 2026-09-17 | ~~**False negatives have no feedback loop.** A user never learns what ATLAS failed to mention. How is a miss ever detected?~~ | **Ruled: the user reports a miss.** Under-reporting accepted (D34) |
| ~~Q14~~ | 2026-09-17 | ~~What is the stake threshold below which ATLAS stays quiet when uncertain?~~ | **Ruled: no floor.** Rank instead, never suppress on amount (D35) |

---

# Update log

## 2026-09-17 — Today: by capability, not by clearance

**Decisions:** D1–D6 · **Scope:** the Today surface only · **Status:** decided, nothing built.
Feature, code and test analysis deliberately deferred — this entry is the input to it.

### 1. The decision in one sentence

Today stops filtering findings by the `ops` / `exec` clearance binary and starts
filtering by **the capability a user needs in order to act on the line**.

### 2. Why

`clearance` is not a permission system. It is one line, derived from role:

```python
# dependencies.py:766
clearance="exec" if role == "Admin" else "ops",
```

The product already has a richer model than the binary that replaced it:

```python
# models.py ROLE_PERMISSION_DEFAULTS
"Admin":   {"can_train": True,  "can_audit": True,  "can_load": True,  "can_send_invoices": True},
"Trainer": {"can_train": True,  "can_audit": False, "can_load": False, "can_send_invoices": False},
"Auditor": {"can_train": False, "can_audit": True,  "can_load": False, "can_send_invoices": False},
NO_ROLE:   {"can_train": False, "can_audit": False, "can_load": False, "can_send_invoices": False},
```

ATLAS ignores all four flags and collapses them to Admin-or-not. Consequences
in the shipped code:

- **Trainer, Auditor and no-role users get byte-identical Today screens.** Three
  different jobs, one list. Each sees roughly half a list that is not theirs,
  with nothing marking which half.
- **A zero-permission user reads everything.** `NO_ROLE` exists as the safe
  fallback for an unmapped IDP role (BE Gap 337 routes `org:member`, `viewer`,
  `restricted` there). They cannot train, audit, load or send — but clearance
  gives them `ops`, so they receive every ops finding: vendors, amounts, what is
  overdue.
- **Every tenant runs the analyst loop twice.** `scripts/run_weekly_analyst.py:59-64`
  enqueues an `ops` pass and an `exec` pass per tenant per cycle, to produce two
  filtered views of largely the same list. Double the LLM spend for a binary.

The Admin Console already describes people by capability, not role — it renders
a user as the join of their grants ("Trainer, Auditor, Loader") or "View only"
(`invoice-fe/app/admin/page.tsx:87-94`, `:504-514`). **"Loader" is a grant, not a
role**; FE Gap 324 exists because the security page once listed it as a role.
So the capability model is the one the product already speaks.

### 3. What Today shows, per profile

Grants stack. A user with `can_audit` + `can_load` gets one merged list, not tabs.
Filtering is per line, so this falls out without extra work.

| Profile | Today shows |
|---|---|
| **Admin** | Everything: cash position, forecast, runway, FP&A, invoices, outbound, training work, document problems. Plus Upload, Run now, questionnaire card. |
| **`can_audit`** | Invoices to approve / reject / query; payment mismatches, duplicates, amount discrepancies; **outbound invoices to send or chase** (D6). No cash, no training work, no upload. |
| **`can_train`** | Extraction came out wrong; vendor unmapped or needs a template; a rule firing incorrectly; low-confidence fields needing a decision. No approvals, no cash, no uploads. |
| **`can_load`** | Missing documents ATLAS is waiting on; failed uploads; unreadable scans; connector / email ingestion errors. Upload button. Nothing else. |
| **no grants** | Empty state: "No tasks assigned. Ask your admin for access." |

**Cash, forecast, runway and the FP&A block are Admin-only** (D2). This is the one
thing the old `exec` clearance was genuinely protecting, and it is worth keeping —
as a capability rule, not as a column on six tables.

### 4. Footprint — what analysis will have to cover

Measured 2026-09-17 on `fix/f22-f33-gaps-624-638`:

- **366 `clearance` references across 24 non-test backend files**, plus 16 test files
- **7 non-test frontend files**, plus 6 test files
- Backend files carrying it: `agents/analyst_agent.py`, `agents/capabilities.py`,
  `dependencies.py`, `models.py`, `queue_worker/analyst_handlers.py`,
  `queue_worker/main_worker.py`, `routers/chat.py`, `routers/chat_attachments.py`,
  `routers/facts.py`, `routers/today.py`, `scripts/run_weekly_analyst.py`,
  `scripts/run_analyst_eval.py`, `services/clearance.py`, `services/business_profile.py`,
  `services/conventions.py`, `services/dependency.py`, `services/facts.py`,
  `services/forecast.py`, `services/insights.py`, `services/overlap.py`,
  `services/semantic_views.py`, `services/tenant_profile_rules.py`, and two migrations
- Frontend: `app/today/page.tsx`, `hooks/useToday.ts`, `lib/today.ts`,
  `components/today/todayContracts.ts`, `components/nav/PrimaryNav.tsx`,
  `components/chat/SessionRail.tsx`, `components/chat/cards/DecisionCard.tsx`,
  `types/chat.ts`

This is a large change. It is mostly **deletion**, which is why it is worth doing.

### 5. Shape of the work

To be verified by analysis, not taken as a plan.

**Build — one thing.** Each finding declares the capability required to act on it.
Whether that is a column on `Insight`, a derivation from `section` / `kind`, or a
lookup table is exactly what the analysis should decide. Today then filters on it.

**Delete:**

| Deleted | Notes |
|---|---|
| `ops` / `exec` clearance | `services/clearance.py`, the rank comparison in `routers/today.py`, the stream filter, the `clearance` column's *meaning* on six tables (see Q3) |
| The dual analyst run | `run_weekly_analyst.py` runs once per tenant. Halves analyst LLM cost |
| Non-actionable lines | The `actionable` flag, `QuestionnaireLines.tsx`, the server-side splice into `findings` / `summary`, and the flag plumbing added in FE Gap 507 |
| ScenarioControl on Today | `components/today/TodayList.tsx` cash section |
| `can_send_invoices` as an audience | Folded into `can_audit` for Today purposes |

**Feature docs to update:** `feature_33_analyst_agent.md` (the clearance model is
specified there, including the `§10 As built` section added this session) and the
FE Feature 22 spec. Per house rule the spec body changes, not only the tracker.

**Tests:** 16 backend and 6 frontend test files reference clearance. Expect most to
be rewritten rather than deleted — the cases they cover (a user must not see X)
remain valid, the mechanism changes. The cross-run collision tests added this
session are the ones to preserve most carefully.

### 6. Rollout note

Anyone currently landing in the `NO_ROLE` fallback goes from a full ops list to an
empty Today. That is the intended fix, but it is a visible overnight change for
real users — worth a note to customers rather than a silent deploy. D3's refinement
limits the blast radius to users with genuinely zero grants, who by definition
cannot act on anything they are currently being shown.

### 7. The half that does not exist (Q4)

The founder's model is two-sided: *show the user what they need to check and what
they can do* — and *for some work, ATLAS does it for them*. Everything above serves
the first half. **The second half has no representation in the code at all** — there
is no notion of a finding ATLAS handles rather than assigns, no record of what it
did on the user's behalf, and no way for a user to see or undo it. This is not an
incomplete implementation; there is no concept to implement against yet. It needs
its own discussion before it can be scoped.

---

## 2026-09-17 — What ATLAS is for: a guide per role, not four screens for everyone

**Decisions:** D7–D13 · **Status:** decided, nothing built. This entry **supersedes the
structural half of update 1** — the capability rules (D1–D6) survive intact; the
assumption that they land on a "Today tab" does not.

### 1. Customer shape, established by interview

Both ends of the market exist: **solo owners and small finance teams**, and volumes
range from ~20 invoices a month to thousands. So the product cannot assume a shape.
It must collapse to one person without feeling empty and work at volume without
becoming chaotic. **Consequence:** attention has to be earned per *item*, not per
*screen* — which is what D7 does.

### 2. What ATLAS is

Not an automation engine. **A guide that sits beside each role**: recommend the next
action, explain why, do it on one click, and teach the person to verify it themselves.

**Every line is a recommendation carrying four things** (D7):

| | |
|---|---|
| **What** | the invoice, the alert, the correction |
| **Why** | the reason, in the user's terms — "this vendor has never billed above ₹20,000" |
| **Action** | a single click, batchable — "approve all 8" |
| **Verify** | opens chat with the document already attached and the question pre-seeded |

That last one is how trust is built. Not by telling a user ATLAS is reliable — by
letting them check it once, cheaply, on the line in front of them.

### 3. Per role

| Role | Their job | How ATLAS helps |
|---|---|---|
| **Admin / owner** | Check on the business, not work in it | Runs setup as a conversation ("you get invoices from 12 vendors; shall I set up email ingestion for the 3 you receive most?"). Helps configure autopilot — which categories may proceed on one click, which always need them. Cash, forecast, what needs a decision, what was handled |
| **Auditor** | Decide on invoices | Triage before they arrive: "these 8 are clean and match history — approve all? these 3 need you, here is why. this one I would reject." Plus **noise pruning** (D12): "this alert has fired 40 times and you dismissed it 40 times — remove it?" |
| **Trainer** | Fix what the system got wrong | "This vendor's format changed, here is the correction I would make" — confirm rather than retype. And impact framing: "fixing this template fixes 60 future invoices" |
| **Loader** | Get documents in | **Design the role toward zero** (D13). Fix ingestion so nobody has this job; meanwhile show what is genuinely stuck versus what is in flight |

### 4. Structure (D9, D10)

A user signs in and lands on **their work** — recommendations shaped by their grants.
Chat is attached to every line, **not a tab**. Records and Settings are reachable from
a menu, not permanent furniture. An Auditor never sees navigation they do not need;
a solo owner simply receives all the line types on one screen.

**This supersedes the four-surfaces project (D10).** PrimaryNav, the redirect table
and `NEXT_PUBLIC_FOUR_SURFACES` go. Two consequences worth stating:

- **FE Gaps 501 and 502 close by deletion.** Nothing redirects away from
  `/invoices/review/:id` or `/trainer`, so neither orphans its affordances. The FE 501
  ruling taken earlier the same day (six affordances into a Records detail view) is
  **superseded** — recorded, not deleted, per this doc's convention.
- **The four-surfaces work is not wasted twice.** Today's line components, the Today
  contracts, the SSE stream and the chat deep links all survive D9 — they were the
  parts worth building. The navigation shell is what goes.

### 5. Trust model (D8)

ATLAS never acts alone. Every recommendation needs a human click; the click may accept
a batch. Autonomy is **not** earned automatically over time — that option was put and
declined. **Therefore everything offered must be reversible**, and a batch acceptance
must be undoable as a batch (Q6, which gates this).

### 6. What this vindicates, and what it condemns

**Vindicated:** the attachment scope, chat-with-attachment, and the Today line
components. They were the right instincts — they were simply never wired to the
moment a user needs them. Under D7 the "verify" affordance gives them that moment.

**Condemned:** the navigation project, the `ops`/`exec` binary, and the habit behind
both. The diagnosis from this session's audit — *everything was verified where it was
written and nowhere else* — has a design twin: **everything was built where it was
specified and nowhere a user stands.**

---

## 2026-09-17 — ATLAS for the Admin: four needs, and the skills that serve them

**Decisions:** D14–D19 · **Status:** decided, nothing built. Derived from the Admin
outward; the other roles follow from this one.

### 1. Correction on record

Earlier in this session "autopilot" was read as *agent autonomy* and treated as a
tension with D8. **It is not.** Autopilot is an existing product feature — **scheduled
bulk ingestion** from cloud folders, with a dedup ledger matching file ids and SHA-256
hashes (`tenant_autopilot_configs`, `tenant_autopilot_logs`). "Help the Admin configure
autopilot" means help them set up automatic document arrival. **D8 is unaffected**, and
autopilot is the mechanism by which D13 (eliminate the Loader role) is actually reached.

### 2. The Admin's four needs (D14)

| # | Need | What ATLAS produces |
|---|---|---|
| 1 | **Don't lose money** | Paid twice · billed above contract · a recurring charge nobody approved. One caught duplicate pays for the product |
| 2 | **Don't run out of money** | Cash position, what is due against what is landing, who is overdue. One line when it is fine, a real warning when it is not |
| 3 | **Don't let it stall** | Ingestion stopped four days ago · extraction failing on one vendor · the auditor's queue aging. **A thing that does not happen makes no noise** — only ATLAS can cover this |
| 4 | **Keep the setup right** | Settings are where a product is configured and the place nobody opens, so wrong defaults persist for years (D17) |

For a **solo owner**, needs 1 and 3 merge into their working list — the invoices to
approve *are* the money-at-risk check. For a **finance lead**, 1 and 2 are theirs alone
and 3 is about whether the team and the pipeline are moving.

**The test for any future line:** if it does not map to one of the four, it is analytics,
not work, and belongs somewhere the Admin goes looking — not on the screen they open
every morning.

### 3. Work is assigned, not only filtered

**Admin sees what only they can decide, plus what nobody else is handling, plus what
ATLAS did.** A line belongs to whoever holds the grant; it returns to the Admin only
when it goes unhandled. A finance lead never sees individual invoices — until twelve of
them have waited five days. A solo owner holds every grant, so "nobody else is handling
it" means everything. **One rule, both shapes, no special-casing.** Nothing is assigned
to anyone today.

### 4. Setup as ATLAS maintains it (D17)

Never ask upfront. An onboarding wizard asks an Admin to configure a product they have
not used, so they guess, and the guesses become permanent. Ask once the pattern is
visible in their own data:

- **People** — "Priya was added three weeks ago with no grants. She has seen an empty screen since."
- **Inbox** — "14 invoices this month came from the same Drive folder. Connect it?"
- **Checks** — "This alert has fired 40 times and been dismissed 40 times. Remove it?" (D12)
- **Notify** — "Nobody is alerted when ingestion fails." A settings gap that causes need 3
- **Plan / Security** — approaching a limit, rotation overdue

**Settings stops being a screen you visit** and becomes something ATLAS maintains with
you — consistent with D9.

### 5. Forecasting as a warning with levers (D15)

"Here is your 90-day cash curve" is a report. *"On the 22nd you are ₹1.2L short — chasing
these two invoices covers it, or delaying this payment covers it, or it resolves itself
if Sharma pays on time"* is work. Same numbers; only the second belongs on the screen.

Four things forecastable from data already held:

1. **What will actually arrive, not what is due.** Forecasts are wrong because they treat
   due dates as real. A customer who pays 12 days late, every time, is knowable from
   payment history. **A forecast built on promised dates is fiction.** Highest value item here
2. **What is coming that nobody typed in** — rent, insurance, subscriptions. `detect_recurrence` exists
3. **Where costs are drifting** — vendor price rises compounding quietly
4. **The shortfall with its levers** — a date, a number, three one-click actions

**The forecast must state its assumption** (D15). Deterministic and honest are different
properties; the existing forecast is the first and silent on the second.

### 6. Reconciliation (D18)

**There is no recon capability among the 16.** The parts exist as plumbing and nothing
exposes recon as something ATLAS offers to do.

| Recon | Note |
|---|---|
| **Vendor statement vs ledger** | The classic monthly job. Attach the statement in chat → matched / they show and we do not / we show and they do not / amount differs. **First to build** |
| Bank vs invoices | Payment with no invoice, invoice paid with no payment. `bank_matching` partly exists |
| **Short payments** | ₹48,000 against a ₹50,000 invoice — ATLAS names the likely reason (TDS, early-payment discount, disputed line) rather than flagging a gap |
| Lump-sum receipts | One payment covering six invoices — propose the allocation, confirm |
| Three-way match | Invoice vs PO vs delivery note. `purchase_orders` / `delivery_notes` are in `INPUT_KINDS`; the match is not built |

**Why this beats the FP&A seven:** recon is work a person is definitely doing today, by
hand, on a schedule, with documents they already hold, and it has a definite answer.
It also makes the attachment scope and chat-with-document mean something — the document
arrives at the moment it is needed, for a job with an answer.

### 7. The claim → witness rule (D19)

Every invoice makes claims; each claim has exactly one external witness.

| The invoice claims | Only this settles it |
|---|---|
| "the rate is ₹1,200/unit" | the quotation or contract |
| "you ordered 200 units" | the purchase order |
| "we delivered them" | the delivery note / GRN |
| "you have not paid" | the bank statement |
| "your balance is ₹4.2L" | the vendor statement |

**The ask is never "let us reconcile."** It is always: a specific claim is in doubt, and
one document settles it. The decision rule:

1. **Is a claim in doubt?** Outside the vendor's historical range, first invoice from a
   new vendor, rate changed, possible duplicate, large enough to matter
2. **Do I already hold the witness?** If yes — check silently, say nothing unless it disagrees
3. **If not — is the answer worth the interruption?** ₹2.4L at 4× normal: ask.
   ₹4,500 matching twelve months of history: never ask

Step 2 is what stops it nagging. Most checks happen invisibly; the user hears only the
failures. **The anti-pattern** is asking for documents on a schedule, at onboarding, or
per invoice — that turns ATLAS into a form. The ask must be earned by a specific doubt
and must carry its reason ("4× their usual"), or the user cannot judge whether attaching
the document is worth two minutes.

### 8. What the registry says about all of this

Read from `agents/capabilities.py` and the trigger points, 2026-09-17:

- **16 capabilities: 10 read, 6 action.** Seven of the ten reads are CFO analytics
- **No Auditor skill and no Trainer skill exists.** The thin Auditor list diagnosed in
  update 1 was not a filtering bug — it is an **empty skill set**
- **No recon skill** (D18)
- **All six actions sit behind `ENABLE_ANALYST_ACTIONS = False`** — ATLAS can currently
  do nothing at all (Q8)
- **No hooks.** Two entry points total: the weekly cron and `POST /today/run`. ATLAS
  never wakes when an invoice arrives, a payment lands, extraction fails or a due date
  passes. **It is a batch job with a manual override** (Q9)
- `auto_apply_credit_notes` is declared `kind="read"` — a name promising to apply
  something, registered read-only. Worth a look
- Half the six actions are setup (`setup_inbound_email`, `enable_auto_load_inbox`,
  `set_outbound_email_sender`), not work

**Responsibilities.** The loop — `observe → plan → act → investigate → say → ask → learn`
— is shaped to produce a *report*: gather, analyse, narrate, ask, record. Under D7 the
job is **notice → recommend → explain → offer → verify → learn from the answer**.
`investigate` and `say` exist to make prose; `plan` exists because the model chooses its
own steps. Neither is obviously needed when the output is "approve these 8, here is why."

---

## 2026-09-17 — The other three roles, hooks, and the rules that make one-click safe

**Decisions:** D20–D29 · **Status:** decided, nothing built.

### 1. Trainer (D21)

**Their job: teach the system so it stops being wrong. Their success is their own work disappearing** — the same shape as the Loader.

- **What is worth fixing, ranked by consequence.** Not a list of errors — a list ordered by what each fix buys. "This vendor's template broke; fixing it fixes 60 invoices a month" against "a one-off typo on a vendor seen twice." Without ranking, a Trainer spends the morning on whatever is at the top
- **The correction already drafted.** "Their invoice number moved to the top-right. I'd map it there — confirm?" Approve rather than retype
- **Proof the teaching worked.** "Since you fixed that template: 47 clean, 0 corrections." Or the honest version — "you fixed this two weeks ago and it is still failing." **Without feedback, training is faith**
- **Bad rules surfaced.** A rule that fires wrongly is worse than no rule, because it is trusted. "Fired 30 times, overridden 22 — it is wrong." D12 pointed at the Trainer's own work

**Every correction is a failure the system already had**, so the real scoreboard is the trend: "corrections are down 60% this quarter." If it is not falling, the product is not learning. The only document work they need is **format drift** — this invoice against the vendor's previous ones.

### 2. Loader (D22)

**Their job: get documents in. ATLAS's job: make the job unnecessary** (D13).

- **Stuck versus in flight.** "Processing" and "failed four days ago" look identical on most screens
- **Why it failed, and the fix — not the fault.** Not "extraction error" but "this is a photo of a screen, unreadable — ask them to send the PDF" · "password-protected" · "this is page 2 of 3"
- **What should have arrived and didn't.** "Airtel bills on the 5th. It is the 9th." **Absence makes no noise** — the same principle as the Admin's *don't let it stall*, and the one Loader line no dashboard can produce
- **The way out of the job**, with the automatically-arriving share as the scoreboard

Blocked by Q7 (one ingestion source per tenant) and Q9 (no hooks — "Airtel is four days late" cannot be noticed until the next scheduled run).

### 3. Hooks (D23)

Three kinds of trigger, and they need three different mechanisms:

| Trigger | Mechanism |
|---|---|
| **Something happened** — document arrived, payment landed, extraction finished | Event. Run the cheap checks immediately, stop |
| **Something did not happen** — Airtel did not bill, the queue has not moved, ingestion stopped | **A clock. No event fires for absence** — and this is the highest-value category in every role |
| **Someone showed up** | Recompute the expensive work — forecast, ranking, recon — on arrival |

A customer who does not sign in for a week then costs almost nothing, and one who signs in daily gets a current screen rather than a Monday batch.

### 4. Cold start (D24, D25)

**The trap:** almost everything designed here needs history — vendor baselines, payment behaviour, recurrence, dismissals, corrections. So ATLAS's first month is its weakest, and that is exactly the month a customer decides whether it was worth buying.

**The founder's answer, which is better than the data-first one:** day one is about **comprehension, not findings**. Teach the working relationship per role, not the screens.

- *Auditor:* "Your job is deciding on invoices. I will group the routine ones so you can approve together, and put the odd ones in front of you with the reason. You will not have to read every document to find out nothing was wrong"
- *Trainer:* "When extraction gets something wrong I will show you the correction I would make. I will tell you which fixes are worth your time"
- *Admin:* "I watch four things: money going out wrongly, money running short, anything stalling, settings that have drifted"
- *Loader:* "I will tell you what is stuck and why, and what should have arrived and did not"

**Then: how to verify me.** *"Any line I give you, you can ask about. Attach the document and ask 'is this right?' — I will show you exactly what I compared. Try it on this one now."* **A user who verifies ATLAS once in their first session has a different relationship with it than one who was told it is reliable**, and it teaches the chat affordance at the moment it makes sense.

**Then: the arc, honestly.** "Right now I do not know your vendors, so I cannot tell you ₹2.4L is unusual. In a month I will. In three months I will know who pays late and forecast around behaviour rather than due dates." A stated plan rather than a disappointment — and it makes week four feel like a promise kept.

**What day one can still find with zero history:** arithmetic (line items not summing, tax on the wrong base), validity (malformed GSTIN, due date before invoice date), duplicates within the batch, and cross-document matching within the batch if they upload a folder.

**The historical import becomes an offer, not a gate.** *"If you have last year's bank statements I can check them now — I usually find a duplicate payment or two, and it teaches me your vendors much faster."* Reconciling the past produces real findings in the first session **and silently builds every baseline**. An offer with a payoff, made to someone who now understands what ATLAS is for.

### 5. Being wrong (D26)

Five failure modes, very different costs:

| Failure | Cost |
|---|---|
| **False positive** | Cheap individually. In aggregate it kills the product — a user who dismisses twenty flags dismisses the twenty-first without reading it, and that is how the real one is missed |
| **False negative** | Real money, and **invisible**: no feedback, no correction, no signal. See Q13 |
| **Wrong recommendation, accepted** | The dangerous one under D8 — the batch click *means* the user delegated judgment |
| **Wrong number** | The most damaging. **Trust in numbers is binary and does not recover** |
| **Right flag, wrong reason** | Erodes credibility quietly, and is visible without anyone clicking |

**The asymmetry:** false positives are visible and self-correcting; false negatives are invisible and permanent. That argues for flagging aggressively, which collides with D12's noise pruning. **The resolution is that the bias depends on the stake** — the cost of a wasted minute is fixed, the cost of a miss scales with the amount (Q14).

**After being wrong:** ATLAS acknowledges plainly and stops. "You were right — I flagged that wrongly and I will not again." Not an apology, an adjustment.

### 6. Notifications (D27)

**The wrong test is "is this important."** Most of Today is important. **The right test is: is there a window, and is it closing?** A duplicate matters *before* the payment run; afterwards it is a recovery problem costing ten times more. So **notify when action is still possible and the window is closing — not when ATLAS noticed.** Discovery time and notification time are different things, and conflating them produces alerts nobody can act on.

**Two tiers, and resist a third:** a rare urgent interrupt, and an optional digest. **ATLAS caps its own interrupts** — if five qualify in a day it sends the two that genuinely cannot wait. An urgent channel that fires often stops being one, and once muted, the one that mattered is gone too.

**The notification carries the decision, not a summons.** Not "you have a new finding, log in" — that spends the interruption and delivers nothing. Instead: *"₹47,000 to Kumar Supplies looks like a duplicate of #1041 paid on the 3rd. Your payment run is tomorrow."*

**Escalation** is the notification form of D20: the Auditor's aging queue notifies the Auditor; after some delay it notifies the Admin, because "nobody is doing this" is an Admin problem (Q12).

### 7. Boundaries (D28, D29)

These are what make one-click acceptance safe. Without them D8 is just a faster way to make mistakes.

**Never move money.** No payment initiation, ever — not with approval, not with configuration. ATLAS prepares the decision; a human executes it in their banking system. **The worst outcome of an ATLAS error is a wrong record, never a wrong transfer.**

**Never send outside the company unseen.** A drafted chase email is good work; one sent on a batch click is not. **Every outbound message is read in full and sent individually** — founder-ruled, no exceptions. A wrong email costs a relationship, and the draft already removed the expensive part.

**Never delete · never invent a number · never write silently · never claim certainty it lacks · never learn a permanent rule from one instance.** On numbers specifically: if the invoice says ₹2,41,300, ATLAS says ₹2,41,300, never "about ₹2.4 lakh" — **the easiest rule to break by accident, because prose comes from a model and models round.**

**The organising principle (D29):** *reversible may be batched · irreversible is individual · anything leaving the company is individual and read in full.* This decides every future case without a new ruling, and it is what Q6's batch-undo must satisfy: **if it cannot be undone as a batch, it cannot be accepted as one.**

---

## 2026-09-17 — Ranking, memory, scope, and a topic that produced nothing

**Decisions:** D30–D33.

**Ranking (D30).** The notification test, applied to the screen: money at stake weighted
by how soon it stops being fixable. A ₹2.4L duplicate before tomorrow's payment run beats
a ₹4,000 one from last month. Everything below the cut stays reachable under a
*show everything* line — **ATLAS ranks, it does not hide.**

**Memory (D31).** Everything learned becomes a **visible, editable rule in plain
language** — whether it came from a direct answer, a dismissal, a correction or something
said in chat. This follows from D28's never-write-silently: if ATLAS believes something
about the business, the user can read it, change it or delete it. **A wrong lesson that
cannot be found is one that haunts the system forever**, and dismissals feeding D12's
noise pruning makes wrong lessons likely enough to plan for.

**Scope (D32).** Multi-currency, single entity. Cash and forecast are **per currency,
never blended** — a mixed-currency total is a wrong number under D28. No entity switcher,
no cross-company view. Worth revisiting only if accountants serving several clients
become a customer segment.

**Records and Settings (D33) — the topic that produced nothing, correctly.**

This was raised as "what do they contain once they stop being surfaces," and the founder's
challenge was the right one: *why are we solving this — on-the-fly lookup is not ATLAS's
job.* Correct. **Lookup is a search box.** Routing "did we pay Kumar?" through an agent
makes it slower.

And the mid-decision lookup case does not survive scrutiny either. If an Auditor looking
at a flagged invoice must go and find what that vendor charged last time, **the line was
incomplete** — "4× their usual ₹40–60k" *is* that history. Supplying the reason (D7) is
what removes the need to look anything up. A user who still has to dig has found a defect
in the line, not a missing feature.

So: both keep their current content and move behind a menu. Nothing rebuilt, nothing
deleted, no new work. **Recorded because the reasoning matters** — the instinct to
re-home them came from their place in the four-surfaces model, not from any user need,
and that instinct is worth catching next time.

---

## Pending — not yet discussed

**Every topic raised in this discussion is now decided.** D1–D33 describe the product.
What remains is four open questions and the spec itself.

- **The rebuild** — D1–D33 describe a product, not a plan. Nothing is scoped.
  **The next step is one new spec covering ATLAS end to end**, replacing both FE Feature 22
  and BE Feature 33 rather than amending either — the BE/FE split is where the seams were.
  Feature 22 is superseded but its file is kept: it holds the founder framing and the
  walkthrough rulings this doc now reverses
- **Q5** — where a list becomes a queue
- **Q6** — undoing a batch, which gates D8 and D29
- **Q7** — one ingestion source per tenant, which gates D13
- **Q13** — how a false negative is ever detected. The hardest question here
- **Q11, Q12, Q14** — notification channel, escalation delay, the quiet-when-uncertain floor.
  All deliberately deferred; none blocks the spec

---

## 2026-09-17 — Every open question ruled

**Decisions:** D34–D46 · **Scope:** the whole of ATLAS · **Status:** decided; BE Feature 34
Slice A is built against D7/D26/D29/D32, the rest is unbuilt.

Thirteen open questions were put to the founder one at a time and all thirteen are now
closed — eleven by ruling, two (Q3, Q8) found moot because they were written against
Feature 33 code that was never built. Three consequences the rulings created were put back
to the founder as risks and accepted as stated.

### 1. What the rulings remove

**The whole notification surface (D36).** ATLAS has no channel and sends nothing. It speaks
when a user opens the app, and at no other time. D27 — the urgent tier, the digest, the
self-limiting interrupt cap — is reversed entirely, and Q11's channel question dies with it.

**Every background mechanism (D38).** No event hooks, no absence clock, no cron. The work is
computed when someone signs in. D23's three-trigger model is reversed to one.

**Escalation (D37).** D20 already gives the Admin every line type; an unhandled item does not
need to travel anywhere to be seen.

**Batching (D42).** Individual accept only in v1, which takes task 34.8 off the critical path.
D8's one-click promise survives; the batch half waits for evidence about which line types are
safe to group.

Together these take Feature 34 from twelve tasks to roughly nine.

### 2. What they add or reverse

**The Auditor sees the cash position (D44)** — a reversal of D2 for that role. The spec's
bounded cash line, decision-consequence without the position, is gone: one forecast, one view.
FP&A and margin analytics are unaffected and stay chat-only per D16.

**Many ingestion sources per tenant (D43)**, which unblocks D13 and requires a schema change:
drop `uq_autopilot_config_tenant`, and give ingestion paths a source id they do not carry.

**The Trainer's before/after view (D45).** Records stay tenant-wide, and a correction line
shows the invoice as it was and as it is. This is D21's "proof the teaching worked" made
concrete at the level of a single document.

**No stored baseline (D39), with the working shown instead (D40).** Claims and vendor
baselines are computed when a check runs. D31 is bounded rather than broken: it governs
lessons ATLAS was told or inferred as rules, not observations recomputed from the customer's
own invoices — and the line states its own basis, so the user can still judge it.

### 3. The three risks, put back and accepted

- **A derived baseline cannot be corrected.** Answered by D40 — show the working on the line.
  Provenance without persistence, which the Slice A contract already carries as a COMPUTED
  figure with its computation named.
- **Absence is only noticed when someone signs in** (D46). A vendor who stops billing goes
  unnoticed until a visit. Accepted as the same trade D36 already makes: a user who does not
  open the app cannot be told anything by definition.
- **A user-reported miss under-reports** (D34). Accepted. The miss rate stays unknown,
  including whether it is worsening; the founder's position is that getting better matters
  more than measuring, and a reported miss names a real pattern that then protects every
  future invoice.

### 4. What still has no answer

Nothing in this register. The remaining unknowns are build-time, not design-time: the volume
threshold at which D41's collapse kicks in, and whether D39's check-time derivation is fast
enough at a customer with thousands of invoices.

---

## 2026-09-18 — Verify, the toggle, and making a line go away

**Decisions:** D47–D49 · **Scope:** the work screen · **Status:** decided; FE Feature 23's
built half is D47-compliant only after the wording change, and D48/D49 are unbuilt.

### 1. Verify stops promising what it cannot do (D47)

FE Gap 640 recorded that the Verify affordance seeds its question but cannot attach the
document, because chat attachments can only be uploaded and never referenced by id. The
founder's ruling removes the promise rather than building the endpoint: **the line tells the
user to attach the document in chat and compare there.** The gap closes as a wording and
expectation change, not as BE work, and the two proposed endpoints in its entry are not built.

This keeps §2's fourth part intact — the user still verifies ATLAS cheaply, on this line —
while dropping the part that would have required copying a customer's own document to make the
UI look right.

### 2. The toggle comes back (D48)

D10 deleted the classic-layout toggle because the four-surfaces project was superseded and
"there is no duality to toggle between". That reasoning no longer holds: ATLAS is an **added**
surface and the existing tabbed screens stay. So a toggle sits **beside the notification bell**
and switches between them.

The choice is remembered **in the browser** for now. There is no per-user preference store in
this backend — FE Feature 22 specced one (`user.ui_prefs` + `PATCH /me/preferences`, BE 33.39)
but Feature 33 was never built. The consequence, stated rather than discovered later: the choice
does not follow a user to another device, and **there is no way to see which mode people
actually use** — which is the evidence that would eventually justify retiring either surface.

### 3. A line has to be able to go away (D49)

The founder raised the case the design had no answer for: a line says "attach the quotation and
compare", the user does exactly that in chat, and ATLAS never learns. Under D38 everything is
recomputed on open, so the line is regenerated and **returns forever**.

Ruled: **a dismiss button on every line, and the dismissal persists.** Not a snooze, not
automatic resolution — the user marks it done and it goes.

What this costs, recorded because it is the honest reading: the user's memory is doing the
work. A line dismissed in error is gone, and ATLAS learns nothing about whether the underlying
problem was solved — which interacts with D34, where a miss is already only detectable by the
user reporting it. D12's noise pruning (a repeatedly dismissed alert becomes a recommendation to
stop showing it) is the partial answer and is still unbuilt.

What makes it work technically: recommendation ids are deterministic
(`audit-approve-<invoice id>`, `train-arithmetic-<invoice id>`), not per-run UUIDs, so a
dismissal recorded against an id suppresses the same line on the next recompute.

**Build note (2026-09-18).** D47, D48 and D49 are built on branch `feature/atlas`, uncommitted.
As built: **BE Feature 34 §16** (D47's contract rule and wording, D49's dismissal store, endpoint
and server-side filter) and **FE Feature 23 §13** (D47's hint, D48's toggle, D49's dismiss
control). Gaps: **BE 693**, **BE 695**, **FE 694**, **FE 696**, and **FE 640 closed by D47**.
D48 has no backend at all — the mode lives in `localStorage` and no per-user preference store was
built, so the cost recorded in §2 above stands as written.

---

## 2026-09-18 — What ATLAS may actually do

**Decisions:** D50–D51 · **Scope:** the action set · **Status:** decided, unbuilt (task 34.7).

The work screen currently proposes eight actions and performs none of them:
`PERFORMABLE_ACTION_KINDS` is empty and every button renders disabled saying so. These two
rulings decide which of the eight ever become real.

### The set, after these rulings

| Action | Ruling |
|---|---|
| `resolve_invoice` | **Performable.** The Auditor's decision, and the highest-volume line type. `PUT /audit/resolve/{invoice_id}` already exists |
| `retry_ingestion_source` | **Performable** (D51). `POST /autopilot/sync` already exists; now per source, which D43 made possible |
| `apply_field_correction` | **Suggest only** (D50). Opens the field review with the context |
| `requeue_invoices` | **Suggest only** (D50). Opens the stuck list |
| `open_upcoming_payments`, `open_field_review` | Navigation. Never were writes |
| `attach_witness_document` | An instruction to the user since D47 — ATLAS never attaches |

### Why the split falls where it does

The two performable actions share a property the two suggest-only ones do not: **being wrong is
cheap and local.** A wrongly resolved invoice is one record, visible, reversible by the same
person. A re-run sync writes nothing new at all.

A wrong **correction** is neither — it teaches a rule, and the rule then misfires on every
future invoice from that vendor, which is D28's "never learns a permanent rule from one
instance" seen from the other end. A wrong **requeue** spends pipeline work nobody asked for and
is not undone by clicking again.

So the boundary is not "read versus write". It is **how far the blast radius travels when ATLAS
is wrong** — which is §5.2's asymmetry applied to actions rather than to findings.

### What this leaves to build in 34.7

Two performable kinds, not eight: a dispatcher mapping an action kind to the endpoint that
already performs it, the capability check on **acting** (separate from the check on *seeing* —
the same grant governs both, but they are two decisions and only one is currently made), the
action log §5.3 requires so that "what ATLAS did" is a real readable list, and
`PERFORMABLE_ACTION_KINDS` populated one kind at a time, so a button is never enabled before
its path works.
