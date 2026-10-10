from data.pipelines.rag import generate_answer, retrieve  # reuse existing RAG code

from .state import AgentState

NO_CONTEXT_ANSWER = (
    "I don't have information about that in the HealthCore knowledge base."
)


def _step(state: AgentState, node: str, summary: str) -> dict:
    return {
        "node": node,
        "order": len(state.get("trace_steps") or []) + 1,
        "output_summary": summary,
    }


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
        answer = generate_answer(state["question"], state["retrieved_context"])
    except Exception as exc:
        return {
            "error": "generation_failed",
            "trace_steps": [_step(state, "query", _failure_summary(exc))],
        }
    return {
        "answer": answer,
        "trace_steps": [_step(state, "query", f"answer of {len(answer)} chars")],
    }
