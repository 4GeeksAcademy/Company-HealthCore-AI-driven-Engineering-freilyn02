"""Explicit read/write interface for the agent memory (never the system prompt).

Two backends share the same interface:
  - RedisMemoryStore: real persistence (Redis DB /1, `agent_memory:` prefix).
  - InMemoryMemoryStore: used by the tests, no Redis needed.
"""

from __future__ import annotations

import json
import os
import re
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Protocol

from .clock import to_iso, utc_now

KEY_PREFIX = "agent_memory"
_STOPWORDS = {"the", "and", "for", "are", "was", "with", "that", "this", "from", "have", "what", "how"}


def memory_redis_url() -> str:
    """Redis URL for memory: same server as Celery, but a DIFFERENT database (/1)."""
    explicit = os.getenv("MEMORY_REDIS_URL")
    if explicit:
        return explicit
    base = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    return re.sub(r"/\d+$", "", base.rstrip("/")) + "/1"


def get_redis_client():
    import redis  # imported lazily so the tests never need a Redis server

    return redis.Redis.from_url(memory_redis_url(), decode_responses=True)


def _tokens(text: str) -> set[str]:
    return {t for t in re.findall(r"[a-z0-9]+", (text or "").lower()) if len(t) >= 3 and t not in _STOPWORDS}


@dataclass
class MemoryEntry:
    id: str
    fact: str
    keys: list[str]
    proposal_id: str  # which approved proposal created it (traceability)
    created_at: str
    last_used_at: str
    hits: int = 0

    @classmethod
    def new(cls, fact: str, keys: list[str], proposal_id: str, now: datetime | None = None) -> "MemoryEntry":
        stamp = to_iso(now or utc_now())
        return cls(
            id=f"mem-{uuid.uuid4().hex[:8]}",
            fact=fact,
            keys=list(keys),
            proposal_id=proposal_id,
            created_at=stamp,
            last_used_at=stamp,
        )

    def to_json(self) -> str:
        return json.dumps(asdict(self))

    @classmethod
    def from_json(cls, raw: str) -> "MemoryEntry":
        return cls(**json.loads(raw))


class MemoryStore(Protocol):
    def write(self, entry: MemoryEntry) -> None: ...
    def read(self, entry_id: str) -> MemoryEntry | None: ...
    def delete(self, entry_id: str) -> None: ...
    def list(self) -> list[MemoryEntry]: ...
    def search(self, query: str, limit: int = 3) -> list[MemoryEntry]: ...
    def touch(self, entry_id: str, now: datetime | None = None) -> MemoryEntry | None: ...


class _StoreBase:
    """Shared search/touch logic; subclasses only implement write/read/delete/list."""

    def search(self, query: str, limit: int = 3) -> list[MemoryEntry]:
        wanted = _tokens(query)
        scored: list[tuple[int, MemoryEntry]] = []
        for entry in self.list():
            key_tokens = _tokens(" ".join(entry.keys))
            fact_tokens = _tokens(entry.fact) - key_tokens
            score = 2 * len(wanted & key_tokens) + len(wanted & fact_tokens)
            if score >= 2:  # one matching key, or two matching words
                scored.append((score, entry))
        scored.sort(key=lambda pair: pair[0], reverse=True)
        return [entry for _, entry in scored[:limit]]

    def touch(self, entry_id: str, now: datetime | None = None) -> MemoryEntry | None:
        entry = self.read(entry_id)
        if entry is None:
            return None
        entry.hits += 1
        entry.last_used_at = to_iso(now or utc_now())
        self.write(entry)
        return entry


class InMemoryMemoryStore(_StoreBase):
    def __init__(self) -> None:
        self._entries: dict[str, MemoryEntry] = {}

    def write(self, entry: MemoryEntry) -> None:
        self._entries[entry.id] = entry

    def read(self, entry_id: str) -> MemoryEntry | None:
        return self._entries.get(entry_id)

    def delete(self, entry_id: str) -> None:
        self._entries.pop(entry_id, None)

    def list(self) -> list[MemoryEntry]:
        return list(self._entries.values())


class RedisMemoryStore(_StoreBase):
    _INDEX = f"{KEY_PREFIX}:index"

    def __init__(self, client=None) -> None:
        self._r = client if client is not None else get_redis_client()

    def _key(self, entry_id: str) -> str:
        return f"{KEY_PREFIX}:entry:{entry_id}"

    def write(self, entry: MemoryEntry) -> None:
        pipe = self._r.pipeline()
        pipe.set(self._key(entry.id), entry.to_json())
        pipe.sadd(self._INDEX, entry.id)
        pipe.execute()

    def read(self, entry_id: str) -> MemoryEntry | None:
        raw = self._r.get(self._key(entry_id))
        return MemoryEntry.from_json(raw) if raw else None

    def delete(self, entry_id: str) -> None:
        pipe = self._r.pipeline()
        pipe.delete(self._key(entry_id))
        pipe.srem(self._INDEX, entry_id)
        pipe.execute()

    def list(self) -> list[MemoryEntry]:
        ids = sorted(self._r.smembers(self._INDEX))
        if not ids:
            return []
        entries: list[MemoryEntry] = []
        for entry_id, raw in zip(ids, self._r.mget([self._key(i) for i in ids])):
            if raw is None:  # stale index entry
                self._r.srem(self._INDEX, entry_id)
            else:
                entries.append(MemoryEntry.from_json(raw))
        return entries
