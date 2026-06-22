"""
Shared pytest fixtures for Asset Compliance AI.

All AWS clients are mocked with moto.
All external API calls (Anthropic, OpenAI, Pinecone, Tavily) are mocked.
Tests MUST NOT make real network calls.

Environment variables are set before any app imports so that Pydantic
BaseSettings can initialise without requiring a real .env file.
"""

import os
from unittest.mock import AsyncMock, MagicMock

import boto3
import pytest
from moto import mock_aws

# ── Set all required env vars before any app imports ─────────────────────────
os.environ.update(
    {
        "AWS_REGION": "us-east-1",
        "AWS_DEFAULT_REGION": "us-east-1",
        "AWS_ACCESS_KEY_ID": "testing",
        "AWS_SECRET_ACCESS_KEY": "testing",
        "AWS_SECURITY_TOKEN": "testing",
        "AWS_SESSION_TOKEN": "testing",
        "S3_BUCKET_NAME": "test-bucket",
        "PINECONE_API_KEY": "test-pinecone-key",
        "PINECONE_INDEX_NAME": "test-index",
        "PINECONE_ENVIRONMENT": "us-east-1-aws",
        "ANTHROPIC_API_KEY": "test-anthropic-key",
        "OPENAI_API_KEY": "test-openai-key",
        "XAI_API_KEY": "test-xai-key",
        "IMAGE_AGENT_PROVIDER": "mock_provider",
        "IMAGE_AGENT_MODEL": "mock_model",
        "RULE_AGENT_PROVIDER": "mock_provider",
        "RULE_AGENT_MODEL": "mock_model",
        "VERDICT_AGENT_PROVIDER": "mock_provider",
        "VERDICT_AGENT_MODEL": "mock_model",
        "CHAT_AGENT_PROVIDER": "mock_provider",
        "CHAT_AGENT_MODEL": "mock_model",
        "EMBEDDING_PROVIDER": "mock_provider",
        "EMBEDDING_MODEL": "mock_model",
        "EMBEDDING_DIMENSIONS": "1536",
        "API_SECRET_KEY": "test-secret-key-minimum-32-chars-long",
        "APP_ENV": "development",
        "LOG_LEVEL": "DEBUG",
        "DYNAMODB_AUDIT_TABLE": "test-audit-runs-table",
        "CORS_ALLOWED_ORIGINS": '["*"]',
        "RATE_LIMIT_AUDIT": "1000/minute",
        "RATE_LIMIT_INGEST": "1000/minute",
        "RATE_LIMIT_CHAT": "1000/minute",
    }
)


# ── Global patches for LangChain init factories to support mock_provider/mock_model ────
from unittest.mock import patch


def _create_global_mock_chat_model(*args, **kwargs):
    client = AsyncMock()

    class MockMessage:
        def __init__(self, content):
            self.content = content

    client.ainvoke = AsyncMock(
        return_value=MockMessage(
            '{"compliance_status": "COMPLIANT", '
            '"confidence": 0.95, '
            '"recommendations": [], '
            '"verdict_reasoning": "All checks passed."}'
        )
    )

    class MockStructuredOutput:
        async def ainvoke(self, *args, **kwargs):
            m = MagicMock()
            m.findings = []
            m.labels = []
            m.condition = "fair"
            m.raw_description = "A mock image analysis."
            m.triggered_rules = []
            m.compliance_status = "COMPLIANT"
            m.confidence = 0.95
            m.recommendations = []
            m.verdict_reasoning = "All checks passed."
            m.model_dump = MagicMock(
                return_value={
                    "compliance_status": "COMPLIANT",
                    "confidence": 0.95,
                    "recommendations": [],
                    "verdict_reasoning": "All checks passed.",
                }
            )
            return m

    client.with_structured_output = MagicMock(return_value=MockStructuredOutput())
    return client


def _create_global_mock_embeddings(*args, **kwargs):
    client = AsyncMock()
    client.aembed_documents = AsyncMock(side_effect=lambda texts: [[0.1] * 1536 for _ in texts])
    client.aembed_query = AsyncMock(return_value=[0.1] * 1536)
    return client


patch("langchain.chat_models.init_chat_model", side_effect=_create_global_mock_chat_model).start()
patch("langchain.embeddings.init_embeddings", side_effect=_create_global_mock_embeddings).start()


# ── AWS fixtures ──────────────────────────────────────────────────────────────


@pytest.fixture()
def s3_bucket():
    """Provide a moto-mocked S3 bucket pre-created for test use."""
    with mock_aws():
        s3 = boto3.client("s3", region_name="us-east-1")
        s3.create_bucket(Bucket="test-bucket")
        yield s3


# ── External service mocks ────────────────────────────────────────────────────


@pytest.fixture()
def mock_pinecone_index():
    """Provide a fully mocked Pinecone Index object."""
    index = MagicMock()
    index.upsert = MagicMock(return_value=MagicMock(upserted_count=5))
    index.delete = MagicMock()
    index.query = MagicMock(return_value=MagicMock(matches=[]))
    index.describe_index_stats = MagicMock(return_value=MagicMock(namespaces={}))
    return index


@pytest.fixture()
def mock_dynamodb_table():
    """
    Provide a moto-mocked DynamoDB table matching the AuditRunsTable schema.

    Creates the table with run_id as the partition key and an AssetIdIndex
    GSI on asset_id, exactly matching the production template.yaml definition.
    """
    with mock_aws():
        client = boto3.client("dynamodb", region_name="us-east-1")
        client.create_table(
            TableName="test-audit-runs-table",
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


@pytest.fixture()
def mock_chat_model():
    """Provide a mocked async ChatModel returning valid compliance JSON/Text."""
    client = AsyncMock()

    # Mock ainvoke to return an AIMessage-like object
    class MockMessage:
        def __init__(self, content):
            self.content = content

    client.ainvoke = AsyncMock(
        return_value=MockMessage(
            '{"compliance_status": "COMPLIANT", '
            '"confidence": 0.95, '
            '"recommendations": [], '
            '"verdict_reasoning": "All checks passed."}'
        )
    )

    # Also mock with_structured_output to return self or another mock that returns an object
    class MockStructuredOutput:
        async def ainvoke(self, *args, **kwargs):
            # We'll just return a magic mock that matches what the agents expect
            m = MagicMock()
            m.findings = []
            m.labels = []
            m.condition = "fair"
            m.raw_description = "A mock image analysis."

            m.triggered_rules = []

            m.compliance_status = "COMPLIANT"
            m.confidence = 0.95
            m.recommendations = []
            m.verdict_reasoning = "All checks passed."
            m.model_dump = MagicMock(
                return_value={
                    "compliance_status": "COMPLIANT",
                    "confidence": 0.95,
                    "recommendations": [],
                    "verdict_reasoning": "All checks passed.",
                }
            )
            return m

    client.with_structured_output = MagicMock(return_value=MockStructuredOutput())
    return client


@pytest.fixture()
def mock_embeddings_model():
    """Provide a mocked Langchain Embeddings model returning 1536-dim zero vectors."""
    client = AsyncMock()
    client.aembed_documents = AsyncMock(side_effect=lambda texts: [[0.1] * 1536 for _ in texts])
    client.aembed_query = AsyncMock(return_value=[0.1] * 1536)
    return client


@pytest.fixture()
def mock_tavily_client():
    """Provide a mocked Tavily client returning a single web search result."""
    client = MagicMock()
    client.search = MagicMock(
        return_value={
            "results": [
                {
                    "url": "https://example.com/compliance",
                    "title": "Compliance Guide",
                    "content": "Example compliance content.",
                    "score": 0.9,
                }
            ]
        }
    )
    return client


# ── Shared test data ──────────────────────────────────────────────────────────


@pytest.fixture()
def sample_asset_spec() -> dict:
    """Return a sample asset specification dict for use in tests."""
    return {
        "name": "Hydraulic Pump HP-5000",
        "category": "pump",
        "manufacturer": "HydroTech",
        "model": "HP-5000",
        "serial_number": "HT-2024-001",
        "installation_date": "2024-01-15",
    }


@pytest.fixture()
def sample_pinecone_match():
    """Return a mock Pinecone query match with realistic metadata."""
    match = MagicMock()
    match.id = "abc-123_manual-v2_p1_c0"
    match.score = 0.92
    match.metadata = {
        "asset_id": "abc-123",
        "doc_id": "manual-v2",
        "doc_type": "user_manual",
        "filename": "pump_manual.pdf",
        "page": 5,
        "text": "Valve pressure must not exceed 150 PSI. Pressure must be marked on housing.",
        "chunk_index": 0,
    }
    return match
