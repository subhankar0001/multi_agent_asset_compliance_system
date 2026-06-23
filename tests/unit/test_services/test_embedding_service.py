"""Unit tests for embedding_service."""

from unittest.mock import AsyncMock

import pytest

from app.services.embedding_service import embed_query, embed_texts


@pytest.mark.asyncio
async def test_embed_texts_returns_one_vector_per_text(mock_embeddings_model):
    """embed_texts should return exactly one embedding per input string."""
    texts = ["text one", "text two", "text three"]
    result = await embed_texts(mock_embeddings_model, texts)
    assert len(result) == 3
    assert len(result[0]) == 1536


@pytest.mark.asyncio
async def test_embed_texts_batches_large_input(mock_embeddings_model):
    """embed_texts should make multiple API calls based on embedding_batch_size (default 50)."""
    mock_embeddings_model.aembed_documents = AsyncMock(
        side_effect=[
            [[0.1] * 1536 for _ in range(50)],
            [[0.2] * 1536 for _ in range(50)],
            [[0.3] * 1536 for _ in range(50)],
        ]
    )
    texts = [f"text {i}" for i in range(150)]
    result = await embed_texts(mock_embeddings_model, texts)
    assert len(result) == 150
    assert mock_embeddings_model.aembed_documents.call_count == 3


@pytest.mark.asyncio
async def test_embed_query_returns_single_vector(mock_embeddings_model):
    """embed_query should return a single flat list of floats."""
    result = await embed_query(mock_embeddings_model, "What is the max pressure?")
    assert isinstance(result, list)
    assert len(result) == 1536
    assert all(isinstance(x, float) for x in result)


@pytest.mark.asyncio
async def test_embed_texts_propagates_api_error(mock_embeddings_model):
    """embed_texts should re-raise after exhausting retries."""
    mock_embeddings_model.aembed_documents = AsyncMock(side_effect=Exception("Connection error"))
    with pytest.raises(Exception, match="Connection error"):
        await embed_texts(mock_embeddings_model, ["test"])
