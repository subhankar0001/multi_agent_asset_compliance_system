"""
S3 service — download documents and images for processing.

Provides:
  - Raw byte download for PDF processing
  - Base64 download for LLM vision calls (multimodal content blocks)
  - Presigned URL generation for secure temporary access
  - MIME type inference from filename extension

All download functions include tenacity retry logic for transient S3 errors.
"""

import asyncio
import base64
from typing import Any

import structlog
from tenacity import retry, stop_after_attempt, wait_exponential

logger = structlog.get_logger(__name__)


_MIME_MAP: dict[str, str] = {
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "png": "image/png",
    "gif": "image/gif",
    "webp": "image/webp",
    "pdf": "application/pdf",
}


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    reraise=True,
)
def _download_bytes_sync(s3_client: Any, bucket: str, key: str) -> bytes:
    """Download an S3 object and return its raw bytes synchronously."""
    response = s3_client.get_object(Bucket=bucket, Key=key)
    data: bytes = response["Body"].read()
    logger.debug("s3_download_complete", bucket=bucket, key=key, size_bytes=len(data))
    return data


async def download_bytes(s3_client: Any, bucket: str, key: str) -> bytes:
    """Download an S3 object and return its raw bytes asynchronously using a worker thread."""
    return await asyncio.to_thread(_download_bytes_sync, s3_client, bucket, key)


def _download_as_base64_sync(s3_client: Any, bucket: str, key: str) -> str:
    """Download an S3 image and return it as a base64-encoded string synchronously."""
    raw = _download_bytes_sync(s3_client, bucket, key)
    encoded = base64.standard_b64encode(raw).decode("utf-8")
    logger.debug("s3_base64_encoded", bucket=bucket, key=key)
    return encoded


async def download_as_base64(s3_client: Any, bucket: str, key: str) -> str:
    """
    Download an S3 image and return it as a base64-encoded string asynchronously.

    Used for LLM multimodal vision calls where images must be passed
    as base64 in the content block (not as URLs).
    """
    return await asyncio.to_thread(_download_as_base64_sync, s3_client, bucket, key)


def _generate_presigned_url_sync(
    s3_client: Any,
    bucket: str,
    key: str,
    expiry_seconds: int = 3600,
) -> str:
    """Generate a presigned URL synchronously."""
    url: str = s3_client.generate_presigned_url(
        "get_object",
        Params={"Bucket": bucket, "Key": key},
        ExpiresIn=expiry_seconds,
    )
    logger.debug("presigned_url_generated", bucket=bucket, key=key, expiry=expiry_seconds)
    return url


async def generate_presigned_url(
    s3_client: Any,
    bucket: str,
    key: str,
    expiry_seconds: int = 3600,
) -> str:
    """
    Generate a presigned URL for temporary, authenticated S3 object access asynchronously.

    Default expiry is 1 hour. All audit images are accessed via presigned
    URLs — never made public.
    """
    return await asyncio.to_thread(
        _generate_presigned_url_sync, s3_client, bucket, key, expiry_seconds
    )


def infer_media_type(filename: str) -> str:
    """
    Infer the MIME type from a file extension.

    Used when constructing LLM vision content blocks that require an
    explicit media_type field. Falls back to 'application/octet-stream'
    for unrecognised extensions.
    """
    ext = filename.lower().rsplit(".", 1)[-1] if "." in filename else ""
    return _MIME_MAP.get(ext, "application/octet-stream")


def _delete_asset_documents_sync(s3_client: Any, bucket: str, asset_id: str) -> int:
    """Delete all S3 objects under an asset prefix synchronously."""
    prefix = f"{asset_id}/"
    paginator = s3_client.get_paginator("list_objects_v2")
    deleted_count = 0

    try:
        for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
            if "Contents" in page:
                objects = [{"Key": obj["Key"]} for obj in page["Contents"]]
                if objects:
                    response = s3_client.delete_objects(
                        Bucket=bucket,
                        Delete={"Objects": objects, "Quiet": True}
                    )
                    deleted_count += len(objects)
    except Exception as e:
        error_name = type(e).__name__
        if "NoSuchBucket" in error_name:
            logger.debug("s3_bucket_not_found_for_erasure", bucket=bucket)
            return 0
        raise
                
    logger.debug("s3_asset_documents_deleted", bucket=bucket, asset_id=asset_id, count=deleted_count)
    return deleted_count


async def delete_asset_documents(s3_client: Any, bucket: str, asset_id: str) -> int:
    """
    Delete all S3 objects associated with an asset.
    Used for GDPR right-to-erasure compliance.
    """
    return await asyncio.to_thread(_delete_asset_documents_sync, s3_client, bucket, asset_id)
