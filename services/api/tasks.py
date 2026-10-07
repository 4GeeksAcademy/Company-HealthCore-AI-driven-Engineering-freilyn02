"""Celery tasks for HealthCore async operations.

@celery_app.task functions receive only lightweight arguments (here,
none at all — the summary reads directly from the incidents table) and
never carry large payloads. Retries use exponential backoff; on final
failure, an audit row is written to the DLQ instead of silently dropping
the task.
"""
import logging
import time

from celery_app import celery_app
from dlq_models import record_dlq_entry
from incident_reporting import generate_incident_summary

logger = logging.getLogger(__name__)


@celery_app.task(bind=True, max_retries=3)
def generate_incident_summary_task(self):
    """Runs the full incidents aggregation in the background."""
    started = time.monotonic()
    attempt = self.request.retries + 1
    try:
        result = generate_incident_summary()
        duration_ms = int((time.monotonic() - started) * 1000)
        logger.info(
            "task_id=%s attempt=%s status=success duration_ms=%s",
            self.request.id, attempt, duration_ms,
        )
        return result
    except Exception as exc:
        duration_ms = int((time.monotonic() - started) * 1000)
        logger.error(
            "task_id=%s attempt=%s status=failure duration_ms=%s error=%s",
            self.request.id, attempt, duration_ms, exc,
        )

        # self.request.retries hasn't been incremented yet for THIS attempt,
        # so ">=" (not ">") correctly identifies the final allowed attempt.
        # We check this ourselves rather than relying on Celery to raise
        # MaxRetriesExceededError — when exc is passed to self.retry(), Celery
        # re-raises that original exception on the final attempt instead of
        # raising MaxRetriesExceededError, so catching that exception type
        # here would never fire.
        if self.request.retries >= self.max_retries:
            record_dlq_entry(
                task_id=self.request.id,
                task_name="generate_incident_summary_task",
                attempt=attempt,
                error_message=str(exc),
            )
            raise

        countdown = 10 * (2 ** self.request.retries)  # 10s, 20s, 40s
        raise self.retry(exc=exc, countdown=countdown)