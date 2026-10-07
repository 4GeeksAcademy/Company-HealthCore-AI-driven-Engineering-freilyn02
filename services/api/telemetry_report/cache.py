"""In-memory TTL cache for GET /telemetry/report.

Deliberately not `@lru_cache`: `lru_cache` has no expiry of its own, and
using raw `datetime` objects as its cache key means two requests that mean
"the same period" but built their datetimes slightly differently (extra
microseconds, different tzinfo objects) would never hit the same cache
entry. A small dict keyed by a normalized string, with an explicit
`expires_at`, is easier to reason about and to unit test.

Process-local only (a plain module-level dict) — fine for this project's
single-instance FastAPI process, per the reference solution's scope.
"""
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

TTL_SECONDS = 60

_cache: dict[str, dict[str, Any]] = {}


def _cache_key(start_date: datetime, end_date: datetime) -> str:
    return f"{start_date.isoformat()}|{end_date.isoformat()}"


def get_or_compute(
    start_date: datetime,
    end_date: datetime,
    compute: Callable[[], dict[str, Any]],
) -> dict[str, Any]:
    """Return the cached report for this exact (start_date, end_date) key
    if it's still within its 60s TTL; otherwise call `compute()`, store the
    result, and return it.

    `compute` is a zero-argument callable (a closure built by the caller)
    so this module stays fully decoupled from what's actually being
    computed — it only knows how to cache *a* dict by *a* key.
    """
    key = _cache_key(start_date, end_date)
    now = datetime.now(timezone.utc)

    entry = _cache.get(key)
    if entry is not None and entry["expires_at"] > now:
        return entry["value"]

    value = compute()
    _cache[key] = {"value": value, "expires_at": now + timedelta(seconds=TTL_SECONDS)}
    return value