"""Tests for the SSE event bus and GET /events/stream (services/api/events/).

No database, network or AI model is involved: the bus is in-process, the stream generator is
driven directly with a fake request, and the route is mounted alone.
"""

from __future__ import annotations

import asyncio
import json
import os

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

# app.core.security refuses to import without a signing key; this throwaway value is test-only.
os.environ.setdefault("SECRET_KEY", "test-only-secret-key-not-used-anywhere-else")

from events import sse  # noqa: E402
from events.bus import EventBus  # noqa: E402


class FakeRequest:
    """Reports 'connected' for `connected_checks` calls, then 'disconnected'."""

    def __init__(self, connected_checks: int) -> None:
        self._remaining = connected_checks

    async def is_disconnected(self) -> bool:
        if self._remaining <= 0:
            return True
        self._remaining -= 1
        return False


async def _collect(stream) -> list[str]:
    return [chunk async for chunk in stream]


# --- bus ------------------------------------------------------------------


def test_publish_fans_out_to_every_subscriber_with_incrementing_ids():
    async def scenario():
        bus = EventBus()
        first, _ = bus.subscribe()
        second, _ = bus.subscribe()

        a = bus.publish("rfp_ticket_created", {"id": 1})
        b = bus.publish("rfp_ticket_created", {"id": 2})

        assert (a.id, b.id) == (1, 2)
        for queue in (first, second):
            assert [queue.get_nowait().data["id"], queue.get_nowait().data["id"]] == [1, 2]

    asyncio.run(scenario())


def test_unsubscribe_is_idempotent_and_stops_delivery():
    async def scenario():
        bus = EventBus()
        queue, _ = bus.subscribe()
        bus.unsubscribe(queue)
        bus.unsubscribe(queue)
        bus.unsubscribe(asyncio.Queue())  # never subscribed

        bus.publish("rfp_ticket_created", {"id": 1})

        assert queue.empty()
        assert bus.subscriber_count == 0

    asyncio.run(scenario())


def test_replay_buffer_keeps_only_the_last_events():
    async def scenario():
        bus = EventBus(replay_size=3)
        for n in range(1, 6):
            bus.publish("rfp_ticket_created", {"id": n})

        _, backlog = bus.subscribe(last_event_id=0)

        assert [e.id for e in backlog] == [3, 4, 5]

    asyncio.run(scenario())


def test_first_connection_gets_no_replay_and_reconnection_gets_only_newer_events():
    async def scenario():
        bus = EventBus()
        for n in range(1, 5):
            bus.publish("rfp_ticket_created", {"id": n})

        _, fresh = bus.subscribe()
        _, resumed = bus.subscribe(last_event_id=2)

        assert fresh == []
        assert [e.id for e in resumed] == [3, 4]

    asyncio.run(scenario())


def test_slow_subscriber_loses_oldest_events_instead_of_blocking_publish(monkeypatch):
    async def scenario():
        monkeypatch.setattr("events.bus.SUBSCRIBER_QUEUE_SIZE", 2)
        bus = EventBus()
        queue, _ = bus.subscribe()

        for n in range(1, 5):
            bus.publish("rfp_ticket_created", {"id": n})

        assert [queue.get_nowait().id, queue.get_nowait().id] == [3, 4]

    asyncio.run(scenario())


def test_publish_from_a_worker_thread_reaches_the_subscriber():
    async def scenario():
        bus = EventBus()
        queue, _ = bus.subscribe()

        await asyncio.to_thread(bus.publish, "rfp_ticket_created", {"id": 7})

        event = await asyncio.wait_for(queue.get(), timeout=2)
        assert event.data == {"id": 7}

    asyncio.run(scenario())


# --- wire format ------------------------------------------------------------


def test_event_is_formatted_as_a_named_sse_event():
    bus = EventBus()
    event = bus.publish("rfp_ticket_created", {"id": 5, "status": "analyzing"})

    text = sse.format_event(event)

    assert text == 'id: 1\nevent: rfp_ticket_created\ndata: {"id": 5, "status": "analyzing"}\n\n'
    assert "event: message" not in text


@pytest.mark.parametrize("raw, expected", [(None, None), ("12", 12), (" 7 ", 7), ("abc", None), ("", None)])
def test_last_event_id_header_parsing(raw, expected):
    assert sse.parse_last_event_id(raw) == expected


# --- stream ----------------------------------------------------------------


def test_stream_opens_with_connected_then_delivers_live_events_and_unsubscribes(monkeypatch):
    monkeypatch.setattr(sse, "POLL_SECONDS", 0.01)

    async def scenario():
        bus = EventBus()
        stream = sse.event_stream(FakeRequest(connected_checks=3), None, bus)

        first = await anext(stream)
        assert first == ": connected\n\n"
        assert bus.subscriber_count == 1

        bus.publish("rfp_ticket_created", {"id": 9})
        rest = await _collect(stream)

        assert rest == ['id: 1\nevent: rfp_ticket_created\ndata: {"id": 9}\n\n']
        assert bus.subscriber_count == 0  # client "disconnected": cleaned up

    asyncio.run(scenario())


def test_stream_replays_buffered_events_after_last_event_id_before_live_ones(monkeypatch):
    monkeypatch.setattr(sse, "POLL_SECONDS", 0.01)

    async def scenario():
        bus = EventBus()
        for n in range(1, 4):
            bus.publish("rfp_ticket_created", {"id": n})

        chunks = await _collect(sse.event_stream(FakeRequest(connected_checks=1), 1, bus))

        ids = [c.split("\n")[0] for c in chunks if c.startswith("id:")]
        assert ids == ["id: 2", "id: 3"]
        assert chunks[0] == ": connected\n\n"

    asyncio.run(scenario())


def test_stream_sends_keepalive_comments_when_idle(monkeypatch):
    monkeypatch.setattr(sse, "POLL_SECONDS", 0.01)
    monkeypatch.setattr(sse, "KEEPALIVE_SECONDS", 0.03)

    async def scenario():
        bus = EventBus()
        chunks = await _collect(sse.event_stream(FakeRequest(connected_checks=12), None, bus))

        assert chunks[0] == ": connected\n\n"
        assert ": keepalive\n\n" in chunks
        assert bus.subscriber_count == 0

    asyncio.run(scenario())


# --- endpoint --------------------------------------------------------------


@pytest.fixture
def client() -> TestClient:
    app = FastAPI()
    app.include_router(sse.router)
    return TestClient(app, raise_server_exceptions=False)


def test_stream_rejects_requests_without_a_token(client):
    response = client.get("/events/stream")

    assert response.status_code == 401


def test_stream_rejects_an_invalid_token(client):
    response = client.get("/events/stream", headers={"Authorization": "Bearer not-a-jwt"})

    assert response.status_code == 401


def test_stream_response_has_the_sse_headers():
    response = asyncio.run(sse.stream_events(FakeRequest(0), None, {"id": 1}))

    assert response.media_type == "text/event-stream"
    assert response.headers["cache-control"] == "no-cache"
    assert response.headers["connection"] == "keep-alive"
    assert response.headers["x-accel-buffering"] == "no"


def test_rfp_ticket_created_payload_is_json_serializable():
    from datetime import datetime, timezone

    from data.pipelines.rfp_intake.models import RfpTicket
    from routers.rfp import RFP_TICKET_CREATED_EVENT, _ticket_created_payload

    ticket = RfpTicket(
        id=4,
        original_filename="clinic-rfp.pdf",
        raw_pdf_path="/secret/path.pdf",
        created_at=datetime(2026, 10, 19, tzinfo=timezone.utc),
    )

    payload = _ticket_created_payload(ticket)

    assert RFP_TICKET_CREATED_EVENT == "rfp_ticket_created"
    assert payload == {
        "id": 4,
        "status": "analyzing",
        "original_filename": "clinic-rfp.pdf",
        "created_at": "2026-10-19T00:00:00+00:00",
    }
    json.dumps(payload)
    assert "raw_pdf_path" not in payload


def test_uploading_an_rfp_publishes_rfp_ticket_created_after_the_ticket_is_saved(tmp_path, monkeypatch):
    from sqlalchemy.pool import StaticPool
    from sqlmodel import Session, SQLModel, create_engine

    from app.core.deps import get_current_user
    from database import get_db
    from events.bus import event_bus
    from routers import rfp

    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine, tables=[rfp.RfpTicket.__table__])

    def override_db():
        with Session(engine) as session:
            yield session

    run_ticket = lambda *args, **kwargs: None  # noqa: E731 - the AI pipeline is not part of this test
    monkeypatch.setattr(rfp, "run_ticket", run_ticket)
    monkeypatch.setattr(rfp, "RAW_RFP_DIR", tmp_path)

    app = FastAPI()
    app.include_router(rfp.router)
    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_user] = lambda: {"id": 1, "role": "admin"}

    published: list = []
    original_publish = event_bus.publish
    monkeypatch.setattr(event_bus, "publish", lambda name, data: published.append((name, data)) or original_publish(name, data))

    response = TestClient(app).post("/rfp/tickets", files={"file": ("clinic-rfp.pdf", b"%PDF-1.4 test", "application/pdf")})

    assert response.status_code == 202
    ticket_id = response.json()["ticket_id"]
    assert published == [
        (
            "rfp_ticket_created",
            {
                "id": ticket_id,
                "status": "analyzing",
                "original_filename": "clinic-rfp.pdf",
                "created_at": published[0][1]["created_at"],
            },
        )
    ]
    with Session(engine) as session:
        assert session.get(rfp.RfpTicket, ticket_id) is not None  # saved before/when announced


def test_live_events_are_not_dropped_when_last_event_id_is_ahead_of_a_restarted_bus(monkeypatch):
    monkeypatch.setattr(sse, "POLL_SECONDS", 0.01)

    async def scenario():
        bus = EventBus()  # fresh process: ids restart at 1, the client still remembers id 57
        stream = sse.event_stream(FakeRequest(connected_checks=3), 57, bus)

        assert await anext(stream) == ": connected\n\n"
        bus.publish("rfp_ticket_created", {"id": 1})
        rest = await _collect(stream)

        assert rest == ['id: 1\nevent: rfp_ticket_created\ndata: {"id": 1}\n\n']

    asyncio.run(scenario())
