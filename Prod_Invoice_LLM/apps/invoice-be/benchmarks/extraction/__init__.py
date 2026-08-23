"""Feature 23 Track 1 — the extraction & alert benchmark.

Two frozen document sets and the harness that runs them through the real
extraction pipeline:

  * **clean** — internally consistent invoices with known-correct field values.
    Measures field-level accuracy and the alert **false-positive** rate.
  * **seeded** — the same documents with exactly one deliberately planted issue
    each. Measures alert **recall** — the number the feature doc names as
    unmeasurable from production usage, because nobody flags what wasn't
    flagged.

Read `docs/extraction_benchmark/README.md` first: it is the methodology record,
written for architect/business-analyst review before any figure produced here is
treated as a real benchmark.
"""
