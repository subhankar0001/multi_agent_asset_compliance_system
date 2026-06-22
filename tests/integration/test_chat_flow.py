"""
Integration tests for the chat query flow.

Tests all three retrieval tiers:
  1. Pinecone RAG (score >= 0.75)
  2. Asset spec fallback (score < 0.75)
  3. Web search augmentation (score < 0.75, triggers Tavily)
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import create_app

_API_KEY = "test-secret-key-minimum-32-chars-long"
_HEADERS = {"X-API-Key": _API_KEY}

_CHAT_PAYLOAD = {
    "asset_id": "abc-123",
    "asset_spec": {
        "name": "Hydraulic Pump HP-5000",
        "category": "pump",
        "manufacturer": "HydroTech",
    },
    "question": "What is the maximum operating pressure?",
}


def _make_pinecone_match(score: float) -> MagicMock:
    match = MagicMock()
    match.id = "abc-123_manual-v2_p1_c0"
    match.score = score
    match.metadata = {
        "doc_id": "manual-v2",
        "doc_type": "user_manual",
        "filename": "pump_manual.pdf",
        "page": 5,
        "text": "Maximum operating pressure is 150 PSI.",
    }
    return match


class MockMessage:
    def __init__(self, content):
        self.content = content


@pytest.mark.asyncio
async def test_chat_pinecone_rag_tier(mock_pinecone_index, mock_embeddings_model, mock_chat_model):
    """When Pinecone score >= 0.75, response should use pinecone_rag search path."""
    mock_pinecone_index.query.return_value = MagicMock(matches=[_make_pinecone_match(0.92)])
    mock_chat_model.ainvoke = AsyncMock(
        return_value=MockMessage("The maximum operating pressure is 150 PSI.")
    )

    app = create_app()
    with (
        patch("app.dependencies._get_pinecone_index", return_value=mock_pinecone_index),
        patch("app.dependencies._get_embeddings_model", return_value=mock_embeddings_model),
        patch("app.dependencies._get_agent_llm", return_value=mock_chat_model),
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(
                "/api/v1/chat/query",
                json=_CHAT_PAYLOAD,
                headers=_HEADERS,
            )

    assert response.status_code == 200
    body = response.json()
    assert body["search_path"] == "pinecone_rag"
    assert not body["web_search_used"]
    assert len(body["sources"]) == 1
    assert body["sources"][0]["filename"] == "pump_manual.pdf"


@pytest.mark.asyncio
async def test_chat_asset_spec_fallback_tier(
    mock_pinecone_index, mock_embeddings_model, mock_chat_model, mock_tavily_client
):
    """When Pinecone score < 0.75 and Tavily returns no results, use asset_spec path."""
    # Low score — will trigger fallback
    mock_pinecone_index.query.return_value = MagicMock(matches=[_make_pinecone_match(0.40)])
    mock_chat_model.ainvoke = AsyncMock(
        return_value=MockMessage("Based on the asset spec, the pump is a HydroTech HP-5000.")
    )

    app = create_app()
    with (
        patch("app.dependencies._get_pinecone_index", return_value=mock_pinecone_index),
        patch("app.dependencies._get_embeddings_model", return_value=mock_embeddings_model),
        patch("app.dependencies._get_agent_llm", return_value=mock_chat_model),
        patch("app.services.web_search_service.search", return_value=[]),
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(
                "/api/v1/chat/query",
                json=_CHAT_PAYLOAD,
                headers=_HEADERS,
            )

    assert response.status_code == 200
    body = response.json()
    assert body["search_path"] == "asset_spec"
    assert not body["web_search_used"]


@pytest.mark.asyncio
async def test_chat_web_search_tier(mock_pinecone_index, mock_embeddings_model, mock_chat_model):
    """When Pinecone scores < 0.75 and Tavily returns results, use web_search path."""
    mock_pinecone_index.query.return_value = MagicMock(matches=[])  # No results

    mock_chat_model.ainvoke = AsyncMock(
        return_value=MockMessage("According to web sources, HP-5000 max pressure is 150 PSI.")
    )

    web_results = [
        {
            "url": "https://hydrotech.example.com/specs",
            "title": "HydroTech HP-5000 Specs",
            "content": "Maximum pressure: 150 PSI",
            "score": 0.85,
        }
    ]

    app = create_app()
    with (
        patch("app.dependencies._get_pinecone_index", return_value=mock_pinecone_index),
        patch("app.dependencies._get_embeddings_model", return_value=mock_embeddings_model),
        patch("app.dependencies._get_agent_llm", return_value=mock_chat_model),
        patch("app.services.web_search_service.search", return_value=web_results),
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(
                "/api/v1/chat/query",
                json=_CHAT_PAYLOAD,
                headers=_HEADERS,
            )

    assert response.status_code == 200
    body = response.json()
    assert body["search_path"] == "web_search"
    assert body["web_search_used"] is True


@pytest.mark.asyncio
async def test_chat_with_doc_type_filter(
    mock_pinecone_index, mock_embeddings_model, mock_chat_model
):
    """chat with doc_type_filter should pass filter to Pinecone query."""
    mock_pinecone_index.query.return_value = MagicMock(matches=[_make_pinecone_match(0.85)])
    mock_chat_model.ainvoke = AsyncMock(
        return_value=MockMessage("Safety sheet says max pressure is 150 PSI.")
    )

    payload = {**_CHAT_PAYLOAD, "doc_type_filter": "safety_sheet"}

    app = create_app()
    with (
        patch("app.dependencies._get_pinecone_index", return_value=mock_pinecone_index),
        patch("app.dependencies._get_embeddings_model", return_value=mock_embeddings_model),
        patch("app.dependencies._get_agent_llm", return_value=mock_chat_model),
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(
                "/api/v1/chat/query",
                json=payload,
                headers=_HEADERS,
            )

    assert response.status_code == 200
    # Verify the filter was passed to Pinecone
    call_kwargs = mock_pinecone_index.query.call_args.kwargs
    assert call_kwargs.get("filter") == {"doc_type": {"$eq": "safety_sheet"}}
