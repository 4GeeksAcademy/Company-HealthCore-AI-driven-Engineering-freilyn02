# RAG Design: HealthCore Knowledge Base

This document explains how the HealthCore knowledge base assistant works: how the
documents are chunked, how embeddings are produced, how relevant chunks are retrieved,
how answers are generated, and why each value was chosen.

## 1. What the system does

Patient coordinators ask questions in natural language ("Will I be charged a no-show fee
if I am on Medicare?"). The system answers **only** from four internal documents and
refuses honestly when the documents do not contain the answer.

| Source document         | Topic                                                                            |
| ----------------------- | -------------------------------------------------------------------------------- |
| `insurance-coverage`    | Accepted insurers in the US and the UK, and what to do with unlisted insurers    |
| `appointment-policy`    | Booking, cancellation, reminders, no-show fees and the no-show flag              |
| `referral-process`      | Standard referral steps, target times, escalation, referrals outside the network |
| `new-patient-checklist` | What a new patient needs before and on the day of the first appointment          |

The documents live in `docs/company-knowledge-base/` (English versions, `*.en.md`).

## 2. The RAG process

```
INDEXING (data/process/rag.py, run once or whenever the documents change)

  4 documents -> chunking -> embed() -> Qdrant collection "healthcore_knowledge"

QUERYING (data/pipelines/rag.py)

  question -> embed() -> retrieve() -> generate_answer() -> answer
                         top 3 chunks     (only from the chunks)
                         with min_score
```

The code is split into separate functions on purpose, because a later LangGraph agent
will reuse them as independent nodes:

| Function                             | File                    | Job                                                      |
| ------------------------------------ | ----------------------- | -------------------------------------------------------- |
| `build_chunks()`                     | `data/process/rag.py`   | Read the documents and split them into chunks            |
| `embed(text)`                        | `data/process/rag.py`   | Turn text into a 1024-dimensional vector                 |
| `setup()`                            | `data/process/rag.py`   | Create the Qdrant collection and load all chunks         |
| `retrieve(query, k, min_score)`      | `data/pipelines/rag.py` | Return the closest chunks with their scores              |
| `generate_answer(question, context)` | `data/pipelines/rag.py` | Ask the generation model to answer using only the chunks |
| `query(question)`                    | `data/pipelines/rag.py` | `retrieve()` followed by `generate_answer()`             |

No orchestration framework (LangChain, LlamaIndex) is used. Everything is plain Python
plus direct HTTP calls to the LLM gateway and the Qdrant client.

The API exposes `query()` as `POST /knowledge/query`. The request is
`{"question": "..."}` and the response is only `{"answer": "..."}`. The question must not
be blank and is limited to 500 characters.

## 3. Chunking strategy

**Strategy: semantic chunking, one chunk per self-contained section.**

Each document is split on blank lines into blocks, and every block becomes one chunk
that keeps its section title. This gives 14 chunks:

| Document                | Chunks                                                                                                       |
| ----------------------- | ------------------------------------------------------------------------------------------------------------ |
| `insurance-coverage`    | 3: US (Texas, Florida, Georgia), UK (London and Manchester), unlisted insurers                               |
| `appointment-policy`    | 4: booking, cancellation policy, automated reminders, flag for 3 no-shows in 6 months                        |
| `referral-process`      | 4: standard process, target completion time, escalation after 5 business days, referrals outside the network |
| `new-patient-checklist` | 3: requirements before the first appointment, documents to bring, incomplete medical history form            |

**Why not fixed-size windows (for example 500 characters with overlap)?**

- The documents are short and already organized in sections that each answer one kind of
  question. A fixed window can cut a rule away from its exception, for example the
  no-show fee from the Medicare/Medicaid exemption. The assistant must never mention a
  fee for Medicare patients, so splitting those two sentences would be dangerous.
- Whole sections keep their meaning, so a retrieved chunk can be read and used on its own.
- With only 14 chunks, retrieving 3 of them covers a question without flooding the prompt.

**Metadata stored with every chunk** (the Qdrant payload): `company`, `source_document`,
`section`, `language`, `chunk_index` and `text`. The source document and section make
every answer traceable back to the original file.

**Idempotent loading.** Point ids are deterministic (`uuid5` of document and chunk index)
and `setup()` deletes and recreates the collection before loading. Running it twice gives
exactly the same 14 points, never duplicates.

## 4. Embedding practices

- **Model:** `perplexity/pplx-embed-v1-0.6b` through the course LLM gateway
  (`/v1/embeddings`). It returns 1024-dimensional vectors, and the collection uses
  **cosine** distance.
- **Embedding model is not the generation model.** They are configured separately
  (`EMBEDDING_MODEL` and `GENERATION_MODEL`) and the code raises an error if both are the
  same model.
- **One `embed()` function for indexing and for queries.** A question and a chunk are only
  comparable if the same model produced both vectors, so there is a single code path.
- **Quantized values.** This model returns quantized vectors (values are multiples of
  1/128). Cosine similarity still works well, and the evaluation below confirms it.
- **Retries.** The gateway rate-limits requests (HTTP 429). `embed()` retries on 429, 502,
  503 and 504, up to 5 times. It honors the `Retry-After` header (capped at 60 seconds)
  and otherwise waits `min(2**attempt, 30)` seconds. A 429 appeared during the first full
  evaluation run, which is why this exists.
- **Secrets.** The API key and model names come from environment variables (`.env`,
  ignored by git). Nothing is hard coded.

## 5. Retrieval and the `min_score` threshold

`retrieve()` returns up to **k = 3** chunks whose cosine similarity is at least
`min_score`. If nothing passes the threshold, the answer is a fixed refusal and **the
generation model is not called at all**, so nothing can be invented.

### How `min_score = 0.25` was chosen

A threshold must be calibrated with real scores, not guessed. These are the measured
scores (higher means more similar):

| Group                                                                  | Scores                                             |
| ---------------------------------------------------------------------- | -------------------------------------------------- |
| Correct chunk for each of the 16 evaluation questions                  | from **0.2798** to 0.7743 (14 of 16 are above 0.5) |
| Off-topic questions (capital of France, cake recipe, football, laptop) | 0.0063 to **0.0804**                               |
| In-domain but unanswerable questions (MRI price, dental services)      | 0.1856 and 0.2105                                  |
| In-domain but unanswerable questions (weekend hours, Manchester phone) | 0.3101 and 0.3646                                  |

- A first guess of **0.5** would have thrown away the two weakest correct chunks,
  including the rule for unlisted insurers (score 0.2798). The assistant would have said
  "I don't know" about exactly the case the business rules care about most.
- **0.25** sits above every off-topic score (0.0804) and below every correct chunk
  (0.2798). With it, Recall@3 stays at 100 % and 6 of the 8 out-of-scope questions are
  refused before reaching the model.
- The threshold can be overridden with the `RAG_MIN_SCORE` environment variable.

### Two layers of protection

1. **Score threshold:** removes off-topic noise (the 4 off-topic questions).
2. **System prompt:** handles questions that are about the domain but not covered. The 2
   near-domain questions that pass the threshold (scores 0.31 and 0.36) reach the model,
   which answers that it has no data, because rule 2 forbids guessing.

## 6. Answer generation

`generate_answer(question, context)` sends the chunks and the question to the generation
model (`/v1/chat/completions`, temperature 0.2). The system prompt enforces:

1. Answer only from the context; never invent coverage, prices, fees or deadlines.
2. If the context does not contain the answer, say so and suggest a coordinator.
3. Insurer not listed: do not confirm or deny, verify with the billing team.
4. United States and United Kingdom policies differ. If the country is not stated, cover
   both cases or ask which one.
5. Never mention a no-show fee as applying to Medicare or Medicaid patients.
6. Do not ask for or repeat personal health information.
7. Short answers (2 to 5 sentences), plain language, coordinator tone.
8. Reply in the language of the question.
9. Only provide information: never offer to book, cancel, call, transfer or verify
   anything for the patient. This rule was added after a test where the assistant
   offered to "arrange that check" for an unlisted insurer.

The generation model must be different from the embedding model (see section 4).

## 7. Evaluation

`data/eval/test-queries.json` has **16 questions** that cover all four documents and
every chunk. `data/eval/evaluate_retrieval.py` retrieves the top 3 chunks for each one
and checks that the expected chunk is among them.

| Metric                           | Result                                                         | Target        |
| -------------------------------- | -------------------------------------------------------------- | ------------- |
| Recall@3, ranking only           | 16/16 = **100 %**                                              | at least 80 % |
| Recall@3 with `min_score = 0.25` | 16/16 = **100 %**                                              | at least 80 % |
| Top-1 hits                       | 15/16 (question q04 ranks the expected chunk lower, see below) | informative   |
| Lowest score of a correct chunk  | 0.2798                                                         |               |
| Out-of-scope questions refused   | 6/8                                                            | informative   |

Question q04 (an insurer that is not listed) finds its chunk in the top 3 but not first,
because the US coverage chunk is similar. This is why Recall@3, not Recall@1, is the
target metric, and why the answer is built from three chunks.

Run it with:

```
uv run --project services/api python -m data.eval.evaluate_retrieval
```

It exits with code 1 if recall with the threshold falls below 80 %.

## 8. Operating the system

| Task                                  | Command                                                             |
| ------------------------------------- | ------------------------------------------------------------------- |
| Start Qdrant                          | `docker compose up -d qdrant`                                       |
| Build or rebuild the knowledge base   | `python -m data.process.rag`                                        |
| Ask from the terminal                 | `python -m data.pipelines.rag "your question"`                      |
| Run the API (knowledge endpoint only) | `cd services/api && uv run uvicorn knowledge_app:app --port 8000`   |
| Run the tests                         | `uv run --project services/api python -m pytest tests/pipelines -q` |

Required environment variables (in the root `.env`, never committed): `LLM_BASE_URL`,
`LLM_API_KEY`, `EMBEDDING_MODEL`, `GENERATION_MODEL`, `QDRANT_URL`, and optionally
`RAG_MIN_SCORE`.

Docker containers do not restart on their own after a Codespace restarts, so Qdrant must
be started again with `docker compose up -d qdrant`. The data is kept in the `qdrant_data`
volume.

## 9. Privacy

- No patient data is stored in the documents, the chunks or the evaluation files.
- The endpoint never logs the question text, only that an upstream service failed.
- The interface shows a visible warning not to enter patient-identifying information,
  because the system cannot detect it.

## 10. Known limitations

- **The threshold margin is thin.** There is only 0.03 between the weakest correct chunk
  (0.2798) and the threshold (0.25). Adding or rewriting documents can change scores, so
  the threshold must be recalibrated with `evaluate_retrieval.py` after any document
  change.
- **Near-domain questions can pass the threshold.** Two of the eight out-of-scope
  questions score above 0.25. They rely on the system prompt, not on the score.
- **No reranking and no hybrid search.** With 14 chunks, plain cosine similarity is
  enough. A larger knowledge base would need both.
- **The endpoint is public and has no rate limiting.** It follows the same pattern as the
  incident endpoints. Authentication and rate limiting should be added before exposing it
  outside the internal network.
- **Only the embedding call retries.** If the generation call is rate-limited, the
  endpoint answers 503 and the user must try again.
- **Small evaluation set.** 16 questions are enough to calibrate this knowledge base, but
  they are not a statistical guarantee for new kinds of questions.
