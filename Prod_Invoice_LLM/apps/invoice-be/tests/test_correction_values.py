"""BE Gaps 530/531/533/534: reading human corrections (utils/correction_values.py). Pure functions, no database."""
from datetime import date, datetime

import pytest

from agents.extraction_agent import AddressItem, InvoiceLineItem, TaxItem
from utils.correction_values import (
    parse_currency,
    parse_date,
    parse_entries,
    parse_line_items,
    parse_money,
    parse_percent,
    parse_tags,
)


@pytest.mark.parametrize("raw,expected", [
    (1250.5, 1250.5),
    (100, 100.0),
    ("1250.50", 1250.5),
    ("1,250.50", 1250.5),
    ("$1,250.60", 1250.6),
    ("₹12,50,000.00", 1250000.0),
    ("€ 1,250", 1250.0),
    ("INR 1,250.50", 1250.5),
    ("1,250.50 USD", 1250.5),
    ("-500", -500.0),
    ("(500.00)", -500.0),
    ("-$1,250.60", -1250.6),
])
def test_parse_money_reads_common_formats(raw, expected):
    assert parse_money(raw) == pytest.approx(expected)


@pytest.mark.parametrize("raw", ["nan", "inf", "-inf", "1e400", "1.250,50", "1,2", "12,5000", "abc", "", True])
def test_parse_money_refuses_what_it_cannot_read_safely(raw):
    with pytest.raises(ValueError):
        parse_money(raw)


@pytest.mark.parametrize("raw,expected", [
    ("2026-01-15", date(2026, 1, 15)),
    ("2026-01-15T10:30:00", date(2026, 1, 15)),
    ("15/01/2026", date(2026, 1, 15)),
    ("01/15/2026", date(2026, 1, 15)),
    ("15-01-2026", date(2026, 1, 15)),
    ("05/05/2026", date(2026, 5, 5)),
    ("15 Jan 2026", date(2026, 1, 15)),
    ("Jan 15, 2026", date(2026, 1, 15)),
    (datetime(2026, 1, 15, 9, 0), date(2026, 1, 15)),
])
def test_parse_date_reads_unambiguous_formats(raw, expected):
    assert parse_date(raw) == expected


@pytest.mark.parametrize("raw", ["01/02/2026", "31/02/2026", "tomorrow", "2026/13/45"])
def test_parse_date_refuses_ambiguous_or_invalid_dates(raw):
    with pytest.raises(ValueError):
        parse_date(raw)


def test_parse_date_names_the_fix_for_an_ambiguous_date():
    with pytest.raises(ValueError, match="YYYY-MM-DD"):
        parse_date("01/02/2026")


def test_parse_line_items_accepts_json_text_and_keeps_only_sent_keys():
    items = parse_line_items('[{"description": "Widget", "amount": "150"}]', InvoiceLineItem)
    assert items == [{"description": "Widget", "amount": 150.0}]


@pytest.mark.parametrize("raw", [
    "Widget A, 100",
    {"description": "Widget", "amount": 1},
    [{"description": "Widget"}],
    [{"description": "Widget", "amount": 1, "unexpected": True}],
    [{"description": "Widget", "amount": "inf"}],
    ["just a string"],
])
def test_parse_line_items_refuses_malformed_items(raw):
    with pytest.raises(ValueError):
        parse_line_items(raw, InvoiceLineItem)


@pytest.mark.parametrize("raw,expected", [("EUR", "EUR"), ("inr", "INR"), ("  usd ", "USD")])
def test_parse_currency_reads_iso_codes(raw, expected):
    assert parse_currency(raw) == expected


@pytest.mark.parametrize("raw", ["EURO", "₹", "US", "978", 978, None, "U$D"])
def test_parse_currency_refuses_anything_but_a_three_letter_code(raw):
    with pytest.raises(ValueError, match="3-letter"):
        parse_currency(raw)


@pytest.mark.parametrize("raw,expected", [(12.5, 12.5), (0, 0.0), (100, 100.0), ("12.5", 12.5), ("12.5%", 12.5), (" 18 % ", 18.0)])
def test_parse_percent_reads_percentages(raw, expected):
    assert parse_percent(raw) == expected


@pytest.mark.parametrize("raw", ["150", -1, "nan", "inf", "twelve", True, "12,5"])
def test_parse_percent_refuses_values_outside_zero_to_hundred_or_unreadable(raw):
    with pytest.raises(ValueError):
        parse_percent(raw)


@pytest.mark.parametrize("raw,expected", [
    ("it, hardware", ["it", "hardware"]),
    ("it, , hardware, it", ["it", "hardware"]),
    (["email", " connector "], ["email", "connector"]),
    ('["a", "b"]', ["a", "b"]),
    ([], []),
])
def test_parse_tags_reads_lists_and_comma_separated_text(raw, expected):
    assert parse_tags(raw) == expected


@pytest.mark.parametrize("raw", [[1, 2], {"tag": "it"}, "[not json", 5])
def test_parse_tags_refuses_non_word_lists(raw):
    with pytest.raises(ValueError):
        parse_tags(raw)


def test_list_entry_model_reads_the_schema_field_not_a_same_named_class():
    """BE Gap 531: the entry model is read from the schema field — for deductions, the invoice deduction model."""
    from agents.extraction_agent import InvoiceExtractionSchema

    from utils.correction_values import list_entry_model

    assert "deduction_type" in list_entry_model(InvoiceExtractionSchema, "deductions").model_fields
    assert list_entry_model(InvoiceExtractionSchema, "items") is InvoiceLineItem


def test_parse_entries_validates_against_the_given_model_and_names_the_entry():
    assert parse_entries([{"tax_type": "CGST", "amount": "45"}], TaxItem, "tax line") == [{"tax_type": "CGST", "amount": 45.0}]
    with pytest.raises(ValueError, match=r"^address 2: text"):
        parse_entries(
            [{"address_type": "billing", "text": "12 Main St"}, {"address_type": "shipping"}], AddressItem, "address"
        )
