"""Per-node traceability (agent / input / output / timestamp).

Every graph node calls `record()`. The event is:
  1. persisted immediately in the store (so it survives crashes and interrupts), and
  2. returned as a one-item list so the node can put it in the graph state
     (`trace` channel with an `operator.add` reducer).

Events hold references only (ids, hashes), never content, so the trace cannot leak PHI.
"""

from __future__ import annotations

from typing import Any

from .models import TraceEvent
from .store import TicketStore


def record(
    store: TicketStore,
    *,
    ticket_id: str,
    agent: str,
    input_ref: str,
    output_ref: str,
    department: str | None = None,
) -> list[dict[str, Any]]:
    event = TraceEvent(
        ticket_id=ticket_id,
        agent=agent,
        department=department,
        input_ref=input_ref,
        output_ref=output_ref,
    )
    store.append_trace(event)
    return [event.model_dump()]


def format_trace(events: list[TraceEvent]) -> str:
    """Human readable timeline: answers 'which agent did what, in what order'."""
    lines = []
    for i, e in enumerate(events, start=1):
        dept = f" [{e.department}]" if e.department else ""
        lines.append(f"{i:02d} {e.ts} {e.agent}{dept}: {e.input_ref} -> {e.output_ref}")
    return "\n".join(lines)
