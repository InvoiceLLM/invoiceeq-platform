# BE Gaps 244 / 240 / 243 / 239 — RAG retrieval evidence (senior-dev, 2026-08-17)

Raw proof for the RAG retrieval group. All measurements were taken against the
real local stack (Postgres `invoice_db` on :5433, Chroma on :8001, Azurite blob
storage), using the real `BAAI/bge-m3` model unless a line explicitly says
otherwise.

**Read the mode label on every number below.** Gap 244's original investigation
went wrong by reading mock-mode measurements as real-model evidence, so every
figure here is tagged `MOCK` or `REAL`.

---

## 0. The correction: the tracker's stated Gap 244 root cause was wrong

The tracker said `get_embeddings()` returned vectors with **L2 norm ≈ 1.82**
against the real model, and that this unnormalized magnitude was what pushed
distances to 5.8–7.3.

That is not what the real model does. `BAAI/bge-m3`'s `modules.json` ends in a
`sentence_transformers.models.Normalize` module (index 2, after Transformer and
Pooling), so `model.encode()` returns **unit-norm (1.0)** vectors with or
without `normalize_embeddings=True`.

`1.82` is the signature of the **mock** path. `MOCK_EMBEDDINGS=true` is set in
this repo's local `.env`, and the mock branch returned
`random.uniform(-0.1, 0.1)` over 1024 dims:

| measurement | mode | value |
|---|---|---|
| mock vector L2 norm, mean | `MOCK` | **1.847** (range 1.814–1.942) |
| mock-vs-mock squared-L2 distance | `MOCK` | **6.55** |
| tracker's reported distance band | — | 5.8–7.3 ← 6.55 sits squarely inside |
| real `bge-m3` vector L2 norm | `REAL` | **1.0** |

So of the original Gap 244 evidence: item 2 ("norm ≈ 1.82") and item 4
("distances 5.8–7.3") are **both mock-path artifacts**. Item 3 (no
`hnsw:space` metadata → Chroma defaults to L2) and item 5 (only the
keyword-overlap fallback was carrying retrieval) are **real and were
independently re-confirmed** — see §1 and §4.

## 1. Live collection state before any change (`REAL` measurement of `MOCK` data)

Norm of every vector actually stored in every live local collection:

| tenant | HNSW space | chunks | stored-vector norm (min/mean/max) | verdict |
|---|---|---|---|---|
| InvoiceEQ Test - India | `l2` | 5 | 1.8476 / **1.8604** / 1.8781 | mock random vectors |
| InvoiceEQ Test - US | `l2` | 9 | 1.8095 / **1.8570** / 1.8947 | mock random vectors |
| InvoiceEQ Test - Europe | `l2` | 7 | 1.8153 / **1.8557** / 1.9214 | mock random vectors |
| Example Workspace | — | *(no collection)* | — | 31 indexable invoices, none indexed |

**Not one real-model embedding existed in the local Chroma stack.** Real-model
RAG retrieval had therefore never been exercised locally, by any test, before
this pass. Every collection was also on Chroma's default `l2` space, confirming
the half of the tracker's root cause that was correct.

## 2. Threshold derivation (`REAL`)

`threshold_derivation_tenant_us.json` — the 8 category-browsing questions
embedded with the real model against tenant-us's 10 real invoice PDFs, computed
in both `l2` and `cosine` space. `threshold_derivation_30_invoices.json` — the
same questions against all 30 invoices of the three InvoiceEQ tenants, so the
false-positive floor is estimated off ~3× the negatives.

Every `l2` figure is **exactly 2×** its `cosine` twin (0.9709/0.4854,
0.7646/0.3823, 0.8263/0.4131, …), which is the identity `||a-b||² = 2·(1-cos)`
holding for unit vectors — an independent confirmation the real model's output
really is unit norm.

Separation band, both runs agreeing:

| bound | value | case |
|---|---|---|
| hardest genuine match still separable | **0.4749** | "janitorial or cleaning services" → Redwood Facilities Group |
| best (lowest) false positive | **0.5062** | "legal or attorney fees" (category absent) → Fieldstone Analytics |

**Threshold = 0.49**, the midpoint — the maximally drift-tolerant point between
catching real matches and still answering "no match" honestly. Replaces the old
0.4, which was calibrated for a bounded cosine space but enforced against
unbounded raw L2, making it unreachable for every query by construction.

The one genuine match 0.49 misses is CMC-330217 at **0.5331** (a single $200
freight line on an otherwise-manufacturing invoice). It sits *above* the
false-positive floor, so no threshold can admit it without also admitting
fabricated matches; it is left to the keyword pass, which is now a genuine
second channel rather than the only working one.

## 3. Migration run (`REAL`)

`scripts/reembed_chroma_collections.py --apply --tenant 3511ae3e-… ` with
`MOCK_EMBEDDINGS=false`.

| | before | after |
|---|---|---|
| HNSW space | `l2` | **`cosine`** |
| chunks | 9 | **10** |
| distinct invoice ids | 7 real + **2 orphans** | **10**, 0 orphans |
| stored-vector norm | ~1.857 (mock) | **1.000000** exactly |

Before-state arithmetic confirms Gaps 240 and 243 simultaneously: tenant-us has
4 COMPLETED + 3 VERIFIED + 2 AUDIT_REQUIRED + 1 NEEDS_REVIEW, and exactly
**7 = |COMPLETED| + |VERIFIED|** were indexed. The 3 missing were precisely the
2 AUDIT_REQUIRED (Gap 240) and the 1 NEEDS_REVIEW (Gap 243).

Only tenant-us was migrated, deliberately — the other tenants were left as-is
to preserve a before-state control (§4) and to avoid disturbing a concurrently
used stack.

## 4. Category-browsing test, before and after (`REAL` model, live through the
shipped `chroma_client.query_invoice_chunks()`)

### BEFORE — control tenant IEQ-Europe, left unmigrated (`space=l2`, mock stored vectors)

| question | result |
|---|---|
| Do we have any industrial or machinery invoices? | Rhein Industrietechnik, dist **2.3610**, `matched_by=keyword` |
| What about catering or food costs? | **NO MATCHES** |
| Show me manufacturing or tooling charges | **NO MATCHES** |

2.3610 is **4.8× the 0.49 threshold**. The vector channel contributes nothing;
the only match is carried entirely by literal keyword overlap.

### AFTER — tenant-us, migrated (`space=cosine`, real unit-norm vectors)

Full output in `step14_category_browsing_after.json`.

| # | question | expected match | dist | kw | carried by |
|---|---|---|---|---|---|
| 1 | How much did we spend on office supplies? | Summit Office Supplies | 0.4132 | 2 | vector+keyword |
| 2 | And logistics or freight costs? | Blue Ridge Logistics | 0.4299 | 2 | vector+keyword |
| 3 | Show me manufacturing or tooling charges | Cascade Manufacturing Co | 0.3848 | 2 | vector+keyword |
| 4 | Any janitorial or cleaning services? | Redwood Facilities Group | 0.4749 | 2 | vector+keyword |
| 5 | What about printing costs? | Apex Print Solutions | 0.3924 | **0** | **vector only** |
| 6 | Do we have any steel or materials related invoices? | Titan Steel Distributors | 0.3823 | 1 | **vector only** |
| 7 | Do we have any legal or attorney fees? | *(absent category)* | — | — | **NO MATCHES** ✓ |
| 8 | Any airline or travel bookings? | *(absent category)* | — | — | **NO MATCHES** ✓ |

6/6 real categories retrieved; 2/2 absent categories honestly returned nothing.

**Turn 5 is the decisive result.** "What about printing costs?" matched Apex
Print Solutions with `keyword_score = 0` — the document says "Print", the
question says "printing", so there is zero literal overlap and the keyword
fallback could not have carried it at any threshold. It was retrieved purely by
semantic similarity. Apex is also `AUDIT_REQUIRED`, so before this pass it was
not in the index at all. Turn 5 proves Gap 240 and Gap 244 together on real
data. Turn 6 (Titan Steel, also `AUDIT_REQUIRED`, kw=1 below the min_k_score of
2) is the same proof a second time.

Honest caveat: at 0.49 several turns also admit non-expected chunks under the
threshold (turn 6 admits 5). That is recall-oriented by design — the LLM filters
the passed chunks afterwards — and it is the reason 0.49 sits at the midpoint of
the separation band rather than at its top. It is not a regression: before the
fix these questions returned only keyword hits or nothing at all.

## 5. Gap 239 orphan measurement (`REAL`, no embeddings involved)

`scripts/reembed_chroma_collections.py --prune-only` against the live stack:

- **41→42 `invoice_chunks_*` collections vs 7 Postgres tenants; 38 belong to
  tenant ids that no longer exist at all.** Consistent with the measured origin
  — Postgres schema teardown (every `tests/test_*.py` fixture calls
  `SQLModel.metadata.drop_all(engine)`) and DB resets against a Chroma volume
  that outlives them. Not a product deletion path: an exhaustive grep of
  `routers/`, `services/`, `queue_worker/`, `scripts/`, `agents/`, `utils/`,
  `models.py` found **zero** hard-deletes of an `Invoice` row, both invoice
  delete endpoints are soft deletes (Gap 192), and
  `chroma_client.delete_invoice_chunks()` had **zero call sites in product
  code**.
- **The reported symptom reproduced exactly.** The chunk-level scan found
  tenant-us holding **2 chunks whose `invoice_id` matches no `Invoice` row**,
  both with `vendor_name: Blue Ridge Logistics` —
  `12ffad51-933f-48c9-92d1-591a31857186` and
  `645e0d90-5827-42eb-abb5-6647da4739db`. Gap 239 reported "cited 3 invoice ids
  for Blue Ridge Logistics, 2 of which return zero rows". Same vendor, same
  count.
- After migration, a re-scan of tenant-us reports **0** orphan chunks.
- **The mechanism was caught happening live.** Across this pass the orphan-collection count rose **38 → 84** (total `invoice_chunks_*` collections **42 → 89**) purely from running the BE test suite three times — no product code executed during that growth. 84 of the 89 collections hold 1–2 chunks each, the signature of a test indexing one single-page document under an ephemeral `uuid4()` tenant whose Postgres schema is then dropped by the fixture teardown. This settles the origin question: the desync isn't merely *explainable* as a test artifact, it is actively manufactured by every suite run against a Chroma volume that has no matching teardown.
- **Left unpruned deliberately** — the `--prune-orphans` tooling is ready and safe by construction (it only touches collections whose tenant has no Postgres row), but a functional-tester was using the same shared local stack and the standing instruction was not to wipe shared databases.

## Files

| file | contents |
|---|---|
| `threshold_derivation_tenant_us.json` | 8 questions × tenant-us's 10 invoices, real model, `l2` and `cosine` |
| `threshold_derivation_30_invoices.json` | same questions × all 30 InvoiceEQ invoices (wider false-positive floor) |
| `step14_category_browsing_after.json` | post-migration live run through `query_invoice_chunks()`, with `matched_by` per chunk |

## Reproducing

```bash
cd Prod_Invoice_LLM/apps/invoice-be
# orphan audit only — never loads the model, safe with MOCK_EMBEDDINGS on
uv run python scripts/reembed_chroma_collections.py --prune-only
# the migration itself — MOCK_EMBEDDINGS must be false or you rebuild with random vectors
MOCK_EMBEDDINGS=false uv run python scripts/reembed_chroma_collections.py --apply --tenant <uuid>
```
