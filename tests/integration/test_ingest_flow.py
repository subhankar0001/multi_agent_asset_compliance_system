"""
Integration tests for the document ingestion flow.

Tests the full HTTP request → ingest handler → Pinecone upsert chain
using moto for S3 and mock clients for Pinecone and OpenAI.
No real network calls are made.
"""

from unittest.mock import MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import create_app

# Required X-API-Key header for all authenticated requests
_API_KEY = "test-secret-key-minimum-32-chars-long"
_HEADERS = {"X-API-Key": _API_KEY}


@pytest.mark.asyncio
async def test_ingest_create_event(s3_bucket, mock_pinecone_index, mock_embeddings_model):
    """POST /ingest with create event should return 200 and upsert vectors."""
    # Upload a fake PDF to mock S3
    s3_bucket.put_object(
        Bucket="test-bucket",
        Key="manuals/pump_v2.pdf",
        Body=b"%PDF-1.4 fake pdf content with text",
    )
    mock_pinecone_index.describe_index_stats.return_value = MagicMock(namespaces={})

    app = create_app()
    with (
        patch("app.dependencies._get_pinecone_index", return_value=mock_pinecone_index),
        patch("app.dependencies._get_embeddings_model", return_value=mock_embeddings_model),
        patch("app.dependencies._get_s3_client", return_value=s3_bucket),
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(
                "/api/v1/ingest",
                json={
                    "asset_id": "abc-123",
                    "event": "create",
                    "documents": [
                        {
                            "s3_key": "manuals/pump_v2.pdf",
                            "doc_id": "manual-v2",
                            "doc_type": "user_manual",
                            "filename": "pump_v2.pdf",
                        }
                    ],
                },
                headers=_HEADERS,
            )

    assert response.status_code == 200
    body = response.json()
    assert body["asset_id"] == "abc-123"
    assert body["event"] == "create"
    assert body["namespace"] == "asset_abc-123"


@pytest.mark.asyncio
async def test_ingest_create_idempotent(s3_bucket, mock_pinecone_index, mock_embeddings_model):
    """POST /ingest with create event on existing namespace should be a no-op."""
    # Namespace already has docs
    mock_pinecone_index.describe_index_stats.return_value = MagicMock(
        namespaces={"asset_abc-123": MagicMock(vector_count=10)}
    )

    app = create_app()
    with (
        patch("app.dependencies._get_pinecone_index", return_value=mock_pinecone_index),
        patch("app.dependencies._get_embeddings_model", return_value=mock_embeddings_model),
        patch("app.dependencies._get_s3_client", return_value=s3_bucket),
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(
                "/api/v1/ingest",
                json={
                    "asset_id": "abc-123",
                    "event": "create",
                    "documents": [
                        {
                            "s3_key": "manuals/pump_v2.pdf",
                            "doc_id": "manual-v2",
                            "doc_type": "user_manual",
                            "filename": "pump_v2.pdf",
                        }
                    ],
                },
                headers=_HEADERS,
            )

    assert response.status_code == 200
    body = response.json()
    # Should be a no-op — zero vectors processed
    assert body["documents_processed"] == 0
    assert body["vectors_upserted"] == 0


@pytest.mark.asyncio
async def test_ingest_update_requires_single_document(
    s3_bucket, mock_pinecone_index, mock_embeddings_model
):
    """POST /ingest with update event and multiple documents should return 422."""
    app = create_app()
    with (
        patch("app.dependencies._get_pinecone_index", return_value=mock_pinecone_index),
        patch("app.dependencies._get_embeddings_model", return_value=mock_embeddings_model),
        patch("app.dependencies._get_s3_client", return_value=s3_bucket),
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(
                "/api/v1/ingest",
                json={
                    "asset_id": "abc-123",
                    "event": "update",
                    "documents": [
                        {
                            "s3_key": "a.pdf",
                            "doc_id": "doc-1",
                            "doc_type": "user_manual",
                            "filename": "a.pdf",
                        },
                        {
                            "s3_key": "b.pdf",
                            "doc_id": "doc-2",
                            "doc_type": "safety_sheet",
                            "filename": "b.pdf",
                        },
                    ],
                },
                headers=_HEADERS,
            )

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_ingest_missing_api_key(s3_bucket, mock_pinecone_index, mock_embeddings_model):
    """POST /ingest without X-API-Key header should return 401."""
    app = create_app()
    with (
        patch("app.dependencies._get_pinecone_index", return_value=mock_pinecone_index),
        patch("app.dependencies._get_embeddings_model", return_value=mock_embeddings_model),
        patch("app.dependencies._get_s3_client", return_value=s3_bucket),
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(
                "/api/v1/ingest",
                json={
                    "asset_id": "abc-123",
                    "event": "create",
                    "documents": [
                        {
                            "s3_key": "a.pdf",
                            "doc_id": "doc-1",
                            "doc_type": "user_manual",
                            "filename": "a.pdf",
                        }
                    ],
                },
                # No X-API-Key header
            )

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_health_check_no_auth_required():
    """GET /health should return 200 without authentication."""
    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"
