"""
Pydantic schemas for the admin management endpoints.

Defines request and response models for:
  GET  /api/v1/admin/assets/{asset_id}/stats
  DELETE /api/v1/admin/assets/{asset_id}
"""

from pydantic import BaseModel, Field


class AssetStatsResponse(BaseModel):
    """Operational statistics for a single asset's data across all stores."""

    asset_id: str = Field(..., description="Asset UUID")

    # Pinecone namespace stats
    pinecone_namespace: str = Field(..., description="Pinecone namespace key")
    pinecone_vector_count: int = Field(
        ...,
        ge=0,
        description="Total vectors stored in the asset's Pinecone namespace",
    )

    # DynamoDB audit run stats
    total_audit_runs: int = Field(..., ge=0, description="Total audit runs recorded")
    audit_run_status_counts: dict[str, int] = Field(
        default_factory=dict,
        description="Count of audit runs by status (IN_PROGRESS, COMPLETE, FAILED, ERASED)",
    )
    latest_audit_run_at: str | None = Field(
        default=None,
        description="ISO 8601 timestamp of the most recent audit run for this asset",
    )


class AssetDeleteResponse(BaseModel):
    """Result of a GDPR erasure request for a single asset."""

    asset_id: str = Field(..., description="Asset UUID that was erased")
    pinecone_vectors_deleted: int = Field(
        ...,
        ge=0,
        description="Number of Pinecone vectors deleted from the asset namespace",
    )
    audit_runs_erased: int = Field(
        ...,
        ge=0,
        description="Number of DynamoDB audit run records marked as ERASED",
    )
    message: str = Field(
        ...,
        description="Human-readable confirmation of the erasure operation",
    )
