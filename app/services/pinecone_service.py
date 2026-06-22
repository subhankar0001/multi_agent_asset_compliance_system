"""
Pinecone vector database service.

Namespace convention: asset_{asset_uuid}
All documents for one asset share one namespace.
Documents within the namespace are distinguished by doc_id metadata.

Retrieval modes:
  - Broad (audit / chat): top-k across entire namespace, no filter
  - Filtered (update / delete): filter on doc_id to scope to one document

All public functions include tenacity retry logic for transient API errors.
"""

from typing import Any

import structlog
from pinecone import Index
from tenacity import retry, stop_after_attempt, wait_exponential

from app.config import get_settings

logger = structlog.get_logger(__name__)


def _namespace(asset_id: str) -> str:
    """Construct the Pinecone namespace key for an asset."""
    return f"asset_{asset_id}"


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    reraise=True,
)
def upsert_vectors(
    index: Index,
    asset_id: str,
    vectors: list[dict[str, Any]],  # [{"id": str, "values": list[float], "metadata": dict}]
) -> int:
    """
    Upsert a batch of vectors into the asset's Pinecone namespace.

    Vectors are batched in groups of 100 to stay within the Pinecone API
    request size limits. Returns the total number of vectors upserted.
    Retries up to 3 times with exponential backoff on transient errors.
    """
    namespace = _namespace(asset_id)
    batch_size = 100
    total = 0
    for i in range(0, len(vectors), batch_size):
        batch = vectors[i : i + batch_size]
        index.upsert(vectors=batch, namespace=namespace)
        total += len(batch)
        logger.debug(
            "pinecone_batch_upserted",
            namespace=namespace,
            batch_size=len(batch),
            offset=i,
        )
    logger.info("pinecone_upsert_complete", namespace=namespace, total_vectors=total)
    return total


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    reraise=True,
)
def delete_by_doc_id(index: Index, asset_id: str, doc_id: str) -> int:
    """
    Delete all vectors belonging to a specific document within an asset namespace.

    Used on update events to remove stale vectors before re-embedding.
    The deletion is scoped to the asset namespace, so other documents
    in the same namespace are never affected.

    Returns the count of deleted vectors (best-effort from stats diff).
    """
    namespace = _namespace(asset_id)

    # Snapshot vector count before deletion
    stats_before = index.describe_index_stats()
    ns_before = stats_before.namespaces.get(namespace, {})
    count_before = getattr(ns_before, "vector_count", 0)

    index.delete(filter={"doc_id": {"$eq": doc_id}}, namespace=namespace)

    # Snapshot vector count after deletion
    stats_after = index.describe_index_stats()
    ns_after = stats_after.namespaces.get(namespace, {})
    count_after = getattr(ns_after, "vector_count", 0)

    deleted = max(0, count_before - count_after)
    logger.info(
        "pinecone_delete_complete",
        namespace=namespace,
        doc_id=doc_id,
        vectors_deleted=deleted,
    )
    return deleted


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    reraise=True,
)
def query_namespace(
    index: Index,
    asset_id: str,
    query_vector: list[float],
    top_k: int,
    doc_type_filter: str | None = None,
) -> list[dict[str, Any]]:
    """
    Query the asset's Pinecone namespace for semantically relevant chunks.

    By default (doc_type_filter=None), searches across ALL documents in the
    namespace so every document type (user_manual, safety_sheet, etc.) can
    contribute to the result set.

    Pass doc_type_filter to restrict retrieval to a specific document type.
    Returns a list of result dicts with keys: id, score, metadata.
    """
    namespace = _namespace(asset_id)
    query_filter = None
    if doc_type_filter:
        query_filter = {"doc_type": {"$eq": doc_type_filter}}

    response = index.query(
        vector=query_vector,
        top_k=top_k,
        namespace=namespace,
        include_metadata=True,
        filter=query_filter,
    )

    results = [
        {
            "id": match.id,
            "score": match.score,
            "metadata": match.metadata or {},
        }
        for match in response.matches
    ]
    logger.debug(
        "pinecone_query_complete",
        namespace=namespace,
        top_k=top_k,
        results_returned=len(results),
        doc_type_filter=doc_type_filter,
    )
    return results


def namespace_has_docs(index: Index, asset_id: str) -> bool:
    """Return True if this asset's namespace already contains vectors."""
    stats = index.describe_index_stats()
    ns = stats.namespaces.get(_namespace(asset_id))
    return ns is not None and getattr(ns, "vector_count", 0) > 0


def doc_id_exists(index: Index, asset_id: str, doc_id: str) -> bool:
    """Return True if vectors with this doc_id already exist in the namespace."""
    settings = get_settings()
    namespace = _namespace(asset_id)
    response = index.query(
        vector=[0.0] * settings.embedding_dimensions,
        top_k=1,
        namespace=namespace,
        filter={"doc_id": {"$eq": doc_id}},
        include_metadata=False,
    )
    return len(response.matches) > 0


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    reraise=True,
)
def delete_namespace(index: Index, asset_id: str) -> int:
    """
    Delete ALL vectors in an asset's Pinecone namespace.

    Used by the admin delete endpoint for GDPR right-to-erasure.  Deletes
    every vector regardless of doc_type or doc_id.  The namespace itself
    is implicitly removed once it contains zero vectors.

    Returns the number of vectors deleted (best-effort via stats diff).
    """
    namespace = _namespace(asset_id)

    # Snapshot count before deletion
    stats_before = index.describe_index_stats()
    ns_before = stats_before.namespaces.get(namespace, {})
    count_before = getattr(ns_before, "vector_count", 0)

    if count_before == 0:
        logger.info("pinecone_namespace_already_empty", namespace=namespace)
        return 0

    # Delete all vectors in the namespace
    index.delete(delete_all=True, namespace=namespace)

    # Snapshot count after deletion
    stats_after = index.describe_index_stats()
    ns_after = stats_after.namespaces.get(namespace, {})
    count_after = getattr(ns_after, "vector_count", 0)

    deleted = max(0, count_before - count_after)
    logger.info(
        "pinecone_namespace_deleted",
        namespace=namespace,
        vectors_deleted=deleted,
    )
    return deleted
