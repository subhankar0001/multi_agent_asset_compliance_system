"""
Integration tests for the admin management endpoints.

Tests:
  GET  /api/v1/admin/assets/{asset_id}/stats
  DELETE /api/v1/admin/assets/{asset_id}

All external service calls (Pinecone, DynamoDB) are mocked.
No real AWS or Pinecone calls are made.
"""

from unittest.mock import MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import create_app

_API_KEY = "test-secret-key-minimum-32-chars-long"
_HEADERS = {"X-API-Key": _API_KEY}


@pytest.mark.asyncio
async def test_get_asset_stats_returns_correct_structure(mock_pinecone_index, mock_dynamodb_table):
    """GET /admin/assets/{asset_id}/stats should return counts from Pinecone and DynamoDB."""
    # Pinecone has 42 vectors in the asset namespace
    ns_mock = MagicMock()
    ns_mock.vector_count = 42
    mock_pinecone_index.describe_index_stats.return_value = MagicMock(
        namespaces={"asset_abc-123": ns_mock}
    )

    app = create_app()
    with (
        patch("app.dependencies._get_pinecone_index", return_value=mock_pinecone_index),
        patch("app.dependencies._get_dynamodb_client", return_value=mock_dynamodb_table),
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get(
                "/api/v1/admin/assets/abc-123/stats",
                headers=_HEADERS,
            )

    assert response.status_code == 200
    body = response.json()
    assert body["asset_id"] == "abc-123"
    assert body["pinecone_namespace"] == "asset_abc-123"
    assert body["pinecone_vector_count"] == 42
    assert "total_audit_runs" in body
    assert "audit_run_status_counts" in body


@pytest.mark.asyncio
async def test_get_asset_stats_empty_namespace(mock_pinecone_index, mock_dynamodb_table):
    """GET /admin/assets/{asset_id}/stats with no vectors should return zero count."""
    mock_pinecone_index.describe_index_stats.return_value = MagicMock(namespaces={})

    app = create_app()
    with (
        patch("app.dependencies._get_pinecone_index", return_value=mock_pinecone_index),
        patch("app.dependencies._get_dynamodb_client", return_value=mock_dynamodb_table),
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get(
                "/api/v1/admin/assets/no-data/stats",
                headers=_HEADERS,
            )

    assert response.status_code == 200
    body = response.json()
    assert body["pinecone_vector_count"] == 0
    assert body["total_audit_runs"] == 0


@pytest.mark.asyncio
async def test_delete_asset_returns_erasure_confirmation(mock_pinecone_index, mock_dynamodb_table):
    """DELETE /admin/assets/{asset_id} should delete Pinecone vectors and DynamoDB records."""
    # Pinecone: simulate 10 vectors in namespace, 0 after deletion
    before_stats = MagicMock()
    before_ns = MagicMock()
    before_ns.vector_count = 10
    before_stats.namespaces = {"asset_del-asset": before_ns}

    after_stats = MagicMock()
    after_stats.namespaces = {}

    mock_pinecone_index.describe_index_stats.side_effect = [before_stats, after_stats]
    mock_pinecone_index.delete = MagicMock()

    app = create_app()
    with (
        patch("app.dependencies._get_pinecone_index", return_value=mock_pinecone_index),
        patch("app.dependencies._get_dynamodb_client", return_value=mock_dynamodb_table),
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.delete(
                "/api/v1/admin/assets/del-asset",
                headers=_HEADERS,
            )

    assert response.status_code == 200
    body = response.json()
    assert body["asset_id"] == "del-asset"
    assert body["pinecone_vectors_deleted"] == 10
    assert "message" in body
    assert "ERASED" in body["message"] or "deleted" in body["message"]


@pytest.mark.asyncio
async def test_delete_asset_empty_namespace(mock_pinecone_index, mock_dynamodb_table):
    """DELETE /admin/assets/{asset_id} on asset with no vectors should return 0 deleted."""
    mock_pinecone_index.describe_index_stats.return_value = MagicMock(namespaces={})

    app = create_app()
    with (
        patch("app.dependencies._get_pinecone_index", return_value=mock_pinecone_index),
        patch("app.dependencies._get_dynamodb_client", return_value=mock_dynamodb_table),
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.delete(
                "/api/v1/admin/assets/ghost-asset",
                headers=_HEADERS,
            )

    assert response.status_code == 200
    body = response.json()
    assert body["pinecone_vectors_deleted"] == 0


@pytest.mark.asyncio
async def test_admin_endpoints_require_api_key(mock_pinecone_index):
    """Admin endpoints should return 401 without X-API-Key."""
    app = create_app()
    with patch("app.dependencies._get_pinecone_index", return_value=mock_pinecone_index):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            stats_response = await client.get("/api/v1/admin/assets/abc/stats")
            delete_response = await client.delete("/api/v1/admin/assets/abc")

    assert stats_response.status_code == 401
    assert delete_response.status_code == 401
