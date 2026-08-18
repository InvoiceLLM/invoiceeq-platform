"""BE Gaps 241 + 242 -- live category-question probe (senior-dev, 2026-08-17).

Read-only. Asks the two questions that opened the gaps against the real running
backend and the real tenant-us data, captures the generated SQL and the reply,
and prints the DB ground truth alongside so the two can be compared directly
rather than taken on trust:

  Gap 241: "How much did we spend on office supplies?"
           -- previously answered $2,040.00 by OR-ing bare '%office%' /
           '%supplies%' branches, which swept in Redwood Facilities Group's
           janitorial invoice ($1,590) alongside Summit Office Supplies ($450).
  Gap 242: "And logistics or freight costs?"
           -- previously answered $200.00 by checking only line-item
           descriptions, missing Blue Ridge Logistics entirely (a vendor named
           "Logistics", tagged freight+logistics). Its `items` column was
           reseeded first (docs/test_evidence/gap242_blue_ridge_reseed_2026-08-17/),
           so this is now verifiable against clean data.

Answers are LLM-non-deterministic, so each question is asked over several fresh
sessions and every run is recorded -- a single pass proves nothing either way.
The tenant's cached answer for exactly these two question strings is deleted
first (chat_answer_cache:{tenant}:{normalized question}); nothing else is
touched, and no invoice row is written.

Usage: python tests/gap241_242_category_probe.py <run_label> [iterations]
Env:   GAP241_BASE_URL (default http://localhost:8000/api/v1)
"""
import io
import json
import os
import sys
import time

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import httpx
from sqlmodel import Session, select

from database import engine
from models import Tenant, Invoice, User

TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
EVIDENCE_DIR = os.environ.get("GAP241_EVIDENCE_DIR") or os.path.join(
    os.path.dirname(TESTS_DIR), "docs", "test_evidence", "gap241_242_category_2026-08-17"
)
os.makedirs(EVIDENCE_DIR, exist_ok=True)

BASE = os.environ.get("GAP241_BASE_URL") or "http://localhost:8000/api/v1"
TENANT_DOMAIN = "invoiceeq-test-us.invalid"

QUESTIONS = [
    ("gap241_office_supplies", "How much did we spend on office supplies?", ["office supplies"]),
    ("gap242_logistics_freight", "And logistics or freight costs?", ["logistics", "freight"]),
]


def drop_cached_answer(tenant_id, question):
    import re as _re
    try:
        import redis
        from config import get_settings

        r = redis.Redis.from_url(get_settings().REDIS_URL, decode_responses=True)
        key = "chat_answer_cache:%s:%s" % (tenant_id, _re.sub(r"\s+", " ", question.strip().lower()))
        r.delete(key)
    except Exception as e:
        print("Cache delete failed (non-fatal): " + str(e))


def ground_truth(tenant_id, phrases):
    """Which invoices SHOULD a category question match, checked in Python
    against the same four columns rule 6b names -- computed from the rows, not
    from any generated SQL."""
    out = []
    with Session(engine) as s:
        rows = s.exec(select(Invoice).where(Invoice.tenant_id == tenant_id)).all()
        for inv in rows:
            haystacks = {
                "tags": json.dumps(inv.tags or []).lower(),
                "items": json.dumps(inv.items or []).lower(),
                "vendor_name": (inv.vendor_name or "").lower(),
                "customer_name": (inv.customer_name or "").lower(),
            }
            hits = {
                col: [p for p in phrases if p in text]
                for col, text in haystacks.items()
                if any(p in text for p in phrases)
            }
            if hits:
                out.append(
                    {
                        "invoice_number": inv.invoice_number,
                        "vendor_name": inv.vendor_name,
                        "grand_total": inv.grand_total,
                        "currency": inv.currency,
                        "matched_via": hits,
                    }
                )
    return out


def main(run_label, iterations):
    with Session(engine) as s:
        tenant = s.exec(select(Tenant).where(Tenant.domain == TENANT_DOMAIN)).first()
        if tenant is None:
            raise SystemExit("tenant %s not found" % TENANT_DOMAIN)
        tenant_id = str(tenant.id)
        user = s.exec(select(User).where(User.clerk_user_id == "user_test_default")).first()
        if user is None or str(user.tenant_id) != tenant_id:
            raise SystemExit(
                "mock user is not pointed at %s -- refusing to repoint it, another agent may be "
                "mid-run against this stack" % TENANT_DOMAIN
            )

    headers = {"Authorization": "Bearer test_" + tenant_id}
    record = {"run_label": run_label, "tenant_id": tenant_id, "questions": []}

    for label, question, phrases in QUESTIONS:
        expected = ground_truth(tenant.id, phrases)
        expected_total = round(sum(e["grand_total"] or 0 for e in expected), 2)
        print("\n########## %s ##########" % label)
        print("Q: " + question)
        print("DB ground truth (%d invoice(s), total %.2f):" % (len(expected), expected_total))
        for e in expected:
            print("  - %s %s %.2f via %s" % (e["invoice_number"], e["vendor_name"], e["grand_total"], list(e["matched_via"])))

        attempts = []
        with httpx.Client(base_url=BASE, timeout=180.0) as client:
            for i in range(iterations):
                drop_cached_answer(tenant_id, question)
                sess = client.post("/chat/sessions", headers=headers, json={"title": "%s %s #%d" % (label, run_label, i)})
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
                print("\n--- attempt %d (%.1fs) ---" % (i, time.time() - t0))
                print("A: " + str(data.get("content"))[:600])
                print("SQL: " + " ".join(str(data.get("generated_sql")).split())[:600])
                attempts.append({"attempt": i, "session_id": session_id, "response_json": data})

        record["questions"].append(
            {
                "label": label,
                "question": question,
                "phrases": phrases,
                "expected": expected,
                "expected_total": expected_total,
                "attempts": attempts,
            }
        )

    out_path = os.path.join(EVIDENCE_DIR, "category_probe_%s.json" % run_label)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(record, f, indent=2, default=str)
    print("\nWrote " + out_path)


if __name__ == "__main__":
    label = sys.argv[1] if len(sys.argv) > 1 else "run1"
    iters = int(sys.argv[2]) if len(sys.argv) > 2 else 3
    main(label, iters)
