"""
Integration tests for the audit streaming flow.

Tests the POST /audit/run endpoint with a mocked LangGraph pipeline.
Verifies NDJSON streaming format, event structure, and final verdict delivery.
"""

import json
from unittest.mock import MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import create_app

_API_KEY = "test-secret-key-minimum-32-chars-long"
_HEADERS = {"X-API-Key": _API_KEY}

_SAMPLE_AUDIT_PAYLOAD = {
    "asset_id": "abc-123",
    "run_id": "run-001",
    "asset_spec": {"name": "Hydraulic Pump HP-5000", "category": "pump"},
    "s3_image_keys": ["audits/photo001.jpg"],
    "auditor_remarks": "Valve cap appears corroded",
}

_MOCK_VERDICT = {
    "asset_id": "abc-123",
    "run_id": "run-001",
    "compliance_status": "NON_COMPLIANT",
    "confidence": 0.87,
    "triggered_rules": [],
    "evidence": [],
    "recommendations": ["Replace valve cap"],
    "verdict_reasoning": "Corrosion detected on valve cap.",
    "documents_consulted": [],
    "generated_at": "2026-01-01T00:00:00+00:00",
}


async def _mock_astream(initial_state, stream_mode):
    """Mock LangGraph astream yielding realistic node events."""
    nodes = ["document_agent", "image_agent", "rule_agent", "evidence_agent", "verdict_agent"]
    for node in nodes:
        if node == "verdict_agent":
            yield {node: {"verdict": _MOCK_VERDICT, "errors": []}}
        else:
            yield {node: {}}


@pytest.fixture(autouse=True)
def mock_dynamo_dep(mock_dynamodb_table):
    """Automatically mock the DynamoDB client for all tests in this module."""
    with patch("app.dependencies._get_dynamodb_client", return_value=mock_dynamodb_table):
        yield mock_dynamodb_table


@pytest.mark.asyncio
async def test_audit_run_streams_ndjson():
    """POST /audit/run should return 200 with application/x-ndjson content type."""
    app = create_app()

    mock_graph = MagicMock()
    mock_graph.astream = _mock_astream

    with patch("app.api.v1.audit.audit_graph", mock_graph):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(
                "/api/v1/audit/run",
                json=_SAMPLE_AUDIT_PAYLOAD,
                headers=_HEADERS,
            )

    assert response.status_code == 200
    assert "ndjson" in response.headers["content-type"]


@pytest.mark.asyncio
async def test_audit_run_emits_node_complete_events():
    """Each agent node should produce a node_complete NDJSON event."""
    app = create_app()

    mock_graph = MagicMock()
    mock_graph.astream = _mock_astream

    with patch("app.api.v1.audit.audit_graph", mock_graph):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(
                "/api/v1/audit/run",
                json=_SAMPLE_AUDIT_PAYLOAD,
                headers=_HEADERS,
            )

    lines = [line for line in response.text.strip().split("\n") if line]
    events = [json.loads(line) for line in lines]

    node_complete_events = [e for e in events if e["event"] == "node_complete"]
    assert len(node_complete_events) == 5


@pytest.mark.asyncio
async def test_audit_run_emits_verdict_event():
    """The last NDJSON line should contain the compliance verdict."""
    app = create_app()

    mock_graph = MagicMock()
    mock_graph.astream = _mock_astream

    with patch("app.api.v1.audit.audit_graph", mock_graph):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(
                "/api/v1/audit/run",
                json=_SAMPLE_AUDIT_PAYLOAD,
                headers=_HEADERS,
            )

    lines = [line for line in response.text.strip().split("\n") if line]
    events = [json.loads(line) for line in lines]

    verdict_events = [e for e in events if e["event"] == "verdict"]
    assert len(verdict_events) == 1
    assert verdict_events[0]["verdict"]["compliance_status"] == "NON_COMPLIANT"
    assert verdict_events[0]["verdict"]["run_id"] == "run-001"


@pytest.mark.asyncio
async def test_audit_run_progress_increases_monotonically():
    """Progress values in node_complete events should increase from 0 to 1."""
    app = create_app()

    mock_graph = MagicMock()
    mock_graph.astream = _mock_astream

    with patch("app.api.v1.audit.audit_graph", mock_graph):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(
                "/api/v1/audit/run",
                json=_SAMPLE_AUDIT_PAYLOAD,
                headers=_HEADERS,
            )

    lines = [line for line in response.text.strip().split("\n") if line]
    events = [json.loads(line) for line in lines]
    progress_values = [e["progress"] for e in events if e["event"] == "node_complete"]

    assert progress_values == sorted(progress_values)
    assert progress_values[-1] == 1.0


@pytest.mark.asyncio
async def test_audit_run_missing_api_key():
    """POST /audit/run without X-API-Key should return 401."""
    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/v1/audit/run",
            json=_SAMPLE_AUDIT_PAYLOAD,
        )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_audit_run_cached_verdict_returns_200():
    """
    If DynamoDB has a COMPLETE record for run_id, the endpoint should return
    HTTP 200 immediately with the cached verdict without invoking the graph.
    """
    app = create_app()

    mock_dynamo = MagicMock()
    mock_dynamo.get_item.return_value = {
        "Item": {
            "run_id": {"S": "run-001"},
            "asset_id": {"S": "abc-123"},
            "status": {"S": "COMPLETE"},
            "created_at": {"S": "2026-01-01T00:00:00+00:00"},
            "updated_at": {"S": "2026-01-01T00:00:00+00:00"},
            "verdict": {
                "S": '{"compliance_status": "COMPLIANT", "confidence": 0.99, "run_id": "run-001"}'
            },
        }
    }

    with patch("app.dependencies._get_dynamodb_client", return_value=mock_dynamo):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(
                "/api/v1/audit/run",
                json=_SAMPLE_AUDIT_PAYLOAD,
                headers=_HEADERS,
            )

    assert response.status_code == 200
    body = response.json()
    assert body["cached"] is True
    assert body["verdict"]["compliance_status"] == "COMPLIANT"
    assert response.headers.get("X-Cache") == "HIT"


@pytest.mark.asyncio
async def test_audit_run_in_progress_returns_409():
    """
    If DynamoDB has an IN_PROGRESS record for run_id, the endpoint should
    return HTTP 409 Conflict without invoking the graph.
    """
    app = create_app()

    mock_dynamo = MagicMock()
    mock_dynamo.get_item.return_value = {
        "Item": {
            "run_id": {"S": "run-001"},
            "asset_id": {"S": "abc-123"},
            "status": {"S": "IN_PROGRESS"},
            "created_at": {"S": "2026-01-01T00:00:00+00:00"},
            "updated_at": {"S": "2026-01-01T00:00:00+00:00"},
        }
    }

    with patch("app.dependencies._get_dynamodb_client", return_value=mock_dynamo):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(
                "/api/v1/audit/run",
                json=_SAMPLE_AUDIT_PAYLOAD,
                headers=_HEADERS,
            )

    assert response.status_code == 409
    body = response.json()
    assert body["detail"]["code"] == "AUDIT_IN_PROGRESS"


@pytest.mark.asyncio
async def test_audit_run_invalid_asset_spec():
    """QA-5: POST /audit/run with invalid asset_spec should return 422."""
    app = create_app()
    payload = _SAMPLE_AUDIT_PAYLOAD.copy()
    payload["asset_spec"] = {"invalid": "missing name and category"}
    
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/v1/audit/run",
            json=payload,
            headers=_HEADERS,
        )
    
    assert response.status_code == 422
    body = response.json()
    assert "asset_spec" in str(body["detail"])


@pytest.mark.asyncio
async def test_audit_run_oversized_auditor_remarks():
    """QA-5: POST /audit/run with oversized auditor_remarks should return 422."""
    app = create_app()
    payload = _SAMPLE_AUDIT_PAYLOAD.copy()
    payload["auditor_remarks"] = "A" * 5001  # Max is 5000
    
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/v1/audit/run",
            json=payload,
            headers=_HEADERS,
        )
    
    assert response.status_code == 422
    body = response.json()
    assert "auditor_remarks" in str(body["detail"])
