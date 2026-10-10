"""Knowledge base endpoint: answers questions with the RAG pipeline.

    POST /knowledge/query   {"question": "..."}  ->  {"answer": "..."}

All retrieval and generation logic lives in data/pipelines/rag.py; this module is only
the HTTP surface (validation, error mapping and the response shape).
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, field_validator
from qdrant_client.http.exceptions import ResponseHandlingException, UnexpectedResponse

# data/ lives at the repository root, outside services/api, so it is not importable by
# default. The root is appended (not inserted first) so it can never shadow this service's
# own modules.
REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.append(str(REPO_ROOT))

from data.pipelines.rag import query as rag_query  # noqa: E402 - needs the path above

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/knowledge", tags=["knowledge"])

MAX_QUESTION_CHARS = 500


class KnowledgeQueryRequest(BaseModel):
    question: str

    @field_validator("question")
    @classmethod
    def validate_question(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("question must not be empty")
        if len(value) > MAX_QUESTION_CHARS:
            raise ValueError(f"question must be at most {MAX_QUESTION_CHARS} characters")
        return value


class KnowledgeQueryResponse(BaseModel):
    answer: str


@router.post("/query", response_model=KnowledgeQueryResponse)
def query_knowledge_base(payload: KnowledgeQueryRequest) -> KnowledgeQueryResponse:
    """Return the generated answer for a question about HealthCore's policies."""
    try:
        answer = rag_query(payload.question)
    except (httpx.HTTPError, ResponseHandlingException, UnexpectedResponse):
        # The embeddings/LLM gateway or Qdrant is unreachable or failed. The question is
        # deliberately not logged: patients may type personal details into it.
        logger.exception("Knowledge base query failed")
        raise HTTPException(
            status_code=503,
            detail="The knowledge base is temporarily unavailable. Please try again in a moment.",
        )
    return KnowledgeQueryResponse(answer=answer)