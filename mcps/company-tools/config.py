"""Runtime configuration, read from environment variables (same pattern as services/api)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from urllib.parse import urlparse


def _split_scopes(raw: str | None) -> list[str]:
    return [s for s in (raw or "").replace(",", " ").split() if s]


@dataclass(frozen=True)
class Settings:
    # --- the live services this MCP server wraps (never mocked data) ---
    incident_api_base_url: str
    inventory_api_base_url: str
    request_timeout_seconds: float
    service_email: str | None  # service account used to read the JWT-protected inventory API
    service_password: str | None

    # --- OAuth 2.1 / OIDC (validated with MCP Auth) ---
    oidc_issuer: str | None  # e.g. https://<tenant>.us.auth0.com/
    resource_url: str  # public URL of THIS MCP endpoint, e.g. https://<codespace>-8001.app.github.dev/mcp
    audience: str | None  # expected "aud" claim; defaults to resource_url
    enforce_scopes: bool  # per-tool least privilege (incidents:read / incidents:write / inventory:read)

    # --- server ---
    host: str
    port: int

    @property
    def resource_path(self) -> str:
        return urlparse(self.resource_url).path or "/"

    @property
    def expected_audience(self) -> str:
        return self.audience or self.resource_url


def load_settings() -> Settings:
    incident_base = os.getenv("INCIDENT_API_BASE_URL", "http://localhost:8000")
    port = int(os.getenv("MCP_PORT", "8001"))
    return Settings(
        incident_api_base_url=incident_base,
        inventory_api_base_url=os.getenv("INVENTORY_API_BASE_URL", incident_base),
        request_timeout_seconds=float(os.getenv("MCP_UPSTREAM_TIMEOUT_SECONDS", "4.0")),
        service_email=os.getenv("AGENT_SERVICE_EMAIL"),
        service_password=os.getenv("AGENT_SERVICE_PASSWORD"),
        oidc_issuer=os.getenv("OIDC_ISSUER"),
        resource_url=os.getenv("MCP_RESOURCE_URL", f"http://localhost:{port}/mcp"),
        audience=os.getenv("MCP_AUDIENCE"),
        enforce_scopes=os.getenv("MCP_ENFORCE_SCOPES", "true").lower() != "false",
        host=os.getenv("MCP_HOST", "0.0.0.0"),
        port=port,
    )


# Scopes each tool needs (least privilege). Documented in the tool descriptions too.
SCOPE_INCIDENTS_READ = "incidents:read"
SCOPE_INCIDENTS_WRITE = "incidents:write"
SCOPE_INVENTORY_READ = "inventory:read"
ALL_SCOPES = [SCOPE_INCIDENTS_READ, SCOPE_INCIDENTS_WRITE, SCOPE_INVENTORY_READ]
