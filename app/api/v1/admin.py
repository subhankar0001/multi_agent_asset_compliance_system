"""
Admin management endpoints — operational visibility and GDPR data erasure.

Routes:
  GET  /api/v1/admin/assets/{asset_id}/stats
       Returns Pinecone vector count and DynamoDB audit run summary for an asset.
       Use for operational dashboards and capacity planning.

  DELETE /api/v1/admin/assets/{asset_id}
       Performs a full GDPR right-to-erasure for an asset:
         1. Deletes all Pinecone vectors in the asset namespace
         2. Marks all DynamoDB audit run records as ERASED
       This is irreversible — S3 objects are outside this service's scope
       and must be deleted separately via the Django asset management system.

Authentication:
  All endpoints require the X-API-Key header (same as all other routes).
  There is no separate admin role — the shared API key is sufficient since
  this service is only called from the trusted Django backend.
"""

import structlog
from fastapi import APIRouter, status

from app.dependencies import DynamoDBDep, PineconeDep, SettingsDep
from app.schemas.admin import AssetDeleteResponse, AssetStatsResponse
from app.services import dynamodb_service, pinecone_service

router = APIRouter(prefix="/admin", tags=["admin"])
logger = structlog.get_logger(__name__)


@router.get(
    "/assets/{asset_id}/stats",
    response_model=AssetStatsResponse,
    status_code=status.HTTP_200_OK,
    summary="Get asset data statistics",
    description=(
        "Returns the Pinecone vector count and DynamoDB audit run summary for "
        "a given asset. Useful for operational dashboards and capacity planning."
    ),
)
async def get_asset_stats(
    asset_id: str,
    index: PineconeDep,
    dynamodb_client: DynamoDBDep,
    settings: SettingsDep,
) -> AssetStatsResponse:
    """Return Pinecone namespace stats and audit run history for an asset."""
    log = logger.bind(asset_id=asset_id)

    # ── Pinecone namespace stats ───────────────────────────────────────────────
    stats = index.describe_index_stats()
    namespace_key = f"asset_{asset_id}"
    ns = stats.namespaces.get(namespace_key)
    vector_count = getattr(ns, "vector_count", 0) if ns else 0

    # ── DynamoDB audit run summary ─────────────────────────────────────────────
    run_summary = dynamodb_service.get_asset_run_summary(
        dynamodb_client,
        settings.dynamodb_audit_table,
        asset_id,
    )

    log.info(
        "admin_asset_stats_fetched",
        vector_count=vector_count,
        total_runs=run_summary["total_runs"],
    )

    return AssetStatsResponse(
        asset_id=asset_id,
        pinecone_namespace=namespace_key,
        pinecone_vector_count=vector_count,
        total_audit_runs=run_summary["total_runs"],
        audit_run_status_counts=run_summary["status_counts"],
        latest_audit_run_at=run_summary["latest_run_at"],
    )


@router.delete(
    "/assets/{asset_id}",
    response_model=AssetDeleteResponse,
    status_code=status.HTTP_200_OK,
    summary="Erase all asset data (GDPR right-to-erasure)",
    description=(
        "Permanently deletes all Pinecone vectors for the asset and marks all "
        "DynamoDB audit run records as ERASED. "
        "⚠️ This operation is irreversible. "
        "S3 documents must be deleted separately via the Django asset management system."
    ),
)
async def delete_asset(
    asset_id: str,
    index: PineconeDep,
    dynamodb_client: DynamoDBDep,
    settings: SettingsDep,
) -> AssetDeleteResponse:
    """Erase all stored data for an asset (GDPR Article 17 compliance)."""
    log = logger.bind(asset_id=asset_id)
    log.warning("admin_asset_erasure_initiated", asset_id=asset_id)

    # ── Delete Pinecone vectors ────────────────────────────────────────────────
    vectors_deleted = pinecone_service.delete_namespace(index, asset_id)

    # ── Erase DynamoDB audit run records ──────────────────────────────────────
    runs_erased = dynamodb_service.erase_asset_runs(
        dynamodb_client,
        settings.dynamodb_audit_table,
        asset_id,
    )

    log.warning(
        "admin_asset_erasure_complete",
        vectors_deleted=vectors_deleted,
        runs_erased=runs_erased,
    )

    return AssetDeleteResponse(
        asset_id=asset_id,
        pinecone_vectors_deleted=vectors_deleted,
        audit_runs_erased=runs_erased,
        message=(
            f"Asset '{asset_id}' data erased: {vectors_deleted} Pinecone vectors deleted, "
            f"{runs_erased} audit run records marked as ERASED. "
            "S3 documents must be deleted separately."
        ),
    )
