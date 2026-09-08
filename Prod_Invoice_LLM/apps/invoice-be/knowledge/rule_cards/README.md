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

**India — unverified (3), and this is a real gap.** Every primary source was
attempted on 2026-09-08 and none could be fetched from this environment:

* `cbic-gst.gov.in` — serves its act/rules pages through JavaScript; every
  direct path tried (`/CGST-bill-e.html`, `/sectionwise-cgst.html`, seven
  `/pdf/…` guesses) returned 404. Its homepage and unrelated PDFs do load, so
  the host is reachable and the documents are simply not at guessable URLs.
* `taxinformation.cbic.gov.in` — `SSL: CERTIFICATE_VERIFY_FAILED`.
* `gst.gov.in` — "Request Rejected" (WAF).
* `indiacode.nic.in`, `gstcouncil.gov.in` — the CGST Act PDF is not at any path
  that could be found from their link graphs.

The three India cards therefore carry `status: unverified`, the source they
must be checked against, and **no rule text**. Their `verify` names are already
wired to real checks in `CHECKS`, so flipping one to `verified` is: fetch the
source, paste the wording, fill `fetched_at` and `effective_from`, change the
status. Nothing else changes.
