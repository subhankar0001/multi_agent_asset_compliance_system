"""
S3 service — download documents and images for processing.

Provides:
  - Raw byte download for PDF processing
  - Base64 download for LLM vision calls (multimodal content blocks)
  - Presigned URL generation for secure temporary access
  - MIME type inference from filename extension

All download functions include tenacity retry logic for transient S3 errors.
"""

import base64
from typing import Any

import structlog
from tenacity import retry, stop_after_attempt, wait_exponential

logger = structlog.get_logger(__name__)


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    reraise=True,
)
def download_bytes(s3_client: Any, bucket: str, key: str) -> bytes:
    """Download an S3 object and return its raw bytes."""
    response = s3_client.get_object(Bucket=bucket, Key=key)
    data: bytes = response["Body"].read()
    logger.debug("s3_download_complete", bucket=bucket, key=key, size_bytes=len(data))
    return data


def download_as_base64(s3_client: Any, bucket: str, key: str) -> str:
    """
    Download an S3 image and return it as a base64-encoded string.

    Used for LLM multimodal vision calls where images must be passed
    as base64 in the content block (not as URLs).
    """
    raw = download_bytes(s3_client, bucket, key)
    encoded = base64.standard_b64encode(raw).decode("utf-8")
    logger.debug("s3_base64_encoded", bucket=bucket, key=key)
    return encoded


def generate_presigned_url(
    s3_client: Any,
    bucket: str,
    key: str,
    expiry_seconds: int = 3600,
) -> str:
    """
    Generate a presigned URL for temporary, authenticated S3 object access.

    Default expiry is 1 hour. All audit images are accessed via presigned
    URLs — never made public.
    """
    url: str = s3_client.generate_presigned_url(
        "get_object",
        Params={"Bucket": bucket, "Key": key},
        ExpiresIn=expiry_seconds,
    )
    logger.debug("presigned_url_generated", bucket=bucket, key=key, expiry=expiry_seconds)
    return url


def infer_media_type(filename: str) -> str:
    """
    Infer the MIME type from a file extension.

    Used when constructing LLM vision content blocks that require an
    explicit media_type field. Falls back to 'application/octet-stream'
    for unrecognised extensions.
    """
    ext = filename.lower().rsplit(".", 1)[-1] if "." in filename else ""
    mime_map: dict[str, str] = {
        "jpg": "image/jpeg",
        "jpeg": "image/jpeg",
        "png": "image/png",
        "gif": "image/gif",
        "webp": "image/webp",
        "pdf": "application/pdf",
    }
    return mime_map.get(ext, "application/octet-stream")
