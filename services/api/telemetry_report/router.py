"""GET /telemetry/report endpoint (Phase 4).

This module owns everything analysis.py deliberately does NOT: resolving
missing start_date/end_date into a concrete 7-day-default window, wiring
the DB session, assembling the {period, metrics} response shape, and
caching that response for 60s. The 3 metric functions in analysis.py stay
pure and pandas-only; this is the only place HTTP and caching concerns
live.
"""
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from fastapi import Depends, FastAPI, Query
from sqlmodel import Session

from database import get_db
from telemetry_report.analysis import error_rate_by_type, events_per_day, latency_per_day
from telemetry_report.cache import get_or_compute

DEFAULT_WINDOW_DAYS = 7


def _resolve_period(
    start_date: Optional[datetime], end_date: Optional[datetime]
) -> tuple[datetime, datetime]:
    """Endpoint-level default resolution. When a bound is missing:
    end_date defaults to now (UTC), start_date defaults to 7 days before
    the resolved end_date. Metric functions never see a missing date —
    they always receive two concrete datetimes.
    """
    now = datetime.now(timezone.utc)
    resolved_end = end_date or now
    resolved_start = start_date or (resolved_end - timedelta(days=DEFAULT_WINDOW_DAYS))
    return resolved_start, resolved_end


def _build_report(db: Session, start: datetime, end: datetime) -> dict[str, Any]:
    return {
        "period": {"from": start.isoformat(), "to": end.isoformat()},
        "metrics": {
            "events_per_day": events_per_day(db, start, end),
            "error_rate_by_type": error_rate_by_type(db, start, end),
            "latency_per_day": latency_per_day(db, start, end),
        },
    }


def register_telemetry_report_routes(app: FastAPI) -> None:
    """Attach the real telemetry report endpoint to the given FastAPI app.

    Named to mirror `register_telemetry_routes()` in telemetry.py — same
    convention, separate module, no name collision.
    """

    @app.get("/telemetry/report")
    def get_telemetry_report(
        start_date: Optional[datetime] = Query(
            default=None, description="ISO 8601 UTC. Defaults to 7 days before end_date."
        ),
        end_date: Optional[datetime] = Query(
            default=None, description="ISO 8601 UTC. Defaults to now."
        ),
        db: Session = Depends(get_db),
    ) -> dict[str, Any]:
        start, end = _resolve_period(start_date, end_date)

        # Cache key is truncated to the minute. When start_date/end_date
        # are explicit query params this only matters at the edges (two
        # requests a few seconds apart within the same minute share a
        # cache entry); when they're omitted (end defaults to "now"),
        # truncating is what makes back-to-back dashboard polls hit the
        # cache at all — otherwise "now" would differ by microseconds on
        # every request and nothing would ever hit.
        cache_start = start.replace(second=0, microsecond=0)
        cache_end = end.replace(second=0, microsecond=0)

        return get_or_compute(cache_start, cache_end, lambda: _build_report(db, start, end))