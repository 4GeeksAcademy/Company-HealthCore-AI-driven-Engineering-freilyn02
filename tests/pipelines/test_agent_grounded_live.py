"""Live grounding eval: runs the REAL RAG (Qdrant + LLM), no mocks.

Run with:
RUN_LIVE_EVALS=1 uv run --project services/api pytest tests/pipelines/test_agent_grounded_live.py -q
"""

import os

import pytest

from agent.graph import run_agent
from agent.tracing import load_trace

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_LIVE_EVALS") != "1",
    reason="Live eval: set RUN_LIVE_EVALS=1 (needs Qdrant + LLM credentials).",
)

# TODO: replace with a question whose answer is in the knowledge base document
QUESTION = "What does the insurance coverage include?"
# TODO: replace with a fact/word that must appear in a grounded answer
EXPECTED_TERM = "coverage"


def test_answer_is_grounded_in_real_knowledge_base():
    run_id, state = run_agent(QUESTION)
    trace = load_trace(run_id)
    steps = {s["node"]: s for s in trace["trace_steps"]}

    assert state["error"] is None
    assert "query" in steps, "agent should have generated an answer from context"
    assert "no_context" not in steps, "retrieval found nothing for a known question"
    assert state["retrieved_context"], "expected at least one retrieved chunk"
    assert EXPECTED_TERM.lower() in state["answer"].lower()
