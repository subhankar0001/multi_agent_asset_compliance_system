"""Unit tests for document_agent node — happy path and error path."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agents.document_agent import document_agent_node
from app.agents.state import AuditState


def _make_state(**kwargs) -> AuditState:
    base = AuditState(
        asset_id="abc-123",
        run_id="run-001",
        asset_spec={"name": "Hydraulic Pump", "category": "pump"},
        s3_image_keys=["audits/img_001.jpg"],
        auditor_remarks="Valve cap appears corroded",
        errors=[],
    )
    base.update(kwargs)
    return base


@pytest.mark.asyncio
async def test_document_agent_populates_state(
    mock_pinecone_index, mock_embeddings_model, sample_pinecone_match
):
    """Happy path: document_agent should return retrieved_chunks and documents_consulted."""
    mock_pinecone_index.query.return_value = MagicMock(matches=[sample_pinecone_match])

    with (
        patch("app.agents.document_agent._get_pinecone_index", return_value=mock_pinecone_index),
        patch(
            "app.agents.document_agent._get_embeddings_model", return_value=mock_embeddings_model
        ),
    ):
        result = await document_agent_node(_make_state())

    assert len(result["retrieved_chunks"]) == 1
    assert result["retrieved_chunks"][0]["doc_id"] == "manual-v2"
    assert result["retrieved_chunks"][0]["score"] == 0.92
    assert "manual-v2" in result["documents_consulted"]


@pytest.mark.asyncio
async def test_document_agent_empty_namespace(mock_pinecone_index, mock_embeddings_model):
    """document_agent should return empty lists when Pinecone has no matches."""
    mock_pinecone_index.query.return_value = MagicMock(matches=[])

    with (
        patch("app.agents.document_agent._get_pinecone_index", return_value=mock_pinecone_index),
        patch(
            "app.agents.document_agent._get_embeddings_model", return_value=mock_embeddings_model
        ),
    ):
        result = await document_agent_node(_make_state())

    assert result["retrieved_chunks"] == []
    assert result["documents_consulted"] == []


@pytest.mark.asyncio
async def test_document_agent_handles_pinecone_error(mock_pinecone_index, mock_embeddings_model):
    """Error path: Pinecone timeout should be caught and added to errors."""
    mock_pinecone_index.query.side_effect = Exception("Pinecone timeout")

    with (
        patch("app.agents.document_agent._get_pinecone_index", return_value=mock_pinecone_index),
        patch(
            "app.agents.document_agent._get_embeddings_model", return_value=mock_embeddings_model
        ),
    ):
        result = await document_agent_node(_make_state())

    assert result["retrieved_chunks"] == []
    assert any("Pinecone timeout" in e for e in result["errors"])


@pytest.mark.asyncio
async def test_document_agent_handles_embedding_error(mock_pinecone_index, mock_embeddings_model):
    """Error path: embedding failure should be caught and added to errors."""
    mock_embeddings_model.aembed_query = AsyncMock(side_effect=Exception("OpenAI rate limit"))

    with (
        patch("app.agents.document_agent._get_pinecone_index", return_value=mock_pinecone_index),
        patch(
            "app.agents.document_agent._get_embeddings_model", return_value=mock_embeddings_model
        ),
    ):
        result = await document_agent_node(_make_state())

    assert any("OpenAI rate limit" in e for e in result["errors"])
