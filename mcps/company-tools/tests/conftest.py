"""Test harness: a REAL OAuth setup, with no mocks inside the MCP server itself.

  - a tiny fake OIDC issuer (discovery document + JWKS) on localhost, signing JWTs with a
    throwaway RSA key, so `fetch_server_config` and MCP Auth's real "jwt" mode run for real;
  - the MCP server running under uvicorn in a background thread;
  - the Incidents Manager / Inventory APIs replaced by an in-process httpx.MockTransport that
    follows the real API contract (status codes, 400 body shape, lifecycle rules).
"""

from __future__ import annotations

import json
import socket
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import httpx
import jwt
import pytest
import uvicorn
from jwt.algorithms import RSAAlgorithm

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import http_client  # noqa: E402
from config import Settings  # noqa: E402
from server import build_app  # noqa: E402


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


# --------------------------------------------------------------------------------------
# Fake OIDC issuer
# --------------------------------------------------------------------------------------
class FakeIssuer:
    def __init__(self) -> None:
        from cryptography.hazmat.primitives.asymmetric import rsa

        self.port = free_port()
        self.issuer = f"http://127.0.0.1:{self.port}"
        self._key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        jwk = json.loads(RSAAlgorithm.to_jwk(self._key.public_key()))
        jwk.update({"kid": "test-key", "use": "sig", "alg": "RS256"})
        self.jwks = {"keys": [jwk]}
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802
                if self.path == "/.well-known/openid-configuration":
                    body = {
                        "issuer": outer.issuer,
                        "authorization_endpoint": f"{outer.issuer}/authorize",
                        "token_endpoint": f"{outer.issuer}/token",
                        "jwks_uri": f"{outer.issuer}/jwks.json",
                        "response_types_supported": ["code"],
                        "subject_types_supported": ["public"],
                        "id_token_signing_alg_values_supported": ["RS256"],
                    }
                elif self.path == "/jwks.json":
                    body = outer.jwks
                else:
                    self.send_response(404)
                    self.end_headers()
                    return
                data = json.dumps(body).encode()
                self.send_response(200)
                self.send_header("content-type", "application/json")
                self.send_header("content-length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def log_message(self, *args):  # silence
                pass

        self._httpd = HTTPServer(("127.0.0.1", self.port), Handler)
        threading.Thread(target=self._httpd.serve_forever, daemon=True).start()

    def token(
        self,
        *,
        audience: str,
        scope: str = "incidents:read incidents:write inventory:read",
        client_id: str = "agent-support-test",
        expires_in: int = 3600,
        issuer: str | None = None,
    ) -> str:
        now = int(time.time())
        claims = {
            "iss": issuer or self.issuer,
            "aud": audience,
            "sub": "service-account",
            "azp": client_id,
            "client_id": client_id,
            "scope": scope,
            "iat": now,
            "exp": now + expires_in,
        }
        return jwt.encode(claims, self._key, algorithm="RS256", headers={"kid": "test-key"})

    def stop(self) -> None:
        self._httpd.shutdown()


# --------------------------------------------------------------------------------------
# Fake company APIs (follow the real contract of services/api)
# --------------------------------------------------------------------------------------
VALID_TRANSITIONS = {
    "open": {"in_progress", "resolved", "discarded"},
    "in_progress": {"resolved", "discarded"},
    "resolved": set(),
    "discarded": set(),
}
PRODUCTS = [
    {"id": 1, "name": "Nitrile Gloves M", "sku": "PPE-GLV-M", "category": "ppe",
     "unit": "box", "country": "US", "current_stock": 120},
    {"id": 2, "name": "Surgical Mask", "sku": "PPE-MSK-01", "category": "ppe",
     "unit": "box", "country": "UK", "current_stock": 15},
]


class FakeCompanyApis:
    def __init__(self) -> None:
        self.incidents: dict[int, dict] = {
            482: {
                "id": 482, "title": "MRI offline", "description": "SECRET-DETAILS",
                "category": "clinical_equipment", "status": "open", "origin": "branch",
                "branch": "central", "created_at": "2026-10-01T10:00:00+00:00",
                "updated_at": "2026-10-01T10:00:00+00:00",
            }
        }
        self.requests: list[tuple[str, str]] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        method, path = request.method, request.url.path
        self.requests.append((method, path))

        if method == "POST" and path == "/auth/login":
            return httpx.Response(200, json={"access_token": "inventory-jwt", "token_type": "bearer"})
        if path.startswith("/inventory/"):
            if request.headers.get("authorization") != "Bearer inventory-jwt":
                return httpx.Response(401, json={"detail": "Not authenticated"})
            if path == "/inventory/products":
                return httpx.Response(200, json=PRODUCTS)
            product_id = int(path.rsplit("/", 1)[1])
            match = [p for p in PRODUCTS if p["id"] == product_id]
            return httpx.Response(200, json=match[0]) if match else httpx.Response(404, json={"detail": "not found"})

        if method == "POST" and path == "/api/incidents":
            body = json.loads(request.content)
            new_id = max(self.incidents) + 1
            now = "2026-10-09T12:00:00+00:00"
            self.incidents[new_id] = {**body, "id": new_id, "status": "open",
                                      "created_at": now, "updated_at": now}
            return httpx.Response(201, json=self.incidents[new_id])

        if method == "GET" and path == "/api/incidents":
            wanted = request.url.params.get("status")
            return httpx.Response(200, json=[i for i in self.incidents.values()
                                             if not wanted or i["status"] == wanted])

        parts = path.strip("/").split("/")  # api / incidents / {id} [/ status]
        if len(parts) >= 3 and parts[:2] == ["api", "incidents"]:
            incident = self.incidents.get(int(parts[2]))
            if incident is None:
                return httpx.Response(404, json={"detail": "Incident not found"})
            if method == "GET" and len(parts) == 3:
                return httpx.Response(200, json=incident)
            if method == "PATCH" and parts[3:] == ["status"]:
                new_status = json.loads(request.content)["status"]
                if new_status not in VALID_TRANSITIONS[incident["status"]]:
                    return httpx.Response(400, json={"detail": {
                        "field": "status",
                        "message": f"Cannot move from {incident['status']} to {new_status}.",
                    }})
                incident["status"] = new_status
                return httpx.Response(200, json=incident)
        return httpx.Response(404, json={"detail": "unknown route"})


# --------------------------------------------------------------------------------------
# Fixtures
# --------------------------------------------------------------------------------------
@pytest.fixture(scope="session")
def issuer():
    fake = FakeIssuer()
    yield fake
    fake.stop()


@pytest.fixture(scope="session")
def apis():
    fake = FakeCompanyApis()
    http_client.set_transport_override(httpx.MockTransport(fake.handler))
    yield fake
    http_client.set_transport_override(None)


@pytest.fixture(scope="session")
def mcp_server(issuer, apis):
    port = free_port()
    settings = Settings(
        incident_api_base_url="http://incidents.test",
        inventory_api_base_url="http://inventory.test",
        request_timeout_seconds=2.0,
        service_email="agent@healthcore.test",
        service_password="not-a-real-password",
        oidc_issuer=issuer.issuer,
        resource_url=f"http://127.0.0.1:{port}/mcp",
        audience=None,
        enforce_scopes=True,
        host="127.0.0.1",
        port=port,
    )
    app = build_app(settings)  # real: issuer discovery + real JWT validation
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.time() + 15
    while not server.started and time.time() < deadline:
        time.sleep(0.05)
    assert server.started, "MCP server did not start"
    yield settings
    server.should_exit = True
    thread.join(timeout=5)
