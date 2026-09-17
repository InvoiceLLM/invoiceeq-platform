"""Runs the two document sets through the real extraction pipeline.

Two modes, and the difference between them is exactly one thing: whether a real
model is asked to read the document.

``verify``  — deterministic, free, no network. Feeds a known extracted record
              plus the case's OCR text straight into `agents/extraction_agent.
              py::verify_node`. This is the real production check function, not
              a reimplementation of it — the ten alert rules under test all live
              behind that one call. What it cannot measure is field-level
              extraction accuracy, because no extraction happened.

``live``    — calls `agents/extraction_agent.py::run_extraction_agent()` end to
              end against the configured Azure OpenAI deployment. Real classify
              -> dynamic_qa -> extract -> verify graph, real retry loop. This is
              the mode that produces a field-accuracy number. Costs real tokens.

Why both, rather than only the live one
----------------------------------------
Alert recall for the five *extraction-surface* mutations is unmeasurable live by
construction: those cases plant an error the model itself would have to make,
and a correctly-behaving model will not make it on demand. `verify` mode is the
only way to answer "if the model fabricated a total, would the check catch it?"
— which is the question Gaps 33/36/43/44/46 were opened for. Live mode is the
only way to answer "does the model fabricate totals in the first place?". They
are different questions and neither mode answers both.

Live mode therefore reports the extraction-surface seeded cases as
`not_applicable` rather than scoring them, and `ConfusionMatrix` keeps them out
of the recall denominator.

What is NOT exercised, stated plainly
--------------------------------------
  * **Page images.** `extract_node` takes the multimodal branch only when
    `LLM_PROVIDER=azure` *and* `state["images"]` is non-empty. These cases carry
    no PDF, so live mode runs the text-prompt branch. `run_extraction_agent()`
    is still the entry point and only skips `pdf_to_base64_images()` because the
    path does not end in `.pdf`.
  * **Document Intelligence.** OCR text is rendered from the spec, not produced
    by a real OCR pass, so nothing here measures OCR quality — only what the
    extraction LLM and the verification checks do with text.
  * **Tenant rules.** Every case runs with `rules=None`, i.e. the untouched
    default tolerances. Feature 18 overrides are a separate axis.
"""

from __future__ import annotations

import copy
import time
from dataclasses import asdict, dataclass, field
from typing import Any, Optional, Protocol, runtime_checkable

from benchmarks.extraction.documents import CLEAN_DOCUMENTS, InvoiceSpec
from benchmarks.extraction.generic_documents import CLEAN_GENERIC_DOCUMENTS
from benchmarks.extraction.metrics import (
    CleanOutcome,
    alert_types,
    compare_fields,
    field_accuracy,
    score_seeded,
)
from benchmarks.extraction.mutations import SeededCase, build_seeded_cases, ocr_result_for

MODE_VERIFY = "verify"
MODE_LIVE = "live"


@runtime_checkable
class ExtractionSpec(Protocol):
    """What the clean-set runner needs from a document fixture.

    BE Gap 687: `run_clean_case` and `score_clean_run` were typed to
    `InvoiceSpec` concretely, so the benchmark could only ever grade invoices --
    ten document types classified, one with extraction ground truth.

    Structural rather than a `Union[InvoiceSpec, DocumentSpec]` on purpose:
    adding a third fixture family later needs no change here, only a type that
    offers these members.

    **How a spec reaches its own schema.** Not through `flow_direction` --
    `"GENERIC"` is not a value a caller may pass, and
    `resolve_direction_profile("GENERIC")` raises `UnknownFlowDirectionError`
    deliberately. `DocumentSpec` is `"INBOUND"` like an inbound invoice, and the
    generic schema is selected downstream by
    `resolve_extraction_profile(flow_direction, doc_type)`. So the routing rides
    on the optional `doc_type` below, which `run_clean_case` forwards into the
    verification state. That is the whole of the "route scoring by spec type"
    BE Gap 687 asked for: the routing already existed in the agent, and the
    harness only had to stop dropping the one field that drives it.

    `doc_type` is optional because `InvoiceSpec` has none -- `getattr(spec,
    "doc_type", None)` yields `None` there, which reproduces the pre-Gap-687
    state dict exactly.
    """

    doc_id: str
    flow_direction: str

    def render_ocr_text(self) -> str: ...

    def ground_truth(self) -> dict[str, Any]: ...

    def initial_extraction(self) -> dict[str, Any]: ...


@dataclass
class CaseRun:
    """One case's raw observation, before scoring. Persisted verbatim."""

    case_id: str
    kind: str  # "clean" | "seeded"
    doc_id: str
    mode: str
    flow_direction: str
    status: Optional[str] = None
    alerts: list[Any] = field(default_factory=list)
    fired_types: list[str] = field(default_factory=list)
    extracted_data: Optional[dict[str, Any]] = None
    latency_ms: float = 0.0
    error: Optional[str] = None


def _verify_only(
    ocr_text: str,
    extracted: dict[str, Any],
    flow_direction: str,
    ocr_result: Optional[dict[str, Any]],
    doc_type: Optional[str] = None,
) -> tuple[str, list[Any]]:
    """Call the real `verify_node` with a hand-supplied extraction.

    The state dict is the real `ExtractionState` shape.

    The `file_path` below used to matter for a second reason: `verify_node`
    carried a `legacy_audit_path_shim` that short-circuited the entire check set
    on an inbound path containing "audit", which would silently turn every case
    into a single bare-string alert. **BE Gap 671 removed that shim** (it was a
    test trigger live in production), so the name is now only cosmetic — kept
    because the `.txt` suffix is what makes `run_extraction_agent` skip the PDF
    fetch in live mode.
    """
    from agents.extraction_agent import verify_node

    state = {
        "file_path": f"benchmark/{flow_direction.lower()}-case.txt",
        "ocr_text": ocr_text,
        "images": [],
        "extracted_data": extracted,
        "alerts": [],
        "status": "PROCESSING",
        "rules": None,
        "complexity": "STANDARD",
        "ocr_result": ocr_result,
        "retry_count": 0,
        "max_retries": 2,
        "feedback": [],
        "dynamic_qa_context": None,
        "flow_direction": flow_direction,
        "tenant_id": "",
        # BE Gap 687: `verify_node` reads this to resolve the verification
        # rubric (`resolve_verification_rubric(flow_direction, doc_type)`), which
        # is what lets a non-invoice document be checked as itself rather than as
        # an invoice that is missing a total. `None` for an `InvoiceSpec`, which
        # reproduces the pre-Gap-687 state dict exactly.
        "doc_type": doc_type,
    }
    result = verify_node(state)  # type: ignore[arg-type]
    return result.get("status", ""), list(result.get("alerts") or [])


def _run_live(ocr_text: str, flow_direction: str, tenant_id: str) -> dict[str, Any]:
    """The real end-to-end graph. `.txt` path so no PDF fetch is attempted.

    No `doc_type` override: live mode lets the classifier node decide the type
    from the document, which is the behaviour under test. Passing the spec's own
    `doc_type` here would grade extraction while hiding a misclassification.
    """
    from agents.extraction_agent import run_extraction_agent

    return run_extraction_agent(
        file_path=f"benchmark/{flow_direction.lower()}-case.txt",
        ocr_text=ocr_text,
        tenant_id=tenant_id,
        rules=None,
        ocr_result=None,
        flow_direction=flow_direction,
    )


# ---------------------------------------------------------------------------
# Clean set
# ---------------------------------------------------------------------------


def run_clean_case(spec: ExtractionSpec, mode: str, tenant_id: str = "") -> CaseRun:
    started = time.perf_counter()
    run = CaseRun(
        case_id=f"{spec.doc_id}__clean",
        kind="clean",
        doc_id=spec.doc_id,
        mode=mode,
        flow_direction=spec.flow_direction,
    )
    try:
        if mode == MODE_VERIFY:
            extracted = copy.deepcopy(spec.initial_extraction())
            status, alerts = _verify_only(
                spec.render_ocr_text(),
                extracted,
                spec.flow_direction,
                None,
                doc_type=getattr(spec, "doc_type", None),
            )
            run.status, run.alerts, run.extracted_data = status, alerts, extracted
        else:
            result = _run_live(spec.render_ocr_text(), spec.flow_direction, tenant_id)
            run.status = result.get("status")
            run.alerts = list(result.get("alerts") or [])
            run.extracted_data = result.get("extracted_data")
    except Exception as e:  # pragma: no cover - surfaced, never swallowed
        run.error = f"{type(e).__name__}: {e}"
    run.fired_types = alert_types(run.alerts)
    run.latency_ms = round((time.perf_counter() - started) * 1000, 1)
    return run


def score_clean_run(spec: ExtractionSpec, run: CaseRun, mode: str) -> CleanOutcome:
    """A clean document that raises any alert at all is a false positive.

    Field accuracy is only meaningful in live mode — in verify mode the
    extraction handed in *is* the ground truth, so scoring it would report a
    guaranteed 100% that measures nothing. It is left at 0/0 there, which
    `field_accuracy` reports as an empty denominator rather than as a perfect
    score.
    """
    outcome = CleanOutcome(case_id=run.case_id, fired=run.fired_types)
    outcome.false_positive = bool(run.fired_types)
    if mode == MODE_LIVE:
        comparisons = compare_fields(spec.ground_truth(), run.extracted_data)
        correct, total, _ = field_accuracy(comparisons)
        outcome.comparisons = comparisons
        outcome.field_correct, outcome.field_total = correct, total
    return outcome


# ---------------------------------------------------------------------------
# Seeded set
# ---------------------------------------------------------------------------


def run_seeded_case(case: SeededCase, mode: str, tenant_id: str = "") -> CaseRun:
    started = time.perf_counter()
    run = CaseRun(
        case_id=case.case_id,
        kind="seeded",
        doc_id=case.doc_id,
        mode=mode,
        flow_direction=case.flow_direction,
    )
    try:
        if mode == MODE_VERIFY:
            extracted = copy.deepcopy(case.extracted_data)
            status, alerts = _verify_only(
                case.ocr_text, extracted, case.flow_direction, ocr_result_for(case)
            )
            run.status, run.alerts, run.extracted_data = status, alerts, extracted
        else:
            result = _run_live(case.ocr_text, case.flow_direction, tenant_id)
            run.status = result.get("status")
            run.alerts = list(result.get("alerts") or [])
            run.extracted_data = result.get("extracted_data")
    except Exception as e:  # pragma: no cover
        run.error = f"{type(e).__name__}: {e}"
    run.fired_types = alert_types(run.alerts)
    run.latency_ms = round((time.perf_counter() - started) * 1000, 1)
    return run


def score_seeded_run(case: SeededCase, run: CaseRun, mode: str):
    """Score one seeded case, marking it not-applicable where the mode can't test it."""
    if mode == MODE_LIVE and not case.gradeable_live:
        return score_seeded(
            case.case_id,
            case.expected_alert_type,
            case.tolerated_alert_types,
            run.fired_types,
            not_applicable=True,
            note=(
                "extraction-surface mutation: the planted error is one the model "
                "itself would have to make, so live mode cannot reproduce it. "
                "Graded in verify mode instead."
            ),
        )
    return score_seeded(
        case.case_id, case.expected_alert_type, case.tolerated_alert_types, run.fired_types
    )


# ---------------------------------------------------------------------------
# Whole-suite driver
# ---------------------------------------------------------------------------


@dataclass
class BenchmarkResult:
    mode: str
    clean_runs: list[CaseRun] = field(default_factory=list)
    seeded_runs: list[CaseRun] = field(default_factory=list)
    clean_outcomes: list[CleanOutcome] = field(default_factory=list)
    seeded_outcomes: list[Any] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "clean_runs": [asdict(r) for r in self.clean_runs],
            "seeded_runs": [asdict(r) for r in self.seeded_runs],
            "clean_outcomes": [asdict(o) for o in self.clean_outcomes],
            "seeded_outcomes": [asdict(o) for o in self.seeded_outcomes],
        }


def run_benchmark(
    mode: str = MODE_VERIFY,
    *,
    case_ids: Optional[set[str]] = None,
    tenant_id: str = "",
    on_progress=None,
) -> BenchmarkResult:
    """Run both sets in `mode` and score them. Pure orchestration."""
    if mode not in (MODE_VERIFY, MODE_LIVE):
        raise ValueError(f"unknown mode {mode!r}; expected {MODE_VERIFY!r} or {MODE_LIVE!r}")

    result = BenchmarkResult(mode=mode)

    # BE Gap 687: invoices *and* the non-invoice specs. Both satisfy
    # `ExtractionSpec`, and each carries the `flow_direction` that routes it to
    # its own schema, so no branch is needed here.
    for spec in tuple(CLEAN_DOCUMENTS) + tuple(CLEAN_GENERIC_DOCUMENTS):
        case_id = f"{spec.doc_id}__clean"
        if case_ids and case_id not in case_ids:
            continue
        run = run_clean_case(spec, mode, tenant_id)
        result.clean_runs.append(run)
        result.clean_outcomes.append(score_clean_run(spec, run, mode))
        if on_progress:
            on_progress(run)

    for case in build_seeded_cases():
        if case_ids and case.case_id not in case_ids:
            continue
        # A not-applicable case is not executed at all in live mode: running it
        # would spend real tokens producing an observation nothing scores.
        if mode == MODE_LIVE and not case.gradeable_live:
            run = CaseRun(
                case_id=case.case_id,
                kind="seeded",
                doc_id=case.doc_id,
                mode=mode,
                flow_direction=case.flow_direction,
                status="SKIPPED",
            )
        else:
            run = run_seeded_case(case, mode, tenant_id)
        result.seeded_runs.append(run)
        result.seeded_outcomes.append(score_seeded_run(case, run, mode))
        if on_progress:
            on_progress(run)

    return result


__all__ = [
    "MODE_LIVE",
    "MODE_VERIFY",
    "BenchmarkResult",
    "CaseRun",
    "run_benchmark",
    "run_clean_case",
    "run_seeded_case",
    "score_clean_run",
    "score_seeded_run",
]
