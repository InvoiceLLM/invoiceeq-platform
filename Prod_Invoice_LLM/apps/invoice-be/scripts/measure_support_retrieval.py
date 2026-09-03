"""Gap 430: derive the Support Assistant's relevance threshold from measurement.

Mirrors Gap 244's method for the invoice-chunk threshold: embed the corpus,
run a labelled set of real paraphrases, and place the cutoff between the
hardest genuine match and the closest false positive -- rather than picking a
number and hoping. The previous 0.35 was picked that way and was unreachable,
so the vector fallback shipped dead.

Run with real embeddings (MOCK_EMBEDDINGS unset/false):
    .venv/Scripts/python.exe scripts/measure_support_retrieval.py
"""
import os
import sys

os.environ.setdefault("MOCK_EMBEDDINGS", "false")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agents.support_agent import (  # noqa: E402
    KNOWLEDGE_TOPICS,
    _score_topic,
    _topic_embedding_text,
)
from chroma_client import get_embeddings  # noqa: E402

# Labelled set: paraphrases a real user might type, each with the topic that
# SHOULD answer it. Deliberately worded to avoid the topic's own keywords --
# a phrasing the keyword pass already catches proves nothing about retrieval.
LABELLED: list[tuple[str, str]] = [
    ("how do I get back in if I can't remember my sign-in details", "account_auth"),
    ("someone left the company, how do I stop them getting in", "user_management"),
    ("can I teach it to read a supplier's layout properly", "trainer"),
    ("the system flagged something on a bill, where do I deal with that", "auditor"),
    ("will it notice if I feed it the same document twice", "autopilot"),
    ("can it pick up paperwork from a shared cloud folder on its own", "autopilot"),
    ("is my information kept private and locked down", "security_retention"),
    ("how long do you hang on to our paperwork", "security_retention"),
    ("what happens if I forward a bill to you by mail", "email_ingestion"),
    ("how do I get the numbers out into a spreadsheet", "export_reports"),
    ("how big can a file be before it stops working", "ingestion_upload"),
    ("what do the different states on a bill actually mean", "invoice_statuses"),
    ("where do I see totals and charts for the month", "dashboard_analytics"),
    ("how much does the paid tier cost", "billing"),
    ("can another system be told automatically when something finishes", "connectors_webhooks"),
]

# Things the assistant genuinely cannot answer. Any of these scoring better
# than the hardest genuine match means the corpus cannot be separated at all.
NEGATIVES = [
    "how do I wash my car",
    "what is the weather like tomorrow",
    "recommend a good restaurant nearby",
    "how do I train for a marathon",
]


def main() -> None:
    texts = [_topic_embedding_text(t) for t in KNOWLEDGE_TOPICS]
    ids = [t["id"] for t in KNOWLEDGE_TOPICS]
    vecs = get_embeddings(texts)

    def cos(a, b):
        return 1.0 - sum(x * y for x, y in zip(a, b))

    def rank(q):
        qv = get_embeddings([q])[0]
        return sorted(((cos(qv, v), i) for v, i in zip(vecs, ids)), key=lambda x: x[0])

    print(f"corpus: {len(ids)} topics\n")

    genuine, wrong_topic, keyword_shadowed = [], [], 0
    print("=== labelled paraphrases ===")
    for q, expected in LABELLED:
        # Only queries the keyword pass MISSES exercise the vector path.
        if any(_score_topic(t, q.lower())[0] > 0 for t in KNOWLEDGE_TOPICS):
            keyword_shadowed += 1
            print(f"  [kw-hit, skipped] {q!r}")
            continue
        r = rank(q)
        d, got = r[0]
        margin = r[1][0] - d
        ok = "OK " if got == expected else "MISS"
        if got == expected:
            genuine.append((d, margin, q))
        else:
            wrong_topic.append((d, got, expected, q))
        print(f"  {ok} {d:.4f} margin={margin:.4f} got={got:<20} want={expected:<20} {q[:44]!r}")

    print("\n=== negatives (must not match) ===")
    neg = []
    for q in NEGATIVES:
        d, got = rank(q)[0]
        neg.append((d, got, q))
        print(f"       {d:.4f} closest={got:<20} {q[:44]!r}")

    print("\n=== derivation ===")
    if not genuine:
        print("  no genuine matches -- corpus/embedding text is not separable")
        return
    hardest = max(g[0] for g in genuine)
    floor = min(n[0] for n in neg)
    print(f"  keyword-shadowed (not vector-tested): {keyword_shadowed}")
    print(f"  correct topic ranked #1:              {len(genuine)}/{len(genuine)+len(wrong_topic)}")
    print(f"  hardest genuine match:                {hardest:.4f}")
    print(f"  closest false positive:               {floor:.4f}")
    if wrong_topic:
        print("  WRONG-TOPIC cases (margin guard must catch these):")
        for d, got, want, q in wrong_topic:
            print(f"     {d:.4f} got={got} want={want} {q[:40]!r}")
    if hardest < floor:
        print(f"  => separable. midpoint threshold = {(hardest + floor) / 2:.4f}")
    else:
        print("  => NOT separable on distance alone; the margin guard is doing the work")
    tightest = min(g[1] for g in genuine)
    print(f"  tightest genuine margin:              {tightest:.4f}  (margin guard must be below this)")


if __name__ == "__main__":
    main()
