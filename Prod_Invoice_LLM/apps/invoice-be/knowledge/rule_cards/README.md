# Regional rule cards (Feature 30, tasks 30.9–30.11)

One markdown file per rule. The YAML front matter is parsed by
`services/rule_cards.py::parse_rule_card()`; the body is the text a user is
shown, in their words, quoting the source.

## `status` is the honesty field

| status | meaning | shown to a user? |
|---|---|---|
| `verified` | somebody FETCHED `source_url` and wrote the body from what it actually says, on `fetched_at` | yes, with its citation |
| `unverified` | the card names a rule we believe exists and the source it should be checked against, but nobody has fetched it. **It has no body.** | never — `load_rule_cards()` filters it out |

CONVENTIONS.md hard rule 8: a rule card is only ever written from a primary
source that was actually fetched and cited. Writing plausible-sounding tax rules
from memory would produce confident, citable-looking statements about the law
that nobody checked — the worst failure available to this feature. An
`unverified` skeleton is the correct output when a source cannot be reached.

## As of 2026-09-08

**EU — verified (3).** Fetched from the European Commission's VAT invoicing page
(`https://taxation-customs.ec.europa.eu/taxation/value-added-tax-vat/vat-invoicing_en`),
which lists what a full VAT invoice must contain: the credit/debit-note
reference, the supplier's VAT identification number, and the "reverse charge"
wording.

**US — verified (2).** Fetched from IRS Publication 583 (`https://www.irs.gov/publications/p583`),
"Supporting Documents". There is no federal rule about the CONTENT of a purchase
order or delivery note, so one card is deliberately guidance (`verify: null`)
rather than a check that would pretend a federal requirement exists.

**India — DROPPED 2026-09-14 by founder ruling ("Drop the India cards"), task
30.9 closed as dropped.** Three skeleton cards (`in-tax-invoice-gstin`,
`in-hsn-code-on-lines`, `in-credit-note-original-reference`) used to sit here as
`status: unverified` with no rule text. They are deleted, and the reason is that
the gap was never going to close on its own: **no CBIC/GSTN primary source could
be reached on either attempt.**

* 2026-09-08 — `cbic-gst.gov.in` serves act/rules pages through JavaScript (every
  direct path 404s); `taxinformation.cbic.gov.in` fails TLS
  (`SSL: CERTIFICATE_VERIFY_FAILED`); `gst.gov.in` returns "Request Rejected"
  (WAF); `indiacode.nic.in` and `gstcouncil.gov.in` have no findable path to the
  CGST Act PDF.
* 2026-09-14, re-probed — `einvoice1.gst.gov.in` ECONNRESET;
  `tutorial.gst.gov.in/userguide/einvoice/` 404; `cbic-gst.gov.in` a JS shell
  redirecting to `taxinformation.cbic.gov.in`, which still fails TLS.

A skeleton with no reachable source is not an unfinished card, it is a standing
promise that something will be checked when nothing is checking it. Per hard rule
8 the honest output is no card at all: an Indian document now gets **no
compliance verdict**, rather than a rule with no text or (worse) EU/US rules
applied to it. `card_compliance`'s three-state `NOT_CHECKED` path for
all-unverified regions is **unchanged and still tested** — it just has no card on
disk that reaches it.

**To add India properly, later:** fetch a primary source, paste the wording,
fill `fetched_at` / `effective_from`, and write the card `status: verified` from
the start. `gstin_present` and `hsn_code_present` are still in `CHECKS`, correct
and unit-tested, waiting for it. Do not re-create the skeletons.
