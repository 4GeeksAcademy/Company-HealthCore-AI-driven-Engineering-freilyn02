"""Tool: manage incident tickets in the HealthCore Incidents Manager (live HTTP calls).

  create     -> POST  /api/incidents
  update     -> PATCH /api/incidents/{id}/status   (body carries ONLY the new status)
  get_status -> GET   /api/incidents/{id}

The Incidents Manager owns the lifecycle rules: an invalid transition comes back as HTTP 400
and is surfaced here as VALIDATION_ERROR with the API's own field-level message.
"""

from __future__ import annotations

from typing import Any, Literal

import httpx
from pydantic import BaseModel

import http_client
from auth import require_scope
from config import SCOPE_INCIDENTS_READ, SCOPE_INCIDENTS_WRITE, Settings
from errors import ErrorCode, ToolFailure

TOOL_NAME = "manage_incident_ticket"

Action = Literal["create", "update", "get_status"]
Category = Literal[
    "clinical_equipment", "it_system", "billing_error", "compliance_breach",
    "patient_experience", "staff_issue", "facility_issue", "referral_issue", "other",
]
Status = Literal["open", "in_progress", "resolved", "discarded"]
Origin = Literal["customer", "branch", "internal"]
Branch = Literal[
    "central", "austin_north", "dallas_uptown", "houston_med_center", "san_antonio_west",
    "miami_brickell", "miami_doral", "orlando_east", "tampa_bay", "atlanta_midtown",
    "savannah", "london_city", "london_west", "manchester_central",
]

DESCRIPTION = (
    "Create, update the status of, or look up the status of an incident ticket in the "
    "HealthCore Incidents Manager. Requires a valid OAuth access token.\n"
    "- action='create': send title, description, category, origin and branch. "
    "NEVER put patient-identifying data in title/description (use opaque IDs only).\n"
    "- action='update': send ONLY ticket_id and the target status. The Incidents Manager "
    "validates the lifecycle (open -> in_progress -> resolved / discarded); an invalid "
    "transition is rejected with VALIDATION_ERROR.\n"
    "- action='get_status': send ticket_id (integer) to read the ticket's current status.\n"
    "Scopes: 'incidents:write' for create/update, 'incidents:read' for get_status. "
    "Errors carry a documented error_code (VALIDATION_ERROR, TICKET_NOT_FOUND, "
    "AUTH_INSUFFICIENT_SCOPE, UPSTREAM_TIMEOUT, UPSTREAM_ERROR)."
)


class IncidentTicket(BaseModel):
    """Status-level view of a ticket. The free-text description is never returned."""

    ticket_id: int
    title: str
    status: Status
    category: str
    origin: str
    branch: str
    created_at: str
    updated_at: str


def _fail(code: ErrorCode, message: str | None = None, field: str | None = None) -> ToolFailure:
    return ToolFailure(code, tool=TOOL_NAME, message=message, field=field)


def _require(name: str, value: Any, action: str) -> None:
    if value is None or (isinstance(value, str) and not value.strip()):
        raise _fail(ErrorCode.VALIDATION_ERROR, f"'{name}' is required for action='{action}'.", name)


def _reject_extra(action: str, extras: dict[str, Any]) -> None:
    sent = [name for name, value in extras.items() if value is not None]
    if sent:
        raise _fail(
            ErrorCode.VALIDATION_ERROR,
            f"action='{action}' does not accept: {', '.join(sent)}.",
            sent[0],
        )


def _to_ticket(body: dict[str, Any]) -> IncidentTicket:
    return IncidentTicket(
        ticket_id=body["id"],
        title=body["title"],
        status=body["status"],
        category=body["category"],
        origin=body["origin"],
        branch=body["branch"],
        created_at=body["created_at"],
        updated_at=body["updated_at"],
    )


def _error_from_response(response: httpx.Response) -> ToolFailure:
    """Translate an Incidents Manager error into a documented error code."""
    status = response.status_code
    if status == 404:
        return _fail(ErrorCode.TICKET_NOT_FOUND)
    if status in (400, 422):
        field, message = None, None
        try:
            detail = response.json().get("detail")
        except ValueError:
            detail = None
        if isinstance(detail, dict):  # {"field": ..., "message": ...} (project's 400 shape)
            field, message = detail.get("field"), detail.get("message")
        elif isinstance(detail, list) and detail:  # FastAPI's default 422 list
            first = detail[0]
            field = str(first.get("loc", ["?"])[-1])
            message = first.get("msg")
        return _fail(ErrorCode.VALIDATION_ERROR, message, field)
    return _fail(ErrorCode.UPSTREAM_ERROR, f"Incidents Manager returned HTTP {status}.")


async def manage_incident_ticket(
    settings: Settings,
    action: Action,
    ticket_id: int | None = None,
    status: Status | None = None,
    title: str | None = None,
    description: str | None = None,
    category: Category | None = None,
    origin: Origin | None = None,
    branch: Branch | None = None,
) -> IncidentTicket:
    if action == "create":
        require_scope(SCOPE_INCIDENTS_WRITE, TOOL_NAME)
        for name, value in (("title", title), ("description", description),
                            ("category", category), ("origin", origin), ("branch", branch)):
            _require(name, value, action)
        _reject_extra(action, {"ticket_id": ticket_id, "status": status})
        request = ("POST", "/api/incidents", {
            "title": title, "description": description,
            "category": category, "origin": origin, "branch": branch,
        })
    elif action == "update":
        require_scope(SCOPE_INCIDENTS_WRITE, TOOL_NAME)
        _require("ticket_id", ticket_id, action)
        _require("status", status, action)
        _reject_extra(action, {"title": title, "description": description,
                               "category": category, "origin": origin, "branch": branch})
        request = ("PATCH", f"/api/incidents/{ticket_id}/status", {"status": status})
    else:  # get_status
        require_scope(SCOPE_INCIDENTS_READ, TOOL_NAME)
        _require("ticket_id", ticket_id, action)
        _reject_extra(action, {"status": status, "title": title, "description": description,
                               "category": category, "origin": origin, "branch": branch})
        request = ("GET", f"/api/incidents/{ticket_id}", None)

    method, path, payload = request
    try:
        async with http_client.build_client(settings.incident_api_base_url, settings) as client:
            response = await client.request(method, path, json=payload)
    except httpx.TimeoutException:
        raise _fail(
            ErrorCode.UPSTREAM_TIMEOUT,
            f"Incidents Manager did not answer within {settings.request_timeout_seconds}s.",
        )
    except httpx.RequestError as exc:
        raise _fail(
            ErrorCode.UPSTREAM_ERROR,
            f"Incidents Manager is unreachable ({type(exc).__name__}).",
        )

    if response.is_error:
        raise _error_from_response(response)
    try:
        return _to_ticket(response.json())
    except (ValueError, KeyError, TypeError):
        raise _fail(ErrorCode.UPSTREAM_ERROR, "Incidents Manager returned an unexpected body.")


# ---------------------------------------------------------------------------------------
# list_incident_tickets: read-only listing (keeps the agent's "how many open tickets?" path)
# ---------------------------------------------------------------------------------------
LIST_TOOL_NAME = "list_incident_tickets"
LIST_MAX_RESULTS = 20

LIST_DESCRIPTION = (
    "Read-only list of incident tickets in the HealthCore Incidents Manager, optionally "
    "filtered by status. Returns the total count and up to 20 ticket summaries "
    "(id, title, status). Use manage_incident_ticket with action='get_status' for one "
    "ticket's full status. Requires the 'incidents:read' scope."
)


class TicketSummary(BaseModel):
    ticket_id: int
    title: str
    status: Status


class IncidentList(BaseModel):
    count: int
    tickets: list[TicketSummary]


async def list_incident_tickets(settings: Settings, status: Status | None = None) -> IncidentList:
    require_scope(SCOPE_INCIDENTS_READ, LIST_TOOL_NAME)
    params = {"status": status} if status else {}
    try:
        async with http_client.build_client(settings.incident_api_base_url, settings) as client:
            response = await client.get("/api/incidents", params=params)
    except httpx.TimeoutException:
        raise ToolFailure(
            ErrorCode.UPSTREAM_TIMEOUT, tool=LIST_TOOL_NAME,
            message=f"Incidents Manager did not answer within {settings.request_timeout_seconds}s.",
        )
    except httpx.RequestError as exc:
        raise ToolFailure(
            ErrorCode.UPSTREAM_ERROR, tool=LIST_TOOL_NAME,
            message=f"Incidents Manager is unreachable ({type(exc).__name__}).",
        )
    if response.is_error:
        failure = _error_from_response(response)
        raise ToolFailure(failure.code, tool=LIST_TOOL_NAME, message=failure.payload.get("message"),
                          field=failure.payload.get("field"))
    try:
        body = response.json()
        tickets = [
            TicketSummary(ticket_id=i["id"], title=i["title"], status=i["status"]) for i in body
        ]
    except (ValueError, KeyError, TypeError):
        raise ToolFailure(ErrorCode.UPSTREAM_ERROR, tool=LIST_TOOL_NAME,
                          message="Incidents Manager returned an unexpected body.")
    return IncidentList(count=len(tickets), tickets=tickets[:LIST_MAX_RESULTS])
