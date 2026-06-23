"""Unit tests for web_search_service."""

from unittest.mock import MagicMock, patch

import pytest

from app.services import web_search_service


@pytest.mark.asyncio
async def test_search_success():
    """Happy path: search returns formatted search results."""
    mock_ddg_instance = MagicMock()
    mock_ddg_instance.text.return_value = [
        {"title": "Result 1", "href": "https://example.com/1", "body": "Content 1"},
        {"title": "Result 2", "href": "https://example.com/2", "body": "Content 2"},
    ]

    with patch("app.services.web_search_service.DDGS") as mock_ddgs:
        # Mock context manager
        mock_ddgs.return_value.__enter__.return_value = mock_ddg_instance

        results = await web_search_service.search("test query", max_results=2)

    assert len(results) == 2
    assert results[0]["title"] == "Result 1"
    assert results[0]["url"] == "https://example.com/1"
    assert results[0]["content"] == "Content 1"
    assert results[0]["score"] == 1.0
    mock_ddg_instance.text.assert_called_once_with("test query", max_results=2)


@pytest.mark.asyncio
async def test_search_empty():
    """Search returns empty list if no results found."""
    mock_ddg_instance = MagicMock()
    mock_ddg_instance.text.return_value = []

    with patch("app.services.web_search_service.DDGS") as mock_ddgs:
        mock_ddgs.return_value.__enter__.return_value = mock_ddg_instance

        results = await web_search_service.search("empty query")

    assert results == []
