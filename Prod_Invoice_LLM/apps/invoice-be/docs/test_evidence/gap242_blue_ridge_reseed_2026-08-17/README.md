# BE Gap 242 test-data reseed -- Blue Ridge Logistics (functional-tester, 2026-08-17)

Scope: restore realistic freight/logistics line-item content for Blue Ridge
Logistics (tenant-us), whose items column BE Gap 242's own tracker entry
disclosed was overwritten with a placeholder during an earlier Gap 234
end-to-end verification test. Test-data prep only -- no application code
touched, no correction made through the app's own audit-correction endpoints
(a direct DB update was used instead, deliberately, so this doesn't write an
AuditLog entry implying a human reviewer made this change).

Invoice: id e6ccfb34-d53f-45e7-8ec9-119ced8aa0db, tenant-us
(3511ae3e-27a4-49a5-897d-6a1a3fc3ac91), invoice_number BRL-200981.

## What was found (before)

- items: single placeholder line, `"TEST LINE ITEM EDIT"`, amount 200.0
- subtotal: 200.0 (matches the placeholder item's amount -- also corrupted
  by the same earlier test, not just items)
- tax_amount: 161.31 (untouched, real)
- grand_total: 2386.31 (untouched, real)

subtotal + tax_amount should equal grand_total, and did not (200.0 + 161.31
= 361.31, not 2386.31) -- direct evidence subtotal was corrupted alongside
items, not just the items column alone. Reverse-solving:
2386.31 - 161.31 = 2225.00, and 2225.00 * 7.25% = 161.3125 (rounds to
161.31, an exact match to the stored tax_amount) -- strong evidence the real
pre-corruption subtotal was $2225.00.

## What was changed

Restored realistic freight/logistics line items summing to exactly
$2225.00, and corrected subtotal to match. grand_total and tax_amount were
left untouched (they were never corrupted).

After:
- items:
  1. "LTL Freight Transportation -- Charlotte, NC to Columbus, OH (Freight Class 70)" -- amount 1800.00
  2. "Fuel Surcharge (12.5%)" -- amount 225.00
  3. "Liftgate Delivery Fee" -- amount 125.00
  4. "Residential Delivery Surcharge" -- amount 75.00
- subtotal: 2225.00 (1800 + 225 + 125 + 75)
- tax_amount: 161.31 (unchanged)
- grand_total: 2386.31 (unchanged; subtotal + tax_amount now reconciles exactly)
- tags: unchanged (["freight", "logistics", "sales_tax"] -- was never touched by the earlier corruption)

Full before/after JSON: before_after.json in this directory. Script used:
tests/gap242_reseed_blue_ridge.py (includes a safety-check assertion that
new subtotal + existing tax_amount == existing grand_total before writing,
and that the row is actually Blue Ridge Logistics, so a re-run against a
changed row would fail loudly rather than silently miswrite).

## Why this matters for the upcoming fix

BE Gap 242's suggested fix has SQL generation also check vendor_name/tags
for a category/keyword question, not just items. Blue Ridge Logistics'
tags (freight, logistics) were never corrupted and already support that
part of a verification. This reseed additionally makes the items-description
path verifiable for the same vendor -- both routes into "does this invoice
show up for a freight/logistics question" can now be checked honestly
against real content, not a placeholder string.
