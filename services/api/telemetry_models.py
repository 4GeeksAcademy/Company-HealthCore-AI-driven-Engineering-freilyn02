"""SQLModel ORM table for Telemetry Storage (Phase 3).

This is the only table this module owns. It lives in Supabase/PostgreSQL,
same engine as the Milestone 5 inventory tables (see database.py).

Append-only fact table: no UPDATE or DELETE paths exist anywhere in the
application for this table. Rows are written once by POST /telemetry/events
(see telemetry.py) and never modified afterward.
"""
from datetime import datetime
from typing import Any, Optional
from uuid import uuid4

from sqlalchemy import Column, DateTime, Index
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field, SQLModel


class TelemetryEventRecord(SQLModel, table=True):
    """A single stored telemetry event row.

    Not to be confused with `TelemetryEvent` in telemetry.py, which is the
    Pydantic model for the incoming envelope (eventId, sessionId, properties,
    etc.) sent by TelemetryService on the frontend. This class is the
    persisted, flattened row that `map_event_to_row()` builds from a valid
    `TelemetryEvent`.
    """

    __tablename__ = "telemetry_events"
    __table_args__ = (
        # GIN index required for efficient containment/key lookups on the
        # tags jsonb column (e.g. WHERE tags @> '{"clinic_id": "..."}').
        Index("idx_telemetry_events_tags", "tags", postgresql_using="gin"),
    )

    # UUID generated in Python (uuid4) rather than relying on Postgres'
    # gen_random_uuid(), so this works even if the pgcrypto extension is
    # not enabled on the Supabase project.
    id: Optional[str] = Field(default_factory=lambda: str(uuid4()), primary_key=True)

    # timezone=True makes Postgres store this as `timestamptz`, not the
    # naive `timestamp` SQLModel would generate by default. Matters because
    # incoming events arrive with UTC ISO timestamps (e.g. "...Z") and
    # HealthCore has clinics across US and UK time zones.
    timestamp: datetime = Field(sa_column=Column(DateTime(timezone=True), index=True, nullable=False))

    service: str
    event_type: str = Field(index=True)
    level: str = Field(default="info")
    value: Optional[float] = None
    message: Optional[str] = None

    tags: dict[str, Any] = Field(
        default_factory=dict,
        sa_column=Column(JSONB, nullable=False, server_default="{}"),
    )