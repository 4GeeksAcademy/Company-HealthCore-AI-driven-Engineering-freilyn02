"""Manual runner for the RFP intake pipeline (a CLI, NOT a second HTTP API).

Usage, from the repo root:
  # 1) Dry run on any PDF: no database, prints the pipeline result as JSON.
  services/api/.venv/bin/python scripts/rfp_intake_smoke.py path/to/rfp.pdf

  # 2) Re-run the pipeline for an existing ticket (needs DATABASE_URL).
  services/api/.venv/bin/python scripts/rfp_intake_smoke.py --reprocess 12
"""
import argparse
import json
import shutil
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "services" / "api"))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(REPO_ROOT / ".env")


def dry_run(pdf: Path) -> None:
    from data.pipelines.rfp_intake.graph import run_intake

    if not pdf.exists():
        sys.exit(f"File not found: {pdf}")

    # Work on a copy so the .md artifact does not pollute your folders.
    with tempfile.TemporaryDirectory() as tmp:
        copy = Path(tmp) / pdf.name
        shutil.copy(pdf, copy)
        state = run_intake(str(copy))

    print("--- classification ---")
    print(json.dumps(state["classification"], indent=2, default=str))
    print("--- metadata / readability ---")
    print(json.dumps({"metadata": state.get("metadata"), "readability": state.get("readability")}, indent=2, default=str))
    if "synthesis" in state:
        print("--- synthesis (what Sales reads) ---")
        print(json.dumps(state["synthesis"], indent=2, default=str))
    else:
        print("--- discarded: the classifier rejected this document ---")


def reprocess(ticket_id: int) -> None:
    from database import engine
    from sqlmodel import Session

    from data.pipelines.rfp_intake.models import STATUS_ANALYZING, RfpTicket
    from data.pipelines.rfp_intake.service import run_ticket

    with Session(engine) as session:
        ticket = session.get(RfpTicket, ticket_id)
        if ticket is None:
            sys.exit(f"Ticket {ticket_id} not found.")
        ticket.status = STATUS_ANALYZING
        session.add(ticket)
        session.commit()

    run_ticket(ticket_id, engine)

    with Session(engine) as session:
        ticket = session.get(RfpTicket, ticket_id)
        print(f"Ticket {ticket_id}: status={ticket.status} error={ticket.error_message}")


def main() -> None:
    parser = argparse.ArgumentParser(description="RFP intake pipeline runner")
    parser.add_argument("pdf", nargs="?", type=Path, help="PDF to analyze (dry run, no database)")
    parser.add_argument("--reprocess", type=int, metavar="TICKET_ID", help="re-run an existing ticket")
    args = parser.parse_args()

    if args.reprocess is not None:
        reprocess(args.reprocess)
    elif args.pdf is not None:
        dry_run(args.pdf)
    else:
        parser.error("give a PDF path or --reprocess TICKET_ID")


if __name__ == "__main__":
    main()
