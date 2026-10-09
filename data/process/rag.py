"""RAG data preparation and indexing for HealthCore's knowledge base.

Responsibilities of this module (and nothing else):
  - ``build_chunks()``: read the source documents and split them into semantic chunks.
  - ``embed()``: turn text into a vector with a dedicated embeddings model.
  - ``setup()``: embed every chunk and load it into the Qdrant collection.

Retrieval and answer generation live in ``data/pipelines/rag.py``.
"""

from __future__ import annotations

import os
import re
import uuid
from pathlib import Path

import httpx
from dotenv import load_dotenv
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, PointStruct, VectorParams

load_dotenv()

# --- Values that come from CONTEXT-company.md (do not change) -----------------
COMPANY = "healthcore"
LANGUAGE = "en"
COLLECTION_NAME = "healthcore_knowledge"

# file name -> stable `source_document` id defined in CONTEXT-company.md
SOURCE_DOCUMENTS: dict[str, str] = {
    "healthcore-insurance-coverage.en.md": "insurance-coverage",
    "healthcore-appointment-policy.en.md": "appointment-policy",
    "healthcore-referral-process.en.md": "referral-process",
    "healthcore-new-patient-checklist.en.md": "new-patient-checklist",
}

# <repo root>/docs/company-knowledge-base  (this file is <repo root>/data/process/rag.py)
KNOWLEDGE_BASE_DIR = Path(__file__).resolve().parents[2] / "docs" / "company-knowledge-base"

# --- Chunking settings --------------------------------------------------------
# A block shorter than this is an intro line (e.g. "HealthCore accepts ... :"),
# so it is merged into the block that follows it instead of becoming its own chunk.
MIN_BLOCK_CHARS = 120

# Readable section names (used in `section` and in citations) for blocks whose first line
# is not a good title.
# Key: (source_document, index of the main block). Blocks are the blank-line separated
# groups of a file, counted from 0 and excluding the "# Title" line. An intro block that
# is merged into the next one does not get its own entry: use the index of the main block.
SECTION_OVERRIDES: dict[tuple[str, int], str] = {
    ("insurance-coverage", 3): "Unlisted insurers: verify with billing",
    ("appointment-policy", 3): "Flag for 3 no-shows in 6 months",
    ("referral-process", 1): "Standard referral process",
    ("referral-process", 3): "Escalation after 5 business days",
    ("referral-process", 4): "Referrals outside the HealthCore network",
    ("new-patient-checklist", 1): "Requirements before the first appointment",
    ("new-patient-checklist", 3): "Incomplete medical history form",
}

_LIST_ITEM = re.compile(r"^(?:-\s|\d+\.\s)")


# =============================================================================
# Chunking
# =============================================================================
def _unwrap(block: str) -> str:
    """Join hard-wrapped lines, but keep each list item ("- ..." or "1. ...") on its own line."""
    lines: list[str] = []
    for raw_line in block.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if not lines or _LIST_ITEM.match(line):
            lines.append(line)
        else:
            lines[-1] += " " + line
    return "\n".join(lines)


def _section_title(block: str, max_len: int = 80) -> str:
    """Derive a short section name from the first line of a block."""
    first_line = block.splitlines()[0]
    label = re.match(rf"^(.{{1,{max_len}}}?):(?:\s|$)", first_line)
    if label:
        return label.group(1)
    first_sentence = re.split(r"(?<=[.!?])\s", first_line, maxsplit=1)[0].rstrip(".")
    if len(first_sentence) <= max_len:
        return first_sentence
    return first_sentence[:max_len].rsplit(" ", 1)[0] + "…"


def _split_document(markdown: str, source_document: str) -> list[dict]:
    """Split one markdown file into semantic chunks (one per logical block)."""
    raw_lines = markdown.strip().splitlines()
    doc_title = raw_lines[0].lstrip("# ").strip()
    body = "\n".join(raw_lines[1:])

    blocks = [_unwrap(b) for b in re.split(r"\n\s*\n", body) if b.strip()]

    # Merge short intro blocks into the block that follows them.
    merged: list[tuple[int, str, str]] = []  # (main block index, section, text)
    pending_intro = ""
    for index, block in enumerate(blocks):
        has_next = index < len(blocks) - 1
        is_short = len(block) < MIN_BLOCK_CHARS
        # An intro line ending in ":" that is followed by a list belongs with that list.
        introduces_list = block.endswith(":") and has_next and _LIST_ITEM.match(blocks[index + 1])
        if has_next and (is_short or introduces_list):
            pending_intro += block + "\n"
            continue
        section = SECTION_OVERRIDES.get((source_document, index)) or _section_title(block)
        merged.append((index, section, pending_intro + block))
        pending_intro = ""
    if pending_intro:  # a short block at the very end joins the previous chunk
        index, section, text = merged[-1]
        merged[-1] = (index, section, text + "\n" + pending_intro.strip())

    chunks = []
    for chunk_index, (_, section, text) in enumerate(merged):
        chunks.append(
            {
                "company": COMPANY,
                "source_document": source_document,
                "section": section,
                "language": LANGUAGE,
                "chunk_index": chunk_index,  # ordinal within the document
                # The header makes every chunk self-contained for retrieval and for the prompt.
                "text": f"[{doc_title} / {section}]\n{text}",
            }
        )
    return chunks


def build_chunks(knowledge_base_dir: Path = KNOWLEDGE_BASE_DIR) -> list[dict]:
    """Read the four source documents and return all chunks (no network calls)."""
    chunks: list[dict] = []
    for file_name, source_document in SOURCE_DOCUMENTS.items():
        path = knowledge_base_dir / file_name
        if not path.exists():
            raise FileNotFoundError(
                f"Missing source document: {path}. Copy it from "
                "00-general-contexts/healthcore/ into docs/company-knowledge-base/."
            )
        chunks.extend(_split_document(path.read_text(encoding="utf-8"), source_document))
    return chunks


# =============================================================================
# Embeddings
# =============================================================================
def _llm_settings() -> tuple[str, str, str]:
    base_url = os.getenv("LLM_BASE_URL", "https://llm.4geeks.ai").rstrip("/")
    api_key = os.getenv("LLM_API_KEY")
    model = os.getenv("EMBEDDING_MODEL")
    if not api_key or not model:
        raise RuntimeError("Set LLM_API_KEY and EMBEDDING_MODEL in your .env file.")
    return base_url, api_key, model


def embed(text: str) -> list[float]:
    """Return the embedding vector of `text`.

    The same function is used to index chunks and to embed user questions, so both
    live in the same vector space. It always uses EMBEDDING_MODEL, which must be a
    different model from the one used for generation.
    """
    if not text or not text.strip():
        raise ValueError("embed() needs a non-empty text.")

    base_url, api_key, model = _llm_settings()
    response = httpx.post(
        f"{base_url}/v1/embeddings",
        headers={"Authorization": f"Bearer {api_key}"},
        json={"model": model, "input": text},
        timeout=30.0,
    )
    response.raise_for_status()
    vector = response.json()["data"][0]["embedding"]
    if not isinstance(vector, list) or not all(isinstance(x, (int, float)) for x in vector):
        raise RuntimeError(
            "The embeddings endpoint did not return a list of numbers "
            "(some models return base64). Check the EMBEDDING_MODEL setting."
        )
    return vector


# =============================================================================
# Indexing
# =============================================================================
def get_qdrant_client() -> QdrantClient:
    return QdrantClient(url=os.getenv("QDRANT_URL", "http://localhost:6333"))


def _point_id(chunk: dict) -> str:
    """Deterministic id: the same chunk always gets the same id (idempotent re-runs)."""
    key = f"{chunk['company']}|{chunk['source_document']}|{chunk['section']}|{chunk['chunk_index']}"
    return str(uuid.uuid5(uuid.NAMESPACE_URL, key))


def setup() -> dict:
    """Build the knowledge base: chunk -> embed -> (re)create collection -> upsert.

    Idempotent strategy: "clean and reload" + deterministic point ids. Running it
    again drops the collection and loads the same points, so nothing is duplicated
    and chunks removed from the documents do not linger in the index.
    """
    chunks = build_chunks()

    # Embed first: if the embeddings API fails, the existing collection is untouched.
    vectors = [embed(chunk["text"]) for chunk in chunks]
    vector_size = len(vectors[0])

    client = get_qdrant_client()
    if client.collection_exists(COLLECTION_NAME):
        client.delete_collection(COLLECTION_NAME)
    client.create_collection(
        collection_name=COLLECTION_NAME,
        vectors_config=VectorParams(size=vector_size, distance=Distance.COSINE),
    )

    points = [
        PointStruct(id=_point_id(chunk), vector=vector, payload=chunk)
        for chunk, vector in zip(chunks, vectors)
    ]
    client.upsert(collection_name=COLLECTION_NAME, points=points, wait=True)

    per_document: dict[str, int] = {}
    for chunk in chunks:
        per_document[chunk["source_document"]] = per_document.get(chunk["source_document"], 0) + 1
    return {
        "collection": COLLECTION_NAME,
        "total_chunks": len(points),
        "vector_size": vector_size,
        "chunks_per_document": per_document,
    }


if __name__ == "__main__":
    print(setup())