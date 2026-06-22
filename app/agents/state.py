"""
AuditState — shared mutable context flowing through every LangGraph node.

Using TypedDict (not dataclass or Pydantic model) because LangGraph
requires plain dict-compatible types for its state merging mechanism.

All fields use total=False so agents can populate them progressively.
Each node receives the full current state and returns only the fields
it populates — LangGraph merges these partial dicts automatically.

Field groups:
  - Input: populated from AuditRequest before the graph starts
  - Per-agent outputs: populated as the graph progresses
  - Error accumulator: non-fatal errors are appended rather than raised
    so the graph always completes and returns a partial verdict
"""

from typing import Any, TypedDict


class ImageAnalysis(TypedDict):
    """Structured result of LLM vision analysis for one audit photo."""

    s3_key: str
    findings: list[str]  # Specific observations about defects or non-compliance
    labels: list[str]  # Visible text labels, serial numbers, warning stickers
    condition: str  # "good" | "fair" | "poor" | "critical"
    raw_description: str  # Full paragraph describing everything visible


class RetrievedChunk(TypedDict):
    """One semantically-retrieved document chunk from Pinecone."""

    doc_id: str
    doc_type: str
    filename: str
    page: int | None
    text: str
    score: float


class AuditState(TypedDict, total=False):
    """
    Shared state dict for the LangGraph audit pipeline.

    All fields are optional at definition time (total=False).
    The input fields are populated before the graph starts.
    Agent nodes populate their respective output fields.
    """

    # ── Input — populated from AuditRequest before graph starts ──────────────
    asset_id: str
    run_id: str
    asset_spec: dict[str, Any]
    s3_image_keys: list[str]
    auditor_remarks: str | None
    previous_verdicts: list[dict[str, Any]] | None

    # ── document_agent output ─────────────────────────────────────────────────
    retrieved_chunks: list[RetrievedChunk]
    documents_consulted: list[str]  # Unique doc_ids from retrieved chunks

    # ── image_agent output ────────────────────────────────────────────────────
    image_analyses: list[ImageAnalysis]

    # ── rule_agent output ─────────────────────────────────────────────────────
    triggered_rules: list[dict[str, Any]]

    # ── evidence_agent output ─────────────────────────────────────────────────
    evidence_bundle: list[dict[str, Any]]

    # ── verdict_agent output ──────────────────────────────────────────────────
    verdict: dict[str, Any] | None

    # ── Error accumulator — non-fatal errors from any agent ──────────────────
    errors: list[str]
