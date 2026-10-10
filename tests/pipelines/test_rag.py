"""Unit tests for the RAG pipeline (data/process/rag.py and data/pipelines/rag.py).

Everything external is mocked: no network calls, no Qdrant server and no API key needed.
Run from the repository root:

    uv run --project services/api python -m pytest tests/pipelines/test_rag.py -v
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import httpx
import pytest

from data.pipelines import rag as pipeline
from data.process import rag as indexing

FAKE_VECTOR = [0.1, 0.2, 0.3]


# --- Helpers -------------------------------------------------------------------
def make_response(status_code: int, body: dict | None = None, headers: dict | None = None) -> httpx.Response:
    """A real httpx.Response (so raise_for_status works) without any network call."""
    return httpx.Response(
        status_code,
        json=body if body is not None else {},
        headers=headers or {},
        request=httpx.Request("POST", "https://gateway.test/v1/endpoint"),
    )


def embedding_response(vector=FAKE_VECTOR) -> httpx.Response:
    return make_response(200, {"data": [{"embedding": vector}]})


def chat_response(content: str | None) -> httpx.Response:
    return make_response(200, {"choices": [{"message": {"content": content}}]})


def make_chunk(text: str = "[Doc / Section]\nSome policy text.", score: float = 0.8) -> dict:
    return {
        "company": "healthcore",
        "source_document": "appointment-policy",
        "section": "Cancellation policy",
        "language": "en",
        "chunk_index": 1,
        "text": text,
        "score": score,
    }


@pytest.fixture(autouse=True)
def llm_env(monkeypatch):
    monkeypatch.setenv("LLM_BASE_URL", "https://gateway.test")
    monkeypatch.setenv("LLM_API_KEY", "test-key")
    monkeypatch.setenv("EMBEDDING_MODEL", "embedding-model")
    monkeypatch.setenv("GENERATION_MODEL", "generation-model")
    monkeypatch.setattr(indexing.time, "sleep", lambda seconds: None)  # never really wait


# --- Chunking ------------------------------------------------------------------
class TestChunking:
    def test_covers_the_four_source_documents(self):
        chunks = indexing.build_chunks()
        assert {c["source_document"] for c in chunks} == set(indexing.SOURCE_DOCUMENTS.values())
        assert len(chunks) == 14

    def test_every_chunk_has_the_required_payload(self):
        required = {"company", "source_document", "section", "language", "chunk_index", "text"}
        for chunk in indexing.build_chunks():
            assert required <= chunk.keys()
            assert chunk["company"] == "healthcore"
            assert chunk["language"] == "en"
            assert chunk["text"].startswith("[")  # self-contained header

    def test_point_ids_are_unique_and_deterministic(self):
        first = [indexing._point_id(c) for c in indexing.build_chunks()]
        second = [indexing._point_id(c) for c in indexing.build_chunks()]
        assert first == second
        assert len(set(first)) == len(first)

    def test_missing_document_raises_a_clear_error(self, tmp_path):
        with pytest.raises(FileNotFoundError, match="Missing source document"):
            indexing.build_chunks(tmp_path)


# --- embed() -------------------------------------------------------------------
class TestEmbed:
    def test_returns_the_vector_from_the_api(self, monkeypatch):
        post = MagicMock(return_value=embedding_response())
        monkeypatch.setattr(indexing.httpx, "post", post)

        assert indexing.embed("hello") == FAKE_VECTOR
        call = post.call_args
        assert call.args[0] == "https://gateway.test/v1/embeddings"
        assert call.kwargs["json"] == {"model": "embedding-model", "input": "hello"}
        assert call.kwargs["headers"]["Authorization"] == "Bearer test-key"

    @pytest.mark.parametrize("text", ["", "   ", None])
    def test_rejects_empty_text(self, text):
        with pytest.raises(ValueError):
            indexing.embed(text)

    def test_retries_on_rate_limit_then_succeeds(self, monkeypatch):
        post = MagicMock(side_effect=[make_response(429), make_response(429), embedding_response()])
        monkeypatch.setattr(indexing.httpx, "post", post)

        assert indexing.embed("hello") == FAKE_VECTOR
        assert post.call_count == 3

    def test_honors_retry_after_header(self, monkeypatch):
        post = MagicMock(side_effect=[make_response(429, headers={"retry-after": "7"}), embedding_response()])
        sleep = MagicMock()
        monkeypatch.setattr(indexing.httpx, "post", post)
        monkeypatch.setattr(indexing.time, "sleep", sleep)

        indexing.embed("hello")
        sleep.assert_called_once_with(7.0)

    def test_gives_up_after_the_maximum_number_of_retries(self, monkeypatch):
        post = MagicMock(return_value=make_response(429))
        monkeypatch.setattr(indexing.httpx, "post", post)

        with pytest.raises(httpx.HTTPStatusError):
            indexing.embed("hello")
        assert post.call_count == indexing.EMBED_MAX_RETRIES + 1

    def test_does_not_retry_client_errors(self, monkeypatch):
        post = MagicMock(return_value=make_response(400))
        monkeypatch.setattr(indexing.httpx, "post", post)

        with pytest.raises(httpx.HTTPStatusError):
            indexing.embed("hello")
        assert post.call_count == 1

    def test_rejects_non_numeric_embeddings(self, monkeypatch):
        monkeypatch.setattr(indexing.httpx, "post", MagicMock(return_value=embedding_response("bm90LWEtdmVjdG9y")))
        with pytest.raises(RuntimeError, match="did not return a list of numbers"):
            indexing.embed("hello")

    def test_requires_key_and_model(self, monkeypatch):
        monkeypatch.delenv("EMBEDDING_MODEL")
        with pytest.raises(RuntimeError, match="EMBEDDING_MODEL"):
            indexing.embed("hello")


# --- setup() -------------------------------------------------------------------
class TestSetup:
    def _run_setup(self, monkeypatch, collection_exists: bool):
        client = MagicMock()
        client.collection_exists.return_value = collection_exists
        monkeypatch.setattr(indexing, "embed", lambda text: FAKE_VECTOR)
        monkeypatch.setattr(indexing, "get_qdrant_client", lambda: client)
        return indexing.setup(), client

    def test_creates_the_collection_and_loads_every_chunk(self, monkeypatch):
        summary, client = self._run_setup(monkeypatch, collection_exists=False)

        client.delete_collection.assert_not_called()
        create = client.create_collection.call_args.kwargs
        assert create["collection_name"] == "healthcore_knowledge"
        assert create["vectors_config"].size == len(FAKE_VECTOR)
        points = client.upsert.call_args.kwargs["points"]
        assert len(points) == summary["total_chunks"] == 14

    def test_rerun_drops_the_old_collection_first(self, monkeypatch):
        _, client = self._run_setup(monkeypatch, collection_exists=True)
        client.delete_collection.assert_called_once_with("healthcore_knowledge")

    def test_rerun_produces_the_same_point_ids(self, monkeypatch):
        _, first = self._run_setup(monkeypatch, collection_exists=False)
        _, second = self._run_setup(monkeypatch, collection_exists=True)
        ids = lambda client: [p.id for p in client.upsert.call_args.kwargs["points"]]
        assert ids(first) == ids(second)

    def test_embedding_failure_leaves_the_existing_collection_untouched(self, monkeypatch):
        client = MagicMock()
        monkeypatch.setattr(indexing, "embed", MagicMock(side_effect=RuntimeError("API down")))
        monkeypatch.setattr(indexing, "get_qdrant_client", lambda: client)

        with pytest.raises(RuntimeError):
            indexing.setup()
        client.delete_collection.assert_not_called()


# --- retrieve() ----------------------------------------------------------------
class TestRetrieve:
    def _patch(self, monkeypatch, points):
        client = MagicMock()
        client.query_points.return_value = SimpleNamespace(points=points)
        embed = MagicMock(return_value=FAKE_VECTOR)
        monkeypatch.setattr(pipeline, "embed", embed)
        monkeypatch.setattr(pipeline, "get_qdrant_client", lambda: client)
        return client, embed

    def test_returns_payload_plus_score_in_order(self, monkeypatch):
        points = [
            SimpleNamespace(score=0.91234, payload={"source_document": "a", "text": "A"}),
            SimpleNamespace(score=0.5, payload={"source_document": "b", "text": "B"}),
        ]
        self._patch(monkeypatch, points)

        results = pipeline.retrieve("question", k=2, min_score=0.3)
        assert results == [
            {"source_document": "a", "text": "A", "score": 0.9123},
            {"source_document": "b", "text": "B", "score": 0.5},
        ]

    def test_embeds_the_question_and_passes_k_and_threshold_to_qdrant(self, monkeypatch):
        client, embed = self._patch(monkeypatch, [])

        pipeline.retrieve("my question", k=4, min_score=0.33)

        embed.assert_called_once_with("my question")
        kwargs = client.query_points.call_args.kwargs
        assert kwargs["collection_name"] == "healthcore_knowledge"
        assert kwargs["query"] == FAKE_VECTOR
        assert kwargs["limit"] == 4
        assert kwargs["score_threshold"] == 0.33

    def test_uses_the_default_threshold_and_top_k(self, monkeypatch):
        client, _ = self._patch(monkeypatch, [])

        pipeline.retrieve("question")

        kwargs = client.query_points.call_args.kwargs
        assert kwargs["limit"] == pipeline.DEFAULT_TOP_K
        assert kwargs["score_threshold"] == pipeline.DEFAULT_MIN_SCORE

    def test_nothing_above_the_threshold_returns_an_empty_list(self, monkeypatch):
        self._patch(monkeypatch, [])
        assert pipeline.retrieve("What is the capital of France?") == []

    @pytest.mark.parametrize("bad_query", ["", "   ", None])
    def test_rejects_empty_queries(self, bad_query):
        with pytest.raises(ValueError):
            pipeline.retrieve(bad_query)

    def test_rejects_invalid_k(self):
        with pytest.raises(ValueError):
            pipeline.retrieve("question", k=0)


# --- generate_answer() ---------------------------------------------------------
class TestGenerateAnswer:
    def test_empty_context_refuses_without_calling_the_model(self, monkeypatch):
        post = MagicMock()
        monkeypatch.setattr(pipeline.httpx, "post", post)

        assert pipeline.generate_answer("Anything?", []) == pipeline.NO_INFO_MESSAGE
        post.assert_not_called()

    def test_sends_rules_context_and_question_to_the_generation_model(self, monkeypatch):
        post = MagicMock(return_value=chat_response("  No fee for Medicare patients.  "))
        monkeypatch.setattr(pipeline.httpx, "post", post)
        context = [make_chunk("[Policy / Cancellation]\nMedicare: no fee."), make_chunk("[Policy / Reminders]\n48h.")]

        answer = pipeline.generate_answer("Do I pay a fee?", context)

        assert answer == "No fee for Medicare patients."
        call = post.call_args
        assert call.args[0] == "https://gateway.test/v1/chat/completions"
        body = call.kwargs["json"]
        assert body["model"] == "generation-model"
        system, user = body["messages"]
        assert system["role"] == "system" and system["content"] == pipeline.SYSTEM_PROMPT
        assert "Medicare: no fee." in user["content"] and "48h." in user["content"]
        assert "Do I pay a fee?" in user["content"]

    def test_system_prompt_keeps_the_business_rules(self):
        prompt = pipeline.SYSTEM_PROMPT
        assert "ONLY" in prompt  # answer from the context only
        assert "billing" in prompt  # unlisted insurer -> verify with billing
        assert "United States" in prompt and "United Kingdom" in prompt
        assert "Medicare" in prompt  # never a no-show fee for Medicare/Medicaid
        assert "Never offer to book" in prompt  # the assistant cannot perform actions

    def test_blank_model_answer_falls_back_to_the_refusal(self, monkeypatch):
        monkeypatch.setattr(pipeline.httpx, "post", MagicMock(return_value=chat_response("   ")))
        assert pipeline.generate_answer("Question?", [make_chunk()]) == pipeline.NO_INFO_MESSAGE

    def test_http_errors_are_not_swallowed(self, monkeypatch):
        monkeypatch.setattr(pipeline.httpx, "post", MagicMock(return_value=make_response(500)))
        with pytest.raises(httpx.HTTPStatusError):
            pipeline.generate_answer("Question?", [make_chunk()])

    def test_rejects_an_empty_question(self):
        with pytest.raises(ValueError):
            pipeline.generate_answer("  ", [make_chunk()])

    def test_requires_a_generation_model(self, monkeypatch):
        monkeypatch.delenv("GENERATION_MODEL")
        with pytest.raises(RuntimeError, match="GENERATION_MODEL"):
            pipeline.generate_answer("Question?", [make_chunk()])

    def test_generation_model_must_differ_from_the_embedding_model(self, monkeypatch):
        monkeypatch.setenv("GENERATION_MODEL", "embedding-model")
        with pytest.raises(RuntimeError, match="different model"):
            pipeline.generate_answer("Question?", [make_chunk()])


# --- query() -------------------------------------------------------------------
class TestQuery:
    def test_is_retrieve_followed_by_generate_answer(self, monkeypatch):
        chunks = [make_chunk()]
        retrieve = MagicMock(return_value=chunks)
        generate = MagicMock(return_value="The answer.")
        monkeypatch.setattr(pipeline, "retrieve", retrieve)
        monkeypatch.setattr(pipeline, "generate_answer", generate)

        assert pipeline.query("Question?", k=2, min_score=0.4) == "The answer."
        retrieve.assert_called_once_with("Question?", k=2, min_score=0.4)
        generate.assert_called_once_with("Question?", chunks)

    def test_nothing_relevant_gives_the_refusal_and_no_model_call(self, monkeypatch):
        monkeypatch.setattr(pipeline, "retrieve", MagicMock(return_value=[]))
        post = MagicMock()
        monkeypatch.setattr(pipeline.httpx, "post", post)

        assert pipeline.query("What is the capital of France?") == pipeline.NO_INFO_MESSAGE
        post.assert_not_called()