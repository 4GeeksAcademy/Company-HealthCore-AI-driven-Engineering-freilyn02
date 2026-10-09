import operator
from typing import Annotated, TypedDict


class AgentState(TypedDict):
    """Minimal state: only what the next node needs, no chat history."""

    question: str
    retrieved_context: list[dict] | None
    answer: str | None
    # operator.add makes LangGraph APPEND each node's trace steps
    trace_steps: Annotated[list[dict], operator.add]
    error: str | None
