"""
DynamoDB service — audit run idempotency tracking.

Stores a record per audit run keyed on ``run_id``.  Before executing the
LangGraph pipeline the audit endpoint checks this table:

  - run not found  → proceed normally; record IN_PROGRESS first
  - IN_PROGRESS    → return HTTP 409 (another invocation is running)
  - COMPLETE       → return the cached verdict immediately (HTTP 200)

This prevents duplicate LLM expenditure when Django retries a timed-out
Lambda request, and gives the system a single source of truth for every
audit verdict.

Table schema
------------
  PK (run_id)          : str  — the Django-supplied idempotency key
  asset_id             : str  — for GSI / query by asset
  status               : str  — IN_PROGRESS | COMPLETE | FAILED | ERASED
  verdict              : str  — JSON-encoded verdict dict (set on COMPLETE)
  created_at           : str  — ISO 8601 UTC
  updated_at           : str  — ISO 8601 UTC
  expires_at           : int  — Unix epoch for DynamoDB TTL (30-day retention)
"""

import json
from datetime import UTC, datetime, timedelta
from typing import Any

import structlog
from tenacity import retry, stop_after_attempt, wait_exponential

logger = structlog.get_logger(__name__)

# Audit run retention window — records expire after 30 days
_TTL_DAYS = 30

# Valid status values
STATUS_IN_PROGRESS = "IN_PROGRESS"
STATUS_COMPLETE = "COMPLETE"
STATUS_FAILED = "FAILED"
STATUS_ERASED = "ERASED"


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _ttl_epoch() -> int:
    """Return Unix epoch timestamp 30 days from now (for DynamoDB TTL)."""
    return int((datetime.now(UTC) + timedelta(days=_TTL_DAYS)).timestamp())


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=5),
    reraise=True,
)
def put_audit_run(
    dynamodb_client: Any,
    table_name: str,
    run_id: str,
    asset_id: str,
) -> None:
    """
    Create a new audit run record with status IN_PROGRESS.

    Uses a ConditionExpression so that a second concurrent call for the
    same run_id raises ConditionalCheckFailedException rather than silently
    overwriting an in-progress run.

    Raises:
        dynamodb_client.exceptions.ConditionalCheckFailedException — if the
        run_id already exists (caller should surface as HTTP 409).
    """
    now = _now_iso()
    dynamodb_client.put_item(
        TableName=table_name,
        Item={
            "run_id": {"S": run_id},
            "asset_id": {"S": asset_id},
            "status": {"S": STATUS_IN_PROGRESS},
            "created_at": {"S": now},
            "updated_at": {"S": now},
            "expires_at": {"N": str(_ttl_epoch())},
        },
        # Prevents overwriting an existing record — idempotency guard
        ConditionExpression="attribute_not_exists(run_id)",
    )
    logger.info("audit_run_created", run_id=run_id, asset_id=asset_id)


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=5),
    reraise=True,
)
def get_audit_run(
    dynamodb_client: Any,
    table_name: str,
    run_id: str,
) -> dict[str, Any] | None:
    """
    Fetch an existing audit run record by run_id.

    Returns None if the run does not exist.
    Returns a dict with keys: run_id, asset_id, status, verdict (optional).
    """
    response = dynamodb_client.get_item(
        TableName=table_name,
        Key={"run_id": {"S": run_id}},
        ConsistentRead=True,  # Strong consistency — idempotency requires it
    )
    item = response.get("Item")
    if not item:
        return None

    result: dict[str, Any] = {
        "run_id": item["run_id"]["S"],
        "asset_id": item["asset_id"]["S"],
        "status": item["status"]["S"],
        "created_at": item["created_at"]["S"],
        "updated_at": item["updated_at"]["S"],
    }
    # Verdict is only present once the run completes
    if "verdict" in item:
        result["verdict"] = json.loads(item["verdict"]["S"])

    logger.debug("audit_run_fetched", run_id=run_id, status=result["status"])
    return result


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=5),
    reraise=True,
)
def complete_audit_run(
    dynamodb_client: Any,
    table_name: str,
    run_id: str,
    verdict: dict[str, Any],
) -> None:
    """
    Mark an audit run as COMPLETE and persist the final verdict.

    The verdict is stored as a JSON string so it can be returned verbatim
    on a cache hit without re-invoking the LangGraph pipeline.
    """
    dynamodb_client.update_item(
        TableName=table_name,
        Key={"run_id": {"S": run_id}},
        UpdateExpression="SET #s = :s, verdict = :v, updated_at = :u",
        ExpressionAttributeNames={"#s": "status"},
        ExpressionAttributeValues={
            ":s": {"S": STATUS_COMPLETE},
            ":v": {"S": json.dumps(verdict, default=str)},
            ":u": {"S": _now_iso()},
        },
    )
    logger.info("audit_run_completed", run_id=run_id)


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=5),
    reraise=True,
)
def fail_audit_run(
    dynamodb_client: Any,
    table_name: str,
    run_id: str,
    error: str,
) -> None:
    """
    Mark an audit run as FAILED.  Called when the LangGraph pipeline raises
    an unrecoverable exception so the next retry is not blocked by an
    orphaned IN_PROGRESS record.
    """
    dynamodb_client.update_item(
        TableName=table_name,
        Key={"run_id": {"S": run_id}},
        UpdateExpression="SET #s = :s, error_message = :e, updated_at = :u",
        ExpressionAttributeNames={"#s": "status"},
        ExpressionAttributeValues={
            ":s": {"S": STATUS_FAILED},
            ":e": {"S": error[:1000]},  # Truncate to stay within DynamoDB limits
            ":u": {"S": _now_iso()},
        },
    )
    logger.warning("audit_run_failed", run_id=run_id, error=error[:200])


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=5),
    reraise=True,
)
def erase_asset_runs(
    dynamodb_client: Any,
    table_name: str,
    asset_id: str,
) -> int:
    """
    Mark all audit run records for an asset as ERASED.

    Used by the admin delete endpoint for GDPR right-to-erasure compliance.
    Requires a GSI on ``asset_id`` (``AssetIdIndex``).

    Returns the number of records affected.
    """
    # Query by asset_id via GSI
    response = dynamodb_client.query(
        TableName=table_name,
        IndexName="AssetIdIndex",
        KeyConditionExpression="asset_id = :aid",
        ExpressionAttributeValues={":aid": {"S": asset_id}},
        ProjectionExpression="run_id",
    )
    items = response.get("Items", [])

    for item in items:
        dynamodb_client.update_item(
            TableName=table_name,
            Key={"run_id": item["run_id"]},
            UpdateExpression="SET #s = :s, updated_at = :u",
            ExpressionAttributeNames={"#s": "status"},
            ExpressionAttributeValues={
                ":s": {"S": STATUS_ERASED},
                ":u": {"S": _now_iso()},
            },
        )

    logger.info("asset_runs_erased", asset_id=asset_id, count=len(items))
    return len(items)


def get_asset_run_summary(
    dynamodb_client: Any,
    table_name: str,
    asset_id: str,
) -> dict[str, Any]:
    """
    Return a summary of all audit runs for an asset.

    Uses the ``AssetIdIndex`` GSI to query by asset_id.
    Returns counts by status and the timestamp of the most recent run.
    """
    response = dynamodb_client.query(
        TableName=table_name,
        IndexName="AssetIdIndex",
        KeyConditionExpression="asset_id = :aid",
        ExpressionAttributeValues={":aid": {"S": asset_id}},
        ProjectionExpression="run_id, #s, created_at",
        ExpressionAttributeNames={"#s": "status"},
    )
    items = response.get("Items", [])

    status_counts: dict[str, int] = {}
    latest_run_at: str | None = None

    for item in items:
        status = item["status"]["S"]
        status_counts[status] = status_counts.get(status, 0) + 1
        created = item["created_at"]["S"]
        if latest_run_at is None or created > latest_run_at:
            latest_run_at = created

    return {
        "asset_id": asset_id,
        "total_runs": len(items),
        "status_counts": status_counts,
        "latest_run_at": latest_run_at,
    }
