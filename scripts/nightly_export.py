"""Nightly telemetry export job (Background Processes project).

Independent CLI process - must be run as `python scripts/nightly_export.py`,
never imported into or triggered from the FastAPI app. Responsibilities:

  1. Export the previous day's telemetry_events to a CSV backup file.
  2. Trigger the Milestone 6 business performance pipeline (which reads
     telemetry_events straight from the database, not from this CSV).
  3. Track its own lifecycle in job_runs so a crash never leaves a job
     "stuck" and a duplicate same-day run never re-does the work.

Usage:
    python scripts/nightly_export.py
    TARGET_DATE=2025-01-15 python scripts/nightly_export.py
"""
import csv
import json
import logging
import os
import subprocess
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

# --- Make services/api importable -------------------------------------------
# This script lives outside services/api, so its modules (database,
# job_runner, telemetry_models) aren't on the import path by default. We add
# that folder here, once, before importing anything from it.
REPO_ROOT = Path(__file__).resolve().parents[1]
SERVICES_API_DIR = REPO_ROOT / "services" / "api"
if str(SERVICES_API_DIR) not in sys.path:
    sys.path.insert(0, str(SERVICES_API_DIR))

from sqlmodel import Session, SQLModel, select  # noqa: E402
from database import engine  # noqa: E402
from telemetry_models import TelemetryEventRecord  # noqa: E402
import job_runner  # noqa: E402

# Creates job_runs (and any other table registered in SQLModel's metadata
# via the imports above) if it doesn't exist yet. Required so this script
# can run standalone, with no FastAPI server needed first.
SQLModel.metadata.create_all(engine)

JOB_NAME = "nightly_export"
PIPELINE_SCRIPT = REPO_ROOT / "data" / "pipelines" / "pipeline.py"
CSV_DIR = REPO_ROOT / "data" / "raw"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%SZ",
)
logger = logging.getLogger(JOB_NAME)


def resolve_target_date() -> date:
    """TARGET_DATE env var (YYYY-MM-DD) takes priority; otherwise yesterday
    in UTC. Never the local machine's timezone - HealthCore has clinics in
    both the US and UK."""
    override = os.getenv("TARGET_DATE")
    if override:
        return datetime.strptime(override, "%Y-%m-%d").date()
    return datetime.now(timezone.utc).date() - timedelta(days=1)


def export_telemetry_csv(target_date: date) -> Path:
    """Writes telemetry_events rows for target_date to a CSV backup.
    Skips the export if the file already exists (idempotent file layer)."""
    CSV_DIR.mkdir(parents=True, exist_ok=True)
    csv_path = CSV_DIR / f"telemetry_{target_date.isoformat()}.csv"

    if csv_path.exists():
        logger.info(
            f"nightly_export status=export_skipped reason=file_exists "
            f"path={csv_path} target_date={target_date}"
        )
        return csv_path

    day_start = datetime(target_date.year, target_date.month, target_date.day, tzinfo=timezone.utc)
    day_end = day_start + timedelta(days=1)

    with Session(engine) as session:
        statement = select(TelemetryEventRecord).where(
            TelemetryEventRecord.timestamp >= day_start,
            TelemetryEventRecord.timestamp < day_end,
        )
        rows = session.exec(statement).all()

    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(
            ["id", "timestamp", "service", "event_type", "level", "value", "message", "tags"]
        )
        for row in rows:
            writer.writerow(
                [
                    row.id,
                    row.timestamp.isoformat(),
                    row.service,
                    row.event_type,
                    row.level,
                    row.value,
                    row.message,
                    json.dumps(row.tags),
                ]
            )

    logger.info(
        f"nightly_export status=export_completed rows={len(rows)} "
        f"path={csv_path} target_date={target_date}"
    )
    return csv_path


def run_pipeline() -> None:
    """Runs the Milestone 6 pipeline as a separate subprocess. Raises
    RuntimeError if it exits non-zero. The pipeline itself reads
    telemetry_events straight from the database, never from the CSV."""
    result = subprocess.run(
        [sys.executable, str(PIPELINE_SCRIPT)],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"pipeline exit code {result.returncode}: {result.stderr.strip()}")
    logger.info(f"nightly_export status=pipeline_completed output={result.stdout.strip()}")


def main() -> int:
    target_date = resolve_target_date()

    if job_runner.has_processing_lock(JOB_NAME):
        logger.info(
            f"nightly_export status=cancelled reason=processing_lock target_date={target_date}"
        )
        return 0

    if job_runner.has_completed_for_date(JOB_NAME, target_date):
        logger.info(f"nightly_export status=skipped reason=duplicate target_date={target_date}")
        return 0

    run = job_runner.create_run(JOB_NAME, target_date)
    job_runner.mark_processing(run.id)
    logger.info(f"nightly_export status=started target_date={target_date}")

    try:
        export_telemetry_csv(target_date)
        run_pipeline()
        job_runner.mark_completed(run.id)
        logger.info(f"nightly_export status=completed target_date={target_date}")
        return 0
    except Exception as e:
        job_runner.mark_failed(run.id, str(e))
        logger.error(f"nightly_export status=failed error={e} target_date={target_date}")
        return 1
    finally:
        # By the time we get here, mark_completed or mark_failed above has
        # already moved the row out of "processing" - this is just the
        # closing log line, not additional lock-clearing logic.
        logger.info(f"nightly_export status=finished target_date={target_date}")


if __name__ == "__main__":
    sys.exit(main())