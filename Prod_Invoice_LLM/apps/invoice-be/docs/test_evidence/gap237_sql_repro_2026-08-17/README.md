# BE Gap 237 step 1 -- live repro (functional-tester, 2026-08-17)

Scope: confirm or disconfirm the tracker's hypothesis ("the follow-up's SQL
simplifies away the `items` branch specifically") against a seeded local-dev
tenant, per BE Gap 237's own step 1. No application code or prompt changes
made -- evidence capture only.

## Test tenant and data

Own, clearly-named test tenant (not tenant-us/india/eu, which a concurrent
senior-dev session is also using): `Gap237 Chat SQL Repro Test`, domain
`gap237-chat-sql-repro-test.invalid`, id `02db74f3-2064-4b3b-aec9-218af9a408f4`.

5 INBOUND, `COMPLETED` invoices, deliberately constructed so a broad "cloud"
category question matches via three different SQL branches, plus one
different-currency match and one non-matching control:

| Invoice | Vendor | Currency | Total | Matches "cloud" via |
|---|---|---|---|---|
| CNH-1001 | CloudNine Hosting | USD | 1,200.00 | vendor_name only |
| ACM-2002 | Acme Manufacturing | USD | 3,400.00 | tags only (["cloud","infra"]) |
| ZEN-3003 | Zenith Consulting | USD | 69,012.43 | items only -- line item "Cloud Migration Assessment"; vendor/customer/tags carry no "cloud" reference at all |
| CNH-EU-1002 | CloudNine Hosting EU | EUR | 800.00 | vendor_name only, different currency |
| ODS-4004 | Office Depot Supplies | USD | 500.00 | control -- no match anywhere |

Seed script: tests/gap237_sql_repro.py. Reseed source of truth for BE Gap 242
is separate (tests/gap242_reseed_blue_ridge.py), not used here.

## Method

Real running backend (localhost:8000), real Postgres/Redis, mock-auth
(ALLOW_MOCK_AUTH=true, Bearer test_<tenant-id>), same pattern as the
developer's own tests/_multiturn_chat_repro.py. One real chat session per
run; two turns in the same session:

1. "What are the total invoices related to cloud?" (broad)
2. "Can you explain the 3 USD ones in detail?" (narrowing follow-up,
   mirrors the founder-reported phrasing "explain the 3 USD ones")

The Redis semantic-answer cache (chat_answer_cache:{tenant_id}:*, Task
6.11) is flushed for this tenant before every run, since it is keyed on
(tenant_id, normalized_question_text) and both turns' question text is
identical across runs -- without the flush, every run after the first would
just replay a cached answer instead of making a fresh LLM call.

Ran 7 times (run0-run6, raw JSON per run in this directory --
raw_turns_run0.json through raw_turns_run6.json; run0 was recovered from the
DB after the very first ad hoc run, before the script had per-run labels).
generated_sql is read directly off the chat API's response
(MessageResponse.generated_sql); result_invoice_ids is read directly from
the ChatMessage DB rows, since the API response schema doesn't expose that
field.

## Results

Turn 1's SQL was structurally the same shape every run (LLM-composed
SELECT currency, COUNT(*), SUM(...) ... WHERE tenant_id = '...' AND (
vendor_name LIKE '%cloud%' OR customer_name LIKE '%cloud%' OR tags::text LIKE
'%cloud%' OR items::text LIKE '%cloud%' [OR other columns] ) GROUP BY
currency) and always correctly found all 4 seeded matches (3 USD, 1 EUR).

Turn 2 varied across runs into three distinct outcomes, not one:

| Run | Turn 2 outcome | generated_sql | Real invoices returned |
|---|---|---|---|
| run0 | WHERE-clause branch dropped | currency='USD' AND (tags LIKE cloud OR items LIKE cloud) -- vendor_name/customer_name/file_path branches gone | 2 of 3 (CNH-1001, the vendor-only match, silently missing) |
| run1 | Correct, full regeneration | kept vendor_name, tags, items (only dropped customer_name, a harmless no-op here -- always NULL on INBOUND rows) | 3 of 3, correct |
| run2 | No SQL generated at all | null -- model answered straight from turn 1's aggregate in chat_history | n/a (no query run) |
| run3 | No SQL generated | null, offered to "retrieve" details instead | n/a |
| run4 | No SQL generated | null, offered to run a live query | n/a |
| run5 | No SQL generated | null, same as run4 | n/a |
| run6 | WHERE-clause branch dropped | currency='USD' AND flow_direction='INBOUND' AND (tags LIKE cloud OR items LIKE cloud) -- vendor_name/customer_name/file_path/invoice_number branches gone | 2 of 3 (CNH-1001 missing again) |

Full turn-2 replies for run0/run6 (the two reproductions) both self-reported
the discrepancy in prose ("I only see two USD invoices ... not three"),
without the user having to notice -- but this came from the LLM's own
in-context reasoning during summary synthesis, not from the Gap 237 step-3
safety net (see below).

## Answer to the confirm/disconfirm question

The core defect reproduces live: a same-session narrowing follow-up can
silently drop a real invoice from a prior turn's answer, 2 of 7 times in
this run set. But the tracker's specific hypothesis -- that the LLM
"simplifies away the items (line-item description) branch" -- is
DISCONFIRMED by direct evidence: in both of the two live reproductions of
the drop mechanism, the items branch was the one that survived. The branch
that was actually dropped, both times, was vendor_name (along with
customer_name/file_path/invoice_number, which happened to be no-ops in this
dataset). The invoice silently lost was the one that matched via vendor
name, not the one that matched via a line-item description.

This does not mean the tracker's underlying concern (an item-only match can
be dropped) is wrong in general -- with a differently-shaped dataset or
phrasing, items could plausibly be the branch that gets simplified away on
a given call, since the LLM regenerates the whole predicate fresh from
chat_history prose each time and which branch survives looks
non-deterministic across calls, not fixed to one column. What this repro
adds, concretely: the drop is not specific to items -- any one of the
original turn's OR branches can be silently omitted, so a WHERE-clause-reuse
fix (Gap 237 step 2) needs to reuse/narrow the prior turn's entire exact
predicate structure, not special-case protect the items clause alone.

## Secondary finding: a distinct, more common failure mode in this repro

4 of 7 runs (run2-run5) didn't reproduce a WHERE-clause drop at all --
instead the SQL-generation call itself returned sql: null for turn 2, and
the model answered purely by restating turn 1's already-known aggregate
numbers, without running any fresh query. The user explicitly asked to
"explain ... in detail," and in 3 of those 4 runs the model's own reply
acknowledged it didn't have the requested detail and offered to fetch it,
rather than asserting anything wrong. This is not the WHERE-clause-drop
mechanism Gap 237 was opened over, and it isn't unsafe (no wrong claim was
asserted) -- but it is a related, previously-undocumented behavior worth the
senior-dev being aware of when designing the step-2 fix: reusing/narrowing
the prior turn's WHERE clause only helps if a follow-up phrased this way
reliably triggers a fresh SQL-generation call in the first place, which this
repro shows it does not always do.

## Secondary finding: the shipped step-3 safety net (hedge) never fired here

Neither run0 nor run6 (the two real reproductions, each missing a real
invoice) triggered the Gap 237 step-3 hedge sentence ("Heads up: you
referenced N from the previous answer..."), confirmed by grepping all 7 raw
evidence files for "Heads up" (zero matches). Read directly from
agents/query_agent.py: the hedge only fires when
len(prior.result_invoice_ids) in referenced_counts -- i.e. when the prior
turn's total row count exactly equals the number the user references. In
this repro (deliberately mirroring the founder's report, where the first
answer described "3 USD invoices" as a currency-scoped subset of a broader
result), turn 1's actual total was 4 rows (3 USD + 1 EUR), so 4 not in {3}
and the check never engages -- even though the user's "3" is a real, correct
reference to a sub-count mentioned in turn 1's own prose. This is not a
defect in code I'm scoped to fix, and step 3 is explicitly out of scope for
me to alter -- flagging it here because it's directly relevant input for the
senior-dev's prompt-fix pass: the hedge's current trigger condition may be
too narrow to catch the real reported shape whenever the referenced count is
a sub-group rather than the whole prior result set.

## Raw evidence files in this directory

- raw_turns_run0.json -- first ad hoc run (recovered from ChatMessage DB rows directly, since the script didn't yet have per-run file names)
- raw_turns_run1.json through raw_turns_run6.json -- full request/response JSON per turn; chat_message_db_rows includes the DB-level result_invoice_ids
