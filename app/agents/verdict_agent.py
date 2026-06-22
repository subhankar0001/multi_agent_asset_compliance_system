"""
Verdict agent — generate the final structured compliance verdict.

This is the final node in the LangGraph audit pipeline. It synthesises
all prior agent outputs (triggered rules, evidence bundle, previous verdicts)
into a structured JSON compliance verdict.

On success, the verdict is returned as a dict matching the internal schema.
On failure, a minimal INSUFFICIENT_DATA verdict is returned so the response
is always well-formed regardless of LLM errors.

Populates: state["verdict"]
"""

import json
from datetime import UTC, datetime
from typing import Any, Literal

import structlog
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from app.agents.state import AuditState
from app.dependencies import get_verdict_agent_llm

logger = structlog.get_logger(__name__)


class VerdictOutput(BaseModel):
    compliance_status: Literal["COMPLIANT", "NON_COMPLIANT", "NEEDS_REVIEW", "INSUFFICIENT_DATA"]
    confidence: float = Field(ge=0.0, le=1.0)
    recommendations: list[str]
    verdict_reasoning: str


_VERDICT_SYSTEM_PROMPT = (
    "You are a senior compliance engineer issuing a formal audit verdict. "
    "Be precise, evidence-based, and actionable. "
    "Never speculate beyond the evidence provided. "
    "Reference specific document clauses and image findings in your reasoning."
)

_VERDICT_PROMPT_TEMPLATE = """Based on the following audit evidence, issue a formal compliance verdict.

ASSET: {asset_name} (ID: {asset_id})

TRIGGERED RULES:
{triggered_rules}

EVIDENCE BUNDLE (first 20 items):
{evidence_bundle}

PREVIOUS VERDICTS (for trend-aware reasoning):
{previous_verdicts}

Use INSUFFICIENT_DATA if there is not enough evidence to reach a reliable conclusion."""


async def verdict_agent_node(state: AuditState) -> dict[str, Any]:
    """
    Generate the final compliance verdict using structured output.
    """
    llm = get_verdict_agent_llm()
    errors: list[str] = list(state.get("errors", []))
    generated_at = datetime.now(UTC).isoformat()

    try:
        # Check if there are no document embeddings found in the system for this asset
        retrieved_chunks = state.get("retrieved_chunks", [])
        if not retrieved_chunks:
            no_docs_error = "No reference compliance document embeddings found in the vector database for this asset namespace."
            if no_docs_error not in errors:
                errors.append(no_docs_error)

            asset_name = state.get("asset_spec", {}).get("name", "Unknown Asset")
            verdict = {
                "asset_id": state["asset_id"],
                "run_id": state["run_id"],
                "compliance_status": "INSUFFICIENT_DATA",
                "confidence": 0.0,
                "triggered_rules": [],
                "evidence": state.get("evidence_bundle", []),
                "recommendations": [
                    "No compliance reference documents or vector embeddings were found for this asset in the vector database.",
                    "Please upload and ingest reference documentation (such as user manuals, safety sheets, or compliance specification documents) before initiating the audit pipeline.",
                ],
                "verdict_reasoning": (
                    f"Compliance audit aborted: No reference document embeddings found in the vector database for Asset '{asset_name}' "
                    f"(ID: '{state['asset_id']}'). Active compliance auditing requires pre-existing reference standards to cross-reference against visual evidence."
                ),
                "documents_consulted": [],
                "generated_at": generated_at,
                "errors": errors if errors else None,
            }
            logger.info(
                "verdict_agent_no_embeddings_fallback",
                asset_id=state["asset_id"],
                run_id=state["run_id"],
                compliance_status=verdict["compliance_status"],
                reason="No embeddings found for asset namespace",
            )
            return {"verdict": verdict, "errors": errors}

        prompt = _VERDICT_PROMPT_TEMPLATE.format(
            asset_name=state.get("asset_spec", {}).get("name", "Unknown Asset"),
            asset_id=state["asset_id"],
            triggered_rules=json.dumps(state.get("triggered_rules", []), indent=2),
            # Limit evidence bundle to first 20 items to stay within token budget
            evidence_bundle=json.dumps(state.get("evidence_bundle", [])[:20], indent=2),
            previous_verdicts=json.dumps(state.get("previous_verdicts") or [], indent=2),
        )

        structured_llm = llm.with_structured_output(VerdictOutput)
        messages = [
            SystemMessage(content=_VERDICT_SYSTEM_PROMPT),
            HumanMessage(content=prompt),
        ]

        parsed_obj: VerdictOutput = await structured_llm.ainvoke(messages)  # type: ignore[assignment]
        parsed = parsed_obj.model_dump()

        verdict = {
            "asset_id": state["asset_id"],
            "run_id": state["run_id"],
            "compliance_status": parsed["compliance_status"],
            "confidence": float(parsed["confidence"]),
            "triggered_rules": state.get("triggered_rules", []),
            "evidence": state.get("evidence_bundle", []),
            "recommendations": parsed.get("recommendations", []),
            "verdict_reasoning": parsed.get("verdict_reasoning", ""),
            "documents_consulted": state.get("documents_consulted", []),
            "generated_at": generated_at,
            "errors": errors if errors else None,
        }

        logger.info(
            "verdict_agent_complete",
            asset_id=state["asset_id"],
            run_id=state["run_id"],
            compliance_status=verdict["compliance_status"],
            confidence=verdict["confidence"],
            rules_triggered=len(state.get("triggered_rules", [])),
        )
        return {"verdict": verdict, "errors": errors}

    except Exception as exc:
        logger.error("verdict_agent_error", error=str(exc))
        errors.append(f"verdict_agent: {exc}")

    # Fallback verdict — always return a well-formed response
    fallback_verdict = {
        "asset_id": state["asset_id"],
        "run_id": state["run_id"],
        "compliance_status": "INSUFFICIENT_DATA",
        "confidence": 0.0,
        "triggered_rules": state.get("triggered_rules", []),
        "evidence": state.get("evidence_bundle", []),
        "recommendations": ["Manual review required — automated analysis could not complete."],
        "verdict_reasoning": "The automated verdict generation encountered an error. Manual review is required.",
        "documents_consulted": state.get("documents_consulted", []),
        "generated_at": generated_at,
        "errors": errors,
    }
    return {"verdict": fallback_verdict, "errors": errors}
