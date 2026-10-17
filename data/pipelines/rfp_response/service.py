"""Persistence + lifecycle for RFP response generation (Milestone 9, Part 2).

Consumes the Part 1 handoff stored in the database (ticket_id + synthesis payload +
department sections). It never re-reads the PDF. Only this module changes ticket
status during Part 2:
    intake_complete -> drafting -> under_evaluation -> (needs_human_review)
Part 3 statuses are NOT created here.
"""
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.engine import Engine
from sqlmodel import Session, delete, select

from ..rfp_intake.config import DEPARTMENTS, LEGAL_INSTRUMENT, currency_for
from ..rfp_intake.models import (
    ROUTING_READY_FOR_PART2,
    ROUTING_READY_FOR_PART3,
    STATUS_DRAFTING,
    STATUS_INTAKE_COMPLETE,
    STATUS_NEEDS_HUMAN_REVIEW,
    STATUS_UNDER_EVALUATION,
    RfpDepartmentSection,
    RfpDraftSection,
    RfpTicket,
)
from ..rfp_intake.phi import redact_text, scrub_obj
from .config import MAX_ITERATIONS
from .loop import run_section_loop

ELIGIBLE_STATUSES = (STATUS_INTAKE_COMPLETE, STATUS_UNDER_EVALUATION, STATUS_NEEDS_HUMAN_REVIEW)
ELIGIBLE_ROUTING = (ROUTING_READY_FOR_PART2, ROUTING_READY_FOR_PART3)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def is_eligible(ticket: RfpTicket) -> bool:
    """Ticket must have finished Part 1 and must not be blocked by a PHI review."""
    return ticket.status in ELIGIBLE_STATUSES and ticket.routing_status in ELIGIBLE_ROUTING


def start_generation(session: Session, ticket: RfpTicket) -> None:
    """Marks the ticket `drafting` synchronously, so a double click cannot start twice."""
    ticket.status = STATUS_DRAFTING
    ticket.error_message = None
    ticket.updated_at = _now()
    session.add(ticket)
    session.commit()


def build_handoffs(session: Session, ticket: RfpTicket) -> dict[str, dict[str, Any]]:
    """One handoff per department, built ONLY from the Part 1 data stored in the DB."""
    meta = ticket.rfp_metadata or {}
    synthesis = ticket.synthesis or {}
    client = {
        key: meta.get(key)
        for key in ("client_name", "client_country", "program_type", "covered_population", "deadline", "budget_range")
    }
    country = client.get("client_country")
    sections = session.exec(select(RfpDepartmentSection).where(RfpDepartmentSection.ticket_id == ticket.id)).all()

    handoffs: dict[str, dict[str, Any]] = {}
    for section in sections:
        if section.department not in DEPARTMENTS:
            continue
        handoffs[section.department] = {
            "ticket_id": ticket.id,
            "department": section.department,
            "label": DEPARTMENTS[section.department]["label"],
            "client": client,
            "currency": meta.get("currency") or currency_for(country),
            "legal_instrument": LEGAL_INSTRUMENT.get(country),
            "summary": synthesis.get("summary") or ticket.summary,
            "key_aspects": section.key_aspects or [],
            "open_questions": section.open_questions or [],
            "contact_role": section.suggested_contact_role or DEPARTMENTS[section.department]["contact_role"],
        }
    return handoffs


def _set_status(engine: Engine, ticket_id: int, status: str) -> None:
    with Session(engine) as session:
        ticket = session.get(RfpTicket, ticket_id)
        if ticket is not None and ticket.status != status:
            ticket.status = status
            ticket.updated_at = _now()
            session.add(ticket)
            session.commit()


def _mark_needs_review(engine: Engine, ticket_id: int, message: str) -> None:
    with Session(engine) as session:
        ticket = session.get(RfpTicket, ticket_id)
        if ticket is None:
            return
        ticket.status = STATUS_NEEDS_HUMAN_REVIEW
        ticket.error_message = redact_text(message)[:1000]
        ticket.updated_at = _now()
        session.add(ticket)
        session.commit()


def run_generation(ticket_id: int, engine: Engine, max_iterations: int = MAX_ITERATIONS) -> None:
    """Runs Part 2 for one ticket. Never raises. The ticket is never discarded."""
    with Session(engine) as session:
        ticket = session.get(RfpTicket, ticket_id)
        if ticket is None or ticket.status != STATUS_DRAFTING:
            return
        handoffs = build_handoffs(session, ticket)

    if not handoffs:
        _mark_needs_review(engine, ticket_id, "No department sections found to draft.")
        return

    # Departments run concurrently; a slow one does not block the others.
    lock = threading.Lock()
    state = {"evaluating": False}

    def on_phase(department: str, phase: str) -> None:
        if phase != "evaluating":
            return
        with lock:
            if state["evaluating"]:
                return
            state["evaluating"] = True
            _set_status(engine, ticket_id, STATUS_UNDER_EVALUATION)

    try:
        with ThreadPoolExecutor(max_workers=len(handoffs)) as pool:
            futures = {
                dept: pool.submit(run_section_loop, dept, handoff, max_iterations=max_iterations, on_phase=on_phase)
                for dept, handoff in handoffs.items()
            }
            results = [futures[dept].result() for dept in sorted(futures)]
    except Exception as exc:
        _mark_needs_review(engine, ticket_id, f"{type(exc).__name__}: {exc}")
        return

    with Session(engine) as session:
        ticket = session.get(RfpTicket, ticket_id)
        if ticket is None:
            return
        session.exec(delete(RfpDraftSection).where(RfpDraftSection.ticket_id == ticket_id))
        for result in results:
            evaluation = scrub_obj(result["evaluation"])
            session.add(
                RfpDraftSection(
                    ticket_id=ticket_id,
                    department=result["department"],
                    content=redact_text(result["content"]),
                    iterations=result["iterations"],
                    overall_pass=bool(evaluation.get("overall_pass")),
                    needs_human_review=result["needs_human_review"],
                    evaluation=evaluation,
                )
            )
        flagged = any(r["needs_human_review"] for r in results)
        ticket.status = STATUS_NEEDS_HUMAN_REVIEW if flagged else STATUS_UNDER_EVALUATION
        ticket.routing_status = ROUTING_READY_FOR_PART3  # flagged sections travel too
        ticket.error_message = None
        ticket.updated_at = _now()
        session.add(ticket)
        session.commit()


def draft_to_dict(draft: RfpDraftSection) -> dict[str, Any]:
    return draft.model_dump(mode="json")
