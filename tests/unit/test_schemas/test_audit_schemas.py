"""Unit tests for audit schemas."""

import pytest
from pydantic import ValidationError

from app.schemas.audit import AuditRequest, Evidence, TriggeredRule


def test_evidence_document_type():
    e = Evidence(source_type="document", finding="Valve pressure not marked", doc_id="doc-1")
    assert e.source_type == "document"
    assert e.relevance_score is None


def test_evidence_relevance_score_bounds():
    with pytest.raises(ValidationError):
        Evidence(source_type="document", finding="test", relevance_score=1.5)

    with pytest.raises(ValidationError):
        Evidence(source_type="document", finding="test", relevance_score=-0.1)


def test_triggered_rule_valid():
    rule = TriggeredRule(
        rule_id="valve-pressure-marking",
        rule_description="Valve pressure must be marked on housing.",
        severity="major",
        evidence_refs=[0, 1],
    )
    assert rule.severity == "major"
    assert len(rule.evidence_refs) == 2


def test_triggered_rule_invalid_severity():
    with pytest.raises(ValidationError):
        TriggeredRule(
            rule_id="test",
            rule_description="test",
            severity="catastrophic",  # Invalid
        )


def test_audit_request_valid(sample_asset_spec):
    req = AuditRequest(
        asset_id="abc-123",
        run_id="run-001",
        asset_spec=sample_asset_spec,
        s3_image_keys=["audits/img001.jpg"],
    )
    assert req.asset_id == "abc-123"
    assert len(req.s3_image_keys) == 1


def test_audit_request_too_many_images_rejected(sample_asset_spec):
    with pytest.raises(ValidationError):
        AuditRequest(
            asset_id="abc-123",
            run_id="run-001",
            asset_spec=sample_asset_spec,
            s3_image_keys=[f"audits/img{i:03d}.jpg" for i in range(21)],
        )


def test_audit_request_no_images_rejected(sample_asset_spec):
    with pytest.raises(ValidationError):
        AuditRequest(
            asset_id="abc-123",
            run_id="run-001",
            asset_spec=sample_asset_spec,
            s3_image_keys=[],
        )
