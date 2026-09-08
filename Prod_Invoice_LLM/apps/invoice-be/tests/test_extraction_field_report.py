"""Gap 485 (Feature 29 phase-2 P1.3) -- per-field accuracy in the extraction report.

The report could say which DOCUMENTS were wrong. It could not say which FIELD is weakest
across the bank, which is the question that decides what to fix next. That matters because
the composite hides exactly the case worth finding: forty fields at 100% will carry one
field at 70% to a 98.8% composite, and the composite is what gets quoted.

  1. `field_accuracy_by_field` buckets every comparison and reports correct/total/ratio.
  2. Line-item indices collapse (`items[3].amount` -> `items[].amount`), or the table would
     be one row per line of every invoice, each with a denominator of one -- which measures
     nothing.
  3. Every compared field appears, including the perfect ones. A report listing only
     failures cannot show that a field stopped being extracted at all.
  4. The composite is unchanged and stays the headline.
"""
from __future__ import annotations

from benchmarks.extraction.metrics import (
    FieldComparison,
    field_accuracy,
    field_accuracy_by_field,
    normalise_field_name,
)


def _c(name: str, correct: bool) -> FieldComparison:
    return FieldComparison(name, "e", "a", correct)


# --- name normalisation -----------------------------------------------------

def test_line_item_indices_collapse_to_one_field():
    assert normalise_field_name("items[0].amount") == "items[].amount"
    assert normalise_field_name("items[17].description") == "items[].description"


def test_ordinary_field_names_are_untouched():
    for name in ("grand_total", "tax_amount", "vendor_name", "invoice_number"):
        assert normalise_field_name(name) == name


def test_a_name_that_merely_starts_with_items_is_not_mangled():
    assert normalise_field_name("items_count") == "items_count"


# --- bucketing --------------------------------------------------------------

def test_every_compared_field_appears_including_the_perfect_ones():
    comparisons = [_c("grand_total", True), _c("tax_amount", False), _c("vendor_name", True)]
    by_field = field_accuracy_by_field(comparisons)
    assert set(by_field) == {"grand_total", "tax_amount", "vendor_name"}
    assert by_field["grand_total"]["ratio"] == 1.0
    assert by_field["tax_amount"]["ratio"] == 0.0


def test_line_items_are_aggregated_across_lines_into_one_row():
    comparisons = [
        _c("items[0].amount", True),
        _c("items[1].amount", True),
        _c("items[2].amount", False),
        _c("items[0].description", True),
    ]
    by_field = field_accuracy_by_field(comparisons)
    assert set(by_field) == {"items[].amount", "items[].description"}
    assert by_field["items[].amount"] == {"correct": 2, "total": 3, "ratio": 2 / 3}
    assert by_field["items[].description"]["total"] == 1


def test_the_weak_field_the_composite_hides_is_visible_per_field():
    """The failure mode this exists for, as an assertion."""
    comparisons = [_c(f"field_{i}", True) for i in range(40)]
    comparisons += [_c("tax_amount", i < 7) for i in range(10)]
    correct, total, ratio = field_accuracy(comparisons)
    # 47 of 50 = 0.94: a composite nobody would investigate
    assert ratio == 0.94

    by_field = field_accuracy_by_field(comparisons)
    assert by_field["tax_amount"]["ratio"] == 0.7
    worst = min(by_field.items(), key=lambda kv: kv[1]["ratio"])
    assert worst[0] == "tax_amount", "the weakest field must be findable"


def test_an_empty_comparison_set_is_an_empty_table_not_a_crash():
    assert field_accuracy_by_field([]) == {}


def test_the_composite_is_unchanged_by_this_addition():
    comparisons = [_c("a", True), _c("b", False), _c("items[0].amount", True)]
    assert field_accuracy(comparisons) == (2, 3, 2 / 3)
    # and the per-field totals reconcile with it
    by_field = field_accuracy_by_field(comparisons)
    assert sum(b["total"] for b in by_field.values()) == 3
    assert sum(b["correct"] for b in by_field.values()) == 2


# --- the report wiring ------------------------------------------------------

def test_the_summary_carries_the_per_field_table():
    import inspect

    from benchmarks.extraction import artifacts

    src = inspect.getsource(artifacts)
    assert '"field_accuracy_by_field": field_accuracy_by_field(' in src
    # the composite must still be there, and still be the headline line
    assert '"field_accuracy": {' in src


def test_the_markdown_and_console_reports_sort_worst_first():
    """Worst-first is not cosmetic: the ordering IS the recommendation."""
    import inspect
    from pathlib import Path

    from benchmarks.extraction import artifacts

    md = inspect.getsource(artifacts)
    assert 'key=lambda kv: (kv[1]["ratio"], -kv[1]["total"], kv[0])' in md
    assert "Accuracy per field (every ground-truth field, worst first)" in md

    runner = (
        Path(__file__).resolve().parents[1] / "scripts" / "run_extraction_benchmark.py"
    ).read_text(encoding="utf-8")
    assert "per field (worst first):" in runner
