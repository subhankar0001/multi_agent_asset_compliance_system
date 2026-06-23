"""Unit tests for evidence_agent node."""

import pytest

from app.agents.evidence_agent import evidence_agent_node
from app.agents.state import AuditState


def _make_state(**kwargs) -> AuditState:
    base = AuditState(
        asset_id="abc-123",
        run_id="run-001",
        asset_spec={"name": "Hydraulic Pump"},
        s3_image_keys=[],
        errors=[],
        retrieved_chunks=[
            {
                "doc_id": "manual-v2",
                "doc_type": "user_manual",
                "filename": "pump_manual.pdf",
                "page": 5,
                "text": "Valve pressure must be marked on housing.",
                "score": 0.91,
            }
        ],
        image_analyses=[
            {
                "s3_key": "audits/img.jpg",
                "findings": ["Missing pressure label"],
                "labels": ["SN-001"],
                "condition": "poor",
                "raw_description": "Pump with missing label.",
            }
        ],
        auditor_remarks="The valve cap appears corroded.",
    )
    base.update(kwargs)
    return base


@pytest.mark.asyncio
async def test_evidence_agent_includes_all_source_types():
    """evidence_agent should produce evidence from documents, images, and remarks."""
    result = await evidence_agent_node(_make_state())
    sources = {e["source_type"] for e in result["evidence_bundle"]}
    assert "document" in sources
    assert "image" in sources
    assert "auditor_remark" in sources


@pytest.mark.asyncio
async def test_evidence_agent_document_evidence_fields():
    """Document evidence should include filename, page, excerpt."""
    result = await evidence_agent_node(_make_state())
    doc_evidence = [e for e in result["evidence_bundle"] if e["source_type"] == "document"]
    assert len(doc_evidence) == 1
    assert doc_evidence[0]["filename"] == "pump_manual.pdf"
    assert doc_evidence[0]["page"] == 5
    assert "excerpt" in doc_evidence[0]


@pytest.mark.asyncio
async def test_evidence_agent_image_evidence_fields():
    """Image evidence should include s3_key and finding."""
    result = await evidence_agent_node(_make_state())
    img_evidence = [e for e in result["evidence_bundle"] if e["source_type"] == "image"]
    assert len(img_evidence) >= 1
    assert img_evidence[0]["s3_key"] == "audits/img.jpg"
    assert img_evidence[0]["finding"] == "Missing pressure label"


@pytest.mark.asyncio
async def test_evidence_agent_remark_evidence():
    """Auditor remark should appear as a single remark evidence item."""
    result = await evidence_agent_node(_make_state())
    remark_evidence = [e for e in result["evidence_bundle"] if e["source_type"] == "auditor_remark"]
    assert len(remark_evidence) == 1
    assert "corroded" in remark_evidence[0]["remark_text"]


@pytest.mark.asyncio
async def test_evidence_agent_no_remarks():
    """Without auditor_remarks, no auditor_remark evidence should appear."""
    result = await evidence_agent_node(_make_state(auditor_remarks=None))
    remark_evidence = [e for e in result["evidence_bundle"] if e["source_type"] == "auditor_remark"]
    assert len(remark_evidence) == 0


@pytest.mark.asyncio
async def test_evidence_agent_empty_state():
    """evidence_agent with empty lists should return an empty bundle."""
    state = AuditState(
        asset_id="abc-123",
        run_id="run-001",
        asset_spec={},
        s3_image_keys=[],
        errors=[],
        retrieved_chunks=[],
        image_analyses=[],
    )
    result = await evidence_agent_node(state)
    assert result["evidence_bundle"] == []
