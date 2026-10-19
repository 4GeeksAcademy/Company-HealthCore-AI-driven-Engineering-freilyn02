"""Shared models and constants for RFP Part 3 (Approval & Document Completion).

All identifiers follow the HealthCore CONTEXT (Milestone 9):
- Department ids and owners: section 2.1
- Ticket statuses: section 2.3
- Conflict triggers / fixed arbiters: section 7

HIPAA / UK GDPR rule: nothing in this module (or any model built on it) may carry
patient identifiers or PHI. Trace events store *references*, never content.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

# --------------------------------------------------------------------------- #
# Constants taken from CONTEXT-healthcore
# --------------------------------------------------------------------------- #

# Order is also the order of sections in the final document.
DEPARTMENT_ORDER: tuple[str, ...] = ("revenue", "clinical", "compliance")

# Compliance is mandatory on every RFP, without exception (CONTEXT 2.1 / 5).
MANDATORY_DEPARTMENTS: frozenset[str] = frozenset({"compliance"})

# Named owner of each department (CONTEXT 2.1). These are the ONLY people who can
# sign off. Keys are normalized actor ids (lowercase, dot separated).
DEPARTMENT_OWNERS: dict[str, dict[str, str]] = {
    "revenue": {"tom.callahan": "Tom Callahan"},
    "clinical": {"marcus.reid": "Dr. Marcus Reid"},
    "compliance": {"claire.whitfield": "Claire Whitfield"},
}

# Ticket statuses (CONTEXT 2.3). Part 3 only *writes* waiting_for_approval and done;
# `drafting` is the Part 2 status we go back to when a section is sent for revision.
STATUS_DRAFTING = "drafting"
STATUS_UNDER_EVALUATION = "under_evaluation"
STATUS_NEEDS_HUMAN_REVIEW = "needs_human_review"
STATUS_WAITING_FOR_APPROVAL = "waiting_for_approval"
STATUS_DONE = "done"

# Statuses a ticket may have when Part 3 starts (Part 2 hand-off).
# NOTE: adjust if your Part 2 leaves a different status when every evaluator passes.
ALLOWED_START_STATUSES: frozenset[str] = frozenset(
    {STATUS_UNDER_EVALUATION, STATUS_NEEDS_HUMAN_REVIEW, STATUS_WAITING_FOR_APPROVAL}
)

# Hard cap on revision cycles per department (reject / request_changes / forced by
# arbitration). When it is reached the section becomes terminally `rejected`.
MAX_REVISION_CYCLES = 3

REDACTION_PLACEHOLDER = "[REDACTED: content blocked by Compliance arbitration (phi-detected)]"
PHI_WITHHELD_SUMMARY = "[withheld: PHI flag set - Compliance review required]"

# Clause instruments (CONTEXT 5)
CLAUSE_BAA = "BAA"
CLAUSE_DPA_UK = "DPA_UK_GDPR"

CURRENCY_BY_COUNTRY = {"US": "USD", "UK": "GBP"}


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def utc_now_iso() -> str:
    return utc_now().strftime("%Y-%m-%dT%H:%M:%SZ")


# --------------------------------------------------------------------------- #
# Enums
# --------------------------------------------------------------------------- #


class ApprovalStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    CHANGES_REQUESTED = "changes_requested"


class Decision(StrEnum):
    APPROVE = "approve"
    REJECT = "reject"
    REQUEST_CHANGES = "request_changes"


# --------------------------------------------------------------------------- #
# Clause helpers (so the BAA/DPA trigger works on structured state)
# --------------------------------------------------------------------------- #

_BAA_RE = re.compile(r"\bbusiness associate agreement\b|\bBAA\b", re.IGNORECASE)
_DPA_RE = re.compile(r"\bdata processing agreement\b|\bDPA\b", re.IGNORECASE)
_UK_GDPR_RE = re.compile(r"\buk[\s-]?gdpr\b", re.IGNORECASE)


def derive_clauses(text: str) -> list[str]:
    """Derive structured clause ids from free text.

    Used only as a fallback when Part 2 did not store `structured["clauses"]`.
    A DPA only counts as UK instrument when UK GDPR is referenced (CONTEXT 5).
    """
    clauses: list[str] = []
    if _BAA_RE.search(text or ""):
        clauses.append(CLAUSE_BAA)
    if _DPA_RE.search(text or "") and _UK_GDPR_RE.search(text or ""):
        clauses.append(CLAUSE_DPA_UK)
    return clauses


# --------------------------------------------------------------------------- #
# Domain models
# --------------------------------------------------------------------------- #


class RFPMeta(BaseModel):
    """Minimal RFP metadata Part 3 needs. Never contains patient data."""

    ticket_id: str
    client_name: str
    client_country: Literal["US", "UK"]
    departments_needed: list[str] = Field(default_factory=list)

    @property
    def currency(self) -> str:
        return CURRENCY_BY_COUNTRY[self.client_country]

    @property
    def required_departments(self) -> list[str]:
        """departments_needed + compliance (always), in canonical order."""
        needed = set(self.departments_needed) | set(MANDATORY_DEPARTMENTS)
        return [d for d in DEPARTMENT_ORDER if d in needed]


class SectionRecord(BaseModel):
    """One department section of the proposal (Part 2 draft + Part 3 approval)."""

    ticket_id: str
    department_id: str
    draft_content: str
    # Structured facts used by arbitration, e.g.
    #   revenue:    {"covered_population": 800}
    #   clinical:   {"committed_capacity": 900}
    #   compliance: {"clauses": ["BAA"]}
    structured: dict[str, Any] = Field(default_factory=dict)
    contains_phi: bool = False
    evaluation_results: dict[str, Any] = Field(default_factory=dict)
    approval_status: ApprovalStatus = ApprovalStatus.PENDING
    approver: str | None = None
    approved_at: datetime | None = None
    revision_count: int = 0
    requested_changes: str | None = None

    @property
    def draft_hash(self) -> str:
        """Fingerprint of the exact draft a human is approving."""
        blob = json.dumps(
            {"draft": self.draft_content, "structured": self.structured},
            sort_keys=True,
            default=str,
        )
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()

    @property
    def phi_flagged(self) -> bool:
        return bool(self.contains_phi or self.evaluation_results.get("contains_phi"))

    def effective_clauses(self) -> list[str]:
        explicit = self.structured.get("clauses")
        if explicit is not None:
            return list(explicit)
        return derive_clauses(self.draft_content)


class SectionUpdate(BaseModel):
    """A regenerated draft coming back from the Part 2 loop (revision hook)."""

    draft_content: str
    structured: dict[str, Any] = Field(default_factory=dict)
    contains_phi: bool = False
    evaluation_results: dict[str, Any] = Field(default_factory=dict)


class InterruptPayload(BaseModel):
    """What the human sees at the approval point (kept small on purpose)."""

    ticket_id: str
    department: str
    owner: str
    section_summary: str
    evaluation_snapshot: dict[str, Any]
    draft_hash: str
    revision: int
    actions: list[str] = Field(
        default_factory=lambda: [d.value for d in Decision]
    )


class ResumePayload(BaseModel):
    """Human decision. Validated BEFORE it is allowed back into the graph."""

    department: str
    decision: Decision
    actor: str
    comment: str | None = None
    requested_changes: str | None = None

    @field_validator("actor")
    @classmethod
    def _normalize_actor(cls, value: str) -> str:
        return value.strip().lower()

    @model_validator(mode="after")
    def _validate(self) -> "ResumePayload":
        if self.department not in DEPARTMENT_OWNERS:
            raise ValueError(f"unknown department: {self.department!r}")
        if self.actor not in DEPARTMENT_OWNERS[self.department]:
            raise ValueError(
                f"actor {self.actor!r} is not the owner of department "
                f"{self.department!r} (CONTEXT 2.1)"
            )
        if self.decision is Decision.REQUEST_CHANGES and not (
            self.requested_changes and self.requested_changes.strip()
        ):
            raise ValueError("request_changes requires non-empty requested_changes")
        if self.decision is Decision.REJECT and not (
            self.comment and self.comment.strip()
        ):
            raise ValueError("reject requires a non-empty comment")
        return self


class TraceEvent(BaseModel):
    """One node execution: which agent did what, in which order.

    `input_ref` / `output_ref` are references (ids, hashes), never content, so the
    trace can never leak PHI.
    """

    ts: str = Field(default_factory=utc_now_iso)
    ticket_id: str
    agent: str
    department: str | None = None
    input_ref: str
    output_ref: str


class FinalDocument(BaseModel):
    ticket_id: str
    client_name: str
    currency: str
    generated_at: str
    sections: list[dict[str, Any]]
    trace_ref: str
    path: str | None = None
