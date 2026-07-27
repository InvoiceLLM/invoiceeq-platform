"""
One-time migration for Gap 55: copies every chunk out of the old shared
"invoice_chunks" Chroma collection into per-tenant collections
(invoice_chunks_{tenant_id}), grouped by each chunk's tenant_id metadata.

No re-embedding — vectors, documents, and metadata are copied as-is.
Safe to re-run: upsert is idempotent per id. The old shared collection is
left in place; delete it manually once the new collections are verified.

Usage:
    uv run python scripts/migrate_chroma_to_per_tenant.py
"""
import logging
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from chroma_client import get_chroma_client, _tenant_collection_name

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

OLD_COLLECTION_NAME = "invoice_chunks"
BATCH_SIZE = 500


def migrate():
    client = get_chroma_client()

    try:
        old_collection = client.get_collection(name=OLD_COLLECTION_NAME)
    except Exception:
        logger.info("No old shared '%s' collection found — nothing to migrate.", OLD_COLLECTION_NAME)
        return

    total = old_collection.count()
    logger.info("Found %d chunks in the shared collection.", total)
    if total == 0:
        return

    by_tenant: dict[str, dict[str, list]] = {}
    offset = 0
    while offset < total:
        batch = old_collection.get(
            limit=BATCH_SIZE,
            offset=offset,
            include=["embeddings", "documents", "metadatas"],
        )
        for i, chunk_id in enumerate(batch["ids"]):
            metadata = batch["metadatas"][i] or {}
            tenant_id = metadata.get("tenant_id")
            if not tenant_id:
                logger.warning("Skipping chunk %s — no tenant_id in metadata.", chunk_id)
                continue
            bucket = by_tenant.setdefault(tenant_id, {"ids": [], "embeddings": [], "documents": [], "metadatas": []})
            bucket["ids"].append(chunk_id)
            bucket["embeddings"].append(batch["embeddings"][i])
            bucket["documents"].append(batch["documents"][i])
            bucket["metadatas"].append(metadata)
        offset += BATCH_SIZE

    logger.info("Grouped chunks across %d tenants.", len(by_tenant))

    for tenant_id, bucket in by_tenant.items():
        target_name = _tenant_collection_name(tenant_id)
        target = client.get_or_create_collection(name=target_name)
        target.upsert(
            ids=bucket["ids"],
            embeddings=bucket["embeddings"],
            documents=bucket["documents"],
            metadatas=bucket["metadatas"],
        )
        logger.info("Migrated %d chunks -> %s", len(bucket["ids"]), target_name)

    logger.info(
        "Migration complete. Verify the new per-tenant collections, then manually "
        "delete the old '%s' collection once satisfied.", OLD_COLLECTION_NAME
    )


if __name__ == "__main__":
    migrate()
