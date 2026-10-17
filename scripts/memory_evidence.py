"""MEM-092: real end-to-end evidence for the two required memory cycles.

Runs the REAL agent (real model, real Qdrant RAG, real Redis memory on DB /1) through:
  Cycle B - a proposal that the user REJECTS: memory stays unchanged.
  Cycle A - a proposal that the user APPROVES: the fact is stored and used in a later,
            separate conversation.
  Cycle C - a request to remember PATIENT information (HealthCore CONTEXT): refused out loud,
            audited with the patient data redacted, nothing stored.
and writes an English transcript + audit trail that can be pasted into the PR.

Needs: `docker compose up -d redis qdrant`, a valid .env (LLM_API_KEY, GENERATION_MODEL).

Usage (from the repo root):
  python scripts/memory_evidence.py
  python scripts/memory_evidence.py --correction "..." --followup "..."
  python scripts/memory_evidence.py --phi-only      # only the patient-information refusal
  python scripts/memory_evidence.py --no-reset      # keep existing memory entries
"""

from __future__ import annotations

import argparse
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))  # `data` package
sys.path.insert(0, str(ROOT / "services" / "api"))  # `agent` package

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")

from agent.graph import run_agent  # noqa: E402
from agent.memory import runtime  # noqa: E402
from agent.memory.audit import REDACTED  # noqa: E402
from agent.memory.flow import PHI_NOTICE  # noqa: E402
from agent.memory.store import KEY_PREFIX, get_redis_client, memory_redis_url  # noqa: E402

DEFAULT_CORRECTION = (
    "Correction: at HealthCore the no-show fee is waived when a patient cancels "
    "at least 24 hours before the appointment."
)
DEFAULT_FOLLOWUP = "Is the no-show fee waived when a patient cancels at least 24 hours in advance?"
DEFAULT_PHI_REQUEST = "Patient Johnson cancelled tomorrow's appointment, note that down."


class Report:
    def __init__(self) -> None:
        self.lines: list[str] = []
        self.checks: list[tuple[str, bool]] = []

    def add(self, text: str = "") -> None:
        self.lines.append(text)
        print(text)

    def check(self, name: str, ok: bool) -> None:
        self.checks.append((name, bool(ok)))
        self.add(f"- [{'PASS' if ok else 'FAIL'}] {name}")


def new_session() -> str:
    return f"evidence-{uuid.uuid4().hex[:10]}"


def memory_facts() -> list[str]:
    return sorted(entry.fact for entry in runtime.get_store().list())


def session_audit(session_id: str) -> list:
    return [r for r in runtime.get_audit_log().list() if r.session_id == session_id]


def run_turn(report: Report, message: str, session_id: str) -> dict:
    report.add(f"**User** (`{session_id}`):")
    report.add(f"> {message}")
    _, state = run_agent(message, session_id=session_id)
    answer = state.get("answer") or f"(no answer, error: {state.get('error')})"
    report.add("**Agent**:")
    for line in answer.splitlines() or [""]:
        report.add(f"> {line}")
    memory_steps = [s["output_summary"] for s in state.get("trace_steps", []) if s["node"].startswith("memory")]
    if memory_steps:
        report.add("Memory steps: " + " | ".join(memory_steps))
    report.add()
    return state


def show_audit(report: Report, session_id: str) -> list[str]:
    report.add("Audit records for this conversation:")
    decisions = []
    for record in session_audit(session_id):
        decisions.append(record.decision)
        report.add(
            f"- `{record.timestamp}` proposal `{record.proposal_id}` -> **{record.decision}** "
            f"(written={record.written}); fact: \"{record.proposed_fact}\""
        )
    report.add()
    return decisions


def cycle_rejected(report: Report, args) -> bool:
    report.add("## Cycle B - proposal rejected, memory unchanged")
    report.add()
    pending = runtime.get_pending_store()
    before = memory_facts()
    sid = new_session()
    run_turn(report, args.correction, sid)
    proposal = pending.get(sid)
    if proposal is None:
        report.add("The model did not propose a memory for this message, so there is no cycle to show.")
        report.add("Try again with another --correction (a clear, reusable correction of a HealthCore fact).")
        return False
    report.add(f"Pending proposal: \"{proposal.fact}\" (keys: {proposal.keys})")
    report.check("Nothing was written before the user decided", memory_facts() == before)
    report.add()
    run_turn(report, args.reject, sid)
    report.check("Pending proposal was cleared", pending.get(sid) is None)
    report.check("Memory is unchanged after the rejection", memory_facts() == before)
    decisions = show_audit(report, sid)
    report.check("Audit log has the proposal and the rejection", decisions == ["proposed", "reject"])
    later = run_turn(report, args.followup, new_session())
    report.check("The rejected fact is not used in a later interaction", not later.get("memories"))
    report.add()
    return True


def cycle_approved(report: Report, args) -> bool:
    report.add("## Cycle A - proposal approved, reflected in a later interaction")
    report.add()
    pending = runtime.get_pending_store()
    before = memory_facts()
    sid = new_session()
    run_turn(report, args.correction, sid)
    proposal = pending.get(sid)
    if proposal is None:
        report.add("The model did not propose a memory for this message, so there is no cycle to show.")
        report.add("Try again with another --correction (a clear, reusable correction of a HealthCore fact).")
        return False
    report.add(f"Pending proposal: \"{proposal.fact}\" (keys: {proposal.keys})")
    report.check("Nothing was written before the user decided", memory_facts() == before)
    report.add()
    run_turn(report, args.approve, sid)
    after = memory_facts()
    report.check("Exactly one new memory was written after the approval", len(after) == len(before) + 1)
    report.check("The stored fact is the approved one", proposal.fact in after)
    decisions = show_audit(report, sid)
    report.check("Audit log has the proposal and the approval", decisions == ["proposed", "approve"])
    later = run_turn(report, args.followup, new_session())
    used = [m["fact"] for m in later.get("memories") or []]
    report.check("The approved fact reached the agent in a NEW conversation", proposal.fact in used)
    report.add()
    return True


def cycle_phi_refused(report: Report, args) -> bool:
    report.add("## Cycle C - a request to remember patient information is refused")
    report.add()
    pending = runtime.get_pending_store()
    before = memory_facts()
    sid = new_session()
    state = run_turn(report, args.phi_request, sid)
    answer = state.get("answer") or ""
    report.check("The agent refused out loud and explained why (HIPAA / UK GDPR)", PHI_NOTICE in answer)
    report.check("Nothing was written to memory", memory_facts() == before)
    report.check("No proposal is pending", pending.get(sid) is None)
    records = session_audit(sid)
    report.add("Audit records for this conversation:")
    for record in records:
        report.add(
            f"- `{record.timestamp}` -> **{record.decision}** (written={record.written}); "
            f"reason: {record.reason}; user message: \"{record.user_message}\""
        )
    report.add()
    report.check("Audit log has the refusal", [r.decision for r in records] == ["policy_rejected"])
    report.check("The patient data is redacted in the audit log", all(r.user_message == REDACTED for r in records))
    report.add()
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description="Real evidence for the memory cycles (MEM-092).")
    parser.add_argument("--correction", default=DEFAULT_CORRECTION)
    parser.add_argument("--followup", default=DEFAULT_FOLLOWUP)
    parser.add_argument("--approve", default="Yes, please remember that.")
    parser.add_argument("--reject", default="No, please don't save that.")
    parser.add_argument("--phi-request", default=DEFAULT_PHI_REQUEST)
    parser.add_argument("--phi-only", action="store_true", help="run only the patient-information refusal")
    parser.add_argument("--no-reset", action="store_true", help="keep existing agent memory in Redis DB /1")
    parser.add_argument("--out", default=str(ROOT / "data" / "eval" / "traces" / "memory_evidence.md"))
    args = parser.parse_args()

    try:
        client = get_redis_client()
        client.ping()
    except Exception as exc:
        print(f"Cannot reach Redis at {memory_redis_url()}: {exc}")
        print("Run: docker compose up -d redis qdrant")
        return 2

    report = Report()
    report.add("# MEM-092 - memory evidence (real model, real Redis, real RAG)")
    report.add()
    report.add(f"Generated: {datetime.now(timezone.utc).isoformat(timespec='seconds')}")
    report.add(f"Memory store: Redis `{memory_redis_url()}` (key prefix `{KEY_PREFIX}:`), separate from the company RAG collection.")
    if not args.no_reset:
        removed = sum(client.delete(key) for key in client.scan_iter(f"{KEY_PREFIX}:*"))
        report.add(f"Reset: removed {removed} `{KEY_PREFIX}:*` keys from this database before starting.")
    report.add()

    if args.phi_only:
        complete = cycle_phi_refused(report, args)
    else:
        complete = cycle_rejected(report, args) and cycle_approved(report, args)
        complete = cycle_phi_refused(report, args) and complete

    passed = sum(1 for _, ok in report.checks if ok)
    report.add("## Result")
    report.add()
    report.add(f"{passed}/{len(report.checks)} checks passed.")
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(report.lines) + "\n", encoding="utf-8")
    print(f"\nTranscript written to {out}")
    return 0 if complete and passed == len(report.checks) else 1


if __name__ == "__main__":
    sys.exit(main())
