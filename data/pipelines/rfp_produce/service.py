"""ApprovalWorkflow: the public API of Part 3.

    wf = ApprovalWorkflow(store=..., checkpointer=get_checkpointer(), revision_hook=...)
    wf.start("rfp-1042")                      # one scoped interrupt per department
    wf.submit_decision("rfp-1042", {...})     # validated resume of ONE department
    wf.status("rfp-1042")                     # who approved, who is pending, done?

After every decision a ticket-level "closing graph" runs:

    gate --(conflict)--> arbitration --> END
      |--(all approved, no conflict)--> ultimate_synthesizer --> END
      `--(otherwise)--> END   (ticket stays waiting_for_approval)

Routers (`services/.../routers/rfp.py`) only call this class; they own no agent logic.
"""

from __future__ import annotations

import operator
from pathlib import Path
from typing import Annotated, Any, TypedDict

from langgraph.graph import END, START, StateGraph

from .approval import (
    RevisionHook,
    apply_revision,
    build_department_graph,
    pending_interrupt,
    start_department,
    store_revised_draft,
    submit_department_decision,
)
from .arbitration import detect_conflicts, make_arbitration_node, plan_resolutions
from .checkpointer import thread_config
from .models import (
    ALLOWED_START_STATUSES,
    MAX_REVISION_CYCLES,
    ApprovalStatus,
    FinalDocument,
    ResumePayload,
    SectionUpdate,
    TraceEvent,
)
from .store import TicketStore
from .synthesizer import DEFAULT_OUTPUT_DIR, synthesize_final_document
from .trace import record


class ClosingState(TypedDict, total=False):
    ticket_id: str
    conflicts: list[dict[str, Any]]
    resolutions: list[dict[str, Any]]
    action_results: dict[str, str]
    outcome: str
    trace: Annotated[list[dict[str, Any]], operator.add]


class ApprovalWorkflow:
    def __init__(
        self,
        store: TicketStore,
        checkpointer: Any,
        *,
        revision_hook: RevisionHook | None = None,
        max_revisions: int = MAX_REVISION_CYCLES,
        output_dir: str | Path = DEFAULT_OUTPUT_DIR,
    ) -> None:
        self.store = store
        self.revision_hook = revision_hook
        self.max_revisions = max_revisions
        self.output_dir = output_dir
        self.dept_graph = build_department_graph(
            store, checkpointer, revision_hook=revision_hook, max_revisions=max_revisions
        )
        self.closing_graph = self._build_closing_graph(checkpointer)

    # ------------------------------------------------------------------ #
    # public API
    # ------------------------------------------------------------------ #
    def start(self, ticket_id: str) -> dict[str, Any]:
        """Open one scoped approval branch per required department."""
        status = self.store.get_status(ticket_id)
        if status not in ALLOWED_START_STATUSES:
            raise ValueError(
                f"ticket {ticket_id} has status {status!r}; Part 3 starts from "
                f"{sorted(ALLOWED_START_STATUSES)}"
            )
        meta = self.store.get_meta(ticket_id)
        sections = {s.department_id: s for s in self.store.list_sections(ticket_id)}
        missing = [d for d in meta.required_departments if d not in sections]
        if missing:
            raise ValueError(f"ticket {ticket_id} has no Part 2 draft for: {missing}")

        for dept in meta.required_departments:
            section = sections[dept]
            if section.approval_status is not ApprovalStatus.PENDING:
                continue
            pending = pending_interrupt(self.dept_graph, ticket_id, dept)
            if pending is not None and pending.draft_hash == section.draft_hash:
                continue  # idempotent: already waiting for this exact draft
            start_department(self.dept_graph, ticket_id, dept)

        return self._close(ticket_id)

    def submit_decision(
        self, ticket_id: str, payload: dict[str, Any] | ResumePayload
    ) -> dict[str, Any]:
        """Validate + resume ONE department, then evaluate the ticket as a whole."""
        submit_department_decision(self.dept_graph, self.store, ticket_id, payload)
        return self._close(ticket_id)

    def submit_revised_draft(
        self, ticket_id: str, department: str, update: SectionUpdate
    ) -> dict[str, Any]:
        """Used by Part 2 when it regenerates a draft asynchronously (no revision_hook)."""
        store_revised_draft(self.store, ticket_id, department, update)
        start_department(self.dept_graph, ticket_id, department)
        return self._close(ticket_id)

    def status(self, ticket_id: str) -> dict[str, Any]:
        meta = self.store.get_meta(ticket_id)
        sections = {s.department_id: s for s in self.store.list_sections(ticket_id)}
        departments: dict[str, Any] = {}
        pending: list[str] = []
        for dept in meta.required_departments:
            section = sections.get(dept)
            if section is None:
                continue
            departments[dept] = {
                "approval_status": section.approval_status.value,
                "approver": section.approver,
                "revision_count": section.revision_count,
            }
            waiting = pending_interrupt(self.dept_graph, ticket_id, dept)
            if waiting is not None and section.approval_status is ApprovalStatus.PENDING:
                pending.append(dept)
        final = self.store.get_final_document(ticket_id)
        return {
            "ticket_id": ticket_id,
            "status": self.store.get_status(ticket_id),
            "departments": departments,
            "pending_approvals": pending,
            "blocked": any(
                s.approval_status is ApprovalStatus.REJECTED
                for d, s in sections.items()
                if d in meta.required_departments
            ),
            "final_document": final.path if final else None,
        }

    def pending_payloads(self, ticket_id: str) -> list[dict[str, Any]]:
        meta = self.store.get_meta(ticket_id)
        out = []
        for dept in meta.required_departments:
            payload = pending_interrupt(self.dept_graph, ticket_id, dept)
            if payload is not None:
                out.append(payload.model_dump(mode="json"))
        return out

    def trace(self, ticket_id: str) -> list[TraceEvent]:
        return self.store.list_trace(ticket_id)

    def final_document(self, ticket_id: str) -> FinalDocument | None:
        return self.store.get_final_document(ticket_id)

    # ------------------------------------------------------------------ #
    # closing graph
    # ------------------------------------------------------------------ #
    def _close(self, ticket_id: str) -> dict[str, Any]:
        result = self.closing_graph.invoke({"ticket_id": ticket_id}, thread_config(ticket_id))
        summary = self.status(ticket_id)
        summary["closing_outcome"] = result.get("outcome")
        summary["resolutions"] = result.get("resolutions", [])
        return summary

    def _apply_action(self, ticket_id: str, department: str, action: dict[str, Any]) -> str:
        if action["kind"] == "reopen":
            section = self.store.get_section(ticket_id, department)
            section.approval_status = ApprovalStatus.PENDING
            section.approver = None
            section.approved_at = None
            self.store.upsert_section(section)
            start_department(self.dept_graph, ticket_id, department)
            return "reopened"

        result = apply_revision(
            self.store,
            ticket_id,
            department,
            action["reason"],
            hook=self.revision_hook,
            max_revisions=self.max_revisions,
            redact=action["redact"],
        )
        if result == "revised":
            start_department(self.dept_graph, ticket_id, department)
        return result

    def _build_closing_graph(self, checkpointer: Any):
        store = self.store

        def gate(state: ClosingState) -> dict[str, Any]:
            ticket_id = state["ticket_id"]
            meta = store.get_meta(ticket_id)
            sections = store.list_sections(ticket_id)
            approved = sorted(
                s.department_id
                for s in sections
                if s.department_id in meta.required_departments
                and s.approval_status is ApprovalStatus.APPROVED
            )
            conflicts = detect_conflicts(meta, sections)
            actionable = bool(plan_resolutions(conflicts, sections)["actions"]) if conflicts else False
            all_approved = approved == sorted(meta.required_departments)
            blocked = any(
                s.approval_status is ApprovalStatus.REJECTED
                for s in sections
                if s.department_id in meta.required_departments
            )

            if actionable:
                route = "arbitration"
            elif conflicts:
                route = "waiting"  # conflicts exist but a revision is already in flight
            elif all_approved:
                route = "synthesize"
            else:
                route = "blocked" if blocked else "waiting"

            return {
                "conflicts": conflicts,
                "resolutions": [],
                "action_results": {},
                "outcome": route,
                "trace": record(
                    store,
                    ticket_id=ticket_id,
                    agent="gate",
                    input_ref=f"approved:{','.join(approved) or 'none'}",
                    output_ref=f"route:{route}",
                ),
            }

        def synthesize(state: ClosingState) -> dict[str, Any]:
            ticket_id = state["ticket_id"]
            doc = synthesize_final_document(store, ticket_id, self.output_dir)
            return {
                "outcome": "done",
                "trace": record(
                    store,
                    ticket_id=ticket_id,
                    agent="ultimate_synthesizer",
                    input_ref=f"approved_sections:{len(doc.sections)}",
                    output_ref=f"final_doc_{ticket_id}.md",
                ),
            }

        def route(state: ClosingState) -> str:
            outcome = state["outcome"]
            return outcome if outcome in ("arbitration", "synthesize") else END

        graph = StateGraph(ClosingState)
        graph.add_node("gate", gate)
        graph.add_node("arbitration", make_arbitration_node(store, self._apply_action))
        graph.add_node("synthesize", synthesize)
        graph.add_edge(START, "gate")
        graph.add_conditional_edges(
            "gate", route, {"arbitration": "arbitration", "synthesize": "synthesize", END: END}
        )
        graph.add_edge("arbitration", END)
        graph.add_edge("synthesize", END)
        return graph.compile(checkpointer=checkpointer)
