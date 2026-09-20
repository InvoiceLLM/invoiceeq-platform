# Trainer re-run — graded against `atlas_admin_vpi_expected.md` §5 (Trainer row) and §6

Capture: `briefing_trainer.txt`. Explicit `GrantSet(can_train=True)` — nothing else. Model
`gpt-5.6-terra`, 2 paragraphs + 1 question, 0 dropped. `tool_calls` shows exactly one dispatch,
`list_lines` (4 rows): `invoices`, `cash_position` and `forecast` are absent from this caller's
schema list, as §5 and F35 §9.4 require.

| # | cites | subject |
|---|---|---|
| P1 | `train-lowconf-530bd65a-…` | RAJ-2009's unread PaymentTerm — **and the duplicate sentence** |
| P2 | `train-lowconf-33d6ccd5-…`, `train-lowconf-d5869da2-…`, `train-lowconf-ff4a9fe0-…` | the other three PaymentTerm fields |
| Q | `train-lowconf-530bd65a-…` | the duplicate question (BE Gap 718) |

## The three required MUST items

| item | verdict | why |
|---|---|---|
| M10 four low-confidence PaymentTerm fields | **PARTIAL** | All four invoices are named across P1 and P2, each citing its own listed `train-lowconf-…` id — the complete set. The four confidence scores (0.485 / 0.414 / 0.406 / 0.332) are **not** stated and no correction is pre-drafted, which §5 asks for. |
| bad or misfiring rules | **MISS** | `memory_rules` was not called and nothing is said about rules. |
| M12 the empty rule set | **MISS** | Same cause: with 0 rules the tenant has nothing to cite, and the briefing says nothing about the absence. |

**Score: 0 MATCH / 1 PARTIAL / 2 MISS.** **INVENTED tokens: 0.** No cash, no shortfall, no
receivables, no reconciliation figure anywhere — the four "absent from its schema" tools stayed
absent, and this run makes no statement that needed one.

## §5 MUST-NOT — 1 violation, unchanged and pre-existing

P1 and the question both carry the duplicate sentence about RAJ-2009/RAJ-2008. §5's Trainer row
says a duplicate-approval line must not reach them.

**Where it comes from matters, and it is not a capability leak.** The Trainer's own
low-confidence line for RAJ-2009 carries the invoice's `sa_alerts` in its `alerts` field —
that is BE Gap 716's row change, applied to every line whose entity is an invoice, and the
`alert_open` flag added by BE Gap 717 is `true` on it (RAJ-2009 is AUDIT_REQUIRED). The audit
tools were all refused on this run. So the question this raises is whether Gap 716's row should
carry the invoice's alert for a caller who cannot act on it — a design question about that row,
recorded here and **not filed or fixed** (CONVENTIONS hard rule 1: the founder approved five
items and this is not one of them). The 2026-09-20 capture recorded the same behaviour; this
run does not make it worse, and the other half of that earlier finding — an `invoices`-tool
reconciliation paragraph reaching a Trainer — **did not reproduce**: the tool was refused.

## The question

Fired, once, cited to the only row the Trainer holds for that invoice
(`train-lowconf-530bd65a-…`) rather than to an `invoices` row they were never given — the
citation follows the caller's own evidence, which is what makes it checkable for them.
