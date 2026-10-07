# Message Queues and Async Tasks (Ticket #DEV-55)

## Overview

`POST /api/incidents/summary` used to compute the full incidents
aggregation (grouped by status, category, origin, and branch) synchronously,
inside the request/response cycle. This project moves that work off the
request path using Celery + Redis, so the endpoint returns immediately and
the client polls for the result.

**Why this endpoint:** it's the only one in the API that performs a full
table scan and in-memory aggregation across four dimensions
(`incidents_table.all()` + four grouping passes), as opposed to the other
endpoints, which look up or write a single record. As incident volume
grows, this is the endpoint most likely to become a bottleneck.

## Architecture

Client --POST--> FastAPI (enqueues task) --> Redis (broker + result backend)
| |
returns 202 Celery worker
+ task_id (separate process)
|
Client --GET /tasks/{id}--> FastAPI --queries--> Redis (result backend)


- **Broker + result backend:** Redis (`redis://localhost:6379/0` outside
  Docker, `redis://redis:6379/0` between containers)
- **Worker:** runs as its own process, never started from FastAPI's
  lifespan or a background thread
- **Monitoring:** Flower, on port `5555`
- **Dead Letter Queue:** `dlq_tasks` table in Supabase (Postgres), written
  only when a task exhausts all of its retries

## Running it locally

You need **3 separate processes** running at the same time:

### 1. Redis + Flower (Docker)

From the repo root:
```bash
docker compose up redis flower
```
Redis: `localhost:6379`. Flower dashboard: `http://localhost:5555`.

### 2. The API

```bash
cd services/api
uv run uvicorn main:app --reload
```

### 3. The Celery worker

```bash
cd services/api
uv run celery -A celery_app worker --loglevel=info --pool=solo
```

> **Windows note:** `--pool=solo` is required. Celery's default pool
> (`prefork`) relies on `fork()`, which isn't natively available on
> Windows, and the worker will fail to process tasks without this flag.

**Stopping the worker does not drain or lose queued tasks** — Redis
persists the queue to disk (RDB snapshots), so any task enqueued while the
worker was down gets picked up as soon as it restarts.

## Environment variables

Add to `services/api/.env`:

REDIS_URL=redis://localhost:6379/0
DATABASE_URL=<your Supabase Postgres connection string>


`celery_app.py` calls `load_dotenv()` itself — the worker process starts
directly from that module and never goes through `main.py`'s import chain
(which is what normally triggers `.env` loading via `app/core/security.py`).

## Endpoint contract

### `POST /api/incidents/summary`

Enqueues the aggregation and returns immediately:
```json
HTTP/1.1 202 Accepted
{"task_id": "a1b2c3d4-..."}
```

> This was originally a `GET` endpoint. It was changed to `POST` because
> triggering a background task is a side effect, not a safe/idempotent
> read — `GET` endpoints shouldn't have side effects per REST convention.

### `GET /tasks/{task_id}`

Polls the task status:
```json
{"task_id": "a1b2c3d4-...", "status": "pending", "result": null}
{"task_id": "a1b2c3d4-...", "status": "started", "result": null}
{"task_id": "a1b2c3d4-...", "status": "success", "result": {"by_status": {...}, "by_category": {...}, "by_origin": {...}, "by_branch": {...}}}
{"task_id": "a1b2c3d4-...", "status": "failure", "result": "<error message>"}
```

Celery's internal states (`PENDING`, `STARTED`, `SUCCESS`, `FAILURE`) are
mapped to lowercase contract values — the raw Celery state names are never
returned to the client.

## Retries and the Dead Letter Queue

- `max_retries=3`, exponential backoff: 10s → 20s → 40s between attempts.
- After the 4th attempt (the 3 retries plus the original) still fails, a
  row is written to `dlq_tasks` in Supabase — `task_id`, `task_name`,
  `attempt`, `error_message`, `created_at`.
- **Implementation detail:** the retry/DLQ branching is decided by
  comparing `self.request.retries >= self.max_retries` directly, rather
  than catching `celery.exceptions.MaxRetriesExceededError`. When
  `self.retry(exc=exc, ...)` is called with an `exc` argument (needed here
  to preserve the real error message), Celery re-raises that original
  exception on the final attempt instead of raising
  `MaxRetriesExceededError` — so a `try/except MaxRetriesExceededError`
  around it would never fire. This was found and fixed during manual
  testing of the retry/DLQ flow (see PR for the before/after logs).

## Logging

Every task execution logs:

task_id=<uuid> attempt=<n> status=<success|failure> duration_ms=<ms>

Failures additionally log `error=<message>`.

## Known issues

- **Clock drift warning in Flower:** `Substantial drift from
  celery@<host>... Current drift is 14400 seconds` can appear after the
  Windows machine wakes from sleep — it's a Docker Desktop/WSL2 clock sync
  issue, not an application bug. Restarting Docker Desktop resolves it.