import operator
from typing import Annotated, TypedDict


class AgentState(TypedDict):
    """Minimal state: only what the next node needs, no chat history."""

    question: str
    # --- Part 2: routing + external tools ---
    route: str | None  # "rag" | "tool" | "both" (set by route_intent)
    route_decision: dict | None  # full structured RouteDecision, for traces
    # operator.add makes LangGraph APPEND each tool's typed output (as a dict)
    tool_results: Annotated[list[dict], operator.add]
    # --- Part 1 ---
    retrieved_context: list[dict] | None
    answer: str | None
    # operator.add makes LangGraph APPEND each node's trace steps
    trace_steps: Annotated[list[dict], operator.add]
    error: str | None