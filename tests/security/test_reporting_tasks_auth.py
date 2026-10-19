"""Security regression tests: reporting, task-status and incident-summary routes require auth.

Before the fix, anyone who could reach the API could trigger the business-performance
pipeline, read reporting data and enqueue background tasks (OWASP A01/A04).
Pipeline and Celery calls are stubbed, so no database, Redis or worker is needed.
"""

import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

# Throwaway values so main.py can be imported outside Docker.
os.environ.setdefault("SECRET_KEY", "test-only-secret-key-not-used-anywhere-else")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")

REPO_ROOT = Path(__file__).resolve().parents[2]
API_DIR = REPO_ROOT / "services" / "api"
if str(API_DIR) not in sys.path:
    sys.path.insert(0, str(API_DIR))
# data/ lives at the repository root; appended so it never shadows this service's modules.
if str(REPO_ROOT) not in sys.path:
    sys.path.append(str(REPO_ROOT))

from fastapi.testclient import TestClient  # noqa: E402

import main  # noqa: E402
from app.core.deps import get_current_user  # noqa: E402

PROTECTED_ROUTES = [
    ("GET", "/reporting/pipeline-runs/latest"),
    ("POST", "/reporting/pipeline-runs"),
    ("GET", "/reporting/monthly-clinic-supply-performance"),
    ("POST", "/api/incidents/summary"),
    ("GET", "/tasks/some-task-id"),
]


@pytest.fixture()
def client(monkeypatch):
    # Stub everything behind the access-control layer.
    monkeypatch.setattr(main, "get_latest_pipeline_run", lambda: {"id": 1})
    monkeypatch.setattr(main, "trigger_pipeline_run", lambda: {"status": "queued"})
    monkeypatch.setattr(
        main,
        "get_monthly_clinic_supply_performance",
        lambda month_start=None: [{"clinic": "stub"}],
    )
    monkeypatch.setattr(
        main,
        "generate_incident_summary_task",
        SimpleNamespace(delay=lambda: SimpleNamespace(id="fake-task-id")),
    )
    monkeypatch.setattr(
        main,
        "AsyncResult",
        lambda task_id, app=None: SimpleNamespace(status="PENDING", result=None),
    )
    # No "with" block: startup hooks (database creation) are not run.
    yield TestClient(main.app)
    main.app.dependency_overrides.clear()


@pytest.mark.parametrize("method,path", PROTECTED_ROUTES)
def test_anonymous_request_is_rejected(client, method, path):
    response = client.request(method, path)
    assert response.status_code == 401, f"{method} {path} answered an anonymous request"


@pytest.mark.parametrize("method,path", PROTECTED_ROUTES)
def test_invalid_token_is_rejected(client, method, path):
    response = client.request(method, path, headers={"Authorization": "Bearer not-a-real-token"})
    assert response.status_code == 401, f"{method} {path} accepted a forged token"


@pytest.mark.parametrize("method,path", PROTECTED_ROUTES)
def test_authenticated_user_still_works(client, method, path):
    # The legitimate backoffice flow must keep working after the fix.
    main.app.dependency_overrides[get_current_user] = lambda: {"id": 1, "role": "admin"}
    response = client.request(method, path)
    assert response.status_code in (200, 202)