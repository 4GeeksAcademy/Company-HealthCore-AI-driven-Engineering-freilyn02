"""OAuth 2.1 / OIDC protection for the MCP server, using MCP Auth (`mcpauth`).

NOT FastMCP's built-in auth: MCP Auth runs as a *resource server*:
  1. `fetch_server_config` discovers the issuer's metadata (JWKS, endpoints).
  2. `MCPAuth(protected_resources=...)` publishes Protected Resource Metadata at
     /.well-known/oauth-protected-resource/... so clients discover where to log in.
  3. `bearer_auth_middleware("jwt", ...)` validates the JWT (signature, issuer, audience)
     on EVERY request to the MCP endpoint: no token => no tool list and no tool call.

`AuthErrorCodeMiddleware` rewrites MCP Auth's 401/403 bodies into this project's documented
error codes (AUTH_MISSING_TOKEN / AUTH_INVALID_TOKEN / AUTH_INSUFFICIENT_SCOPE) while
keeping the WWW-Authenticate header MCP Auth sets (clients need it to start the OAuth flow).
"""

from __future__ import annotations

import json
from typing import Any

import jwt  # PyJWT, installed as a dependency of mcpauth
from fastmcp.server.dependencies import get_http_headers
from mcpauth import MCPAuth
from mcpauth.config import AuthServerType
from mcpauth.types import AuthInfo, ResourceServerConfig, ResourceServerMetadata
from mcpauth.utils import fetch_server_config

from config import ALL_SCOPES, Settings
from errors import ErrorCode, ToolFailure, error_payload

# MCP Auth `error` values that mean "the client did not send a usable Bearer token at all".
_MISSING_TOKEN_ERRORS = {
    "missing_auth_header",
    "invalid_auth_header_format",
    "missing_bearer_token",
}

_mcp_auth: MCPAuth | None = None
_enforce_scopes = True


def build_mcp_auth(settings: Settings, auth_server_config: Any | None = None) -> MCPAuth:
    """Create the MCP Auth resource-server object.

    `auth_server_config` is only injected by tests; in production it is discovered from
    OIDC_ISSUER (this makes one HTTPS call to the issuer at startup).
    """
    global _mcp_auth, _enforce_scopes

    if auth_server_config is None:
        if not settings.oidc_issuer:
            # Secure by default: there is deliberately NO "run without auth" mode.
            raise RuntimeError(
                "OIDC_ISSUER is not set. The MCP server refuses to start without OAuth "
                "configured (see mcps/company-tools/README.md)."
            )
        auth_server_config = fetch_server_config(
            settings.oidc_issuer, AuthServerType.OIDC
        )

    _mcp_auth = MCPAuth(
        protected_resources=ResourceServerConfig(
            metadata=ResourceServerMetadata(
                resource=settings.resource_url,
                authorization_servers=[auth_server_config],
                scopes_supported=ALL_SCOPES,
                resource_name="HealthCore company tools",
            )
        )
    )
    _enforce_scopes = settings.enforce_scopes
    return _mcp_auth


# --------------------------------------------------------------------------------------
# Who is calling? (used by tool-level scope checks and by the invocation log)
# --------------------------------------------------------------------------------------
def _claims_from_request_header() -> dict[str, Any]:
    """Fallback when MCP Auth's context variable is not visible inside the tool task.

    Safe because a request only reaches a tool after the bearer middleware has already
    verified this very token (signature, issuer, audience, expiry)."""
    header = get_http_headers().get("authorization", "")
    if not header.lower().startswith("bearer "):
        return {}
    try:
        return jwt.decode(
            header.split(" ", 1)[1], options={"verify_signature": False}
        )
    except jwt.PyJWTError:
        return {}


def current_client_id() -> str:
    info: AuthInfo | None = _mcp_auth.auth_info if _mcp_auth else None
    if info and info.client_id:
        return info.client_id
    claims = _claims_from_request_header()
    return str(claims.get("azp") or claims.get("client_id") or claims.get("sub") or "unknown")


def _current_scopes() -> set[str]:
    info: AuthInfo | None = _mcp_auth.auth_info if _mcp_auth else None
    if info is not None:
        return set(info.scopes or [])
    claims = _claims_from_request_header()
    raw = claims.get("scope", claims.get("scp", ""))
    return set(raw.split() if isinstance(raw, str) else raw)


def require_scope(scope: str, tool: str) -> None:
    """Least privilege: each tool action declares the one scope it needs."""
    if not _enforce_scopes:
        return
    if scope not in _current_scopes():
        raise ToolFailure(
            ErrorCode.AUTH_INSUFFICIENT_SCOPE,
            tool=tool,
            message=f"This action requires the '{scope}' scope, which the access token does not include.",
        )


# --------------------------------------------------------------------------------------
# HTTP-level error codes
# --------------------------------------------------------------------------------------
class AuthErrorCodeMiddleware:
    """Pure-ASGI middleware (does not break streaming) placed OUTSIDE the bearer middleware.

    It only touches 401/403 responses produced by MCP Auth and swaps the body for
    {"error_code", "message"}, keeping every other header (notably WWW-Authenticate).
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        held_start: dict | None = None
        body = bytearray()

        async def rewriting_send(message):
            nonlocal held_start
            if message["type"] == "http.response.start" and message["status"] in (401, 403):
                held_start = message  # hold until the (small) body is complete
                return
            if held_start is not None and message["type"] == "http.response.body":
                body.extend(message.get("body", b""))
                if message.get("more_body", False):
                    return
                await self._send_rewritten(send, held_start, bytes(body))
                return
            await send(message)

        await self.app(scope, receive, rewriting_send)

    @staticmethod
    async def _send_rewritten(send, start: dict, original_body: bytes) -> None:
        status = start["status"]
        try:
            original_error = json.loads(original_body or b"{}").get("error", "")
        except ValueError:
            original_error = ""

        if status == 403:
            code = ErrorCode.AUTH_INSUFFICIENT_SCOPE
        elif original_error in _MISSING_TOKEN_ERRORS:
            code = ErrorCode.AUTH_MISSING_TOKEN
        else:
            code = ErrorCode.AUTH_INVALID_TOKEN

        payload = json.dumps(error_payload(code)).encode()
        headers = [
            (k, v)
            for k, v in start.get("headers", [])
            if k.lower() not in (b"content-length", b"content-type")
        ]
        headers.append((b"content-type", b"application/json"))
        headers.append((b"content-length", str(len(payload)).encode()))
        await send({"type": "http.response.start", "status": status, "headers": headers})
        await send({"type": "http.response.body", "body": payload})
