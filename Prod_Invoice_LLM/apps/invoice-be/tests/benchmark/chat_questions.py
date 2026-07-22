"""Derives a small RAG-chat question set from a day's generated invoice batch,
scoped to specific invoice numbers (not tenant-wide aggregates) so answers can
be graded against ground truth we control, without contamination from any
other data that happens to sit in the mock test tenant.

Kept deliberately light (3 questions per region per day, not per-invoice) -
the extraction pass already makes 10 real LLM calls per region; this adds a
small, representative RAG sample rather than tripling the run's cost.

Grading is heuristic (substring/number-proximity match on a free-text LLM
answer), not exact - results are reported as pass/fail/inconclusive with the
raw Q&A included so a human can eyeball anything marked inconclusive.
"""
import re
from dataclasses import dataclass

from tests.benchmark.generator import GeneratedInvoice

AMOUNT_TOLERANCE = 0.05  # relative, e.g. 0.05 = 5%


@dataclass
class ChatQuestion:
    region: str
    invoice_number: str  # "*" for cross-invoice aggregate questions
    kind: str  # "amount" | "vendor" | "audit_status" | "audit_count" | "mutating_regression"
    question: str
    expected: object


def _pick_sample(batch: list[GeneratedInvoice]) -> list[GeneratedInvoice]:
    """One clean + one flawed (+ one high-complexity if distinct) invoice per region."""
    clean = next((g for g in batch if g.ground_truth.get("expected_status") == "COMPLETED"), None)
    flawed = next((g for g in batch if g.ground_truth.get("expected_status") == "AUDIT_REQUIRED"), None)
    picks = [g for g in (clean, flawed) if g is not None]
    return picks


def build_daily_chat_questions(batches_by_region: dict[str, list[GeneratedInvoice]]) -> list[ChatQuestion]:
    questions: list[ChatQuestion] = []
    for region, batch in batches_by_region.items():
        for gen in _pick_sample(batch):
            gt = gen.ground_truth
            invoice_number = gt.get("invoice_number", gen.name)

            questions.append(ChatQuestion(
                region=region,
                invoice_number=invoice_number,
                kind="amount",
                question=f"What is the total amount (grand total) for invoice {invoice_number}?",
                expected=gt.get("expected_grand_total"),
            ))
            questions.append(ChatQuestion(
                region=region,
                invoice_number=invoice_number,
                kind="vendor",
                question=f"Who is the vendor on invoice {invoice_number}?",
                expected=gt.get("expected_vendor_name"),
            ))
            questions.append(ChatQuestion(
                region=region,
                invoice_number=invoice_number,
                kind="audit_status",
                question=f"Is invoice {invoice_number} flagged for audit? If so, why?",
                expected=gt.get("expected_status"),
            ))

    # Cross-invoice aggregate question, one per day (not per region) — exercises SQL
    # generation over the whole batch (Gap 13 territory) instead of a single-invoice
    # lookup, and its natural phrasing ("most recently created") is a direct regression
    # check for Gap 32 (mutating-SQL guardrail false-triggering on ORDER BY created_at).
    total_audit_required = sum(
        1 for batch in batches_by_region.values() for g in batch
        if g.ground_truth.get("expected_status") == "AUDIT_REQUIRED"
    )
    questions.append(ChatQuestion(
        region="ALL",
        invoice_number="*",
        kind="audit_count",
        question="How many invoices are currently flagged for audit (status AUDIT_REQUIRED)?",
        expected=total_audit_required,
    ))
    questions.append(ChatQuestion(
        region="ALL",
        invoice_number="*",
        kind="mutating_regression",
        question="Which invoice was created most recently?",
        expected=None,
    ))
    return questions


_NUMBER_RE = re.compile(r"[-+]?\d[\d,]*\.?\d*")


def grade_answer(q: ChatQuestion, answer: str) -> str:
    """Returns 'pass', 'fail', or 'inconclusive'."""
    text = (answer or "").lower()

    if q.kind == "amount":
        expected = q.expected
        if expected is None:
            return "inconclusive"
        found = [float(m.replace(",", "")) for m in _NUMBER_RE.findall(answer or "")]
        if not found:
            return "fail"
        return "pass" if any(abs(f - expected) <= max(AMOUNT_TOLERANCE * expected, 0.5) for f in found) else "fail"

    if q.kind == "vendor":
        expected = (q.expected or "").lower()
        if not expected:
            return "inconclusive"
        # accept if any significant word from the vendor name appears in the answer
        words = [w for w in re.split(r"\W+", expected) if len(w) > 3]
        return "pass" if words and any(w in text for w in words) else "fail"

    if q.kind == "audit_status":
        expects_audit = q.expected == "AUDIT_REQUIRED"
        mentions_audit = any(kw in text for kw in ["audit", "flag", "mismatch", "discrepanc", "issue"])
        if expects_audit:
            return "pass" if mentions_audit else "fail"
        # clean invoice: pass unless it wrongly claims an audit/issue
        return "fail" if mentions_audit else "pass"

    if q.kind == "audit_count":
        expected = q.expected
        if expected is None:
            return "inconclusive"
        found = [int(float(m.replace(",", ""))) for m in _NUMBER_RE.findall(answer or "")]
        return "pass" if expected in found else "fail"

    if q.kind == "mutating_regression":
        # Gap 32 regression: the question just needs to NOT be rejected by the
        # mutating-SQL guardrail. Don't care what the actual answer content is.
        failure_markers = ["mutating sql operations", "failed to execute database check"]
        return "fail" if any(m in text for m in failure_markers) else "pass"

    return "inconclusive"
