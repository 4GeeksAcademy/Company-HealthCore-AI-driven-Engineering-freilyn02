"""Persistence + lifecycle for RFP tickets. Called by the router (services/api).

The router creates the ticket and enqueues `run_ticket`; the pipeline runs in
the background and this module is the only place that changes ticket status.

HIPAA / UK GDPR: everything that reaches the database passes through
`scrub_obj` first, as a last line of defense on top of the PHI guard in the graph.
"""
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.engine import Engine
from sqlmodel import Session, delete, select

from .config import currency_for
from .graph import run_intake
from .models import (
    ROUTING_COMPLIANCE_REVIEW,
    ROUTING_READY_FOR_PART2,
    STATUS_DISCARDED,
    STATUS_INTAKE_COMPLETE,
    RfpDepartmentSection,
    RfpTicket,
)
from .phi import redact_text, scrub_obj


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

    Design decision: Part 1 only allows analyzing / intake_complete / discarded.
    If the pipeline itself crashes we mark the ticket `discarded` and fill
    `error_message`, so it never stays stuck in `analyzing` forever.
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
            ticket.error_message = redact_text(f"{type(exc).__name__}: {exc}")[:1000]
            ticket.updated_at = _now()
            session.add(ticket)
            session.commit()
            return

        phi = state.get("phi") or {"contains_phi": False, "findings": {}}
        classification = state["classification"]
        rfp_fields = scrub_obj(state.get("rfp_fields") or {})

        ticket.markdown_path = state.get("markdown_path")  # redacted markdown
        ticket.readability = state.get("readability")
        ticket.contains_phi = bool(phi["contains_phi"])
        ticket.phi_findings = phi["findings"]  # counts by type, never values
        ticket.is_rfp = classification["is_rfp"]
        ticket.classifier_confidence = classification["confidence"]
        ticket.classifier_reason = redact_text(classification["reason"])
        ticket.detected_departments = classification["detected_departments"]
        ticket.classified_at = _now()

        if not classification["is_rfp"]:
            ticket.status = STATUS_DISCARDED  # explicit, never a silent failure
            ticket.rfp_metadata = {"document": state.get("metadata")}
        else:
            worker_results = scrub_obj(state.get("worker_results") or [])
            departments_needed = sorted(r["department"] for r in worker_results)
            synthesis = scrub_obj(
                {
                    **state["synthesis"],
                    "ticket_id": ticket.id,  # Part 2 handoff payload
                    "departments_needed": departments_needed,
                }
            )

            ticket.rfp_metadata = {
                **rfp_fields,
                "currency": currency_for(rfp_fields.get("client_country")),
                "departments_needed": departments_needed,
                "document": state.get("metadata"),
            }
            session.exec(delete(RfpDepartmentSection).where(RfpDepartmentSection.ticket_id == ticket.id))
            for result in worker_results:
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
            # With PHI the handoff is blocked until Compliance reviews the ticket.
            ticket.routing_status = (
                ROUTING_COMPLIANCE_REVIEW if ticket.contains_phi else ROUTING_READY_FOR_PART2
            )
            ticket.status = STATUS_INTAKE_COMPLETE
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
