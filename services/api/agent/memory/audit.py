"""Append-only audit log: every proposal and every outcome, approved or not.

There is deliberately NO delete/clear/update method. Restricted data (patient data,
credentials) is redacted before it is logged; injection attempts are kept in full so
repeated poisoning attempts stay visible.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from typing import Literal, Protocol

from .policy import inspect
from .store import KEY_PREFIX, get_redis_client

Decision = Literal["proposed", "approve", "edit", "reject", "unclear", "timeout", "policy_rejected"]

MAX_MESSAGE_CHARS = 300
# Redis runs with noeviction, so the list must be bounded. In production this is
# rotated to durable storage before it is trimmed.
MAX_AUDIT_RECORDS = 20_000
REDACTED = "[redacted: restricted data]"


@dataclass(frozen=True)
class AuditRecord:
    timestamp: str
    proposal_id: str
    session_id: str
    proposed_fact: str
    user_message: str | None
    decision: Decision
    written: bool
    reason: str | None = None

    def to_json(self) -> str:
        return json.dumps(asdict(self))


def sanitize_text(text: str | None) -> str | None:
    """Truncate, and redact anything the memory policy marks as sensitive."""
    if text is None:
        return None
    if inspect(text).sensitive:
        return REDACTED
    return text[:MAX_MESSAGE_CHARS]


class AuditLog(Protocol):
    def append(self, record: AuditRecord) -> None: ...
    def list(self, limit: int | None = None) -> list[AuditRecord]: ...


class InMemoryAuditLog:
    def __init__(self) -> None:
        self._records: list[AuditRecord] = []

    def append(self, record: AuditRecord) -> None:
        self._records.append(record)

    def list(self, limit: int | None = None) -> list[AuditRecord]:
        return list(self._records if limit is None else self._records[-limit:])


class RedisAuditLog:
    _KEY = f"{KEY_PREFIX}:audit"

    def __init__(self, client=None) -> None:
        self._r = client if client is not None else get_redis_client()

    def append(self, record: AuditRecord) -> None:
        pipe = self._r.pipeline()
        pipe.rpush(self._KEY, record.to_json())
        pipe.ltrim(self._KEY, -MAX_AUDIT_RECORDS, -1)
        pipe.execute()

    def list(self, limit: int | None = None) -> list[AuditRecord]:
        start = 0 if limit is None else -limit
        return [AuditRecord(**json.loads(raw)) for raw in self._r.lrange(self._KEY, start, -1)]
