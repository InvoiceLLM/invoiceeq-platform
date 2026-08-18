"""BE Gap 237 step 1 -- live repro, functional-tester pass 2026-08-17.

Seeds a dedicated, clearly-named test tenant (NOT tenant-us/india/eu -- those
are shared fixtures a concurrent senior-dev session is also using) with a
small invoice set deliberately constructed so a broad "cloud" category
question matches invoices via three different SQL branches:

  1. vendor_name  -- "CloudNine Hosting"            (USD 1200.00)
  2. tags         -- Acme Manufacturing, tags contains cloud  (USD 3400.00)
  3. items ONLY   -- Zenith Consulting, line item "Cloud Migration
                     Assessment" -- vendor_name/customer_name/tags contain
                     no cloud reference at all               (USD 69012.43)
  4. vendor_name, different currency -- "CloudNine Hosting EU" (EUR 800.00)
  5. control, no match anywhere -- Office Depot Supplies        (USD 500.00)

Turn 1: broad category question (cloud).
Turn 2 (same session): a narrowing follow-up that explicitly references a
count from turn 1's answer ("the N USD ones"), mirroring the founder-reported
phrasing ("explain the 3 USD ones") that Gap 237 was opened from.

Both turns' generated_sql, and the real ChatMessage.result_invoice_ids rows
(read directly from the DB -- not exposed by the chat API response schema),
are captured verbatim. Evidence-capture only, no assertions, no application
code or prompt changes.

Run index / cache: the SQL/RAG answer cache is keyed on
(tenant_id, normalized_question_text) with a 1hr TTL (Task 6.11) -- so
re-running this script against the SAME tenant with the SAME question text
would just replay the first run's cached answer, not make a fresh LLM call.
This script therefore flushes that tenant's cache keys before posting.
"""
import io
import json
import os
import sys
import time
from datetime import date

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import httpx
from sqlmodel import Session, select

from database import engine
from models import Tenant, Invoice, User, ChatMessage

TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
# Both overrides added by senior-dev's Gap 237 step-2 fix pass (2026-08-17) so the
# same harness can be pointed at a private backend instance / private evidence
# folder without disturbing a concurrently-running agent's server or clobbering
# functional-tester's original run0..run6 evidence. Defaults are unchanged.
EVIDENCE_DIR = os.environ.get("GAP237_EVIDENCE_DIR") or os.path.join(
    os.path.dirname(TESTS_DIR), "docs", "test_evidence", "gap237_sql_repro_2026-08-17"
)
os.makedirs(EVIDENCE_DIR, exist_ok=True)

TENANT_DOMAIN = "gap237-chat-sql-repro-test.invalid"
TENANT_NAME = "Gap237 Chat SQL Repro Test (functional-tester, do not reuse for other tests)"

BASE = os.environ.get("GAP237_BASE_URL") or "http://localhost:8000/api/v1"


def flush_answer_cache(tenant_id):
    try:
        import redis
        from config import get_settings
        r = redis.Redis.from_url(get_settings().REDIS_URL, decode_responses=True)
        keys = r.keys("chat_answer_cache:" + tenant_id + ":*")
        if keys:
            r.delete(*keys)
            print("Flushed " + str(len(keys)) + " cached answer key(s) for tenant " + tenant_id)
    except Exception as e:
        print("Cache flush failed (non-fatal): " + str(e))


def seed_tenant_and_invoices():
    with Session(engine) as s:
        tenant = s.exec(select(Tenant).where(Tenant.domain == TENANT_DOMAIN)).first()
        if tenant is None:
            tenant = Tenant(name=TENANT_NAME, domain=TENANT_DOMAIN, billing_plan="pro_combined")
            s.add(tenant)
            s.commit()
            s.refresh(tenant)
            print("Created tenant " + str(tenant.id))
        else:
            print("Reusing tenant " + str(tenant.id))
            existing = s.exec(select(Invoice).where(Invoice.tenant_id == tenant.id)).all()
            for inv in existing:
                s.delete(inv)
            s.commit()

        invoices = [
            dict(
                vendor_name="CloudNine Hosting",
                invoice_number="CNH-1001",
                grand_total=1200.00,
                subtotal=1200.00,
                tax_amount=0.0,
                currency="USD",
                tags=["hosting", "subscription"],
                items=[{"description": "Monthly hosting fee", "quantity": 1, "unit_price": 1200.00, "amount": 1200.00}],
                po_number="PO-CNH-1001",
            ),
            dict(
                vendor_name="Acme Manufacturing",
                invoice_number="ACM-2002",
                grand_total=3400.00,
                subtotal=3400.00,
                tax_amount=0.0,
                currency="USD",
                tags=["cloud", "infra"],
                items=[{"description": "Server rack maintenance", "quantity": 1, "unit_price": 3400.00, "amount": 3400.00}],
                po_number="PO-ACM-2002",
            ),
            dict(
                vendor_name="Zenith Consulting",
                invoice_number="ZEN-3003",
                grand_total=69012.43,
                subtotal=69012.43,
                tax_amount=0.0,
                currency="USD",
                tags=["consulting", "assessment"],
                items=[{"description": "Cloud Migration Assessment", "quantity": 1, "unit_price": 69012.43, "amount": 69012.43}],
                po_number="PO-ZEN-3003",
            ),
            dict(
                vendor_name="CloudNine Hosting EU",
                invoice_number="CNH-EU-1002",
                grand_total=800.00,
                subtotal=800.00,
                tax_amount=0.0,
                currency="EUR",
                tags=["hosting", "subscription"],
                items=[{"description": "Monthly hosting fee EU region", "quantity": 1, "unit_price": 800.00, "amount": 800.00}],
                po_number="PO-CNH-EU-1002",
            ),
            dict(
                vendor_name="Office Depot Supplies",
                invoice_number="ODS-4004",
                grand_total=500.00,
                subtotal=500.00,
                tax_amount=0.0,
                currency="USD",
                tags=["office", "supplies"],
                items=[{"description": "Paper and toner cartridges", "quantity": 1, "unit_price": 500.00, "amount": 500.00}],
                po_number="PO-ODS-4004",
            ),
        ]

        created = []
        for spec in invoices:
            inv = Invoice(
                tenant_id=tenant.id,
                file_path="test/" + spec["invoice_number"] + ".pdf",
                status="COMPLETED",
                flow_direction="INBOUND",
                invoice_date=date(2026, 6, 15),
                due_date=date(2026, 7, 15),
                **spec,
            )
            s.add(inv)
            created.append(spec["invoice_number"])
        s.commit()
        print("Seeded invoices: " + str(created))
        return str(tenant.id)


def repoint_mock_user(tenant_id):
    """Same pattern as tests/_multiturn_chat_repro.py -- ALLOW_MOCK_AUTH's
    shared user_test_default row determines the effective tenant once it
    exists, regardless of the UUID embedded in the Bearer test_<uuid> token.
    Returns the PRIOR tenant_id (as str, or None) so it can be restored."""
    with Session(engine) as s:
        user = s.exec(select(User).where(User.clerk_user_id == "user_test_default")).first()
        prior = str(user.tenant_id) if (user and user.tenant_id) else None
        if user is not None:
            user.tenant_id = tenant_id
            s.add(user)
            s.commit()
    return prior


def restore_mock_user(prior_tenant_id):
    if prior_tenant_id is None:
        return
    with Session(engine) as s:
        user = s.exec(select(User).where(User.clerk_user_id == "user_test_default")).first()
        if user is not None:
            user.tenant_id = prior_tenant_id
            s.add(user)
            s.commit()
    print("Restored user_test_default.tenant_id -> " + str(prior_tenant_id))


def fetch_result_invoice_ids(session_id):
    """Read straight from ChatMessage -- not exposed on the chat API response
    schema (routers/chat.py's MessageResponse omits result_invoice_ids)."""
    with Session(engine) as s:
        rows = s.exec(
            select(ChatMessage)
            .where(ChatMessage.session_id == session_id, ChatMessage.role == "assistant")
            .order_by(ChatMessage.created_at)
        ).all()
        return [{"content_snippet": r.content[:120], "result_invoice_ids": r.result_invoice_ids} for r in rows]


def main(run_label):
    tenant_id = seed_tenant_and_invoices()
    flush_answer_cache(tenant_id)
    prior_tenant = repoint_mock_user(tenant_id)
    print("user_test_default repointed to " + tenant_id + " (was " + str(prior_tenant) + ")")

    headers = {"Authorization": "Bearer test_" + tenant_id}
    turns = []
    session_id = None

    try:
        with httpx.Client(base_url=BASE, timeout=180.0) as client:
            session_resp = client.post(
                "/chat/sessions", headers=headers, json={"title": "Gap237 SQL repro " + run_label}
            )
            session_resp.raise_for_status()
            session_id = session_resp.json()["id"]
            print("Session: " + str(session_id))

            questions = [
                ("turn_1_broad", "What are the total invoices related to cloud?"),
                ("turn_2_narrow", "Can you explain the 3 USD ones in detail?"),
            ]

            for label, prompt in questions:
                t0 = time.time()
                resp = client.post(
                    "/chat/sessions/" + str(session_id) + "/message",
                    headers=headers,
                    json={"content": prompt},
                    timeout=120.0,
                )
                elapsed = round(time.time() - t0, 1)
                resp.raise_for_status()
                data = resp.json()
                print("\n=== " + label + " (" + str(elapsed) + "s) ===")
                print("Q: " + prompt)
                print("A: " + str(data.get("content")))
                print("generated_sql: " + str(data.get("generated_sql")))
                turns.append(
                    {
                        "label": label,
                        "prompt": prompt,
                        "status_code": resp.status_code,
                        "response_json": data,
                        "elapsed_seconds": elapsed,
                    }
                )

            db_snapshot = fetch_result_invoice_ids(session_id)
    finally:
        restore_mock_user(prior_tenant)

    out_path = os.path.join(EVIDENCE_DIR, "raw_turns_" + run_label + ".json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(
            {
                "run_label": run_label,
                "tenant_id": tenant_id,
                "session_id": str(session_id),
                "turns": turns,
                "chat_message_db_rows": db_snapshot,
            },
            f,
            indent=2,
            default=str,
        )
    print("\nWrote " + out_path)


if __name__ == "__main__":
    run_label = sys.argv[1] if len(sys.argv) > 1 else "run1"
    main(run_label)
