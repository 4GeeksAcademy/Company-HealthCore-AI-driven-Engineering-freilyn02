"""Technical/operational metrics over telemetry_events (Phase 4).

Every function below follows the same fixed pipeline:

    load (SQL: event_type + timestamp window)
      -> refine (pandas: derived columns)
      -> convert types (pd.to_datetime with utc=True)
      -> groupby
      -> aggregate
      -> list[dict]

Functions are pure: same (db, start_date, end_date) in -> same list[dict]
out, no writes, no side effects. `db` is only used to read; the endpoint in
router.py owns resolving default dates and caching the assembled response —
these functions never see missing dates and never touch the cache.
"""
from datetime import datetime
from typing import Any, Optional

import pandas as pd
from sqlmodel import Session, select

from telemetry_models import TelemetryEventRecord


def _load_events(
    db: Session,
    start_date: datetime,
    end_date: datetime,
    event_types: Optional[list[str]] = None,
) -> pd.DataFrame:
    """Load rows from telemetry_events, filtered in SQL — never a full
    table scan pulled into pandas afterward.

    - Timestamp window is inclusive start, exclusive end (matches the
      GET /telemetry/report contract documented in router.py).
    - `event_types`, when given, pushes an `IN (...)` filter down to SQL.
      Used by latency_per_day() below, which only cares about one event
      type and would otherwise waste memory loading everything else.
    """
    query = select(
        TelemetryEventRecord.id,
        TelemetryEventRecord.timestamp,
        TelemetryEventRecord.event_type,
        TelemetryEventRecord.level,
        TelemetryEventRecord.value,
    ).where(
        TelemetryEventRecord.timestamp >= start_date,
        TelemetryEventRecord.timestamp < end_date,
    )

    if event_types:
        query = query.where(TelemetryEventRecord.event_type.in_(event_types))

    rows = db.exec(query).all()

    # Each row is a SQLAlchemy Row (named-tuple-like), not a plain dict.
    # `row._mapping` is the documented, version-stable way to get a
    # dict-like view of it (works across SQLAlchemy 1.4 and 2.0).
    return pd.DataFrame([dict(row._mapping) for row in rows])


def events_per_day(
    db: Session, start_date: datetime, end_date: datetime
) -> list[dict[str, Any]]:
    """Operational question: which events occur, and how often, per day?

    This is the most basic volume signal — it covers every event_type in
    the catalogue (business and technical alike) and is usually the first
    place you notice something broke: a type that suddenly stops appearing,
    or one that spikes far above its normal daily count.
    """
    df = _load_events(db, start_date, end_date)

    if df.empty:
        return []

    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    df["date"] = df["timestamp"].dt.date.astype(str)

    result = (
        df.groupby(["date", "event_type"])["id"]
        .count()
        .reset_index()
        .rename(columns={"id": "event_count"})
        .sort_values(["date", "event_type"])
        .to_dict(orient="records")
    )
    return result


def error_rate_by_type(
    db: Session, start_date: datetime, end_date: datetime
) -> list[dict[str, Any]]:
    """Operational question: where do failures concentrate, day over day?

    Uses the `level` column instead of hardcoding event_type ==
    "frontend_error_caught". `level` is already derived once, at ingestion
    time, in telemetry.py's `_derive_level()` — reusing it here means this
    metric automatically stays correct if a new error-level event type gets
    instrumented later, with no change needed in this file.
    """
    df = _load_events(db, start_date, end_date)

    if df.empty:
        return []

    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    df["date"] = df["timestamp"].dt.date.astype(str)
    df["is_error"] = df["level"] == "error"

    grouped = df.groupby("date")["is_error"].agg(["sum", "count"]).reset_index()
    grouped["error_rate"] = (grouped["sum"] / grouped["count"]).round(4)

    result = (
        grouped[["date", "error_rate"]]
        .sort_values("date")
        .to_dict(orient="records")
    )
    return result


def latency_per_day(
    db: Session, start_date: datetime, end_date: datetime
) -> list[dict[str, Any]]:
    """Operational question: how fast does the measured API path respond,
    per day?

    Only `api_latency_recorded` carries a meaningful numeric `value`
    (duration_ms — see `_derive_value()` in telemetry.py), so the
    event_type filter is pushed down into `_load_events()`'s SQL query
    instead of loading every event type and discarding most rows in
    pandas afterward.
    """
    df = _load_events(db, start_date, end_date, event_types=["api_latency_recorded"])

    if df.empty:
        return []

    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    df["date"] = df["timestamp"].dt.date.astype(str)

    result = (
        df.groupby("date")["value"]
        .mean()
        .round(1)
        .reset_index()
        .rename(columns={"value": "avg_ms"})
        .sort_values("date")
        .to_dict(orient="records")
    )
    return result