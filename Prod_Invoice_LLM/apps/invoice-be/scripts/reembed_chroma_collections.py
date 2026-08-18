"""
One-time migration for Gap 244 (and the cleanup half of Gap 239).

Why it's needed
---------------
Chroma pins a collection's HNSW distance space at **creation** time. Verified
live against chromadb 1.5.9: calling `get_or_create_collection(name=...,
metadata={"hnsw:space": "cosine"})` on a collection that already exists returns
the existing collection with its original `space` — no error, no warning. So the
`_collection_metadata()` change in `chroma_client.py` only affects collections
created *after* it shipped; every pre-existing `invoice_chunks_*` collection
keeps raw (squared) L2 forever until it is dropped and rebuilt. That rebuild has
to re-embed, because the vectors have to be re-inserted into a new index anyway.

What it does, per tenant
------------------------
1. Drops `invoice_chunks_{tenant_id}` and recreates it with `hnsw:space=cosine`.
2. Re-indexes every invoice of that tenant whose status passes
   `chroma_client.should_index_status()` — which now includes `AUDIT_REQUIRED`
   (Gap 240) and `NEEDS_REVIEW` (Gap 243), so this migration is also the
   backfill for the two indexing gaps, not just the distance-space fix.
   Soft-deleted rows (Gap 192) are re-indexed too: their chunks are retained on
   purpose so a restore stays possible.
3. Reports Gap 239 orphans at **both** granularities:
   * whole collections whose tenant no longer exists in Postgres at all, and
   * individual chunks inside a *live* tenant's collection whose `invoice_id`
     matches no `Invoice` row — the exact shape Gap 239 was filed for (a chat
     citation pointing at an invoice id that returns zero rows).
   With `--prune-orphans` both are dropped. Note that a full rebuild already
   removes intra-collection orphans by construction (the collection is dropped
   and refilled from Postgres); the chunk-level scan exists so a dry run
   *reports the real desync count* before anything is changed, and so
   `--prune-orphans --tenant X` can clean one tenant without a costly re-embed.

Cost warning: this re-embeds every indexable document, one page per chunk,
through BAAI/bge-m3. Run it with `MOCK_EMBEDDINGS` unset/false, or the
collections get rebuilt full of random vectors.

Usage:
    uv run python scripts/reembed_chroma_collections.py                  # dry run, all tenants
    uv run python scripts/reembed_chroma_collections.py --apply
    uv run python scripts/reembed_chroma_collections.py --apply --tenant <uuid>
    uv run python scripts/reembed_chroma_collections.py --apply --prune-orphans
    uv run python scripts/reembed_chroma_collections.py --prune-only          # audit, no re-embed
    uv run python scripts/reembed_chroma_collections.py --apply --prune-only --prune-orphans

The full documented procedure (pre-flight, ordering, rollback, verification)
lives in `docs/feature_6_rag.md` §"Gap 244 re-embed migration procedure".
"""
import argparse
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlmodel import Session, select  # noqa: E402

from chroma_client import (  # noqa: E402
    _collection_metadata,
    _collection_space,
    _tenant_collection_name,
    delete_invoice_chunks,
    get_chroma_client,
    index_invoice_document,
    should_index_status,
)
from config import get_settings  # noqa: E402
from database import engine  # noqa: E402
from models import Invoice, Tenant  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger("reembed")

COLLECTION_PREFIX = "invoice_chunks_"


def _existing_collection_names(client) -> dict[str, str]:
    """Maps tenant_id -> collection name for every invoice_chunks_* collection."""
    out = {}
    for col in client.list_collections():
        name = col if isinstance(col, str) else col.name
        if name.startswith(COLLECTION_PREFIX):
            out[name[len(COLLECTION_PREFIX):]] = name
    return out


def _current_space(client, name: str) -> str:
    """The HNSW space a collection is on *today*, for before/after reporting."""
    try:
        return _collection_space(client.get_collection(name))
    except Exception:
        return "none (new collection)"


def _orphan_chunk_invoice_ids(client, tenant_id: str, live_invoice_ids: set[str]) -> dict[str, int]:
    """
    Gap 239, chunk granularity: returns {orphan invoice_id: chunk count} for
    chunks in this tenant's collection whose `invoice_id` matches no `Invoice`
    row at all.

    `live_invoice_ids` is built **without** an `invoice_not_deleted()` filter on
    purpose — a soft-deleted invoice (Gap 192) keeps its chunks by design and is
    a legitimate citation, so it is not an orphan. Only an id with no row
    whatsoever counts.
    """
    name = _tenant_collection_name(tenant_id)
    try:
        collection = client.get_collection(name)
    except Exception:
        return {}  # tenant has no collection yet — nothing to scan
    try:
        stored = collection.get(include=["metadatas"])
    except Exception as e:
        logger.error("  could not read %s for orphan scan: %s", name, e)
        return {}
    counts: dict[str, int] = {}
    for meta in stored.get("metadatas") or []:
        inv_id = str((meta or {}).get("invoice_id") or "")
        if inv_id and inv_id not in live_invoice_ids:
            counts[inv_id] = counts.get(inv_id, 0) + 1
    return counts


def reembed(apply_changes: bool, only_tenant: str | None, prune_orphans: bool,
            prune_only: bool = False) -> None:
    settings = get_settings()
    if settings.MOCK_EMBEDDINGS and not prune_only:
        logger.warning(
            "MOCK_EMBEDDINGS is on — this would rebuild every collection with RANDOM vectors. "
            "Unset it before running with --apply. (--prune-only never embeds and is safe either way.)"
        )
        if apply_changes:
            raise SystemExit(2)

    client = get_chroma_client()
    collections = _existing_collection_names(client)

    with Session(engine) as session:
        tenants = session.exec(select(Tenant)).all()
        tenant_ids = {str(t.id) for t in tenants}

        orphans = sorted(set(collections) - tenant_ids)
        if orphans:
            logger.warning(
                "Gap 239: %d Chroma collection(s) belong to a tenant with no Postgres row "
                "— every chunk in them is an orphan citation waiting to happen.", len(orphans)
            )
            for tid in orphans:
                logger.warning("  orphan collection %s", collections[tid])
            if prune_orphans and apply_changes:
                for tid in orphans:
                    client.delete_collection(collections[tid])
                    logger.info("  dropped %s", collections[tid])
            elif prune_orphans:
                logger.info("  (dry run — pass --apply to actually drop these)")
            else:
                logger.info("  (pass --prune-orphans to drop them)")

        targets = [t for t in tenants if not only_tenant or str(t.id) == only_tenant]
        if only_tenant and not targets:
            raise SystemExit(f"No tenant with id {only_tenant}")

        for tenant in targets:
            tenant_id = str(tenant.id)
            invoices = session.exec(
                select(Invoice).where(Invoice.tenant_id == tenant.id)
            ).all()
            live_invoice_ids = {str(i.id) for i in invoices}
            indexable = [i for i in invoices if should_index_status(i.status) and i.file_path]
            name = _tenant_collection_name(tenant_id)

            # Gap 239, chunk granularity — reported for every tenant that has a
            # collection, including ones with nothing left to index.
            if tenant_id in collections:
                orphan_chunks = _orphan_chunk_invoice_ids(client, tenant_id, live_invoice_ids)
                if orphan_chunks:
                    total = sum(orphan_chunks.values())
                    logger.warning(
                        "Gap 239: tenant %s (%s) has %d chunk(s) across %d invoice id(s) with no "
                        "Postgres row — these are what a chat citation can point at and find nothing.",
                        tenant_id, tenant.name, total, len(orphan_chunks),
                    )
                    for inv_id, n in sorted(orphan_chunks.items()):
                        logger.warning("    orphan invoice_id %s (%d chunk(s))", inv_id, n)
                    if prune_orphans and apply_changes:
                        for inv_id in orphan_chunks:
                            delete_invoice_chunks(inv_id, tenant_id)
                        logger.info("    pruned %d orphan chunk(s)", total)
                    elif prune_orphans:
                        logger.info("    (dry run — pass --apply to actually prune these)")
                    else:
                        logger.info("    (pass --prune-orphans to prune them; a full rebuild "
                                    "below also removes them by construction)")

            if prune_only:
                continue

            if not indexable:
                logger.info("tenant %s (%s): nothing indexable, skipped", tenant_id, tenant.name)
                continue

            logger.info(
                "tenant %s (%s): %d/%d invoice(s) indexable -> rebuild %s (currently space=%s) as cosine",
                tenant_id, tenant.name, len(indexable), len(invoices), name,
                _current_space(client, name),
            )
            if not apply_changes:
                for inv in indexable:
                    logger.info("    would index %s [%s/%s]",
                                inv.invoice_number or inv.id, inv.flow_direction, inv.status)
                continue

            try:
                client.delete_collection(name)
            except Exception:
                pass  # first-time tenants have no collection yet
            collection = client.get_or_create_collection(name=name, metadata=_collection_metadata())

            indexed = 0
            for inv in indexable:
                try:
                    index_invoice_document(
                        invoice_id=str(inv.id),
                        tenant_id=tenant_id,
                        vendor_name=inv.vendor_name or inv.customer_name,
                        file_path=inv.file_path,
                    )
                    indexed += 1
                except Exception as e:
                    logger.error("    FAILED %s: %s", inv.invoice_number or inv.id, e)
            # Verify the rebuild actually landed in cosine space rather than
            # assuming it — the whole reason this script exists is that Chroma
            # silently keeps the old space when the collection already existed.
            space = _collection_space(collection)
            log = logger.info if space == "cosine" else logger.error
            log("    re-indexed %d/%d invoice(s); collection space is now %s",
                indexed, len(indexable), space)

    logger.info("Done%s.", "" if apply_changes else " (dry run — nothing was changed)")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="actually rebuild (default is a dry run)")
    parser.add_argument("--tenant", default=None, help="restrict to one tenant id")
    parser.add_argument("--prune-orphans", action="store_true",
                        help="also drop orphan collections and orphan chunks (Gap 239)")
    parser.add_argument("--prune-only", action="store_true",
                        help="scan/prune Gap 239 orphans without re-embedding anything "
                             "(safe with MOCK_EMBEDDINGS on — it never calls the model)")
    args = parser.parse_args()
    reembed(apply_changes=args.apply, only_tenant=args.tenant,
            prune_orphans=args.prune_orphans, prune_only=args.prune_only)
