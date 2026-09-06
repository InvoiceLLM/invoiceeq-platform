# SAGE chat: a generic architecture for accurate answers across every scenario — research note (2026-09-06)

> Companion to `knowledge-layer-plan.md`. This note answers one question the founder asked after the
> 2026-09-05/06 matrix and attachment probes: *is there a generic way to build the chat area so that every
> scenario we have found, and the ones we have not yet found, gets an accurate answer?*
>
> Short answer: **yes, but the generic thing is not a prompt or a model — it is an architecture with a fixed
> answer contract, a small set of typed capabilities, deterministic computation, and a verification gate.**
> Every failure we have measured so far is explained by the absence of one of those pieces, and the research
> record says the same thing at industry scale.

---

## 1. What the evidence says the bottleneck is

| finding | source | what it means for us |
|---|---|---|
| Five models scored 28–44% SQL / 22–28% chat on the same golden set — a flat line | our matrix run 2026-09-05 | model choice is not the lever |
| ~81% of enterprise text-to-SQL failures are semantic (metric/join/filter), ~19% syntax | [Atlan](https://atlan.com/know/ai-agent/data-for-ai/text-to-sql-for-enterprise/) | the model is not misunderstanding SQL; it is misunderstanding *our data* |
| Off-the-shelf LLMs score ~21% on Spider 2.0 and near 0% on BEAVER (real enterprise schemas) | [dbt 2026](https://docs.getdbt.com/blog/semantic-layer-vs-text-to-sql-2026) | raw-schema text-to-SQL does not generalise to real schemas, ours included |
| Semantic-layer grounding: 84–90% → 98–100% on in-scope questions; out-of-scope questions fail *transparently* (error) instead of *silently* (plausible wrong SQL) | [dbt 2026](https://docs.getdbt.com/blog/semantic-layer-vs-text-to-sql-2026) | certified views + metric definitions are the single biggest lever, and they also change the *failure mode* |
| Execution-feedback repair loops add +6–8 pts (Reflect-SQL: 64.9 → 72.0 on BIRD); they catch logic errors but cannot fix a poor knowledge base | [Reflect-SQL](https://arxiv.org/html/2609.02944) | our 3-attempt repair loop is right but is capped by what it is grounded in |
| Verified-query repositories are how Cortex Analyst reaches 90%+: retrieve similar certified Q→SQL pairs at answer time; "invalid or inaccurate queries negatively impact accuracy" | [Snowflake VQR](https://docs.snowflake.com/en/user-guide/snowflake-cortex/cortex-analyst/verified-query-repository) | our C4 example retrieval is the right shape; the examples must be *certified*, not just present |
| Deterministic-tool financial QA: 95.5% on calculation-intensive queries vs direct LLM baselines "even when provided with complete formulas and rate cards"; LLM never performs arithmetic | [CIFQA](https://arxiv.org/abs/2608.26114) | hard rule 3 is validated at scale — and it says the gap is *missing tools*, never a smarter prompt |
| Even code-generating models "execute correct logic on hallucinated input variables" — the fix is to forbid the model from injecting scalars | VeNRA via [PAL research log](https://beancount.io/bean-labs/research-logs/2026/04/23/pal-program-aided-language-models) | our "may not state a number not in the JSON" rule is exactly this; it must stay |
| Judge calibration: sample 100–300 traces, 2–3 human raters, Cohen's κ > 0.6 acceptable, > 0.8 strong; κ < 0.4 means the *rubric* is ambiguous; use a different model family than the generator | [Galileo](https://galileo.ai/blog/calibrate-llm-judge-human-annotations), [FutureAGI](https://futureagi.com/blog/llm-as-judge-best-practices-2026/) | our 0.10–0.19 judge delta and 28% pass flips mean we cannot yet tell a real gain from noise |
| Enterprise agentic RAG progression: router → planner → verifier → (only then) multi-agent | [Toloka](https://toloka.ai/blog/agentic-rag-systems-for-enterprise-scale-information-retrieval/) | we are at "router"; the next two steps are planner and verifier, not more agents |
| Clarifying agents with *domain-grounded* detectors beat few-shot LLM clarification; budget the turns | [ECLAIR](https://arxiv.org/pdf/2503.20791) | keyword-hit clarification is the weakest form; ambiguity must be detected against the schema and the session |
| Groundedness = every claim traces to evidence; inference-time gates that block unfaithful answers are now standard | [Openlayer](https://www.openlayer.com/blog/rag-pipeline-evaluation-groundedness-faithfulness) | a per-answer check that every figure is in the computed payload is cheap and deterministic for us |

**One sentence:** accuracy comes from *what the model is grounded in* and *what it is forbidden to do*, not from which model it is.

---

## 2. What our own probes found, re-read through that lens

Every failure from the 2026-09-05/06 runs falls into one of five buckets. None of them is "the model was not smart enough".

| bucket | our instances | generic cause |
|---|---|---|
| **Did not route** | A4, A7, B3, B4 all hit the "read or compare?" card; 9/36 chat turns ran with no rows | routing is keyword-driven and defaults to *ask* — a new question shape is invisible until someone adds its words |
| **Nothing computed the answer** | A4 (amount owed), B4 (expected tax), A7/B3 (per-reference outcome in prose) | the answer needed arithmetic or aggregation that only the model could see, and the model is (correctly) forbidden to do it |
| **Wrong evidence in front of the model** | SQL projection of 2–13 columns; 0 vector chunks; contract prose walled off from the money prompt | the context was chosen by the route, not by the question |
| **Wrong SQL that ran** | 28–44% exec-correct; semantic errors dominate | no certified metric definitions; raw joins over a schema the model has to re-derive each time |
| **We cannot tell** | judge δ 0.10–0.19 between judges, up to 28% pass flips; stale golden set | the ruler moves more than the thing being measured |

The pattern across Gaps 470/472/473: each was **two defects stacked** — a routing miss *and* a missing computation. Fixing one alone leaves the turn failing. A generic design must therefore fix both *structurally*, not gap by gap.

---

## 3. The scenario space (discovered + possible)

A generic solution has to be generic over something. This is the space:

**Question intents** (what the user wants done)
1. Lookup — one fact about one record ("what is the total of RIT-2026-0456?")
2. Aggregate — sum/count/rank over a set ("highest inbound grand total", "combined total of X and Y")
3. Filter/list — records meeting a predicate ("inbound invoices with no PO")
4. Explain — why a value is what it is ("why was no sales tax charged?") — needs record + document text
5. Verify — does a figure agree with a rule or another document ("is the tax correct per the contract?", "does the line add up?")
6. Reconcile — set-vs-set ("which lines on this statement do we have?")
7. Derive — a figure that exists nowhere and must be computed ("after the credit, what do we owe?")
8. Compare — A vs B where both are documents or records
9. Procedural — "how do I / what should I do about X" (playbooks)
10. Compliance — "is this invoice compliant with GST/EN 16931/…" (rule cards + record)
11. Conversational — follow-ups, pronouns, "and the second one?"
12. Out of scope / unanswerable — must abstain, not guess

**Evidence sources** (where the answer lives)
- Postgres invoice row(s) — all columns, JSON parsed
- Line items, taxes, alerts, notes
- Vector chunks of the invoice document
- Attached document(s) in the session — extracted fields, and their text chunks
- Knowledge layer — glossary, metric definitions, rule cards, playbooks, certified examples
- Session history

**Ambiguity classes** (why a good question still fails)
- Entity ambiguity — which invoice/vendor ("the Apex invoice" when there are three)
- Metric ambiguity — "total" = subtotal, grand total, or net of credits?
- Scope ambiguity — this month, this vendor, this document?
- Missing operand — "is the tax correct?" with no contract or rate on file
- Unit/currency ambiguity — mixed currencies, "in USD equivalent"

Any of the 12 intents × any evidence source × any ambiguity class is a legal question. There are far too many combinations to write a prompt or a keyword list per cell — which is precisely why the generic solution cannot be more prompts.

---

## 4. The generic architecture — seven layers

The claim: a chat surface that has **all seven** handles every cell of §3 with the same code, and a *new* scenario becomes either a new certified example (minutes) or a new deterministic capability (hours) — never a new prompt branch.

### Layer 1 — Answer contract (the thing that makes "accurate" checkable)

Every answer is assembled from a typed payload, and the model narrates the payload. The contract:

- **Every figure in the prose must appear verbatim in the payload.** Already the rule on the attachment branches (Gaps 431/472/473). Extend it to *every* route.
- **Every claim carries provenance** — invoice id, column, chunk id, rule-card id, or "computed by `<function>`".
- **Abstain is a first-class answer** — `{status: "insufficient_evidence", missing: [...]}` renders as a specific "I can't answer because X is not on file", never a plausible guess. dbt's finding that semantic layers fail *transparently* is this property; we want it on every route.
- **A deterministic groundedness gate before the answer leaves**: extract numbers from the prose, check each is in the payload; fail → regenerate once with the offending figure named, then abstain. Cheap, no model, catches the class of error the judge currently has to find.

### Layer 2 — Typed capabilities, not routes

Today: four routes (SQL / RAG / CHAT / ATTACHMENT) chosen by a classifier + keyword lists. The generic form: a **small registry of typed capabilities**, each with a declared input, output and evidence, that a planner composes.

| capability | in | out | deterministic? |
|---|---|---|---|
| `resolve_entities(question, session)` | text | invoice ids / vendor ids / attachment ids + confidence | mostly (name/number match; LLM only to *propose*, never to *decide*) |
| `fetch_records(ids)` | ids | full rows, JSON parsed, + chunks | yes |
| `query_metric(metric, filters)` | metric name from the semantic layer | rows | yes — runs a certified view |
| `generate_sql(question, schema_link, examples)` | text | SQL → rows, with the 3-attempt execution-repair loop | LLM + execution feedback |
| `compute(kind, operands)` | typed operands | figure + workings | yes — `query_tools.compute()`, `compute_amount_owed()`, `compare_contract_terms_to_invoice()`, line-sum checks, tax-rate checks |
| `compare(doc_a, doc_b, mode)` | two typed docs | diff | yes |
| `reconcile(references, invoices)` | list + set | per-reference outcomes | yes |
| `retrieve_text(scope, query)` | attachment/invoice/knowledge + query | chunks + reranked | yes (bge-m3 → rerank-v4) |
| `lookup_rule(region, topic)` | region + topic | rule cards with `effective_from` | yes |
| `clarify(ambiguity)` | a typed ambiguity | one question with options | template |

Each of Gaps 470–473 was the discovery that one of these capabilities was missing or unreachable. With the registry, a new scenario is a new row, not a new branch.

### Layer 3 — Planner instead of classifier

The classifier answers "which route?"; a planner answers "which capabilities, in what order, on which operands?" — and it is allowed to say "I need to ask first". Concretely, a single fast-model call that returns a **typed plan** (JSON, schema-validated):

```
{ intent: "derive",
  entities: [{kind:"invoice", ref:"APS-410093"}, {kind:"attachment", ref:"CN-APEX-01"}, {kind:"attachment", ref:"PO-US-7002"}],
  steps: [ fetch_records, compute(amount_owed) ],
  ambiguities: [] }
```

Rules that keep it honest:
- The plan is **validated against the registry** before anything runs — an unknown capability or an operand the plan cannot name is a validation error, not a guess.
- **Entity resolution is deterministic** after the planner proposes; a proposal that matches 0 or >1 records becomes a `clarify` step automatically (this is ECLAIR's "domain-grounded detector", and it removes the keyword-list problem at the root: A4/B4 did not fail because words were missing, they failed because nobody checked whether the question *named things we could resolve*).
- The planner never sees document text — only the manifest (Gap 439). Hostile text cannot steer the plan.
- Budget: one clarify per turn, and only when resolution genuinely fails (ECLAIR's cost-sensitive stopping).

This is the "add a planner" step in the router → planner → verifier progression. It replaces the keyword lists, which have now been extended three times in one day and will need extending again next week.

### Layer 4 — Grounding: semantic layer + certified examples + full records

This is `knowledge-layer-plan.md` §1–3, and it is where the biggest measured gain lives (84–90% → 98–100% in scope).

- **Certified views + one metric definition each.** `query_metric()` runs them; `generate_sql()` is told to prefer them and is given the definitions. The failure mode moves from silent to transparent.
- **Certified Q→SQL examples, top-5 by similarity**, seeded from the golden set and grown by the flywheel. Snowflake's warning applies: an *uncertified* example in the store actively hurts, so certification is a state, not a folder.
- **Full records, always** — the founder's 2026-09-06 decision. After ids are known, the summary prompt gets the whole row + its chunks, never a 2–13-column projection. This alone removes the 9/36 "no rows" turns and the "invoice not in the provided context" class of chat failure.
- **Glossary** resolves metric ambiguity *before* SQL generation ("total" → `grand_total` unless the tenant says otherwise).

### Layer 5 — Deterministic computation, as a growing library

Hard rule 3, made systematic. The model never computes; it names a computation and the operands, and Python does it and hands back the figure *with workings*. The library today: `query_tools.compute()`, line-sum checks, `compare_reference_to_invoices()`, `compare_documents()`, `reconcile_referenced_documents()`, and since today `compute_amount_owed()` and `compare_contract_terms_to_invoice()`.

The generic rule for growth: **when a probe turn fails because a figure was never computed, the fix is a new function in `services/document_comparison.py` or `query_tools.py` with tests, never a prompt that lets the model try.** CIFQA's 95.5% on calculation-intensive queries is this rule at scale; so is the fact that every model in our matrix failed A4 and B4 identically.

### Layer 6 — Verification before, and measurement after

- **Before the answer**: execution-repair for SQL (have it), entailment check that the result *shape* matches the plan (e.g. an aggregate question that returned 40 rows and no aggregate → re-plan once), and the Layer-1 groundedness gate.
- **After the answer**: a **calibrated** judge. 30 hand-graded turns is the floor the plan already sets; the research floor is 100–300 with 2–3 raters and κ > 0.6. Until that is done, no prompt or model change should be accepted on judge delta alone. Judge must be a different family from the generator where possible (gpt-5-mini vs Luna satisfies "different model", not "different family" — acceptable for now, noted).
- **Failure taxonomy as a standing artefact**, not a one-off: every judged failure is tagged with the §2 bucket. That is what tells us which layer to invest in next.

### Layer 7 — The flywheel

A correction (user thumbs-down + fix, or a hand-graded failure) becomes one of exactly three things:
1. a **certified example** (the SQL/plan was wrong, the capability existed) — minutes;
2. a **new deterministic capability or rule card** (nothing could compute/lookup it) — hours, with tests;
3. a **planner/resolver fix** (it did not route) — and the taxonomy count tells us when that is a pattern.

Nothing else is a valid outcome of a failure. "Adjust the prompt" is not on the list unless the taxonomy shows a narration-only defect with a correct payload.

---

## 5. Walking every discovered scenario through the seven layers

| turn | today | with the seven layers |
|---|---|---|
| A4 — PO + credit note, "what do we owe?" | clarify card → (after Gap 472) pair-compare branch with ledger | planner: `derive`; resolve {PO, CN, confirmed invoice}; `compute(amount_owed)`; narrate. No keyword needed. |
| A7 — statement, "which do we have?" | counts only → (Gap 470) named | planner: `reconcile`; per-reference outcomes are the payload; contract forces each to be named |
| B3 — remittance, "which invoice does this pay, in full?" | clarify card → (Gap 470) reconcile | `reconcile` + `compute(amount_owed)` with the remittance as −1 term → "paid in full" is `net == 0`, computed |
| B4 — contract, "is the tax correct?" | "contract states no tax" → (Gap 473) computed | planner: `verify`; `retrieve_text(contract, fixed query)` → `compute(contract_tax_check)`; quoted span as evidence |
| B5 — delivery note + contract, "which vendor needs follow-up?" | compared to each other | planner: two independent `verify` steps, each doc against its own invoice; merge; doc-to-doc only when the plan says `compare(doc, doc)` |
| eu_outbound_reverse_charge (chat) — "which two of three outbound used reverse charge?" | "context does not identify the three" | full records → tax lines present; `filter/list` over 3 rows |
| eu_benelux_line_understated — "does the line add up?" | "invoice not in context" | resolve BMN-2026-0234 → fetch → `compute(line_check)` → 3 × 620 = 1,860 vs 1,680 |
| A8 — combined total of two invoices | passes | `aggregate` via `compute` (already) — unchanged |
| A9 — why no sales tax? | passes on 2/3 | `explain` → record + chunks; the chunk with the exemption certificate is evidence; abstain if absent |
| "and the second line?" (follow-up) | attachment branch sees history since Gap 440 | session entities are in the planner's input; resolver picks the prior invoice |
| "what's the GST rate on HSN 8471?" | not answerable | `lookup_rule(IN, hsn)` → rule card with `effective_from`; abstain if none |
| "is this EU invoice compliant?" | not answerable | `fetch` + `lookup_rule(EU, EN16931)` + deterministic field check → per-field pass/fail payload |

Every row uses the same seven layers; none adds a branch.

---

## 6. What *not* to do (each has been tried somewhere and measured)

- **Keep growing keyword lists.** Three extensions today; each one is a scenario nobody had anticipated. The resolver-based clarify makes them unnecessary.
- **Add a prompt per scenario.** Prompts do not compose; the §3 space is combinatorial.
- **Swap the model.** Five models, flat line. Terra for long-doc is a *role* decision gated on 5 golden cases, not an accuracy lever.
- **Let the model compute "just this once".** VeNRA: it will hallucinate an operand. CIFQA: it loses to a 17B model with tools.
- **Trust the judge before calibrating it.** 28% pass flips means any "improvement" under 10 pts is noise today.
- **Cache answers without the full key.** The answer cache is keyed on (tenant, question) with no attachment dimension (documented invariant on the content branch) — a generic design keys on the *plan*, not the question.
- **Send document text to the planner or the money prompt as free text.** Evidence spans only, fenced, attached to computed figures (Gap 473 shape).

---

## 7. Implementation order — what to build, in what sequence, with the gate for each

Aligned with `knowledge-layer-plan.md`; adds the planner/contract pieces that plan does not cover.

| step | build | gate to proceed |
|---|---|---|
| 0 | Finish Step 5 (5.5, 5.6 probe), commit. Failure taxonomy over current golden set (Step 3a). Judge calibration: ≥30 hand-graded turns now, 100+ before any model/prompt conclusion. | taxonomy counts by §2 bucket; κ reported |
| 1 | **Full records on every route** (tasklist Step 4). Answer contract + deterministic groundedness gate on all routes. `abstain` payload. | golden chat re-run; "no rows"/"not in context" failures → 0 |
| 2 | **Semantic layer**: 4 certified views + metric definitions (Alembic, add-only); glossary; certified examples table seeded from golden set; `generate_sql` prefers views. | SQL exec-correct on golden set vs step-0 baseline; target +15 pts (dbt/Atlan range) |
| 3 | **Planner + resolver**: typed plan JSON, registry validation, deterministic entity resolution → automatic clarify on 0/>1 match. Retire keyword lists behind a flag; keep them as fallback for one release. | clarify-card rate on the 16-turn probe → 0 for questions that name a resolvable entity; no regression on golden |
| 4 | **Reranker + retrieval measurement** (rerank-v4; recall@k instrumented). Chat tier at minimal reasoning effort. | RAG recall measured for the first time; chat pass ≥ 60% (tasklist 3d target) |
| 5 | **long_doc role**: 5 golden cases, Terra vs Luna on the attachment branches. | Luna stays if within 2 pts |
| 6 | **Rule cards + playbooks**, India first, each verified against its primary source with `effective_from`. `lookup_rule` capability + compliance `verify` computations. | compliance golden set (new) passes |
| 7 | **Flywheel**: thumbs-down → correction → certified example / capability / resolver fix; online trend in the control-tower workbook. | weekly taxonomy shows bucket counts falling |

Steps 1–3 are where the measured gains are; 4–7 are what keep them.

---

## 8. Sources

- [Atlan — Text-to-SQL for Enterprise: metric drift and context layer (2026)](https://atlan.com/know/ai-agent/data-for-ai/text-to-sql-for-enterprise/)
- [dbt Developer Blog — Semantic Layer vs. Text-to-SQL: 2026 benchmark update](https://docs.getdbt.com/blog/semantic-layer-vs-text-to-sql-2026)
- [Atlan — Text-to-SQL or Semantic Layer: the self-serve decision (2026)](https://atlan.com/know/ai-agent/semantic-layer/text-to-sql-vs-semantic-layer-for-self-serve-analytics/)
- [Reflect-SQL: a self-reflection based framework for text-to-SQL (arXiv 2609.02944)](https://arxiv.org/html/2609.02944)
- [The Death of Schema Linking? (arXiv 2408.07702)](https://arxiv.org/pdf/2408.07702)
- [Snowflake — Cortex Analyst verified query repository](https://docs.snowflake.com/en/user-guide/snowflake-cortex/cortex-analyst/verified-query-repository)
- [Snowflake — Optimize a semantic model with verified queries](https://docs.snowflake.com/en/user-guide/snowflake-cortex/cortex-analyst/analyst-optimization)
- [CIFQA: a deterministic tool-grounded multi-agent LLM framework for financial query answering (arXiv 2608.26114)](https://arxiv.org/abs/2608.26114)
- [Neuro-symbolic financial reasoning via deterministic fact ledgers (arXiv 2603.04663)](https://arxiv.org/html/2603.04663v2)
- [PAL for reliable financial arithmetic — Beancount research log](https://beancount.io/bean-labs/research-logs/2026/04/23/pal-program-aided-language-models)
- [Evaluating prompting and execution-based methods for deterministic computation in LLMs (arXiv 2605.03227)](https://arxiv.org/pdf/2605.03227)
- [Galileo — How to calibrate your LLM judge with human annotations](https://galileo.ai/blog/calibrate-llm-judge-human-annotations)
- [FutureAGI — LLM-as-judge best practices 2026: calibration, bias, cost](https://futureagi.com/blog/llm-as-judge-best-practices-2026/)
- [Toloka — Agentic RAG systems for enterprise-scale information retrieval](https://toloka.ai/blog/agentic-rag-systems-for-enterprise-scale-information-retrieval/)
- [Unstructured — From static to smart: agentic RAG for enterprise AI](https://unstructured.io/insights/from-static-to-smart-agentic-rag-for-enterprise-ai)
- [ECLAIR: enhanced clarification for interactive responses in an enterprise AI assistant (arXiv 2503.20791)](https://arxiv.org/pdf/2503.20791)
- [Clarifying agents in dialogue systems — Emergent Mind](https://www.emergentmind.com/topics/clarifying-agent)
- [Query, Decompose, Compress: structured query expansion for multi-hop retrieval (arXiv 2603.21024)](https://arxiv.org/html/2603.21024v1)
- [When should queries be decomposed? (arXiv 2606.08577)](https://arxiv.org/pdf/2606.08577)
- [Hybrid relational-vector systems — Emergent Mind](https://www.emergentmind.com/topics/hybrid-relational-vector-unstructured-systems)
- [Openlayer — RAG evaluation in production: groundedness, faithfulness, retrieval quality (2026)](https://www.openlayer.com/blog/rag-pipeline-evaluation-groundedness-faithfulness)
- [LLM output verification patterns — grounding checks, self-verification, citation enforcement](https://hidekazu-konishi.com/entry/llm_output_verification_patterns.html)
