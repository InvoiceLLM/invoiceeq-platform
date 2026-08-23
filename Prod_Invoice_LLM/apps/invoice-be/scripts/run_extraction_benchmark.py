"""Feature 23 Track 1 — run the extraction & alert benchmark.

Two modes, described in full in `tests/extraction_benchmark/harness.py`:

    # deterministic, free, no network. Alert recall + false-positive rate over
    # all 4 clean documents and all 13 seeded cases.
    uv run python scripts/run_extraction_benchmark.py --mode verify

    # real Azure OpenAI extraction end to end. Field-level accuracy, plus alert
    # behaviour on the 5 document-surface seeded cases. Costs real tokens.
    uv run python scripts/run_extraction_benchmark.py --mode live

    # regenerate the review corpus artifacts without running anything
    uv run python scripts/run_extraction_benchmark.py --artifacts-only

Artifacts land under `docs/extraction_benchmark/` — the corpus manifest is the
review record architect and a business analyst read before this set is trusted
as the real benchmark; `runs/<mode>-latest.md` is the most recent measurement.

Exit code is 1 if any seeded case in a gradeable surface was missed, if any
clean document raised an alert, or if any case errored — so this is usable as a
pre-deploy gate as-is, which is one of the two cadences the feature doc names.
`--no-gate` reports without failing, for a measurement-only run.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

_BE_ROOT = Path(__file__).resolve().parent.parent
if str(_BE_ROOT) not in sys.path:
    sys.path.insert(0, str(_BE_ROOT))

# Extraction itself needs no embeddings, but `config`/`chroma_client` are pulled
# in transitively by the agent module's imports and a real BAAI/bge-m3 load is a
# multi-GB download that has nothing to do with what is being measured.
os.environ.setdefault("MOCK_EMBEDDINGS", "true")

# Moved out of tests/extraction_benchmark/ to benchmarks/extraction/ on
# 2026-08-23 -- `.dockerignore` excludes `**/tests/` from the deployed image,
# which is why the deleted `caj-agent-eval-dev` job could never actually run
# (ModuleNotFoundError). See benchmarks/__init__.py.
from benchmarks.extraction.artifacts import (  # noqa: E402
    ARTIFACT_ROOT,
    summarise,
    write_corpus_artifacts,
    write_run_artifacts,
)
from benchmarks.extraction.harness import (  # noqa: E402
    MODE_LIVE,
    MODE_VERIFY,
    run_benchmark,
)

#: A stable synthetic tenant, used only for telemetry attribution on live runs
#: (`ExtractionState["tenant_id"]` — no node reads it for any extraction
#: decision). Fixed so a cost rollup can filter benchmark spend out of real
#: tenant spend.
BENCHMARK_TENANT_ID = "00000000-0000-0000-0000-0000000023b1"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--mode", choices=[MODE_VERIFY, MODE_LIVE], default=MODE_VERIFY)
    parser.add_argument("--cases", default=None, help="comma list of case ids (default: all)")
    parser.add_argument(
        "--artifacts-only",
        action="store_true",
        help="regenerate the corpus manifest/documents and exit without running anything",
    )
    parser.add_argument("--no-write", action="store_true", help="run but write no run artifact")
    parser.add_argument("--no-gate", action="store_true", help="always exit 0")
    parser.add_argument("--json", action="store_true", help="print the summary as JSON")
    parser.add_argument(
        "--tolerate-fp",
        default="",
        help=(
            "comma list of clean-document case ids allowed to false-positive without "
            "failing the gate. For a known, deliberately-not-fixed defect only -- e.g. "
            "Gap 293 (outbound_trade_discount__clean: OutboundInvoiceExtractionSchema has "
            "no discount_amount/discount_percent/round_off field, so verify_totals_math "
            "always mismatches a correct extraction of a discounted/rounded outbound "
            "invoice). The case stays IN the corpus either way -- see "
            "docs/feature_23_ai_control_tower.md, 'The defect the first run found' -- so "
            "the false-positive rate this run reports is unaffected; only the gate's "
            "pass/fail decision is. Any other clean-document false positive still fails."
        ),
    )
    args = parser.parse_args()
    tolerated_fp_ids = {c.strip() for c in args.tolerate_fp.split(",") if c.strip()}

    written = write_corpus_artifacts()
    print(f"Corpus artifacts written to {ARTIFACT_ROOT} ({len(written)} files)")
    if args.artifacts_only:
        return 0

    case_ids = {c.strip() for c in args.cases.split(",")} if args.cases else None

    def progress(run):
        fired = ",".join(run.fired_types) or "-"
        print(f"  [{run.kind:6}] {run.case_id:52} {str(run.status):16} {fired}")

    print(f"\nRunning in {args.mode!r} mode...")
    result = run_benchmark(
        mode=args.mode,
        case_ids=case_ids,
        tenant_id=BENCHMARK_TENANT_ID,
        on_progress=progress,
    )

    summary = summarise(result)
    if args.json:
        print(json.dumps(summary, indent=2, default=str))
    else:
        matrix = summary["confusion_matrix"]
        pct = lambda v: "n/a" if v is None else f"{v:.1%}"  # noqa: E731
        print("\n--- confusion matrix (unit: one document) ---")
        print(f"  TP {matrix['true_positive']}   FN {matrix['false_negative']}")
        print(f"  FP {matrix['false_positive']}   TN {matrix['true_negative']}")
        if matrix["not_applicable"]:
            print(f"  not applicable in this mode: {matrix['not_applicable']}")
        print(f"  alert recall .............. {pct(matrix['recall'])}")
        print(f"  clean false-positive rate . {pct(matrix['false_positive_rate'])}")
        print(f"  document-level precision .. {pct(matrix['document_level_precision'])}")
        fa = summary["field_accuracy"]
        if fa["total"]:
            print(f"  field accuracy ............ {fa['correct']}/{fa['total']} = {pct(fa['ratio'])}")
        for entry in summary["missed_cases"]:
            print(f"  MISSED {entry['case_id']}: expected {entry['expected']}, fired {entry['fired']}")
        for entry in summary["false_positive_documents"]:
            print(f"  FALSE POSITIVE {entry['case_id']}: {entry['alerts']}")
        for entry in summary["errors"]:
            print(f"  ERROR {entry['case_id']}: {entry['error']}")

    if not args.no_write:
        paths = write_run_artifacts(result)
        for name in paths:
            print(f"  wrote runs/{name}")

    if args.no_gate:
        return 0
    ungated_false_positives = [
        entry
        for entry in summary["false_positive_documents"]
        if entry["case_id"] not in tolerated_fp_ids
    ]
    if tolerated_fp_ids:
        tolerated_hit = [
            entry["case_id"]
            for entry in summary["false_positive_documents"]
            if entry["case_id"] in tolerated_fp_ids
        ]
        print(f"  (tolerated, not gating: {tolerated_hit or 'none fired this run'})")
    failed = bool(summary["missed_cases"] or ungated_false_positives or summary["errors"])
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
