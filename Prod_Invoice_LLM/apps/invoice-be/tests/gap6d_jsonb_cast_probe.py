"""BE Gap 241/242 follow-on -- live jsonb-cast probe (senior-dev, 2026-08-18).

A live run against fully-merged master aborted a large fraction of tag/keyword
chat questions with:

    psycopg2.errors.UndefinedFunction: function lower(jsonb) does not exist

...because the SQL prompt's own canonical example was
`LOWER(tags) LIKE LOWER('%"hardware"%')`, labelled "works in both SQLite and
Postgres". It does not: `tags`/`items`/`sa_alerts` are JSONB on Postgres
(models.py `JSON_VARIANT`), and Postgres has no lower(jsonb). The unit suite
runs on SQLite, which is untyped and accepts it -- which is how it shipped.

This probe asks the question shapes that trip that path, over fresh sessions,
against whichever backend GAP6D_BASE_URL points at, and records for each
generated query:

  sql_error      -- the reply is the SQL route's failure text (or names the
                    lower(jsonb) error directly)
  uncast_lower   -- the generated SQL contains LOWER(<json col>) with no cast
  cast_used      -- the generated SQL casts the json column (CAST/::text)

IMPORTANT, learned from the 2026-08-18 run: these three counters are computed
from the API's `generated_sql`, which is the query that finally SUCCEEDED. The
SQL route retries up to 3 times and feeds the DB error back to the model, so a
first attempt that aborted on lower(jsonb) is invisible here -- the pre-fix run
scored uncast_lower 0/16 at this level while the server log recorded 13 real
`function lower(jsonb) does not exist` aborts over the same 16 messages. The
backend log is the ground truth for this defect; these counters only show what
the user ended up being answered from. Both are kept in the evidence dir.

It reuses the Gap 237 repro tenant and seed data (tests/gap237_sql_repro.py) so
no other tenant's fixtures are disturbed, and restores the mock user's tenant
afterwards exactly like that harness does. Read-only apart from the reseed the
shared harness performs.

Usage: python tests/gap6d_jsonb_cast_probe.py <run_label> [iterations]
Env:   GAP6D_BASE_URL (default http://localhost:8000/api/v1)
       GAP6D_EVIDENCE_DIR
"""
import json
import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import httpx

# NB: gap237_sql_repro rebinds sys.stdout to a utf-8 TextIOWrapper at import
# time. Doing the same here as well would leave two wrappers over one buffer and
# the first close would take the stream down mid-run -- so this module doesn't.
from gap237_sql_repro import (  # noqa: E402  (same tenant + seed as the Gap 237 harness)
    flush_answer_cache,
    repoint_mock_user,
    restore_mock_user,
    seed_tenant_and_invoices,
)

TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
EVIDENCE_DIR = os.environ.get("GAP6D_EVIDENCE_DIR") or os.path.join(
    os.path.dirname(TESTS_DIR), "docs", "test_evidence", "gap237_jsonb_cast_2026-08-18"
)
os.makedirs(EVIDENCE_DIR, exist_ok=True)

BASE = os.environ.get("GAP6D_BASE_URL") or "http://localhost:8000/api/v1"

# GAP6D_SET picks a question set.
#   category  -- the phrasings from the failing live run (cloud / office
#                supplies / furniture tag+keyword searches, plus an sa_alerts one)
#   tag_literal -- phrasings that map straight onto rule 6's own worked example
#                (a specific NAMED tag, i.e. the '%"hardware"%' shape). This is
#                the set where the pre-fix prompt actually reproduced the
#                lower(jsonb) abort; the category set did not.
QUESTION_SETS = {
    "category": [
        ("cloud_tag", "Which invoices are tagged cloud?"),
        ("office_supplies", "How much did we spend on office supplies?"),
        ("furniture", "How much did we spend on furniture?"),
        ("items_keyword", "Show me invoices with toner cartridges in the line items"),
        ("alerts", "Which invoices have audit alerts mentioning a duplicate?"),
    ],
    "tag_literal": [
        ("tag_hosting", "Do we have any invoices with the tag 'hosting'?"),
        ("tag_infra", "List the invoices carrying the tag \"infra\"."),
        ("tag_supplies", "Which invoices have the tag 'supplies' on them?"),
    ],
}
QUESTIONS = QUESTION_SETS[os.environ.get("GAP6D_SET", "category")]

JSON_COLUMNS = ("tags", "items", "sa_alerts")
SQL_ERROR_MARKERS = (
    "Failed to execute database check",
    "function lower(jsonb) does not exist",
    "UndefinedFunction",
)


def classify(sql, content):
    sql = sql or ""
    flat = " ".join(sql.split())
    uncast = [c for c in JSON_COLUMNS if re.search(r"LOWER\(\s*%s\s*\)" % c, flat, re.IGNORECASE)]
    cast = [
        c
        for c in JSON_COLUMNS
        if re.search(r"CAST\(\s*%s\s+AS\s+TEXT\s*\)" % c, flat, re.IGNORECASE)
        or re.search(r"%s\s*::\s*text" % c, flat, re.IGNORECASE)
    ]
    return {
        "sql_error": any(m in (content or "") for m in SQL_ERROR_MARKERS),
        "uncast_lower": uncast,
        "cast_used": cast,
        "sql": flat,
    }


def main(run_label, iterations):
    tenant_id = seed_tenant_and_invoices()
    prior_tenant = repoint_mock_user(tenant_id)
    headers = {"Authorization": "Bearer test_" + tenant_id}
    record = {"run_label": run_label, "tenant_id": tenant_id, "base_url": BASE, "questions": []}

    try:
        with httpx.Client(base_url=BASE, timeout=180.0) as client:
            for label, question in QUESTIONS:
                attempts = []
                print("\n########## %s ##########\nQ: %s" % (label, question))
                for i in range(iterations):
                    flush_answer_cache(tenant_id)
                    sess = client.post(
                        "/chat/sessions", headers=headers,
                        json={"title": "jsonb cast probe %s %s #%d" % (label, run_label, i)},
                    )
                    sess.raise_for_status()
                    session_id = sess.json()["id"]
                    t0 = time.time()
                    resp = client.post(
                        "/chat/sessions/%s/message" % session_id,
                        headers=headers,
                        json={"content": question},
                        timeout=120.0,
                    )
                    resp.raise_for_status()
                    data = resp.json()
                    verdict = classify(data.get("generated_sql"), data.get("content"))
                    print(
                        "--- attempt %d (%.1fs) sql_error=%s uncast=%s cast=%s"
                        % (i, time.time() - t0, verdict["sql_error"], verdict["uncast_lower"], verdict["cast_used"])
                    )
                    print("SQL: " + verdict["sql"][:400])
                    print("A:   " + str(data.get("content"))[:300].replace("\n", " "))
                    attempts.append(
                        {"attempt": i, "session_id": session_id, "verdict": verdict, "response_json": data}
                    )
                record["questions"].append({"label": label, "question": question, "attempts": attempts})
    finally:
        restore_mock_user(prior_tenant)

    all_attempts = [a for q in record["questions"] for a in q["attempts"]]
    summary = {
        "attempts": len(all_attempts),
        "sql_error": sum(1 for a in all_attempts if a["verdict"]["sql_error"]),
        "uncast_lower": sum(1 for a in all_attempts if a["verdict"]["uncast_lower"]),
        "cast_used": sum(1 for a in all_attempts if a["verdict"]["cast_used"]),
        "no_sql": sum(1 for a in all_attempts if not a["verdict"]["sql"]),
    }
    record["summary"] = summary
    print("\nSUMMARY %s: %s" % (run_label, summary))

    out_path = os.path.join(EVIDENCE_DIR, "jsonb_cast_probe_%s.json" % run_label)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(record, f, indent=2, default=str)
    print("Wrote " + out_path)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "run1", int(sys.argv[2]) if len(sys.argv) > 2 else 2)
