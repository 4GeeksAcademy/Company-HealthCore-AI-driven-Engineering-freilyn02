"""Reproducible E2E for Milestone 9 Part 3 (simulated human resumes, no network, no LLM).

    uv run python scripts/run_rfp_e2e.py            # US/USD case
    uv run python scripts/run_rfp_e2e.py thames     # UK/GBP case
    uv run python scripts/run_rfp_e2e.py capacity   # arbitration case

Flow: seeded Part 2 drafts -> start (3 scoped interrupts) -> simulated owner decisions
(each one in a NEW workflow object, i.e. a simulated process restart) -> final document.
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from data.pipelines.rfp_produce import ApprovalWorkflow, SqliteTicketStore, get_checkpointer  # noqa: E402
from data.pipelines.rfp_produce.fixtures import CASES, approve, make_revision_hook, seed_ticket  # noqa: E402


def main(case: str = "meridian") -> int:
    if case not in CASES:
        print(f"unknown case {case!r}; choose from {sorted(CASES)}")
        return 2
    work = Path(tempfile.mkdtemp(prefix="rfp_e2e_"))
    store = SqliteTicketStore(work / "tickets.sqlite")
    ticket_id = f"rfp-demo-{case}"

    def workflow() -> ApprovalWorkflow:  # new checkpointer each time = process restart
        return ApprovalWorkflow(
            store, get_checkpointer(work / "ckpt.sqlite"),
            revision_hook=make_revision_hook(store), output_dir=work / "final",
        )

    seed_ticket(store, ticket_id, case)
    out = workflow().start(ticket_id)
    print(f"[start]    status={out['status']} pending={out['pending_approvals']}")
    for res in out["resolutions"]:
        print(f"[arbiter]  {res['conflict_id']} -> {res['arbiter']}: {res['resolution']}")

    for dept in ("revenue", "clinical", "compliance"):
        out = workflow().submit_decision(ticket_id, approve(dept))
        print(f"[approve]  {dept:<10} status={out['status']} pending={out['pending_approvals']}")

    if out["status"] != "done":
        print("FAILED: ticket is not done")
        return 1
    print(f"[done]     final document: {out['final_document']}")
    print("\n--- trace ---")
    for e in workflow().trace(ticket_id):
        print(f"{e.ts} {e.department or '-':<10} {e.agent:<32} {e.input_ref} -> {e.output_ref}")
    print("\n--- document ---")
    print(Path(out["final_document"]).read_text())
    return 0


if __name__ == "__main__":
    raise SystemExit(main(*sys.argv[1:2]))
