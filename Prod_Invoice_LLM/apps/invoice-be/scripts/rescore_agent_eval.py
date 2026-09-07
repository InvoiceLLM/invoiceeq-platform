"""Gap 466 matrix, task (e): judge stability.

Re-grades the *answers already recorded* in a `run_agent_eval.py` output file
with a different judge deployment, so the only thing that changes between two
score sets is the judge. Answers are not regenerated — regenerating them would
mix model variance into what is meant to be judge variance.

    uv run python scripts/rescore_agent_eval.py --run runs/x/gpt-5-mini__chat.json \
        --judge-deployment gpt-5.6-luna --out runs/x/luna__judge.json

Reports per-metric means under the new judge next to the means recorded in the
run file, and the mean absolute per-turn delta.
"""
from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import get_settings  # noqa: E402
from utils.llm import build_llm  # noqa: E402
from utils.model_registry import cost_usd  # noqa: E402

METRICS = ("faithfulness_score", "relevance_score", "accuracy_score", "context_score", "persona_score")


def _mean(xs):
    xs = [x for x in xs if isinstance(x, (int, float))]
    return round(statistics.mean(xs), 3) if xs else None


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", required=True, help="run_agent_eval.py output JSON")
    ap.add_argument("--judge-deployment", required=True)
    ap.add_argument("--judge", default="separate", choices=["separate", "combined"])
    ap.add_argument("--out", default=None)
    args = ap.parse_args(argv)

    payload = json.load(open(args.run, encoding="utf-8"))
    turns = payload.get("turns") or []

    # Import after sys.path so the harness module's own path setup runs.
    from scripts.run_agent_eval import score_turn  # noqa: E402
    from benchmarks.agent_eval_golden_sample import CASES  # noqa: E402

    case_by_id = {c.case_id: c for c in CASES}
    try:
        from benchmarks.agent_eval_multiturn import all_cases as _mt_cases  # type: ignore

        for c in _mt_cases():
            case_by_id.setdefault(c.case_id, c)
    except Exception:
        pass

    settings = get_settings()
    judge = build_llm("azure", model=args.judge_deployment, api_version=settings.AZURE_OPENAI_API_VERSION, allow_mock_fallback=False)
    print(f"Judge: {args.judge_deployment}; {len(turns)} turns from {os.path.basename(args.run)} (model_under_test={payload.get('model_under_test')})")

    import logging

    events: list[dict] = []

    class _Cap(logging.Handler):
        def emit(self, record):
            if record.getMessage() == "llm_agent_call":
                events.append(dict(getattr(record, "extra_fields", None) or {}))

    for name in ("invoice_be_telemetry", "invoice_worker_telemetry"):
        lg = logging.getLogger(name)
        lg.addHandler(_Cap(level=logging.INFO))
        if lg.level == logging.NOTSET or lg.level > logging.INFO:
            lg.setLevel(logging.INFO)

    rescored = []
    skipped = 0
    for t in turns:
        case = case_by_id.get(t.get("case_id"))
        if case is None or t.get("error") or not t.get("answer_prose"):
            skipped += 1
            continue
        original = {m: t.get(m) for m in METRICS}
        fresh = dict(t)
        try:
            score_turn(fresh, case, judge, combined_judge=(args.judge == "combined"))
            err = None
        except Exception as e:
            err = f"{type(e).__name__}: {e}"
        rescored.append({
            "case_id": t.get("case_id"),
            "original": original,
            "rescored": {m: fresh.get(m) for m in METRICS},
            "original_passed": t.get("passed"),
            "rescored_passed": fresh.get("passed"),
            # Gap 479: the judge's own reasons travel with the re-score, so a
            # verdict that moved can be read rather than guessed at.
            "rescored_notes": fresh.get("score_notes"),
            "error": err,
        })
        print(f"  {t.get('case_id'):<40} acc {original.get('accuracy_score')} -> {fresh.get('accuracy_score')}")

    per_metric = {}
    for m in METRICS:
        orig = [r["original"][m] for r in rescored]
        new = [r["rescored"][m] for r in rescored]
        deltas = [abs(a - b) for a, b in zip(orig, new) if isinstance(a, (int, float)) and isinstance(b, (int, float))]
        per_metric[m] = {"original_mean": _mean(orig), "rescored_mean": _mean(new), "mean_abs_delta": _mean(deltas), "n": len(deltas)}
    pass_flips = sum(1 for r in rescored if r["original_passed"] is not None and r["rescored_passed"] is not None and r["original_passed"] != r["rescored_passed"])
    tin = sum(int(e.get("tokens_in") or 0) for e in events)
    tout = sum(int(e.get("tokens_out") or 0) for e in events)
    cost = cost_usd(args.judge_deployment, tin, tout)
    summary = {
        "task": "judge",
        "judge_deployment": args.judge_deployment,
        "judge_mode": args.judge,
        "source_run": os.path.basename(args.run),
        "source_model_under_test": payload.get("model_under_test"),
        "run_at": datetime.now(timezone.utc).isoformat(),
        "turns_rescored": len(rescored),
        "turns_skipped": skipped,
        "per_metric": per_metric,
        "pass_flips": pass_flips,
        "pass_flip_pct": round(100.0 * pass_flips / len(rescored), 1) if rescored else None,
        "judge_llm_calls": len(events),
        "tokens_in": tin,
        "tokens_out": tout,
        "cost_usd": round(cost, 5),
        "cost_per_1k_calls_usd": round(cost / len(events) * 1000, 3) if events else None,
        "turns": rescored,
    }
    acc = per_metric["accuracy_score"]
    print(f"[judge {args.judge_deployment}] accuracy mean {acc['original_mean']} -> {acc['rescored_mean']} | mean|delta| {acc['mean_abs_delta']} | pass flips {pass_flips}/{len(rescored)} | cost {summary['cost_usd']} USD")
    if args.out:
        os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
        json.dump(summary, open(args.out, "w", encoding="utf-8"), indent=2, default=str)
        print(f"Wrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
