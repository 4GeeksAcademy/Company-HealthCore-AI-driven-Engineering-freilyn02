from data.pipelines.rag import generate_answer, retrieve  # reuse existing RAG code

from . import tools as agent_tools
from .harness import observability
from .harness.casual import casual_reply
from .harness.external_content import wrap_chunks
from .harness.input_guards import check_input
from .harness.output_guards import guard_output
from .prompts.system import CASUAL_FALLBACK, REDIRECT_SUFFIX
from .router import RouteDecision, classify_question
from .state import AgentState

NO_CONTEXT_ANSWER = (
    "I don't have information about that in the HealthCore knowledge base."
)


def _step(state: AgentState, node: str, summary: str, outcome: str | None = None) -> dict:
    step = {
        "node": node,
        "order": len(state.get("trace_steps") or []) + 1,
        "output_summary": summary,
    }
    if outcome is not None:  # per-tool HTTP outcome: success | timeout | not_found | http_error
        step["outcome"] = outcome
    return step


def _failure_summary(exc: Exception) -> str:
    """Short, single-line error description for the trace (never sent to the API client)."""
    message = " ".join(str(exc).split())[:150]
    return f"failed: {type(exc).__name__}: {message}" if message else f"failed: {type(exc).__name__}"


def receive_question(state: AgentState) -> dict:
    question = (state.get("question") or "").strip()
    if not question:
        return {
            "question": "",
            "error": "empty_question",
            "trace_steps": [_step(state, "receive_question", "empty question")],
        }
    return {
        "question": question,
        "trace_steps": [_step(state, "receive_question", f"received: {question[:60]}")],
    }


def retrieve_node(state: AgentState) -> dict:
    try:
        chunks = retrieve(state["question"])
    except Exception as exc:  # never leak a raw stack trace
        return {
            "error": "retrieval_failed",
            "trace_steps": [_step(state, "retrieve", _failure_summary(exc))],
        }
    chunks = chunks or []
    return {
        "retrieved_context": chunks,
        "trace_steps": [_step(state, "retrieve", f"{len(chunks)} chunks")],
    }


def no_context_node(state: AgentState) -> dict:
    return {
        "answer": NO_CONTEXT_ANSWER,
        "trace_steps": [_step(state, "no_context", "honest 'I don't know' answer")],
    }


def query_node(state: AgentState) -> dict:
    try:
        # Retrieved text is DATA: neutralize instruction-like spans and wrap it in
        # <untrusted_source> tags (it travels in the user role, never the system role).
        safe_context = wrap_chunks(state["retrieved_context"])
        answer = generate_answer(state["question"], safe_context)
    except Exception as exc:
        return {
            "error": "generation_failed",
            "trace_steps": [_step(state, "query", _failure_summary(exc))],
        }
    return {
        "answer": answer,
        "trace_steps": [_step(state, "query", f"answer of {len(answer)} chars")],
    }


# =============================================================================
# Part 2: routing + external tools
# =============================================================================
def route_intent(state: AgentState) -> dict:
    decision = classify_question(state["question"])
    return {
        "route": decision.route,
        "route_decision": decision.model_dump(),
        "trace_steps": [
            _step(
                state,
                "route_intent",
                f"route={decision.route} tools={decision.tools} ({decision.rationale})",
            )
        ],
    }


def lookup_ticket(state: AgentState) -> dict:
    decision = RouteDecision(**state["route_decision"])
    result = agent_tools.lookup_ticket(
        agent_tools.TicketLookupInput(
            ticket_id=decision.ticket_id, status=decision.ticket_status
        )
    )
    target = f"ticket {decision.ticket_id}" if decision.ticket_id else "ticket list"
    return {
        "tool_results": [{"tool": "ticket", **result.model_dump()}],
        "trace_steps": [
            _step(state, "lookup_ticket", f"{target}: {result.outcome}", result.outcome)
        ],
    }


def lookup_inventory(state: AgentState) -> dict:
    decision = RouteDecision(**state["route_decision"])
    result = agent_tools.lookup_inventory(
        agent_tools.InventoryLookupInput(query=decision.inventory_query)
    )
    target = f"inventory '{decision.inventory_query}'" if decision.inventory_query else "inventory"
    return {
        "tool_results": [{"tool": "inventory", **result.model_dump()}],
        "trace_steps": [
            _step(state, "lookup_inventory", f"{target}: {result.outcome}", result.outcome)
        ],
    }


def _pretty(value: str | None) -> str:
    return (value or "unknown").replace("_", " ")


def _render_ticket(r: dict) -> str:
    if r["outcome"] == "not_found":
        return (
            f"I couldn't find a ticket with id {r['ticket_id']}. "
            "Please double-check the number."
        )
    if r["outcome"] != "success":
        what = f"ticket {r['ticket_id']}" if r["ticket_id"] else "the ticket list"
        return (
            f"I couldn't confirm the status of {what} right now. "
            "Please try again in a moment or check the incident manager directly."
        )
    if r["ticket_id"] and r["count"] is None:
        return (
            f"Ticket {r['ticket_id']} (\"{r['title']}\") is currently "
            f"{_pretty(r['status'])}. Category: {_pretty(r['category'])}; "
            f"branch: {_pretty(r['branch'])}; last updated: {r['updated_at']}."
        )
    label = f" with status '{_pretty(r['status'])}'" if r["status"] else ""
    if not r["found"]:
        return f"There are no tickets{label} right now."
    listed = ", ".join(f"#{m['ticket_id']}" for m in r["matches"])
    return f"There are {r['count']} ticket(s){label}. First ones: {listed}."


def _render_inventory(r: dict) -> str:
    if r["outcome"] == "not_found":
        return "I couldn't find a product matching that name or SKU in the inventory."
    if r["outcome"] != "success":
        return (
            "I couldn't confirm the stock levels right now. "
            "Please try again in a moment or check the inventory manager directly."
        )
    lines = [
        f"- {m['name']} ({m['sku']}): {m['current_stock']} {m['unit']} in stock ({m['country']})"
        for m in r["matches"]
    ]
    return "Current stock:\n" + "\n".join(lines)


def render_tool_results(results: list[dict]) -> str:
    """Turn typed tool outputs into user-facing text WITHOUT an LLM, so nothing
    (status, category, dates, stock) can ever be invented."""
    renderers = {"ticket": _render_ticket, "inventory": _render_inventory}
    return "\n\n".join(renderers[r["tool"]](r) for r in results)


def handle_tool_failure(state: AgentState) -> dict:
    failed = [r for r in state["tool_results"] if r["outcome"] != "success"]
    summary = ", ".join(f"{r['tool']}={r['outcome']}" for r in failed)
    update: dict = {
        "trace_steps": [_step(state, "handle_tool_failure", f"honest fallback for: {summary}")]
    }
    if state.get("route") == "tool":
        # Nothing else will add to the answer: this IS the final, honest answer.
        update["answer"] = render_tool_results(state["tool_results"])
    return update


def synthesize_answer(state: AgentState) -> dict:
    parts = [render_tool_results(state["tool_results"])]
    if state.get("answer"):  # RAG answer, present only on the "both" route
        parts.append(state["answer"])
    return {
        "answer": "\n\n".join(parts),
        "trace_steps": [
            _step(state, "synthesize_answer", f"merged {len(parts)} source(s)")
        ],
    }


# =============================================================================
# SEC-114: harness nodes (input guard, casual redirect, output guard)
# =============================================================================
def input_guard(state: AgentState) -> dict:
    """First line of defense: runs before routing, retrieval, tools or any model call."""
    decision = check_input(state["question"])
    update: dict = {"guard_decision": decision.as_dict()}
    if decision.action == "allow":
        update["trace_steps"] = [_step(state, "input_guard", "allowed")]
        return update

    observability.record_event(
        decision.guardrail or "input_guard",
        decision.failure_type or "content",
        "block" if decision.action == "block" else "redirect",
        state["question"],
        redirect=True,  # both the refusal and the casual answer steer back to HealthCore
        sensitive=decision.sensitive,
    )
    update["trace_steps"] = [
        _step(state, "input_guard", f"{decision.action}: {decision.guardrail} ({decision.failure_type})")
    ]
    if decision.action == "block":
        update["answer"] = decision.message
    return update


def casual_node(state: AgentState) -> dict:
    """Brief answer to a casual question, ALWAYS closed with the redirect to HealthCore."""
    reply = casual_reply(state["question"]) or CASUAL_FALLBACK
    return {
        "answer": f"{reply}\n\n{REDIRECT_SUFFIX}",
        "trace_steps": [_step(state, "casual_reply", "brief answer + redirect to HealthCore")],
    }


def output_guard(state: AgentState) -> dict:
    """Last line of defense: validate whatever answer is about to leave the agent."""
    if state.get("error"):  # failed runs return an HTTP error, not an answer
        return {"trace_steps": [_step(state, "output_guard", "skipped (run failed)")]}
    verdict = guard_output(state.get("answer"))
    for finding in verdict.findings:
        observability.record_event(
            finding.guardrail,
            finding.failure_type,
            finding.action,
            state.get("answer") if isinstance(state.get("answer"), str) else None,
            sensitive=True,  # never copy a flagged answer into the logs
        )
    if not verdict.changed:
        return {"trace_steps": [_step(state, "output_guard", "ok")]}
    names = ", ".join(f.guardrail for f in verdict.findings)
    return {
        "answer": verdict.answer,
        "trace_steps": [_step(state, "output_guard", f"sanitized: {names}")],
    }
