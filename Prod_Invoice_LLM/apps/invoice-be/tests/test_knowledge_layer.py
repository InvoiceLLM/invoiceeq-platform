"""Feature 30 task 30.7 — the knowledge layer and glossary-aware narration.

Verification plan 30.7: "`lookup_glossary('total')` -> `grand_total`; another
tenant's collection not readable."

Chroma, not Postgres, is the store here, and `MOCK_EMBEDDINGS=true` keeps the
embedding model out of it — the behaviour under test is collection scoping and
metadata filtering, neither of which depends on real vectors. The one place a
real distance would matter (`lookup_rule`'s ranking) is asserted on WHICH cards
come back and on their metadata, never on an ordering that mock embeddings
cannot produce meaningfully.
"""
import os
from uuid import uuid4

import pytest

os.environ.setdefault("MOCK_EMBEDDINGS", "true")

from services import knowledge as kn  # noqa: E402


@pytest.fixture(name="flag_on")
def flag_on_fixture(monkeypatch):
    from config import get_settings

    monkeypatch.setattr(get_settings(), "ENABLE_KNOWLEDGE_LAYER", True, raising=False)
    yield


@pytest.fixture(name="tenants")
def tenants_fixture():
    a, b = uuid4(), uuid4()
    yield str(a), str(b)
    for t in (a, b):
        kn.delete_knowledge(str(t))


def _rule(term_id, region, doc_types, url="https://cbic-gst.gov.in/example"):
    return kn.KnowledgeDoc(
        doc_id=kn.make_doc_id(kn.KIND_RULE, term_id),
        kind=kn.KIND_RULE,
        title=f"Rule {term_id}",
        body="A credit note must reference the original invoice number.",
        region=region,
        source_url=url,
        applies_to_doc_types=doc_types,
        effective_from="2026-01-01",
        review_at="2026-12-31",
    )


# --- the flag --------------------------------------------------------------


def test_everything_is_inert_with_the_flag_off(tenants):
    tenant_a, _ = tenants
    kn.seed_glossary([{"term": "total", "canonical": "grand_total"}], tenant_a)
    assert kn.lookup_glossary("total", tenant_a) is None
    assert kn.lookup_rule("credit note", tenant_a) == []
    assert kn.glossary_for_narration(tenant_a) == {}


# --- glossary --------------------------------------------------------------


def test_lookup_glossary_returns_the_tenants_own_word(tenants, flag_on):
    tenant_a, _ = tenants
    kn.seed_glossary(
        [
            {"term": "total", "canonical": "grand_total"},
            {"term": "bill", "canonical": "invoice"},
        ],
        tenant_a,
    )
    entry = kn.lookup_glossary("total", tenant_a)
    assert entry["canonical"] == "grand_total"
    assert kn.lookup_glossary("TOTAL", tenant_a)["canonical"] == "grand_total"
    assert kn.lookup_glossary("nonsense", tenant_a) is None


def test_one_tenants_glossary_is_not_readable_by_another(tenants, flag_on):
    tenant_a, tenant_b = tenants
    kn.seed_glossary([{"term": "total", "canonical": "grand_total"}], tenant_a)
    kn.seed_glossary([{"term": "total", "canonical": "subtotal"}], tenant_b)

    assert kn.lookup_glossary("total", tenant_a)["canonical"] == "grand_total"
    # B quotes ex-tax, so "total" means something else in their business.
    assert kn.lookup_glossary("total", tenant_b)["canonical"] == "subtotal"
    assert kn.knowledge_collection_name(tenant_a) != kn.knowledge_collection_name(tenant_b)


def test_re_seeding_a_term_replaces_it(tenants, flag_on):
    tenant_a, _ = tenants
    kn.seed_glossary([{"term": "total", "canonical": "grand_total"}], tenant_a)
    kn.seed_glossary([{"term": "total", "canonical": "net_total"}], tenant_a)
    assert kn.lookup_glossary("total", tenant_a)["canonical"] == "net_total"


def test_glossary_for_narration_returns_the_terms_the_bubble_uses(tenants, flag_on):
    tenant_a, _ = tenants
    kn.seed_glossary(
        [{"term": "total", "canonical": "grand_total"}, {"term": "vendor", "canonical": "supplier"}],
        tenant_a,
    )
    mapping = kn.glossary_for_narration(tenant_a)
    assert mapping["total"] == "grand_total"
    assert mapping["vendor"] == "supplier"


# --- rules -----------------------------------------------------------------


def test_a_rule_without_a_source_url_is_refused(tenants):
    """Hard rule 8, enforced at the index boundary rather than by convention."""
    bad = kn.KnowledgeDoc(
        doc_id="x", kind=kn.KIND_RULE, title="No source", body="Something plausible."
    )
    with pytest.raises(kn.KnowledgeError):
        kn.index_knowledge([bad], tenants[0])


def test_a_glossary_entry_needs_no_source(tenants):
    ok = kn.KnowledgeDoc(
        doc_id="y", kind=kn.KIND_GLOSSARY, title="total", body="grand_total", term="total"
    )
    assert kn.index_knowledge([ok], tenants[0]) == 1


def test_rules_are_filtered_by_region_and_document_type(tenants, flag_on):
    tenant_a, _ = tenants
    kn.index_knowledge(
        [
            _rule("in-credit-note", "IN", ("CREDIT_NOTE",)),
            _rule("eu-po", "EU", ("PURCHASE_ORDER",)),
        ],
        tenant_a,
    )

    india = kn.lookup_rule("credit note reference", tenant_a, region="IN")
    assert india and all(r["region"] == "IN" for r in india)
    assert all(r["source_url"] for r in india)

    wrong_type = kn.lookup_rule("credit note reference", tenant_a, region="IN", doc_type="PURCHASE_ORDER")
    assert wrong_type == []


def test_a_rule_always_carries_its_citation(tenants, flag_on):
    tenant_a, _ = tenants
    kn.index_knowledge([_rule("cited", "IN", ("CREDIT_NOTE",))], tenant_a)
    found = kn.lookup_rule("credit note", tenant_a, region="IN")
    assert found[0]["source_url"].startswith("https://")
    assert found[0]["effective_from"] == "2026-01-01"
    assert found[0]["review_at"] == "2026-12-31"


def test_a_glossary_term_is_never_returned_as_a_rule(tenants, flag_on):
    """The two kinds share a collection and must not share a lookup."""
    tenant_a, _ = tenants
    kn.seed_glossary([{"term": "credit note", "canonical": "adjustment"}], tenant_a)
    assert kn.lookup_rule("credit note", tenant_a) == []


# --- narration wiring ------------------------------------------------------


def test_the_narration_prompt_carries_the_glossary_and_says_it_is_not_figures(
    tenants, flag_on, monkeypatch
):
    """30.7's other half: the block's narration uses the tenant's vocabulary."""
    import json

    from services import attachment_insights as ai

    tenant_a, _ = tenants
    kn.seed_glossary([{"term": "total", "canonical": "order value"}], tenant_a)

    class _StubLLM:
        def __init__(self):
            self.messages = None

        def invoke(self, messages):
            self.messages = messages

            class _R:
                content = "This order value is 100.0 more than agreed."

            return _R()

    llm = _StubLLM()
    block = {
        "doc_type_label": "purchase order",
        "currency": "INR",
        "tenant_id": tenant_a,
        "findings": [{"title": "billed over", "impact_amount": 100.0, "confidence": "high"}],
        "figures": {"overbilled": 100.0},
        "checks_not_run": [],
        "verdict": "billed over.",
    }
    out = ai.narrate_insight_block(block, llm=llm)

    sent = json.loads(llm.messages[1]["content"])
    assert sent["glossary"]["total"] == "order value"
    assert "not figures" in sent["glossary_note"]
    assert out["gate"]["status"] == "ok"
