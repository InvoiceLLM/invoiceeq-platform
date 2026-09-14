"""Feature 30 tasks 30.19 / 30.20 and the L1 claim verifier.

Every test here asserts a PROPERTY of the layer, never one card's exact sentence. That is
the point of both tasks: the defect classes they close (Gaps 509, 511, 512, 515.2, 517.1,
519, 480) each appeared in several cards at once, and a test pinned to one card's output
would let the next instance through.

The last test is the fixture-mutation check — rename the vendor, swap the currency, change
the item descriptions, and the same claims must still be produced with the same structure.
It is the one that catches a fix written to satisfy one case.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

import services.attachment_insights as ai


# --- money_text: the single number-to-text path (30.20) --------------------


@pytest.mark.parametrize(
    "value,currency,expected",
    [
        (437190, "INR", "₹437,190.00"),
        (Decimal("1200.5"), "EUR", "€1,200.50"),
        (0, "USD", "$0.00"),
        (-98.4, "GBP", "-£98.40"),
        # An unlisted currency renders as its own ISO code, so a tenant billing in a
        # currency nobody has seen needs no code change. This is the generic-vs-hardcoded
        # test applied to the formatter itself.
        (1200.5, "SGD", "SGD 1,200.50"),
        (1200.5, None, "1,200.50"),
        (None, "INR", "an unknown amount"),
    ],
)
def test_money_text_renders_every_currency_without_a_code_change(value, currency, expected):
    assert ai.money_text(value, currency) == expected


def test_money_text_always_emits_two_places_and_separators():
    """Gap 509's shape, as a property.

    The defect was `437190.0` — one decimal place and no separators, straight from a float.
    The property that excludes it is positive, not negative: the output is ALWAYS grouped
    thousands with exactly two decimal places. (A bare `0.10` with no currency is correct
    output, not a Gap 509 instance, which is why "must not look like a float" is the wrong
    assertion here.)
    """
    import re

    shape = re.compile(r"^-?(?:[^\d\s]{1,3}|[A-Z]{3} )?\d{1,3}(?:,\d{3})*\.\d{2}$")
    for value in (437190, 0.1, 1234.5, Decimal("99999999.999"), -5, 1000000):
        for currency in ("INR", "USD", None, "SGD"):
            rendered = ai.money_text(value, currency)
            assert shape.match(rendered), (value, currency, rendered)


def test_days_and_count_text_never_emit_a_plural_bug():
    assert ai.days_text(1) == "1 day"
    assert ai.days_text(0) == "0 days"
    assert ai.days_text(26) == "26 days"
    assert ai.count_text(1, "invoice") == "1 invoice"
    assert ai.count_text(3, "invoice") == "3 invoices"


# --- every claim kind can be rendered (30.20) ------------------------------


def test_every_registered_claim_template_renders_without_raising():
    """A card emits a claim; if no template can turn it into a sentence, the user sees a
    placeholder. This asserts the registry is complete for every kind we register."""
    for kind, template in ai.CLAIM_TEMPLATES.items():
        claim = ai.Claim(
            kind=kind,
            entity="SUBJECT",
            figures={
                k: Decimal("100")
                for k in (
                    "amount", "excess", "remaining", "ordered", "invoiced", "total",
                    "shortfall", "closing_balance", "granted_days", "agreed_days",
                    "horizon_days",
                )
            },
            subjects=["a subject"],
            currency="INR",
        )
        sentence = template(claim)
        assert isinstance(sentence, str) and sentence.strip(), kind


def test_an_unregistered_claim_kind_degrades_instead_of_raising():
    """A bubble must never be taken down by a missing template."""
    sentence = ai.render_claim(ai.Claim(kind="not_registered_anywhere", entity="X"))
    assert "X" in sentence


def test_rendered_claims_carry_no_bare_float():
    """The §11.3 guard, applied to live output rather than to source text."""
    import re

    claim = ai.Claim(
        kind="order_not_fully_invoiced",
        entity="PO-1",
        figures={"remaining": Decimal("437190")},
        currency="INR",
    )
    assert not re.search(r"(?<![\d,.])\d+\.\d(?!\d)", ai.render_claim(claim))


# --- three-state check result (30.19) --------------------------------------


def test_a_check_that_could_not_run_is_never_counted_as_clean():
    log = ai.CheckLog(card="demo")
    log.check_passed("A")
    log.check_not_checked("B", "no comparable line")
    log.check_not_checked("C", "no comparable line")

    title = log.title("lines")
    assert "1 lines checked" in title
    assert "2 not checked" in title

    # And it names WHICH ones, grouped by reason — "2 lines could not be paired" is only
    # useful if the user can see which two.
    detail = log.unchecked_detail()
    assert detail == [{"reason": "no comparable line", "subjects": ["B", "C"], "count": 2}]


def test_a_card_that_evaluated_nothing_does_not_claim_it_checked_things():
    log = ai.CheckLog(card="demo")
    log.check_not_checked("A", "missing input")
    assert log.title("lines") == "0 lines checked, 1 not checked"
    assert log.as_card("lines").status == ai.STATUS_OK


def test_an_all_clear_card_still_reads_as_checked():
    log = ai.CheckLog(card="demo")
    log.check_passed("A")
    log.check_passed("B")
    assert log.title("invoices") == "2 invoices checked"
    assert "not checked" not in log.title("invoices")


def test_the_unchecked_detail_reaches_the_card_evidence():
    log = ai.CheckLog(card="demo")
    log.check_not_checked("A", "reason one")
    card = log.as_card("lines")
    assert card.evidence["not_checked"][0]["subjects"] == ["A"]


# --- ranking (Gap 519) -----------------------------------------------------


def test_an_unquantified_breach_outranks_a_large_routine_figure():
    """Gap 519: only the top 3 findings reach the narrator, and the old key sorted every
    finding WITHOUT an amount below every finding WITH one — so a compliance breach, which
    never carries a currency impact, could not be spoken at all."""
    breach = ai.claim_finding(
        ai.Claim(kind="k", entity="E", severity=ai.SEVERITY_BREACH),
        "breach", card="compliance",
    )
    routine = ai.claim_finding(
        ai.Claim(kind="k", entity="E2", severity=ai.SEVERITY_INFO, currency="INR"),
        "routine", card="open_po_value", impact_amount=9_000_000.0,
    )
    ranked = ai.rank_findings({"findings": [routine, breach]})
    assert ranked[0]["finding_key"] == "breach"


def test_money_still_orders_findings_of_equal_severity():
    small = ai.claim_finding(
        ai.Claim(kind="k", entity="A", severity=ai.SEVERITY_WARN, currency="INR"),
        "small", card="c", impact_amount=10.0, confidence="high",
    )
    large = ai.claim_finding(
        ai.Claim(kind="k", entity="B", severity=ai.SEVERITY_WARN, currency="INR"),
        "large", card="c", impact_amount=5000.0, confidence="high",
    )
    ranked = ai.rank_findings({"findings": [small, large]})
    assert [f["finding_key"] for f in ranked] == ["large", "small"]


# --- L1: is the CLAIM true, not just the FIGURE real? ----------------------


def test_two_cards_asserting_different_values_for_one_fact_are_a_contradiction():
    """Gap 512. The answer-contract gate cannot see this: both figures are real."""
    left = ai.claim_finding(
        ai.Claim(kind="k", entity="PO-1", asserts={"has_linked_invoices": True}),
        "left", card="agreed_vs_billed",
    )
    right = ai.claim_finding(
        ai.Claim(kind="k", entity="PO-1", asserts={"has_linked_invoices": False}),
        "right", card="open_po_value",
    )
    found = ai.verify_claims({"findings": [left, right]})
    assert len(found) == 1
    assert found[0]["entity"] == "PO-1"
    assert found[0]["fact"] == "has_linked_invoices"


def test_agreement_on_a_fact_is_not_a_contradiction():
    rows = [
        ai.claim_finding(
            ai.Claim(kind="k", entity="PO-1", asserts={"has_linked_invoices": True}),
            f"f{i}", card=f"card{i}",
        )
        for i in range(2)
    ]
    assert ai.verify_claims({"findings": rows}) == []


def test_the_same_fact_about_different_entities_is_not_a_contradiction():
    rows = [
        ai.claim_finding(
            ai.Claim(kind="k", entity="PO-1", asserts={"has_linked_invoices": True}),
            "a", card="x",
        ),
        ai.claim_finding(
            ai.Claim(kind="k", entity="PO-2", asserts={"has_linked_invoices": False}),
            "b", card="y",
        ),
    ]
    assert ai.verify_claims({"findings": rows}) == []


# --- the mutation check ----------------------------------------------------


def test_the_same_claim_survives_a_renamed_vendor_and_a_swapped_currency():
    """The check this repo's anti-hardcoding harness exists to force.

    Mutate everything incidental — the party, the currency, the document reference — and
    the layer must produce the SAME claim structure, with only the figures re-rendered.
    A fix written to satisfy one fixture fails here.
    """
    def build(entity: str, currency: str) -> dict:
        return ai.claim_finding(
            ai.Claim(
                kind="billed_over_agreed",
                entity=entity,
                figures={"excess": Decimal("1500")},
                subjects=["purchase order"],
                severity=ai.SEVERITY_BREACH,
                currency=currency,
                asserts={"has_linked_invoices": True},
            ),
            f"agreed_vs_billed:{entity}",
            card="agreed_vs_billed",
            impact_amount=1500.0,
        )

    first = build("RAJ-2009", "INR")
    second = build("ACME-77/B", "SGD")

    assert first["claim"]["kind"] == second["claim"]["kind"]
    assert first["claim"]["severity"] == second["claim"]["severity"]
    assert first["claim"]["asserts"] == second["claim"]["asserts"]

    # Only the rendered words differ, and they differ exactly where the inputs did.
    assert "₹1,500.00" in first["title"] and "RAJ-2009" in first["title"]
    assert "SGD 1,500.00" in second["title"] and "ACME-77/B" in second["title"]
