"""RFP endpoints (Milestone 9, Parts 1, 2 and 3).

Thin HTTP layer on the EXISTING API: it stores the PDF, creates the ticket,
enqueues the background pipelines and answers status queries. The LangGraph
flows (Part 1 intake, Part 2 generator/evaluator loop, Part 3 approval) live in
data/pipelines/ and are never owned by this router.

Part 3 endpoints only call `ApprovalWorkflow` (data/pipelines/rfp_produce/):
    GET  /rfp/approver/me                     which approver (if any) the logged-in user is
    POST /rfp/tickets/{id}/approvals/start    open one scoped interrupt per department
    GET  /rfp/tickets/{id}/approvals          who approved, who is pending, final doc?
    POST /rfp/tickets/{id}/approvals/resume   validated human decision (approve/reject/request_changes)
    GET  /rfp/tickets/{id}/trace              per-node execution trace
    GET  /rfp/tickets/{id}/final-document     the consolidated proposal (markdown)
"""
import re
import sys
import uuid
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, UploadFile
from fastapi.responses import JSONResponse, PlainTextResponse
from sqlmodel import Session, select

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.core.deps import get_current_user  # noqa: E402
from data.pipelines.rfp_intake.convert import RAW_RFP_DIR  # noqa: E402
from data.pipelines.rfp_intake.models import (  # noqa: E402
    ROUTING_READY_FOR_PART3,
    RfpDraftSection,
    RfpTicket,
)
from data.pipelines.rfp_intake.service import create_ticket, run_ticket, ticket_to_dict  # noqa: E402
from data.pipelines.rfp_produce import NoPendingApproval, ResumePayload, StaleDraftError  # noqa: E402
from data.pipelines.rfp_produce.approvers import (  # noqa: E402
    ENV_VAR as APPROVERS_ENV_VAR,
    actor_for_user,
    department_for_actor,
)
from data.pipelines.rfp_produce.factory import get_workflow  # noqa: E402
from data.pipelines.rfp_produce.models import ALLOWED_START_STATUSES  # noqa: E402
from data.pipelines.rfp_response.service import (  # noqa: E402
    draft_to_dict,
    is_eligible,
    run_generation,
    start_generation,
)
from database import engine, get_db  # noqa: E402

router = APIRouter(prefix="/rfp", tags=["rfp"])

MAX_UPLOAD_BYTES = 20 * 1024 * 1024


def _safe_name(filename: str) -> str:
    stem = Path(filename).stem
    return re.sub(r"[^A-Za-z0-9._-]+", "_", stem)[:80] or "rfp"


@router.post("/tickets", status_code=202)
async def upload_rfp(
    file: UploadFile,
    background_tasks: BackgroundTasks,
    session: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Accepts a PDF, answers fast (202) and runs the pipeline in the background."""
    original = file.filename or "rfp.pdf"
    if not original.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail={"field": "file", "message": "Only PDF files are accepted."})

    content = await file.read()
    if not content.startswith(b"%PDF"):  # do not trust the extension alone
        raise HTTPException(status_code=400, detail={"field": "file", "message": "The file is not a valid PDF."})
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=400, detail={"field": "file", "message": "The PDF is larger than 20 MB."})

    RAW_RFP_DIR.mkdir(parents=True, exist_ok=True)
    pdf_path = RAW_RFP_DIR / f"{uuid.uuid4().hex[:8]}_{_safe_name(original)}.pdf"
    pdf_path.write_bytes(content)

    ticket = create_ticket(session, filename=original, pdf_path=str(pdf_path), user_id=current_user["id"])
    background_tasks.add_task(run_ticket, ticket.id, engine)
    return JSONResponse(status_code=202, content={"ticket_id": ticket.id, "status": ticket.status})


@router.get("/tickets")
def list_tickets(session: Session = Depends(get_db), current_user: dict = Depends(get_current_user)):
    tickets = session.exec(select(RfpTicket).order_by(RfpTicket.created_at.desc())).all()
    return [ticket_to_dict(session, t, with_sections=False) for t in tickets]


@router.get("/tickets/{ticket_id}")
def get_ticket(ticket_id: int, session: Session = Depends(get_db), current_user: dict = Depends(get_current_user)):
    ticket = session.get(RfpTicket, ticket_id)
    if ticket is None:
        raise HTTPException(status_code=404, detail="Ticket not found")
    return ticket_to_dict(session, ticket)


@router.post("/tickets/{ticket_id}/generate", status_code=202)
def generate_response(
    ticket_id: int,
    background_tasks: BackgroundTasks,
    session: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Part 2: drafts one section per department and evaluates it, in the background."""
    ticket = session.get(RfpTicket, ticket_id)
    if ticket is None:
        raise HTTPException(status_code=404, detail="Ticket not found")
    if not is_eligible(ticket):
        raise HTTPException(
            status_code=409,
            detail={
                "message": "The ticket is not ready for response generation (Part 1 not finished, "
                "already drafting, or blocked until Compliance reviews detected PHI).",
                "status": ticket.status,
                "routing_status": ticket.routing_status,
            },
        )
    start_generation(session, ticket)  # status = drafting, synchronously
    background_tasks.add_task(run_generation, ticket.id, engine)
    return JSONResponse(status_code=202, content={"ticket_id": ticket.id, "status": ticket.status})


@router.get("/tickets/{ticket_id}/drafts")
def get_drafts(ticket_id: int, session: Session = Depends(get_db), current_user: dict = Depends(get_current_user)):
    """Part 3 handoff: every department draft + its EvaluationResult (flagged ones included)."""
    ticket = session.get(RfpTicket, ticket_id)
    if ticket is None:
        raise HTTPException(status_code=404, detail="Ticket not found")
    drafts = session.exec(select(RfpDraftSection).where(RfpDraftSection.ticket_id == ticket_id)).all()
    return {
        "ticket_id": ticket.id,
        "status": ticket.status,
        "routing_status": ticket.routing_status,
        "drafts": [draft_to_dict(d) for d in drafts],
    }


# --------------------------------------------------------------------------- #
# Part 3: approval and completion
# --------------------------------------------------------------------------- #


def _current_actor(current_user: dict) -> str | None:
    try:
        return actor_for_user(current_user)
    except ValueError as exc:  # misconfigured RFP_APPROVERS
        raise HTTPException(status_code=503, detail=str(exc))


@router.get("/approver/me")
def get_my_approver(current_user: dict = Depends(get_current_user)):
    """Who the logged-in user may decide as (null when the account is not an approver)."""
    actor = _current_actor(current_user)
    return {"actor": actor, "department": department_for_actor(actor)}


def _get_ticket_or_404(session: Session, ticket_id: int) -> RfpTicket:
    ticket = session.get(RfpTicket, ticket_id)
    if ticket is None:
        raise HTTPException(status_code=404, detail="Ticket not found")
    return ticket


@router.post("/tickets/{ticket_id}/approvals/start")
def start_approvals(
    ticket_id: int,
    session: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Opens one approval interrupt per required department (idempotent)."""
    ticket = _get_ticket_or_404(session, ticket_id)
    if ticket.status not in ALLOWED_START_STATUSES or ticket.routing_status != ROUTING_READY_FOR_PART3:
        raise HTTPException(
            status_code=409,
            detail={
                "message": "The ticket is not ready for approval (Part 2 not finished, or already done).",
                "status": ticket.status,
                "routing_status": ticket.routing_status,
            },
        )
    try:
        return get_workflow().start(str(ticket_id))
    except ValueError as exc:  # missing drafts, unsupported country, ...
        raise HTTPException(status_code=409, detail=str(exc))


@router.get("/tickets/{ticket_id}/approvals")
def get_approvals(
    ticket_id: int,
    session: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Approval board for the backoffice: per-department state + what each approver sees."""
    _get_ticket_or_404(session, ticket_id)
    workflow = get_workflow()
    try:
        return {"approvals": workflow.status(str(ticket_id)), "pending": workflow.pending_payloads(str(ticket_id))}
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@router.post("/tickets/{ticket_id}/approvals/resume")
def resume_approval(
    ticket_id: int,
    payload: ResumePayload,
    session: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Explicit, validated resume of ONE department's paused approval.

    Invalid payloads (wrong owner, missing comment) are rejected with 422 before they
    reach the graph. The decision must be made AS the logged-in user's own approver
    identity (403 otherwise). A department without a pending approval, or whose draft
    changed after the request, answers 409.
    """
    _get_ticket_or_404(session, ticket_id)
    actor = _current_actor(current_user)
    if actor is None:
        raise HTTPException(
            status_code=403,
            detail=f"Your account is not linked to a department approver ({APPROVERS_ENV_VAR}).",
        )
    if payload.actor != actor:
        raise HTTPException(status_code=403, detail=f"You can only decide as {actor}.")
    try:
        return get_workflow().submit_decision(str(ticket_id), payload)
    except (NoPendingApproval, StaleDraftError) as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@router.get("/tickets/{ticket_id}/trace")
def get_trace(
    ticket_id: int,
    session: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    _get_ticket_or_404(session, ticket_id)
    return [event.model_dump(mode="json") for event in get_workflow().trace(str(ticket_id))]


@router.get("/tickets/{ticket_id}/final-document", response_class=PlainTextResponse)
def get_final_document(
    ticket_id: int,
    session: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    _get_ticket_or_404(session, ticket_id)
    markdown = get_workflow().store.get_final_markdown(str(ticket_id))
    if markdown is None:
        raise HTTPException(status_code=404, detail="The final document does not exist yet")
    return PlainTextResponse(markdown, media_type="text/markdown")
