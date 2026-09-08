"""Feature 30 task 30.7 (was Feature 29 task 29.16) — the knowledge layer.

TWO KINDS OF KNOWLEDGE, ONE COLLECTION
--------------------------------------
`knowledge_{tenant_id}` holds short documents that are ABOUT the tenant's world
rather than about one invoice:

* **glossary** — what a word means HERE. One tenant's "total" is `grand_total`;
  another's is `subtotal` because they quote ex-tax. A narration that uses the
  tenant's own vocabulary is understood; one that uses ours has to be translated
  by the reader every time.
* **rule** — a regional compliance rule card (30.9 / 30.10), each carrying the
  `source_url` it was fetched from.

They share a collection because they are retrieved the same way and are the same
size; they are kept apart by a `kind` metadata field, and every lookup filters on
it. A glossary term must never be returned as a rule — the rule cards are cited
to the user with a source, and a glossary entry has no source to cite.

TENANT ISOLATION IS STRUCTURAL
------------------------------
One collection per tenant, exactly like `invoice_chunks_{tenant}` (Gap 55) and
`chat_docs_{tenant}` (Feature 26 E-2). A metadata filter that has to be
remembered at every call site cannot prevent a leak; a collection another
tenant's code cannot name can. Global rule cards (`tenant_id=None`) live in
`knowledge_global`, which is readable by everyone and writable only by the
seeding script.

FLAG
----
`ENABLE_KNOWLEDGE_LAYER` (default False) gates USE, not existence. Off,
`lookup_glossary()` and `lookup_rule()` return nothing and the narration runs
without a glossary — which is exactly today's behaviour.
"""
from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional, Sequence

logger = logging.getLogger(__name__)

KIND_GLOSSARY = "glossary"
KIND_RULE = "rule"

#: The collection every tenant-agnostic card lives in. Named, not implied, so a
#: reader can tell at a glance which lookups can cross tenants (only this one,
#: and only for rules).
GLOBAL_SCOPE = "global"


@dataclass
class KnowledgeDoc:
    """One indexed piece of knowledge.

    `source_url` is required for a rule and meaningless for a glossary term, and
    that asymmetry is enforced in `index_knowledge()`: a compliance rule the user
    is shown must be traceable to the page it came from (hard rule 8), while
    "what we call the total" is the tenant's own decision and has no source.
    """

    doc_id: str
    kind: str
    title: str
    body: str
    tenant_id: Optional[str] = None
    term: Optional[str] = None
    canonical: Optional[str] = None
    region: Optional[str] = None
    source_url: Optional[str] = None
    effective_from: Optional[str] = None
    review_at: Optional[str] = None
    applies_to_doc_types: Sequence[str] = field(default_factory=tuple)
    status: str = "active"

    def metadata(self) -> dict:
        """Chroma metadata must be flat scalars — lists are joined, not nested."""
        return {
            "kind": self.kind,
            "title": self.title,
            "tenant_id": self.tenant_id or GLOBAL_SCOPE,
            "term": (self.term or "").lower(),
            "canonical": self.canonical or "",
            "region": self.region or "",
            "source_url": self.source_url or "",
            "effective_from": self.effective_from or "",
            "review_at": self.review_at or "",
            "applies_to_doc_types": ",".join(self.applies_to_doc_types or ()),
            "status": self.status,
        }


class KnowledgeError(ValueError):
    """A document that cannot be indexed as asked (e.g. a rule with no source)."""


def knowledge_collection_name(tenant_id: Any = None) -> str:
    """`knowledge_{tenant}`, or `knowledge_global` for the shared rule cards."""
    return f"knowledge_{tenant_id}" if tenant_id else f"knowledge_{GLOBAL_SCOPE}"


def _collection(tenant_id: Any = None):
    from chroma_client import _collection_metadata, get_chroma_client

    client = get_chroma_client()
    return client.get_or_create_collection(
        name=knowledge_collection_name(tenant_id),
        # Gap 244's cosine pin, taken from the one place that owns it rather than
        # restated: a collection created on the default L2 space would make every
        # distance threshold in this repo meaningless for it.
        metadata=_collection_metadata(),
    )


def knowledge_enabled() -> bool:
    """Read at call time so a test's monkeypatch is seen."""
    try:
        from config import get_settings

        return bool(getattr(get_settings(), "ENABLE_KNOWLEDGE_LAYER", False))
    except Exception:  # pragma: no cover - defensive
        return False


def make_doc_id(kind: str, key: str, tenant_id: Any = None) -> str:
    """A stable id, so re-indexing the same term REPLACES it.

    Hashed rather than concatenated because a glossary term is free text and
    Chroma ids must be usable in a URL path.
    """
    raw = f"{tenant_id or GLOBAL_SCOPE}:{kind}:{key.lower().strip()}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def index_knowledge(docs: Sequence[KnowledgeDoc], tenant_id: Any = None) -> int:
    """Upsert knowledge documents. Returns how many were written.

    Refuses a rule without a `source_url` — hard rule 8: a compliance statement
    the user is shown must be traceable to the primary source it came from, and
    a card with no source is exactly the invented-rule failure the rule states.
    """
    if not docs:
        return 0
    for doc in docs:
        if doc.kind == KIND_RULE and not (doc.source_url or "").strip():
            raise KnowledgeError(
                f"Rule card {doc.doc_id!r} has no source_url. A rule shown to a user "
                "must cite the page it came from."
            )

    collection = _collection(tenant_id)
    collection.upsert(
        ids=[d.doc_id for d in docs],
        documents=[f"{d.title}\n\n{d.body}" for d in docs],
        metadatas=[d.metadata() for d in docs],
    )
    return len(docs)


def lookup_glossary(term: str, tenant_id: Any = None) -> Optional[dict]:
    """What this tenant calls `term`, or None.

    An EXACT metadata match on the normalised term, not a vector search. A
    glossary is a lookup table: "total" means what the tenant said it means, and
    a nearest-neighbour answer ("we found something a bit like 'total'") is worse
    than no answer, because the narration would then use a word the tenant never
    chose.
    """
    if not knowledge_enabled() or not term:
        return None
    try:
        collection = _collection(tenant_id)
        found = collection.get(
            where={"$and": [{"kind": {"$eq": KIND_GLOSSARY}}, {"term": {"$eq": term.lower().strip()}}]},
            limit=1,
        )
    except Exception as exc:
        logger.warning("Glossary lookup failed for %r: %s", term, exc)
        return None

    metadatas = (found or {}).get("metadatas") or []
    if not metadatas:
        return None
    meta = metadatas[0]
    return {
        "term": meta.get("term"),
        "canonical": meta.get("canonical"),
        "title": meta.get("title"),
        "body": ((found.get("documents") or [""])[0]),
    }


def glossary_for_narration(tenant_id: Any = None, terms: Sequence[str] = ()) -> dict:
    """`{term: canonical}` for the words a bubble is about to use.

    Passed into `narrate_insight_block()` so the model writes "what you call a
    bill" rather than "invoice". Returns `{}` when the flag is off, and `{}` is a
    complete answer — the narration is not degraded without a glossary, it is
    simply in our words rather than theirs.
    """
    if not knowledge_enabled():
        return {}
    out: dict = {}
    for term in terms or ("total", "invoice", "vendor", "due date"):
        entry = lookup_glossary(term, tenant_id)
        if entry and entry.get("canonical"):
            out[entry["term"]] = entry["canonical"]
    return out


def lookup_rule(
    query: str,
    tenant_id: Any = None,
    region: Optional[str] = None,
    doc_type: Optional[str] = None,
    k: int = 3,
) -> list:
    """Rule cards relevant to a question, filtered by region and document type.

    Searches the tenant's collection AND the global one: rule cards are published
    centrally (30.9 / 30.10) and a tenant may add its own. Every result carries
    its `source_url`, because a compliance statement without a citation is not
    something this product is willing to show.
    """
    if not knowledge_enabled() or not query:
        return []

    results: list = []
    for scope in (tenant_id, None):
        try:
            collection = _collection(scope)
            clauses: list = [{"kind": {"$eq": KIND_RULE}}]
            if region:
                clauses.append({"region": {"$eq": region}})
            where = {"$and": clauses} if len(clauses) > 1 else clauses[0]
            found = collection.query(query_texts=[query], n_results=k, where=where)
        except Exception as exc:
            logger.warning("Rule lookup failed in %s: %s", knowledge_collection_name(scope), exc)
            continue

        for i, doc in enumerate((found.get("documents") or [[]])[0]):
            meta = (found.get("metadatas") or [[]])[0][i] or {}
            applies = [t for t in (meta.get("applies_to_doc_types") or "").split(",") if t]
            if doc_type and applies and doc_type.upper() not in applies:
                continue
            results.append(
                {
                    "title": meta.get("title"),
                    "body": doc,
                    "region": meta.get("region"),
                    "source_url": meta.get("source_url"),
                    "effective_from": meta.get("effective_from"),
                    "review_at": meta.get("review_at"),
                    "applies_to_doc_types": applies,
                    "status": meta.get("status"),
                    "scope": meta.get("tenant_id"),
                    "distance": ((found.get("distances") or [[]])[0][i] if found.get("distances") else None),
                }
            )
        if scope is not None and tenant_id is None:
            break
    return results[:k]


def seed_glossary(entries: Sequence[dict], tenant_id: Any) -> int:
    """Index a tenant's glossary from `{term, canonical, note?}` mappings.

    Deliberately explicit rather than learned from usage: a glossary is a
    statement by the tenant about their own vocabulary, and inferring it from how
    they phrase questions would put words in their mouth.
    """
    docs = [
        KnowledgeDoc(
            doc_id=make_doc_id(KIND_GLOSSARY, entry["term"], tenant_id),
            kind=KIND_GLOSSARY,
            title=f"{entry['term']} = {entry['canonical']}",
            body=entry.get("note") or f"In this business, '{entry['term']}' means {entry['canonical']}.",
            tenant_id=str(tenant_id),
            term=entry["term"],
            canonical=entry["canonical"],
        )
        for entry in entries
    ]
    return index_knowledge(docs, tenant_id)


def delete_knowledge(tenant_id: Any) -> None:
    """Drop one tenant's knowledge collection (tenant deletion path)."""
    try:
        from chroma_client import get_chroma_client

        get_chroma_client().delete_collection(name=knowledge_collection_name(tenant_id))
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("Could not delete %s: %s", knowledge_collection_name(tenant_id), exc)
