"""Part 2 evals: routing between RAG and external tools, and the failure fallback.

The MCP server is stubbed ONLY here, in the test fixtures, so CI needs no running
services: `mcp_client.call_tool` is replaced by a fake that answers exactly like the real
company-tools server (same tool names, argument contract and error codes). The production
code under test is still the real tool adapters and the real graph. The real client <->
server <-> OAuth path is covered by mcps/company-tools/tests and the PR evidence.
"""

import pytest

from agent import mcp_client, nodes, tools, tracing
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


def stub_mcp(monkeypatch, handler):
    """Replace the MCP call with `handler(tool_name, arguments) -> ToolCallResult`.
    Returns the list of (tool_name, arguments) calls that were made."""
    calls: list[tuple[str, dict]] = []

    def recording(name: str, arguments: dict) -> mcp_client.ToolCallResult:
        calls.append((name, arguments))
        return handler(name, arguments)

    monkeypatch.setattr(mcp_client, "call_tool", recording)
    return calls


def ok(data: dict) -> mcp_client.ToolCallResult:
    return mcp_client.ToolCallResult(True, data=data)


def fail(code: str, message: str = "simulated") -> mcp_client.ToolCallResult:
    return mcp_client.ToolCallResult(False, error_code=code, message=message)


def _mcp_ticket(raw: dict) -> dict:
    # what manage_incident_ticket returns: no description, integer ticket_id
    return {
        "ticket_id": int(raw["id"]), "title": raw["title"], "status": raw["status"],
        "category": raw["category"], "origin": raw["origin"], "branch": raw["branch"],
        "created_at": raw["created_at"], "updated_at": raw["updated_at"],
    }


def incident_service_up(name: str, arguments: dict) -> mcp_client.ToolCallResult:
    if name == "manage_incident_ticket" and arguments == {"action": "get_status", "ticket_id": 482}:
        return ok(_mcp_ticket(TICKET_482))
    if name == "manage_incident_ticket":
        return fail("TICKET_NOT_FOUND")
    if name == "list_incident_tickets" and arguments.get("status") == "open":
        return ok({"count": 1, "tickets": [{"ticket_id": 482, "title": TICKET_482["title"], "status": "open"}]})
    if name == "list_incident_tickets":
        return ok({"count": 0, "tickets": []})
    return fail("UPSTREAM_ERROR")


def incident_service_timeout(name: str, arguments: dict) -> mcp_client.ToolCallResult:
    return fail("UPSTREAM_TIMEOUT")


def nodes_run(run_id: str) -> list[str]:
    return [s["node"] for s in load_trace(run_id)["trace_steps"]]


# --------------------------------------------------------------------------- evals
def test_eval_tool_routing_uses_ticket_tool_not_rag(monkeypatch, rag_calls):
    requests = stub_mcp(monkeypatch, incident_service_up)

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
    assert [c[0] for c in requests] == ["manage_incident_ticket"]
    assert requests[0][1]["action"] == "get_status"


def test_eval_rag_routing_uses_rag_not_tools(monkeypatch, rag_calls):
    requests = stub_mcp(monkeypatch, incident_service_up)

    run_id, state = run_agent("What is the no-show fee policy for Medicare patients?")
    trace = load_trace(run_id)

    assert trace["route"] == "rag"
    assert "retrieve" in nodes_run(run_id) and "query" in nodes_run(run_id)
    assert not {"lookup_ticket", "lookup_inventory"} & set(nodes_run(run_id))
    assert trace["sources_used"] == ["rag"]
    assert requests == [], "no external service may be called on a RAG-only question"
    assert "Medicare" in state["answer"]


def test_eval_fallback_when_incident_service_times_out(monkeypatch, rag_calls):
    stub_mcp(monkeypatch, incident_service_timeout)

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
    stub_mcp(monkeypatch, incident_service_up)

    run_id, state = run_agent("What is the status of ticket 999?")
    step = next(s for s in load_trace(run_id)["trace_steps"] if s["node"] == "lookup_ticket")

    assert step["outcome"] == "not_found"
    assert "handle_tool_failure" in nodes_run(run_id)
    assert "couldn't find a ticket with id 999" in state["answer"]


def test_both_route_runs_tool_then_rag_and_merges(monkeypatch, rag_calls):
    stub_mcp(monkeypatch, incident_service_up)

    run_id, state = run_agent(
        "What is the status of ticket 482 and what is the no-show fee policy?"
    )
    trace = load_trace(run_id)

    assert trace["route"] == "both"
    assert trace["sources_used"] == ["ticket_tool", "rag"]  # tool first, then RAG
    assert nodes_run(run_id)[-1] == "synthesize_answer"
    assert "Ticket 482" in state["answer"] and "Per policy" in state["answer"]


def test_both_route_with_tool_failure_still_answers_the_knowledge_part(monkeypatch, rag_calls):
    stub_mcp(monkeypatch, incident_service_timeout)

    run_id, state = run_agent(
        "What is the status of ticket 482 and what is the no-show fee policy?"
    )

    assert "handle_tool_failure" in nodes_run(run_id)
    assert "retrieve" in nodes_run(run_id)
    assert "couldn't confirm" in state["answer"] and "Per policy" in state["answer"]


# ------------------------------------------------------------------- tool contract
def test_agent_only_uses_read_only_mcp_operations(monkeypatch, rag_calls):
    calls = stub_mcp(monkeypatch, incident_service_up)

    run_agent("What is the status of ticket 482?")
    run_agent("How many open tickets are there?")

    assert calls
    for name, arguments in calls:
        assert name in {"list_incident_tickets", "query_inventory", "manage_incident_ticket"}
        if name == "manage_incident_ticket":
            assert arguments["action"] == "get_status"  # never create/update from the agent


def test_old_direct_http_path_is_gone():
    assert not hasattr(tools, "build_client")
    assert not hasattr(tools, "INCIDENT_API_BASE_URL")


def test_mcp_call_has_an_explicit_numeric_timeout():
    assert isinstance(mcp_client.MCP_TIMEOUT_SECONDS, float)
    assert 0 < mcp_client.MCP_TIMEOUT_SECONDS <= 30


def test_missing_mcp_credentials_fall_back_honestly(monkeypatch, rag_calls):
    for var in ("MCP_ACCESS_TOKEN", "MCP_TOKEN_URL", "MCP_CLIENT_ID", "MCP_CLIENT_SECRET"):
        monkeypatch.delenv(var, raising=False)
    mcp_client.reset_token_cache()

    run_id, state = run_agent("What is the status of ticket 482?")  # real call_tool, no token

    step = next(s for s in load_trace(run_id)["trace_steps"] if s["node"] == "lookup_ticket")
    assert step["outcome"] == "http_error"
    assert "couldn't confirm" in state["answer"]


def test_ticket_list_by_status(monkeypatch, rag_calls):
    stub_mcp(monkeypatch, incident_service_up)

    _, state = run_agent("How many open tickets are there?")

    assert "1 ticket(s)" in state["answer"] and "open" in state["answer"]


# ------------------------------------------------------------------ inventory tool
def test_inventory_goes_through_the_mcp_inventory_tool(monkeypatch, rag_calls):
    def inventory_service(name, arguments):
        assert name == "query_inventory" and "updates" not in arguments  # read-only call
        return ok({"count": 1, "products": [
            {"product_id": 1, "name": "Nitrile Gloves", "sku": "GLV-001", "category": "ppe",
             "unit": "box", "country": "US", "current_stock": 42},
        ]})

    calls = stub_mcp(monkeypatch, inventory_service)

    run_id, state = run_agent("What is the stock of nitrile gloves?")
    trace = load_trace(run_id)

    assert trace["sources_used"] == ["inventory_tool"]
    assert "lookup_ticket" not in nodes_run(run_id), "tickets and inventory are separate tools"
    assert "Nitrile Gloves" in state["answer"] and "42" in state["answer"]
    assert calls == [("query_inventory", {"query": "nitrile gloves"})]


def test_inventory_mcp_error_falls_back_honestly(monkeypatch, rag_calls):
    stub_mcp(monkeypatch, lambda n, a: fail("UPSTREAM_ERROR", "no service credentials"))

    run_id, state = run_agent("What is the stock of nitrile gloves?")

    assert "handle_tool_failure" in nodes_run(run_id)
    assert "couldn't confirm the stock levels" in state["answer"]


def test_expired_oauth_token_falls_back_honestly(monkeypatch, rag_calls):
    stub_mcp(monkeypatch, lambda n, a: fail("AUTH_INVALID_TOKEN"))

    run_id, state = run_agent("What is the status of ticket 482?")

    step = next(s for s in load_trace(run_id)["trace_steps"] if s["node"] == "lookup_ticket")
    assert step["outcome"] == "http_error"
    assert state["error"] is None and "couldn't confirm" in state["answer"]


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