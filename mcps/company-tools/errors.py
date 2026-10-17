"""Error catalogue for the HealthCore company-tools MCP server.

Every failure a client can see has its own documented code, so an agent (or a human
reading a log) can tell an authentication problem from an authorization problem from a
validation problem without parsing free text.

Tool failures are raised as `ToolFailure`, a FastMCP `ToolError` whose message is a JSON
document: {"error_code": ..., "message": ..., "tool": ..., "field": ...}.
HTTP-level auth failures are rewritten to the same JSON shape by `auth.py`.
"""

from __future__ import annotations

import json
from enum import Enum
from typing import Any

from fastmcp.exceptions import ToolError


class ErrorCode(str, Enum):
    # --- authentication / authorization (HTTP layer, before any tool runs) ---
    AUTH_MISSING_TOKEN = "AUTH_MISSING_TOKEN"
    AUTH_INVALID_TOKEN = "AUTH_INVALID_TOKEN"
    AUTH_INSUFFICIENT_SCOPE = "AUTH_INSUFFICIENT_SCOPE"
    # --- business rules ---
    INVENTORY_WRITE_FORBIDDEN = "INVENTORY_WRITE_FORBIDDEN"
    VALIDATION_ERROR = "VALIDATION_ERROR"
    TICKET_NOT_FOUND = "TICKET_NOT_FOUND"
    # --- downstream services ---
    UPSTREAM_TIMEOUT = "UPSTREAM_TIMEOUT"
    UPSTREAM_ERROR = "UPSTREAM_ERROR"


# Documented, human-readable message for each code (never a generic "error").
DEFAULT_MESSAGES: dict[ErrorCode, str] = {
    ErrorCode.AUTH_MISSING_TOKEN: (
        "No OAuth access token was sent. Send 'Authorization: Bearer <access_token>'."
    ),
    ErrorCode.AUTH_INVALID_TOKEN: (
        "The OAuth access token is invalid, expired, or was issued for another audience."
    ),
    ErrorCode.AUTH_INSUFFICIENT_SCOPE: (
        "The access token is valid but does not include the scope this tool requires."
    ),
    ErrorCode.INVENTORY_WRITE_FORBIDDEN: (
        "Inventory tool is read-only. Write operations are not permitted on this MCP server."
    ),
    ErrorCode.VALIDATION_ERROR: "The tool input is not valid.",
    ErrorCode.TICKET_NOT_FOUND: "No incident ticket exists with that ticket_id.",
    ErrorCode.UPSTREAM_TIMEOUT: "The company service did not answer in time.",
    ErrorCode.UPSTREAM_ERROR: "The company service returned an unexpected error.",
}

# What each code maps to over HTTP (informational: tool errors travel inside MCP).
HTTP_EQUIVALENT: dict[ErrorCode, int] = {
    ErrorCode.AUTH_MISSING_TOKEN: 401,
    ErrorCode.AUTH_INVALID_TOKEN: 401,
    ErrorCode.AUTH_INSUFFICIENT_SCOPE: 403,
    ErrorCode.INVENTORY_WRITE_FORBIDDEN: 403,
    ErrorCode.VALIDATION_ERROR: 400,
    ErrorCode.TICKET_NOT_FOUND: 404,
    ErrorCode.UPSTREAM_TIMEOUT: 504,
    ErrorCode.UPSTREAM_ERROR: 502,
}


def error_payload(
    code: ErrorCode,
    *,
    tool: str | None = None,
    message: str | None = None,
    field: str | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "error_code": code.value,
        "message": message or DEFAULT_MESSAGES[code],
    }
    if tool:
        payload["tool"] = tool
    if field:
        payload["field"] = field
    return payload


class ToolFailure(ToolError):
    """A tool failure carrying a structured, documented error code."""

    def __init__(
        self,
        code: ErrorCode,
        *,
        tool: str | None = None,
        message: str | None = None,
        field: str | None = None,
    ) -> None:
        self.code = code
        self.payload = error_payload(code, tool=tool, message=message, field=field)
        super().__init__(json.dumps(self.payload))
