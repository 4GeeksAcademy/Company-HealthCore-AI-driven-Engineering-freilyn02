"""SQLModel tables for the RFP intake flow (Milestone 9, Part 1).

These tables live in the same Supabase/PostgreSQL database as inventory,
telemetry_events and job_runs (see services/api/database.py).

Ticket lifecycle in Part 1 (vocabulary from the HealthCore CONTEXT):
    analyzing -> intake_complete
              -> discarded
Statuses of Parts 2 and 3 (drafting, under_evaluation, ...) must NOT be set here.

HIPAA / UK GDPR: no column in these tables may hold patient identifiers or PHI.
`phi_findings` only stores COUNTS by type (e.g. {"patient_name": 1}), never values.
"""
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import CheckConstraint, Column, DateTime, Index, JSON
from sqlmodel import Field, SQLModel

# --- Status vocabulary: single source of truth ------------------------------
STATUS_ANALYZING = "analyzing"
STATUS_DISCARDED = "discarded"
STATUS_INTAKE_COMPLETE = "intake_complete"
PART1_STATUSES = (STATUS_ANALYZING, STATUS_DISCARDED, STATUS_INTAKE_COMPLETE)

# Handoff flag for Part 2 (same API, same DB: no queue service needed).
ROUTING_PENDING = "pending"
ROUTING_READY_FOR_PART2 = "ready_for_part2"
# PHI was detected: Part 2 must not start until Compliance reviews the ticket.
ROUTING_COMPLIANCE_REVIEW = "compliance_review_required"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class RfpTicket(SQLModel, table=True):
    """One row = one uploaded PDF. The UI polls this row for its status."""

    __tablename__ = "rfp_tickets"
    __table_args__ = (
        CheckConstraint(
            "status IN ('analyzing', 'discarded', 'intake_complete')",
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
