"""External tools for the support agent: live data that does NOT belong in the RAG.

Design rules (see the project brief):
  - Tools read from the REAL services (incident manager, inventory) over HTTP.
    There is no fake or parallel dataset anywhere in this file.
  - Tools are READ-ONLY: every data request is a GET. The only POST in this file is
    the inventory login (authentication, it never creates or changes inventory data).
  - One responsibility per tool: `lookup_ticket` and `lookup_inventory` are separate.
  - Every request has an explicit numeric timeout.
  - Tools NEVER raise: failures come back as a structured `outcome` + `error`, so the
    graph can route to a fallback branch instead of crashing.
  - Ticket descriptions are never returned: they could contain sensitive text, and the
    agent only needs status-level information.
"""

from __future__ import annotations

import os
from typing import Literal

import httpx
from pydantic import BaseModel

# --- Configuration (same env-var pattern as the rest of the monorepo) ----------------
INCIDENT_API_BASE_URL = os.getenv("INCIDENT_API_BASE_URL", "http://localhost:8000")
INVENTORY_API_BASE_URL = os.getenv("INVENTORY_API_BASE_URL", INCIDENT_API_BASE_URL)

# Explicit numeric timeout (seconds) applied to EVERY request made by a tool.
TOOL_TIMEOUT_SECONDS = float(os.getenv("AGENT_TOOL_TIMEOUT_SECONDS", "4.0"))

MAX_LIST_RESULTS = 5

Outcome = Literal["success", "timeout", "not_found", "http_error"]


def build_client(base_url: str) -> httpx.Client:
    """Single place where HTTP clients are created (tests replace it with a stub)."""
    return httpx.Client(base_url=base_url, timeout=TOOL_TIMEOUT_SECONDS)


# =============================================================================
# Tool 1: incident ticket lookup
# =============================================================================
class TicketLookupInput(BaseModel):
    # Incident ids in this monorepo are strings (TinyDB doc ids like "482").
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
    """Read ticket data from the incident manager (GET only)."""
    # The incident API is public (no auth, per the Centralized Incident Manager spec),
    # so no credential is attached here. If it ever gets protected, read the token
    # from the environment and add an Authorization header in this function.
    try:
        with build_client(INCIDENT_API_BASE_URL) as client:
            if params.ticket_id:
                response = client.get(f"/api/incidents/{params.ticket_id}")
            else:
                query = {"status": params.status} if params.status else {}
                response = client.get("/api/incidents", params=query)
            response.raise_for_status()
            body = response.json()
    except httpx.TimeoutException:
        return _ticket_error(
            "timeout",
            f"incident service did not answer within {TOOL_TIMEOUT_SECONDS}s",
            ticket_id=params.ticket_id,
        )
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 404:
            return _ticket_error(
                "not_found", "ticket not found", ticket_id=params.ticket_id
            )
        return _ticket_error(
            "http_error",
            f"incident service returned HTTP {exc.response.status_code}",
            ticket_id=params.ticket_id,
        )
    except (httpx.RequestError, ValueError) as exc:
        return _ticket_error(
            "http_error",
            f"incident service unreachable or invalid response: {type(exc).__name__}",
            ticket_id=params.ticket_id,
        )

    if params.ticket_id:
        return TicketLookupOutput(
            found=True,
            outcome="success",
            ticket_id=str(body.get("id", params.ticket_id)),
            title=body.get("title"),
            status=body.get("status"),
            category=body.get("category"),
            origin=body.get("origin"),
            branch=body.get("branch"),
            created_at=body.get("created_at"),
            updated_at=body.get("updated_at"),
        )

    incidents = body if isinstance(body, list) else []
    return TicketLookupOutput(
        found=len(incidents) > 0,
        outcome="success",
        status=params.status,
        count=len(incidents),
        matches=[
            TicketSummary(
                ticket_id=str(i.get("id")), title=i.get("title", ""), status=i.get("status", "")
            )
            for i in incidents[:MAX_LIST_RESULTS]
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


def _inventory_auth_header(client: httpx.Client) -> dict[str, str]:
    """The inventory API requires a JWT. Log in with service credentials from the
    environment (never hardcoded). Raises httpx errors, handled by the caller."""
    email = os.getenv("AGENT_SERVICE_EMAIL")
    password = os.getenv("AGENT_SERVICE_PASSWORD")
    if not email or not password:
        raise PermissionError("AGENT_SERVICE_EMAIL / AGENT_SERVICE_PASSWORD are not set")
    response = client.post("/auth/login", data={"username": email, "password": password})
    response.raise_for_status()
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def lookup_inventory(params: InventoryLookupInput) -> InventoryLookupOutput:
    """Read stock levels from the inventory manager (GET only, after login)."""
    query = params.query.strip() if params.query else None
    try:
        with build_client(INVENTORY_API_BASE_URL) as client:
            headers = _inventory_auth_header(client)
            response = client.get("/inventory/products", headers=headers)
            response.raise_for_status()
            products = response.json()
    except PermissionError as exc:
        return _inventory_error("http_error", str(exc), query)
    except httpx.TimeoutException:
        return _inventory_error(
            "timeout",
            f"inventory service did not answer within {TOOL_TIMEOUT_SECONDS}s",
            query,
        )
    except httpx.HTTPStatusError as exc:
        return _inventory_error(
            "http_error", f"inventory service returned HTTP {exc.response.status_code}", query
        )
    except (httpx.RequestError, ValueError, KeyError) as exc:
        return _inventory_error(
            "http_error",
            f"inventory service unreachable or invalid response: {type(exc).__name__}",
            query,
        )

    if query:
        needle = query.lower()
        products = [
            p for p in products if needle in p["name"].lower() or needle in p["sku"].lower()
        ]
    if not products:
        return _inventory_error("not_found", "no matching product", query)

    return InventoryLookupOutput(
        found=True,
        outcome="success",
        query=query,
        matches=[
            SupplyStock(
                product_id=p["id"],
                name=p["name"],
                sku=p["sku"],
                unit=p["unit"],
                country=p["country"],
                current_stock=p["current_stock"],
            )
            for p in products[:MAX_LIST_RESULTS]
        ],
    )