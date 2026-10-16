# HealthCore company-tools MCP server

FastMCP server that exposes the company's incident manager and inventory to agents, protected
by OAuth (MCP Auth). The LangGraph support agent (`services/api/agent`) consumes it through
`langchain-mcp-adapters`.

## Tools

| Tool | What it does | Scope |
|---|---|---|
| `manage_incident_ticket` | `create` (POST /api/incidents), `update` status (PATCH /api/incidents/{id}/status), `get_status` (GET /api/incidents/{id}) | `incidents:write` (create/update), `incidents:read` (get_status) |
| `list_incident_tickets` | Read-only list, optional status filter | `incidents:read` |
| `query_inventory` | Read-only stock lookup. Any write attempt is refused with `INVENTORY_WRITE_FORBIDDEN` before any HTTP call | `inventory:read` |

Tool descriptions and per-parameter descriptions are part of the discovery response
(`tools/list`), so a client can use the tools without reading this file.

## Transport decision: Streamable HTTP

- The server must be reachable by remote clients (MCP Playground via a public Codespaces
  URL, the agent over the network). stdio only works for a local child process.
- Streamable HTTP is the transport the MCP spec recommends for remote servers (SSE is
  deprecated) and the one OAuth bearer tokens are defined for: the token travels in the
  `Authorization` header of every request.
- `stateless_http=True`: no server-side session, so every request is authorised on its own
  and the server scales/restarts without losing anything.

## Authentication (MCP Auth, not FastMCP's built-in auth)

The server is an OAuth **resource server**. It does not issue tokens; it validates JWTs from
an external OIDC provider (`OIDC_ISSUER`): signature (JWKS), expiry, issuer and audience.

- `GET /.well-known/oauth-protected-resource/mcp` (public) tells clients which authorization
  server to use. Everything under `/mcp` requires `Authorization: Bearer <token>`: an
  unauthenticated client cannot list or call tools.
- Resource-server mode needs the MCP Auth **beta** (`mcpauth==0.2.0b1`); the stable 0.1.x only
  supports authorization-server mode.
- Least privilege: each tool checks its scope (`MCP_ENFORCE_SCOPES=false` disables this for
  providers that cannot add custom scopes -- not recommended).

## Error codes

| Code | HTTP-equivalent | When |
|---|---|---|
| `AUTH_MISSING_TOKEN` | 401 | No `Authorization: Bearer` header |
| `AUTH_INVALID_TOKEN` | 401 | Malformed, expired, bad signature, wrong issuer/audience |
| `AUTH_INSUFFICIENT_SCOPE` | 403 | Valid token without the scope the tool needs |
| `INVENTORY_WRITE_FORBIDDEN` | 403 | Any write attempt on `query_inventory` |
| `VALIDATION_ERROR` | 400 | Bad/missing/extra arguments, or the Incidents Manager rejected the change (e.g. invalid lifecycle transition). Includes `field` when known |
| `TICKET_NOT_FOUND` | 404 | Unknown `ticket_id` |
| `UPSTREAM_TIMEOUT` / `UPSTREAM_ERROR` | 504 / 502 | Company service slow or failing |

HTTP-level auth errors return `{"error_code", "message"}` with the `WWW-Authenticate` header
preserved; tool errors return the same JSON as the MCP error text.

## Logging

One JSON line per tool invocation on logger `company_tools.invocations`:

```json
{"timestamp": "...", "client_id": "agent-support", "tool": "manage_incident_ticket",
 "input_summary": {"action": "get_status", "ticket_id": 482}, "result": "success", "duration_ms": 41}
```

`input_summary` is an allow-list (action, ticket_id, status, product_id, query): titles and
descriptions can hold sensitive text and are never logged.

## Run

```bash
cp .env.example .env   # fill OIDC_ISSUER, MCP_RESOURCE_URL, service account
cd mcps/company-tools
uv run --project ../../services/api python server.py
```

Dependencies live in `services/api` (`uv add fastmcp "mcpauth==0.2.0b1" langchain-mcp-adapters`).
Keep `fastmcp>=3.4,<4`: fastmcp 4 needs `mcp` 2.x while `langchain-mcp-adapters` requires
`mcp<2`.

## Tests

```bash
cd mcps/company-tools && uv run --project ../../services/api pytest tests
```

They run the real server under uvicorn with a local fake OIDC issuer (discovery + JWKS +
RS256 tokens), so token validation is the real code path; only the company APIs are mocked.
