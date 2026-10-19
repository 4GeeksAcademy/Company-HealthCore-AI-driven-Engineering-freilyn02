"""GET /events/stream - Server-Sent Events for the backoffice.

Protected by the same JWT dependency as the other backoffice routes (`get_current_user`),
so it needs `Authorization: Bearer <token>`. The browser's native EventSource cannot send
that header; the client must read the stream with fetch.

Wire format (named events, never the generic "message"):

    id: <n>
    event: rfp_ticket_created
    data: <json>
    <blank line>

plus ": connected" on open and ": keepalive" comments every KEEPALIVE_SECONDS when idle.
On reconnect the client sends `Last-Event-ID`; buffered events after that id are replayed
first, then the live stream continues.
"""
import asyncio
import json
import time
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends, Header, Request
from fastapi.responses import StreamingResponse

from app.core.deps import get_current_user
from events.bus import Event, EventBus, event_bus

router = APIRouter(prefix="/events", tags=["events"])

KEEPALIVE_SECONDS = 15.0
# How often an idle stream wakes up to check for a closed connection / a due keepalive.
POLL_SECONDS = 1.0

SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",
}


def format_event(event: Event) -> str:
    return f"id: {event.id}\nevent: {event.name}\ndata: {json.dumps(event.data)}\n\n"


def parse_last_event_id(value: str | None) -> int | None:
    """A missing or malformed header means a first connection (no replay)."""
    if value is None:
        return None
    try:
        return int(value.strip())
    except ValueError:
        return None


async def event_stream(
    request: Request, last_event_id: int | None = None, bus: EventBus = event_bus
) -> AsyncIterator[str]:
    queue, backlog = bus.subscribe(last_event_id)
    try:
        yield ": connected\n\n"
        last_write = time.monotonic()

        for event in backlog:
            yield format_event(event)
            last_write = time.monotonic()

        while not await request.is_disconnected():
            try:
                event = await asyncio.wait_for(queue.get(), timeout=POLL_SECONDS)
            except TimeoutError:
                if time.monotonic() - last_write >= KEEPALIVE_SECONDS:
                    yield ": keepalive\n\n"
                    last_write = time.monotonic()
                continue
            # subscribe() registers and snapshots the replay buffer under one lock, so a live
            # event is never also in the backlog. Do not filter by the client's Last-Event-ID
            # here: after a server restart ids start again at 1 and would be dropped.
            yield format_event(event)
            last_write = time.monotonic()
    finally:
        bus.unsubscribe(queue)


@router.get("/stream")
async def stream_events(
    request: Request,
    last_event_id: str | None = Header(default=None),
    current_user: dict = Depends(get_current_user),
):
    return StreamingResponse(
        event_stream(request, parse_last_event_id(last_event_id), event_bus),
        media_type="text/event-stream",
        headers=SSE_HEADERS,
    )
