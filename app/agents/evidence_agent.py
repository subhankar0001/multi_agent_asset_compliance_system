"""
Evidence agent — consolidate all findings into a structured evidence bundle.

This node merges outputs from three sources into a unified list of evidence
dicts that the verdict agent will consume:
  1. Retrieved document chunks (source_type: "document")
  2. Image analysis findings (source_type: "image")
  3. Auditor remarks (source_type: "auditor_remark")

Each evidence item is normalised to a common structure regardless of source.
This normalisation makes it straightforward for the verdict agent to reason
across heterogeneous evidence types in a single LLM call.

Populates: state["evidence_bundle"]
"""

from typing import Any

import structlog

from app.agents.state import AuditState

logger = structlog.get_logger(__name__)


async def evidence_agent_node(state: AuditState) -> dict[str, Any]:
    """
    Consolidate document, image, and remark evidence into a unified bundle.

    No external API calls are made — this is a pure data transformation node.
    The evidence bundle is ordered: documents first, then images, then remarks.

    Returns:
        dict with keys: evidence_bundle
    """
    evidence: list[dict[str, Any]] = []

    # ── Evidence from retrieved document chunks ───────────────────────────────
    for chunk in state.get("retrieved_chunks", []):
        evidence.append(
            {
                "source_type": "document",
                "doc_id": chunk["doc_id"],
                "doc_type": chunk["doc_type"],
                "filename": chunk["filename"],
                "page": chunk.get("page"),
                # Truncate excerpt to keep the evidence bundle a reasonable size
                "excerpt": chunk["text"][:400],
                "finding": f"Relevant clause from {chunk['filename']}: {chunk['text'][:200]}",
                "relevance_score": chunk.get("score"),
            }
        )

    # ── Evidence from image analyses ──────────────────────────────────────────
    for analysis in state.get("image_analyses", []):
        for finding in analysis.get("findings", []):
            evidence.append(
                {
                    "source_type": "image",
                    "s3_key": analysis["s3_key"],
                    "image_finding": finding,
                    "finding": finding,
                    "condition": analysis.get("condition"),
                }
            )
        # Include the overall condition as a summary finding
        if analysis.get("raw_description"):
            evidence.append(
                {
                    "source_type": "image",
                    "s3_key": analysis["s3_key"],
                    "image_finding": analysis["raw_description"],
                    "finding": f"Image condition [{analysis.get('condition', 'unknown')}]: "
                    f"{analysis['raw_description'][:300]}",
                    "condition": analysis.get("condition"),
                }
            )

    # ── Evidence from auditor remarks ─────────────────────────────────────────
    if state.get("auditor_remarks"):
        evidence.append(
            {
                "source_type": "auditor_remark",
                "remark_text": state["auditor_remarks"],
                "finding": f"Auditor observed: {state['auditor_remarks']}",
            }
        )

    logger.info(
        "evidence_agent_complete",
        asset_id=state.get("asset_id"),
        evidence_count=len(evidence),
        document_evidence=sum(1 for e in evidence if e["source_type"] == "document"),
        image_evidence=sum(1 for e in evidence if e["source_type"] == "image"),
        remark_evidence=sum(1 for e in evidence if e["source_type"] == "auditor_remark"),
    )
    return {"evidence_bundle": evidence}
