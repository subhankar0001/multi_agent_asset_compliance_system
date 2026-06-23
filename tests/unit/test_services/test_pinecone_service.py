"""Unit tests for pinecone_service — all Pinecone calls mocked."""

from unittest.mock import MagicMock

from app.services import pinecone_service


def test_upsert_vectors_batches_correctly(mock_pinecone_index):
    """upsert_vectors should batch in groups of 100 and return the total count."""
    vectors = [
        {"id": f"vec_{i}", "values": [0.1] * 1536, "metadata": {"doc_id": "doc-1"}}
        for i in range(250)
    ]
    result = pinecone_service.upsert_vectors(mock_pinecone_index, "asset-abc", vectors)
    assert result == 250
    # 250 vectors / 100 per batch = 3 upsert calls
    assert mock_pinecone_index.upsert.call_count == 3


def test_upsert_vectors_small_batch(mock_pinecone_index):
    """upsert_vectors with fewer than 100 vectors should make exactly one call."""
    vectors = [
        {"id": f"vec_{i}", "values": [0.1] * 1536, "metadata": {"doc_id": "doc-1"}}
        for i in range(50)
    ]
    result = pinecone_service.upsert_vectors(mock_pinecone_index, "asset-abc", vectors)
    assert result == 50
    assert mock_pinecone_index.upsert.call_count == 1


def test_delete_by_doc_id_calls_correct_filter(mock_pinecone_index):
    """delete_by_doc_id must list ids by prefix and delete them."""
    mock_pinecone_index.list.return_value = iter([["vec1", "vec2"]])
    
    deleted = pinecone_service.delete_by_doc_id(mock_pinecone_index, "abc", "manual-v2")
    
    mock_pinecone_index.list.assert_called_once_with(
        prefix="abc_manual-v2_",
        namespace="asset_abc"
    )
    mock_pinecone_index.delete.assert_called_once_with(
        ids=["vec1", "vec2"],
        namespace="asset_abc",
    )
    assert deleted == 2


def test_delete_by_doc_id_returns_zero_when_namespace_empty(mock_pinecone_index):
    """delete_by_doc_id should return 0 when list yields nothing."""
    mock_pinecone_index.list.return_value = iter([])
    deleted = pinecone_service.delete_by_doc_id(mock_pinecone_index, "abc", "doc-1")
    assert deleted == 0
    assert mock_pinecone_index.delete.call_count == 0


def test_query_namespace_applies_doc_type_filter(mock_pinecone_index):
    """query_namespace must apply the doc_type filter when provided."""
    pinecone_service.query_namespace(
        mock_pinecone_index,
        "abc",
        [0.1] * 1536,
        top_k=5,
        doc_type_filter="safety_sheet",
    )
    call_kwargs = mock_pinecone_index.query.call_args.kwargs
    assert call_kwargs["filter"] == {"doc_type": {"$eq": "safety_sheet"}}


def test_query_namespace_no_filter_by_default(mock_pinecone_index):
    """query_namespace without doc_type_filter must NOT include a filter."""
    pinecone_service.query_namespace(mock_pinecone_index, "abc", [0.1] * 1536, top_k=5)
    call_kwargs = mock_pinecone_index.query.call_args.kwargs
    assert call_kwargs.get("filter") is None


def test_namespace_has_docs_true(mock_pinecone_index):
    """namespace_has_docs returns True when namespace has vectors."""
    mock_pinecone_index.describe_index_stats.return_value = MagicMock(
        namespaces={"asset_abc": MagicMock(vector_count=5)}
    )
    assert pinecone_service.namespace_has_docs(mock_pinecone_index, "abc") is True


def test_namespace_has_docs_false_empty_namespace(mock_pinecone_index):
    """namespace_has_docs returns False when namespace doesn't exist."""
    mock_pinecone_index.describe_index_stats.return_value = MagicMock(namespaces={})
    assert pinecone_service.namespace_has_docs(mock_pinecone_index, "abc") is False
