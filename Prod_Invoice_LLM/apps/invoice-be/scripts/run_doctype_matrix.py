"""Gap 466 matrix, task (b): document-type classification accuracy of the LLM
fallback path, per candidate model.

Runs `services.document_type_classifier._classify_with_llm` — the Stage 2 call
the pipeline makes when the deterministic title-band pass is not enough — over
every PDF under `tests/fixtures/doc_types/<type>/<region>_inbound/`. The folder
name is the expected type. Text comes from pypdf, not Document Intelligence, so
every model sees byte-identical input and no OCR spend is added.

    uv run python scripts/run_doctype_matrix.py --deployment gpt-5.6-luna --out runs/x/luna__doctype.json

Same prompt for every model (`_build_classifier_prompt`), api-version from
settings (2024-10-21). One pass per fixture; a raised call is recorded as an
error, not retried.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import statistics
import sys
import time
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import get_settings  # noqa: E402
from utils.model_registry import cost_usd, resolve_model  # noqa: E402

FIXTURES = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tests", "fixtures", "doc_types")


class _Capture(logging.Handler):
    def __init__(self):
        super().__init__(level=logging.INFO)
        self.events: list[dict] = []

    def emit(self, record):
        if record.getMessage() == "llm_agent_call":
            self.events.append(dict(getattr(record, "extra_fields", None) or {}))


def _install() -> _Capture:
    cap = _Capture()
    for name in ("invoice_be_telemetry", "invoice_worker_telemetry"):
        lg = logging.getLogger(name)
        lg.addHandler(cap)
        if lg.level == logging.NOTSET or lg.level > logging.INFO:
            lg.setLevel(logging.INFO)
    return cap


def _pdf_text(path: str) -> str:
    import pypdf

    reader = pypdf.PdfReader(path)
    return "\n".join((p.extract_text() or "") for p in reader.pages).strip()


def _pct(xs, q):
    if not xs:
        return None
    ys = sorted(xs)
    return round(ys[max(0, min(len(ys) - 1, int(round(q * (len(ys) - 1)))))], 3)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--deployment", default=None)
    ap.add_argument("--out", default=None)
    args = ap.parse_args(argv)

    settings = get_settings()
    if args.deployment:
        settings.AZURE_OPENAI_DEPLOYMENT_NAME = args.deployment
        settings.AZURE_OPENAI_FAST_DEPLOYMENT_NAME = ""
    spec = resolve_model("primary")
    print(f"Classifier model: {spec.deployment} (api {spec.api_version})")

    from services.document_type_classifier import DOC_TYPES, _classify_with_llm

    cap = _install()
    cases = []
    for type_dir in sorted(os.listdir(FIXTURES)):
        tdir = os.path.join(FIXTURES, type_dir)
        if not os.path.isdir(tdir):
            continue
        for root, _dirs, files in os.walk(tdir):
            for f in sorted(files):
                if f.lower().endswith(".pdf"):
                    cases.append((type_dir, os.path.join(root, f)))
    print(f"{len(cases)} fixtures; vocabulary: {DOC_TYPES}")

    rows = []
    for expected_dir, path in cases:
        expected = expected_dir.upper()
        in_vocab = expected in DOC_TYPES
        text = _pdf_text(path)
        t0 = time.perf_counter()
        before = len(cap.events)
        try:
            res = _classify_with_llm(text, tenant_id="matrix")
            predicted = str(res.doc_type)
            confidence = getattr(res, "confidence", None)
            err = None
        except Exception as e:  # recorded, not retried
            predicted, confidence, err = None, None, f"{type(e).__name__}: {e}"
        latency = time.perf_counter() - t0
        ev = cap.events[before:]
        rows.append({
            "file": os.path.relpath(path, FIXTURES),
            "expected": expected,
            "expected_in_vocab": in_vocab,
            "predicted": predicted,
            "correct": bool(in_vocab and predicted == expected),
            "confidence": confidence,
            "latency_s": round(latency, 3),
            "tokens_in": sum(int(e.get("tokens_in") or 0) for e in ev),
            "tokens_out": sum(int(e.get("tokens_out") or 0) for e in ev),
            "error": err,
        })
        print(f"  {expected:<22} -> {predicted!s:<22} {'OK' if rows[-1]['correct'] else 'MISS'} ({latency:.1f}s)")

    scorable = [r for r in rows if r["expected_in_vocab"]]
    correct = sum(1 for r in scorable if r["correct"])
    tin = sum(r["tokens_in"] for r in rows)
    tout = sum(r["tokens_out"] for r in rows)
    lat = [r["latency_s"] for r in rows]
    cost = cost_usd(spec.deployment, tin, tout)
    summary = {
        "task": "doctype",
        "model": spec.deployment,
        "api_version": spec.api_version,
        "run_at": datetime.now(timezone.utc).isoformat(),
        "fixtures": len(rows),
        "scorable": len(scorable),
        "not_in_vocab": [r["expected"] for r in rows if not r["expected_in_vocab"]],
        "accuracy_pct": round(100.0 * correct / len(scorable), 1) if scorable else None,
        "errors": sum(1 for r in rows if r["error"]),
        "llm_calls": len(cap.events),
        "tokens_in": tin,
        "tokens_out": tout,
        "cost_usd": round(cost, 5),
        "cost_per_1k_calls_usd": round(cost / len(rows) * 1000, 3) if rows else None,
        "latency_s": {"p50": _pct(lat, 0.5), "p95": _pct(lat, 0.95), "mean": round(statistics.mean(lat), 3) if lat else None},
        "rows": rows,
    }
    print(f"[{spec.deployment}] doctype accuracy {summary['accuracy_pct']}% on {len(scorable)} | p95 {summary['latency_s']['p95']}s | cost {summary['cost_usd']} USD")
    if args.out:
        os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(summary, f, indent=2, default=str)
        print(f"Wrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
