"""Persistence + lifecycle for RFP tickets. Called by the router (services/api).

The router creates the ticket and enqueues `run_ticket`; the pipeline runs in
the background and this module is the only place that changes ticket status.
"""
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.engine import Engine
from sqlmodel import Session, delete, select

from .graph import run_intake
from .models import (
    ROUTING_READY_FOR_PART2,
    STATUS_ANALYSIS_COMPLETE,
    STATUS_DISCARDED,
    RfpDepartmentSection,
    RfpTicket,
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def create_ticket(session: Session, *, filename: str, pdf_path: str, user_id: int | None) -> RfpTicket:
    ticket = RfpTicket(original_filename=filename, raw_pdf_path=pdf_path, created_by_user_id=user_id)
    session.add(ticket)
    session.commit()
    session.refresh(ticket)
    return ticket


def run_ticket(ticket_id: int, engine: Engine) -> None:
    """Runs the whole pipeline for one ticket. Never raises: failures are stored.

    Design decision: Part 1 only allows analizando / analisis_completo /
    descartado. If the pipeline itself crashes we mark the ticket `descartado`
    and fill `error_message`, so it never stays stuck in `analizando` forever.
    `scripts/rfp_intake_smoke.py --reprocess <id>` can run it again.
    """
    with Session(engine) as session:
        ticket = session.get(RfpTicket, ticket_id)
        if ticket is None:
            return
        try:
            state = run_intake(ticket.raw_pdf_path)
        except Exception as exc:
            ticket.status = STATUS_DISCARDED
            ticket.error_message = f"{type(exc).__name__}: {exc}"[:1000]
            ticket.updated_at = _now()
            session.add(ticket)
            session.commit()
            return

        classification = state["classification"]
        ticket.markdown_path = state.get("markdown_path")
        ticket.rfp_metadata = state.get("metadata")
        ticket.readability = state.get("readability")
        ticket.is_rfp = classification["is_rfp"]
        ticket.classifier_confidence = classification["confidence"]
        ticket.classifier_reason = classification["reason"]
        ticket.detected_departments = classification["detected_departments"]
        ticket.classified_at = _now()

        if not classification["is_rfp"]:
            ticket.status = STATUS_DISCARDED  # explicit, never a silent failure
        else:
            synthesis = {**state["synthesis"], "ticket_id": ticket.id}  # Part 2 handoff payload
            session.exec(delete(RfpDepartmentSection).where(RfpDepartmentSection.ticket_id == ticket.id))
            for result in state.get("worker_results") or []:
                session.add(
                    RfpDepartmentSection(
                        ticket_id=ticket.id,
                        department=result["department"],
                        key_aspects=result["key_aspects"],
                        open_questions=result["open_questions"],
                        suggested_contact_role=result["suggested_contact_role"],
                    )
                )
            ticket.synthesis = synthesis
            ticket.summary = synthesis["summary"]
            ticket.routing_status = ROUTING_READY_FOR_PART2
            ticket.status = STATUS_ANALYSIS_COMPLETE
            ticket.completed_at = _now()

        ticket.error_message = None
        ticket.updated_at = _now()
        session.add(ticket)
        session.commit()


def ticket_to_dict(session: Session, ticket: RfpTicket, *, with_sections: bool = True) -> dict[str, Any]:
    data = ticket.model_dump(mode="json")
    if with_sections:
        sections = session.exec(
            select(RfpDepartmentSection).where(RfpDepartmentSection.ticket_id == ticket.id)
        ).all()
        data["sections"] = [s.model_dump(mode="json") for s in sections]
    return data
