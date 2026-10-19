"""Security regression tests: the agent and knowledge endpoints require authentication.

Before the fix these endpoints answered anonymous requests, so anyone who could reach the
API could spend LLM and vector-database budget and trigger MCP tool calls (OWASP A01/A04).
The agent and RAG backends are stubbed, so no real LLM or Qdrant call is ever made.
"""

import os
import sys
from pathlib import Path

import pytest

# security.py refuses to import without a signing key; use a throwaway one for tests.
os.environ.setdefault("SECRET_KEY", "test-only-secret-key-not-used-anywhere-else")

REPO_ROOT = Path(__file__).resolve().parents[2]
API_DIR = REPO_ROOT / "services" / "api"
if str(API_DIR) not in sys.path:
    sys.path.insert(0, str(API_DIR))
# data/ lives at the repository root, outside services/api. It is appended (never
# inserted first) so it cannot shadow this service's own modules.
if str(REPO_ROOT) not in sys.path:
    sys.path.append(str(REPO_ROOT))

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.core.deps import get_current_user  # noqa: E402
from routers import agent as agent_router_module  # noqa: E402
from routers import knowledge as knowledge_router_module  # noqa: E402

PROTECTED_ROUTES = [
    ("POST", "/agent/query", {"question": "What are the clinic opening hours?"}),
    ("POST", "/knowledge/query", {"question": "What is the refund policy?"}),
    ("GET", "/agent/guardrails/summary", None),
]


@pytest.fixture()
def client(monkeypatch):
    # Stub the expensive backends: the tests only check the access control layer.
    monkeypatch.setattr(
        agent_router_module,
        "run_agent",
        lambda question, session_id=None: ("run-test", {"answer": "stub answer"}),
    )
    monkeypatch.setattr(knowledge_router_module, "rag_query", lambda question: "stub answer")

    app = FastAPI()
    app.include_router(agent_router_module.router)
    app.include_router(knowledge_router_module.router)
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.mark.parametrize("method,path,body", PROTECTED_ROUTES)
def test_anonymous_request_is_rejected(client, method, path, body):
    response = client.request(method, path, json=body)
    assert response.status_code == 401, f"{method} {path} answered an anonymous request"


@pytest.mark.parametrize("method,path,body", PROTECTED_ROUTES)
def test_invalid_token_is_rejected(client, method, path, body):
    response = client.request(
        method, path, json=body, headers={"Authorization": "Bearer not-a-real-token"}
    )
    assert response.status_code == 401, f"{method} {path} accepted a forged token"


@pytest.mark.parametrize("method,path,body", PROTECTED_ROUTES)
def test_authenticated_user_still_works(client, method, path, body):
    # Legitimate flow must keep working after the fix.
    client.app.dependency_overrides[get_current_user] = lambda: {"id": 1, "role": "admin"}
    response = client.request(method, path, json=body)
    assert response.status_code == 200