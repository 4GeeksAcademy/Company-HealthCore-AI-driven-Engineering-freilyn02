"""Ticket persistence used by Part 3.

`TicketStore` is a small Protocol so the pipeline does not depend on how tickets are
stored. `SqliteTicketStore` is a real, file-backed implementation used by the tests
and the reproducible E2E script.

For production, CONTEXT 2.3 says Ticket / DepartmentSection / FinalDocument live in
PostgreSQL (Supabase) through your SQLModel layer. Write a `SqlModelTicketStore`
that implements the same methods on top of your existing models and pass it to
`ApprovalWorkflow(store=...)`. Nothing else in the pipeline has to change.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Protocol

from .models import FinalDocument, RFPMeta, SectionRecord, TraceEvent


class TicketStore(Protocol):
    def create_ticket(self, meta: RFPMeta, status: str) -> None: ...
    def get_meta(self, ticket_id: str) -> RFPMeta: ...
    def get_status(self, ticket_id: str) -> str: ...
    def set_status(self, ticket_id: str, status: str) -> None: ...
    def upsert_section(self, section: SectionRecord) -> None: ...
    def get_section(self, ticket_id: str, department_id: str) -> SectionRecord: ...
    def list_sections(self, ticket_id: str) -> list[SectionRecord]: ...
    def append_trace(self, event: TraceEvent) -> None: ...
    def list_trace(self, ticket_id: str) -> list[TraceEvent]: ...
    def save_final_document(self, doc: FinalDocument, markdown: str) -> None: ...
    def get_final_document(self, ticket_id: str) -> FinalDocument | None: ...


class SqliteTicketStore:
    """File-backed store. A new connection per call, so it survives restarts and
    can be shared between threads."""

    def __init__(self, path: str | Path) -> None:
        if str(path) == ":memory:":
            raise ValueError("SqliteTicketStore needs a real file path")
        self.path = str(path)
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        with self._conn() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS tickets (
                    ticket_id TEXT PRIMARY KEY,
                    status TEXT NOT NULL,
                    meta_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS sections (
                    ticket_id TEXT NOT NULL,
                    department_id TEXT NOT NULL,
                    section_json TEXT NOT NULL,
                    PRIMARY KEY (ticket_id, department_id)
                );
                CREATE TABLE IF NOT EXISTS trace (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ticket_id TEXT NOT NULL,
                    event_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS final_documents (
                    ticket_id TEXT PRIMARY KEY,
                    doc_json TEXT NOT NULL,
                    markdown TEXT NOT NULL
                );
                """
            )

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=30)
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    # -- tickets ----------------------------------------------------------- #
    def create_ticket(self, meta: RFPMeta, status: str) -> None:
        with self._conn() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO tickets (ticket_id, status, meta_json) VALUES (?,?,?)",
                (meta.ticket_id, status, meta.model_dump_json()),
            )

    def get_meta(self, ticket_id: str) -> RFPMeta:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT meta_json FROM tickets WHERE ticket_id=?", (ticket_id,)
            ).fetchone()
        if row is None:
            raise KeyError(f"ticket not found: {ticket_id}")
        return RFPMeta.model_validate_json(row[0])

    def get_status(self, ticket_id: str) -> str:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT status FROM tickets WHERE ticket_id=?", (ticket_id,)
            ).fetchone()
        if row is None:
            raise KeyError(f"ticket not found: {ticket_id}")
        return row[0]

    def set_status(self, ticket_id: str, status: str) -> None:
        with self._conn() as conn:
            cur = conn.execute(
                "UPDATE tickets SET status=? WHERE ticket_id=?", (status, ticket_id)
            )
            if cur.rowcount == 0:
                raise KeyError(f"ticket not found: {ticket_id}")

    # -- sections ---------------------------------------------------------- #
    def upsert_section(self, section: SectionRecord) -> None:
        with self._conn() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO sections (ticket_id, department_id, section_json) "
                "VALUES (?,?,?)",
                (section.ticket_id, section.department_id, section.model_dump_json()),
            )

    def get_section(self, ticket_id: str, department_id: str) -> SectionRecord:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT section_json FROM sections WHERE ticket_id=? AND department_id=?",
                (ticket_id, department_id),
            ).fetchone()
        if row is None:
            raise KeyError(f"section not found: {ticket_id}/{department_id}")
        return SectionRecord.model_validate_json(row[0])

    def list_sections(self, ticket_id: str) -> list[SectionRecord]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT section_json FROM sections WHERE ticket_id=?", (ticket_id,)
            ).fetchall()
        return [SectionRecord.model_validate_json(r[0]) for r in rows]

    # -- trace ------------------------------------------------------------- #
    def append_trace(self, event: TraceEvent) -> None:
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO trace (ticket_id, event_json) VALUES (?,?)",
                (event.ticket_id, event.model_dump_json()),
            )

    def list_trace(self, ticket_id: str) -> list[TraceEvent]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT event_json FROM trace WHERE ticket_id=? ORDER BY id", (ticket_id,)
            ).fetchall()
        return [TraceEvent.model_validate(json.loads(r[0])) for r in rows]

    # -- final document ---------------------------------------------------- #
    def save_final_document(self, doc: FinalDocument, markdown: str) -> None:
        with self._conn() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO final_documents (ticket_id, doc_json, markdown) "
                "VALUES (?,?,?)",
                (doc.ticket_id, doc.model_dump_json(), markdown),
            )

    def get_final_document(self, ticket_id: str) -> FinalDocument | None:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT doc_json FROM final_documents WHERE ticket_id=?", (ticket_id,)
            ).fetchone()
        return FinalDocument.model_validate_json(row[0]) if row else None
