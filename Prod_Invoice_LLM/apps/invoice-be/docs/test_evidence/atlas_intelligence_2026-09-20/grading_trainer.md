# Grading — Trainer briefing, VPI, live Terra (2026-09-20)

Source: `briefing_trainer.sse.txt` (4 paragraphs, `model: gpt-5.6-terra`, DB row tokens_in 8046 /
tokens_out 941 / cost_usd 0.027384, deleted per deliverable 3 cleanup). Trainer is graded against
`atlas_admin_vpi_expected.md` §5's Trainer row.

## Paragraphs captured

1. RAJ-2009 duplicate — cites `audit-approve-530bd65a…`
2. NAT-2007 duplicate — cites `audit-approve-22490a93…`
3. **VPI-OUT-2014**: "Subtotal (409500.00) + Tax (73710.00) does not match Grand Total
   (483850.00). Its due date is 17 September." — cites `13d719a7…` via tool `invoices`
4. PaymentTerm on GBP-2012, RAJ-2009, RAJ-2008, OM -2002 (all 4 named) — cites all 4
   `train-lowconf-*` ids

## §5 MUST see

| item | verdict | notes |
|---|---|---|
| M10 four low-confidence PaymentTerm fields, correction pre-drafted and ranked by consequence | **PARTIAL** | All 4 vendors/invoices named in one paragraph (P4), all 4 `train-lowconf-*` ids cited together — citation test passes. No confidence decimals (0.485/0.414/0.406/0.332) stated, and no "correction pre-drafted, ranked by consequence" structure — it is a flat list, not a ranked one. |
| bad/misfiring rules | N/A | 0 memory rules exist on this tenant — nothing to flag; correctly silent. |
| M12 empty rule set | **MISS** | `memory_rules` never called; the "0 rules, 0 proposals" statement never made. |

## §5 MUST NOT — **two violations found**

1. **Paragraphs 1 & 2 (duplicate/audit-approve content).** Ground truth §5 excludes
   `cash_position`, `forecast`, `reconcile`, `doubts`, `vendor_baseline` from Trainer's tool
   schema, and explicitly: *"therefore no cash, no shortfall, **no duplicate-approval line**, no
   receivables."* Both duplicate paragraphs cite `audit-approve-*` recommendation ids — this is
   exactly the excluded duplicate-approval content.
2. **Paragraph 3 (VPI-OUT-2014 tax mismatch).** This is a reconciliation/tax-mismatch finding —
   arithmetic-defect content that BE Gap 716's tracker note describes the `invoices` tool as
   gated to `can_audit`/Admin ("new `invoices` tool (inbound AND outbound, alerts +
   low-confidence keys, `can_audit`/Admin)"). This user's grants at capture time were
   `can_train=true, can_audit=false` (Trainer only) — the tool fired anyway. **This looks like
   the same pre-fetch gating defect as (1): audit-scoped tool output reaching a can_train-only
   caller.** Flagged as a candidate gap (not filed, not fixed here — see README).

No `$`, no calendar-as-FY, no invented numeric token (all present figures are in §1/§2's allowed
set, including `409,500.00` / `73,710.00` / `483,850.00`, all of which are M2's GT figures).

## Score

**0 MATCH / 1 PARTIAL / 2 MISS** against §5's positive Trainer items. **2 confirmed §5 MUST-NOT
violations** (audit-approve duplicate content, VPI-OUT-2014 reconciliation content) — both fail
the run per the grading rule.
