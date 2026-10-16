"""Tests for POST /knowledge/query (services/api/routers/knowledge.py).

Only the router is mounted (not the whole HealthCore API), and the RAG pipeline is mocked,
so no database, Qdrant server or API key is needed.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from qdrant_client.http.exceptions import ResponseHandlingException

from routers import knowledge


@pytest.fixture
def client() -> TestClient:
    app = FastAPI()
    app.include_router(knowledge.router)
    return TestClient(app, raise_server_exceptions=False)


def test_returns_only_the_generated_answer(client, monkeypatch):
    rag_query = MagicMock(return_value="No fee for Medicare patients.")
    monkeypatch.setattr(knowledge, "rag_query", rag_query)

    response = client.post("/knowledge/query", json={"question": "  Do I pay a no-show fee?  "})

    assert response.status_code == 200
    assert response.json() == {"answer": "No fee for Medicare patients."}  # nothing else leaks
    rag_query.assert_called_once_with("Do I pay a no-show fee?")  # trimmed


@pytest.mark.parametrize("body", [{}, {"question": ""}, {"question": "   "}, {"question": 123}, {"question": None}])
def test_rejects_missing_or_blank_questions(client, monkeypatch, body):
    rag_query = MagicMock()
    monkeypatch.setattr(knowledge, "rag_query", rag_query)

    assert client.post("/knowledge/query", json=body).status_code == 422
    rag_query.assert_not_called()


def test_rejects_questions_that_are_too_long(client, monkeypatch):
    monkeypatch.setattr(knowledge, "rag_query", MagicMock())
    too_long = "a" * (knowledge.MAX_QUESTION_CHARS + 1)

    assert client.post("/knowledge/query", json={"question": too_long}).status_code == 422


@pytest.mark.parametrize(
    "error",
    [
        httpx.ConnectError("gateway down"),
        httpx.ReadTimeout("gateway too slow"),
        ResponseHandlingException(Exception("qdrant down")),
    ],
)
def test_upstream_failures_become_a_safe_503(client, monkeypatch, error):
    monkeypatch.setattr(knowledge, "rag_query", MagicMock(side_effect=error))

    response = client.post("/knowledge/query", json={"question": "Do you accept Aetna?"})

    assert response.status_code == 503
    assert "temporarily unavailable" in response.json()["detail"]
    assert "gateway" not in response.text and "qdrant" not in response.text  # no internals


def test_refusal_message_is_a_normal_answer(client, monkeypatch):
    refusal = "I'm sorry, I don't have reliable information about that."
    monkeypatch.setattr(knowledge, "rag_query", MagicMock(return_value=refusal))

    response = client.post("/knowledge/query", json={"question": "What is the capital of France?"})

    assert response.status_code == 200
    assert response.json() == {"answer": refusal}