"""Scoring for Track 1: field-level accuracy, and the alert confusion matrix.

Nothing here calls a model. Every number this module produces is a deterministic
function of (ground truth, extracted record, alerts fired), so two runs of the
same mode over the same cases produce the same figures and a change in them is
attributable to the pipeline, not to grader variance.

Field accuracy — what counts as equal
--------------------------------------
Comparing extracted invoice fields is not string equality, and pretending it is
would produce an accuracy figure that mostly measures formatting:

  * **Money and numbers** compare to the cent (`_MONEY_TOLERANCE`). `5085`,
    `5085.0` and `5085.00` are one value.
  * **Dates** are normalised to `YYYY-MM-DD` where the extracted form is
    recognisable, because the schema asks for that format "if possible" and a
    model that returns `14 Jul 2026` got the date right.
  * **Names** are compared case-insensitively with punctuation and legal-entity
    suffixes (`Ltd`, `LLC`, `Pvt`, `GmbH`, `Inc`, `Corp`, `BV`) stripped, for
    the same reason `utils/trace_scrubbing.py::_short_form()` strips them:
    "Cascade Industrial Supply LLC" and "Cascade Industrial Supply" are the same
    vendor and scoring them as a miss would be measuring punctuation.
  * **Line items** are matched positionally after both lists are sorted by
    description, and each of `description`/`quantity`/`unit_price`/`amount` is
    its own graded field. A missing or extra line is counted as a miss on every
    field of that line, so dropping a line item cannot be cheaper than
    mis-reading one.
  * **`None` on both sides is a hit.** A correctly-absent optional field (no PO
    number on the GST invoice) is a correct extraction, not an unscored one.

Alert scoring — what a hit actually is
---------------------------------------
Recall is per seeded case, and a hit requires the **expected type specifically**,
not "some alert fired". A pipeline that raised `tax_mismatch` on every document
would otherwise score 100% recall while being useless. Alerts that are neither
the expected type nor listed in the case's `tolerated_alert_types` are reported
as **collateral** — not scored against recall (the case's own planted issue was
still caught) but surfaced, because a check that fires on things it was not
seeded for is the same miscalibration signal as a clean-set false positive.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Iterable, Optional

_MONEY_TOLERANCE = 0.005

_ENTITY_SUFFIXES = {
    "ltd", "limited", "llc", "llp", "inc", "incorporated", "corp", "corporation",
    "pvt", "private", "gmbh", "bv", "nv", "sa", "ag", "plc", "co", "company",
    "traders", "group",
}

_DATE_FORMATS_RE = (
    (re.compile(r"^(\d{4})-(\d{2})-(\d{2})$"), lambda m: f"{m[1]}-{m[2]}-{m[3]}"),
    (re.compile(r"^(\d{2})/(\d{2})/(\d{4})$"), lambda m: f"{m[3]}-{m[2]}-{m[1]}"),
    (re.compile(r"^(\d{4})/(\d{2})/(\d{2})$"), lambda m: f"{m[1]}-{m[2]}-{m[3]}"),
)

_MONEY_FIELDS = frozenset(
    {"subtotal", "tax_amount", "grand_total", "round_off", "discount_amount",
     "quantity", "unit_price", "amount"}
)
_DATE_FIELDS = frozenset({"invoice_date", "due_date"})
_NAME_FIELDS = frozenset({"vendor_name", "customer_name"})


def _normalise_name(value: str) -> str:
    tokens = re.sub(r"[^\w\s]", " ", value.lower()).split()
    kept = [t for t in tokens if t not in _ENTITY_SUFFIXES]
    return " ".join(kept or tokens)


def _normalise_date(value: str) -> str:
    value = value.strip()
    for pattern, build in _DATE_FORMATS_RE:
        m = pattern.match(value)
        if m:
            return build(m)
    return value.lower()


def values_match(field_name: str, expected: Any, actual: Any) -> bool:
    """Is `actual` a correct extraction of `expected` for this field?"""
    if expected is None and actual is None:
        return True
    if expected is None or actual is None:
        return False
    base = field_name.split(".")[-1]
    if base in _MONEY_FIELDS:
        try:
            return abs(float(expected) - float(actual)) <= _MONEY_TOLERANCE
        except (TypeError, ValueError):
            return False
    if base in _DATE_FIELDS:
        return _normalise_date(str(expected)) == _normalise_date(str(actual))
    if base in _NAME_FIELDS:
        return _normalise_name(str(expected)) == _normalise_name(str(actual))
    return str(expected).strip().lower() == str(actual).strip().lower()


@dataclass
class FieldComparison:
    field_name: str
    expected: Any
    actual: Any
    correct: bool


_LINE_FIELDS = ("description", "quantity", "unit_price", "amount")


def compare_fields(
    ground_truth: dict[str, Any], extracted: Optional[dict[str, Any]]
) -> list[FieldComparison]:
    """Field-by-field comparison, line items expanded into their own fields.

    An extraction of `None` (the pipeline failed outright) is not skipped — it
    is scored as every field missed. A benchmark that dropped failed extractions
    from the denominator would report its highest accuracy on the day the model
    stopped responding.
    """
    extracted = extracted or {}
    out: list[FieldComparison] = []

    for name, expected in ground_truth.items():
        if name == "items":
            continue
        actual = extracted.get(name)
        out.append(FieldComparison(name, expected, actual, values_match(name, expected, actual)))

    expected_items = list(ground_truth.get("items") or [])
    actual_items = list(extracted.get("items") or [])
    key = lambda item: str((item or {}).get("description", "")).strip().lower()  # noqa: E731
    expected_items.sort(key=key)
    actual_items.sort(key=key)
    for i in range(max(len(expected_items), len(actual_items))):
        exp = expected_items[i] if i < len(expected_items) else None
        act = actual_items[i] if i < len(actual_items) else None
        for sub in _LINE_FIELDS:
            e = (exp or {}).get(sub) if exp is not None else None
            a = (act or {}).get(sub) if act is not None else None
            correct = (exp is not None and act is not None) and values_match(sub, e, a)
            out.append(FieldComparison(f"items[{i}].{sub}", e, a, correct))
    return out


def field_accuracy(comparisons: Iterable[FieldComparison]) -> tuple[int, int, float]:
    """`(correct, total, ratio)`. Ratio is 0.0 on an empty comparison set."""
    comparisons = list(comparisons)
    correct = sum(1 for c in comparisons if c.correct)
    total = len(comparisons)
    return correct, total, (correct / total if total else 0.0)


# ---------------------------------------------------------------------------
# Alerts
# ---------------------------------------------------------------------------


def alert_types(alerts: Optional[list[Any]]) -> list[str]:
    """The `type` of every alert, tolerating the two shapes `verify_node` emits.

    `verify_node`'s legacy audit-path shim returns bare strings (`["Math
    mismatch"]`), and `token_limit_exceeded` is a dict like every other alert.
    A bare string is reported under a stable pseudo-type so it is visible rather
    than dropped.
    """
    out: list[str] = []
    for alert in alerts or []:
        if isinstance(alert, dict):
            out.append(str(alert.get("type") or "untyped_alert"))
        else:
            out.append("legacy_string_alert")
    return out


@dataclass
class SeededOutcome:
    case_id: str
    expected_alert_type: str
    fired: list[str]
    hit: bool
    collateral: list[str]
    #: True when this case cannot be graded in the mode it was run in — an
    #: extraction-surface mutation under live mode. Excluded from the recall
    #: denominator entirely, and counted separately so the exclusion is visible.
    not_applicable: bool = False
    note: str = ""


@dataclass
class CleanOutcome:
    case_id: str
    fired: list[str]
    #: Any alert at all on a clean document is a false positive.
    false_positive: bool = False
    field_correct: int = 0
    field_total: int = 0
    comparisons: list[FieldComparison] = field(default_factory=list)


def score_seeded(
    case_id: str,
    expected_alert_type: str,
    tolerated: Iterable[str],
    fired: list[str],
    *,
    not_applicable: bool = False,
    note: str = "",
) -> SeededOutcome:
    tolerated_set = set(tolerated) | {expected_alert_type}
    return SeededOutcome(
        case_id=case_id,
        expected_alert_type=expected_alert_type,
        fired=fired,
        hit=expected_alert_type in fired,
        collateral=sorted({t for t in fired if t not in tolerated_set}),
        not_applicable=not_applicable,
        note=note,
    )


@dataclass
class ConfusionMatrix:
    """The real confusion matrix the feature doc asks for, over *documents*.

    The unit is one document, not one alert, and the four cells mean:

      * **TP** — a seeded document where the expected check fired.
      * **FN** — a seeded document where it did not. This is the number the
        feature doc calls unmeasurable from production usage.
      * **FP** — a clean document that raised any alert at all.
      * **TN** — a clean document that stayed silent.

    Not-applicable seeded cases (extraction-surface mutations under live mode)
    are outside all four cells and reported separately, so recall is never
    computed over a denominator that includes cases the mode could not test.
    """

    true_positive: int = 0
    false_negative: int = 0
    false_positive: int = 0
    true_negative: int = 0
    not_applicable: int = 0

    @property
    def recall(self) -> Optional[float]:
        denom = self.true_positive + self.false_negative
        return (self.true_positive / denom) if denom else None

    @property
    def false_positive_rate(self) -> Optional[float]:
        denom = self.false_positive + self.true_negative
        return (self.false_positive / denom) if denom else None

    @property
    def precision(self) -> Optional[float]:
        """Document-level precision: of the documents that alerted, how many
        actually had a planted issue.

        Stated as document-level on purpose. It is **not** the "alert precision"
        the feature doc's parameter table defines (% of alerts leading to a real
        correction in the Review Console) — that one is measured from human
        action on production data and cannot be computed here at all.
        """
        denom = self.true_positive + self.false_positive
        return (self.true_positive / denom) if denom else None

    def as_dict(self) -> dict[str, Any]:
        return {
            "true_positive": self.true_positive,
            "false_negative": self.false_negative,
            "false_positive": self.false_positive,
            "true_negative": self.true_negative,
            "not_applicable": self.not_applicable,
            "recall": self.recall,
            "false_positive_rate": self.false_positive_rate,
            "document_level_precision": self.precision,
        }


def build_confusion(
    clean: Iterable[CleanOutcome], seeded: Iterable[SeededOutcome]
) -> ConfusionMatrix:
    matrix = ConfusionMatrix()
    for outcome in clean:
        if outcome.false_positive:
            matrix.false_positive += 1
        else:
            matrix.true_negative += 1
    for outcome in seeded:
        if outcome.not_applicable:
            matrix.not_applicable += 1
        elif outcome.hit:
            matrix.true_positive += 1
        else:
            matrix.false_negative += 1
    return matrix


def recall_by_alert_type(seeded: Iterable[SeededOutcome]) -> dict[str, dict[str, Any]]:
    """Per-check recall. One overall number hides which check is the broken one."""
    buckets: dict[str, dict[str, Any]] = {}
    for outcome in seeded:
        if outcome.not_applicable:
            continue
        bucket = buckets.setdefault(
            outcome.expected_alert_type, {"seeded": 0, "detected": 0, "missed_cases": []}
        )
        bucket["seeded"] += 1
        if outcome.hit:
            bucket["detected"] += 1
        else:
            bucket["missed_cases"].append(outcome.case_id)
    for bucket in buckets.values():
        bucket["recall"] = bucket["detected"] / bucket["seeded"] if bucket["seeded"] else None
    return buckets


__all__ = [
    "CleanOutcome",
    "ConfusionMatrix",
    "FieldComparison",
    "SeededOutcome",
    "alert_types",
    "build_confusion",
    "compare_fields",
    "field_accuracy",
    "recall_by_alert_type",
    "score_seeded",
    "values_match",
]
