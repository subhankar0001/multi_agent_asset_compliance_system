"""
Document agent — retrieve relevant chunks from the asset's Pinecone namespace.

This is the first node in the LangGraph audit pipeline. It runs a broad
top-k semantic query across the entire asset namespace (no doc_type filter)
so that all document types (user_manual, safety_sheet, compliance_spec,
installation_image) can contribute to the audit.

The query text is constructed from asset spec + auditor remarks to maximise
semantic relevance across the diverse document types.

Populates: state["retrieved_chunks"], state["documents_consulted"]
"""

from typing import Any

import structlog

from app.agents.state import AuditState, RetrievedChunk
from app.config import get_settings
from app.dependencies import _get_embeddings_model, _get_pinecone_index
from app.services import pinecone_service
from app.services.embedding_service import embed_query

logger = structlog.get_logger(__name__)


async def document_agent_node(state: AuditState) -> dict[str, Any]:
    """
    Retrieve semantically relevant document chunks from Pinecone.

    Constructs a rich query from the asset's metadata and auditor remarks,
    embeds it, and queries the asset's Pinecone namespace with no doc_type
    filter so all document types can contribute.

    Returns:
        dict with keys: retrieved_chunks, documents_consulted
        On error: also sets errors key
    """
    settings = get_settings()
    index = _get_pinecone_index()
    embeddings = _get_embeddings_model()

    asset_id = state["asset_id"]
    asset_spec = state.get("asset_spec", {})
    auditor_remarks = state.get("auditor_remarks") or ""

    # Build a rich query that spans all relevant compliance topics
    query_text = (
        f"Asset: {asset_spec.get('name', '')} "
        f"Category: {asset_spec.get('category', '')} "
        f"Manufacturer: {asset_spec.get('manufacturer', '')} "
        f"Auditor remarks: {auditor_remarks or 'none'} "
        "Compliance requirements, safety specifications, installation procedures, "
        "maintenance standards, inspection criteria, and regulatory obligations."
    )

    try:
        query_vector = await embed_query(embeddings, query_text)
        raw = pinecone_service.query_namespace(
            index,
            asset_id,
            query_vector,
            top_k=settings.retrieval_top_k_audit,
        )

        chunks: list[RetrievedChunk] = [
            {
                "doc_id": r["metadata"].get("doc_id", ""),
                "doc_type": r["metadata"].get("doc_type", ""),
                "filename": r["metadata"].get("filename", ""),
                "page": r["metadata"].get("page"),
                "text": r["metadata"].get("text", ""),
                "score": r["score"],
            }
            for r in raw
        ]

        doc_ids = list({c["doc_id"] for c in chunks if c["doc_id"]})
        logger.info(
            "document_agent_complete",
            asset_id=asset_id,
            chunks_retrieved=len(chunks),
            unique_documents=len(doc_ids),
        )
        return {"retrieved_chunks": chunks, "documents_consulted": doc_ids}

    except Exception as exc:
        logger.error("document_agent_error", asset_id=asset_id, error=str(exc))
        existing_errors: list[str] = list(state.get("errors", []))
        return {
            "retrieved_chunks": [],
            "documents_consulted": [],
            "errors": [*existing_errors, f"document_agent: {exc}"],
        }
