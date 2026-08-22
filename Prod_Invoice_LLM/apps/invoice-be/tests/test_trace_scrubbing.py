"""Feature 23 — tests for `utils/trace_scrubbing.py`.

Two halves, deliberately, because the doc frames scrubbing as a two-sided
constraint and a test that only checks one side would pass a broken utility:

* **Redaction** — the five categories `feature_23_ai_control_tower.md` names
  (vendor/customer names, invoice numbers, GSTINs, `payment_instructions` bank
  details, monetary values) really are gone, including from free text.
* **Survival** — the structural properties a reproduction depends on are still
  there afterwards: every field name, the question's wording around the
  aliases, currency, quantity, `flow_direction`, `status`, `stop_reason`,
  tool names, and the referential identity that lets "the answer named the same
  vendor the question asked about" still be checked.

The sample trace is modelled on the real Gap 263 turn recorded in
`feature_23_ai_control_tower.md` ("whats the CGST we paid to Rajesh Steel" ->
"The CGST recorded for Rajesh Steel is INR 18,000.00") plus the real
`PaymentInstructionItem` shape from `agents/extraction_agent.py`.
"""
from __future__ import annotations

import copy

import pytest

from utils.trace_scrubbing import (
    ZERO_AMOUNT_PLACEHOLDER,
    contains_obvious_pii,
    scrub_trace,
)


@pytest.fixture
def raw_trace() -> dict:
    return {
        "case_id": "rajesh_steel_cgst",
        "question": "whats the CGST we paid to Rajesh Steel on INDIA-20260722-003",
        "system_prompt": (
            "Tenant Data Snapshot: 7 total invoices, total spend per currency: "
            "INR 118,000.00; USD 0.00. Primary vendor Rajesh Steel Pvt Ltd, "
            "GSTIN 06AABCI5678F1Z9, remittance contact ap@rajeshsteel.co.in."
        ),
        "route": "sql",
        "stop_reason": "tool_call_budget_exhausted",
        "tool_calls": [
            {
                "tool": "identify_invoices",
                "generated_sql": (
                    "SELECT tax_amount FROM invoice "
                    "WHERE LOWER(vendor_name) LIKE LOWER('%Rajesh Steel%') "
                    "AND invoice_number = 'INDIA-20260722-003'"
                ),
            }
        ],
        "tool_results": [
            {
                "vendor_name": "Rajesh Steel Pvt Ltd",
                "customer_name": "Infinevo Cloud Pvt Ltd",
                "invoice_number": "INDIA-20260722-003",
                "po_number": "PO-IN-4410",
                "currency": "INR",
                "flow_direction": "INBOUND",
                "status": "COMPLETED",
                "grand_total": 118000.0,
                "tax_amount": 18000.00,
                "subtotal": 100000,
                "items": [
                    {
                        "description": "Bolts",
                        "quantity": 5000,
                        "unit_price": 0.08,
                        "amount": 420.00,
                    }
                ],
                "payment_instructions": [
                    {
                        "method_type": "UPI ID + IFSC",
                        "details": "rajesh@okhdfcbank / IFSC HDFC0001234",
                    },
                    {
                        "method_type": "IBAN+SWIFT/BIC",
                        "details": "DE89370400440532013000",
                    },
                ],
            }
        ],
        "answer": (
            "The CGST recorded for Rajesh Steel is INR 18,000.00. The bolts line "
            "reads 5,000 units x INR 0.08 = INR 420.00."
        ),
    }


def _flatten(node, out=None):
    """Every string leaf in the structure, for whole-trace assertions."""
    out = [] if out is None else out
    if isinstance(node, dict):
        for value in node.values():
            _flatten(value, out)
    elif isinstance(node, list):
        for item in node:
            _flatten(item, out)
    elif isinstance(node, str):
        out.append(node)
    return out


def _all_text(trace) -> str:
    return "\n".join(_flatten(trace))


# ---------------------------------------------------------------------------
# Redaction — the five named categories
# ---------------------------------------------------------------------------


def test_vendor_and_customer_names_are_gone_from_every_leaf(raw_trace):
    scrubbed = scrub_trace(raw_trace).trace
    text = _all_text(scrubbed)
    assert "Rajesh Steel" not in text
    assert "Rajesh Steel Pvt Ltd" not in text
    assert "Infinevo Cloud" not in text
    assert scrubbed["tool_results"][0]["vendor_name"] == "<VENDOR_1>"
    assert scrubbed["tool_results"][0]["customer_name"] == "<CUSTOMER_1>"


def test_short_form_vendor_name_in_prose_and_sql_is_redacted(raw_trace):
    """The leak this utility most easily misses.

    `vendor_name` holds "Rajesh Steel Pvt Ltd" but the user's question, the
    generated SQL's LIKE clause and the answer all say "Rajesh Steel". Aliasing
    only the exact stored spelling leaves the real name sitting in the question.
    """
    scrubbed = scrub_trace(raw_trace).trace
    assert "Rajesh Steel" not in scrubbed["question"]
    assert "Rajesh Steel" not in scrubbed["answer"]
    assert "Rajesh Steel" not in scrubbed["tool_calls"][0]["generated_sql"]
    # ...and still reads as the same entity in all three.
    assert "<VENDOR_1>" in scrubbed["question"]
    assert "<VENDOR_1>" in scrubbed["answer"]
    assert "LIKE LOWER('%<VENDOR_1>%')" in scrubbed["tool_calls"][0]["generated_sql"]


def test_invoice_and_po_numbers_are_redacted_everywhere(raw_trace):
    scrubbed = scrub_trace(raw_trace).trace
    text = _all_text(scrubbed)
    assert "INDIA-20260722-003" not in text
    assert "PO-IN-4410" not in text
    assert scrubbed["tool_results"][0]["invoice_number"] == "<INVOICE_NO_1>"
    # Same document id in the question, the SQL and the row -> one alias.
    assert scrubbed["question"].endswith("<INVOICE_NO_1>")
    assert "'<INVOICE_NO_1>'" in scrubbed["tool_calls"][0]["generated_sql"]


def test_gstin_is_redacted(raw_trace):
    scrubbed = scrub_trace(raw_trace).trace
    assert "06AABCI5678F1Z9" not in _all_text(scrubbed)
    assert "GSTIN <GSTIN_1>" in scrubbed["system_prompt"]


def test_payment_instruction_bank_details_are_redacted_method_type_is_not(raw_trace):
    scrubbed = scrub_trace(raw_trace).trace
    instructions = scrubbed["tool_results"][0]["payment_instructions"]
    text = _all_text(scrubbed)

    assert "HDFC0001234" not in text
    assert "rajesh@okhdfcbank" not in text
    assert "DE89370400440532013000" not in text
    assert instructions[0]["details"].startswith("<BANK_DETAILS_")
    assert instructions[1]["details"].startswith("<BANK_DETAILS_")
    # The *kind* of payment rail is structure, not a secret, and a reasoning
    # error about UPI-vs-IBAN handling is unreproducible without it.
    assert instructions[0]["method_type"] == "UPI ID + IFSC"
    assert instructions[1]["method_type"] == "IBAN+SWIFT/BIC"


def test_monetary_values_are_redacted_in_fields_and_in_prose(raw_trace):
    scrubbed = scrub_trace(raw_trace).trace
    text = _all_text(scrubbed)
    for figure in ("118,000.00", "118000", "18,000.00", "18000", "100000"):
        assert figure not in text
    assert str(scrubbed["tool_results"][0]["grand_total"]).startswith("<AMOUNT_")
    assert str(scrubbed["tool_results"][0]["tax_amount"]).startswith("<AMOUNT_")
    assert "INR <AMOUNT_" in scrubbed["answer"]


def test_email_address_is_redacted(raw_trace):
    scrubbed = scrub_trace(raw_trace).trace
    assert "ap@rajeshsteel.co.in" not in _all_text(scrubbed)
    assert "<EMAIL_1>" in scrubbed["system_prompt"]


def test_contains_obvious_pii_finds_it_before_and_nothing_after(raw_trace):
    before = contains_obvious_pii(raw_trace)
    assert before, "the un-scrubbed fixture must trip the checker, or it proves nothing"
    assert contains_obvious_pii(scrub_trace(raw_trace).trace) == []


# ---------------------------------------------------------------------------
# Survival — what a reproduction still needs
# ---------------------------------------------------------------------------


def test_every_field_name_survives(raw_trace):
    """Field names are schema, not customer data — and a reasoning bug is often
    *about* a field name (`status` misread as a payment status)."""

    def keys(node, acc):
        if isinstance(node, dict):
            for k, v in node.items():
                acc.add(k)
                keys(v, acc)
        elif isinstance(node, list):
            for item in node:
                keys(item, acc)
        return acc

    assert keys(raw_trace, set()) == keys(scrub_trace(raw_trace).trace, set())


def test_structural_values_survive(raw_trace):
    scrubbed = scrub_trace(raw_trace).trace
    row = scrubbed["tool_results"][0]
    assert row["currency"] == "INR"
    assert row["flow_direction"] == "INBOUND"
    assert row["status"] == "COMPLETED"
    assert row["items"][0]["quantity"] == 5000  # a count, not an amount
    assert row["items"][0]["description"] == "Bolts"
    assert scrubbed["route"] == "sql"
    assert scrubbed["stop_reason"] == "tool_call_budget_exhausted"
    assert scrubbed["tool_calls"][0]["tool"] == "identify_invoices"
    assert scrubbed["case_id"] == "rajesh_steel_cgst"


def test_question_shape_survives(raw_trace):
    """Gap 263 reproduces only if the question is still recognisably a request
    for a CGST component that this schema does not store."""
    scrubbed = scrub_trace(raw_trace).trace
    assert scrubbed["question"].startswith("whats the CGST we paid to ")
    assert scrubbed["question"].split() == [
        "whats", "the", "CGST", "we", "paid", "to", "<VENDOR_1>", "on", "<INVOICE_NO_1>",
    ]


def test_tax_component_vocabulary_is_not_eaten_by_the_identifier_pattern():
    """The document-id pattern requires a digit precisely so that domain
    acronyms survive — they are what the tax-reasoning bugs are made of."""
    scrubbed = scrub_trace(
        {"answer": "No CGST-SGST split is stored; RCM-B2B invoices carry zero tax."}
    ).trace
    assert scrubbed["answer"] == (
        "No CGST-SGST split is stored; RCM-B2B invoices carry zero tax."
    )


def test_short_format_id_is_caught_via_the_structured_field_it_also_appears_in():
    """`DOC_ID_RE` requires a 3+ digit run so that "RCM-B2B" survives. The cost
    is that a short id like "AB-12-34" is invisible to the pattern — so it is
    covered by exact-literal replacement whenever the same value also sits in an
    `invoice_number` field. This test pins both halves of that trade-off."""
    scrubbed = scrub_trace(
        {
            "question": "pull up AB-12-34 please",
            "row": {"invoice_number": "AB-12-34"},
        }
    ).trace
    assert scrubbed["question"] == "pull up <INVOICE_NO_1> please"

    # ...and the stated hole: no structured field, no redaction.
    prose_only = scrub_trace({"question": "pull up AB-12-34 please"}).trace
    assert prose_only["question"] == "pull up AB-12-34 please"


def test_sql_structure_survives(raw_trace):
    scrubbed = scrub_trace(raw_trace).trace
    sql = scrubbed["tool_calls"][0]["generated_sql"]
    assert sql.startswith("SELECT tax_amount FROM invoice WHERE LOWER(vendor_name)")
    assert "LIKE LOWER(" in sql
    assert "invoice_number =" in sql


def test_equal_amounts_share_an_alias_and_unequal_ones_do_not():
    """A mismatch bug (Gap 269: 5,000 x 0.08 printed as 420.00, not 400.00) only
    reproduces if identical figures stay identical and different figures stay
    different after scrubbing."""
    scrubbed = scrub_trace(
        {
            "items": [{"quantity": 5000, "unit_price": 0.08, "amount": 420.00}],
            "subtotal": 420.00,
            "grand_total": 400.00,
        }
    ).trace
    assert scrubbed["items"][0]["amount"] == scrubbed["subtotal"]
    assert scrubbed["grand_total"] != scrubbed["subtotal"]


def test_currency_token_survives_next_to_the_alias():
    """"Never add across currencies" is a real tested behaviour; flattening the
    currency would delete the property a mixed-currency bug turns on."""
    scrubbed = scrub_trace(
        {"answer": "1 invoice totalling EUR 800.00 and 3 totalling USD 73,612.43."}
    ).trace
    assert "EUR <AMOUNT_" in scrubbed["answer"]
    assert "USD <AMOUNT_" in scrubbed["answer"]
    assert "800" not in scrubbed["answer"]
    assert "73,612.43" not in scrubbed["answer"]


def test_zero_keeps_its_own_placeholder():
    """Gap 224's false-confident-zero is unreproducible if a zero total is
    indistinguishable from any other figure."""
    scrubbed = scrub_trace(
        {"answer": "You spent USD 0.00 with them, out of USD 96,420.00 overall."}
    ).trace
    assert ZERO_AMOUNT_PLACEHOLDER in scrubbed["answer"]
    assert scrubbed["answer"].count("<AMOUNT_1>") == 1


def test_ordinary_prose_mentioning_an_account_is_not_eaten():
    """Over-redaction is a failure mode too: an earlier draft's bank pattern
    swallowed 'the account balance is not stored' whole."""
    text = "There is no payment or account status stored for this invoice."
    assert scrub_trace({"answer": text}).trace["answer"] == text


# ---------------------------------------------------------------------------
# Mechanics
# ---------------------------------------------------------------------------


def test_input_is_not_mutated(raw_trace):
    original = copy.deepcopy(raw_trace)
    scrub_trace(raw_trace)
    assert raw_trace == original


def test_scrubbing_is_idempotent(raw_trace):
    once = scrub_trace(raw_trace).trace
    twice = scrub_trace(once).trace
    assert twice == once


def test_report_holds_the_reidentification_key_and_the_trace_does_not(raw_trace):
    result = scrub_trace(raw_trace)
    assert result.report.aliases["Rajesh Steel Pvt Ltd"] == "<VENDOR_1>"
    assert result.report.aliases["06AABCI5678F1Z9"] == "<GSTIN_1>"
    assert result.report.total_redactions > 0
    # The key must never travel with the fixture.
    assert "aliases" not in result.trace
    assert "06AABCI5678F1Z9" not in _all_text(result.trace)


def test_extra_entity_names_covers_a_party_named_only_in_prose():
    scrubbed = scrub_trace(
        {"question": "what did we spend with Nonexistent Holdings last quarter"},
        extra_entity_names=["Nonexistent Holdings"],
    ).trace
    assert scrubbed["question"] == "what did we spend with <PARTY_1> last quarter"


def test_preserve_amounts_is_opt_in_and_leaves_figures_alone(raw_trace):
    scrubbed = scrub_trace(raw_trace, preserve_amounts=True).trace
    assert scrubbed["tool_results"][0]["grand_total"] == 118000.0
    assert "INR 18,000.00" in scrubbed["answer"]
    # ...but names and identifiers are still redacted even in this mode.
    assert "Rajesh Steel" not in _all_text(scrubbed)
    assert "INDIA-20260722-003" not in _all_text(scrubbed)


def test_non_dict_inputs_are_handled(raw_trace):
    turns = scrub_trace([raw_trace, raw_trace]).trace
    assert isinstance(turns, list) and len(turns) == 2
    assert turns[0]["tool_results"][0]["vendor_name"] == "<VENDOR_1>"
    # One alias registry across the whole list — the same vendor in two turns is
    # one vendor, which is what makes a multi-turn drift case reproducible.
    assert turns[1]["tool_results"][0]["vendor_name"] == "<VENDOR_1>"


def test_empty_and_none_leaves_are_untouched():
    scrubbed = scrub_trace(
        {"answer": "", "notes": None, "citations": [], "passed": True, "llm_calls": 3}
    ).trace
    assert scrubbed == {
        "answer": "",
        "notes": None,
        "citations": [],
        "passed": True,
        "llm_calls": 3,
    }
