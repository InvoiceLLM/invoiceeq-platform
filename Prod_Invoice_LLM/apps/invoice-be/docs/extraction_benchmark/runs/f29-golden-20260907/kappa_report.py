# -*- coding: utf-8 -*-
"""P0.1: kappa of the LIVE f29-golden-20260907 run (fixed judge, Gap 479) against the
human verdicts in tests/golden_calibration.json. Same method as kappa_479.py, but the
new judge verdicts come from a real run rather than an offline re-score."""
import json
import sys

sys.path.insert(0, ".")
from scripts.run_agent_eval import cohens_kappa  # noqa: E402

RUN = "docs/extraction_benchmark/runs/f29-golden-20260907/agent_eval_output.json"

cal = json.load(open("tests/golden_calibration.json", encoding="utf-8"))
human = {e["case_id"]: bool(e["human_verdict"]) for e in cal["entries"]}
old = {e["case_id"]: bool(e["judge_verdict"]) for e in cal["entries"]}

run = json.load(open(RUN, encoding="utf-8"))
new = {t["case_id"]: t for t in run["turns"]}

pairs_old, pairs_new, ids = [], [], []
print("| case | human | old judge | NEW judge | acc | faith | notes |")
print("|---|---|---|---|---|---|---|")
for cid, h in human.items():
    t = new.get(cid)
    if t is None:
        print(f"| {cid} | {'P' if h else 'F'} | - | MISSING FROM RUN | | | |")
        continue
    np_ = bool(t.get("passed"))
    ids.append(cid)
    pairs_old.append((old[cid], h))
    pairs_new.append((np_, h))
    flag = "" if np_ == h else " **DISAGREE**"
    notes = " / ".join(t.get("score_notes") or [])[:70].replace("|", "/")
    print(
        f"| {cid} | {'P' if h else 'F'} | {'P' if old[cid] else 'F'} | "
        f"{'P' if np_ else 'F'}{flag} | {t.get('accuracy_score')} | "
        f"{t.get('faithfulness_score')} | {notes} |"
    )

ko, kn = cohens_kappa(pairs_old), cohens_kappa(pairs_new)
n = len(pairs_new)
print()
print(f"n={n}  human PASS={sum(h for _, h in pairs_new)}  "
      f"old judge PASS={sum(a for a, _ in pairs_old)}  NEW judge PASS={sum(a for a, _ in pairs_new)}")
print(f"kappa OLD = {ko['kappa']}  agreement {ko['agreement']}")
print(f"kappa NEW = {kn['kappa']}  agreement {kn['agreement']}   "
      f"gate>=0.6: {'PASS' if (kn['kappa'] or 0) >= 0.6 else 'FAIL'}")

fn = [c for c, (a, h) in zip(ids, pairs_new) if h and not a]
fp = [c for c, (a, h) in zip(ids, pairs_new) if a and not h]
print("2x2 NEW: both_pass", sum(1 for a, h in pairs_new if a and h),
      " both_fail", sum(1 for a, h in pairs_new if not a and not h),
      " judge_pass_human_fail", len(fp), " human_pass_judge_fail", len(fn))
print("new judge false-fails :", fn)
print("new judge false-passes:", fp)

# --- run headline numbers (for the tracker / spec) ---
s = run["summary"]["default"]
print()
print(f"RUN pass_rate={s['pass_rate']}  accuracy_mean={s['accuracy_mean']}  "
      f"faithfulness_mean={s['faithfulness_mean']}  turns={s['turns']}  errors={s['errors']}")
print("taxonomy:", run["failure_taxonomy"]["counts"])

# --- the answer-contract abstain cases (tasklist 29.9 gate) ---
print()
print("ABSTAIN / answer-contract cases:")
for t in run["turns"]:
    ans = (t.get("answer_prose") or t.get("answer") or "")
    blocks = t.get("appended_blocks") or []
    if "abstain" in json.dumps(blocks).lower() or "can't confirm" in ans.lower() or "cannot confirm" in ans.lower():
        print(f"  {t['case_id']}: passed={t.get('passed')} acc={t.get('accuracy_score')} :: {ans[:110]!r}")
