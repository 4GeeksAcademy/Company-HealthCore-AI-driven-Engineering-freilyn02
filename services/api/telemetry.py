"""
Telemetry ingestion (Phase 3 — real storage).

This module defines the request/response contract for telemetry events and
the real endpoint that validates each event individually and persists valid
ones to Supabase in a single bulk INSERT.

Design invariant (unchanged from Phase 1/2): same URL, same request body,
same HTTP 200 on success. TelemetryService on the frontend ignores the
response body's shape beyond a 2xx status, so nothing on the frontend needs
to change.
"""

import logging
from datetime import datetime
from typing import Any, Optional
from uuid import uuid4

from fastapi import Body, Depends, FastAPI
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import insert
from sqlmodel import Session

from database import get_db
from telemetry_models import TelemetryEventRecord

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


# ---- Input schema (unchanged from Phase 2 — do not modify) ----
# This is the envelope contract every event from TelemetryService must
# satisfy. It is reused as-is; only what happens after validation changed.

class TelemetryEvent(BaseModel):
    eventId: str
    timestamp: datetime
    sessionId: str
    userId: str
    event_type: str
    schemaVersion: str
    requestId: str
    properties: dict[str, Any] = Field(default_factory=dict)


# ---- Output schema ----

class TelemetryStorageResponse(BaseModel):
    received: int
    stored: int
    rejected: int


# ---- event_type -> level derivation ----
# Kept as explicit sets (not a single hardcoded value) so the mapping stays
# traceable back to telemetry-plan.md and event-schemas.json. Anything not
# listed here defaults to "info".

_ERROR_EVENT_TYPES = {
    "frontend_error_caught",
}

_WARN_EVENT_TYPES = {
    "login_failed",
    "direct_stock_edit_rejected",
    "permission_denied",
    "order_validation_failed",
    "stock_threshold_triggered",
    "supply_expiry_flagged",
    "session_expired",
    "order_flow_abandoned",
}


def _derive_level(event_type: str) -> str:
    if event_type in _ERROR_EVENT_TYPES:
        return "error"
    if event_type in _WARN_EVENT_TYPES:
        return "warn"
    return "info"


def _derive_value(event: TelemetryEvent) -> Optional[float]:
    """Extract a single representative numeric metric, when the event type
    has an obvious one. Returns None otherwise (most events don't have a
    single meaningful number)."""

    props = event.properties

    if event.event_type == "api_latency_recorded":
        return props.get("duration_ms")
    if event.event_type in ("inbound_order_created", "outbound_order_created"):
        return props.get("quantity")
    if event.event_type == "stock_threshold_triggered":
        return props.get("current_stock")
    if event.event_type == "product_search_performed":
        return props.get("result_count")
    if event.event_type == "session_expired":
        return props.get("session_duration_seconds")

    return None


def _derive_message(event: TelemetryEvent) -> Optional[str]:
    """Short human-readable summary for events where one adds real value
    (mostly errors/rejections). None otherwise."""

    props = event.properties

    if event.event_type == "frontend_error_caught":
        return props.get("error_message")
    if event.event_type == "login_failed":
        return f"login failed: {props.get('failure_reason')}"
    if event.event_type == "direct_stock_edit_rejected":
        return f"direct stock edit rejected: {props.get('attempted_action')}"
    if event.event_type == "permission_denied":
        return f"permission denied: {props.get('attempted_action')}"
    if event.event_type == "order_validation_failed":
        return f"order validation failed: {props.get('validation_error_code')}"

    return None


def map_event_to_row(event: TelemetryEvent) -> dict[str, Any]:
    """Flatten a validated TelemetryEvent envelope into a telemetry_events
    row. `tags` gets the full `properties` dict as-is: event-schemas.json
    already enforces `additionalProperties: false` per event type, so the
    allowlisting already happened at validation time on the frontend/here —
    nothing extra to filter here."""

    return {
        "id": str(uuid4()),
        "timestamp": event.timestamp,
        # Every event instrumented so far originates from the backoffice UI
        # (see telemetry-frontend-capture notes). Revisit if/when another
        # service starts sending telemetry.
        "service": "backoffice",
        "event_type": event.event_type,
        "level": _derive_level(event.event_type),
        "value": _derive_value(event),
        "message": _derive_message(event),
        "tags": event.properties,
    }


def register_telemetry_routes(app: FastAPI) -> None:
    """Attach the real telemetry storage endpoint to the given FastAPI app."""

    @app.post("/telemetry/events", response_model=TelemetryStorageResponse)
    def receive_telemetry_events(
        payload: dict[str, Any] = Body(...),
        db: Session = Depends(get_db),
    ) -> TelemetryStorageResponse:
        # Intentionally NOT typed as `events: list[TelemetryEvent]` in the
        # signature above. Doing so would make FastAPI validate the whole
        # batch atomically and return 422 the moment a single event is
        # malformed, aborting valid events along with it. Instead we accept
        # the raw payload and validate each event ourselves, one at a time.
        raw_events = payload.get("events", [])

        valid_rows: list[dict[str, Any]] = []
        rejected = 0

        for raw in raw_events:
            try:
                event = TelemetryEvent.model_validate(raw)
            except ValidationError:
                rejected += 1
                continue
            valid_rows.append(map_event_to_row(event))

        stored = 0
        if valid_rows:
            # Single bulk INSERT (one statement, multiple VALUES rows) in
            # one transaction — not a loop of individual inserts.
            db.execute(insert(TelemetryEventRecord), valid_rows)
            db.commit()
            stored = len(valid_rows)

        received = len(raw_events)
        logger.info(
            "telemetry_batch received=%d stored=%d rejected=%d",
            received,
            stored,
            rejected,
        )

        return TelemetryStorageResponse(received=received, stored=stored, rejected=rejected)