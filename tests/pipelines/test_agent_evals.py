import pytest

from agent import nodes
from agent.graph import agent_graph, run_agent
from agent.tracing import load_trace

FAKE_CHUNKS = [{"text": "Refunds are accepted within 30 days.", "score": 0.9}]


@pytest.fixture
def mock_rag(monkeypatch):
    monkeypatch.setattr(nodes, "retrieve", lambda q: FAKE_CHUNKS)
    monkeypatch.setattr(
        nodes, "generate_answer", lambda q, ctx: f"Based on policy: {ctx[0]['text']}"
    )


def _order(trace):
    return [s["node"] for s in trace["trace_steps"]]


def test_node_order_retrieve_before_query(mock_rag):
    run_id, _ = run_agent("What is the refund policy?")
    order = _order(load_trace(run_id))
    assert order.index("retrieve") < order.index("query")


def test_empty_question_never_reaches_query(mock_rag):
    run_id, state = run_agent("   ")
    trace = load_trace(run_id)
    assert "query" not in _order(trace)
    assert state["error"] == "empty_question"


def test_no_context_answers_honestly(monkeypatch):
    monkeypatch.setattr(nodes, "retrieve", lambda q: [])
    run_id, state = run_agent("Something unrelated")
    assert "no_context" in _order(load_trace(run_id))
    assert "don't have information" in state["answer"]


def test_checkpoints_are_inspectable(mock_rag):
    run_id, _ = run_agent("What is the refund policy?")
    config = {"configurable": {"thread_id": run_id}}
    assert len(list(agent_graph.get_state_history(config))) > 1


def test_answer_is_grounded_in_context(mock_rag):
    _, state = run_agent("What is the refund policy?")
    assert state["answer"] and "30 days" in state["answer"]
