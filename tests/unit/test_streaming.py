"""Unit tests for streaming.py utility."""

import json

from app.utils.streaming import ErrorEvent, NodeCompleteEvent, VerdictEvent, serialise_event


def test_serialise_node_complete_event():
    event = NodeCompleteEvent(
        node="document_agent",
        asset_id="abc-123",
        run_id="run-001",
        progress=0.25,
    )
    result = serialise_event(event)
    assert result.endswith("\n")
    data = json.loads(result.strip())
    assert data["event"] == "node_complete"
    assert data["node"] == "document_agent"
    assert data["asset_id"] == "abc-123"
    assert data["run_id"] == "run-001"
    assert data["progress"] == 0.25


def test_serialise_verdict_event():
    event = VerdictEvent(
        verdict={"compliance_status": "COMPLIANT", "confidence": 0.9}
    )
    result = serialise_event(event)
    assert result.endswith("\n")
    data = json.loads(result.strip())
    assert data["event"] == "verdict"
    assert data["verdict"]["compliance_status"] == "COMPLIANT"
    assert data["verdict"]["confidence"] == 0.9


def test_serialise_error_event():
    event = ErrorEvent(
        message="An error occurred",
        node="image_agent",
    )
    result = serialise_event(event)
    assert result.endswith("\n")
    data = json.loads(result.strip())
    assert data["event"] == "error"
    assert data["message"] == "An error occurred"
    assert data["node"] == "image_agent"
