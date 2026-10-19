"""Single place where HTTP clients to the company services are created.

Every request has an explicit timeout. Tests can inject a transport with
`set_transport_override` so no real network is needed.
"""

from __future__ import annotations

import httpx

from config import Settings

_transport_override: httpx.AsyncBaseTransport | None = None


def set_transport_override(transport: httpx.AsyncBaseTransport | None) -> None:
    global _transport_override
    _transport_override = transport


def build_client(base_url: str, settings: Settings) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        base_url=base_url,
        timeout=settings.request_timeout_seconds,
        transport=_transport_override,
    )
