"""SQLModel tables for the RFP intake flow (Milestone 9, Parts 1, 2 and 3).

These tables live in the same Supabase/PostgreSQL database as inventory,
telemetry_events and job_runs (see services/api/database.py).

Ticket lifecycle (vocabulary from the HealthCore CONTEXT):
    Part 1: analyzing -> intake_complete
                      -> discarded
    Part 2: intake_complete -> drafting -> under_evaluation
                                        -> needs_human_review
    Part 3: under_evaluation / needs_human_review -> waiting_for_approval -> done
            (a revision requested by a human or by arbitration goes back to `drafting`)

HIPAA / UK GDPR: no column in these tables may hold patient identifiers or PHI.
`phi_findings` only stores COUNTS by type (e.g. {"patient_name": 1}), never values.
Part 3 trace events store REFERENCES (ids / hashes), never content.
"""
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import CheckConstraint, Column, DateTime, Index, JSON, Text, UniqueConstraint
from sqlmodel import Field, SQLModel

# --- Status vocabulary: single source of truth ------------------------------
STATUS_ANALYZING = "analyzing"
STATUS_DISCARDED = "discarded"
STATUS_INTAKE_COMPLETE = "intake_complete"
PART1_STATUSES = (STATUS_ANALYZING, STATUS_DISCARDED, STATUS_INTAKE_COMPLETE)

# Part 2 statuses (response generation + evaluation).
STATUS_DRAFTING = "drafting"
STATUS_UNDER_EVALUATION = "under_evaluation"
STATUS_NEEDS_HUMAN_REVIEW = "needs_human_review"
PART2_STATUSES = (STATUS_DRAFTING, STATUS_UNDER_EVALUATION, STATUS_NEEDS_HUMAN_REVIEW)

# Part 3 statuses (human approval + completion).
STATUS_WAITING_FOR_APPROVAL = "waiting_for_approval"
STATUS_DONE = "done"
PART3_STATUSES = (STATUS_WAITING_FOR_APPROVAL, STATUS_DONE)

ALL_STATUSES = PART1_STATUSES + PART2_STATUSES + PART3_STATUSES

# Handoff flag for Part 2 (same API, same DB: no queue service needed).
ROUTING_PENDING = "pending"
ROUTING_READY_FOR_PART2 = "ready_for_part2"
# PHI was detected: Part 2 must not start until Compliance reviews the ticket.
ROUTING_COMPLIANCE_REVIEW = "compliance_review_required"
# Handoff flag for Part 3: drafts + EvaluationResults are stored for every department.
ROUTING_READY_FOR_PART3 = "ready_for_part3"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class RfpTicket(SQLModel, table=True):
    """One row = one uploaded PDF. The UI polls this row for its status."""

    __tablename__ = "rfp_tickets"
    __table_args__ = (
        CheckConstraint(
            "status IN ('analyzing', 'discarded', 'intake_complete', "
            "'drafting', 'under_evaluation', 'needs_human_review', "
            "'waiting_for_approval', 'done')",
            name="ck_rfp_tickets_status",
        ),
        Index("idx_rfp_tickets_status", "status"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    status: str = Field(default=STATUS_ANALYZING, max_length=32)

    original_filename: str = Field(max_length=255)
    raw_pdf_path: str = Field(max_length=512)
    markdown_path: Optional[str] = Field(default=None, max_length=512)  # REDACTED markdown
    created_by_user_id: Optional[int] = None

    # RFP metadata (client_name, client_country, program_type, covered_population,
    # deadline, budget_range, departments_needed, currency) + document stats.
    rfp_metadata: Optional[dict[str, Any]] = Field(default=None, sa_column=Column(JSON))
    readability: Optional[dict[str, Any]] = Field(default=None, sa_column=Column(JSON))

    # PHI guard (counts by type only, never values).
    contains_phi: bool = Field(default=False)
    phi_findings: Optional[dict[str, Any]] = Field(default=None, sa_column=Column(JSON))

    # Classifier result (hard gate).
    is_rfp: Optional[bool] = None
    classifier_confidence: Optional[float] = None
    classifier_reason: Optional[str] = None
    detected_departments: Optional[list[str]] = Field(default=None, sa_column=Column(JSON))

    # Synthesizer output (what Revenue Cycle reads) + Part 2 handoff.
    summary: Optional[str] = None
    synthesis: Optional[dict[str, Any]] = Field(default=None, sa_column=Column(JSON))
    routing_status: str = Field(default=ROUTING_PENDING, max_length=32)

    error_message: Optional[str] = None

    created_at: datetime = Field(
        default_factory=_utcnow, sa_column=Column(DateTime(timezone=True), nullable=False)
    )
    updated_at: datetime = Field(
        default_factory=_utcnow, sa_column=Column(DateTime(timezone=True), nullable=False)
    )
    classified_at: Optional[datetime] = Field(default=None, sa_column=Column(DateTime(timezone=True)))
    completed_at: Optional[datetime] = Field(default=None, sa_column=Column(DateTime(timezone=True)))


class RfpDepartmentSection(SQLModel, table=True):
    """Output of one worker: key aspects for one department of one ticket."""

    __tablename__ = "rfp_department_sections"
    __table_args__ = (Index("idx_rfp_sections_ticket", "ticket_id"),)

    id: Optional[int] = Field(default=None, primary_key=True)
    ticket_id: int = Field(foreign_key="rfp_tickets.id", nullable=False)
    department: str = Field(max_length=64)  # revenue | clinical | compliance

    key_aspects: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    open_questions: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    suggested_contact_role: Optional[str] = Field(default=None, max_length=255)

    created_at: datetime = Field(
        default_factory=_utcnow, sa_column=Column(DateTime(timezone=True), nullable=False)
    )


class RfpDraftSection(SQLModel, table=True):
    """Part 2 output: the last draft of one department + its EvaluationResult.

    A section that exhausted the iteration limit is NOT dropped: it is stored with
    `needs_human_review = True` and still travels in the handoff to Part 3.
    """

    __tablename__ = "rfp_draft_sections"
    __table_args__ = (Index("idx_rfp_drafts_ticket", "ticket_id"),)

    id: Optional[int] = Field(default=None, primary_key=True)
    ticket_id: int = Field(foreign_key="rfp_tickets.id", nullable=False)
    department: str = Field(max_length=64)

    content: str = Field(default="", sa_column=Column(Text, nullable=False))  # markdown draft
    iterations: int = Field(default=0)
    overall_pass: bool = Field(default=False)
    needs_human_review: bool = Field(default=False)
    # EvaluationResult: readability / relevance / compliance / overall_pass / feedback.
    evaluation: Optional[dict[str, Any]] = Field(default=None, sa_column=Column(JSON))

    created_at: datetime = Field(
        default_factory=_utcnow, sa_column=Column(DateTime(timezone=True), nullable=False)
    )
    updated_at: datetime = Field(
        default_factory=_utcnow, sa_column=Column(DateTime(timezone=True), nullable=False)
    )


# --- Part 3 tables ----------------------------------------------------------


class RfpApproval(SQLModel, table=True):
    """Part 3: approval state of ONE department section of ONE ticket.

    The draft text itself stays in `rfp_draft_sections.content`; this row holds who
    approved it, how many revisions it went through and the structured facts the
    arbitration rules read (covered population, committed capacity). No PHI here.
    """

    __tablename__ = "rfp_approvals"
    __table_args__ = (
        UniqueConstraint("ticket_id", "department", name="uq_rfp_approvals_ticket_dept"),
        CheckConstraint(
            "approval_status IN ('pending', 'approved', 'rejected', 'changes_requested')",
            name="ck_rfp_approvals_status",
        ),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    ticket_id: int = Field(foreign_key="rfp_tickets.id", nullable=False, index=True)
    department: str = Field(max_length=64)

    approval_status: str = Field(default="pending", max_length=32)
    approver: Optional[str] = Field(default=None, max_length=128)  # normalized owner id
    approved_at: Optional[datetime] = Field(default=None, sa_column=Column(DateTime(timezone=True)))
    revision_count: int = Field(default=0)
    requested_changes: Optional[str] = Field(default=None, sa_column=Column(Text))

    structured: Optional[dict[str, Any]] = Field(default=None, sa_column=Column(JSON))
    contains_phi: bool = Field(default=False)

    updated_at: datetime = Field(
        default_factory=_utcnow, sa_column=Column(DateTime(timezone=True), nullable=False)
    )


class RfpTraceEvent(SQLModel, table=True):
    """Part 3: one executed node (agent, input ref, output ref, timestamp)."""

    __tablename__ = "rfp_trace_events"
    __table_args__ = (Index("idx_rfp_trace_ticket", "ticket_id"),)

    id: Optional[int] = Field(default=None, primary_key=True)
    ticket_id: int = Field(foreign_key="rfp_tickets.id", nullable=False)
    ts: str = Field(max_length=32)  # ISO-8601 UTC, second resolution
    agent: str = Field(max_length=128)
    department: Optional[str] = Field(default=None, max_length=64)
    input_ref: str = Field(max_length=512)
    output_ref: str = Field(max_length=512)


class RfpFinalDocument(SQLModel, table=True):
    """Part 3: the consolidated proposal, stored once every approval is in."""

    __tablename__ = "rfp_final_documents"

    id: Optional[int] = Field(default=None, primary_key=True)
    ticket_id: int = Field(foreign_key="rfp_tickets.id", nullable=False, unique=True)
    content_md: str = Field(default="", sa_column=Column(Text, nullable=False))
    path: Optional[str] = Field(default=None, max_length=512)
    document: Optional[dict[str, Any]] = Field(default=None, sa_column=Column(JSON))
    generated_at: str = Field(max_length=32)
