"""RFP intake endpoints (Milestone 9, Part 1).

Thin HTTP layer on the EXISTING API: it only stores the PDF, creates the ticket,
enqueues the background pipeline and answers status queries. The LangGraph
lives in data/pipelines/rfp_intake/ and is never owned by this router.
"""
import re
import sys
import uuid
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, UploadFile
from fastapi.responses import JSONResponse
from sqlmodel import Session, select

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.core.deps import get_current_user  # noqa: E402
from data.pipelines.rfp_intake.convert import RAW_RFP_DIR  # noqa: E402
from data.pipelines.rfp_intake.models import RfpTicket  # noqa: E402
from data.pipelines.rfp_intake.service import create_ticket, run_ticket, ticket_to_dict  # noqa: E402
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
