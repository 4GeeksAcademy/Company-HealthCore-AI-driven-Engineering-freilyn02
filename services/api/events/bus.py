"""In-process pub-sub event bus behind the Server-Sent Events stream.

Each SSE connection subscribes and gets its own asyncio.Queue; publish() fans an event
out to every subscriber. The last REPLAY_BUFFER_SIZE events are kept in memory with an
incrementing integer id, so a client that reconnects with `Last-Event-ID` can catch up.

Scope: one API process. Subscribers and the replay buffer live in memory, so ids restart
at 1 after a restart and events are not shared between workers. Nothing here calls an AI
model or agent: it only moves small JSON payloads between coroutines.
"""
from __future__ import annotations

import asyncio
import threading
from collections import deque
from dataclasses import dataclass
from typing import Any

REPLAY_BUFFER_SIZE = 50
# A subscriber that stops reading loses its OLDEST queued events instead of growing memory.
SUBSCRIBER_QUEUE_SIZE = 100


@dataclass(frozen=True)
class Event:
    id: int
    name: str
    data: dict[str, Any]


def _put_dropping_oldest(queue: asyncio.Queue[Event], event: Event) -> None:
    try:
        queue.put_nowait(event)
    except asyncio.QueueFull:
        queue.get_nowait()
        queue.put_nowait(event)


class EventBus:
    def __init__(self, replay_size: int = REPLAY_BUFFER_SIZE) -> None:
        self._lock = threading.Lock()
        self._subscribers: dict[asyncio.Queue[Event], asyncio.AbstractEventLoop] = {}
        self._buffer: deque[Event] = deque(maxlen=replay_size)
        self._last_id = 0

    def subscribe(self, last_event_id: int | None = None) -> tuple[asyncio.Queue[Event], list[Event]]:
        """Registers a new connection. Must be called from the event loop that will read the queue.

        Returns (queue, backlog). `backlog` holds the buffered events with id greater than
        `last_event_id` (empty for a first connection). Registering and reading the buffer
        happen under one lock, so no event is lost between the replay and the live stream.
        """
        queue: asyncio.Queue[Event] = asyncio.Queue(maxsize=SUBSCRIBER_QUEUE_SIZE)
        loop = asyncio.get_running_loop()
        with self._lock:
            self._subscribers[queue] = loop
            backlog = [] if last_event_id is None else [e for e in self._buffer if e.id > last_event_id]
        return queue, backlog

    def unsubscribe(self, queue: asyncio.Queue[Event]) -> None:
        """Safe to call more than once, or with a queue that was never subscribed."""
        with self._lock:
            self._subscribers.pop(queue, None)

    def publish(self, name: str, data: dict[str, Any]) -> Event:
        """Stores the event in the replay buffer and delivers it to every subscriber.

        Never blocks and never raises because of a subscriber. Safe to call from the event
        loop or from a worker thread (sync endpoints run in a threadpool).
        """
        with self._lock:
            self._last_id += 1
            event = Event(id=self._last_id, name=name, data=data)
            self._buffer.append(event)
            for queue, loop in list(self._subscribers.items()):
                self._deliver(queue, loop, event)
        return event

    @staticmethod
    def _deliver(queue: asyncio.Queue[Event], loop: asyncio.AbstractEventLoop, event: Event) -> None:
        try:
            running = asyncio.get_running_loop()
        except RuntimeError:
            running = None
        if running is loop:
            _put_dropping_oldest(queue, event)
            return
        try:
            loop.call_soon_threadsafe(_put_dropping_oldest, queue, event)
        except RuntimeError:  # that connection's loop is already closed
            pass

    @property
    def subscriber_count(self) -> int:
        with self._lock:
            return len(self._subscribers)


event_bus = EventBus()
