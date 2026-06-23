"""Unit tests for s3_service."""

import base64

import pytest
from botocore.exceptions import ClientError

from app.services import s3_service


async def test_download_bytes(s3_bucket):
    """download_bytes should return raw bytes from S3."""
    s3_bucket.put_object(Bucket="test-bucket", Key="docs/manual.pdf", Body=b"PDF content here")
    result = await s3_service.download_bytes(s3_bucket, "test-bucket", "docs/manual.pdf")
    assert result == b"PDF content here"


async def test_download_as_base64(s3_bucket):
    """download_as_base64 should return the correct base64 encoding."""
    raw = b"image bytes"
    s3_bucket.put_object(Bucket="test-bucket", Key="images/photo.jpg", Body=raw)
    result = await s3_service.download_as_base64(s3_bucket, "test-bucket", "images/photo.jpg")
    assert result == base64.standard_b64encode(raw).decode("utf-8")


async def test_download_bytes_missing_key_raises(s3_bucket):
    """download_bytes should raise ClientError for a missing key."""
    with pytest.raises(ClientError):
        await s3_service.download_bytes(s3_bucket, "test-bucket", "nonexistent/key.pdf")


async def test_generate_presigned_url(s3_bucket):
    """generate_presigned_url should return a URL string."""
    s3_bucket.put_object(Bucket="test-bucket", Key="docs/doc.pdf", Body=b"content")
    url = await s3_service.generate_presigned_url(s3_bucket, "test-bucket", "docs/doc.pdf")
    assert "test-bucket" in url
    assert "doc.pdf" in url


def test_infer_media_type_jpeg():
    assert s3_service.infer_media_type("photo.jpg") == "image/jpeg"
    assert s3_service.infer_media_type("photo.jpeg") == "image/jpeg"


def test_infer_media_type_png():
    assert s3_service.infer_media_type("screenshot.PNG") == "image/png"


def test_infer_media_type_unknown():
    assert s3_service.infer_media_type("file.xyz") == "application/octet-stream"


def test_infer_media_type_no_extension():
    assert s3_service.infer_media_type("README") == "application/octet-stream"
