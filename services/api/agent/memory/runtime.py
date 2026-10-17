"""One place that builds the memory backends (Redis by default, in-memory for tests)."""

from __future__ import annotations

import os

from .audit import AuditLog, InMemoryAuditLog, RedisAuditLog
from .proposal import InMemoryPendingStore, PendingStore, RedisPendingStore
from .store import InMemoryMemoryStore, MemoryStore, RedisMemoryStore

_instances: dict[str, object] = {}


def _use_redis() -> bool:
    return os.getenv("AGENT_MEMORY_BACKEND", "redis").lower() != "memory"


def get_store() -> MemoryStore:
    if "store" not in _instances:
        _instances["store"] = RedisMemoryStore() if _use_redis() else InMemoryMemoryStore()
    return _instances["store"]  # type: ignore[return-value]


def get_pending_store() -> PendingStore:
    if "pending" not in _instances:
        _instances["pending"] = RedisPendingStore() if _use_redis() else InMemoryPendingStore()
    return _instances["pending"]  # type: ignore[return-value]


def get_audit_log() -> AuditLog:
    if "audit" not in _instances:
        _instances["audit"] = RedisAuditLog() if _use_redis() else InMemoryAuditLog()
    return _instances["audit"]  # type: ignore[return-value]


def use_in_memory() -> tuple[MemoryStore, PendingStore, AuditLog]:
    """Swap every backend for a fresh in-memory one (used by the tests)."""
    _instances["store"] = InMemoryMemoryStore()
    _instances["pending"] = InMemoryPendingStore()
    _instances["audit"] = InMemoryAuditLog()
    return _instances["store"], _instances["pending"], _instances["audit"]  # type: ignore[return-value]
