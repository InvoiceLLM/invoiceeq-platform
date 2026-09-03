"""Gap 426 — `_normalize_string_equality` must keep a table qualifier inside the call.

`\\b{column}` matches `invoice_number` inside `invoice.invoice_number` because a
dot is a word boundary, and the rewrite emitted `TRIM(LOWER(invoice_number))`
with the qualifier left dangling in front: `invoice.TRIM(LOWER(invoice_number))`,
a syntax error on both engines. Rule 6d's taught shape qualifies every column
with `invoice.`, so a model following it and filtering by number hit this on
every attempt. Found 2026-09-03 by the C4.3 verification harness, which runs
every curated example through `execute_generated_sql`: 5 of 29 failed with
`near "(": syntax error`.
"""
import os

import pytest

os.environ.setdefault("MOCK_EMBEDDINGS", "true")

from agents.query_agent import _normalize_string_equality as normalize  # noqa: E402


@pytest.mark.parametrize(
    "sql, expected",
    [
        # exact-fuzzy column, qualified and not
        ("WHERE invoice.invoice_number = 'US-1'", "WHERE TRIM(LOWER(invoice.invoice_number)) = TRIM(LOWER('US-1'))"),
        ("WHERE invoice_number = 'US-1'", "WHERE TRIM(LOWER(invoice_number)) = TRIM(LOWER('US-1'))"),
        ("WHERE i.po_number = 'PO-9'", "WHERE TRIM(LOWER(i.po_number)) = TRIM(LOWER('PO-9'))"),
        # substring-fuzzy column
        ("WHERE invoice.vendor_name = 'Acme'", "WHERE TRIM(LOWER(invoice.vendor_name)) LIKE LOWER('%Acme%')"),
        ("WHERE vendor_name = 'Acme'", "WHERE TRIM(LOWER(vendor_name)) LIKE LOWER('%Acme%')"),
        # IN and NOT IN
        ("WHERE invoice.vendor_name IN ('a', 'b')", "WHERE TRIM(LOWER(invoice.vendor_name)) IN (TRIM(LOWER('a')), TRIM(LOWER('b')))"),
        ("WHERE vendor_name NOT IN ('a')", "WHERE TRIM(LOWER(vendor_name)) NOT IN (TRIM(LOWER('a')))"),
        # LIKE and NOT LIKE
        ("WHERE invoice.invoice_number LIKE 'US%'", "WHERE TRIM(LOWER(invoice.invoice_number)) LIKE LOWER('US%')"),
        ("WHERE customer_name NOT LIKE '%x%'", "WHERE TRIM(LOWER(customer_name)) NOT LIKE LOWER('%x%')"),
    ],
)
def test_qualified_and_unqualified_columns_rewrite_to_valid_sql(sql, expected):
    assert normalize(sql) == expected


def test_the_dangling_qualifier_never_appears():
    out = normalize(
        "SELECT invoice.invoice_number FROM invoice WHERE tenant_id = 't' "
        "AND invoice.invoice_number = 'US-20260722-001' "
        "AND LOWER(item.value ->> 'description') LIKE '%bolts%'"
    )
    assert "invoice.TRIM(" not in out
    assert "TRIM(LOWER(invoice.invoice_number))" in out
    # Untouched: the tenant predicate and the JSON-path LIKE are not fuzzy columns.
    assert "tenant_id = 't'" in out
    assert "LOWER(item.value ->> 'description') LIKE '%bolts%'" in out


def test_a_column_name_inside_another_identifier_is_left_alone():
    """`\\b` still protects `my_vendor_name` -- the qualifier group only ever
    captures a real `word.` prefix."""
    assert normalize("WHERE my_vendor_name = 'x'") == "WHERE my_vendor_name = 'x'"
