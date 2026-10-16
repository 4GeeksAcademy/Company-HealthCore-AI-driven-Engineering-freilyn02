"""External tools for the support agent: live data that does NOT belong in the RAG.

Since the MCP migration, these functions are thin adapters: they call the company-tools
MCP server (mcps/company-tools) through `agent.mcp_client` (langchain-mcp-adapters over
Streamable HTTP, OAuth-protected) and translate its result into the typed outputs the
graph already uses. There are NO direct HTTP calls to the Incidents Manager or the
Inventory API left in the agent.

Design rules (unchanged):
  - One responsibility per tool: `lookup_ticket` and `lookup_inventory` are separate.
  - Tools NEVER raise: failures come back as a structured `outcome` + `error`, so the
    graph can route to a fallback branch instead of crashing.
  - Ticket descriptions are never returned: the MCP server does not expose them.
  - Read-only from the agent's side: it only uses `get_status`, `list_incident_tickets`
    and `query_inventory`. Creating/updating tickets stays available to other MCP clients.

Deprecated and removed: `build_client`, `INCIDENT_API_BASE_URL`, `INVENTORY_API_BASE_URL`
and the direct `httpx` lookups. Configure the MCP connection instead (see mcp_client.py).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

from . import mcp_client

MAX_LIST_RESULTS = 5

Outcome = Literal["success", "timeout", "not_found", "http_error"]

# MCP error_code -> outcome recorded in the trace
_OUTCOME_BY_CODE: dict[str, Outcome] = {
    "TICKET_NOT_FOUND": "not_found",
    "UPSTREAM_TIMEOUT": "timeout",
}


def _outcome_for(result: mcp_client.ToolCallResult) -> Outcome:
    return _OUTCOME_BY_CODE.get(result.error_code or "", "http_error")


# =============================================================================
# Tool 1: incident ticket lookup
# =============================================================================
class TicketLookupInput(BaseModel):
    # Kept as a string for the router; converted to the integer the MCP tool requires.
    ticket_id: str | None = None
    status: str | None = None  # optional filter for the list endpoint


class TicketSummary(BaseModel):
    ticket_id: str
    title: str
    status: str


class TicketLookupOutput(BaseModel):
    found: bool
    outcome: Outcome
    ticket_id: str | None = None
    title: str | None = None
    status: str | None = None
    category: str | None = None
    origin: str | None = None
    branch: str | None = None
    created_at: str | None = None
    updated_at: str | None = None
    # Only used when the lookup is a list (status filter, no ticket_id)
    count: int | None = None
    matches: list[TicketSummary] = []
    error: str | None = None  # set on timeout / HTTP failure / not found


def _ticket_error(outcome: Outcome, error: str, **extra) -> TicketLookupOutput:
    return TicketLookupOutput(found=False, outcome=outcome, error=error, **extra)


def lookup_ticket(params: TicketLookupInput) -> TicketLookupOutput:
    """Read ticket data through the MCP server (get_status / list_incident_tickets)."""
    if params.ticket_id:
        try:
            ticket_id = int(params.ticket_id)
        except ValueError:
            return _ticket_error("not_found", "ticket not found", ticket_id=params.ticket_id)
        result = mcp_client.call_tool(
            "manage_incident_ticket", {"action": "get_status", "ticket_id": ticket_id}
        )
    else:
        arguments = {"status": params.status} if params.status else {}
        result = mcp_client.call_tool("list_incident_tickets", arguments)

    if not result.ok:
        return _ticket_error(
            _outcome_for(result),
            f"{result.error_code}: {result.message}",
            ticket_id=params.ticket_id,
        )

    body = result.data
    if params.ticket_id:
        return TicketLookupOutput(
            found=True,
            outcome="success",
            ticket_id=str(body.get("ticket_id", params.ticket_id)),
            title=body.get("title"),
            status=body.get("status"),
            category=body.get("category"),
            origin=body.get("origin"),
            branch=body.get("branch"),
            created_at=body.get("created_at"),
            updated_at=body.get("updated_at"),
        )

    tickets = body.get("tickets", [])
    return TicketLookupOutput(
        found=body.get("count", 0) > 0,
        outcome="success",
        status=params.status,
        count=body.get("count", len(tickets)),
        matches=[
            TicketSummary(
                ticket_id=str(t["ticket_id"]), title=t.get("title", ""), status=t.get("status", "")
            )
            for t in tickets[:MAX_LIST_RESULTS]
        ],
    )


# =============================================================================
# Tool 2 (stretch): inventory lookup
# =============================================================================
class InventoryLookupInput(BaseModel):
    query: str | None = None  # product name or SKU (case-insensitive substring)


class SupplyStock(BaseModel):
    product_id: int
    name: str
    sku: str
    unit: str
    country: str
    current_stock: int


class InventoryLookupOutput(BaseModel):
    found: bool
    outcome: Outcome
    query: str | None = None
    matches: list[SupplyStock] = []
    error: str | None = None


def _inventory_error(outcome: Outcome, error: str, query: str | None) -> InventoryLookupOutput:
    return InventoryLookupOutput(found=False, outcome=outcome, error=error, query=query)


def lookup_inventory(params: InventoryLookupInput) -> InventoryLookupOutput:
    """Read stock levels through the MCP server (query_inventory, read-only)."""
    query = params.query.strip() if params.query else None
    arguments = {"query": query} if query else {}
    result = mcp_client.call_tool("query_inventory", arguments)

    if not result.ok:
        return _inventory_error(_outcome_for(result), f"{result.error_code}: {result.message}", query)

    products = result.data.get("products", [])
    if not products:
        return _inventory_error("not_found", "no matching product", query)
    return InventoryLookupOutput(
        found=True,
        outcome="success",
        query=query,
        matches=[
            SupplyStock(
                product_id=p["product_id"],
                name=p["name"],
                sku=p["sku"],
                unit=p["unit"],
                country=p["country"],
                current_stock=p["current_stock"],
            )
            for p in products[:MAX_LIST_RESULTS]
        ],
    )
