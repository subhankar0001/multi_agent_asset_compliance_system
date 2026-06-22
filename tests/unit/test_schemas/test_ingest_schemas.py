"""Unit tests for ingest schemas."""

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from app.schemas.ingest import IngestRequest, IngestResponse, S3Document


def _make_doc(**kwargs) -> dict:
    base = {
        "s3_key": "docs/manual.pdf",
        "doc_id": "manual-v1",
        "doc_type": "user_manual",
        "filename": "manual.pdf",
    }
    return {**base, **kwargs}


def test_s3_document_valid():
    doc = S3Document(**_make_doc())
    assert doc.doc_id == "manual-v1"
    assert doc.doc_type == "user_manual"


def test_s3_document_invalid_doc_type():
    with pytest.raises(ValidationError):
        S3Document(**_make_doc(doc_type="unknown_type"))


def test_ingest_request_create_event():
    req = IngestRequest(
        asset_id="abc-123",
        event="create",
        documents=[_make_doc()],
    )
    assert req.event == "create"
    assert len(req.documents) == 1


def test_ingest_request_empty_documents_rejected():
    with pytest.raises(ValidationError):
        IngestRequest(asset_id="abc-123", event="create", documents=[])


def test_ingest_request_too_many_documents_rejected():
    with pytest.raises(ValidationError):
        IngestRequest(
            asset_id="abc-123",
            event="add",
            documents=[_make_doc(doc_id=f"doc-{i}") for i in range(51)],
        )


def test_ingest_request_invalid_event():
    with pytest.raises(ValidationError):
        IngestRequest(asset_id="abc-123", event="delete", documents=[_make_doc()])


def test_ingest_response_model():
    resp = IngestResponse(
        asset_id="abc-123",
        event="create",
        documents_processed=2,
        vectors_upserted=10,
        vectors_deleted=0,
        completed_at=datetime.now(UTC),
        namespace="asset_abc-123",
    )
    assert resp.namespace == "asset_abc-123"
