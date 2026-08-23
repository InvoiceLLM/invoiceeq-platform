"""Generates the review artifacts under `docs/extraction_benchmark/`.

The founder's requirement, verbatim: keep detailed artifacts of exactly what was
generated and how — what was mutated, what the expected correct answer is versus
the planted issue — in a clearly organised location, because architect and a
business analyst review these before the set is trusted as the real benchmark.

So this module writes the corpus out in a form that can be read without reading
any Python:

  ``case_manifest.json``   Machine-readable. Every clean document (full OCR text
                           + full ground truth) and every seeded case (mutation
                           name, surface, field path, correct value, planted
                           value, expected alert, rationale, full mutated OCR
                           text, full mutated record).
  ``case_manifest.md``     The same content as review prose + tables.
  ``documents/*.txt``      One file per rendered document, clean and seeded, so
                           a reviewer can diff a seeded document against its
                           clean parent with any diff tool.
  ``runs/<mode>-<ts>.json`` One measurement run's raw observations and scores.
  ``runs/<mode>-latest.md`` The most recent run of that mode, as a summary table.

Everything in here is derived — regenerating over a clean tree reproduces it
byte for byte, because `documents.py` and `mutations.py` contain no randomness.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from benchmarks.extraction.documents import CLEAN_DOCUMENTS
from benchmarks.extraction.harness import BenchmarkResult
from benchmarks.extraction.metrics import build_confusion, field_accuracy, recall_by_alert_type
from benchmarks.extraction.mutations import (
    MUTATION_ABS_FLOOR,
    MUTATION_REL,
    build_seeded_cases,
)

#: `<repo>/Prod_Invoice_LLM/apps/invoice-be/docs/extraction_benchmark`
ARTIFACT_ROOT = Path(__file__).resolve().parents[2] / "docs" / "extraction_benchmark"


def _fmt(value: Any) -> str:
    if value is None:
        return "_(absent)_"
    if isinstance(value, float):
        return f"{value:,.2f}"
    return f"`{value}`"


# ---------------------------------------------------------------------------
# Corpus manifest
# ---------------------------------------------------------------------------


def build_manifest() -> dict[str, Any]:
    """The whole corpus as one JSON-serialisable structure."""
    seeded = build_seeded_cases()
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "generator": "tests/extraction_benchmark/{documents,mutations}.py",
        "determinism": (
            "No RNG. Regenerating from an unchanged tree reproduces this file "
            "byte for byte."
        ),
        "mutation_policy": {
            "relative": MUTATION_REL,
            "absolute_floor": MUTATION_ABS_FLOOR,
            "why": (
                "verify_line_items_math / verify_totals_math accept "
                "max(0.01, 0.5% relative) (Gap 31). Every arithmetic mutation "
                "clears that band with about an order of magnitude of headroom, "
                "so a recall miss is never explainable as a near-miss."
            ),
        },
        "clean_documents": [
            {
                "doc_id": spec.doc_id,
                "flow_direction": spec.flow_direction,
                "region": spec.region,
                "currency": spec.currency,
                "rationale": spec.rationale,
                "ocr_text": spec.render_ocr_text(),
                "ground_truth": spec.ground_truth(),
            }
            for spec in CLEAN_DOCUMENTS
        ],
        "seeded_cases": [
            {
                "case_id": case.case_id,
                "parent_document": case.doc_id,
                "mutation": case.mutation,
                "surface": case.surface,
                "gradeable_in_live_mode": case.gradeable_live,
                "field_path": case.field_path,
                "correct_value": case.correct_value,
                "planted_value": case.planted_value,
                "expected_alert_type": case.expected_alert_type,
                "tolerated_alert_types": list(case.tolerated_alert_types),
                "rationale": case.rationale,
                "mutated_ocr_text": case.ocr_text,
                "extraction_under_test": case.extracted_data,
            }
            for case in seeded
        ],
    }


def render_manifest_markdown(manifest: dict[str, Any]) -> str:
    lines: list[str] = []
    add = lines.append
    add("# Extraction benchmark — case manifest")
    add("")
    add(
        "**Generated file. Do not edit.** Regenerate with "
        "`uv run python scripts/run_extraction_benchmark.py --artifacts-only`."
    )
    add("")
    add(f"Generated: `{manifest['generated_at']}` from `{manifest['generator']}`.")
    add("")
    add(
        "This is the review artifact for Feature 23 Track 1. It exists so architect "
        "and a business analyst can check **what was planted and why** without "
        "reading the generator. Every seeded case states the field that was "
        "changed, the correct value, the value planted instead, and the exact "
        "alert type that must fire for the case to count as detected."
    )
    add("")
    add("## Mutation sizing policy")
    add("")
    policy = manifest["mutation_policy"]
    add(
        f"Every arithmetic mutation shifts its figure by "
        f"`max({policy['relative']:.0%} of the amount, {policy['absolute_floor']:.2f})`. "
        + policy["why"]
    )
    add("")
    add("## Clean documents")
    add("")
    add(
        "Internally consistent by construction: every line amount equals "
        "quantity x unit price, the lines sum to the subtotal, and "
        "subtotal - discount + tax + round-off equals the grand total. Every "
        "figure in the ground truth is printed verbatim in the document text, so "
        "all five source-text faithfulness checks must stay silent on all of them."
    )
    add("")
    add("| Document | Direction | Region | Currency | Grand total | Why this shape |")
    add("|---|---|---|---|---|---|")
    for doc in manifest["clean_documents"]:
        gt = doc["ground_truth"]
        add(
            f"| `{doc['doc_id']}` | {doc['flow_direction']} | {doc['region']} | "
            f"{doc['currency']} | {gt['grand_total']:,.2f} | {doc['rationale']} |"
        )
    add("")
    add("## Seeded cases")
    add("")
    add(
        "One planted issue per case, deliberately. Two would make *which check "
        "caught it* ambiguous, and alert recall is the reason this set exists."
    )
    add("")
    add(
        "`surface` is load-bearing. **document** = the OCR text was mutated, so "
        "the document itself is inconsistent and a faithful extraction should "
        "reproduce the problem — gradeable in both run modes. **extraction** = "
        "the extracted record was mutated while the text stayed clean, "
        "simulating the model going wrong — gradeable in verify mode only, "
        "because a correctly-behaving model will not make the planted error on "
        "demand."
    )
    add("")
    add("| Case | Parent | Surface | Field | Correct | Planted | Must fire |")
    add("|---|---|---|---|---|---|---|")
    for case in manifest["seeded_cases"]:
        add(
            f"| `{case['case_id']}` | `{case['parent_document']}` | {case['surface']} | "
            f"`{case['field_path']}` | {_fmt(case['correct_value'])} | "
            f"{_fmt(case['planted_value'])} | `{case['expected_alert_type']}` |"
        )
    add("")
    add("### Why each issue was planted")
    add("")
    for case in manifest["seeded_cases"]:
        add(f"**`{case['case_id']}`** — {case['rationale']}")
        tolerated = case["tolerated_alert_types"]
        if tolerated:
            add("")
            add(
                "  Tolerated side effects (the same planted issue legitimately "
                "trips these too, and they are not counted against the case): "
                + ", ".join(f"`{t}`" for t in tolerated)
                + "."
            )
        add("")
    add("## Document text")
    add("")
    add(
        "Full rendered text for every document, clean and seeded, is written to "
        "`documents/`. A seeded file and its clean parent differ by exactly the "
        "mutation named above, so any diff tool shows the planted issue directly."
    )
    return "\n".join(lines) + "\n"


def write_corpus_artifacts(root: Optional[Path] = None) -> dict[str, Path]:
    """Write the manifest (JSON + markdown) and every document's text."""
    root = root or ARTIFACT_ROOT
    docs_dir = root / "documents"
    docs_dir.mkdir(parents=True, exist_ok=True)

    manifest = build_manifest()
    written: dict[str, Path] = {}

    manifest_json = root / "case_manifest.json"
    manifest_json.write_text(json.dumps(manifest, indent=2, sort_keys=False), encoding="utf-8")
    written["case_manifest.json"] = manifest_json

    manifest_md = root / "case_manifest.md"
    manifest_md.write_text(render_manifest_markdown(manifest), encoding="utf-8")
    written["case_manifest.md"] = manifest_md

    for spec in CLEAN_DOCUMENTS:
        path = docs_dir / f"{spec.doc_id}__clean.txt"
        path.write_text(spec.render_ocr_text(), encoding="utf-8")
        written[path.name] = path
    for case in build_seeded_cases():
        path = docs_dir / f"{case.case_id}.txt"
        path.write_text(case.ocr_text, encoding="utf-8")
        written[path.name] = path

    return written


# ---------------------------------------------------------------------------
# Run artifacts
# ---------------------------------------------------------------------------


def summarise(result: BenchmarkResult) -> dict[str, Any]:
    """The scored summary of one run. No I/O — the tests assert on this."""
    matrix = build_confusion(result.clean_outcomes, result.seeded_outcomes)
    correct = sum(o.field_correct for o in result.clean_outcomes)
    total = sum(o.field_total for o in result.clean_outcomes)
    collateral = sorted(
        {t for o in result.seeded_outcomes for t in getattr(o, "collateral", [])}
    )
    return {
        "mode": result.mode,
        "clean_documents": len(result.clean_outcomes),
        "seeded_cases": len(result.seeded_outcomes),
        "confusion_matrix": matrix.as_dict(),
        "recall_by_alert_type": recall_by_alert_type(result.seeded_outcomes),
        "field_accuracy": {
            "correct": correct,
            "total": total,
            "ratio": (correct / total) if total else None,
            "note": (
                "Only measured in live mode; verify mode is handed the extraction "
                "it would be grading, so a figure there would measure nothing."
            ),
        },
        "false_positive_documents": [
            {"case_id": o.case_id, "alerts": o.fired}
            for o in result.clean_outcomes
            if o.false_positive
        ],
        "missed_cases": [
            {"case_id": o.case_id, "expected": o.expected_alert_type, "fired": o.fired}
            for o in result.seeded_outcomes
            if not o.not_applicable and not o.hit
        ],
        "collateral_alert_types": collateral,
        "errors": [
            {"case_id": r.case_id, "error": r.error}
            for r in (result.clean_runs + result.seeded_runs)
            if r.error
        ],
    }


def render_run_markdown(summary: dict[str, Any], result: BenchmarkResult) -> str:
    lines: list[str] = []
    add = lines.append
    matrix = summary["confusion_matrix"]
    pct = lambda v: "n/a" if v is None else f"{v:.1%}"  # noqa: E731

    add(f"# Extraction benchmark run — `{summary['mode']}` mode")
    add("")
    add("**Generated file. Do not edit.**")
    add("")
    add(f"Run at: `{datetime.now(timezone.utc).isoformat(timespec='seconds')}`")
    add("")
    add(
        f"{summary['clean_documents']} clean documents, "
        f"{summary['seeded_cases']} seeded cases."
    )
    add("")
    add("## Confusion matrix (unit: one document)")
    add("")
    add("| | Alert fired | Stayed silent |")
    add("|---|---|---|")
    add(f"| **Seeded (issue planted)** | {matrix['true_positive']} (TP) | {matrix['false_negative']} (FN) |")
    add(f"| **Clean (no issue)** | {matrix['false_positive']} (FP) | {matrix['true_negative']} (TN) |")
    add("")
    add(f"- **Alert recall** (the number production usage cannot give): {pct(matrix['recall'])}")
    add(f"- **False-positive rate on clean documents**: {pct(matrix['false_positive_rate'])}")
    add(f"- **Document-level precision**: {pct(matrix['document_level_precision'])}")
    if matrix["not_applicable"]:
        add(
            f"- **Not applicable in this mode**: {matrix['not_applicable']} "
            "extraction-surface cases, excluded from the recall denominator "
            "(see `case_manifest.md`, 'Seeded cases')."
        )
    add("")
    add("## Recall per check")
    add("")
    add("| Alert type | Seeded | Detected | Recall | Missed |")
    add("|---|---|---|---|---|")
    for alert_type, bucket in sorted(summary["recall_by_alert_type"].items()):
        missed = ", ".join(f"`{c}`" for c in bucket["missed_cases"]) or "—"
        add(
            f"| `{alert_type}` | {bucket['seeded']} | {bucket['detected']} | "
            f"{pct(bucket['recall'])} | {missed} |"
        )
    add("")
    fa = summary["field_accuracy"]
    add("## Field-level accuracy (clean documents)")
    add("")
    if fa["total"]:
        add(f"**{fa['correct']}/{fa['total']} fields correct = {pct(fa['ratio'])}**")
        add("")
        add("| Document | Correct | Total | Wrong fields |")
        add("|---|---|---|---|")
        for outcome in result.clean_outcomes:
            wrong = [c.field_name for c in outcome.comparisons if not c.correct]
            add(
                f"| `{outcome.case_id}` | {outcome.field_correct} | {outcome.field_total} | "
                + (", ".join(f"`{w}`" for w in wrong) or "—")
                + " |"
            )
        add("")
        add("### Every field the extraction got wrong")
        add("")
        add("| Document | Field | Expected | Extracted |")
        add("|---|---|---|---|")
        any_wrong = False
        for outcome in result.clean_outcomes:
            for c in outcome.comparisons:
                if not c.correct:
                    any_wrong = True
                    add(
                        f"| `{outcome.case_id}` | `{c.field_name}` | "
                        f"{_fmt(c.expected)} | {_fmt(c.actual)} |"
                    )
        if not any_wrong:
            add("| — | — | — | — |")
    else:
        add(f"Not measured. {fa['note']}")
    add("")
    if summary["false_positive_documents"]:
        add("## False positives on clean documents")
        add("")
        for entry in summary["false_positive_documents"]:
            add(f"- `{entry['case_id']}` fired: " + ", ".join(f"`{t}`" for t in entry["alerts"]))
        add("")
    if summary["missed_cases"]:
        add("## Missed seeded issues (false negatives)")
        add("")
        for entry in summary["missed_cases"]:
            fired = ", ".join(f"`{t}`" for t in entry["fired"]) or "nothing"
            add(f"- `{entry['case_id']}` expected `{entry['expected']}`, fired {fired}")
        add("")
    if summary["collateral_alert_types"]:
        add("## Collateral alert types")
        add("")
        add(
            "Fired on a seeded case but neither the expected type nor a declared "
            "tolerated side effect. Not counted against recall — the planted "
            "issue was still caught — but the same miscalibration signal as a "
            "clean-set false positive."
        )
        add("")
        for t in summary["collateral_alert_types"]:
            add(f"- `{t}`")
        add("")
    if summary["errors"]:
        add("## Errors")
        add("")
        for entry in summary["errors"]:
            add(f"- `{entry['case_id']}`: {entry['error']}")
        add("")
    add("## Per-case detail")
    add("")
    add("| Case | Kind | Status | Alerts fired | Latency (ms) |")
    add("|---|---|---|---|---|")
    for run in result.clean_runs + result.seeded_runs:
        fired = ", ".join(f"`{t}`" for t in run.fired_types) or "—"
        add(f"| `{run.case_id}` | {run.kind} | {run.status} | {fired} | {run.latency_ms:,.1f} |")
    return "\n".join(lines) + "\n"


def write_run_artifacts(result: BenchmarkResult, root: Optional[Path] = None) -> dict[str, Path]:
    root = root or ARTIFACT_ROOT
    runs_dir = root / "runs"
    runs_dir.mkdir(parents=True, exist_ok=True)

    summary = summarise(result)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    written: dict[str, Path] = {}

    raw = runs_dir / f"{result.mode}-{stamp}.json"
    raw.write_text(
        json.dumps({"summary": summary, "detail": result.to_dict()}, indent=2, default=str),
        encoding="utf-8",
    )
    written[raw.name] = raw

    latest = runs_dir / f"{result.mode}-latest.md"
    latest.write_text(render_run_markdown(summary, result), encoding="utf-8")
    written[latest.name] = latest
    return written


__all__ = [
    "ARTIFACT_ROOT",
    "build_manifest",
    "render_manifest_markdown",
    "render_run_markdown",
    "summarise",
    "write_corpus_artifacts",
    "write_run_artifacts",
]
