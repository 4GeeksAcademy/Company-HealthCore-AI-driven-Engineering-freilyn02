"""Minimal guardrail observability: one structured log line per block/redirect/sanitize,
plus in-memory counters per failure type exposed through a summary.

failure_type is one of:
  - "structural": the output had the wrong shape (empty, too long, internal markers)
  - "content":    scope or sensitive-content problems (personal use, PHI, leaks, redirects)
  - "security":   attempts to manipulate the agent (instruction override, injected text)

Counters live in process memory on purpose (simple, no extra infrastructure): they reset
when the API restarts. For a real deployment, ship the JSON log lines to a log platform.
"""

from __future__ import annotations

import json
import logging
import threading
from collections import Counter, deque
from datetime import datetime, timezone

logger = logging.getLogger("agent.guardrails")

FAILURE_TYPES = ("structural", "content", "security")
PREVIEW_CHARS = 80

_lock = threading.Lock()
_by_type: Counter = Counter()
_by_guardrail: Counter = Counter()
_redirects = 0
_recent: deque = deque(maxlen=200)


def _preview(message: str | None, sensitive: bool) -> str:
    if sensitive:
        # Never copy possible patient data into logs.
        return "[redacted]"
    text = " ".join((message or "").split())
    return text[:PREVIEW_CHARS] + ("..." if len(text) > PREVIEW_CHARS else "")


def record_event(
    guardrail: str,
    failure_type: str,
    action: str,
    message: str | None = None,
    *,
    redirect: bool = False,
    sensitive: bool = False,
) -> dict:
    """Log one guardrail activation and update the session counters."""
    global _redirects
    if failure_type not in FAILURE_TYPES:
        raise ValueError(f"failure_type must be one of {FAILURE_TYPES}, got {failure_type!r}")
    event = {
        "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "guardrail": guardrail,
        "failure_type": failure_type,
        "action": action,
        "message_preview": _preview(message, sensitive),
    }
    logger.warning(json.dumps(event, ensure_ascii=False))
    with _lock:
        _by_type[failure_type] += 1
        _by_guardrail[guardrail] += 1
        if redirect:
            _redirects += 1
        _recent.append(event)
    return event


def summary() -> dict:
    """Counters since the process started (or since the last reset())."""
    with _lock:
        result = {ft: _by_type[ft] for ft in FAILURE_TYPES}
        result["redirects"] = _redirects
        result["by_guardrail"] = dict(_by_guardrail)
        return result


def recent_events(limit: int = 20) -> list[dict]:
    with _lock:
        return list(_recent)[-limit:]


def reset() -> None:
    global _redirects
    with _lock:
        _by_type.clear()
        _by_guardrail.clear()
        _recent.clear()
        _redirects = 0
