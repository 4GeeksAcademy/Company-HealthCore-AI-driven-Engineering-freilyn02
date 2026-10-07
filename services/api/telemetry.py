"""
Telemetry ingestion stub (Phase 1).

This module defines the request/response contract for telemetry events
and a stub endpoint that logs incoming events without persisting them.
Persistence is out of scope for this phase (see project notes).
"""

import logging
from datetime import datetime
from typing import Any

from fastapi import FastAPI
from pydantic import BaseModel, Field

logger = logging.getLogger("telemetry")

# Uvicorn does not configure the root logger, so a logger with no explicit
# handler silently drops INFO-level messages (Python's logging.lastResort
# handler only surfaces WARNING and above). Attaching a handler here
# guarantees these logs are visible regardless of uvicorn's own config.
if not logger.handlers:
    _handler = logging.StreamHandler()
    _handler.setFormatter(logging.Formatter("%(levelname)s:%(name)s:%(message)s"))
    logger.addHandler(_handler)
logger.setLevel(logging.INFO)
logger.propagate = False


# ---- Input schemas ----

class TelemetryEvent(BaseModel):
    eventId: str
    timestamp: datetime
    sessionId: str
    userId: str
    event_type: str
    schemaVersion: str
    requestId: str
    properties: dict[str, Any] = Field(default_factory=dict)


class TelemetryBatch(BaseModel):
    events: list[TelemetryEvent]


# ---- Output schema ----

class TelemetryReceivedResponse(BaseModel):
    received: int


def register_telemetry_routes(app: FastAPI) -> None:
    """Attach the telemetry stub endpoint to the given FastAPI app."""

    @app.post("/telemetry/events", response_model=TelemetryReceivedResponse)
    def receive_telemetry_events(batch: TelemetryBatch) -> TelemetryReceivedResponse:
        for event in batch.events:
            logger.info(
                "telemetry_event received event_type=%s eventId=%s sessionId=%s",
                event.event_type,
                event.eventId,
                event.sessionId,
            )

        logger.info("telemetry_batch received count=%d", len(batch.events))

        return TelemetryReceivedResponse(received=len(batch.events))