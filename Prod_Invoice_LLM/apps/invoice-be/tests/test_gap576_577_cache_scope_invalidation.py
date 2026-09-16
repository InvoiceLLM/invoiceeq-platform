"""Regression test suite for BE Gap 576 (CH-9) and BE Gap 577 (CH-10).

BE Gap 576 (CH-9):
- The answer cache is restricted strictly to provably self-contained questions
  (Option b: no focus set on the session, no pronoun or demonstrative, no dependence
  on a prior turn; everything else is never cached).

BE Gap 577 (CH-10):
- Per-tenant data_version in Redis, bumped by any invoice state write (ingestion,
  status change, correction, resolve, deletion), instantly making older cached answers
  unreachable without expensive or blocking keys scans.
"""
import os
import sys
import json
import pytest
from uuid import uuid4
from unittest.mock import MagicMock, patch

os.environ.setdefault("MOCK_EMBEDDINGS", "true")
sys.modules.setdefault("sentence_transformers", MagicMock())

from sqlmodel import Session, SQLModel, create_engine
from models import ChatSession, ChatMessage
from agents import query_agent
from agents.query_agent import _is_provably_self_contained, _cache_key, get_cached_answer, set_cached_answer
from services.chat_cache import (
    get_tenant_data_version,
    bump_tenant_data_version,
    CHAT_DATA_VERSION_PREFIX,
    DEFAULT_DATA_VERSION,
)


@pytest.fixture(name="db_session")
def db_session_fixture():
    engine = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


class _InMemoryRedis:
    """Hermetic Redis fake for testing version bumping and cache key composition."""
    def __init__(self):
        self._store = {}

    def get(self, key):
        return self._store.get(key)

    def set(self, key, val, ex=None):
        self._store[key] = val
        return True

    def incr(self, key):
        cur = int(self._store.get(key, 0))
        cur += 1
        self._store[key] = str(cur)
        return cur


# ============================================================================
# BE Gap 576 (CH-9): Provably Self-Contained Query Recognition
# ============================================================================

PROVABLY_SELF_CONTAINED = [
    "what is our total spend this month?",
    "list all overdue invoices",
    "what did we pay acme last quarter?",
    "what is the total for invoice CMC-330217",
    "show spending by vendor for 2026",
]

NON_SELF_CONTAINED_PRONOUNS_DEMONSTRATIVES = [
    # Demonstratives
    "can you break this down?",
    "what about that invoice?",
    "list these bills",
    "show me those",
    # 3rd-person pronouns
    "when is it due?",
    "is it paid?",
    "why was it rejected?",
    "detail their payment status",
    "explain them",
    "what did they charge?",
    # Comparative / ordinal references
    "what about the second one",
    "and the other one?",
    "show the previous one",
    "compare with another one",
    "is the former approved?",
    # Conversational follow-up openings
    "what about acme?",
    "how about last year?",
    "and for march?",
    "why?",
    "tell me more",
    "more details",
]


@pytest.mark.parametrize("query", PROVABLY_SELF_CONTAINED)
def test_self_contained_queries_are_recognized(query):
    """Self-contained queries without pronouns, demonstratives, or ellipsis pass."""
    assert _is_provably_self_contained(query) is True, f"Failed for {query}"


@pytest.mark.parametrize("query", NON_SELF_CONTAINED_PRONOUNS_DEMONSTRATIVES)
def test_queries_with_pronouns_or_demonstratives_are_rejected(query):
    """Founder ruling 2026-09-16: questions with pronouns, demonstratives, or follow-up stems are never cached."""
    assert _is_provably_self_contained(query) is False, f"Expected non-self-contained for {query}"


def test_session_with_focus_is_never_cached(db_session):
    """If a session has active focus (e.g. Acme), queries in that session cannot be cached."""
    session_id = uuid4()
    chat_session = ChatSession(
        id=session_id,
        tenant_id=uuid4(),
        title="Acme Audit",
        focus={"vendor": "Acme Corporation"},
    )
    db_session.add(chat_session)
    db_session.commit()

    # Even a question without pronouns is context-dependent when session has focus
    query = "what is the total outstanding?"
    assert _is_provably_self_contained(query, session_id=session_id, db_session=db_session) is False


def test_session_with_prior_turns_is_never_cached(db_session):
    """If a session already has prior assistant turns, questions may depend on prior turns and are not cached."""
    session_id = uuid4()
    chat_session = ChatSession(
        id=session_id,
        tenant_id=uuid4(),
        title="Investigation",
        focus={},
    )
    db_session.add(chat_session)
    db_session.commit()

    # Turn 1: Assistant answered
    prior_msg = ChatMessage(
        id=uuid4(),
        session_id=session_id,
        role="assistant",
        content="Here are the Acme invoices.",
    )
    db_session.add(prior_msg)
    db_session.commit()

    # Turn 2: Follow-up question
    query = "what is the total outstanding?"
    assert _is_provably_self_contained(query, session_id=session_id, db_session=db_session) is False


def test_fresh_session_without_focus_or_prior_turns_is_cacheable(db_session):
    """Turn 1 in a new session with no focus and no prior turns is provably self-contained."""
    session_id = uuid4()
    chat_session = ChatSession(
        id=session_id,
        tenant_id=uuid4(),
        title="New Chat",
        focus={},
    )
    db_session.add(chat_session)
    db_session.commit()

    query = "what is our total spend this month?"
    assert _is_provably_self_contained(query, session_id=session_id, db_session=db_session) is True


# ============================================================================
# BE Gap 577 (CH-10): Data Version Cache Invalidation
# ============================================================================

def test_cache_key_incorporates_data_version():
    """_cache_key mixes :v=<version> when provided."""
    key_v1 = _cache_key("tenant-1", "list invoices", rules_version="r1", data_version=1)
    key_v2 = _cache_key("tenant-1", "list invoices", rules_version="r1", data_version=2)
    key_plain = _cache_key("tenant-1", "list invoices", rules_version="r1")

    assert key_v1 == "chat_answer_cache:tenant-1:list invoices:v=1:rules=r1"
    assert key_v2 == "chat_answer_cache:tenant-1:list invoices:v=2:rules=r1"
    assert key_plain == "chat_answer_cache:tenant-1:list invoices:rules=r1"
    assert key_v1 != key_v2


def test_bump_tenant_data_version_increments_and_invalidates():
    """Bumping data_version moves version from 1 to 2, rendering v1 keys unreachable."""
    fake_redis = _InMemoryRedis()
    tenant_id = "tenant-test-123"

    # Default is 1
    assert get_tenant_data_version(tenant_id, client=fake_redis) == 1

    # Write answer at v1
    v1 = get_tenant_data_version(tenant_id, client=fake_redis)
    k1 = _cache_key(tenant_id, "list all overdue invoices", data_version=v1)
    fake_redis.set(k1, json.dumps({"content": "Invoice A is overdue."}))

    # Cached answer exists at v1
    assert fake_redis.get(k1) is not None

    # Invoice is paid / uploaded / approved -> data version bumped
    new_v = bump_tenant_data_version(tenant_id, client=fake_redis)
    assert new_v == 2
    assert get_tenant_data_version(tenant_id, client=fake_redis) == 2

    # Next lookup reads at v2 -> cache miss!
    k2 = _cache_key(tenant_id, "list all overdue invoices", data_version=new_v)
    assert fake_redis.get(k2) is None


def test_tenant_isolation_in_data_versions():
    """Bumping data version for Tenant A leaves Tenant B unaffected."""
    fake_redis = _InMemoryRedis()
    tenant_a = "tenant-A"
    tenant_b = "tenant-B"

    bump_tenant_data_version(tenant_a, client=fake_redis)
    assert get_tenant_data_version(tenant_a, client=fake_redis) == 2
    bump_tenant_data_version(tenant_a, client=fake_redis)
    assert get_tenant_data_version(tenant_a, client=fake_redis) == 3

    assert get_tenant_data_version(tenant_b, client=fake_redis) == DEFAULT_DATA_VERSION


def test_get_and_set_cached_answer_uses_current_data_version():
    """get_cached_answer and set_cached_answer automatically bind to live tenant data_version."""
    fake_redis = _InMemoryRedis()
    tenant_id = "tenant-abc"

    with patch.object(query_agent, "_get_redis_client", return_value=fake_redis), \
         patch("services.chat_cache._get_redis_client", return_value=fake_redis):

        # 1. Store answer at current data version (default 1)
        set_cached_answer(tenant_id, "list overdue invoices", {"result": "5 invoices"})

        # 2. Lookup finds it
        ans = get_cached_answer(tenant_id, "list overdue invoices")
        assert ans == {"result": "5 invoices"}

        # 3. Bump version (e.g. invoice approved or deleted)
        bump_tenant_data_version(tenant_id, client=fake_redis)

        # 4. Lookup now misses because key version bumped from v1 to v2
        ans_after_bump = get_cached_answer(tenant_id, "list overdue invoices")
        assert ans_after_bump is None


# ============================================================================
# BE Gaps 576/577 end to end: a real chat turn through `run_query_agent`
# ============================================================================
# The tests above check the helpers one at a time, which is how the write-side
# bug got past them: `update_session_focus()` runs before the cache write, so a
# check made at write time saw the focus this very turn had just set and refused
# every answer that found an invoice. Only a whole turn shows that.

from contextlib import ExitStack  # noqa: E402

from dependencies import MOCK_TENANT_ID  # noqa: E402
from models import Invoice  # noqa: E402

_TENANT = str(MOCK_TENANT_ID)
_QUESTION = "list all overdue invoices"


class _ScriptedLLM:
    """Every deployment a SQL turn uses. With `allowed=False` any call fails the
    test, which is how a cache hit is proven rather than assumed."""

    def __init__(self, allowed=True, summary="There are 2 overdue invoices."):
        self.allowed = allowed
        self.summary = summary
        # Counted before refusing: the agent catches model errors and carries on,
        # so "SQL never ran" alone would also be true of a turn that just failed.
        self.attempts = 0

    def _use(self):
        self.attempts += 1
        if not self.allowed:
            raise AssertionError("the model was called -- this turn should have been served from cache")

    def with_structured_output(self, schema):
        outer = self

        class _Structured:
            def invoke(self, prompt):
                outer._use()
                return MagicMock(sql=f"SELECT id FROM invoice WHERE tenant_id = '{_TENANT}'")

        return _Structured()

    def invoke(self, prompt):
        self._use()
        return MagicMock(content=self.summary)


def _new_session(db_session, **kwargs):
    chat_session = ChatSession(id=uuid4(), tenant_id=MOCK_TENANT_ID, title="t", **kwargs)
    db_session.add(chat_session)
    db_session.commit()
    return chat_session.id


def _turn(db_session, fake_redis, session_id, llm, *, ids=None, on_execute=None):
    """Run one SQL turn with the model and the database query stubbed.
    Returns (result, number of times SQL was executed)."""
    ids = ids or [str(uuid4()), str(uuid4())]
    executed = []

    def _fake_execute(sql, tenant_id, db_sess, snapshot=None):
        executed.append(sql)
        if on_execute is not None:
            on_execute()
        if snapshot is not None:
            snapshot.extend(ids)
        return "\n\nid | currency\n--- | ---\n" + "\n".join(f"{i} | USD" for i in ids)

    with ExitStack() as stack:
        for p in (
            patch.object(query_agent, "_get_redis_client", return_value=fake_redis),
            patch("services.chat_cache._get_redis_client", return_value=fake_redis),
            patch("agents.query_agent.classify_query", return_value="SQL"),
            patch("agents.query_agent.query_invoice_chunks", return_value=[]),
            patch("agents.query_agent.get_llm", return_value=llm),
            patch("agents.query_agent.build_llm", return_value=llm),
            patch("agents.query_agent._get_tenant_stats_summary", return_value=""),
            patch("agents.query_agent.execute_generated_sql", side_effect=_fake_execute),
        ):
            stack.enter_context(p)
        result = query_agent.run_query_agent(str(session_id), _QUESTION, _TENANT, db_session)
    return result, len(executed)


def _answer_keys(fake_redis):
    return [k for k in fake_redis._store if k.startswith("chat_answer_cache:")]


def test_a_first_turn_that_finds_invoices_is_cached_and_served_to_the_next_session(db_session):
    fake_redis = _InMemoryRedis()
    first_session = _new_session(db_session)

    first, executed = _turn(db_session, fake_redis, first_session, _ScriptedLLM())

    assert executed == 1
    assert first["result_invoice_ids"], "sanity: the turn must find invoices"
    db_session.expire_all()
    assert db_session.get(ChatSession, first_session).focus, (
        "sanity: the turn set a focus before writing -- the exact state that used to block the write"
    )
    assert len(_answer_keys(fake_redis)) == 1, "the answer was not written to the cache"

    no_model = _ScriptedLLM(allowed=False)
    second, executed = _turn(db_session, fake_redis, _new_session(db_session), no_model)

    assert (executed, no_model.attempts) == (0, 0)
    assert second["content"] == first["content"]


def test_an_invoice_write_after_caching_makes_the_next_session_recompute(db_session):
    fake_redis = _InMemoryRedis()
    _turn(db_session, fake_redis, _new_session(db_session), _ScriptedLLM())
    assert len(_answer_keys(fake_redis)) == 1

    bump_tenant_data_version(MOCK_TENANT_ID, client=fake_redis)  # e.g. an invoice was approved

    _, executed = _turn(db_session, fake_redis, _new_session(db_session), _ScriptedLLM())
    assert executed == 1, "a pre-approval answer was served after the approval"


def test_an_invoice_write_during_the_turn_leaves_that_turns_answer_unreachable(db_session):
    """The turn reads its data version before touching data and writes under that
    same version. Read again at write time, the pre-approval answer would be filed
    under the post-approval key and served to everyone for the next hour."""
    fake_redis = _InMemoryRedis()
    _turn(
        db_session,
        fake_redis,
        _new_session(db_session),
        _ScriptedLLM(),
        on_execute=lambda: bump_tenant_data_version(MOCK_TENANT_ID, client=fake_redis),
    )
    assert len(_answer_keys(fake_redis)) == 1, "sanity: the answer was written"

    _, executed = _turn(db_session, fake_redis, _new_session(db_session), _ScriptedLLM())
    assert executed == 1, "an answer computed before a mid-turn write was served after it"


def test_a_question_in_a_session_with_a_prior_turn_is_neither_served_nor_stored(db_session):
    fake_redis = _InMemoryRedis()
    session_id = _new_session(db_session)
    db_session.add(
        ChatMessage(id=uuid4(), session_id=session_id, role="assistant", content="Here are the Acme invoices.")
    )
    db_session.commit()

    poisoned = {"content": "Another session's answer.", "generated_sql": None, "citations": [], "result_invoice_ids": []}
    with patch.object(query_agent, "_get_redis_client", return_value=fake_redis), \
         patch("services.chat_cache._get_redis_client", return_value=fake_redis):
        set_cached_answer(_TENANT, _QUESTION, poisoned, query_agent.chat_rules_version(_TENANT, db_session))
    assert len(_answer_keys(fake_redis)) == 1

    result, executed = _turn(db_session, fake_redis, session_id, _ScriptedLLM())

    assert executed == 1
    assert result["content"] != poisoned["content"]
    assert len(_answer_keys(fake_redis)) == 1, "a follow-up's answer was written to the shared cache"


def test_a_cached_answer_is_not_served_after_the_utc_day_changes(db_session):
    """"Overdue invoices" or "spend this month" computed at 23:50 is a different
    answer at 00:10."""
    fake_redis = _InMemoryRedis()
    no_model = _ScriptedLLM(allowed=False)
    with patch.object(query_agent, "_utc_today", return_value="2026-09-30"):
        first, _ = _turn(db_session, fake_redis, _new_session(db_session), _ScriptedLLM())
        same_day, executed = _turn(db_session, fake_redis, _new_session(db_session), no_model)
    assert (executed, no_model.attempts) == (0, 0)
    assert same_day["content"] == first["content"]

    with patch.object(query_agent, "_utc_today", return_value="2026-10-01"):
        _, next_day = _turn(db_session, fake_redis, _new_session(db_session), _ScriptedLLM())
    assert next_day == 1


def _seed_invoice(db_session, **kwargs):
    fields = dict(
        id=uuid4(), tenant_id=MOCK_TENANT_ID, file_path="mock/inv.pdf",
        flow_direction="INBOUND", status="PROCESSING", currency="USD",
    )
    fields.update(kwargs)
    invoice = Invoice(**fields)
    db_session.add(invoice)
    db_session.commit()
    return invoice


def test_extraction_failure_and_requeue_invalidate_only_after_their_commit(db_session):
    """Both status writes in `services/invoice_reconciliation.py` bump the version,
    and after the commit: bumping first would let a turn that starts in between
    read the old row and file it under the new version."""
    from services import invoice_reconciliation

    bumps = []

    def _record_bump(tenant_id):
        bumps.append((str(tenant_id), not db_session.dirty))

    invoice = _seed_invoice(db_session)
    with patch("services.chat_cache.bump_tenant_data_version", side_effect=_record_bump):
        invoice_reconciliation.mark_invoice_failed(db_session, invoice, reason="OCR timed out")
        assert invoice.status == invoice_reconciliation.FAILED_STATUS

        with patch.object(invoice_reconciliation, "_enqueue", return_value=True):
            assert invoice_reconciliation.force_requeue(db_session, invoice.id) is True
        assert invoice.status == "PROCESSING"

    assert bumps == [(_TENANT, True), (_TENANT, True)]
