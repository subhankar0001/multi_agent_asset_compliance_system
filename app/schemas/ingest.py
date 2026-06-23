"""
Pydantic schemas for the document ingestion endpoint.

Defines the request and response models for POST /api/v1/ingest.
"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class S3Document(BaseModel):
    """Represents one document stored in S3 that belongs to an asset."""

    s3_key: str = Field(
        ...,
        pattern=r'^[a-zA-Z0-9/_\-\.]+$',
        description="Full S3 object key (path within the bucket)",
    )
    doc_id: str = Field(
        ...,
        min_length=1,
        description=(
            "Stable identifier for this document assigned by Django. "
            "The same logical document retains the same doc_id across versions. "
            "Used as the deletion filter key on update events."
        ),
    )
    doc_type: Literal[
        "user_manual",
        "safety_sheet",
        "compliance_spec",
        "installation_image",
        "other",
    ] = Field(..., description="Document category for metadata tagging and filtered retrieval")
    filename: str = Field(
        ...,
        min_length=1,
        description="Original filename for display in evidence citations",
    )


class IngestRequest(BaseModel):
    """Request body for POST /api/v1/ingest."""

    asset_id: str = Field(..., min_length=1, description="UUID of the asset in Django's database")
    event: Literal["create", "update", "add"] = Field(
        ...,
        description=(
            "create — first ingest for this asset (idempotent: skipped if namespace exists); "
            "update — replace an existing document (doc_id must match existing vectors); "
            "add — append new document(s) to an existing asset namespace"
        ),
    )
    documents: list[S3Document] = Field(
        ...,
        min_length=1,
        max_length=50,
        description="Documents to ingest. For 'update', exactly one document is expected.",
    )


class IngestResponse(BaseModel):
    """Response body for POST /api/v1/ingest."""

    asset_id: str
    event: str
    documents_processed: int
    vectors_upserted: int
    vectors_deleted: int
    completed_at: datetime
    namespace: str
