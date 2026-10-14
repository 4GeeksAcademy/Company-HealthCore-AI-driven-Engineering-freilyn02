import uuid

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, StateGraph

from .nodes import (
    casual_node,
    handle_tool_failure,
    input_guard,
    memory_finalize,
    memory_read,
    memory_resolve,
    output_guard,
    lookup_inventory,
    lookup_ticket,
    no_context_node,
    query_node,
    receive_question,
    retrieve_node,
    route_intent,
    synthesize_answer,
)
from .state import AgentState
from .tracing import save_trace

# tool name (from the RouteDecision) -> graph node that runs it
TOOL_NODES = {"ticket": "lookup_ticket", "inventory": "lookup_inventory"}


def _pending_tools(state: AgentState) -> list[str]:
    """Tools the router asked for that have not run yet, in the router's order."""
    wanted = (state.get("route_decision") or {}).get("tools", [])
    done = {r["tool"] for r in state.get("tool_results") or []}
    return [t for t in wanted if t not in done]


def after_receive(state: AgentState) -> str:
    return "end" if state.get("error") else "memory_resolve"


def after_memory_resolve(state: AgentState) -> str:
    """MEM-092: the user only answered the memory proposal and asked nothing else -> done."""
    if not (state.get("question") or "").strip():
        return "end"
    return "input_guard"


def after_input_guard(state: AgentState) -> str:
    """Conditional edge driven by the input guard verdict (SEC-114)."""
    action = (state.get("guard_decision") or {}).get("action", "allow")
    if action == "block":
        return "end"  # fixed refusal already in state["answer"]; nothing else runs
    if action == "redirect_casual":
        return "casual"
    return "memory_read"


def after_route(state: AgentState) -> str:
    """Conditional edge driven by the STRUCTURED router output, not a fixed sequence."""
    pending = _pending_tools(state)
    if state.get("route") in ("tool", "both") and pending:
        return TOOL_NODES[pending[0]]
    return "retrieve"


def after_tool(state: AgentState) -> str:
    pending = _pending_tools(state)
    if pending:
        return TOOL_NODES[pending[0]]
    if any(r["outcome"] != "success" for r in state["tool_results"]):
        return "handle_tool_failure"  # explicit recovery branch, never an exception
    return "retrieve" if state.get("route") == "both" else "synthesize_answer"


def after_failure(state: AgentState) -> str:
    # "both": still answer the knowledge part; "tool": the fallback text is final
    return "retrieve" if state.get("route") == "both" else "end"


def after_retrieve(state: AgentState) -> str:
    if state.get("error"):
        return "end"
    if not state.get("retrieved_context"):
        # MEM-092: with no documents, an approved memory may still answer the question
        return "query" if state.get("memories") else "no_context"
    return "query"


def after_rag_answer(state: AgentState) -> str:
    # On the "both" route the RAG answer is merged with the tool results
    return "synthesize_answer" if state.get("route") == "both" else "end"


def build_agent_graph():
    builder = StateGraph(AgentState)
    builder.add_node("receive_question", receive_question)
    builder.add_node("memory_resolve", memory_resolve)
    builder.add_node("input_guard", input_guard)
    builder.add_node("casual", casual_node)
    builder.add_node("memory_read", memory_read)
    builder.add_node("memory_finalize", memory_finalize)
    builder.add_node("output_guard", output_guard)
    builder.add_node("route_intent", route_intent)
    builder.add_node("lookup_ticket", lookup_ticket)
    builder.add_node("lookup_inventory", lookup_inventory)
    builder.add_node("handle_tool_failure", handle_tool_failure)
    builder.add_node("retrieve", retrieve_node)
    builder.add_node("no_context", no_context_node)
    builder.add_node("query", query_node)
    builder.add_node("synthesize_answer", synthesize_answer)

    builder.set_entry_point("receive_question")
    # Every path that used to finish at the output guard now passes through
    # memory_finalize first (so the memory text is ALSO checked by the output guard).
    builder.add_conditional_edges(
        "receive_question",
        after_receive,
        {"memory_resolve": "memory_resolve", "end": "memory_finalize"},
    )
    builder.add_conditional_edges(
        "memory_resolve",
        after_memory_resolve,
        {"input_guard": "input_guard", "end": "memory_finalize"},
    )
    builder.add_conditional_edges(
        "input_guard",
        after_input_guard,
        {"memory_read": "memory_read", "casual": "casual", "end": "memory_finalize"},
    )
    builder.add_edge("memory_read", "route_intent")
    builder.add_edge("casual", "memory_finalize")
    builder.add_conditional_edges(
        "route_intent",
        after_route,
        {
            "lookup_ticket": "lookup_ticket",
            "lookup_inventory": "lookup_inventory",
            "retrieve": "retrieve",
        },
    )
    tool_targets = {
        "lookup_ticket": "lookup_ticket",
        "lookup_inventory": "lookup_inventory",
        "handle_tool_failure": "handle_tool_failure",
        "retrieve": "retrieve",
        "synthesize_answer": "synthesize_answer",
    }
    builder.add_conditional_edges("lookup_ticket", after_tool, tool_targets)
    builder.add_conditional_edges("lookup_inventory", after_tool, tool_targets)
    builder.add_conditional_edges(
        "handle_tool_failure", after_failure, {"retrieve": "retrieve", "end": "memory_finalize"}
    )
    builder.add_conditional_edges(
        "retrieve",
        after_retrieve,
        {"query": "query", "no_context": "no_context", "end": "memory_finalize"},
    )
    builder.add_conditional_edges(
        "no_context",
        after_rag_answer,
        {"synthesize_answer": "synthesize_answer", "end": "memory_finalize"},
    )
    builder.add_conditional_edges(
        "query",
        after_rag_answer,
        {"synthesize_answer": "synthesize_answer", "end": "memory_finalize"},
    )
    builder.add_edge("synthesize_answer", "memory_finalize")
    builder.add_edge("memory_finalize", "output_guard")
    builder.add_edge("output_guard", END)

    # compile() validates the structure: a broken graph fails at import time
    return builder.compile(checkpointer=MemorySaver())


agent_graph = build_agent_graph()  # compiled once, at startup


def run_agent(question: str, session_id: str | None = None) -> tuple[str, dict]:
    run_id = f"run-{uuid.uuid4().hex[:8]}"
    config = {"configurable": {"thread_id": run_id}}
    final_state = agent_graph.invoke(
        {
            "question": question,
            "session_id": session_id,
            "memories": None,
            "memory_proposal": None,
            "memory_notice": None,
            "guard_decision": None,
            "route": None,
            "route_decision": None,
            "tool_results": [],
            "retrieved_context": None,
            "answer": None,
            "trace_steps": [],
            "error": None,
        },
        config,
    )
    save_trace(run_id, final_state)
    return run_id, final_state
