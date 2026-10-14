import operator
from typing import Annotated, TypedDict


class AgentState(TypedDict):
    """Minimal state: only what the next node needs, no chat history."""

    question: str
    # --- MEM-092: memory (all optional; nothing happens unless session_id is set) ---
    session_id: str | None  # conversation id sent by the client; None = memory is off
    memories: list[dict] | None  # approved memories read for this question
    memory_proposal: dict | None  # self-evaluation output (fact / keys / reason)
    memory_notice: str | None  # "Saved..." / "Okay, I won't remember that." for this turn
    # --- Part 3: harness (SEC-114) ---
    guard_decision: dict | None  # input guard verdict: action / guardrail / failure_type
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
