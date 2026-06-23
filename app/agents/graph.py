"""
LangGraph StateGraph assembly for the compliance audit pipeline.

Graph topology (all sequential, no conditional branches):

  document_agent → image_agent → rule_agent → evidence_agent → verdict_agent → END

Design decisions:
  - All five agents run on every audit regardless of outcome.
  - Non-fatal errors are accumulated in state["errors"] rather than raising,
    so the graph always completes and returns at minimum an INSUFFICIENT_DATA verdict.
  - The compiled graph is created at module import time and reused across
    Lambda warm starts, avoiding re-compilation overhead per request.
"""

from typing import Any

from langgraph.graph import END, StateGraph

from app.agents.document_agent import document_agent_node
from app.agents.evidence_agent import evidence_agent_node
from app.agents.image_agent import image_agent_node
from app.agents.rule_agent import rule_agent_node
from app.agents.state import AuditState
from app.agents.verdict_agent import verdict_agent_node


def start_node(state: AuditState) -> dict[str, Any]:
    """Dummy start node to orchestrate parallel execution of agents."""
    return {}


def build_audit_graph() -> Any:
    """
    Construct and compile the LangGraph StateGraph for audit runs.

    Returns the compiled graph. Call once at module load — the compiled
    graph object is thread-safe and can be shared across requests.
    """
    graph: StateGraph = StateGraph(AuditState)

    # Register agent nodes
    graph.add_node("start", start_node)
    graph.add_node("document_agent", document_agent_node)
    graph.add_node("image_agent", image_agent_node)
    graph.add_node("rule_agent", rule_agent_node)
    graph.add_node("evidence_agent", evidence_agent_node)
    graph.add_node("verdict_agent", verdict_agent_node)

    # Wire up the parallel and sequential pipeline
    graph.set_entry_point("start")
    graph.add_edge("start", "document_agent")
    graph.add_edge("start", "image_agent")
    graph.add_edge("document_agent", "rule_agent")
    graph.add_edge("image_agent", "rule_agent")
    graph.add_edge("rule_agent", "evidence_agent")
    graph.add_edge("evidence_agent", "verdict_agent")
    graph.add_edge("verdict_agent", END)

    return graph.compile()


# Module-level compiled graph — reused across Lambda invocations (warm starts).
# This avoids graph compilation overhead on every request.
audit_graph = build_audit_graph()
