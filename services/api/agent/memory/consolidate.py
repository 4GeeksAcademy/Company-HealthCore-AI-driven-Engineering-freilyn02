"""Consolidation / cleanup, so the memory can never grow without limit.

Policy (and why):
  0. RE-CHECK every entry against the memory policy (patient information, credentials, poisoning)
     and DELETE any entry that fails. HealthCore requires this: validating only when a
     proposal is made is not enough, because the rules can get stricter and entries can be
     edited. Consolidation never rewrites or summarizes a fact, so nothing new is ever
     written; it only keeps or deletes entries that passed this check.
  1. EXPIRE entries not used for ENTRY_TTL_DAYS: stale facts are worse than no facts.
  2. SUPERSEDE: entries with the same keys (a newer correction) or the same normalized
     text keep only the newest one, so old values never fight the corrected one.
  3. CAP at MAX_ENTRIES: evict the least used (then the least recently used) entries.
     HealthCore support volume is low, and Redis runs with noeviction, so the cap is ours.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from .clock import from_iso, utc_now
from .policy import validate_fact
from .store import MemoryEntry, MemoryStore

ENTRY_TTL_DAYS = 90
MAX_ENTRIES = 200


@dataclass
class ConsolidationReport:
    policy_removed: list[tuple[str, str]] = field(default_factory=list)  # (entry id, policy reason)
    expired: list[str] = field(default_factory=list)
    superseded: list[str] = field(default_factory=list)
    evicted: list[str] = field(default_factory=list)
    kept: int = 0


def _normalized_fact(fact: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", fact.lower()))


def _key_set(entry: MemoryEntry) -> tuple[str, ...]:
    return tuple(sorted({k.lower().strip() for k in entry.keys if k.strip()}))


def consolidate(store: MemoryStore, now: datetime | None = None, ttl_days: int = ENTRY_TTL_DAYS,
                max_entries: int = MAX_ENTRIES) -> ConsolidationReport:
    now = now or utc_now()
    report = ConsolidationReport()

    live: list[MemoryEntry] = []
    for entry in store.list():
        check = validate_fact(entry.fact, entry.keys)  # step 0: the policy is re-applied to what is stored
        if not check.allowed:
            report.policy_removed.append((entry.id, check.reason or "policy"))
        elif now - from_iso(entry.last_used_at) > timedelta(days=ttl_days):
            report.expired.append(entry.id)
        else:
            live.append(entry)

    live.sort(key=lambda e: e.created_at, reverse=True)  # newest first
    seen_facts: set[str] = set()
    seen_keys: set[tuple[str, ...]] = set()
    survivors: list[MemoryEntry] = []
    for entry in live:
        fact, keys = _normalized_fact(entry.fact), _key_set(entry)
        if fact in seen_facts or (keys and keys in seen_keys):
            report.superseded.append(entry.id)
            continue
        seen_facts.add(fact)
        if keys:
            seen_keys.add(keys)
        survivors.append(entry)

    if len(survivors) > max_entries:
        survivors.sort(key=lambda e: (e.hits, e.last_used_at))  # least used first
        cut = len(survivors) - max_entries
        report.evicted = [e.id for e in survivors[:cut]]
        survivors = survivors[cut:]

    removed = [entry_id for entry_id, _ in report.policy_removed]
    for entry_id in removed + report.expired + report.superseded + report.evicted:
        store.delete(entry_id)
    report.kept = len(survivors)
    return report
