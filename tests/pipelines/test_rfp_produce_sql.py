"""Part 3 on the real SQLModel tables (SQLite file engine, fake LLM collaborators)."""

from pathlib import Path

import pytest
from sqlmodel import Session, SQLModel, create_engine, select

from data.pipelines.rfp_intake.models import (
    ROUTING_READY_FOR_PART3,
    STATUS_DONE,
    STATUS_UNDER_EVALUATION,
    STATUS_WAITING_FOR_APPROVAL,
    RfpApproval,
    RfpDraftSection,
    RfpFinalDocument,
    RfpTicket,
    RfpTraceEvent,
)
from data.pipelines.rfp_produce import get_checkpointer
from data.pipelines.rfp_produce.factory import build_workflow, make_sql_revision_hook
from data.pipelines.rfp_produce.fixtures import approve
from data.pipelines.rfp_produce.sql_store import SqlTicketStore, extract_structured, parse_int

CLEAN = {
    "revenue": "Pricing proposal in {cur}: per-member-per-month fee with quarterly reconciliation.",
    "clinical": "Clinical delivery plan: three sites, capacity for 900 members, weekly staffing reviews.",
    "compliance": {
        "US": "Business Associate Agreement (BAA) executed before any data exchange.",
        "UK": "Data Processing Agreement (DPA) under UK GDPR executed before any data exchange.",
    },
}


def clean_text(department: str, country: str) -> str:
    cur = "USD" if country == "US" else "GBP"
    if department == "revenue":
        return CLEAN["revenue"].format(cur=cur)
    if department == "clinical":
        return CLEAN["clinical"]
    return CLEAN["compliance"][country]


@pytest.fixture
def db(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'api.sqlite'}", connect_args={"check_same_thread": False}
    )
    SQLModel.metadata.create_all(engine)

    def seed(country_label="US", overrides=None, population=800):
        country = "UK" if country_label in ("UK", "United Kingdom") else "US"
        overrides = overrides or {}
        with Session(engine) as session:
            ticket = RfpTicket(
                status=STATUS_UNDER_EVALUATION,
                routing_status=ROUTING_READY_FOR_PART3,
                original_filename="rfp.pdf",
                raw_pdf_path="/tmp/rfp.pdf",
                rfp_metadata={
                    "client_name": "Meridian Health Network",
                    "client_country": country_label,
                    "covered_population": population,
                    "departments_needed": ["revenue", "clinical", "compliance"],
                },
            )
            session.add(ticket)
            session.commit()
            session.refresh(ticket)
            for dept in ("revenue", "clinical", "compliance"):
                session.add(
                    RfpDraftSection(
                        ticket_id=ticket.id,
                        department=dept,
                        content=overrides.get(dept, clean_text(dept, country)),
                        iterations=1,
                        overall_pass=True,
                        evaluation={"overall_pass": True},
                    )
                )
            session.commit()
            return ticket.id

    return engine, seed


def fake_generate(department, handoff, feedback=None, previous_draft=None):
    return clean_text(department, handoff["country"])


def fake_evaluate(department, draft, handoff):
    return {"overall_pass": True, "feedback_for_generator": ""}


def make_workflow(engine, tmp_path, *, generate=fake_generate, max_revisions=3):
    def handoff_for(session, ticket, department):
        label = (ticket.rfp_metadata or {})["client_country"]
        return {"country": "UK" if label in ("UK", "United Kingdom") else "US"}

    hook = make_sql_revision_hook(
        engine, generate=generate, evaluate=fake_evaluate, handoff_for=handoff_for, max_iterations=2
    )
    return build_workflow(
        engine,
        get_checkpointer(tmp_path / "ckpt.sqlite"),
        revision_hook=hook,
        max_revisions=max_revisions,
        output_dir=tmp_path / "final",
    )


def ticket_status(engine, ticket_id):
    with Session(engine) as session:
        return session.get(RfpTicket, ticket_id).status


def test_parse_int_and_extractors():
    assert parse_int("1,200 employees") == 1200
    assert parse_int(800) == 800
    assert parse_int(None) is None and parse_int(True) is None
    assert extract_structured("revenue", "x", {"covered_population": "2,500"}) == {"covered_population": 2500}
    assert extract_structured("clinical", "capacity for 900 members", {}) == {"committed_capacity": 900}
    assert extract_structured("clinical", "no number here", {}) == {}
    assert extract_structured("compliance", "BAA", {"covered_population": 5}) == {}


def test_full_flow_persists_to_the_database(db, tmp_path):
    engine, seed = db
    ticket_id = seed()
    workflow = make_workflow(engine, tmp_path)

    out = workflow.start(str(ticket_id))
    assert out["status"] == STATUS_WAITING_FOR_APPROVAL
    assert ticket_status(engine, ticket_id) == STATUS_WAITING_FOR_APPROVAL
    assert sorted(out["pending_approvals"]) == ["clinical", "compliance", "revenue"]

    for dept in ("revenue", "clinical", "compliance"):
        out = workflow.submit_decision(str(ticket_id), approve(dept))

    assert out["status"] == STATUS_DONE
    assert ticket_status(engine, ticket_id) == STATUS_DONE
    with Session(engine) as session:
        approvals = session.exec(select(RfpApproval).where(RfpApproval.ticket_id == ticket_id)).all()
        assert {a.department: a.approver for a in approvals} == {
            "revenue": "tom.callahan",
            "clinical": "marcus.reid",
            "compliance": "claire.whitfield",
        }
        final = session.exec(select(RfpFinalDocument).where(RfpFinalDocument.ticket_id == ticket_id)).one()
        assert "Economic Proposal - Meridian Health Network" in final.content_md
        assert "USD" in final.content_md and "BAA" in final.content_md
        agents = [e.agent for e in session.exec(select(RfpTraceEvent).order_by(RfpTraceEvent.id)).all()]
    assert agents[-1] == "ultimate_synthesizer" and "human:tom.callahan" in agents
    assert Path(out["final_document"]).exists()


def test_approval_survives_a_restart(db, tmp_path):
    engine, seed = db
    ticket_id = seed()
    make_workflow(engine, tmp_path).start(str(ticket_id))
    restarted = make_workflow(engine, tmp_path)  # new store, new checkpointer, same files
    out = restarted.submit_decision(str(ticket_id), approve("revenue"))
    assert out["departments"]["revenue"]["approval_status"] == "approved"
    assert "revenue" not in out["pending_approvals"]


def test_request_changes_regenerates_with_feedback(db, tmp_path):
    engine, seed = db
    ticket_id = seed()
    seen = {}

    def generate(department, handoff, feedback=None, previous_draft=None):
        seen[department] = (feedback, previous_draft)
        return clean_text(department, handoff["country"]) + " Revised."

    workflow = make_workflow(engine, tmp_path, generate=generate)
    workflow.start(str(ticket_id))
    out = workflow.submit_decision(
        str(ticket_id),
        {"department": "revenue", "decision": "request_changes", "actor": "tom.callahan",
         "requested_changes": "Lower the PMPM."},
    )
    assert seen["revenue"][0] == "Lower the PMPM."
    assert "revenue" in out["pending_approvals"]
    assert out["departments"]["revenue"]["revision_count"] == 1
    with Session(engine) as session:
        draft = session.exec(
            select(RfpDraftSection).where(
                RfpDraftSection.ticket_id == ticket_id, RfpDraftSection.department == "revenue"
            )
        ).one()
        assert draft.content.endswith("Revised.")
    assert ticket_status(engine, ticket_id) == STATUS_WAITING_FOR_APPROVAL


def test_capacity_conflict_is_arbitrated_from_the_database(db, tmp_path):
    engine, seed = db
    ticket_id = seed(
        overrides={"clinical": "Clinical plan: two sites, capacity for 500 members."}, population=800
    )
    workflow = make_workflow(engine, tmp_path)
    out = workflow.start(str(ticket_id))
    assert any(r["conflict_id"] == "capacity-vs-population" and r["arbiter"] == "tom.callahan"
               for r in out["resolutions"])
    assert out["departments"]["clinical"]["revision_count"] == 1
    for dept in ("revenue", "clinical", "compliance"):
        out = workflow.submit_decision(str(ticket_id), approve(dept))
    assert out["status"] == STATUS_DONE


def test_uk_client_with_baa_is_forced_to_dpa(db, tmp_path):
    engine, seed = db
    ticket_id = seed(
        "United Kingdom",
        overrides={"compliance": "Business Associate Agreement (BAA) executed."},
    )
    workflow = make_workflow(engine, tmp_path)
    out = workflow.start(str(ticket_id))
    assert any(r["conflict_id"] == "baa-dpa-mismatch" for r in out["resolutions"])
    section = SqlTicketStore(engine).get_section(str(ticket_id), "compliance")
    assert "UK GDPR" in section.draft_content


def test_unsupported_country_is_a_clear_error(db, tmp_path):
    engine, seed = db
    ticket_id = seed("Canada")
    with pytest.raises(ValueError, match="Unsupported client_country"):
        SqlTicketStore(engine).get_meta(str(ticket_id))


def test_phi_tokens_in_a_stored_draft_trigger_the_hard_stop(db, tmp_path):
    from data.pipelines.rfp_produce.sql_store import detect_phi

    assert detect_phi("Care for [REDACTED_PATIENT_NAME] at site A.", {})
    assert detect_phi("Patient name: Jane Doe", {})  # raw PHI that slipped through
    assert not detect_phi("Capacity for 900 members.", {"compliance": {"rule_ids": [], "violations": []}})

    engine, seed = db
    ticket_id = seed(overrides={"clinical": "Plan for [REDACTED_PATIENT_NAME]: three sites, capacity for 900 members."})
    workflow = make_workflow(engine, tmp_path)
    out = workflow.start(str(ticket_id))
    assert any(r["conflict_id"] == "phi-detected" and r["arbiter"] == "claire.whitfield"
               for r in out["resolutions"])
    assert "[REDACTED_" not in SqlTicketStore(engine).get_section(str(ticket_id), "clinical").draft_content
    for dept in ("revenue", "clinical", "compliance"):
        out = workflow.submit_decision(str(ticket_id), approve(dept))
    assert out["status"] == STATUS_DONE
