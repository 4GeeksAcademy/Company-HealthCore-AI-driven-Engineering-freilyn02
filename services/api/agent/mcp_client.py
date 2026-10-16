"""MCP client for the support agent: the ONLY way the agent reaches company tools.

The agent talks to the HealthCore company-tools MCP server (mcps/company-tools) through
`langchain-mcp-adapters`, over Streamable HTTP, presenting an OAuth access token on every
connection. Replaces the old direct HTTP calls to the Incidents Manager / Inventory API.

`call_tool` NEVER raises: it returns a `ToolCallResult` with either `data` (the tool's
structured output) or an `error_code` from the server's documented catalogue
(AUTH_MISSING_TOKEN, AUTH_INVALID_TOKEN, VALIDATION_ERROR, TICKET_NOT_FOUND, ...), so the
graph can route to its fallback branch instead of crashing.

Token sources (first match wins):
  1. MCP_ACCESS_TOKEN                      static token (local dev / Playground tests)
  2. MCP_TOKEN_URL + MCP_CLIENT_ID + MCP_CLIENT_SECRET [+ MCP_AUDIENCE, MCP_SCOPE]
                                           OAuth client-credentials grant, cached until expiry
"""

from __future__ import annotations

import asyncio
import json
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any

import httpx

MCP_SERVER_URL = os.getenv("MCP_SERVER_URL", "http://localhost:8001/mcp")
# Explicit numeric timeout (seconds) for the whole tool call, token fetch included.
MCP_TIMEOUT_SECONDS = float(os.getenv("MCP_TIMEOUT_SECONDS", os.getenv("AGENT_TOOL_TIMEOUT_SECONDS", "8.0")))
SERVER_NAME = "company_tools"


@dataclass
class ToolCallResult:
    ok: bool
    data: dict[str, Any] = field(default_factory=dict)
    error_code: str | None = None
    message: str | None = None


# --------------------------------------------------------------------------- token
_token_lock = threading.Lock()
_cached: tuple[str, float] | None = None  # (token, expires_at epoch)


def _fetch_client_credentials_token() -> str | None:
    url = os.getenv("MCP_TOKEN_URL")
    client_id = os.getenv("MCP_CLIENT_ID")
    client_secret = os.getenv("MCP_CLIENT_SECRET")
    if not (url and client_id and client_secret):
        return None
    global _cached
    with _token_lock:
        if _cached and _cached[1] > time.time() + 30:
            return _cached[0]
        payload = {
            "grant_type": "client_credentials",
            "client_id": client_id,
            "client_secret": client_secret,
        }
        if os.getenv("MCP_AUDIENCE"):
            payload["audience"] = os.environ["MCP_AUDIENCE"]
        if os.getenv("MCP_SCOPE"):
            payload["scope"] = os.environ["MCP_SCOPE"]
        response = httpx.post(url, data=payload, timeout=MCP_TIMEOUT_SECONDS)
        response.raise_for_status()
        body = response.json()
        _cached = (body["access_token"], time.time() + float(body.get("expires_in", 300)))
        return _cached[0]


def get_access_token() -> str | None:
    return os.getenv("MCP_ACCESS_TOKEN") or _fetch_client_credentials_token()


def reset_token_cache() -> None:  # used by tests
    global _cached
    _cached = None


# --------------------------------------------------------------------------- call
def _parse_tool_output(raw: Any) -> ToolCallResult:
    """langchain-mcp-adapters returns the tool's content blocks; our server puts the JSON
    document (result or {"error_code": ...}) in the first text block."""
    if isinstance(raw, list):
        text = next((b.get("text") for b in raw if isinstance(b, dict) and b.get("type") == "text"), None)
    else:
        text = raw if isinstance(raw, str) else None
    try:
        document = json.loads(text) if text else None
    except ValueError:
        document = None
    if not isinstance(document, dict):
        return ToolCallResult(False, error_code="UPSTREAM_ERROR", message="MCP tool returned an unreadable result")
    if "error_code" in document:
        return ToolCallResult(False, error_code=document["error_code"], message=document.get("message"))
    return ToolCallResult(True, data=document)


def _flatten(exc: BaseException) -> list[BaseException]:
    if isinstance(exc, BaseExceptionGroup):
        return [leaf for inner in exc.exceptions for leaf in _flatten(inner)]
    return [exc]


def _classify_exception(exc: BaseException) -> ToolCallResult:
    for leaf in _flatten(exc):
        if isinstance(leaf, httpx.HTTPStatusError) and leaf.response.status_code in (401, 403):
            code = "AUTH_INSUFFICIENT_SCOPE" if leaf.response.status_code == 403 else "AUTH_INVALID_TOKEN"
            return ToolCallResult(False, error_code=code, message="MCP server rejected the access token")
        if isinstance(leaf, (httpx.TimeoutException, TimeoutError, asyncio.TimeoutError)):
            return ToolCallResult(False, error_code="UPSTREAM_TIMEOUT", message="MCP server did not answer in time")
    leaf = _flatten(exc)[0]
    return ToolCallResult(False, error_code="UPSTREAM_ERROR", message=f"MCP server unreachable: {type(leaf).__name__}")


async def _call_async(name: str, arguments: dict[str, Any], token: str) -> ToolCallResult:
    # Imported lazily so the rest of the API (and its tests) never needs the MCP stack.
    from langchain_mcp_adapters.client import MultiServerMCPClient

    client = MultiServerMCPClient(
        {
            SERVER_NAME: {
                "transport": "streamable_http",
                "url": MCP_SERVER_URL,
                "headers": {"Authorization": f"Bearer {token}"},
            }
        }
    )
    tools = {t.name: t for t in await client.get_tools()}
    if name not in tools:
        return ToolCallResult(False, error_code="UPSTREAM_ERROR", message=f"MCP server has no tool '{name}'")
    return _parse_tool_output(await tools[name].ainvoke(arguments))


def _run_in_fresh_loop(coro_factory) -> ToolCallResult:
    return asyncio.run(asyncio.wait_for(coro_factory(), timeout=MCP_TIMEOUT_SECONDS))


def call_tool(name: str, arguments: dict[str, Any]) -> ToolCallResult:
    """Synchronous entry point used by the (synchronous) LangGraph nodes."""
    try:
        token = get_access_token()
    except httpx.TimeoutException:
        return ToolCallResult(False, error_code="UPSTREAM_TIMEOUT", message="token endpoint timed out")
    except Exception as exc:  # noqa: BLE001 - never raise into the graph
        return ToolCallResult(False, error_code="AUTH_INVALID_TOKEN", message=f"could not obtain a token: {type(exc).__name__}")
    if not token:
        return ToolCallResult(
            False,
            error_code="AUTH_MISSING_TOKEN",
            message="No MCP credentials configured (MCP_ACCESS_TOKEN or MCP_TOKEN_URL/MCP_CLIENT_ID/MCP_CLIENT_SECRET).",
        )
    try:
        # A fresh event loop per call, in a worker thread: safe whether or not the caller
        # already runs inside an event loop (FastAPI sync endpoints, notebooks, tests).
        with ThreadPoolExecutor(max_workers=1) as pool:
            return pool.submit(_run_in_fresh_loop, lambda: _call_async(name, arguments, token)).result()
    except BaseException as exc:  # noqa: BLE001 - includes ExceptionGroup from the MCP transport
        return _classify_exception(exc)
