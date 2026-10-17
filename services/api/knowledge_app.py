"""Standalone app that serves ONLY the knowledge base endpoint (POST /knowledge/query).

The full HealthCore API (main.py) needs Supabase, TinyDB and Celery to start. This app does
not: it only needs Qdrant and the LLM gateway, so the RAG feature can be developed, demoed
and tested on its own. It mounts the very same router that main.py mounts.

Run from services/api:

    uv run uvicorn knowledge_app:app --port 8000
"""

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from routers.knowledge import router as knowledge_router

app = FastAPI(title="HealthCore Knowledge API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://localhost:3001"],
    # GitHub Codespaces serves forwarded ports from https://<name>-<port>.app.github.dev
    allow_origin_regex=r"https://.*\.app\.github\.dev",
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(RequestValidationError)
async def validation_error_handler(request: Request, exc: RequestValidationError):
    # Same error shape as the full API (main.py): a single {field, message} with status 400.
    first_error = exc.errors()[0]
    field = ".".join(str(part) for part in first_error["loc"] if part != "body")
    return JSONResponse(
        status_code=400,
        content={"field": field or "body", "message": first_error["msg"]},
    )


app.include_router(knowledge_router)