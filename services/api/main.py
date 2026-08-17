import logging

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from tinydb import Query
from datetime import datetime, timezone

from database import incidents_table
from models import (
    Incident,
    IncidentCreate,
    IncidentStatusUpdate,
    IncidentSummary,
    ValidationErrorBody,
    VALID_STATUS_TRANSITIONS,
)

logger = logging.getLogger(__name__)

app = FastAPI(title="HealthCore — Centralized Incident Manager")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)

IncidentQuery = Query()

# --- Error handling ----------------------------------------------------
# Business-rule failures raise HTTPException(400, ...) with the exact
# {field, message} shape the reference solution requires. Anything else
# (a real bug, a TinyDB error, etc.) is caught here and turned into a
# generic 500 body — the real exception is never leaked to the client.

@app.exception_handler(RequestValidationError)
async def validation_error_handler(request: Request, exc: RequestValidationError):
    # Pydantic/FastAPI validation errors default to 422 with a list shape.
    # The reference solution requires 400 with a single {field, message}.
    first_error = exc.errors()[0]
    field = ".".join(str(part) for part in first_error["loc"] if part != "body")
    return JSONResponse(
        status_code=400,
        content={"field": field or "body", "message": first_error["msg"]},
    )


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    # If detail is already a {field, message} dict (our 400 business-rule
    # errors), return it unwrapped. Otherwise (e.g. 404 with a string
    # detail), keep FastAPI's normal {"detail": ...} shape.
    if isinstance(exc.detail, dict) and "field" in exc.detail and "message" in exc.detail:
        return JSONResponse(status_code=exc.status_code, content=exc.detail)
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    logger.exception(f"Unhandled error on {request.method} {request.url.path}")
    return JSONResponse(
        status_code=500,
        content={"message": "Internal server error"},
    )


# --- Helpers -------------------------------------------------------------

def _doc_to_incident(doc: dict) -> Incident:
    # doc may carry internal-only keys (e.g. _seed_source_id) — Incident
    # ignores unknown fields by default, so they never leak into responses.
    return Incident(id=str(doc.doc_id), **doc)


# --- Endpoints -------------------------------------------------------------

@app.post("/api/incidents", response_model=Incident, status_code=201)
def create_incident(payload: IncidentCreate):
    now = datetime.now(timezone.utc)
    doc = {
        "title": payload.title,
        "description": payload.description,
        "category": payload.category.value,
        "status": "open",
        "origin": payload.origin.value,
        "branch": payload.branch.value,
        "created_at": now.isoformat(),
        "updated_at": now.isoformat(),
    }
    doc_id = incidents_table.insert(doc)
    stored = incidents_table.get(doc_id=doc_id)
    return _doc_to_incident(stored)


@app.get("/api/incidents", response_model=list[Incident])
def list_incidents(
    status: str | None = None,
    origin: str | None = None,
    branch: str | None = None,
    category: str | None = None,
):
    query = None
    filters = {"status": status, "origin": origin, "branch": branch, "category": category}
    for field, value in filters.items():
        if value is None:
            continue
        condition = getattr(IncidentQuery, field) == value
        query = condition if query is None else (query & condition)

    docs = incidents_table.search(query) if query is not None else incidents_table.all()
    return [_doc_to_incident(doc) for doc in docs]


@app.get("/api/incidents/summary", response_model=IncidentSummary)
def get_summary():
    docs = incidents_table.all()

    by_status: dict[str, int] = {}
    by_category: dict[str, int] = {}
    by_origin: dict[str, int] = {}
    by_branch: dict[str, int] = {}

    for doc in docs:
        by_status[doc["status"]] = by_status.get(doc["status"], 0) + 1
        by_category[doc["category"]] = by_category.get(doc["category"], 0) + 1
        by_origin[doc["origin"]] = by_origin.get(doc["origin"], 0) + 1
        by_branch[doc["branch"]] = by_branch.get(doc["branch"], 0) + 1

    return IncidentSummary(
        by_status=by_status,
        by_category=by_category,
        by_origin=by_origin,
        by_branch=by_branch,
    )


@app.get("/api/incidents/{incident_id}", response_model=Incident)
def get_incident(incident_id: int):
    doc = incidents_table.get(doc_id=incident_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="Incident not found")
    return _doc_to_incident(doc)


@app.patch("/api/incidents/{incident_id}/status", response_model=Incident)
def update_incident_status(incident_id: int, payload: IncidentStatusUpdate):
    doc = incidents_table.get(doc_id=incident_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="Incident not found")

    current_status = doc["status"]
    try:
        current_enum = next(s for s in VALID_STATUS_TRANSITIONS if s.value == current_status)
    except StopIteration:
        logger.error(
            f"Data integrity issue: incident {incident_id} has unrecognized status '{current_status}'"
        )
        raise HTTPException(
            status_code=500,
            detail="This incident has an invalid status and cannot be updated. Contact support.",
        )

    allowed = VALID_STATUS_TRANSITIONS[current_enum]
    if payload.status not in allowed:
        body = ValidationErrorBody(
            field="status",
            message=f"Cannot move from {current_status} to {payload.status.value}.",
        )
        raise HTTPException(status_code=400, detail=body.model_dump())

    now = datetime.now(timezone.utc)
    incidents_table.update(
        {"status": payload.status.value, "updated_at": now.isoformat()},
        doc_ids=[incident_id],
    )
    updated = incidents_table.get(doc_id=incident_id)
    return _doc_to_incident(updated)