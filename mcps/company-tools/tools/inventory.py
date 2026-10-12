"""Tool: READ-ONLY lookup of HealthCore medical-supply stock (live HTTP calls).

Read-only by design, not by omission: the tool accepts `action` and `updates` precisely so it
can REFUSE writes with a distinct, documented error (INVENTORY_WRITE_FORBIDDEN). The refusal
happens before any network call, so a write can never reach the inventory API from here.

The inventory API is JWT-protected, so the server logs in with a service account taken from
the environment (AGENT_SERVICE_EMAIL / AGENT_SERVICE_PASSWORD, never hardcoded). That is the
server's own credential, separate from the OAuth token the MCP *client* presents to us.
"""

from __future__ import annotations

from typing import Any

import httpx
from pydantic import BaseModel

import http_client
from auth import require_scope
from config import SCOPE_INVENTORY_READ, Settings
from errors import ErrorCode, ToolFailure

TOOL_NAME = "query_inventory"
MAX_RESULTS = 20

DESCRIPTION = (
    "Read-only lookup of HealthCore medical-supply stock. Write operations are not "
    "supported and are rejected with error_code INVENTORY_WRITE_FORBIDDEN.\n"
    "- Search by 'query' (case-insensitive part of the product name or SKU) or by "
    "'product_id'. With neither, the first products are listed.\n"
    "- 'action' must be 'read' (the default). Any other action, or any value in "
    "'updates', is rejected: this server never changes inventory.\n"
    "Requires the 'inventory:read' scope."
)


class SupplyStock(BaseModel):
    product_id: int
    name: str
    sku: str
    category: str
    unit: str
    country: str
    current_stock: int


class InventoryResult(BaseModel):
    count: int
    products: list[SupplyStock]


def _fail(code: ErrorCode, message: str | None = None, field: str | None = None) -> ToolFailure:
    return ToolFailure(code, tool=TOOL_NAME, message=message, field=field)


def _to_stock(p: dict[str, Any]) -> SupplyStock:
    return SupplyStock(
        product_id=p["id"], name=p["name"], sku=p["sku"], category=str(p["category"]),
        unit=str(p["unit"]), country=str(p["country"]), current_stock=p["current_stock"],
    )


async def _login(client: httpx.AsyncClient, settings: Settings) -> dict[str, str]:
    if not settings.service_email or not settings.service_password:
        raise _fail(
            ErrorCode.UPSTREAM_ERROR,
            "The MCP server has no inventory service credentials configured "
            "(AGENT_SERVICE_EMAIL / AGENT_SERVICE_PASSWORD).",
        )
    response = await client.post(
        "/auth/login", data={"username": settings.service_email, "password": settings.service_password}
    )
    response.raise_for_status()
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


async def query_inventory(
    settings: Settings,
    query: str | None = None,
    product_id: int | None = None,
    action: str = "read",
    updates: dict[str, Any] | None = None,
) -> InventoryResult:
    # 1) Explicit write rejection FIRST: distinct from auth and validation errors.
    if action != "read" or updates:
        raise _fail(ErrorCode.INVENTORY_WRITE_FORBIDDEN)

    # 2) Least privilege.
    require_scope(SCOPE_INVENTORY_READ, TOOL_NAME)

    # 3) Live read from the inventory API.
    try:
        async with http_client.build_client(settings.inventory_api_base_url, settings) as client:
            headers = await _login(client, settings)
            if product_id is not None:
                response = await client.get(f"/inventory/products/{product_id}", headers=headers)
                if response.status_code == 404:
                    return InventoryResult(count=0, products=[])
                response.raise_for_status()
                products = [response.json()]
            else:
                response = await client.get("/inventory/products", headers=headers)
                response.raise_for_status()
                products = response.json()
    except ToolFailure:
        raise
    except httpx.TimeoutException:
        raise _fail(
            ErrorCode.UPSTREAM_TIMEOUT,
            f"Inventory service did not answer within {settings.request_timeout_seconds}s.",
        )
    except httpx.HTTPStatusError as exc:
        raise _fail(
            ErrorCode.UPSTREAM_ERROR, f"Inventory service returned HTTP {exc.response.status_code}."
        )
    except (httpx.RequestError, ValueError, KeyError) as exc:
        raise _fail(
            ErrorCode.UPSTREAM_ERROR,
            f"Inventory service is unreachable or returned an invalid response ({type(exc).__name__}).",
        )

    if query and query.strip():
        needle = query.strip().lower()
        products = [
            p for p in products if needle in p["name"].lower() or needle in p["sku"].lower()
        ]
    found = [_to_stock(p) for p in products[:MAX_RESULTS]]
    return InventoryResult(count=len(found), products=found)
