"""Scores a directory of tests/gap237_sql_repro.py raw_turns_*.json files.

Same four counters the Gap 237 baseline was recorded with, applied
mechanically so the before/after numbers in README.md are reproducible rather
than eyeballed:

  correct     -- turn 2 ran a query and its answer names all three seeded USD
                 invoices (CNH-1001 vendor-only, ACM-2002 tags-only,
                 ZEN-3003 items-only)
  no_sql      -- turn 2's generated_sql is null (no fresh query at all)
  branch_drop -- turn 2 ran a query but at least one of the three is missing,
                 i.e. an OR branch of turn 1's predicate was simplified away
  hedge_fired -- turn 2's reply carries the step-3 "Heads up: ..." sentence

Also counts sql_error runs: any turn whose reply is the SQL route's failure
text. That is the counter the 2026-08-18 jsonb-cast fix is about.

Usage: python score_runs.py <evidence_dir> [file_glob]
"""
import glob
import json
import os
import sys

EXPECTED_USD = ("CNH-1001", "ACM-2002", "ZEN-3003")
SQL_ERROR_MARKERS = (
    "Failed to execute database check",
    "function lower(jsonb) does not exist",
    "UndefinedFunction",
)


def score_file(path):
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    turns = data["turns"]
    t2 = turns[1]["response_json"]
    sql = t2.get("generated_sql")
    content = t2.get("content") or ""
    all_content = " ".join((t.get("response_json", {}).get("content") or "") for t in turns)

    row = {
        "file": os.path.basename(path),
        "no_sql": sql is None,
        "hedge_fired": "Heads up" in content,
        "sql_error": any(m in all_content for m in SQL_ERROR_MARKERS),
        "missing": [n for n in EXPECTED_USD if n not in content],
    }
    row["correct"] = (not row["no_sql"]) and not row["missing"] and not row["sql_error"]
    row["branch_drop"] = (not row["no_sql"]) and bool(row["missing"]) and not row["sql_error"]
    return row


def main(directory, pattern="raw_turns_*.json"):
    files = sorted(glob.glob(os.path.join(directory, pattern)))
    rows = [score_file(p) for p in files]
    n = len(rows)
    print(f"{directory}  ({pattern})  n={n}")
    print(f"{'file':<28} {'correct':>8} {'no_sql':>7} {'branch_drop':>12} {'sql_error':>10} {'hedge':>6}  missing")
    for r in rows:
        print(
            f"{r['file']:<28} {str(r['correct']):>8} {str(r['no_sql']):>7} "
            f"{str(r['branch_drop']):>12} {str(r['sql_error']):>10} {str(r['hedge_fired']):>6}  {','.join(r['missing'])}"
        )
    for key in ("correct", "no_sql", "branch_drop", "sql_error", "hedge_fired"):
        print(f"{key}: {sum(1 for r in rows if r[key])}/{n}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else ".", sys.argv[2] if len(sys.argv) > 2 else "raw_turns_*.json")
