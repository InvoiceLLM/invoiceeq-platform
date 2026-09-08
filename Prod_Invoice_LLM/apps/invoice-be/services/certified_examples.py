"""Feature 30 task 30.8 (was Feature 29 task 29.15) — certified question/SQL examples.

WHAT THEY ARE FOR
-----------------
Two consumers, and they want the same rows for different reasons:

* the **SQL prompt** replaces its static examples tail with the closest certified
  examples, so the model's few-shot context is questions this system has actually
  answered correctly rather than ones somebody imagined in a docstring;
* the **suggested-questions card** offers three questions that fit the document
  in front of the user ("what else have we bought on this PO?"), which is the
  cheapest way to teach someone what the chat can do.

THE CERTIFICATION GATE
----------------------
`retrieve_examples()` returns ONLY rows with `certified = true`. Nothing else in
this module can bypass that, and the flywheel (30.13) writes rows uncertified.
An uncertified example is a proposal about what might be right; putting one into
the prompt is how a wrong answer becomes the house style, permanently and
invisibly, because every later answer is then shaped by it.

RETRIEVAL IS NOT A MODEL CALL
-----------------------------
Similarity is token overlap (`difflib`), not embeddings. Three reasons: the
corpus is small (tens of rows, not thousands), the questions are short and
literal, and a retrieval step that needs the embedding service turns "suggest
three questions" into a network dependency on the bubble's critical path.
"""
from __future__ import annotations

import difflib
import logging
import re
from datetime import datetime
from typing import Any, Optional, Sequence

logger = logging.getLogger(__name__)

#: Below this overlap two questions are not about the same thing. Deliberately
#: low: a miss returns fewer examples, which is a smaller prompt, while a false
#: hit puts an unrelated query shape in front of the model.
EXAMPLE_MATCH_FLOOR = 0.35

_WORD = re.compile(r"[a-z0-9]+")


def _tokens(text: str) -> list:
    return _WORD.findall((text or "").lower())


#: Words that carry no subject matter. Removed before comparison because they
#: are what make two unrelated questions look similar: "how much did we spend on
#: packaging" and "who signed the contract" share `did/we/the` and nothing else,
#: and a character-level ratio over the raw strings scores that above 0.4.
_STOPWORDS = frozenset(
    {
        "a", "an", "and", "any", "are", "as", "at", "be", "by", "did", "do", "does",
        "for", "from", "has", "have", "how", "in", "is", "it", "last", "me", "much",
        "of", "on", "or", "our", "show", "that", "the", "their", "there", "this",
        "to", "us", "was", "we", "were", "what", "when", "which", "who", "with",
        "year", "list", "give",
    }
)


def _content_tokens(text: str) -> set:
    return {t for t in _tokens(text) if t not in _STOPWORDS}


def _similarity(a: str, b: str) -> float:
    """Jaccard overlap of the content words, with a character-level tiebreak.

    Token overlap rather than `SequenceMatcher` over the raw strings: the
    questions here are short, and a character ratio scores two questions that
    merely share function words far too highly. When the content words agree
    exactly, the character ratio is used only to order equally-good matches --
    it can never lift a pair over the floor on its own.
    """
    tokens_a, tokens_b = _content_tokens(a), _content_tokens(b)
    if not tokens_a or not tokens_b:
        return 0.0
    overlap = len(tokens_a & tokens_b) / len(tokens_a | tokens_b)
    if overlap == 0:
        return 0.0
    character = difflib.SequenceMatcher(None, " ".join(sorted(tokens_a)), " ".join(sorted(tokens_b))).ratio()
    return round(overlap + (character * 0.001), 6)


def certified_examples_enabled() -> bool:
    """`ENABLE_CERTIFIED_EXAMPLES` (Feature 29 capability flag, default False)."""
    try:
        from config import get_settings

        return bool(getattr(get_settings(), "ENABLE_CERTIFIED_EXAMPLES", False))
    except Exception:  # pragma: no cover - defensive
        return False


def certify_example(
    question: str,
    sql: str,
    db_session: Any,
    tenant_id: Any = None,
    doc_type: str | None = None,
    metric: str | None = None,
    certified_by: str | None = None,
    source_correction_id: Any = None,
    certified: bool = True,
) -> Any:
    """Write an example. Certified by default because the usual caller is a human.

    `certified=False` is what the flywheel passes: a proposal that a person has
    not yet endorsed. The parameter exists rather than a second function so both
    paths write the same row through the same validation.
    """
    from models import CertifiedSqlExample

    if not (question or "").strip() or not (sql or "").strip():
        raise ValueError("A certified example needs both a question and its SQL.")

    row = CertifiedSqlExample(
        tenant_id=tenant_id,
        question=question.strip()[:2000],
        sql=sql.strip(),
        doc_type=(doc_type or None),
        metric=(metric or None),
        certified=bool(certified),
        certified_by=certified_by if certified else None,
        certified_at=datetime.utcnow() if certified else None,
        source_correction_id=source_correction_id,
    )
    db_session.add(row)
    db_session.commit()
    db_session.refresh(row)
    return row


def retrieve_examples(
    question: str,
    db_session: Any,
    tenant_id: Any = None,
    k: int = 5,
    doc_type: str | None = None,
) -> list:
    """The `k` closest CERTIFIED examples, tenant's own first, then global.

    Returns `[]` when the flag is off — the SQL prompt then keeps its static
    tail, which is the shipped behaviour and not a degradation.
    """
    if not certified_examples_enabled() or not question:
        return []

    from sqlmodel import or_, select

    from models import CertifiedSqlExample

    try:
        stmt = select(CertifiedSqlExample).where(CertifiedSqlExample.certified == True)  # noqa: E712
        stmt = stmt.where(
            or_(
                CertifiedSqlExample.tenant_id == tenant_id,
                CertifiedSqlExample.tenant_id == None,  # noqa: E711
            )
        )
        if doc_type:
            stmt = stmt.where(
                or_(
                    CertifiedSqlExample.doc_type == doc_type,
                    CertifiedSqlExample.doc_type == None,  # noqa: E711
                )
            )
        rows = db_session.exec(stmt).all()
    except Exception as exc:
        logger.warning("Certified example retrieval failed: %s", exc)
        try:
            db_session.rollback()
        except Exception:
            pass
        return []

    scored = [(row, _similarity(question, row.question)) for row in rows]
    scored = [(r, s) for r, s in scored if s >= EXAMPLE_MATCH_FLOOR]
    # The tenant's own example wins a tie with a global one: it was certified
    # against their data.
    scored.sort(key=lambda pair: (pair[1], pair[0].tenant_id is not None), reverse=True)
    return [
        {
            "id": str(r.id),
            "question": r.question,
            "sql": r.sql,
            "doc_type": r.doc_type,
            "metric": r.metric,
            "scope": "tenant" if r.tenant_id else "global",
            "score": round(s, 3),
        }
        for r, s in scored[:k]
    ]


def suggested_questions(
    doc_type: str, db_session: Any, tenant_id: Any = None, k: int = 3
) -> list:
    """The three click-questions the bubble offers for this document type.

    Certified rows for this type first; if the tenant has none, the built-in
    starters below. The starters are questions, not answers — they carry no
    figures and cannot be wrong, which is why they are allowed to exist as
    constants while every FIGURE in this feature must come from a computation.
    """
    if certified_examples_enabled():
        from sqlmodel import or_, select

        from models import CertifiedSqlExample

        try:
            rows = db_session.exec(
                select(CertifiedSqlExample)
                .where(
                    CertifiedSqlExample.certified == True,  # noqa: E712
                    CertifiedSqlExample.doc_type == doc_type,
                )
                .where(
                    or_(
                        CertifiedSqlExample.tenant_id == tenant_id,
                        CertifiedSqlExample.tenant_id == None,  # noqa: E711
                    )
                )
                .limit(k)
            ).all()
        except Exception as exc:
            logger.warning("Suggested-question lookup failed: %s", exc)
            try:
                db_session.rollback()
            except Exception:
                pass
            rows = []
        if rows:
            return [
                {"question": r.question, "source": "certified", "doc_type": r.doc_type}
                for r in rows[:k]
            ]

    return [
        {"question": q, "source": "starter", "doc_type": doc_type}
        for q in STARTER_QUESTIONS.get(doc_type, STARTER_QUESTIONS["_default"])[:k]
    ]


#: Built-in starters per document type. Plain words (§8.2), and every one is
#: answerable by the existing chat — a suggested question the product cannot
#: answer is worse than no suggestion.
STARTER_QUESTIONS: dict = {
    "PURCHASE_ORDER": [
        "What else have we been billed against this order?",
        "Has this supplier billed us over an order before?",
        "What is still to come on this order?",
    ],
    "ORDER_CONFIRMATION": [
        "What else have we been billed against this order?",
        "When is this likely to be payable?",
        "What is still to come on this order?",
    ],
    "QUOTATION": [
        "How does this quote compare with what we have paid before?",
        "Have we ordered from this supplier since this quote?",
        "What did we spend with this supplier last year?",
    ],
    "CONTRACT": [
        "Do this supplier's invoices follow these payment terms?",
        "What have we spent with this supplier under this contract?",
        "When are their bills usually due?",
    ],
    "DELIVERY_NOTE": [
        "Have we been billed for this delivery?",
        "Has this supplier short-delivered before?",
        "What is still outstanding on this order?",
    ],
    "GRN": [
        "Have we been billed for this delivery?",
        "Has this supplier short-delivered before?",
        "What is still outstanding on this order?",
    ],
    "CREDIT_NOTE": [
        "What do we owe this supplier now?",
        "Which bill does this credit apply to?",
        "What else is overdue with this supplier?",
    ],
    "DEBIT_NOTE": [
        "What do we owe this supplier now?",
        "Which bill does this note adjust?",
        "What else is overdue with this supplier?",
    ],
    "REMITTANCE_ADVICE": [
        "Which bills does this payment settle?",
        "Is anything still unpaid from this customer?",
        "What is overdue with this customer?",
    ],
    "STATEMENT_OF_ACCOUNT": [
        "Which payments on this statement are not in our records?",
        "What is due in the next 30 days?",
        "Have we paid any bill twice?",
    ],
    "_default": [
        "What is overdue right now?",
        "What did we spend with this supplier this year?",
        "Which bills are waiting on approval?",
    ],
}


def seed_from_golden(db_session: Any, golden_path: str | None = None, certified_by: str = "seed") -> int:
    """Seed global examples from the agent-eval golden file. Returns the count.

    The golden cases are questions this repo already asserts correct answers for,
    which makes them the only question set in the codebase with a defensible
    claim to being certified. Cases with no `expected_sql` are skipped rather
    than guessed at.
    """
    import json
    import os

    from sqlmodel import select

    from models import CertifiedSqlExample

    path = golden_path or os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "benchmarks",
        "agent_eval_golden_facts.json",
    )
    try:
        with open(path, "r", encoding="utf-8") as fh:
            payload = json.load(fh)
    except Exception as exc:
        logger.warning("Could not read golden file %s: %s", path, exc)
        return 0

    cases = payload if isinstance(payload, list) else payload.get("cases") or []
    written = 0
    for case in cases:
        if not isinstance(case, dict):
            continue
        question = case.get("question") or case.get("query")
        sql = case.get("expected_sql") or case.get("sql")
        if not question or not sql:
            continue
        existing = db_session.exec(
            select(CertifiedSqlExample).where(
                CertifiedSqlExample.tenant_id == None,  # noqa: E711
                CertifiedSqlExample.question == question,
            )
        ).first()
        if existing is not None:
            continue
        certify_example(
            question, sql, db_session, tenant_id=None, certified_by=certified_by, certified=True
        )
        written += 1
    return written
