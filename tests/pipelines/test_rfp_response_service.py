"""Service test with an in-memory SQLite DB: statuses, persistence and handoff flags."""
import pytest
from sqlmodel import Session, SQLModel, create_engine, select
from sqlalchemy.pool import StaticPool

from data.pipelines.rfp_intake.models import (
    ROUTING_COMPLIANCE_REVIEW,
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
from data.pipelines.rfp_response import evaluators, generators
from data.pipelines.rfp_response.service import is_eligible, run_generation, start_generation


@pytest.fixture
def engine():
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(
        eng, tables=[RfpTicket.__table__, RfpDepartmentSection.__table__, RfpDraftSection.__table__]
    )
    return eng


def seed_ticket(engine, routing=ROUTING_READY_FOR_PART2) -> int:
    with Session(engine) as session:
        ticket = RfpTicket(
            original_filename="rfp.pdf",
            raw_pdf_path="rfp.pdf",
            status=STATUS_INTAKE_COMPLETE,
            routing_status=routing,
            rfp_metadata={"client_name": "Acme", "client_country": "US", "currency": "USD"},
            synthesis={"summary": "Acme wants occupational health."},
        )
        session.add(ticket)
        session.commit()
        session.refresh(ticket)
        for department in ("revenue", "compliance"):
            session.add(
                RfpDepartmentSection(ticket_id=ticket.id, department=department, key_aspects=["need"], open_questions=[])
            )
        session.commit()
        return ticket.id


def fake_pipeline(monkeypatch, failing_departments=()):
    monkeypatch.setattr(
        generators, "generate_section", lambda d, h, feedback=None, previous_draft=None: f"draft for {d}"
    )

    def evaluate(department, content, handoff):
        passed = department not in failing_departments
        return {
            "section_id": department,
            "department_id": department,
            "readability": {"pass": True, "score": 8.0, "details": {}},
            "relevance": {"pass": passed, "missing_aspects": [] if passed else ["x"]},
            "compliance": {"pass": True, "rule_ids": [], "violations": []},
            "overall_pass": passed,
            "feedback_for_generator": "" if passed else "fix it",
        }

    monkeypatch.setattr(evaluators, "evaluate_section", evaluate)


def run(engine, ticket_id, max_iterations=2):
    with Session(engine) as session:
        ticket = session.get(RfpTicket, ticket_id)
        start_generation(session, ticket)
        assert ticket.status == STATUS_DRAFTING
    run_generation(ticket_id, engine, max_iterations=max_iterations)


def test_all_sections_pass(engine, monkeypatch):
    fake_pipeline(monkeypatch)
    ticket_id = seed_ticket(engine)
    run(engine, ticket_id)
    with Session(engine) as session:
        ticket = session.get(RfpTicket, ticket_id)
        drafts = session.exec(select(RfpDraftSection).where(RfpDraftSection.ticket_id == ticket_id)).all()
    assert ticket.status == STATUS_UNDER_EVALUATION
    assert ticket.routing_status == ROUTING_READY_FOR_PART3
    assert len(drafts) == 2
    assert all(d.overall_pass and not d.needs_human_review for d in drafts)


def test_exhausted_section_is_flagged_but_still_in_the_handoff(engine, monkeypatch):
    fake_pipeline(monkeypatch, failing_departments=("compliance",))
    ticket_id = seed_ticket(engine)
    run(engine, ticket_id)
    with Session(engine) as session:
        ticket = session.get(RfpTicket, ticket_id)
        drafts = {d.department: d for d in session.exec(select(RfpDraftSection)).all()}
    assert ticket.status == STATUS_NEEDS_HUMAN_REVIEW  # ticket is NOT discarded
    assert ticket.routing_status == ROUTING_READY_FOR_PART3
    assert drafts["compliance"].needs_human_review is True
    assert drafts["compliance"].iterations == 2
    assert drafts["compliance"].content == "draft for compliance"  # last draft kept
    assert drafts["compliance"].evaluation["overall_pass"] is False
    assert drafts["revenue"].needs_human_review is False  # other departments are unaffected


def test_ticket_blocked_for_phi_is_not_eligible(engine):
    ticket_id = seed_ticket(engine, routing=ROUTING_COMPLIANCE_REVIEW)
    with Session(engine) as session:
        assert is_eligible(session.get(RfpTicket, ticket_id)) is False
