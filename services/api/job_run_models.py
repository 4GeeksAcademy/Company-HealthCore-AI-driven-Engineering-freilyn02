"""SQLModel ORM table for the nightly background job orchestration
(Background Processes project).

This is the only table this module owns. It lives in the same
Supabase/PostgreSQL database as telemetry_events and the Milestone 5
inventory tables (see database.py).

job_runs tracks the lifecycle of scheduled jobs (currently just
"nightly_export") so a run can be resumed/skipped safely:
  pending -> processing -> completed
                        -> failed

`status = "processing"` doubles as the distributed lock: as long as a row
for a job_name is in that state, no second run of the same job is allowed
to start (see has_processing_lock() in job_runner.py). There is no
separate lock table or column.
"""
from datetime import date, datetime, timezone
from typing import Optional

from sqlalchemy import CheckConstraint, Column, DateTime, Index
from sqlmodel import Field, SQLModel


class JobRun(SQLModel, table=True):
    """A single row = one attempt to run one job for one target_date."""

    __tablename__ = "job_runs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'processing', 'completed', 'failed')",
            name="ck_job_runs_status",
        ),
        # Idempotency key: one (job_name, target_date) pair identifies a
        # single logical day's run, even across retries.
        Index("idx_job_runs_name_date", "job_name", "target_date"),
        Index("idx_job_runs_name_status", "job_name", "status"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    job_name: str = Field(index=True, max_length=64)
    target_date: date = Field(nullable=False)
    status: str = Field(default="pending", max_length=16)

    started_at: Optional[datetime] = Field(
        default=None, sa_column=Column(DateTime(timezone=True))
    )
    finished_at: Optional[datetime] = Field(
        default=None, sa_column=Column(DateTime(timezone=True))
    )
    error_message: Optional[str] = None

    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )