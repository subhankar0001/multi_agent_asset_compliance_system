"""Unit tests for offline mock clients (LocalS3Client, LocalDynamoDBClient, LocalPineconeIndex)."""

import io
import json
from pathlib import Path

import pytest
from botocore.exceptions import ClientError

from app.utils.offline_clients import (
    ConditionalCheckFailedException,
    LocalDynamoDBClient,
    LocalPineconeIndex,
    LocalS3Client,
)

# ── LocalS3Client Tests ───────────────────────────────────────────────────────


def test_local_s3_client_put_and_get(tmp_path: Path) -> None:
    """Test putting and getting objects from LocalS3Client."""
    s3_dir = tmp_path / "s3"
    client = LocalS3Client(s3_dir)

    # Test put_object with bytes
    client.put_object(Bucket="my-bucket", Key="docs/file1.txt", Body=b"hello world")

    # Test get_object
    response = client.get_object(Bucket="my-bucket", Key="docs/file1.txt")
    assert response["ResponseMetadata"]["HTTPStatusCode"] == 200
    assert response["Body"].read() == b"hello world"

    # Test put_object with file-like object
    body_io = io.BytesIO(b"file-like data")
    client.put_object(Bucket="my-bucket", Key="docs/file2.txt", Body=body_io)

    response = client.get_object(Bucket="my-bucket", Key="docs/file2.txt")
    assert response["Body"].read() == b"file-like data"


def test_local_s3_client_missing_key(tmp_path: Path) -> None:
    """Test get_object raises NoSuchKey ClientError for nonexistent files."""
    s3_dir = tmp_path / "s3"
    client = LocalS3Client(s3_dir)

    with pytest.raises(ClientError) as exc_info:
        client.get_object(Bucket="my-bucket", Key="nonexistent.txt")

    assert exc_info.value.response["Error"]["Code"] == "NoSuchKey"


def test_local_s3_client_generate_presigned_url(tmp_path: Path) -> None:
    """Test generate_presigned_url returns a valid file URI."""
    s3_dir = tmp_path / "s3"
    client = LocalS3Client(s3_dir)

    url = client.generate_presigned_url(
        "get_object", Params={"Bucket": "my-bucket", "Key": "images/test.png"}
    )
    assert url.startswith("file://")
    assert "my-bucket/images/test.png" in url


# ── LocalDynamoDBClient Tests ─────────────────────────────────────────────────


def test_local_dynamodb_client_flow(tmp_path: Path) -> None:
    """Test basic write, read, update, and query flow for LocalDynamoDBClient."""
    db_file = tmp_path / "dynamodb.db"
    client = LocalDynamoDBClient(db_file)

    # Write items
    item_1 = {
        "run_id": {"S": "run-1"},
        "asset_id": {"S": "asset-abc"},
        "status": {"S": "IN_PROGRESS"},
        "created_at": {"S": "2026-06-22T12:00:00Z"},
        "updated_at": {"S": "2026-06-22T12:00:00Z"},
        "expires_at": {"N": "1782132000"},
    }
    client.put_item(TableName="audit_runs", Item=item_1)

    # Get item
    fetched = client.get_item(TableName="audit_runs", Key={"run_id": {"S": "run-1"}})
    assert fetched["Item"]["run_id"]["S"] == "run-1"
    assert fetched["Item"]["status"]["S"] == "IN_PROGRESS"
    assert "verdict" not in fetched["Item"]

    # Test conditional put (ConditionalCheckFailedException expected)
    with pytest.raises(ConditionalCheckFailedException):
        client.put_item(
            TableName="audit_runs", Item=item_1, ConditionExpression="attribute_not_exists(run_id)"
        )

    # Update item to complete status with verdict
    verdict = {"compliance_status": "COMPLIANT", "confidence": 0.9}
    client.update_item(
        TableName="audit_runs",
        Key={"run_id": {"S": "run-1"}},
        UpdateExpression="SET #s = :s, verdict = :v, updated_at = :u",
        ExpressionAttributeValues={
            ":s": {"S": "COMPLETE"},
            ":v": {"S": json.dumps(verdict)},
            ":u": {"S": "2026-06-22T12:05:00Z"},
        },
    )

    fetched_updated = client.get_item(TableName="audit_runs", Key={"run_id": {"S": "run-1"}})
    assert fetched_updated["Item"]["status"]["S"] == "COMPLETE"
    assert fetched_updated["Item"]["verdict"]["S"] == json.dumps(verdict)

    # Query items by asset
    query_resp = client.query(
        TableName="audit_runs",
        IndexName="AssetIdIndex",
        ExpressionAttributeValues={":aid": {"S": "asset-abc"}},
    )
    assert len(query_resp["Items"]) == 1
    assert query_resp["Items"][0]["run_id"]["S"] == "run-1"


def test_local_dynamodb_client_fail_run(tmp_path: Path) -> None:
    """Test updating status to FAILED with error message."""
    db_file = tmp_path / "dynamodb.db"
    client = LocalDynamoDBClient(db_file)

    item = {
        "run_id": {"S": "run-2"},
        "asset_id": {"S": "asset-xyz"},
        "status": {"S": "IN_PROGRESS"},
        "created_at": {"S": "2026-06-22T12:00:00Z"},
        "updated_at": {"S": "2026-06-22T12:00:00Z"},
        "expires_at": {"N": "1782132000"},
    }
    client.put_item(TableName="audit_runs", Item=item)

    client.update_item(
        TableName="audit_runs",
        Key={"run_id": {"S": "run-2"}},
        UpdateExpression="SET #s = :s, error_message = :e, updated_at = :u",
        ExpressionAttributeValues={
            ":s": {"S": "FAILED"},
            ":e": {"S": "Out of memory"},
            ":u": {"S": "2026-06-22T12:05:00Z"},
        },
    )

    fetched = client.get_item(TableName="audit_runs", Key={"run_id": {"S": "run-2"}})
    assert fetched["Item"]["status"]["S"] == "FAILED"
    assert fetched["Item"]["error_message"]["S"] == "Out of memory"


# ── LocalPineconeIndex Tests ──────────────────────────────────────────────────


def test_local_pinecone_index_operations(tmp_path: Path) -> None:
    """Test upserting, querying, deleting, and stats in LocalPineconeIndex."""
    qdrant_dir = tmp_path / "qdrant_test"
    index = LocalPineconeIndex(qdrant_dir, 3)

    # Initial stats check
    stats = index.describe_index_stats()
    assert "asset_123" not in stats.namespaces

    # Upsert vectors
    vectors = [
        {
            "id": "vec1",
            "values": [1.0, 0.0, 0.0],
            "metadata": {"doc_id": "docA", "doc_type": "manual", "text": "pump description"},
        },
        {
            "id": "vec2",
            "values": [0.0, 1.0, 0.0],
            "metadata": {"doc_id": "docA", "doc_type": "manual", "text": "valve description"},
        },
        {
            "id": "vec3",
            "values": [0.0, 0.0, 1.0],
            "metadata": {"doc_id": "docB", "doc_type": "datasheet", "text": "safety limits"},
        },
    ]
    upsert_resp = index.upsert(vectors=vectors, namespace="asset_123")
    assert upsert_resp["upserted_count"] == 3

    # Check stats after upsert
    stats_after = index.describe_index_stats()
    assert stats_after.namespaces["asset_123"].vector_count == 3

    # Query with exact match
    query_resp = index.query(
        vector=[1.0, 0.0, 0.0], top_k=2, namespace="asset_123", include_metadata=True
    )
    assert len(query_resp.matches) == 2
    assert query_resp.matches[0].id == "vec1"
    assert query_resp.matches[0].score == pytest.approx(1.0)
    assert query_resp.matches[0].metadata["text"] == "pump description"

    # Query with filter
    query_filtered = index.query(
        vector=[0.0, 1.0, 0.0],
        top_k=2,
        namespace="asset_123",
        include_metadata=True,
        filter={"doc_type": {"$eq": "datasheet"}},
    )
    assert len(query_filtered.matches) == 1
    assert query_filtered.matches[0].id == "vec3"

    # Delete by doc_id
    index.delete(filter={"doc_id": {"$eq": "docA"}}, namespace="asset_123")
    stats_after_delete = index.describe_index_stats()
    assert stats_after_delete.namespaces["asset_123"].vector_count == 1

    # Delete all
    index.delete(delete_all=True, namespace="asset_123")
    stats_final = index.describe_index_stats()
    assert "asset_123" not in stats_final.namespaces
