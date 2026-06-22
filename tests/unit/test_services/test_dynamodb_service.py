"""
Unit tests for app/services/dynamodb_service.py

Tests all CRUD operations against a moto-mocked DynamoDB table.
No real AWS calls are made.
"""

import boto3
import pytest
from botocore.exceptions import ClientError
from moto import mock_aws

# conftest.py sets all required env vars before any test module is loaded,
# so this top-level import is safe (env vars are already present).
from app.services import dynamodb_service

TABLE_NAME = "test-audit-runs-table"
REGION = "us-east-1"


@pytest.fixture()
def dynamodb_client():
    """Provide a moto-mocked DynamoDB client with the AuditRunsTable created."""
    with mock_aws():
        client = boto3.client("dynamodb", region_name=REGION)
        client.create_table(
            TableName=TABLE_NAME,
            BillingMode="PAY_PER_REQUEST",
            AttributeDefinitions=[
                {"AttributeName": "run_id", "AttributeType": "S"},
                {"AttributeName": "asset_id", "AttributeType": "S"},
            ],
            KeySchema=[{"AttributeName": "run_id", "KeyType": "HASH"}],
            GlobalSecondaryIndexes=[
                {
                    "IndexName": "AssetIdIndex",
                    "KeySchema": [{"AttributeName": "asset_id", "KeyType": "HASH"}],
                    "Projection": {"ProjectionType": "ALL"},
                }
            ],
        )
        yield client


class TestPutAuditRun:
    """Tests for put_audit_run()."""

    def test_creates_record_in_progress(self, dynamodb_client):
        """put_audit_run should create a new IN_PROGRESS record."""
        dynamodb_service.put_audit_run(dynamodb_client, TABLE_NAME, "run-001", "asset-abc")

        response = dynamodb_client.get_item(
            TableName=TABLE_NAME,
            Key={"run_id": {"S": "run-001"}},
        )
        item = response["Item"]
        assert item["status"]["S"] == dynamodb_service.STATUS_IN_PROGRESS
        assert item["asset_id"]["S"] == "asset-abc"
        assert "created_at" in item
        assert "expires_at" in item

    def test_raises_on_duplicate_run_id(self, dynamodb_client):
        """put_audit_run should raise on a duplicate run_id (ConditionalCheckFailed)."""
        dynamodb_service.put_audit_run(dynamodb_client, TABLE_NAME, "run-dup", "asset-abc")

        with pytest.raises(ClientError, match="ConditionalCheckFailed"):
            # Second call should fail the ConditionExpression
            dynamodb_service.put_audit_run(dynamodb_client, TABLE_NAME, "run-dup", "asset-abc")


class TestGetAuditRun:
    """Tests for get_audit_run()."""

    def test_returns_none_for_unknown_run(self, dynamodb_client):
        """get_audit_run should return None for a non-existent run_id."""
        result = dynamodb_service.get_audit_run(dynamodb_client, TABLE_NAME, "not-exist")
        assert result is None

    def test_returns_dict_for_existing_run(self, dynamodb_client):
        """get_audit_run should return a dict with status and asset_id."""
        dynamodb_service.put_audit_run(dynamodb_client, TABLE_NAME, "run-get", "asset-xyz")
        result = dynamodb_service.get_audit_run(dynamodb_client, TABLE_NAME, "run-get")

        assert result is not None
        assert result["run_id"] == "run-get"
        assert result["asset_id"] == "asset-xyz"
        assert result["status"] == dynamodb_service.STATUS_IN_PROGRESS
        assert "verdict" not in result  # verdict not present until COMPLETE

    def test_returns_verdict_when_complete(self, dynamodb_client):
        """get_audit_run should include the verdict dict when status is COMPLETE."""
        dynamodb_service.put_audit_run(dynamodb_client, TABLE_NAME, "run-done", "asset-xyz")
        verdict = {"compliance_status": "COMPLIANT", "confidence": 0.95}
        dynamodb_service.complete_audit_run(dynamodb_client, TABLE_NAME, "run-done", verdict)

        result = dynamodb_service.get_audit_run(dynamodb_client, TABLE_NAME, "run-done")
        assert result is not None
        assert result["status"] == dynamodb_service.STATUS_COMPLETE
        assert result["verdict"]["compliance_status"] == "COMPLIANT"


class TestCompleteAuditRun:
    """Tests for complete_audit_run()."""

    def test_sets_status_to_complete(self, dynamodb_client):
        """complete_audit_run should update status to COMPLETE and store verdict."""
        dynamodb_service.put_audit_run(dynamodb_client, TABLE_NAME, "run-c", "asset-abc")
        verdict = {"compliance_status": "NON_COMPLIANT", "confidence": 0.87}
        dynamodb_service.complete_audit_run(dynamodb_client, TABLE_NAME, "run-c", verdict)

        result = dynamodb_service.get_audit_run(dynamodb_client, TABLE_NAME, "run-c")
        assert result["status"] == dynamodb_service.STATUS_COMPLETE
        assert result["verdict"]["compliance_status"] == "NON_COMPLIANT"


class TestFailAuditRun:
    """Tests for fail_audit_run()."""

    def test_sets_status_to_failed(self, dynamodb_client):
        """fail_audit_run should update status to FAILED."""
        dynamodb_service.put_audit_run(dynamodb_client, TABLE_NAME, "run-f", "asset-abc")
        dynamodb_service.fail_audit_run(dynamodb_client, TABLE_NAME, "run-f", "LLM timeout")

        result = dynamodb_service.get_audit_run(dynamodb_client, TABLE_NAME, "run-f")
        assert result["status"] == dynamodb_service.STATUS_FAILED


class TestEraseAssetRuns:
    """Tests for erase_asset_runs()."""

    def test_erases_all_runs_for_asset(self, dynamodb_client):
        """erase_asset_runs should mark all runs for an asset as ERASED."""
        dynamodb_service.put_audit_run(dynamodb_client, TABLE_NAME, "run-e1", "erase-asset")
        dynamodb_service.put_audit_run(dynamodb_client, TABLE_NAME, "run-e2", "erase-asset")
        dynamodb_service.put_audit_run(dynamodb_client, TABLE_NAME, "run-e3", "other-asset")

        count = dynamodb_service.erase_asset_runs(dynamodb_client, TABLE_NAME, "erase-asset")

        assert count == 2

        r1 = dynamodb_service.get_audit_run(dynamodb_client, TABLE_NAME, "run-e1")
        r2 = dynamodb_service.get_audit_run(dynamodb_client, TABLE_NAME, "run-e2")
        r3 = dynamodb_service.get_audit_run(dynamodb_client, TABLE_NAME, "run-e3")
        assert r1["status"] == dynamodb_service.STATUS_ERASED
        assert r2["status"] == dynamodb_service.STATUS_ERASED
        assert r3["status"] == dynamodb_service.STATUS_IN_PROGRESS  # different asset — untouched

    def test_returns_zero_for_no_runs(self, dynamodb_client):
        """erase_asset_runs should return 0 if no records exist for the asset."""
        count = dynamodb_service.erase_asset_runs(dynamodb_client, TABLE_NAME, "ghost-asset")
        assert count == 0


class TestGetAssetRunSummary:
    """Tests for get_asset_run_summary()."""

    def test_returns_status_counts(self, dynamodb_client):
        """get_asset_run_summary should count runs by status."""
        dynamodb_service.put_audit_run(dynamodb_client, TABLE_NAME, "run-s1", "sum-asset")
        dynamodb_service.put_audit_run(dynamodb_client, TABLE_NAME, "run-s2", "sum-asset")
        dynamodb_service.complete_audit_run(dynamodb_client, TABLE_NAME, "run-s2", {})

        summary = dynamodb_service.get_asset_run_summary(dynamodb_client, TABLE_NAME, "sum-asset")
        assert summary["asset_id"] == "sum-asset"
        assert summary["total_runs"] == 2
        assert summary["status_counts"][dynamodb_service.STATUS_IN_PROGRESS] == 1
        assert summary["status_counts"][dynamodb_service.STATUS_COMPLETE] == 1
        assert summary["latest_run_at"] is not None

    def test_returns_empty_summary_for_unknown_asset(self, dynamodb_client):
        """get_asset_run_summary should return zero counts for an asset with no runs."""
        summary = dynamodb_service.get_asset_run_summary(dynamodb_client, TABLE_NAME, "no-asset")
        assert summary["total_runs"] == 0
        assert summary["latest_run_at"] is None
