"""Durable checkpointer wiring + namespaced thread ids.

The checkpointer is what makes an interrupt *durable*: the graph state is written to
disk before the pause, so a human can answer minutes or days later - even after the
process restarted - and the run resumes exactly where it stopped.

In-memory checkpointers are refused unless you opt in explicitly (local dev only).
"""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path
from typing import Any

from langgraph.checkpoint.sqlite import SqliteSaver

DEFAULT_CHECKPOINT_DB = "data/process/rfp_checkpoints.sqlite"
ENV_VAR = "RFP_CHECKPOINT_DB"


def get_checkpointer(db: str | os.PathLike[str] | None = None, *, allow_memory: bool = False) -> Any:
    """Return a durable checkpointer.

    - `postgresql://...` -> PostgresSaver (needs `langgraph-checkpoint-postgres` and
      `psycopg[binary]`; this branch is NOT covered by the tests here).
    - anything else      -> SQLite file (default `data/process/rfp_checkpoints.sqlite`).
    """
    target = str(db or os.getenv(ENV_VAR) or DEFAULT_CHECKPOINT_DB)

    if target == ":memory:":
        if not allow_memory:
            raise ValueError(
                "In-memory checkpointer refused: state would be lost on restart. "
                "Pass allow_memory=True only for local development."
            )
        from langgraph.checkpoint.memory import InMemorySaver

        return InMemorySaver()

    if target.startswith(("postgresql://", "postgres://")):
        from langgraph.checkpoint.postgres import PostgresSaver
        from psycopg import Connection
        from psycopg.rows import dict_row

        conn = Connection.connect(
            target, autocommit=True, prepare_threshold=0, row_factory=dict_row
        )
        saver = PostgresSaver(conn)
        saver.setup()
        return saver

    Path(target).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(target, check_same_thread=False)
    return SqliteSaver(conn)


# --------------------------------------------------------------------------- #
# thread ids
# --------------------------------------------------------------------------- #


def thread_id(ticket_id: str, department: str | None = None) -> str:
    """Namespaced thread id.

    - ticket level (closing graph):   rfp-{ticket_id}
    - department branch:              rfp-{ticket_id}:{department}

    Two tickets can never share a checkpoint, and two departments of the same ticket
    can be paused / resumed independently.
    """
    if not ticket_id or ":" in ticket_id:
        raise ValueError(f"invalid ticket_id for thread id: {ticket_id!r}")
    base = f"rfp-{ticket_id}"
    return f"{base}:{department}" if department else base


def thread_config(ticket_id: str, department: str | None = None) -> dict[str, Any]:
    return {
        "configurable": {"thread_id": thread_id(ticket_id, department)},
        "recursion_limit": 60,
    }
