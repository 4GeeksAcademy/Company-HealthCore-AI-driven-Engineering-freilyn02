"""Human-in-the-loop approval, one scoped graph branch per department.

Design (see the Milestone 9 Part 3 reference solution):

* Each department has its OWN compiled-graph run and its OWN checkpoint thread
  (`rfp-{ticket_id}:{department}`), so pausing `legal`/`compliance` never blocks
  `revenue` or `clinical` (scoped interrupt, true parallelism).
* `human_approval` calls `interrupt()` as its very first statement: the state is
  checkpointed before the pause and the node has no side effects before it.
* Resume is an explicit entry point (`submit_department_decision`): the human payload
  is validated (named owner, required fields, draft not stale) BEFORE it re-enters the
  graph, and the run continues from the checkpoint - it never restarts.
* Reject / request_changes go back to the Part 2 generator through `revision_hook`
  (documented edge `request_revision -> prepare_review`), bounded by
  `max_revisions` so the loop always terminates.
"""

from __future__ import annotations

import operator
from typing import Annotated, Any, Callable, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt

from .checkpointer import thread_config
from .models import (
    DEPARTMENT_OWNERS,
    MAX_REVISION_CYCLES,
    PHI_WITHHELD_SUMMARY,
    REDACTION_PLACEHOLDER,
    STATUS_DONE,
    STATUS_DRAFTING,
    STATUS_WAITING_FOR_APPROVAL,
    ApprovalStatus,
    Decision,
    InterruptPayload,
    ResumePayload,
    SectionRecord,
    SectionUpdate,
    utc_now,
)
from .store import TicketStore
from .trace import record

# (ticket_id, department, reason, previous_section) -> regenerated section.
# In production this wraps your Part 2 generator + evaluator loop.
RevisionHook = Callable[[str, str, str, SectionRecord], SectionUpdate]


class NoPendingApproval(RuntimeError):
    """The department has no pending interrupt (already decided or never started)."""


class StaleDraftError(RuntimeError):
    """The draft changed after the approval request was issued."""


class DeptState(TypedDict, total=False):
    ticket_id: str
    department: str
    interrupt_payload: dict[str, Any]
    draft_hash: str
    resume: dict[str, Any]
    outcome: str
    revision_reason: str
    trace: Annotated[list[dict[str, Any]], operator.add]


# --------------------------------------------------------------------------- #
# Shared revision logic (also used by arbitration)
# --------------------------------------------------------------------------- #


def apply_revision(
    store: TicketStore,
    ticket_id: str,
    department: str,
    reason: str,
    *,
    hook: RevisionHook | None,
    max_revisions: int = MAX_REVISION_CYCLES,
    redact: bool = False,
) -> str:
    """Send a section back to Part 2.

    Returns one of:
      - "revised"            new draft stored, approval reset to pending
      - "awaiting_revision"  no hook configured; Part 2 must call submit_revised_draft
      - "iteration_limit"    cap reached; section is terminally `rejected`
    """
    section = store.get_section(ticket_id, department)

    if redact:
        # Hard stop for PHI: the offending content must not stay in the ticket.
        section.draft_content = REDACTION_PLACEHOLDER

    section.approver = None
    section.approved_at = None
    section.requested_changes = reason

    if section.revision_count >= max_revisions:
        section.approval_status = ApprovalStatus.REJECTED
        store.upsert_section(section)
        return "iteration_limit"

    section.revision_count += 1
    section.approval_status = ApprovalStatus.CHANGES_REQUESTED
    store.upsert_section(section)
    if store.get_status(ticket_id) != STATUS_DONE:
        store.set_status(ticket_id, STATUS_DRAFTING)

    if hook is None:
        return "awaiting_revision"

    update = hook(ticket_id, department, reason, section)
    store_revised_draft(store, ticket_id, department, update)
    return "revised"


def store_revised_draft(
    store: TicketStore, ticket_id: str, department: str, update: SectionUpdate
) -> SectionRecord:
    section = store.get_section(ticket_id, department)
    section.draft_content = update.draft_content
    section.structured = update.structured
    section.contains_phi = update.contains_phi
    section.evaluation_results = update.evaluation_results
    section.approval_status = ApprovalStatus.PENDING
    section.approver = None
    section.approved_at = None
    store.upsert_section(section)
    return section


# --------------------------------------------------------------------------- #
# Department graph
# --------------------------------------------------------------------------- #


def build_department_graph(
    store: TicketStore,
    checkpointer: Any,
    *,
    revision_hook: RevisionHook | None = None,
    max_revisions: int = MAX_REVISION_CYCLES,
):
    def prepare_review(state: DeptState) -> dict[str, Any]:
        ticket_id, department = state["ticket_id"], state["department"]
        section = store.get_section(ticket_id, department)
        summary = (
            PHI_WITHHELD_SUMMARY
            if section.phi_flagged
            else section.draft_content[:400]
        )
        payload = InterruptPayload(
            ticket_id=ticket_id,
            department=department,
            owner=next(iter(DEPARTMENT_OWNERS[department].values())),
            section_summary=summary,
            evaluation_snapshot={
                "passed": section.evaluation_results.get("passed"),
                "iterations": section.evaluation_results.get("iterations"),
                "contains_phi": section.phi_flagged,
            },
            draft_hash=section.draft_hash,
            revision=section.revision_count,
        )
        if store.get_status(ticket_id) != STATUS_DONE:
            store.set_status(ticket_id, STATUS_WAITING_FOR_APPROVAL)
        return {
            "interrupt_payload": payload.model_dump(mode="json"),
            "draft_hash": section.draft_hash,
            "outcome": "",
            "resume": {},
            "trace": record(
                store,
                ticket_id=ticket_id,
                department=department,
                agent="approval_prepare",
                input_ref=f"section:{ticket_id}:{department}:r{section.revision_count}",
                output_ref=f"interrupt_payload:{section.draft_hash[:12]}",
            ),
        }

    def human_approval(state: DeptState) -> dict[str, Any]:
        # First statement on purpose: nothing before the pause can run twice.
        raw = interrupt(state["interrupt_payload"])
        payload = ResumePayload.model_validate(raw)  # defense in depth
        return {
            "resume": payload.model_dump(mode="json"),
            "trace": record(
                store,
                ticket_id=state["ticket_id"],
                department=state["department"],
                agent=f"human:{payload.actor}",
                input_ref=f"draft:{state['draft_hash'][:12]}",
                output_ref=f"decision:{payload.decision.value}",
            ),
        }

    def record_decision(state: DeptState) -> dict[str, Any]:
        ticket_id, department = state["ticket_id"], state["department"]
        payload = ResumePayload.model_validate(state["resume"])
        section = store.get_section(ticket_id, department)

        if section.draft_hash != state["draft_hash"]:
            outcome, reason = "stale", ""
        elif payload.decision is Decision.APPROVE:
            section.approval_status = ApprovalStatus.APPROVED
            section.approver = payload.actor
            section.approved_at = utc_now()
            section.requested_changes = None
            store.upsert_section(section)
            outcome, reason = "approved", ""
        else:
            outcome = (
                "changes_requested"
                if payload.decision is Decision.REQUEST_CHANGES
                else "rejected"
            )
            reason = (
                payload.requested_changes
                if payload.decision is Decision.REQUEST_CHANGES
                else payload.comment
            ) or ""

        return {
            "outcome": outcome,
            "revision_reason": reason,
            "trace": record(
                store,
                ticket_id=ticket_id,
                department=department,
                agent="approval_record",
                input_ref=f"decision:{payload.decision.value}",
                output_ref=f"outcome:{outcome}",
            ),
        }

    def request_revision(state: DeptState) -> dict[str, Any]:
        ticket_id, department = state["ticket_id"], state["department"]
        result = apply_revision(
            store,
            ticket_id,
            department,
            state["revision_reason"],
            hook=revision_hook,
            max_revisions=max_revisions,
        )
        return {
            "outcome": result,
            "trace": record(
                store,
                ticket_id=ticket_id,
                department=department,
                agent="part2_revision",
                input_ref=f"reason_for:{department}",
                output_ref=f"revision:{result}",
            ),
        }

    def after_decision(state: DeptState) -> str:
        return "request_revision" if state["outcome"] in ("rejected", "changes_requested") else END

    def after_revision(state: DeptState) -> str:
        # Documented edge: a regenerated draft needs a NEW human approval.
        return "prepare_review" if state["outcome"] == "revised" else END

    graph = StateGraph(DeptState)
    graph.add_node("prepare_review", prepare_review)
    graph.add_node("human_approval", human_approval)
    graph.add_node("record_decision", record_decision)
    graph.add_node("request_revision", request_revision)
    graph.add_edge(START, "prepare_review")
    graph.add_edge("prepare_review", "human_approval")
    graph.add_edge("human_approval", "record_decision")
    graph.add_conditional_edges(
        "record_decision", after_decision, {"request_revision": "request_revision", END: END}
    )
    graph.add_conditional_edges(
        "request_revision", after_revision, {"prepare_review": "prepare_review", END: END}
    )
    return graph.compile(checkpointer=checkpointer)


# --------------------------------------------------------------------------- #
# Entry points (start / resume / inspect)
# --------------------------------------------------------------------------- #


def start_department(dept_graph: Any, ticket_id: str, department: str) -> dict[str, Any]:
    """(Re)start the approval branch of one department. A new run on a thread that is
    paused on an old draft replaces that stale interrupt."""
    return dept_graph.invoke(
        {"ticket_id": ticket_id, "department": department},
        thread_config(ticket_id, department),
    )


def pending_interrupt(
    dept_graph: Any, ticket_id: str, department: str
) -> InterruptPayload | None:
    snap = dept_graph.get_state(thread_config(ticket_id, department))
    if not snap.next:
        return None
    return InterruptPayload.model_validate(snap.values["interrupt_payload"])


def submit_department_decision(
    dept_graph: Any, store: TicketStore, ticket_id: str, raw_payload: dict[str, Any] | ResumePayload
) -> dict[str, Any]:
    """Validate a human decision and resume ONLY that department's branch.

    Raises pydantic.ValidationError (bad payload / wrong actor), NoPendingApproval or
    StaleDraftError. Nothing invalid ever reaches the graph.
    """
    payload = (
        raw_payload
        if isinstance(raw_payload, ResumePayload)
        else ResumePayload.model_validate(raw_payload)
    )
    config = thread_config(ticket_id, payload.department)
    snap = dept_graph.get_state(config)
    if not snap.next:
        raise NoPendingApproval(
            f"no pending approval for {ticket_id}/{payload.department}"
        )
    expected = snap.values["draft_hash"]
    current = store.get_section(ticket_id, payload.department).draft_hash
    if expected != current:
        raise StaleDraftError(
            f"draft of {payload.department} changed after the approval request"
        )
    return dept_graph.invoke(Command(resume=payload.model_dump(mode="json")), config)
