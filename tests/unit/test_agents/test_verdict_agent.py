"""Unit tests for verdict_agent node."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agents.state import AuditState
from app.agents.verdict_agent import VerdictOutput, verdict_agent_node


def _make_state(**kwargs) -> AuditState:
    base = AuditState(
        asset_id="abc-123",
        run_id="run-001",
        asset_spec={"name": "Hydraulic Pump"},
        s3_image_keys=[],
        retrieved_chunks=[
            {
                "doc_id": "manual-v2",
                "doc_type": "user_manual",
                "filename": "pump_manual.pdf",
                "page": 5,
                "text": "Valve pressure must not exceed 150 PSI.",
                "score": 0.92,
            }
        ],
        triggered_rules=[
            {"rule_id": "valve-pressure", "severity": "major", "rule_description": "Test rule"}
        ],
        evidence_bundle=[
            {"source_type": "document", "finding": "Pressure label missing", "relevance_score": 0.9}
        ],
        documents_consulted=["manual-v2"],
        previous_verdicts=None,
        errors=[],
    )
    base.update(kwargs)
    return base


@pytest.mark.asyncio
async def test_verdict_agent_happy_path(mock_chat_model):
    """Happy path: verdict_agent should return a complete verdict dict."""
    mock_structured = AsyncMock()
    mock_structured.ainvoke = AsyncMock(
        return_value=VerdictOutput(
            compliance_status="NON_COMPLIANT",
            confidence=0.88,
            recommendations=["Replace pressure label immediately."],
            verdict_reasoning="Pressure label is missing, violating section 3.2.",
        )
    )
    mock_chat_model.with_structured_output = MagicMock(return_value=mock_structured)

    with patch("app.agents.verdict_agent.get_verdict_agent_llm", return_value=mock_chat_model):
        result = await verdict_agent_node(_make_state())

    verdict = result["verdict"]
    assert verdict["compliance_status"] == "NON_COMPLIANT"
    assert verdict["confidence"] == 0.88
    assert verdict["asset_id"] == "abc-123"
    assert verdict["run_id"] == "run-001"
    assert "generated_at" in verdict
    assert len(result["errors"]) == 0


@pytest.mark.asyncio
async def test_verdict_agent_compliant_status(mock_chat_model):
    """verdict_agent should correctly return COMPLIANT status."""
    mock_structured = AsyncMock()
    mock_structured.ainvoke = AsyncMock(
        return_value=VerdictOutput(
            compliance_status="COMPLIANT",
            confidence=0.95,
            recommendations=[],
            verdict_reasoning="All checks passed.",
        )
    )
    mock_chat_model.with_structured_output = MagicMock(return_value=mock_structured)

    with patch("app.agents.verdict_agent.get_verdict_agent_llm", return_value=mock_chat_model):
        result = await verdict_agent_node(_make_state(triggered_rules=[]))

    assert result["verdict"]["compliance_status"] == "COMPLIANT"


@pytest.mark.asyncio
async def test_verdict_agent_llm_failure_returns_insufficient_data(mock_chat_model):
    """Error path: LLM failure should return INSUFFICIENT_DATA fallback verdict."""
    mock_structured = AsyncMock()
    mock_structured.ainvoke = AsyncMock(side_effect=Exception("Anthropic unavailable"))
    mock_chat_model.with_structured_output = MagicMock(return_value=mock_structured)

    with patch("app.agents.verdict_agent.get_verdict_agent_llm", return_value=mock_chat_model):
        result = await verdict_agent_node(_make_state())

    verdict = result["verdict"]
    assert verdict["compliance_status"] == "INSUFFICIENT_DATA"
    assert verdict["confidence"] == 0.0
    assert any("Anthropic unavailable" in e for e in result["errors"])


@pytest.mark.asyncio
async def test_verdict_agent_json_parse_error_returns_fallback(mock_chat_model):
    """Error path: malformed JSON should return INSUFFICIENT_DATA fallback."""
    mock_structured = AsyncMock()
    mock_structured.ainvoke = AsyncMock(side_effect=ValueError("Validation Error"))
    mock_chat_model.with_structured_output = MagicMock(return_value=mock_structured)

    with patch("app.agents.verdict_agent.get_verdict_agent_llm", return_value=mock_chat_model):
        result = await verdict_agent_node(_make_state())

    assert result["verdict"]["compliance_status"] == "INSUFFICIENT_DATA"
    assert len(result["errors"]) > 0


@pytest.mark.asyncio
async def test_verdict_agent_includes_documents_consulted(mock_chat_model):
    """verdict_agent should propagate documents_consulted from state."""
    mock_structured = AsyncMock()
    mock_structured.ainvoke = AsyncMock(
        return_value=VerdictOutput(
            compliance_status="COMPLIANT",
            confidence=0.95,
            recommendations=[],
            verdict_reasoning="All checks passed.",
        )
    )
    mock_chat_model.with_structured_output = MagicMock(return_value=mock_structured)

    with patch("app.agents.verdict_agent.get_verdict_agent_llm", return_value=mock_chat_model):
        result = await verdict_agent_node(_make_state())

    assert "manual-v2" in result["verdict"]["documents_consulted"]


@pytest.mark.asyncio
async def test_verdict_agent_no_embeddings_fallback():
    """verdict_agent should short-circuit and return an enterprise fallback if retrieved_chunks is empty."""
    # We do not patch get_verdict_agent_llm since the LLM should not be called at all
    state = _make_state(retrieved_chunks=[])
    result = await verdict_agent_node(state)

    verdict = result["verdict"]
    assert verdict["compliance_status"] == "INSUFFICIENT_DATA"
    assert verdict["confidence"] == 0.0
    assert (
        "No compliance reference documents or vector embeddings were found"
        in verdict["recommendations"][0]
    )
    assert "Compliance audit aborted" in verdict["verdict_reasoning"]
    assert "No reference compliance document embeddings found" in result["errors"][0]
