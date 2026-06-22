"""Unit tests for image_agent node."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agents.image_agent import ImageAnalysisOutput, image_agent_node
from app.agents.state import AuditState


def _make_state(s3_keys: list[str] | None = None) -> AuditState:
    return AuditState(
        asset_id="abc-123",
        run_id="run-001",
        asset_spec={"name": "Hydraulic Pump"},
        s3_image_keys=s3_keys or ["audits/img001.jpg"],
        errors=[],
    )


@pytest.mark.asyncio
async def test_image_agent_happy_path(mock_chat_model, s3_bucket):
    """Happy path: valid image should produce a structured ImageAnalysis."""
    s3_bucket.put_object(Bucket="test-bucket", Key="audits/img001.jpg", Body=b"jpeg-bytes")

    mock_structured = AsyncMock()
    mock_structured.ainvoke = AsyncMock(
        return_value=ImageAnalysisOutput(
            findings=["Valve cap corroded", "Pressure label faded"],
            labels=["MAX 150 PSI", "SN-2024-001"],
            condition="fair",
            raw_description="An industrial pump with visible corrosion on the valve cap.",
        )
    )
    mock_chat_model.with_structured_output = MagicMock(return_value=mock_structured)

    with (
        patch("app.agents.image_agent.get_image_agent_llm", return_value=mock_chat_model),
        patch("app.agents.image_agent.get_s3_client", return_value=s3_bucket),
    ):
        result = await image_agent_node(_make_state())

    assert len(result["image_analyses"]) == 1
    analysis = result["image_analyses"][0]
    assert analysis["condition"] == "fair"
    assert "Valve cap corroded" in analysis["findings"]
    assert len(result["errors"]) == 0


@pytest.mark.asyncio
async def test_image_agent_json_parse_error(mock_chat_model, s3_bucket):
    """Error path: invalid JSON/validation error from LLM should be caught and added to errors."""
    s3_bucket.put_object(Bucket="test-bucket", Key="audits/bad.jpg", Body=b"jpeg-bytes")

    mock_structured = AsyncMock()
    mock_structured.ainvoke = AsyncMock(side_effect=ValueError("Validation Error"))
    mock_chat_model.with_structured_output = MagicMock(return_value=mock_structured)

    with (
        patch("app.agents.image_agent.get_image_agent_llm", return_value=mock_chat_model),
        patch("app.agents.image_agent.get_s3_client", return_value=s3_bucket),
    ):
        result = await image_agent_node(_make_state(s3_keys=["audits/bad.jpg"]))

    assert len(result["image_analyses"]) == 0
    assert any("image_agent" in e for e in result["errors"])


@pytest.mark.asyncio
async def test_image_agent_s3_download_error(mock_chat_model, s3_bucket):
    """Error path: S3 download failure should be caught per-image."""
    # Do NOT upload anything — key will be missing
    with (
        patch("app.agents.image_agent.get_image_agent_llm", return_value=mock_chat_model),
        patch("app.agents.image_agent.get_s3_client", return_value=s3_bucket),
    ):
        result = await image_agent_node(_make_state(s3_keys=["missing/photo.jpg"]))

    assert result["image_analyses"] == []
    assert len(result["errors"]) == 1


@pytest.mark.asyncio
async def test_image_agent_multiple_images_partial_failure(mock_chat_model, s3_bucket):
    """One bad image should not prevent other images from being analysed."""
    s3_bucket.put_object(Bucket="test-bucket", Key="audits/good.jpg", Body=b"jpeg-bytes")
    # "bad.jpg" is NOT uploaded — will fail

    mock_structured = AsyncMock()
    mock_structured.ainvoke = AsyncMock(
        return_value=ImageAnalysisOutput(
            findings=["Valve cap corroded"],
            labels=["MAX 150 PSI"],
            condition="fair",
            raw_description="An industrial pump",
        )
    )
    mock_chat_model.with_structured_output = MagicMock(return_value=mock_structured)

    with (
        patch("app.agents.image_agent.get_image_agent_llm", return_value=mock_chat_model),
        patch("app.agents.image_agent.get_s3_client", return_value=s3_bucket),
    ):
        result = await image_agent_node(
            _make_state(s3_keys=["audits/good.jpg", "audits/missing.jpg"])
        )

    assert len(result["image_analyses"]) == 1
    assert len(result["errors"]) == 1
