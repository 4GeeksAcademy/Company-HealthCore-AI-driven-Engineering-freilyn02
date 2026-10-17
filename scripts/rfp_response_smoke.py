"""Runs RFP response generation (Part 2) on an existing ticket with the real LLM.

Usage (from services/api):
    uv run python ../../scripts/rfp_response_smoke.py                  # list tickets
    uv run python ../../scripts/rfp_response_smoke.py <ticket_id>      # run with the default limit
    uv run python ../../scripts/rfp_response_smoke.py <ticket_id> 1    # force a low iteration limit
"""
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "services" / "api"))

from sqlmodel import Session, select  # noqa: E402

from data.pipelines.rfp_intake.models import RfpDraftSection, RfpTicket  # noqa: E402
from data.pipelines.rfp_response.config import MAX_ITERATIONS  # noqa: E402
from data.pipelines.rfp_response.service import is_eligible, run_generation, start_generation  # noqa: E402
from database import engine  # noqa: E402


def list_tickets() -> None:
    with Session(engine) as session:
        for t in session.exec(select(RfpTicket).order_by(RfpTicket.id)).all():
            print(f"id={t.id} status={t.status} routing={t.routing_status} eligible={is_eligible(t)} file={t.original_filename}")


def main() -> None:
    if len(sys.argv) < 2:
        list_tickets()
        return
    ticket_id = int(sys.argv[1])
    max_iterations = int(sys.argv[2]) if len(sys.argv) > 2 else MAX_ITERATIONS

    with Session(engine) as session:
        ticket = session.get(RfpTicket, ticket_id)
        if ticket is None or not is_eligible(ticket):
            print("Ticket not found or not eligible (needs Part 1 finished and no PHI block).")
            return
        start_generation(session, ticket)

    run_generation(ticket_id, engine, max_iterations=max_iterations)

    with Session(engine) as session:
        ticket = session.get(RfpTicket, ticket_id)
        print(f"\nTICKET {ticket.id}: status={ticket.status} routing={ticket.routing_status} error={ticket.error_message}")
        for d in session.exec(select(RfpDraftSection).where(RfpDraftSection.ticket_id == ticket_id)).all():
            print(f"\n===== {d.department} | iterations={d.iterations} | pass={d.overall_pass} | needs_human_review={d.needs_human_review}")
            print(d.content)
            print("--- evaluation:")
            print(json.dumps(d.evaluation, indent=2))


if __name__ == "__main__":
    main()
