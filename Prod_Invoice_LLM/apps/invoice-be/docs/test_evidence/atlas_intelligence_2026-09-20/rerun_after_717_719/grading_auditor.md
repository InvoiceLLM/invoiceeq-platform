# Auditor re-run — graded against `atlas_admin_vpi_expected.md` §5 (Auditor row) and §6

Capture: `briefing_auditor.txt`. Explicit `GrantSet(can_audit=True)` — nothing else. Model
`gpt-5.6-terra`, 4 paragraphs + 1 question, 0 dropped. `tool_calls` shows the two pre-fetched
tools only (`list_lines` 3 rows, `invoices` 26 rows); `cash_position` and `forecast` are absent
from this caller's schema list, as §5 requires.

| # | cites | subject |
|---|---|---|
| P1 | `audit-approve-530bd65a-…` | RAJ-2009 duplicate |
| P2 | `audit-approve-22490a93-…` | NAT-2007 duplicate |
| P3 | `audit-cash-INR` | 30-day payable/receivable **plus a runway sentence** |
| P4 | `13d719a7-…` | VPI-OUT-2014 — **the BE Gap 717 appended paragraph** |
| Q | `530bd65a-…` | the duplicate question (BE Gap 718) |

## The four required MUST items

| item | verdict | why |
|---|---|---|
| M1 duplicates | **PARTIAL** | P1 and P2 cite listed ids and carry each invoice's own figure verbatim; the ₹5,17,146.80 sum is absent (no tool renders it). |
| M2 VPI-OUT-2014 | **PARTIAL** | P4 cites `13d719a7-…` with the alert's working. This paragraph is **not the model's** — the model wrote three paragraphs and left the tenant's only arithmetic defect out; the deterministic append put it back (BE Gap 717). The +₹640.00 difference is absent. |
| M9 three blocked | **PARTIAL** | All three named across P1/P2/P4, each citing a listed id; the count and the ₹10,00,996.80 held are absent. No fourth invoice is presented as needing attention. |
| outbound to chase + bounded approval consequence | **MISS** | Nothing about chasing an outbound invoice, and no "approving RAJ-2008 commits ₹4,37,190.00 on 15-Sep" sentence. |

**Score: 0 MATCH / 3 PARTIAL / 1 MISS.** **INVENTED tokens: 0** — every figure came from a row,
0 dropped.

## §5 MUST-NOT — 1 violation, unchanged and pre-existing

P3: *"…and the runway assumes the last 90 days of payments continue."* §5's Auditor row forbids
any runway line. **The tool gate is working**: `cash_position` and `forecast` are not in this
caller's schema (and a direct dispatch is refused — proved separately in the id dump for this
tenant). The sentence arrives through `services/atlas_skills.py::_cash_lines()`, which emits
`audit-cash-INR` as an `AtlasCapability.AUDIT` **line**, so `list_lines` returns it to every
`can_audit` caller. This is the same violation the 2026-09-20 capture recorded, it is a Feature
34 line-visibility question rather than anything BE Gaps 717/718/719 touched, and it was **not
filed or fixed here** (CONVENTIONS hard rule 1 — the founder approved five items, and this is
not one of them).

No other §3/§5 violation: no bank statement or balance figure, no salary/GST/electricity/AMC
line, no `$`, no FP&A, nothing about a person's speed.

## The question

Fired, once, identical to the Admin's and cited to the `invoices` row for RAJ-2009. An Auditor
is exactly who should be asked whether a flagged pair is a real second order, so this is the
right reader for it.
