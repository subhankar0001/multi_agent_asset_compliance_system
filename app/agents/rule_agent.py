"""
Rule agent — cross-reference findings against compliance documents.

This node synthesises the outputs of the document and image agents to
identify which specific compliance rules, requirements, or standards
are violated or at risk based on:
  - Image analysis findings
  - Auditor remarks
  - Retrieved document clauses

The LLM is instructed to return ONLY a JSON array of triggered rule objects,
each referencing its source document. This structure is consumed directly
by the evidence agent and verdict agent.

Populates: state["triggered_rules"]
"""

import json
from typing import Any

import structlog
from langchain_core.messages import HumanMessage
from pydantic import BaseModel

from app.agents.state import AuditState, get_asset_spec_dict
from app.dependencies import get_rule_agent_llm
from app.schemas.audit import TriggeredRule
from app.utils.circuit_breaker import circuit_breaker

logger = structlog.get_logger(__name__)


def _format_retrieved_docs(chunks: list[Any]) -> str:
    """Format retrieved document chunks for the rule analysis prompt."""
    if not chunks:
        return "No documents retrieved."
    return "\n\n".join(
        f"[{c['filename']} | page {c.get('page', 'N/A')} | {c['doc_type']}]\n{c['text']}"
        for c in chunks
    )


def _format_image_findings(analyses: list[Any]) -> str:
    """Format image analysis results for the rule analysis prompt."""
    if not analyses:
        return "No images analysed."
    lines = []
    for a in analyses:
        lines.append(
            f"Image: {a['s3_key']}\n"
            f"  Condition: {a['condition']}\n"
            f"  Findings: {'; '.join(a['findings']) or 'None'}\n"
            f"  Labels: {'; '.join(a['labels']) or 'None'}"
        )
    return "\n\n".join(lines)


_RULE_PROMPT_TEMPLATE = """You are a compliance auditor reviewing a physical asset audit.

ASSET SPECIFICATION:
{asset_spec}

RETRIEVED COMPLIANCE DOCUMENTS:
{retrieved_docs}

IMAGE ANALYSIS FINDINGS:
{image_findings}

AUDITOR REMARKS:
{auditor_remarks}

Identify every compliance rule or requirement from the documents that is violated or at risk
based on the image findings and auditor remarks.

Return [] if no rules are violated."""


class RulesOutput(BaseModel):
    triggered_rules: list[TriggeredRule]


async def rule_agent_node(state: AuditState) -> dict[str, Any]:
    """
    Identify violated compliance rules by cross-referencing findings with documents.
    """
    llm = get_rule_agent_llm()
    new_errors: list[str] = []

    try:
        asset_spec_dict = get_asset_spec_dict(state)
        asset_spec_json = json.dumps(asset_spec_dict, indent=2)
        prompt = _RULE_PROMPT_TEMPLATE.format(
            asset_spec=asset_spec_json,
            retrieved_docs=_format_retrieved_docs(state.get("retrieved_chunks", [])),
            image_findings=_format_image_findings(state.get("image_analyses", [])),
            auditor_remarks=state.get("auditor_remarks") or "None provided",
        )

        structured_llm = llm.with_structured_output(RulesOutput)
        messages = [HumanMessage(content=prompt)]

        cb = circuit_breaker("llm", failure_threshold=3, recovery_timeout=60)
        parsed_obj: RulesOutput = await cb(structured_llm.ainvoke)(messages)  # type: ignore[assignment]
        triggered_dicts = [rule.model_dump() for rule in parsed_obj.triggered_rules]

        logger.info(
            "rule_agent_complete",
            asset_id=state.get("asset_id"),
            rules_triggered=len(triggered_dicts),
        )
        return {"triggered_rules": triggered_dicts, "errors": new_errors}

    except Exception as exc:
        logger.error("rule_agent_error", error=type(exc).__name__)
        new_errors.append(f"rule_agent: {exc}")
        return {"triggered_rules": [], "errors": new_errors}
