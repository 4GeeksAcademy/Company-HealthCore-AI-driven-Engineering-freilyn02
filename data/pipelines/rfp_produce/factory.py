"""Wiring: builds the Part 3 workflow on top of the real database and the Part 2 generator.

    from data.pipelines.rfp_produce.factory import get_workflow
    workflow = get_workflow()          # one instance per process (cached)

The revision hook is the bridge to Part 2: when a human (or the arbitration node) asks for
changes, the department draft is regenerated with that feedback by the SAME generator and
evaluators Part 2 uses, bounded by Part 2's own MAX_ITERATIONS.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any, Callable

from sqlalchemy.engine import Engine
from sqlmodel import Session

from ..rfp_intake.models import RfpTicket
from ..rfp_intake.phi import redact_text, scrub_obj
from .checkpointer import get_checkpointer
from .models import REDACTION_PLACEHOLDER, SectionRecord, SectionUpdate
from .service import ApprovalWorkflow
from .sql_store import SqlTicketStore, detect_phi, extract_structured

Generate = Callable[..., str]
Evaluate = Callable[..., dict[str, Any]]
HandoffFor = Callable[[Session, RfpTicket, str], dict[str, Any]]


def _default_handoff_for(session: Session, ticket: RfpTicket, department: str) -> dict[str, Any]:
    from ..rfp_response.service import build_handoffs

    return build_handoffs(session, ticket)[department]


def make_sql_revision_hook(
    engine: Engine,
    *,
    generate: Generate | None = None,
    evaluate: Evaluate | None = None,
    handoff_for: HandoffFor | None = None,
    max_iterations: int | None = None,
):
    """Return a `RevisionHook` that re-runs the Part 2 generator + evaluators with feedback.

    All collaborators are injectable so tests never call a real LLM.
    """

    def hook(ticket_id: str, department: str, reason: str, previous: SectionRecord) -> SectionUpdate:
        gen = generate
        ev = evaluate
        limit = max_iterations
        if gen is None or ev is None:
            from ..rfp_response import evaluators, generators

            gen = gen or generators.generate_section
            ev = ev or evaluators.evaluate_section
        if limit is None:
            from ..rfp_response.config import MAX_ITERATIONS

            limit = MAX_ITERATIONS

        with Session(engine) as session:
            ticket = session.get(RfpTicket, int(ticket_id))
            if ticket is None:
                raise KeyError(f"unknown ticket {ticket_id}")
            handoff = (handoff_for or _default_handoff_for)(session, ticket, department)
            rfp_metadata = dict(ticket.rfp_metadata or {})

        # A redacted placeholder is not a useful "previous draft" to rewrite.
        draft: str | None = (
            None if previous.draft_content.startswith(REDACTION_PLACEHOLDER[:24]) else previous.draft_content
        )
        feedback: str | None = reason
        evaluation: dict[str, Any] = {}
        iterations = 0
        for _ in range(max(1, limit)):
            iterations += 1
            draft = gen(department, handoff, feedback=feedback, previous_draft=draft)
            evaluation = ev(department, draft, handoff)
            if evaluation.get("overall_pass"):
                break
            feedback = evaluation.get("feedback_for_generator") or reason

        evaluation["iterations"] = iterations
        content = redact_text(draft or "")
        evaluation = scrub_obj(evaluation)
        return SectionUpdate(
            draft_content=content,
            structured=extract_structured(department, content, rfp_metadata),
            contains_phi=detect_phi(content, evaluation),
            evaluation_results=evaluation,
        )

    return hook


def build_workflow(engine: Engine, checkpointer: Any = None, **kwargs: Any) -> ApprovalWorkflow:
    return ApprovalWorkflow(
        SqlTicketStore(engine),
        checkpointer if checkpointer is not None else get_checkpointer(),
        revision_hook=kwargs.pop("revision_hook", None) or make_sql_revision_hook(engine),
        **kwargs,
    )


@lru_cache(maxsize=1)
def get_workflow() -> ApprovalWorkflow:
    """Process-wide workflow bound to the API's engine (database.engine)."""
    from database import engine  # services/api/database.py

    return build_workflow(engine)
