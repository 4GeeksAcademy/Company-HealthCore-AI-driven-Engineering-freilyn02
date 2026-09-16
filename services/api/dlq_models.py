"""SQLModel table + helper for the async-tasks Dead Letter Queue.

Persists to Supabase (Postgres) via DATABASE_URL, following the same
create_all-based pattern used elsewhere in this repo (no Alembic).
A row here means: this Celery task exhausted all of its retries and
still failed — someone needs to look at it.
"""
import os
from datetime import datetime, timezone
from typing import Optional

from sqlmodel import Field, SQLModel, Session, create_engine

DATABASE_URL = os.environ["DATABASE_URL"]

engine = create_engine(DATABASE_URL)


class DLQTask(SQLModel, table=True):
    __tablename__ = "dlq_tasks"

    id: Optional[int] = Field(default=None, primary_key=True)
    task_id: str = Field(unique=True, index=True)
    task_name: str
    attempt: int
    error_message: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


def init_dlq_table() -> None:
    """Create the dlq_tasks table if it doesn't exist yet."""
    SQLModel.metadata.create_all(engine)


def record_dlq_entry(task_id: str, task_name: str, attempt: int, error_message: str) -> None:
    """Persist a task that exhausted all retries. Called only from the
    task's MaxRetriesExceededError handler in tasks.py."""
    with Session(engine) as session:
        entry = DLQTask(
            task_id=task_id,
            task_name=task_name,
            attempt=attempt,
            error_message=error_message,
        )
        session.add(entry)
        session.commit()