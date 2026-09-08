"""Gap 466 — the model benchmark matrix (founder's STEP 3, 2026-09-05).

For each model, runs the five tasks and writes one JSON per (model, task) plus a
`summary.md` matrix into `docs/extraction_benchmark/runs/matrix-<date>/`:

  a. extraction   tests/run_extraction_harness.py --deployment <m>   (27 PDFs; needs backend on :8000)
  b. doctype      scripts/run_doctype_matrix.py --deployment <m>     (24 fixtures, pypdf text)
  c. sql          scripts/run_agent_eval.py --model <m>              (SQL-route cases of the golden sample)
  d. chat         same run as (c), scored by the fixed judge         (all cases; judge = configured judge role)
  e. judge        scripts/rescore_agent_eval.py --judge-deployment <m> over the BASELINE's (c/d) answers

Same prompts, same api-version (settings), same seeds; each task runs once per
model. A failed subprocess is recorded in the summary and the matrix continues.

    uv run --with openpyxl python scripts/run_model_matrix.py \
        --models gpt-5-mini,gpt-5.6-luna,gpt-5.6-terra,gpt-5.6-sol,gpt-6-astra

    # smoke: one invoice, one model, tasks a+b only
    uv run --with openpyxl python scripts/run_model_matrix.py --models gpt-5.6-luna --tasks a,b --ids US-IN-01
"""
from __future__ import annotations

import argparse
import json
import os
import statistics
import subprocess
import sys
import time
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
BE = os.path.dirname(HERE)
sys.path.insert(0, BE)

from config import get_settings  # noqa: E402
from utils.model_registry import cost_usd, registry_snapshot  # noqa: E402

PY = [sys.executable]


def _run(cmd: list[str], log_path: str, timeout: int) -> tuple[int, float]:
    t0 = time.perf_counter()
    with open(log_path, "w", encoding="utf-8") as log:
        log.write("$ " + " ".join(cmd) + "\n\n")
        log.flush()
        try:
            rc = subprocess.run(cmd, cwd=BE, stdout=log, stderr=subprocess.STDOUT, timeout=timeout).returncode
        except subprocess.TimeoutExpired:
            log.write(f"\n[timeout after {timeout}s]\n")
            rc = -9
    return rc, round(time.perf_counter() - t0, 1)


def _load(path: str):
    try:
        return json.load(open(path, encoding="utf-8"))
    except Exception:
        return None


def _pct(xs, q):
    xs = [x for x in xs if isinstance(x, (int, float))]
    if not xs:
        return None
    ys = sorted(xs)
    return round(ys[max(0, min(len(ys) - 1, int(round(q * (len(ys) - 1)))))], 3)


def _mean(xs):
    xs = [x for x in xs if isinstance(x, (int, float))]
    return round(statistics.mean(xs), 3) if xs else None


def digest_extraction(d: dict | None) -> dict | None:
    if not d:
        return None
    li = d.get("line_items") or {}
    calls = d.get("llm_calls") or 0
    cost = d.get("cost_usd")
    return {
        "metric": d.get("field_accuracy_pct"),
        "metric_name": "field accuracy %",
        "invoice_accuracy_pct": d.get("invoice_accuracy_pct"),
        "line_p": li.get("precision_pct"),
        "line_r": li.get("recall_pct"),
        "line_f1": li.get("f1_pct"),
        "per_field": {k: v.get("accuracy_pct") for k, v in (d.get("per_field") or {}).items()},
        "errors": d.get("errors"),
        "cost_usd": cost,
        "cost_per_invoice": d.get("cost_per_invoice_usd"),
        "cost_per_1k_calls": round(cost / calls * 1000, 3) if (cost is not None and calls) else None,
        "p95": (d.get("latency_s") or {}).get("p95"),
        "calls": calls,
        "tokens": [d.get("tokens_in"), d.get("tokens_out")],
    }


def digest_doctype(d: dict | None) -> dict | None:
    if not d:
        return None
    return {
        "metric": d.get("accuracy_pct"),
        "metric_name": "doc-type accuracy %",
        "errors": d.get("errors"),
        "cost_usd": d.get("cost_usd"),
        "cost_per_1k_calls": d.get("cost_per_1k_calls_usd"),
        "p95": (d.get("latency_s") or {}).get("p95"),
        "calls": d.get("llm_calls"),
        "tokens": [d.get("tokens_in"), d.get("tokens_out")],
    }


def digest_eval(d: dict | None, model: str) -> tuple[dict | None, dict | None]:
    """(c) SQL exec-correctness + repair attempts over SQL-route turns; (d) judge score over all turns."""
    if not d:
        return None, None
    turns = [t for t in (d.get("turns") or []) if not t.get("error")]
    errors = len((d.get("turns") or [])) - len(turns)
    tin = sum(int(t.get("tokens_in") or 0) for t in turns)
    tout = sum(int(t.get("tokens_out") or 0) for t in turns)
    cost = cost_usd(model, tin, tout)
    calls = sum(int(t.get("llm_call_count") or 0) for t in turns)

    # Gap 484: the denominator is the SQL-ROUTE CASE SET, not "the turns that came
    # back with SQL". A turn that timed out, crashed or never emitted a statement is
    # a turn the SQL route got wrong, and dropping it reports the highest score on
    # the worst run. `all_turns` is used deliberately -- `turns` above has already
    # filtered errors out for the cost/latency figures, where excluding them is
    # right, and for correctness it is not.
    #
    # A case is SQL-gradeable when it declares an expected retrieval set. `()` is a
    # real expectation ("fetch nothing"); `None` means the case declares none and
    # the turn stays unscored rather than being guessed at.
    all_turns = list(d.get("turns") or [])
    sql_turns = [t for t in all_turns if t.get("generated_sql")]
    gradeable = [t for t in all_turns if t.get("expected_invoice_numbers") is not None]
    exec_ok = []
    for t in gradeable:
        expected = set(t.get("expected_invoice_numbers") or [])
        fetched = set(t.get("fetched_invoice_numbers") or [])
        # An errored turn fetched nothing, so it scores 0 here without a special
        # case -- which is the point: timeout = wrong, by construction.
        exec_ok.append(1.0 if expected <= fetched else 0.0)
    attempts = []
    for t in sql_turns:
        gen_events = [e for e in (t.get("llm_events") or []) if "sql" in str(e.get("agent_name", e)).lower() and "summary" not in str(e.get("agent_name", e)).lower()]
        attempts.append(len(gen_events) if gen_events else 1)
    sql_errors = sum(1 for t in gradeable if t.get("error"))
    sql_no_statement = sum(1 for t in gradeable if not t.get("generated_sql"))
    sql_p95 = _pct([t.get("latency_ms", 0) / 1000.0 for t in sql_turns], 0.95)
    sql_tin = sum(int(t.get("tokens_in") or 0) for t in sql_turns)
    sql_tout = sum(int(t.get("tokens_out") or 0) for t in sql_turns)
    sql_calls = sum(int(t.get("llm_call_count") or 0) for t in sql_turns) or None
    sql_cost = cost_usd(model, sql_tin, sql_tout)
    c = {
        "metric": round(100.0 * statistics.mean(exec_ok), 1) if exec_ok else None,
        "metric_name": "SQL exec-correct %",
        # Gap 484: `n` is the fixed denominator the percentage is over, and it is
        # reported next to the percentage so a number can never again be quoted
        # without the base it was computed on.
        "n": len(exec_ok),
        "sql_pass_pct": round(100.0 * statistics.mean(exec_ok), 1) if exec_ok else None,
        "sql_turns": len(sql_turns),
        "scored": len(exec_ok),
        # How the denominator was spent, so a low score is attributable.
        "errored": sql_errors,
        "no_statement": sql_no_statement,
        "graded_by": "deterministic set comparison (expected <= fetched)",
        "mean_attempts": _mean(attempts),
        "cost_usd": round(sql_cost, 5),
        "cost_per_1k_calls": round(sql_cost / sql_calls * 1000, 3) if sql_calls else None,
        "p95": sql_p95,
        "calls": sql_calls,
    }
    dd = {
        "metric": _mean([t.get("accuracy_score") for t in turns]),
        "metric_name": "judge accuracy (0-1)",
        "faithfulness": _mean([t.get("faithfulness_score") for t in turns]),
        "relevance": _mean([t.get("relevance_score") for t in turns]),
        "passed_pct": round(100.0 * sum(1 for t in turns if t.get("passed")) / len(turns), 1) if turns else None,
        "turns": len(turns),
        "errors": errors,
        "cost_usd": round(cost, 5),
        "cost_per_turn": round(cost / len(turns), 5) if turns else None,
        "cost_per_1k_calls": round(cost / calls * 1000, 3) if calls else None,
        "p95": _pct([t.get("latency_ms", 0) / 1000.0 for t in turns], 0.95),
        "calls": calls,
        "tokens": [tin, tout],
        "judge_mode": d.get("judge_mode"),
    }
    return c, dd


def digest_judge(d: dict | None) -> dict | None:
    if not d:
        return None
    acc = (d.get("per_metric") or {}).get("accuracy_score") or {}
    return {
        "metric": acc.get("mean_abs_delta"),
        "metric_name": "mean |Δ accuracy| vs current judge (lower = more stable)",
        "rescored_accuracy_mean": acc.get("rescored_mean"),
        "original_accuracy_mean": acc.get("original_mean"),
        "pass_flip_pct": d.get("pass_flip_pct"),
        "turns": d.get("turns_rescored"),
        "cost_usd": d.get("cost_usd"),
        "cost_per_1k_calls": d.get("cost_per_1k_calls_usd"),
        "p95": None,
        "calls": d.get("judge_llm_calls"),
    }


def _cell(x: dict | None) -> str:
    if x is None:
        return "—"
    m = x.get("metric")
    c = x.get("cost_per_1k_calls")
    p = x.get("p95")
    return f"{m if m is not None else '—'} | ${c if c is not None else '—'}/1k | p95 {p if p is not None else '—'}s"


def write_summary(out_dir: str, models: list[str], results: dict, runs: list[dict], baseline: str) -> str:
    tasks = [("a", "extraction", "field accuracy %"), ("b", "doctype", "accuracy %"), ("c", "sql", "exec-correct %"),
             ("d", "chat", "judge accuracy 0-1"), ("e", "judge", "mean |Δ acc| vs current judge")]
    lines = [f"# Model matrix — {os.path.basename(out_dir)}", "",
             f"Generated {datetime.now(timezone.utc).isoformat()}. Baseline `{baseline}`. api-version `{get_settings().AZURE_OPENAI_API_VERSION}`. "
             "Cells: primary metric | USD per 1k LLM calls (registry list price) | p95 latency. Same prompts, one run each.", "",
             "| task | " + " | ".join(models) + " |", "|---|" + "---|" * len(models)]
    for key, name, mname in tasks:
        lines.append(f"| ({key}) {name} — {mname} | " + " | ".join(_cell(results.get(m, {}).get(name)) for m in models) + " |")
    lines += ["", "## Extraction detail", "", "| model | invoice acc % | field acc % | line P % | line R % | line F1 % | errors | $/invoice | p95 s |", "|---|---|---|---|---|---|---|---|---|"]
    for m in models:
        x = results.get(m, {}).get("extraction")
        if x:
            lines.append(f"| {m} | {x['invoice_accuracy_pct']} | {x['metric']} | {x['line_p']} | {x['line_r']} | {x['line_f1']} | {x['errors']} | {x['cost_per_invoice']} | {x['p95']} |")
    lines += ["", "### Per-field accuracy % (fields < 80 on every model are OCR/prompt problems, not model problems)", ""]
    fields = sorted({f for m in models for f in ((results.get(m, {}).get("extraction") or {}).get("per_field") or {})})
    if fields:
        lines += ["| field | " + " | ".join(models) + " |", "|---|" + "---|" * len(models)]
        for f in fields:
            vals = [((results.get(m, {}).get("extraction") or {}).get("per_field") or {}).get(f) for m in models]
            flag = " ⚠ all <80" if vals and all(v is not None and v < 80 for v in vals) else ""
            lines.append(f"| {f}{flag} | " + " | ".join(str(v) for v in vals) + " |")
    lines += ["", "## Chat / SQL detail", "", "| model | SQL turns | exec-correct % | mean attempts | judge acc | faithfulness | relevance | passed % | $/turn | p95 s |", "|---|---|---|---|---|---|---|---|---|---|"]
    for m in models:
        c = results.get(m, {}).get("sql") or {}
        dd = results.get(m, {}).get("chat") or {}
        if c or dd:
            lines.append(f"| {m} | {c.get('sql_turns')} | {c.get('metric')} | {c.get('mean_attempts')} | {dd.get('metric')} | {dd.get('faithfulness')} | {dd.get('relevance')} | {dd.get('passed_pct')} | {dd.get('cost_per_turn')} | {dd.get('p95')} |")
    lines += ["", "## Judge stability (re-grading the baseline's answers)", "", "| judge | mean |Δ acc| | rescored acc mean | original acc mean | pass flips % | $/1k calls |", "|---|---|---|---|---|---|"]
    for m in models:
        j = results.get(m, {}).get("judge")
        if j:
            lines.append(f"| {m} | {j['metric']} | {j['rescored_accuracy_mean']} | {j['original_accuracy_mean']} | {j['pass_flip_pct']} | {j['cost_per_1k_calls']} |")
    lines += ["", "## Runs", "", "| model | task | rc | wall s | log |", "|---|---|---|---|---|"]
    for r in runs:
        lines.append(f"| {r['model']} | {r['task']} | {r['rc']} | {r['wall_s']} | {r['log']} |")
    lines += ["", "## Registry in force", "", "```json", json.dumps(registry_snapshot(), indent=2, default=str), "```", ""]
    path = os.path.join(out_dir, "summary.md")
    open(path, "w", encoding="utf-8").write("\n".join(lines))
    return path


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--models", default="gpt-5-mini,gpt-5.6-luna,gpt-5.6-terra,gpt-5.6-sol,gpt-6-astra")
    ap.add_argument("--baseline", default="gpt-5-mini")
    ap.add_argument("--tasks", default="a,b,c,d,e")
    ap.add_argument("--out-dir", default=None)
    ap.add_argument("--ids", default=None, help="passed to the extraction harness (smoke)")
    ap.add_argument("--cases", default=None, help="passed to run_agent_eval (smoke)")
    ap.add_argument("--judge", default="separate", choices=["separate", "combined"])
    ap.add_argument("--timeout", type=int, default=3600)
    args = ap.parse_args(argv)

    models = [m.strip() for m in args.models.split(",") if m.strip()]
    tasks = {t.strip() for t in args.tasks.split(",")}
    out_dir = args.out_dir or os.path.join(BE, "docs", "extraction_benchmark", "runs", "matrix-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"))
    os.makedirs(out_dir, exist_ok=True)
    api_version = get_settings().AZURE_OPENAI_API_VERSION
    print(f"Matrix -> {out_dir}\nmodels={models} tasks={sorted(tasks)} api={api_version}")

    results: dict[str, dict] = {m: {} for m in models}
    runs: list[dict] = []
    eval_out: dict[str, str] = {}

    # Cells already in out_dir (from an earlier or concurrent invocation sharing
    # the directory) are digested first, so summary.md always reflects every
    # file present, not only the tasks this process ran.
    def _preload():
        for m in models:
            ex = os.path.join(out_dir, f"{m}__extraction.json")
            if os.path.exists(ex):
                results[m]["extraction"] = digest_extraction(_load(ex))
            dt = os.path.join(out_dir, f"{m}__doctype.json")
            if os.path.exists(dt):
                results[m]["doctype"] = digest_doctype(_load(dt))
            ch = os.path.join(out_dir, f"{m}__chat.json")
            if os.path.exists(ch):
                eval_out[m] = ch
                results[m]["sql"], results[m]["chat"] = digest_eval(_load(ch), m)
            jd = os.path.join(out_dir, f"{m}__judge.json")
            if os.path.exists(jd):
                results[m]["judge"] = digest_judge(_load(jd))
    _preload()

    def record(model, task, rc, wall, log):
        runs.append({"model": model, "task": task, "rc": rc, "wall_s": wall, "log": os.path.basename(log)})
        print(f"  [{model}] {task}: rc={rc} ({wall}s)")

    for m in models:
        print(f"\n=== {m} ===")
        if "a" in tasks:
            out = os.path.join(out_dir, f"{m}__extraction.json")
            log = os.path.join(out_dir, f"{m}__extraction.log")
            cmd = PY + [os.path.join(BE, "tests", "run_extraction_harness.py"), "--deployment", m, "--label", m, "--scores-out", out]
            if args.ids:
                cmd += ["--ids", args.ids]
            rc, wall = _run(cmd, log, args.timeout)
            record(m, "extraction", rc, wall, log)
            results[m]["extraction"] = digest_extraction(_load(out))
        if "b" in tasks:
            out = os.path.join(out_dir, f"{m}__doctype.json")
            log = os.path.join(out_dir, f"{m}__doctype.log")
            rc, wall = _run(PY + [os.path.join(HERE, "run_doctype_matrix.py"), "--deployment", m, "--out", out], log, args.timeout)
            record(m, "doctype", rc, wall, log)
            results[m]["doctype"] = digest_doctype(_load(out))
        if "c" in tasks or "d" in tasks:
            out = os.path.join(out_dir, f"{m}__chat.json")
            log = os.path.join(out_dir, f"{m}__chat.log")
            cmd = PY + [os.path.join(HERE, "run_agent_eval.py"), "--paths", "default", "--provider", "azure", "--model", m,
                        "--api-version", api_version, "--judge", args.judge, "--no-persist", "--no-mirror", "--no-multi-turn", "--out", out]
            if args.cases:
                cmd += ["--cases", args.cases]
            rc, wall = _run(cmd, log, args.timeout)
            record(m, "chat+sql", rc, wall, log)
            eval_out[m] = out
            c, dd = digest_eval(_load(out), m)
            results[m]["sql"], results[m]["chat"] = c, dd

    if "e" in tasks:
        base_run = eval_out.get(args.baseline) or os.path.join(out_dir, f"{args.baseline}__chat.json")
        if os.path.exists(base_run):
            for m in models:
                out = os.path.join(out_dir, f"{m}__judge.json")
                log = os.path.join(out_dir, f"{m}__judge.log")
                rc, wall = _run(PY + [os.path.join(HERE, "rescore_agent_eval.py"), "--run", base_run, "--judge-deployment", m, "--judge", args.judge, "--out", out], log, args.timeout)
                record(m, "judge", rc, wall, log)
                results[m]["judge"] = digest_judge(_load(out))
        else:
            print(f"(e) skipped: no baseline chat run at {base_run}")

    _preload()  # pick up cells other concurrent invocations finished meanwhile
    json.dump({"models": models, "baseline": args.baseline, "api_version": api_version, "results": results, "runs": runs,
               "registry": registry_snapshot()}, open(os.path.join(out_dir, "matrix.json"), "w", encoding="utf-8"), indent=2, default=str)
    path = write_summary(out_dir, models, results, runs, args.baseline)
    print(f"\nWrote {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
