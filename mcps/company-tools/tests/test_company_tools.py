"""End-to-end tests of the MCP server over real HTTP, with real JWT validation."""

from __future__ import annotations

import asyncio
import json
import logging

import httpx
import pytest
from fastmcp import Client

INIT_BODY = {
    "jsonrpc": "2.0", "id": 1, "method": "initialize",
    "params": {"protocolVersion": "2025-06-18", "capabilities": {},
               "clientInfo": {"name": "t", "version": "0"}},
}
MCP_HEADERS = {"content-type": "application/json", "accept": "application/json, text/event-stream"}


def _run(coro):
    return asyncio.run(coro)


def call(settings, token, tool, args):
    """Call a tool and return (is_error, payload)."""
    async def go():
        async with Client(settings.resource_url, auth=token) as client:
            result = await client.call_tool(tool, args, raise_on_error=False)
            if result.is_error:
                return True, json.loads(result.content[0].text)
            return False, result.structured_content
    return _run(go())


def list_tools(settings, token):
    async def go():
        async with Client(settings.resource_url, auth=token) as client:
            return await client.list_tools()
    return _run(go())


@pytest.fixture
def token(issuer, mcp_server):
    return issuer.token(audience=mcp_server.resource_url)


# ------------------------------- authentication -------------------------------------
def test_missing_token_is_rejected_before_discovery(mcp_server):
    response = httpx.post(mcp_server.resource_url, json=INIT_BODY, headers=MCP_HEADERS)
    assert response.status_code == 401
    assert response.json()["error_code"] == "AUTH_MISSING_TOKEN"
    assert "resource_metadata" in response.headers["www-authenticate"]


def test_garbage_token_is_invalid(mcp_server):
    headers = {**MCP_HEADERS, "authorization": "Bearer not-a-jwt"}
    response = httpx.post(mcp_server.resource_url, json=INIT_BODY, headers=headers)
    assert response.status_code == 401
    assert response.json()["error_code"] == "AUTH_INVALID_TOKEN"


def test_expired_wrong_audience_and_wrong_issuer_tokens_are_invalid(issuer, mcp_server):
    bad = {
        "expired": issuer.token(audience=mcp_server.resource_url, expires_in=-3600),
        "wrong_audience": issuer.token(audience="https://someone-else.example/mcp"),
        "wrong_issuer": issuer.token(audience=mcp_server.resource_url, issuer="https://evil.example"),
    }
    for name, tok in bad.items():
        response = httpx.post(
            mcp_server.resource_url, json=INIT_BODY,
            headers={**MCP_HEADERS, "authorization": f"Bearer {tok}"},
        )
        assert response.status_code == 401, name
        assert response.json()["error_code"] == "AUTH_INVALID_TOKEN", name


def test_protected_resource_metadata_is_public(mcp_server):
    base = mcp_server.resource_url.rsplit("/mcp", 1)[0]
    response = httpx.get(f"{base}/.well-known/oauth-protected-resource/mcp")
    assert response.status_code == 200
    body = response.json()
    assert body["resource"] == mcp_server.resource_url
    assert body["authorization_servers"]


# --------------------------------- discovery ----------------------------------------
def test_discovery_exposes_both_tools_with_schemas(mcp_server, token):
    tools = {t.name: t for t in list_tools(mcp_server, token)}
    assert set(tools) == {"manage_incident_ticket", "list_incident_tickets", "query_inventory"}
    for tool in tools.values():
        assert tool.description and len(tool.description) > 80
        assert tool.inputSchema["properties"]
        assert tool.outputSchema is not None
    props = tools["manage_incident_ticket"].inputSchema["properties"]
    assert set(props["action"]["enum"]) == {"create", "update", "get_status"}
    assert all(p.get("description") for p in props.values())


# ----------------------------- incident ticket tool ---------------------------------
def test_ticket_full_flow_create_update_status(mcp_server, token, apis):
    is_error, created = call(mcp_server, token, "manage_incident_ticket", {
        "action": "create", "title": "Printer jam", "description": "Third floor printer",
        "category": "facility_issue", "origin": "internal", "branch": "austin_north",
    })
    assert not is_error and created["status"] == "open"
    ticket_id = created["ticket_id"]
    assert "description" not in created  # free text is never returned

    is_error, moved = call(mcp_server, token, "manage_incident_ticket",
                           {"action": "update", "ticket_id": ticket_id, "status": "in_progress"})
    assert not is_error and moved["status"] == "in_progress"
    assert ("PATCH", f"/api/incidents/{ticket_id}/status") in apis.requests  # lifecycle endpoint

    is_error, looked_up = call(mcp_server, token, "manage_incident_ticket",
                               {"action": "get_status", "ticket_id": ticket_id})
    assert not is_error and looked_up["status"] == "in_progress"


def test_invalid_lifecycle_transition_is_validation_error(mcp_server, token):
    is_error, err = call(mcp_server, token, "manage_incident_ticket",
                         {"action": "update", "ticket_id": 482, "status": "open"})
    assert is_error
    assert err["error_code"] == "VALIDATION_ERROR"
    assert err["field"] == "status"
    assert "Cannot move" in err["message"]


def test_unknown_ticket_is_not_found(mcp_server, token):
    is_error, err = call(mcp_server, token, "manage_incident_ticket",
                         {"action": "get_status", "ticket_id": 99999})
    assert is_error and err["error_code"] == "TICKET_NOT_FOUND"


def test_update_must_send_only_status(mcp_server, token):
    is_error, err = call(mcp_server, token, "manage_incident_ticket",
                         {"action": "update", "ticket_id": 482, "status": "resolved", "title": "sneaky"})
    assert is_error and err["error_code"] == "VALIDATION_ERROR" and err["field"] == "title"


def test_create_requires_all_fields(mcp_server, token):
    is_error, err = call(mcp_server, token, "manage_incident_ticket",
                         {"action": "create", "title": "Only a title"})
    assert is_error and err["error_code"] == "VALIDATION_ERROR" and err["field"] == "description"


def test_schema_violation_is_a_validation_error_too(mcp_server, token):
    is_error, err = call(mcp_server, token, "manage_incident_ticket",
                         {"action": "delete", "ticket_id": 1})
    assert is_error and err["error_code"] == "VALIDATION_ERROR" and "action" in err["message"]


def test_list_tickets_with_status_filter(mcp_server, token, apis):
    is_error, result = call(mcp_server, token, "list_incident_tickets", {"status": "open"})
    assert not is_error and result["count"] >= 1
    assert ("GET", "/api/incidents") in apis.requests


# --------------------------------- inventory tool -----------------------------------
def test_inventory_reads_work(mcp_server, token):
    is_error, result = call(mcp_server, token, "query_inventory", {"query": "glove"})
    assert not is_error and result["count"] == 1
    assert result["products"][0]["current_stock"] == 120

    is_error, by_id = call(mcp_server, token, "query_inventory", {"product_id": 2})
    assert not is_error and by_id["products"][0]["sku"] == "PPE-MSK-01"


@pytest.mark.parametrize("args", [
    {"action": "update", "product_id": 1},
    {"action": "delete"},
    {"product_id": 1, "updates": {"current_stock": 9999}},
])
def test_inventory_writes_are_explicitly_rejected_without_touching_the_api(mcp_server, token, apis, args):
    before = len(apis.requests)
    is_error, err = call(mcp_server, token, "query_inventory", args)
    assert is_error
    assert err["error_code"] == "INVENTORY_WRITE_FORBIDDEN"
    assert err["tool"] == "query_inventory"
    assert err["message"].startswith("Inventory tool is read-only")
    assert len(apis.requests) == before  # refused before any HTTP call


# ------------------------------ least privilege (scopes) ----------------------------
def test_missing_scope_is_authorization_error(issuer, mcp_server):
    read_only = issuer.token(audience=mcp_server.resource_url, scope="incidents:read")
    is_error, err = call(mcp_server, read_only, "manage_incident_ticket", {
        "action": "create", "title": "t", "description": "d",
        "category": "other", "origin": "internal", "branch": "central",
    })
    assert is_error and err["error_code"] == "AUTH_INSUFFICIENT_SCOPE"
    # the same token can still read
    is_error, _ = call(mcp_server, read_only, "manage_incident_ticket",
                       {"action": "get_status", "ticket_id": 482})
    assert not is_error


# ------------------------------------ logging ---------------------------------------
def test_one_structured_log_per_invocation(mcp_server, token, caplog):
    with caplog.at_level(logging.INFO, logger="company_tools.invocations"):
        call(mcp_server, token, "manage_incident_ticket", {"action": "get_status", "ticket_id": 482})
        call(mcp_server, token, "query_inventory", {"action": "update"})
        call(mcp_server, token, "manage_incident_ticket", {
            "action": "create", "title": "TOP-SECRET-TITLE", "description": "TOP-SECRET-BODY",
            "category": "other", "origin": "internal", "branch": "central",
        })
    entries = [json.loads(r.message) for r in caplog.records if r.name == "company_tools.invocations"]
    assert len(entries) == 3
    assert {"timestamp", "client_id", "tool", "input_summary", "result", "duration_ms"} <= set(entries[0])
    assert entries[0]["client_id"] == "agent-support-test"
    assert entries[0]["tool"] == "manage_incident_ticket"
    assert entries[0]["input_summary"] == {"action": "get_status", "ticket_id": 482}
    assert entries[0]["result"] == "success"
    assert entries[1]["result"] == "error:INVENTORY_WRITE_FORBIDDEN"
    assert "TOP-SECRET" not in json.dumps(entries)  # titles/descriptions never reach the logs
