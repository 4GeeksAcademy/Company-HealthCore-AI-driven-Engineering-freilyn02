"""GET /events/stream through the real FastAPI app: content, auth and Last-Event-ID recovery.

The route is called over raw ASGI (no network, no database, no AI model): the stream never ends
on its own, so the helper reads it incrementally and then sends `http.disconnect`, exactly like a
browser closing the tab. The bus is a fresh in-memory EventBus per test.

NOTE ON THE BRIEFING: company-BRIEFING.md is not in the repository, so REQUIRED_FIELDS and
INITIAL_STATUS below mirror the existing RfpTicket model and the payload built by
routers.rfp._ticket_created_payload. When the BRIEFING is available, confirm (or change) these
two constants - they are the single place the tests take the contract from.
"""

from __future__ import annotations

import asyncio
import json
import os
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI

# app.core.security refuses to import without a signing key; this throwaway value is test-only.
os.environ.setdefault("SECRET_KEY", "test-only-secret-key-not-used-anywhere-else")

from events import sse  # noqa: E402
from events.bus import EventBus  # noqa: E402

EVENT_NAME = "rfp_ticket_created"
REQUIRED_FIELDS = {"id", "status", "original_filename", "created_at"}
INITIAL_STATUS = "analyzing"

# Generous on purpose: these are failure deadlines, not delays. A passing test never waits for them.
CONNECT_TIMEOUT = 15.0  # request -> ": connected" (first request through a fresh app)
LIVE_TIMEOUT = 5.0  # ": connected" -> the event / replay / close the test is waiting for


# --- helpers ---------------------------------------------------------------


@dataclass
class StreamResult:
    status: int | None = None
    headers: dict[str, str] = field(default_factory=dict)
    body: str = ""
    finished_on_its_own: bool = False


async def call_stream(
    app: FastAPI,
    headers: dict[str, str] | None = None,
    *,
    until: Callable[[str], bool] | None = None,
    after_connected: Callable[[], None] | None = None,
    settle: float = 0.0,
    timeout: float = LIVE_TIMEOUT,
    connect_timeout: float = CONNECT_TIMEOUT,
) -> StreamResult:
    """GET /events/stream over ASGI and return what the server sent.

    Reads until `until(body)` is true (or the response ends by itself, e.g. a 401), waits `settle`
    seconds to catch anything unexpected that follows, then disconnects like a closed browser tab.
    `after_connected` runs once, as soon as the ": connected" comment arrived.

    Two separate clocks, so a slow start can never be mistaken for a slow stream:
    - `connect_timeout`: from the request until ": connected" arrives (first-request overhead);
    - `timeout`: the wait for what the test expects (live events, replay, close). It starts only
      after ": connected" arrived AND `after_connected` returned, so time spent inside the hook
      (it blocks the event loop while it runs) is never charged to the stream.
    A response that ends by itself (401) needs no ": connected" and stops the loop at once.
    """
    scope = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": "/events/stream",
        "raw_path": b"/events/stream",
        "query_string": b"",
        "root_path": "",
        "headers": [(k.lower().encode(), v.encode()) for k, v in (headers or {}).items()],
        "client": ("testclient", 50000),
        "server": ("testserver", 80),
    }
    disconnect = asyncio.Event()
    inbox: asyncio.Queue = asyncio.Queue()

    async def receive():
        await disconnect.wait()
        return {"type": "http.disconnect"}

    async def send(message):
        await inbox.put(message)

    result = StreamResult()

    def absorb(message) -> None:
        if message["type"] == "http.response.start":
            result.status = message["status"]
            result.headers = {k.decode().lower(): v.decode() for k, v in message["headers"]}
        elif message["type"] == "http.response.body":
            result.body += message.get("body", b"").decode()

    task = asyncio.create_task(app(scope, receive, send))
    connected = False
    loop = asyncio.get_running_loop()
    deadline = loop.time() + connect_timeout
    try:
        while True:
            try:
                absorb(await asyncio.wait_for(inbox.get(), timeout=0.02))
            except asyncio.TimeoutError:
                if task.done() and inbox.empty():
                    result.finished_on_its_own = True
                    break
            if not connected and ": connected" in result.body:
                connected = True
                if after_connected is not None:
                    after_connected()
                deadline = loop.time() + timeout  # the live-event clock starts here
            if until is not None and until(result.body):
                break
            if loop.time() > deadline:
                phase = f"live events ({timeout}s)" if connected else f"connect ({connect_timeout}s)"
                pytest.fail(f"stream did not reach the expected state, timed out in {phase}; got: {result.body!r}")
        if not result.finished_on_its_own:
            if settle:
                await asyncio.sleep(settle)
            disconnect.set()
            await asyncio.wait_for(task, timeout=timeout)
        while not inbox.empty():
            absorb(inbox.get_nowait())
    finally:
        disconnect.set()
        if not task.done():
            task.cancel()
    return result


def parse_frames(body: str) -> list[dict[str, str]]:
    """Splits an SSE body into frames {id, event, data}; comment lines (": ...") are skipped."""
    frames = []
    for block in body.split("\n\n"):
        fields: dict[str, str] = {}
        for line in block.split("\n"):
            if not line or line.startswith(":"):
                continue
            name, _, value = line.partition(":")
            fields[name] = value.removeprefix(" ")
        if fields:
            frames.append(fields)
    return frames


def event_ids(body: str) -> list[int]:
    return [int(frame["id"]) for frame in parse_frames(body)]


def ticket_ids(body: str) -> list[int]:
    return [json.loads(frame["data"])["id"] for frame in parse_frames(body)]


def has_event_id(n: int) -> Callable[[str], bool]:
    return lambda body: n in event_ids(body)


def created_payload(ticket_id: int) -> dict:
    """The payload the upload route really publishes (routers.rfp._ticket_created_payload)."""
    from data.pipelines.rfp_intake.models import RfpTicket
    from routers.rfp import _ticket_created_payload

    ticket = RfpTicket(
        id=ticket_id,
        original_filename=f"clinic-{ticket_id}.pdf",
        raw_pdf_path="/never/sent/to/clients.pdf",
        created_at=datetime(2026, 10, 19, 12, 0, tzinfo=timezone.utc),
    )
    return _ticket_created_payload(ticket)


# --- fixtures --------------------------------------------------------------


@pytest.fixture(scope="module", autouse=True)
def warm_up_heavy_imports() -> None:
    """Pay the one-time import cost (routers.rfp pulls in the database layer and the pipelines
    package: ~1.5 s warm, ~7 s without a bytecode cache) before any test starts its clock.
    Without this, whichever test calls created_payload() first blocks the event loop for that
    long inside its own stream, and fails when it runs first."""
    created_payload(0)


@pytest.fixture
def bus(monkeypatch) -> EventBus:
    fresh = EventBus()
    monkeypatch.setattr(sse, "event_bus", fresh)
    monkeypatch.setattr(sse, "POLL_SECONDS", 0.01)
    return fresh


@pytest.fixture
def app(bus) -> FastAPI:
    application = FastAPI()
    application.include_router(sse.router)
    return application


@pytest.fixture
def auth_headers(monkeypatch) -> dict[str, str]:
    """A real signed JWT; only the user lookup (a TinyDB read) is replaced."""
    from app.core.security import create_access_token

    monkeypatch.setattr("app.core.deps.get_user", lambda user_id: {"id": user_id, "email": "ana@healthcore.test"})
    return {"Authorization": f"Bearer {create_access_token({'sub': '1'})}"}


# --- 1. content ------------------------------------------------------------


def test_stream_serves_a_named_rfp_ticket_created_event_with_the_required_fields(app, bus, auth_headers):
    async def scenario():
        return await call_stream(
            app,
            auth_headers,
            after_connected=lambda: bus.publish(EVENT_NAME, created_payload(4)),
            until=lambda body: "event: rfp_ticket_created" in body,
        )

    result = asyncio.run(scenario())

    assert result.status == 200
    assert "text/event-stream" in result.headers["content-type"]

    lines = result.body.split("\n")
    assert ": connected" in lines
    assert "event: rfp_ticket_created" in lines
    assert "event: message" not in lines  # a named event, never the generic one
    data_lines = [line for line in lines if line.startswith("data: ")]
    assert len(data_lines) == 1

    data = json.loads(data_lines[0].removeprefix("data: "))
    assert REQUIRED_FIELDS <= data.keys()
    assert data["status"] == INITIAL_STATUS
    assert data["id"] == 4 and isinstance(data["id"], int)
    assert data["original_filename"] == "clinic-4.pdf"
    assert datetime.fromisoformat(data["created_at"]) == datetime(2026, 10, 19, 12, 0, tzinfo=timezone.utc)
    assert "raw_pdf_path" not in data  # internal path never leaves the server

    [frame] = parse_frames(result.body)
    assert frame["id"].isdigit()
    assert frame["event"] == EVENT_NAME


def test_stream_response_headers_disable_caching_and_proxy_buffering(app, auth_headers):
    result = asyncio.run(call_stream(app, auth_headers, until=lambda body: ": connected" in body))

    assert result.headers["cache-control"] == "no-cache"
    assert result.headers["x-accel-buffering"] == "no"
    assert result.headers["connection"] == "keep-alive"


# --- 2. auth ---------------------------------------------------------------


def _signed(claims: dict, key: str | None = None) -> str:
    from jose import jwt

    from app.core.security import ALGORITHM, SECRET_KEY

    return jwt.encode(claims, key or SECRET_KEY, algorithm=ALGORITHM)


def _expired_token() -> str:
    return _signed({"sub": "1", "exp": datetime.now(timezone.utc) - timedelta(minutes=5)})


def _foreign_key_token() -> str:
    return _signed({"sub": "1", "exp": datetime.now(timezone.utc) + timedelta(minutes=5)}, key="some-other-key")


def test_request_without_a_jwt_is_rejected(app, bus):
    result = asyncio.run(call_stream(app))

    assert result.status == 401
    assert result.finished_on_its_own
    assert "text/event-stream" not in result.headers.get("content-type", "")
    assert "event:" not in result.body
    assert bus.subscriber_count == 0  # an unauthenticated client never gets subscribed


@pytest.mark.parametrize(
    "authorization",
    [
        "Bearer not-a-jwt",
        "Basic dXNlcjpwYXNz",
        "Bearer ",
    ],
)
def test_request_with_a_malformed_authorization_header_is_rejected(app, bus, authorization):
    result = asyncio.run(call_stream(app, {"Authorization": authorization}))

    assert result.status == 401
    assert bus.subscriber_count == 0


@pytest.mark.parametrize("make_token", [_expired_token, _foreign_key_token], ids=["expired", "wrong-signing-key"])
def test_request_with_an_expired_or_forged_jwt_is_rejected(app, bus, monkeypatch, make_token):
    monkeypatch.setattr("app.core.deps.get_user", lambda user_id: {"id": user_id})

    result = asyncio.run(call_stream(app, {"Authorization": f"Bearer {make_token()}"}))

    assert result.status == 401
    assert bus.subscriber_count == 0


def test_valid_jwt_for_a_user_that_no_longer_exists_is_rejected(app, bus, auth_headers, monkeypatch):
    monkeypatch.setattr("app.core.deps.get_user", lambda user_id: None)

    result = asyncio.run(call_stream(app, auth_headers))

    assert result.status == 401
    assert bus.subscriber_count == 0


def test_request_with_a_valid_jwt_is_accepted_and_cleaned_up_on_disconnect(app, bus, auth_headers):
    async def scenario():
        result = await call_stream(app, auth_headers, until=lambda body: ": connected" in body)
        return result, bus.subscriber_count

    result, subscribers_after = asyncio.run(scenario())

    assert result.status == 200
    assert result.body.startswith(": connected\n\n")
    assert subscribers_after == 0  # the closed connection was unsubscribed


# --- 3. recovery (Last-Event-ID) -------------------------------------------


def _publish_tickets(bus: EventBus, ticket_ids: range) -> None:
    for ticket_id in ticket_ids:
        bus.publish(EVENT_NAME, created_payload(ticket_id))


def test_reconnect_with_last_event_id_replays_only_newer_events(app, bus, auth_headers):
    _publish_tickets(bus, range(101, 106))  # event ids 1..5

    result = asyncio.run(
        call_stream(app, {**auth_headers, "Last-Event-ID": "3"}, until=has_event_id(5), settle=0.1)
    )

    assert event_ids(result.body) == [4, 5]
    assert ticket_ids(result.body) == [104, 105]


def test_replay_is_followed_by_live_events_without_duplicates(app, bus, auth_headers):
    _publish_tickets(bus, range(101, 106))

    async def scenario():
        return await call_stream(
            app,
            {**auth_headers, "Last-Event-ID": "3"},
            after_connected=lambda: bus.publish(EVENT_NAME, created_payload(106)),
            until=has_event_id(6),
            settle=0.1,
        )

    result = asyncio.run(scenario())

    ids = event_ids(result.body)
    assert ids == [4, 5, 6]
    assert len(ids) == len(set(ids))
    assert ticket_ids(result.body) == [104, 105, 106]


def test_client_that_went_offline_recovers_exactly_what_it_missed(app, bus, auth_headers):
    """First connection sees 1-3, two tickets arrive while offline, the reconnect brings 4-5 only."""

    async def scenario():
        first = await call_stream(
            app,
            auth_headers,
            after_connected=lambda: _publish_tickets(bus, range(101, 104)),
            until=has_event_id(3),
        )
        last_seen = str(event_ids(first.body)[-1])  # what the client keeps as lastEventId

        _publish_tickets(bus, range(104, 106))  # published while nobody is connected

        second = await call_stream(
            app,
            {**auth_headers, "Last-Event-ID": last_seen},
            until=has_event_id(5),
            settle=0.1,
        )
        return first, second

    first, second = asyncio.run(scenario())

    assert event_ids(first.body) == [1, 2, 3]
    assert event_ids(second.body) == [4, 5]
    every_ticket = ticket_ids(first.body) + ticket_ids(second.body)
    assert every_ticket == [101, 102, 103, 104, 105]  # nothing lost, nothing twice


@pytest.mark.parametrize(
    "last_event_id",
    [None, "999", "abc", ""],
    ids=["first-connection", "ahead-of-the-server", "not-a-number", "empty"],
)
def test_no_replay_without_a_usable_last_event_id(app, bus, auth_headers, last_event_id):
    _publish_tickets(bus, range(101, 104))
    headers = dict(auth_headers)
    if last_event_id is not None:
        headers["Last-Event-ID"] = last_event_id

    result = asyncio.run(call_stream(app, headers, until=lambda body: ": connected" in body, settle=0.1))

    assert result.status == 200
    assert parse_frames(result.body) == []  # only the ": connected" comment, no old events
