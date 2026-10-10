"""Part 2 evals: routing between RAG and external tools, and the failure fallback.

The HTTP client is stubbed ONLY here, in the test fixtures, so CI needs no running
services. The production code under test still goes through the real tool code
(typed contract, numeric timeout, GET-only) and the real graph.
"""

import httpx
import pytest

from agent import nodes, tools, tracing
from agent.graph import run_agent
from agent.router import classify_question
from agent.tracing import load_trace

FAKE_CHUNKS = [{"text": "No-show fees do not apply to Medicare patients.", "score": 0.9}]

TICKET_482 = {
    "id": "482",
    "title": "Infusion pump alarm failing",
    "description": "internal text that must never reach the answer",
    "category": "clinical_equipment",
    "status": "in_progress",
    "origin": "branch",
    "branch": "austin_main",
    "created_at": "2026-10-01T10:00:00+00:00",
    "updated_at": "2026-10-08T09:30:00+00:00",
}


@pytest.fixture(autouse=True)
def isolated_trace_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(tracing, "TRACE_DIR", tmp_path)


@pytest.fixture
def rag_calls(monkeypatch):
    """Mock the RAG and record every call, to prove WHEN it did or did not run."""
    calls: list[str] = []

    def fake_retrieve(question):
        calls.append(question)
        return FAKE_CHUNKS

    monkeypatch.setattr(nodes, "retrieve", fake_retrieve)
    monkeypatch.setattr(
        nodes, "generate_answer", lambda q, ctx: f"Per policy: {ctx[0]['text']}"
    )
    return calls


def stub_http(monkeypatch, handler):
    """Replace the tools' HTTP client factory with one backed by `handler`.
    Returns the list of requests that were made."""
    requests: list[httpx.Request] = []

    def recording_handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return handler(request)

    def fake_build_client(base_url: str) -> httpx.Client:
        return httpx.Client(
            base_url=base_url,
            transport=httpx.MockTransport(recording_handler),
            timeout=tools.TOOL_TIMEOUT_SECONDS,
        )

    monkeypatch.setattr(tools, "build_client", fake_build_client)
    return requests


def incident_service_up(request: httpx.Request) -> httpx.Response:
    if request.url.path == "/api/incidents/482":
        return httpx.Response(200, json=TICKET_482)
    if request.url.path == "/api/incidents" and request.url.params.get("status") == "open":
        return httpx.Response(200, json=[{**TICKET_482, "status": "open"}])
    return httpx.Response(404, json={"detail": "Incident not found"})


def incident_service_timeout(request: httpx.Request) -> httpx.Response:
    raise httpx.ConnectTimeout("simulated timeout", request=request)


def nodes_run(run_id: str) -> list[str]:
    return [s["node"] for s in load_trace(run_id)["trace_steps"]]


# --------------------------------------------------------------------------- evals
def test_eval_tool_routing_uses_ticket_tool_not_rag(monkeypatch, rag_calls):
    requests = stub_http(monkeypatch, incident_service_up)

    run_id, state = run_agent("What is the status of ticket 482?")
    trace = load_trace(run_id)

    assert trace["route"] == "tool"
    assert "lookup_ticket" in nodes_run(run_id)
    assert "retrieve" not in nodes_run(run_id), "RAG must NOT run for a live-ticket question"
    assert rag_calls == []
    assert trace["sources_used"] == ["ticket_tool"]
    assert trace["rag_executed"] is False
    # the answer comes from the real service payload, nothing invented
    assert "482" in state["answer"] and "in progress" in state["answer"]
    assert "internal text" not in state["answer"], "ticket description must never leak"
    # the tool step records the HTTP outcome
    step = next(s for s in trace["trace_steps"] if s["node"] == "lookup_ticket")
    assert step["outcome"] == "success"
    assert [r.method for r in requests] == ["GET"]


def test_eval_rag_routing_uses_rag_not_tools(monkeypatch, rag_calls):
    requests = stub_http(monkeypatch, incident_service_up)

    run_id, state = run_agent("What is the no-show fee policy for Medicare patients?")
    trace = load_trace(run_id)

    assert trace["route"] == "rag"
    assert "retrieve" in nodes_run(run_id) and "query" in nodes_run(run_id)
    assert not {"lookup_ticket", "lookup_inventory"} & set(nodes_run(run_id))
    assert trace["sources_used"] == ["rag"]
    assert requests == [], "no external service may be called on a RAG-only question"
    assert "Medicare" in state["answer"]


def test_eval_fallback_when_incident_service_times_out(monkeypatch, rag_calls):
    stub_http(monkeypatch, incident_service_timeout)

    run_id, state = run_agent("What is the status of ticket 482?")
    trace = load_trace(run_id)

    order = nodes_run(run_id)
    assert order.index("lookup_ticket") < order.index("handle_tool_failure")
    step = next(s for s in trace["trace_steps"] if s["node"] == "lookup_ticket")
    assert step["outcome"] == "timeout"
    assert state["error"] is None, "a tool failure must not crash the run"
    assert "couldn't confirm" in state["answer"]
    # nothing fabricated
    for invented in ("in progress", "open", "resolved", "clinical", "austin"):
        assert invented not in state["answer"].lower()


def test_ticket_not_found_is_honest(monkeypatch, rag_calls):
    stub_http(monkeypatch, incident_service_up)

    run_id, state = run_agent("What is the status of ticket 999?")
    step = next(s for s in load_trace(run_id)["trace_steps"] if s["node"] == "lookup_ticket")

    assert step["outcome"] == "not_found"
    assert "handle_tool_failure" in nodes_run(run_id)
    assert "couldn't find a ticket with id 999" in state["answer"]


def test_both_route_runs_tool_then_rag_and_merges(monkeypatch, rag_calls):
    stub_http(monkeypatch, incident_service_up)

    run_id, state = run_agent(
        "What is the status of ticket 482 and what is the no-show fee policy?"
    )
    trace = load_trace(run_id)

    assert trace["route"] == "both"
    assert trace["sources_used"] == ["ticket_tool", "rag"]  # tool first, then RAG
    assert nodes_run(run_id)[-1] == "synthesize_answer"
    assert "Ticket 482" in state["answer"] and "Per policy" in state["answer"]


def test_both_route_with_tool_failure_still_answers_the_knowledge_part(monkeypatch, rag_calls):
    stub_http(monkeypatch, incident_service_timeout)

    run_id, state = run_agent(
        "What is the status of ticket 482 and what is the no-show fee policy?"
    )

    assert "handle_tool_failure" in nodes_run(run_id)
    assert "retrieve" in nodes_run(run_id)
    assert "couldn't confirm" in state["answer"] and "Per policy" in state["answer"]


# ------------------------------------------------------------------- tool contract
def test_tools_are_read_only_get_requests(monkeypatch, rag_calls):
    requests = stub_http(monkeypatch, incident_service_up)

    run_agent("What is the status of ticket 482?")
    run_agent("How many open tickets are there?")

    assert requests and all(r.method == "GET" for r in requests)


def test_every_request_has_an_explicit_numeric_timeout():
    assert isinstance(tools.TOOL_TIMEOUT_SECONDS, float)
    assert 0 < tools.TOOL_TIMEOUT_SECONDS <= 10
    client = tools.build_client("http://localhost:8000")
    assert client.timeout.read == tools.TOOL_TIMEOUT_SECONDS


def test_ticket_list_by_status(monkeypatch, rag_calls):
    stub_http(monkeypatch, incident_service_up)

    _, state = run_agent("How many open tickets are there?")

    assert "1 ticket(s)" in state["answer"] and "open" in state["answer"]


# ------------------------------------------------------------------ inventory tool
def test_inventory_tool_logs_in_then_reads_with_get(monkeypatch, rag_calls):
    monkeypatch.setenv("AGENT_SERVICE_EMAIL", "agent@healthcore.test")
    monkeypatch.setenv("AGENT_SERVICE_PASSWORD", "secret")

    def inventory_service(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/auth/login":
            return httpx.Response(200, json={"access_token": "t", "token_type": "bearer"})
        assert request.headers["authorization"] == "Bearer t"
        return httpx.Response(
            200,
            json=[
                {"id": 1, "name": "Nitrile Gloves", "sku": "GLV-001", "category": "ppe",
                 "unit": "box", "country": "US", "current_stock": 42},
                {"id": 2, "name": "Syringes 5ml", "sku": "SYR-005", "category": "consumable",
                 "unit": "box", "country": "US", "current_stock": 7},
            ],
        )

    requests = stub_http(monkeypatch, inventory_service)

    run_id, state = run_agent("What is the stock of nitrile gloves?")
    trace = load_trace(run_id)

    assert trace["sources_used"] == ["inventory_tool"]
    assert "lookup_ticket" not in nodes_run(run_id), "tickets and inventory are separate tools"
    assert "Nitrile Gloves" in state["answer"] and "42" in state["answer"]
    assert "Syringes" not in state["answer"]
    assert [r.method for r in requests] == ["POST", "GET"]  # login, then read-only GET
    assert requests[0].url.path == "/auth/login"


def test_inventory_without_credentials_falls_back_honestly(monkeypatch, rag_calls):
    monkeypatch.delenv("AGENT_SERVICE_EMAIL", raising=False)
    monkeypatch.delenv("AGENT_SERVICE_PASSWORD", raising=False)
    stub_http(monkeypatch, lambda r: httpx.Response(500))

    run_id, state = run_agent("What is the stock of nitrile gloves?")

    assert "handle_tool_failure" in nodes_run(run_id)
    assert "couldn't confirm the stock levels" in state["answer"]


# -------------------------------------------------------------------------- router
@pytest.mark.parametrize(
    "question, route, tools_expected",
    [
        ("What is the status of ticket 482?", "tool", ["ticket"]),
        ("Is incident #17 resolved yet?", "tool", ["ticket"]),
        ("How many open tickets are there?", "tool", ["ticket"]),
        ("Do we have nitrile gloves in stock?", "tool", ["inventory"]),
        ("What is the refund policy for cancelled appointments?", "rag", []),
        ("What is the procedure for reporting an incident?", "rag", []),
        ("Does HealthCore accept Medicaid in Georgia?", "rag", []),
        ("Status of ticket 5 and what is the escalation procedure?", "both", ["ticket"]),
    ],
)
def test_router_decisions(question, route, tools_expected):
    decision = classify_question(question)
    assert decision.route == route
    assert decision.tools == tools_expected
    assert decision.rationale


def test_empty_question_stops_before_routing(rag_calls):
    run_id, state = run_agent("   ")
    assert state["error"] == "empty_question"
    assert "route_intent" not in nodes_run(run_id)