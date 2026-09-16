"""Celery app instance for HealthCore async tasks.

Broker and result backend both point at Redis (REDIS_URL). The tasks
module is imported at the bottom so the worker process discovers the
@celery_app.task-decorated functions inside it — a task defined in a
module that's never imported is invisible to `celery -A ... worker`.
"""
import os
from pathlib import Path

from celery import Celery
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent / ".env")

REDIS_URL = os.environ["REDIS_URL"]

celery_app = Celery(
    "healthcore_api",
    broker=REDIS_URL,
    backend=REDIS_URL,
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    task_track_started=True,   # lets GET /tasks/{id} report "started", not just pending/success
    task_time_limit=300,       # hard kill after 5 min — a stuck task should not block the worker forever
    task_soft_time_limit=240,  # gives the task a chance to clean up before the hard kill
    result_expires=86400,      # 24h — results don't need to live in Redis forever
)

# Import at the bottom (after celery_app exists) so tasks.py can safely
# do `from celery_app import celery_app` without a circular import.
import tasks  # noqa: E402,F401
