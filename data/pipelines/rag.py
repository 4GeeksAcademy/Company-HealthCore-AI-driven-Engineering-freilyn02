"""RAG retrieval and answer generation for HealthCore's knowledge base.

Three functions, kept separate on purpose so a LangGraph agent can reuse them as
independent nodes later:

  - ``retrieve(query)``: embed the question and return the closest chunks from Qdrant.
  - ``generate_answer(question, context)``: ask the generation model to answer using
    ONLY the given chunks.
  - ``query(question)``: ``retrieve()`` + ``generate_answer()``.

Indexing (chunking, embeddings, collection setup) lives in ``data/process/rag.py``.
"""

from __future__ import annotations

import argparse
import os

import httpx
from dotenv import load_dotenv

from data.process.rag import COLLECTION_NAME, embed, get_qdrant_client

load_dotenv()

# --- Retrieval settings -------------------------------------------------------
# Recall@3 is the target metric, and the knowledge base is small (14 chunks), so 3 chunks
# are enough to cover a question and keep the prompt focused.
DEFAULT_TOP_K = 3

# Minimum cosine similarity for a chunk to count as relevant. Chunks below it are dropped,
# and if nothing is left the system refuses to answer instead of guessing.
# Calibrated with data/eval/evaluate_retrieval.py: off-topic questions score at most 0.08 and the
# weakest correct chunk scores 0.28, so 0.25 sits in between. Override with RAG_MIN_SCORE.
DEFAULT_MIN_SCORE = float(os.getenv("RAG_MIN_SCORE", "0.25"))

# Returned when no chunk is relevant enough. No model call is made in that case.
NO_INFO_MESSAGE = (
    "I'm sorry, I don't have reliable information about that in HealthCore's "
    "knowledge base. Please contact a HealthCore coordinator and they will be happy "
    "to help you directly."
)

SYSTEM_PROMPT = """\
You are the virtual assistant of HealthCore's patient coordination team. You speak \
like a warm, professional coordinator: empathetic, clear and reassuring, always \
helping the patient feel supported.

Rules you must always follow:
1. Answer ONLY with information found in the CONTEXT below. Never use outside \
knowledge and never invent coverage, prices, fees, deadlines or policies.
2. If the CONTEXT does not contain the answer, say so honestly and suggest contacting \
a HealthCore coordinator. Do not guess.
3. If the question is about an insurer that is not listed in the CONTEXT, do not \
confirm or deny coverage. Explain that coverage must be verified with the billing team.
4. Policies differ between the United States and the United Kingdom (currencies, \
Medicare/Medicaid versus NHS, and so on). If the answer depends on the country and the \
patient did not say which one, do not assume: briefly cover both cases or ask which \
clinic or country they mean.
5. Never charge or mention a no-show fee as applying to Medicare or Medicaid patients.
6. Do not ask for or repeat personal health information (diagnoses, member IDs, \
documents). If the patient shares some, gently tell them it is not needed to answer.
7. Keep the answer short (2 to 5 sentences), in plain language. Do not mention the \
CONTEXT or its labels.
8. Reply in the same language as the question.
9. You can only provide information. Never offer to book, cancel, call, transfer or verify anything for the patient; tell them who to contact instead.
"""


# =============================================================================
# Retrieval
# =============================================================================
def retrieve(
    query: str,
    *,
    k: int = DEFAULT_TOP_K,
    min_score: float | None = None,
) -> list[dict]:
    """Return up to `k` chunks whose cosine similarity to `query` is >= `min_score`.

    Each result is the chunk payload (company, source_document, section, language,
    chunk_index, text) plus a ``score`` key, sorted from most to least similar.
    An empty list means nothing in the knowledge base is relevant enough.
    """
    if not query or not query.strip():
        raise ValueError("retrieve() needs a non-empty query.")
    if k < 1:
        raise ValueError("k must be at least 1.")

    threshold = DEFAULT_MIN_SCORE if min_score is None else min_score

    # The question is embedded with the same function used to index the chunks.
    vector = embed(query)
    response = get_qdrant_client().query_points(
        collection_name=COLLECTION_NAME,
        query=vector,
        limit=k,
        score_threshold=threshold,
        with_payload=True,
    )
    return [{**(point.payload or {}), "score": round(point.score, 4)} for point in response.points]


# =============================================================================
# Generation
# =============================================================================
def _generation_settings() -> tuple[str, str, str]:
    base_url = os.getenv("LLM_BASE_URL", "https://llm.4geeks.ai").rstrip("/")
    api_key = os.getenv("LLM_API_KEY")
    model = os.getenv("GENERATION_MODEL")
    if not api_key or not model:
        raise RuntimeError("Set LLM_API_KEY and GENERATION_MODEL in your .env file.")
    if model == os.getenv("EMBEDDING_MODEL"):
        raise RuntimeError("GENERATION_MODEL must be a different model from EMBEDDING_MODEL.")
    return base_url, api_key, model


def _format_context(context: list[dict]) -> str:
    """Join the retrieved chunks into one block for the prompt."""
    return "\n\n---\n\n".join(chunk["text"] for chunk in context)


def generate_answer(question: str, context: list[dict]) -> str:
    """Answer `question` using only the retrieved `context` chunks.

    With an empty context it returns an honest refusal without calling the model,
    so nothing can be invented when the knowledge base has no relevant information.
    """
    if not question or not question.strip():
        raise ValueError("generate_answer() needs a non-empty question.")
    if not context:
        return NO_INFO_MESSAGE

    base_url, api_key, model = _generation_settings()
    response = httpx.post(
        f"{base_url}/v1/chat/completions",
        headers={"Authorization": f"Bearer {api_key}"},
        json={
            "model": model,
            "temperature": 0.2,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": f"CONTEXT:\n{_format_context(context)}\n\nQUESTION:\n{question.strip()}",
                },
            ],
        },
        timeout=60.0,
    )
    response.raise_for_status()
    answer = response.json()["choices"][0]["message"]["content"]
    return (answer or "").strip() or NO_INFO_MESSAGE


# =============================================================================
# Full pipeline
# =============================================================================
def query(
    question: str,
    *,
    k: int = DEFAULT_TOP_K,
    min_score: float | None = None,
) -> str:
    """Retrieve the relevant chunks and generate the final answer."""
    context = retrieve(question, k=k, min_score=min_score)
    return generate_answer(question, context)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Ask the HealthCore knowledge base.")
    parser.add_argument("question")
    parser.add_argument("-k", type=int, default=DEFAULT_TOP_K)
    parser.add_argument("--min-score", type=float, default=None)
    args = parser.parse_args()

    chunks = retrieve(args.question, k=args.k, min_score=args.min_score)
    print(f"Retrieved {len(chunks)} chunk(s):")
    for chunk in chunks:
        print(f"  {chunk['score']:.4f}  {chunk['source_document']} / {chunk['section']}")
    print("\nAnswer:")
    print(generate_answer(args.question, chunks))