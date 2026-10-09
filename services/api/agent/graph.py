import uuid

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, StateGraph

from .nodes import no_context_node, query_node, receive_question, retrieve_node
from .state import AgentState
from .tracing import save_trace


def after_receive(state: AgentState) -> str:
    return "end" if state.get("error") else "retrieve"


def after_retrieve(state: AgentState) -> str:
    if state.get("error"):
        return "end"
    if not state.get("retrieved_context"):
        return "no_context"
    return "query"


def build_agent_graph():
    builder = StateGraph(AgentState)
    builder.add_node("receive_question", receive_question)
    builder.add_node("retrieve", retrieve_node)
    builder.add_node("no_context", no_context_node)
    builder.add_node("query", query_node)

    builder.set_entry_point("receive_question")
    builder.add_conditional_edges(
        "receive_question", after_receive, {"retrieve": "retrieve", "end": END}
    )
    builder.add_conditional_edges(
        "retrieve",
        after_retrieve,
        {"query": "query", "no_context": "no_context", "end": END},
    )
    builder.add_edge("no_context", END)
    builder.add_edge("query", END)

    # compile() validates the structure: a broken graph fails at import time
    return builder.compile(checkpointer=MemorySaver())


agent_graph = build_agent_graph()  # compiled once, at startup


def run_agent(question: str) -> tuple[str, dict]:
    run_id = f"run-{uuid.uuid4().hex[:8]}"
    config = {"configurable": {"thread_id": run_id}}
    final_state = agent_graph.invoke(
        {
            "question": question,
            "retrieved_context": None,
            "answer": None,
            "trace_steps": [],
            "error": None,
        },
        config,
    )
    save_trace(run_id, final_state)
    return run_id, final_state
