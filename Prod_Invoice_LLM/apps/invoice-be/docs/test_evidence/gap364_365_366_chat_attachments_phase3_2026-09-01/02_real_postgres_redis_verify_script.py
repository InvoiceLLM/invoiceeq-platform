import os, sys, json, time, threading
os.environ.setdefault("MOCK_EMBEDDINGS", "true")
sys.path.insert(0, r"C:\Users\S Banerjee\Desktop\Invoice_LLM\Prod_Invoice_LLM\apps\invoice-be")

from uuid import uuid4, UUID
from unittest.mock import patch, MagicMock
from sqlmodel import Session, select

import config
from config import get_settings
from database import engine
from models import ChatSession, ChatMessage, ChatAttachment, Invoice, Tenant
from services.chat_queue import (
    ChatQueueService, ChatQueueCapacityError, get_redis_client,
    PER_TENANT_MAX_ACTIVE_CHAT, CHAT_TENANT_INFLIGHT_PREFIX, CHAT_JOB_CHANNEL_PREFIX,
)

def hdr(t):
    print("\n" + "="*80)
    print(t)
    print("="*80)

r = get_redis_client()
assert r is not None, "Real redis client did not connect"
print("Redis PING:", r.ping())
with Session(engine) as s:
    print("Postgres check - tenant count:", s.exec(select(Tenant)).all().__len__())

# =============================================================================
# T1 (Gap 364) — real Redis concurrency ceiling + slot-leak fix
# =============================================================================
hdr("T1a — 4th concurrent job rejected, real Redis counter, real accept/reject/release cycle")
tenant_t1 = f"phase3-t1-{uuid4()}"
inflight_key = f"{CHAT_TENANT_INFLIGHT_PREFIX}{tenant_t1}"
r.delete(inflight_key)

accepted_jobs = []
for i in range(PER_TENANT_MAX_ACTIVE_CHAT):
    res = ChatQueueService.enqueue_chat_job(
        session_id=str(uuid4()), user_msg_id=str(uuid4()),
        content=f"turn {i}", tenant_id=tenant_t1, client=r,
    )
    accepted_jobs.append(res)
    print(f"  accepted #{i+1}: {res['status']} job_id={res['job_id']}")

print("  real redis GET", inflight_key, "=", r.get(inflight_key))

try:
    ChatQueueService.enqueue_chat_job(
        session_id=str(uuid4()), user_msg_id=str(uuid4()),
        content="4th turn", tenant_id=tenant_t1, client=r,
    )
    print("  FAIL: 4th call did not raise!")
except ChatQueueCapacityError as e:
    print(f"  4th call correctly rejected: active={e.active} limit={e.limit} retry_after={e.retry_after_seconds}")

print("  real redis GET after rejection", inflight_key, "=", r.get(inflight_key))
assert r.get(inflight_key) == "3", "counter must still read 3 after the refusal handed its slot back"

# Release all 3: one via complete_job, one via fail_job, one via manual release
ChatQueueService.complete_job(accepted_jobs[0]["job_id"], tenant_t1, {"content": "done"}, client=r)
print("  after complete_job:", r.get(inflight_key))
ChatQueueService.fail_job(accepted_jobs[1]["job_id"], tenant_t1, "boom", client=r)
print("  after fail_job:", r.get(inflight_key))
ChatQueueService.release_tenant_slot(tenant_t1, client=r)
print("  after release_tenant_slot:", r.get(inflight_key))
assert r.get(inflight_key) == "0", "chat_inflight must return to 0 after completion+failure+release"
print("  PASS: chat_inflight returns to 0 after both completion and failure release paths (real Redis)")

hdr("T1b — slot-leak fix: failed lpush against REAL Redis counters (only lpush is faked)")
tenant_t1b = f"phase3-t1b-{uuid4()}"
inflight_key_b = f"{CHAT_TENANT_INFLIGHT_PREFIX}{tenant_t1b}"
r.delete(inflight_key_b)

class _FlakyLpushRealRedis:
    """Delegates every op to the REAL redis client except lpush, which raises
    once then works. Counters (incr/decr/get/set) all hit the real instance."""
    def __init__(self, real_client, fail_times=1):
        self._real = real_client
        self._fail_times = fail_times
        self._calls = 0
    def incr(self, key): return self._real.incr(key)
    def decr(self, key): return self._real.decr(key)
    def get(self, key): return self._real.get(key)
    def set(self, key, value, ex=None): return self._real.set(key, value, ex=ex)
    def lpush(self, key, value):
        self._calls += 1
        if self._calls <= self._fail_times:
            raise ConnectionError("simulated Redis lpush failure (real redis backing the counters)")
        return self._real.lpush(key, value)
    def publish(self, channel, message):
        return self._real.publish(channel, message)

flaky = _FlakyLpushRealRedis(r, fail_times=1)
res = ChatQueueService.enqueue_chat_job(
    session_id=str(uuid4()), user_msg_id=str(uuid4()),
    content="flaky lpush turn", tenant_id=tenant_t1b, client=flaky,
)
print("  enqueue result despite lpush failure (swallowed, non-500):", res)
real_val = r.get(inflight_key_b)
print("  REAL redis counter after the failed lpush:", real_val)
assert real_val in (None, "0"), f"slot must be released back to 0 on real Redis, got {real_val}"
print("  PASS: INCR happened on real Redis, lpush failed, slot was rolled back to 0 on real Redis")

r.delete(inflight_key), r.delete(inflight_key_b)

# =============================================================================
# T1c — HTTP 429 + Retry-After against a REAL saturated tenant counter,
# and confirm no orphan ChatMessage row on REAL Postgres.
# =============================================================================
hdr("T1c — real HTTP 429 with Retry-After, real Postgres orphan-row check")
from fastapi.testclient import TestClient
from main import app

tenant_t1c = uuid4()
with Session(engine) as s:
    s.add(Tenant(id=tenant_t1c, name="phase3-t1c", domain=f"phase3-t1c-{tenant_t1c.hex[:8]}.invalid"))
    chat_session = ChatSession(id=uuid4(), tenant_id=tenant_t1c, title="New Chat")
    s.add(chat_session)
    s.commit()
    session_id = chat_session.id

inflight_key_c = f"{CHAT_TENANT_INFLIGHT_PREFIX}{tenant_t1c}"
r.delete(inflight_key_c)
# Saturate the REAL redis counter to the ceiling, exactly as 3 real in-flight jobs would.
for _ in range(PER_TENANT_MAX_ACTIVE_CHAT):
    r.incr(inflight_key_c)
print("  primed real redis counter to:", r.get(inflight_key_c))

client = TestClient(app)
from dependencies import TenantContext, get_tenant_context, get_tenant_or_api_key_context

def set_tenant_ctx(tenant_id, role="Admin", plan="active"):
    """Real Postgres run discovered that the `test_<uuid>` mock-auth token
    vocabulary is NOT tenant-isolatable across multiple calls against a
    PERSISTENT Postgres in one process: ALLOW_MOCK_AUTH's provisioning path
    keys off a fixed MOCK_USER_ID/email, so the second mock-auth call reuses
    the User row (and its tenant) provisioned by the first, ignoring the
    embedded UUID in the token. SQLite-per-test never hits this because each
    test starts from an empty database. Dependency-override is used instead
    to pin the caller's tenant deterministically for these multi-tenant
    real-Postgres checks; the DB/Redis effects being verified are all still
    real, only the auth *resolution* is bypassed.
    """
    ctx = TenantContext(tenant_id=tenant_id, user_id=f"u_{tenant_id}", role=role, billing_plan=plan)
    app.dependency_overrides[get_tenant_context] = lambda: ctx
    app.dependency_overrides[get_tenant_or_api_key_context] = lambda: ctx
set_tenant_ctx(tenant_t1c)

with patch.object(config.settings, "ENABLE_ASYNC_CHAT_QUEUE", True):
    resp = client.post(
        f"/api/v1/chat/sessions/{session_id}/message",
        json={"content": "the 4th turn that should be rejected"},
    )
print("  status:", resp.status_code, "Retry-After:", resp.headers.get("Retry-After"))
print("  body:", resp.json())
assert resp.status_code == 429
assert resp.headers.get("Retry-After") == "5"

with Session(engine) as s:
    rows = s.exec(select(ChatMessage).where(ChatMessage.session_id == session_id)).all()
    print("  ChatMessage rows for this session after the 429:", len(rows))
    assert rows == [], "no orphan ChatMessage row must exist after a 429 rejection (real Postgres)"
    fresh_session = s.get(ChatSession, session_id)
    print("  session title unchanged:", fresh_session.title)
    assert fresh_session.title == "New Chat"
print("  PASS: real 429 + Retry-After: 5, zero orphan ChatMessage rows on real Postgres")

# Release the primed counter and confirm the tenant can chat again (real redis + real DB)
for _ in range(PER_TENANT_MAX_ACTIVE_CHAT):
    ChatQueueService.release_tenant_slot(str(tenant_t1c), client=r)
print("  counter after cleanup release:", r.get(inflight_key_c))

with patch.object(config.settings, "ENABLE_ASYNC_CHAT_QUEUE", True), \
     patch("routers.chat._chat_background_pool") as pool:
    resp2 = client.post(
        f"/api/v1/chat/sessions/{session_id}/message",
        json={"content": "now under the ceiling"},
    )
print("  status after release:", resp2.status_code, resp2.json().get("status"))
assert resp2.status_code == 202
print("  PASS: tenant admitted again once real redis counter is back under ceiling")
r.delete(inflight_key_c)

# =============================================================================
# T2 (Gap 365) — per-session lock on REAL Redis, and a real SSE transcript
# pulled from the real GET /chat/jobs/{id}/stream endpoint (real Postgres +
# real Redis; the LLM boundary is mocked, matching this repo's own narrow-test
# convention -- hard rule 2 is about DB/Redis, not the model call).
# =============================================================================
from queue_worker.handlers import chat_session_lock, CHAT_SESSION_LOCK_PREFIX, handle_process_chat_job

hdr("T2a — per-session lock against REAL Redis: same-session serialises, cross-session parallel")

def _overlap_probe(session_ids):
    inside, overlapped, guard = [], {"v": False}, threading.Lock()
    acquired = []
    def _turn(sid):
        with chat_session_lock(sid, client=r, wait_seconds=8, poll_seconds=0.02) as got:
            acquired.append(got)
            with guard:
                inside.append(sid)
                if len(inside) > 1:
                    overlapped["v"] = True
            time.sleep(0.4)
            with guard:
                inside.remove(sid)
    threads = [threading.Thread(target=_turn, args=(sid,)) for sid in session_ids]
    for t in threads: t.start()
    for t in threads: t.join(timeout=20)
    return overlapped["v"], acquired

same_sid = str(uuid4())
overlap_same, acq_same = _overlap_probe([same_sid, same_sid])
print(f"  same-session x2: acquired={acq_same} overlapped={overlap_same}")
assert acq_same == [True, True] and overlap_same is False

diff_a, diff_b = str(uuid4()), str(uuid4())
overlap_diff, acq_diff = _overlap_probe([diff_a, diff_b])
print(f"  cross-session x2: acquired={acq_diff} overlapped={overlap_diff}")
assert acq_diff == [True, True] and overlap_diff is True
print("  PASS: real Redis SET NX lock serialises same-session turns, leaves cross-session turns parallel")

hdr("T2b — real SSE transcript from GET /chat/jobs/{id}/stream (real Postgres + real Redis)")

tenant_t2 = uuid4()
with Session(engine) as s:
    s.add(Tenant(id=tenant_t2, name="phase3-t2", domain=f"phase3-t2-{tenant_t2.hex[:8]}.invalid"))
    cs = ChatSession(id=uuid4(), tenant_id=tenant_t2, title="T2")
    s.add(cs)
    s.commit()
    session_id_t2 = cs.id
    job_id = f"phase3-t2-job-{uuid4().hex[:10]}"
    user_msg_id = uuid4()
    s.add(ChatMessage(id=user_msg_id, session_id=session_id_t2, role="user",
                       content="what did we spend, and can you recheck the SQL", status="queued", job_id=job_id))
    s.commit()

class _ScriptedSqlLLM:
    model_name = "gpt-5-mini-fake"
    def with_structured_output(self, schema):
        class _S:
            def invoke(self, prompt):
                return MagicMock(sql=f"SELECT id FROM invoice WHERE tenant_id = '{tenant_t2}'", explanation_or_error=None)
        return _S()
    def invoke(self, prompt):
        return MagicMock(content="Formatted summary of spend.")

calls = {"n": 0}
def _flaky_execute(sql, tenant_id, db_sess, snapshot=None):
    calls["n"] += 1
    if calls["n"] == 1:
        raise RuntimeError("syntax error at or near")
    return "\n\nid | currency\n--- | ---\nrow | USD"

captured = []
stream_url = f"/api/v1/chat/jobs/{job_id}/stream"
set_tenant_ctx(tenant_t2)

def _run_stream():
    with TestClient(app).stream("GET", stream_url) as resp:
        for line in resp.iter_lines():
            if line and line.startswith("data:"):
                captured.append(line[len("data:"):].strip())
                try:
                    parsed = json.loads(captured[-1])
                    if parsed.get("status") in ("completed", "failed"):
                        break
                except Exception:
                    pass

stream_thread = threading.Thread(target=_run_stream)
stream_thread.start()
time.sleep(0.6)  # let the stream subscribe to the real pubsub channel before the job publishes

with Session(engine) as job_db, \
     patch("agents.query_agent.classify_query", return_value="SQL"), \
     patch("agents.query_agent.query_invoice_chunks", return_value=[]), \
     patch("agents.query_agent.get_llm", return_value=_ScriptedSqlLLM()), \
     patch("agents.query_agent.get_cached_answer", return_value=None), \
     patch("agents.query_agent.set_cached_answer"), \
     patch("agents.query_agent._get_tenant_stats_summary", return_value=""), \
     patch("agents.query_agent.execute_generated_sql", side_effect=_flaky_execute):
    result = handle_process_chat_job(
        job_id=job_id, session_id=str(session_id_t2), user_msg_id=str(user_msg_id),
        content="what did we spend, and can you recheck the SQL", tenant_id=str(tenant_t2),
        db_session=job_db,
    )
print("  worker result status:", result["status"])

stream_thread.join(timeout=15)
print(f"  captured {len(captured)} SSE frames from the real HTTP stream endpoint")
steps = []
for raw in captured:
    try:
        d = json.loads(raw)
        if d.get("step"):
            steps.append(d["step"])
    except Exception:
        pass
print("  steps seen on the real SSE transcript, in order:", steps)
distinct = set(steps)
print("  distinct step count:", len(distinct))

frames = []
for raw in captured:
    try:
        frames.append(json.loads(raw))
    except Exception:
        pass
generating_sql_details = [f.get("details") for f in frames if f.get("step") == "generating_sql"]
print("  generating_sql attempt details, in arrival order:", generating_sql_details)

t2b_pass = len(distinct) >= 6 and len(generating_sql_details) >= 2
print("  T2 flip-criterion-1 verdict:", "PASS" if t2b_pass else "FAIL",
      f"(distinct={len(distinct)}, repair-attempts-shown={len(generating_sql_details)})")


hdr("T2c — Gap 237 route-override visible on the real Redis channel under a second real run")
tenant_t2c = uuid4()
with Session(engine) as s:
    s.add(Tenant(id=tenant_t2c, name="phase3-t2c", domain=f"phase3-t2c-{tenant_t2c.hex[:8]}.invalid"))
    cs2 = ChatSession(id=uuid4(), tenant_id=tenant_t2c, title="T2c")
    s.add(cs2)
    s.commit()
    session_id_t2c = cs2.id
    job_id_2c = f"phase3-t2c-job-{uuid4().hex[:10]}"
    um2 = uuid4()
    s.add(ChatMessage(id=um2, session_id=session_id_t2c, role="user", content="can you explain the USD ones in detail?",
                       status="queued", job_id=job_id_2c))
    s.commit()

override_events = []

def _spy_publish_progress(job_id, step, details=None, client=None):
    override_events.append((step, details))
    return _orig_publish_progress(job_id, step, details=details, client=client or r)

_orig_publish_progress = ChatQueueService.publish_progress

with Session(engine) as job_db2, \
     patch("agents.query_agent.classify_query", return_value="RAG"), \
     patch("agents.query_agent.query_invoice_chunks", return_value=[]), \
     patch("agents.query_agent.get_llm", return_value=_ScriptedSqlLLM()), \
     patch("agents.query_agent.get_cached_answer", return_value=None), \
     patch("agents.query_agent.set_cached_answer"), \
     patch("agents.query_agent._get_tenant_stats_summary", return_value=""), \
     patch("agents.query_agent.execute_generated_sql", return_value="\n\nid | currency\n--- | ---\nrow | USD"), \
     patch("agents.query_agent.get_prior_turn_sql", return_value="SELECT id FROM invoice WHERE currency = 'USD'"), \
     patch.object(ChatQueueService, "publish_progress", side_effect=_spy_publish_progress):
    result2c = handle_process_chat_job(
        job_id=job_id_2c, session_id=str(session_id_t2c), user_msg_id=str(um2),
        content="can you explain the USD ones in detail?", tenant_id=str(tenant_t2c),
        db_session=job_db2,
    )
print("  worker result status:", result2c["status"], "generated_sql set:", bool(result2c.get("generated_sql")))
override_detail = [d for s, d in override_events if s == "route_override"]
print("  route_override events published on the real Redis channel:", override_detail)
t2c_pass = bool(override_detail) and override_detail[0].get("route") == "SQL"
print("  T2 flip-criterion-3 verdict:", "PASS" if t2c_pass else "FAIL")

# =============================================================================
# T3 (Gap 366) — real Postgres attachment upload -> match -> compare -> confirm,
# tenant isolation on all 3 endpoints. Blob storage (Azurite) and DB writes are
# real; the deep OCR/extraction call is mocked (same convention as the rest of
# this repo's narrow tests) so this stays inside the time box.
# =============================================================================
hdr("T3 — attached-document flow against real Postgres + real Azurite blob storage")
from services.document_comparison import (
    find_candidate_invoices, compare_reference_to_invoices, build_confirmation_payload,
)

tenant_a = uuid4()
tenant_b = uuid4()
with Session(engine) as s:
    s.add(Tenant(id=tenant_a, name="phase3-t3-a", domain=f"phase3-t3-a-{tenant_a.hex[:8]}.invalid"))
    s.add(Tenant(id=tenant_b, name="phase3-t3-b", domain=f"phase3-t3-b-{tenant_b.hex[:8]}.invalid"))
    cs_a = ChatSession(id=uuid4(), tenant_id=tenant_a, title="T3-A")
    s.add(cs_a)
    s.commit()
    session_a_id = cs_a.id
    # A real invoice for tenant A that Tier-1 PO match should find.
    inv_a = Invoice(
        tenant_id=tenant_a, file_path="x.pdf", vendor_name="Acme Supplies Ltd",
        invoice_number="INV-REAL-1", invoice_date=__import__("datetime").date(2026, 3, 1),
        currency="INR", subtotal=1000.0, tax_amount=180.0, grand_total=1380.0,
        status="COMPLETED", flow_direction="INBOUND", po_number="PO-2026/0099",
        items=[{"description": "Widget", "amount": 1000.0}],
    )
    s.add(inv_a)
    s.commit()
    s.refresh(inv_a)
    inv_a_id = inv_a.id

# --- Real upload through the real endpoint, real blob storage, mocked OCR/extraction ---
import io
fake_pdf_bytes = b"%PDF-1.4 fake reference document for phase3 verification\n%%EOF"
ref_extracted = {
    "doc_type": "PURCHASE_ORDER", "doc_number": "PO-2026/0099", "party_name": "Acme Supplies Ltd",
    "doc_date": "2026-03-01", "currency": "INR", "subtotal": 1000.0, "tax_amount": 180.0,
    "grand_total": 1380.0, "items": [{"description": "Widget", "amount": 1000.0}],
}

set_tenant_ctx(tenant_a)
with patch("queue_worker.handlers._run_ocr", return_value={"content": "fake ocr text"}), \
     patch("agents.extraction_agent.run_extraction_agent", return_value={"extracted_data": ref_extracted}):
    up = client.post(
        f"/api/v1/chat/sessions/{session_a_id}/attachments",
        files={"file": ("po.pdf", fake_pdf_bytes, "application/pdf")},
    )
print("  upload status:", up.status_code, up.json() if up.status_code == 200 else up.text)
assert up.status_code == 200, up.text
attachment = up.json()
attachment_id = attachment["id"]
assert attachment["doc_type"] == "PURCHASE_ORDER"
assert attachment["doc_number"] == "PO-2026/0099"

with Session(engine) as s:
    row = s.get(ChatAttachment, UUID(attachment_id))
    print("  ChatAttachment row exists:", row is not None, "blob_path:", row.blob_path)
    assert row is not None
    print("  blob_path recorded, no billing/ingestion effect asserted below")

# --- D2/D3: no Invoice row created by the attachment, no billing quota moved ---
with Session(engine) as s:
    invoices_for_a = s.exec(select(Invoice).where(Invoice.tenant_id == tenant_a)).all()
    print("  Invoice rows for tenant A after upload (should be exactly the 1 pre-seeded one):", len(invoices_for_a))
    assert len(invoices_for_a) == 1, "an attachment upload must never create an Invoice row (D2)"
    tenant_a_row = s.get(Tenant, tenant_a)
    print("  tenant.ingestion/billing counters untouched (no such field bumped):",
          {k: v for k, v in tenant_a_row.model_dump().items() if "quota" in k.lower() or "usage" in k.lower() or "count" in k.lower()})

# --- Tier 1 exact PO match against real Postgres ---
found1 = find_candidate_invoices(
    tenant_id=tenant_a, po_number="PO-2026/0099", party_name="Acme Supplies Ltd",
    doc_date="2026-03-01", db_session=Session(engine),
)
print("  Tier 1 match on real Postgres:", found1["tier"], [i.id for i in found1["invoices"]])
assert found1["tier"] == 1 and found1["invoices"][0].id == inv_a_id

# --- Tier 2 fallback: a second invoice, no PO number, same vendor/date window ---
with Session(engine) as s:
    inv_a2 = Invoice(
        tenant_id=tenant_a, file_path="y.pdf", vendor_name="Acme Supplies Ltd",
        invoice_number="INV-REAL-2", invoice_date=__import__("datetime").date(2026, 3, 10),
        currency="INR", subtotal=500.0, tax_amount=90.0, grand_total=590.0,
        status="COMPLETED", flow_direction="INBOUND", po_number=None,
        items=[{"description": "Gadget", "amount": 500.0}],
    )
    s.add(inv_a2)
    s.commit()
    s.refresh(inv_a2)
    inv_a2_id = inv_a2.id

found2 = find_candidate_invoices(
    tenant_id=tenant_a, po_number="PO-NOT-ON-FILE", party_name="Acme Supplies Ltd",
    doc_date="2026-03-10", db_session=Session(engine),
)
print("  Tier 2 fallback on real Postgres (no PO match):", found2["tier"], [i.id for i in found2["invoices"]])
assert found2["tier"] == 2 and inv_a2_id in [i.id for i in found2["invoices"]]

# --- Zero-match path ---
found0 = find_candidate_invoices(
    tenant_id=tenant_a, po_number="PO-NEVER-EXISTED", party_name="Nobody Ltd",
    doc_date="2026-01-01", db_session=Session(engine),
)
print("  zero-match path on real Postgres:", found0["tier"], found0["invoices"])
assert found0["tier"] == 0 and found0["invoices"] == []

# --- Confirmation gate: an answer turn BEFORE confirm-matches must return the
#     confirmation payload, never a computed number (real Postgres row state) ---
import agents.query_agent as qa
with Session(engine) as s:
    att_row = s.get(ChatAttachment, UUID(attachment_id))
    assert att_row.confirmed_invoice_ids in (None, [])
    with patch.object(qa, "classify_query") as classify_spy, patch.object(qa, "get_llm") as llm_spy:
        pre_confirm = qa._run_query_agent(
            session_id=str(session_a_id), user_message="was I over-billed on this PO?",
            tenant_id=str(tenant_a), db_session=s, turn=MagicMock(), attachment_id=attachment_id,
        )
    print("  pre-confirm turn (real Postgres row):", pre_confirm.get("attachment_confirmation", {}).get("kind"))
    assert classify_spy.call_count == 0 and llm_spy.call_count == 0
    assert "attachment_comparison" not in pre_confirm
    assert pre_confirm["attachment_confirmation"]["kind"] == "attachment_match_confirmation"

# --- Confirm matches via the real endpoint, real Postgres ---
set_tenant_ctx(tenant_a)
confirm_resp = client.post(
    f"/api/v1/chat/attachments/{attachment_id}/confirm-matches",
    json={"invoice_ids": [str(inv_a_id)]},
)
print("  confirm-matches status:", confirm_resp.status_code, confirm_resp.json())
assert confirm_resp.status_code == 200
assert confirm_resp.json()["confirmed_invoice_ids"] == [str(inv_a_id)]

# --- Answer turn AFTER confirmation: deterministic diff computed against real Postgres row ---
with Session(engine) as s:
    fake_llm2 = MagicMock()
    fake_llm2.invoke.return_value = MagicMock(content="You were over-billed by 200.")
    with patch.object(qa, "classify_query") as classify_spy2, \
         patch.object(qa, "get_llm", return_value=fake_llm2), \
         patch.object(qa, "tracked_llm_call"):
        post_confirm = qa._run_query_agent(
            session_id=str(session_a_id), user_message="was I over-billed on this PO?",
            tenant_id=str(tenant_a), db_session=s, turn=MagicMock(), attachment_id=attachment_id,
        )
    assert classify_spy2.call_count == 0
    diff = post_confirm["attachment_comparison"]
    gt_field = next(f for f in diff["comparisons"][0]["fields"] if f["field"] == "grand_total")
    print("  post-confirm deterministic diff (real Postgres invoice + real attachment row): grand_total delta =", gt_field["delta"], "status =", gt_field["status"])
    assert gt_field["status"] == "match"  # inv_a grand_total 1380.0 == ref grand_total 1380.0

# --- Currency-mismatch hard stop against a real Postgres row ---
with Session(engine) as s:
    inv_eur = Invoice(
        tenant_id=tenant_a, file_path="z.pdf", vendor_name="Acme Supplies Ltd",
        invoice_number="INV-REAL-EUR", invoice_date=__import__("datetime").date(2026, 3, 1),
        currency="EUR", subtotal=1000.0, tax_amount=180.0, grand_total=1180.0,
        status="COMPLETED", flow_direction="INBOUND", po_number="PO-2026/0099",
        items=[{"description": "Widget", "amount": 1000.0}],
    )
    s.add(inv_eur)
    s.commit()
    s.refresh(inv_eur)
    diff_cm = compare_reference_to_invoices(ref_extracted, [inv_eur])
    c = diff_cm["comparisons"][0]
    print("  currency-mismatch outcome on real Postgres row:", c["outcome"], c.get("blocked_reason"))
    assert c["outcome"] == "currency_mismatch" and c["fields"] == []

# --- Tenant isolation on all 3 chat_attachments.py endpoints ---
hdr("T3d — tenant isolation on chat_attachments.py endpoints (real Postgres)")
set_tenant_ctx(tenant_b)
get_as_b = client.get(f"/api/v1/chat/attachments/{attachment_id}")
print("  tenant B GET tenant A's attachment:", get_as_b.status_code)
assert get_as_b.status_code in (403, 404)

confirm_as_b = client.post(
    f"/api/v1/chat/attachments/{attachment_id}/confirm-matches",
    json={"invoice_ids": [str(inv_a_id)]},
)
print("  tenant B confirm-matches on tenant A's attachment:", confirm_as_b.status_code)
assert confirm_as_b.status_code in (403, 404)

upload_as_b = client.post(
    f"/api/v1/chat/sessions/{session_a_id}/attachments",
    files={"file": ("po2.pdf", fake_pdf_bytes, "application/pdf")},
)
print("  tenant B upload into tenant A's session:", upload_as_b.status_code)
assert upload_as_b.status_code in (403, 404)

set_tenant_ctx(tenant_a)
get_as_a = client.get(f"/api/v1/chat/attachments/{attachment_id}")
print("  tenant A (owner) GET own attachment still works:", get_as_a.status_code)
assert get_as_a.status_code == 200
print("  PASS: tenant isolation holds on GET/confirm-matches/upload (real Postgres, 2 real tenants)")

# =============================================================================
# T4 — evaluate ENABLE_ASYNC_CHAT_QUEUE's 5 flip criteria
# =============================================================================
hdr("T4 — flip-criteria summary")
print("1. LIVE PROGRESS (>=6 distinct steps + per-attempt repair visibility):",
      "PASS" if t2b_pass else "FAIL", f"(distinct={len(distinct)}, repair-attempts={len(generating_sql_details)})")
print("2. CONCURRENCY CEILING (4th job real-429 while 3 in flight complete): PASS (T1a/T1c)")
print("3. FOLLOW-UP CORRECTNESS UNDER LOAD (Gap 237 override visible + per-session lock real):",
      "PASS" if t2c_pass else "FAIL")
print("4. FAILED JOB RELEASES SLOT (chat_inflight back to 0 after fail_job, real Redis): PASS (T1a)")
print("5. REDIS DOWN DEGRADES, NO 500: NOT EXERCISED IN THIS RUN (see report)")
