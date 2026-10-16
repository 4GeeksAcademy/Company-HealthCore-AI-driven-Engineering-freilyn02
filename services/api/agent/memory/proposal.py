"""The single pending memory proposal per conversation (session).

Rules enforced here:
  - at most ONE pending proposal per session (set_if_empty refuses a second one);
  - a proposal nobody answers within PENDING_TTL_SECONDS is DISCARDED, never approved;
  - every proposal is audited when it is created and again when it is resolved.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Protocol

from .audit import AuditLog, AuditRecord, Decision, sanitize_text
from .clock import from_iso, to_iso, utc_now
from .policy import inspect
from .store import KEY_PREFIX, get_redis_client

PENDING_TTL_SECONDS = 30 * 60
_REDIS_CLEANUP_SECONDS = 24 * 60 * 60  # garbage collection only; the audit already has "proposed"


@dataclass
class MemoryProposal:
    proposal_id: str
    session_id: str
    fact: str
    keys: list[str]
    reason: str
    source_message: str  # the user message that originated the proposal
    created_at: str

    @classmethod
    def new(cls, session_id: str, fact: str, keys: list[str], reason: str, source_message: str,
            now: datetime | None = None) -> "MemoryProposal":
        return cls(
            proposal_id=f"mem-{uuid.uuid4().hex[:8]}",
            session_id=session_id,
            fact=fact,
            keys=list(keys),
            reason=reason,
            source_message=source_message,
            created_at=to_iso(now or utc_now()),
        )

    def to_json(self) -> str:
        return json.dumps(asdict(self))

    @classmethod
    def from_json(cls, raw: str) -> "MemoryProposal":
        return cls(**json.loads(raw))


class PendingStore(Protocol):
    def get(self, session_id: str) -> MemoryProposal | None: ...
    def set_if_empty(self, proposal: MemoryProposal) -> bool: ...
    def clear(self, session_id: str) -> None: ...


class InMemoryPendingStore:
    def __init__(self) -> None:
        self._pending: dict[str, MemoryProposal] = {}

    def get(self, session_id: str) -> MemoryProposal | None:
        return self._pending.get(session_id)

    def set_if_empty(self, proposal: MemoryProposal) -> bool:
        if proposal.session_id in self._pending:
            return False
        self._pending[proposal.session_id] = proposal
        return True

    def clear(self, session_id: str) -> None:
        self._pending.pop(session_id, None)


class RedisPendingStore:
    def __init__(self, client=None) -> None:
        self._r = client if client is not None else get_redis_client()

    def _key(self, session_id: str) -> str:
        return f"{KEY_PREFIX}:pending:{session_id}"

    def get(self, session_id: str) -> MemoryProposal | None:
        raw = self._r.get(self._key(session_id))
        return MemoryProposal.from_json(raw) if raw else None

    def set_if_empty(self, proposal: MemoryProposal) -> bool:
        # NX: only sets the key if it does not exist -> "one pending proposal at a time"
        return bool(self._r.set(self._key(proposal.session_id), proposal.to_json(),
                                nx=True, ex=_REDIS_CLEANUP_SECONDS))

    def clear(self, session_id: str) -> None:
        self._r.delete(self._key(session_id))


def audit_record(proposal: MemoryProposal, decision: Decision, written: bool,
                 user_message: str | None = None, reason: str | None = None,
                 now: datetime | None = None) -> AuditRecord:
    """Build an audit record, redacting restricted data in the fact and in the message."""
    fact_is_sensitive = inspect(proposal.fact).sensitive
    return AuditRecord(
        timestamp=to_iso(now or utc_now()),
        proposal_id=proposal.proposal_id,
        session_id=proposal.session_id,
        proposed_fact="[redacted: restricted data]" if fact_is_sensitive else proposal.fact,
        user_message=sanitize_text(user_message),
        decision=decision,
        written=written,
        reason=reason,
    )


def get_active_or_expire(pending: PendingStore, audit: AuditLog, session_id: str,
                         now: datetime | None = None) -> MemoryProposal | None:
    """Return the live pending proposal; if it is too old, discard it (and audit a timeout)."""
    proposal = pending.get(session_id)
    if proposal is None:
        return None
    now = now or utc_now()
    if (now - from_iso(proposal.created_at)).total_seconds() > PENDING_TTL_SECONDS:
        pending.clear(session_id)
        audit.append(audit_record(proposal, "timeout", written=False,
                                  reason="no answer within the pending window", now=now))
        return None
    return proposal
