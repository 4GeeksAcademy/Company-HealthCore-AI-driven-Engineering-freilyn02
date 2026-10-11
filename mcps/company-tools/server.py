"""HealthCore company-tools MCP server.

Run (from this folder, with the services/api environment):
    uv run --project ../../services/api python server.py

Transport: Streamable HTTP (remote clients, MCP Playground, the LangGraph agent), protected by
OAuth through MCP Auth. See README.md for the reasoning and the environment variables.
"""

from __future__ import annotations

import logging
from typing import Annotated, Any

import uvicorn
from fastmcp import FastMCP
from pydantic import Field
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.routing import Mount

from audit_log import InvocationLogMiddleware
from auth import AuthErrorCodeMiddleware, build_mcp_auth
from config import Settings, load_settings
from tools import incidents, inventory

SERVER_INSTRUCTIONS = (
    "HealthCore company tools. Use manage_incident_ticket to create, update or look up "
    "incident tickets (list_incident_tickets lists them), and query_inventory to read medical-supply stock. Inventory is "
    "read-only. Never include patient-identifying data in tickets."
)


def build_server(settings: Settings) -> FastMCP:
    mcp = FastMCP(
        "healthcore-company-tools",
        instructions=SERVER_INSTRUCTIONS,
        middleware=[InvocationLogMiddleware()],
    )

    @mcp.tool(name=incidents.TOOL_NAME, description=incidents.DESCRIPTION)
    async def manage_incident_ticket(
        action: Annotated[incidents.Action, Field(description="What to do: 'create', 'update' or 'get_status'.")],
        ticket_id: Annotated[int | None, Field(description="Integer ticket id. Required for 'update' and 'get_status'.")] = None,
        status: Annotated[incidents.Status | None, Field(description="Target status. 'update' only.")] = None,
        title: Annotated[str | None, Field(description="Short title, max 200 chars. 'create' only. No patient data.")] = None,
        description: Annotated[str | None, Field(description="Details, max 2000 chars. 'create' only. No patient data.")] = None,
        category: Annotated[incidents.Category | None, Field(description="Incident category. 'create' only.")] = None,
        origin: Annotated[incidents.Origin | None, Field(description="Who reported it. 'create' only.")] = None,
        branch: Annotated[incidents.Branch | None, Field(description="Clinic branch id. 'create' only.")] = None,
    ) -> incidents.IncidentTicket:
        return await incidents.manage_incident_ticket(
            settings, action, ticket_id, status, title, description, category, origin, branch
        )

    @mcp.tool(name=incidents.LIST_TOOL_NAME, description=incidents.LIST_DESCRIPTION)
    async def list_incident_tickets(
        status: Annotated[incidents.Status | None, Field(description="Only tickets with this status. Omit for all.")] = None,
    ) -> incidents.IncidentList:
        return await incidents.list_incident_tickets(settings, status)

    @mcp.tool(name=inventory.TOOL_NAME, description=inventory.DESCRIPTION)
    async def query_inventory(
        query: Annotated[str | None, Field(description="Case-insensitive part of a product name or SKU.")] = None,
        product_id: Annotated[int | None, Field(description="Exact product id.")] = None,
        action: Annotated[str, Field(description="Must be 'read'. Any other value is rejected (INVENTORY_WRITE_FORBIDDEN).")] = "read",
        updates: Annotated[dict[str, Any] | None, Field(description="NOT SUPPORTED. Any value is rejected (INVENTORY_WRITE_FORBIDDEN).")] = None,
    ) -> inventory.InventoryResult:
        return await inventory.query_inventory(settings, query, product_id, action, updates)

    return mcp


def build_app(
    settings: Settings | None = None,
    auth_server_config: Any | None = None,
    verify: Any = "jwt",
) -> Starlette:
    """ASGI app = Protected Resource Metadata routes + the OAuth-protected MCP endpoint.

    `auth_server_config` / `verify` exist for tests; production uses the defaults
    (issuer discovery from OIDC_ISSUER + built-in JWT validation).
    """
    settings = settings or load_settings()
    mcp = build_server(settings)
    mcp_auth = build_mcp_auth(settings, auth_server_config)

    bearer = mcp_auth.bearer_auth_middleware(
        verify,
        audience=settings.expected_audience,
        resource=settings.resource_url,
        show_error_details=False,
    )
    # Order matters: AuthErrorCodeMiddleware wraps the bearer middleware (outermost first).
    mcp_app = mcp.http_app(
        path=settings.resource_path,
        middleware=[Middleware(AuthErrorCodeMiddleware), Middleware(bearer)],
        stateless_http=True,
    )

    return Starlette(
        routes=[
            *mcp_auth.resource_metadata_router().routes,  # public: clients must discover auth
            Mount("/", app=mcp_app),
        ],
        lifespan=mcp_app.lifespan,
    )


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    settings = load_settings()
    uvicorn.run(build_app(settings), host=settings.host, port=settings.port)


if __name__ == "__main__":
    main()
