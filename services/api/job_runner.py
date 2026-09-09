"""Persistence layer for job_runs (Background Processes project).

All database access for the nightly job orchestration lives here. The
calling script (scripts/nightly_export.py) only orchestrates; it never
touches the database directly.
"""
from datetime import date, datetime, timezone

from sqlmodel import Session, select

from database import engine
from job_run_models import JobRun


def create_run(job_name: str, target_date: date) -> JobRun:
    """Insert a new `pending` row for this (job_name, target_date)."""
    run = JobRun(job_name=job_name, target_date=target_date, status="pending")
    with Session(engine) as session:
        session.add(run)
        session.commit()
        session.refresh(run)
        return run


def mark_processing(run_id: int) -> None:
    """Transition a run to `processing` and stamp started_at.

    Acts as the distributed lock: as long as this row stays `processing`,
    has_processing_lock() reports the job as busy.
    """
    with Session(engine) as session:
        run = session.get(JobRun, run_id)
        run.status = "processing"
        run.started_at = datetime.now(timezone.utc)
        session.add(run)
        session.commit()


def mark_completed(run_id: int) -> None:
    """Transition a run to `completed` and stamp finished_at. Releases the lock."""
    with Session(engine) as session:
        run = session.get(JobRun, run_id)
        run.status = "completed"
        run.finished_at = datetime.now(timezone.utc)
        session.add(run)
        session.commit()


def mark_failed(run_id: int, error_message: str) -> None:
    """Transition a run to `failed`, stamp finished_at, record the error.
    Releases the lock (a `failed` row is not `processing`)."""
    with Session(engine) as session:
        run = session.get(JobRun, run_id)
        run.status = "failed"
        run.finished_at = datetime.now(timezone.utc)
        run.error_message = error_message
        session.add(run)
        session.commit()


def has_processing_lock(job_name: str) -> bool:
    """True if any row for this job_name is currently `processing`."""
    with Session(engine) as session:
        statement = select(JobRun).where(
            JobRun.job_name == job_name, JobRun.status == "processing"
        )
        return session.exec(statement).first() is not None


def has_completed_for_date(job_name: str, target_date: date) -> bool:
    """Idempotency check: True if this (job_name, target_date) already
    has a `completed` row."""
    with Session(engine) as session:
        statement = select(JobRun).where(
            JobRun.job_name == job_name,
            JobRun.target_date == target_date,
            JobRun.status == "completed",
        )
        return session.exec(statement).first() is not None