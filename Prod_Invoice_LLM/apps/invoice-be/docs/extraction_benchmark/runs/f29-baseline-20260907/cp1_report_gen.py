# -*- coding: utf-8 -*-
"""CP1 report: read the baseline golden run, compute pass %, kappa, the SQL metric on
its FIXED denominator (Gap 484) and the taxonomy, and write a markdown report next to
the run. No model is called -- every number here is derived from the stored run."""
import json
import sys
from pathlib import Path

sys.path.insert(0, ".")
from scripts.run_agent_eval import cohens_kappa  # noqa: E402
from scripts.run_model_matrix import digest_eval  # noqa: E402

RUN = Path("docs/extraction_benchmark/runs/f29-baseline-20260907")
OUT = RUN / "agent_eval_output.json"

run = json.loads(OUT.read_text(encoding="utf-8"))
turns = run["turns"]
summary = run["summary"]["default"]

# --- kappa against the human reference verdicts -----------------------------
cal = json.loads(Path("tests/golden_calibration.json").read_text(encoding="utf-8"))
human = {e["case_id"]: bool(e["human_verdict"]) for e in cal["entries"]}
by_id = {t["case_id"]: t for t in turns}
pairs, ids = [], []
for cid, h in human.items():
    t = by_id.get(cid)
    if t is None:
        continue
    pairs.append((bool(t.get("passed")), h))
    ids.append(cid)
k = cohens_kappa(pairs) if pairs else {"kappa": None, "agreement": None}

# --- SQL metric on the fixed denominator ------------------------------------
sql, chat = digest_eval(run, "gpt-5.6-luna")

# --- capability flags + routes ---------------------------------------------
flags = sorted({f for t in turns for f in (t.get("capability_flags") or [])})
routes = {}
for t in turns:
    routes[t.get("route") or "(none)"] = routes.get(t.get("route") or "(none)", 0) + 1

lines = []
a = lines.append
a("# CP1 — Feature 29 phase-2 baseline (live)")
a("")
a(f"Run: `{OUT.as_posix()}`  ")
a(f"Recorded: {run.get('run_at')}  ")
a(f"Model under test: **gpt-5.6-luna** (the app's configured deployment; "
  f"`model_under_test` is `{run.get('model_under_test')}`, meaning \"the application's own\").  ")
a(f"Judge: gpt-5-mini, mode `{run.get('judge_mode')}`.  ")
a(f"Phase-2 capability flags active: **{', '.join(flags) if flags else 'none — all five off, as CP1 requires'}**.")
a("")
a("## Headline")
a("")
a("| metric | value | n |")
a("|---|---|---|")
a(f"| golden pass % | **{summary['pass_rate'] * 100:.1f}%** | {summary['turns']} |")
a(f"| judge accuracy (mean) | {summary['accuracy_mean']} | {summary['turns']} |")
a(f"| faithfulness (mean) | {summary['faithfulness_mean']} | {summary['turns']} |")
a(f"| relevance (mean) | {summary['relevance_mean']} | {summary['turns']} |")
a(f"| errors | {summary['errors']} | {summary['turns']} |")
a(f"| Cohen's κ vs human verdicts | **{k['kappa']}** (agreement {k['agreement']}) | {len(pairs)} |")
a(f"| SQL exec-correct % | **{sql['sql_pass_pct']}%** | {sql['n']} |")
a(f"| — of which errored | {sql['errored']} | |")
a(f"| — of which emitted no statement | {sql['no_statement']} | |")
a(f"| SQL graded by | {sql['graded_by']} | |")
a(f"| latency median / max (s) | {summary['latency_ms_median']/1000:.1f} / {summary['latency_ms_max']/1000:.1f} | |")
a(f"| cost per turn | ${chat['cost_per_turn'] if 'cost_per_turn' in chat else 'n/a'} | |")
a("")
a("## Failure taxonomy")
a("")
a("| bucket | count |")
a("|---|---|")
for bucket, count in run["failure_taxonomy"]["counts"].items():
    a(f"| `{bucket}` | {count} |")
a("")
a("## Routes taken")
a("")
a("| route | turns |")
a("|---|---|")
for route, count in sorted(routes.items(), key=lambda kv: -kv[1]):
    a(f"| `{route}` | {count} |")
a("")
a("## Judge vs human, case by case")
a("")
a("| case | human | judge | accuracy | faithfulness |")
a("|---|---|---|---|---|")
for cid in ids:
    t, h = by_id[cid], human[cid]
    j = bool(t.get("passed"))
    mark = "" if j == h else " **DISAGREE**"
    a(f"| `{cid}` | {'PASS' if h else 'FAIL'} | {'PASS' if j else 'FAIL'}{mark} | "
      f"{t.get('accuracy_score')} | {t.get('faithfulness_score')} |")
a("")

report = RUN / "cp1_report.md"
report.write_text("\n".join(lines) + "\n", encoding="utf-8")
print("\n".join(lines[:40]))
print(f"\nwrote {report}")
