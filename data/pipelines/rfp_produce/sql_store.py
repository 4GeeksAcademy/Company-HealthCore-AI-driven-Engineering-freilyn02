"""SQLModel implementation of the Part 3 `TicketStore`.

Reads the Part 1/2 tables (`rfp_tickets`, `rfp_draft_sections`) and writes the Part 3
tables (`rfp_approvals`, `rfp_trace_events`, `rfp_final_documents`).

* The Part 3 module identifies tickets by string; the database uses integers.
  `str(ticket.id)` <-> `int(ticket_id)` conversion lives ONLY in this file.
* One new `Session` per call, so the store is safe to share between FastAPI worker
  threads and background tasks.
* Draft text is never duplicated: `rfp_draft_sections.content` stays the single copy.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.engine import Engine
from sqlmodel import Session, select

from ..rfp_intake.models import (
    RfpApproval,
    RfpDraftSection,
    RfpFinalDocument,
    RfpTicket,
    RfpTraceEvent,
)
from ..rfp_intake.phi import TOKENS, redact_text
from .models import (
    DEPARTMENT_ORDER,
    ApprovalStatus,
    FinalDocument,
    RFPMeta,
    SectionRecord,
    TraceEvent,
    utc_now,
)

_COUNTRY_ALIASES = {
    "US": "US",
    "USA": "US",
    "UNITED STATES": "US",
    "UNITED STATES OF AMERICA": "US",
    "UK": "UK",
    "GB": "UK",
    "GBR": "UK",
    "UNITED KINGDOM": "UK",
    "GREAT BRITAIN": "UK",
    "ENGLAND": "UK",
    "SCOTLAND": "UK",
    "WALES": "UK",
    "NORTHERN IRELAND": "UK",
}


def normalize_country(value: Any) -> str:
    key = str(value or "").strip().upper()
    if key in _COUNTRY_ALIASES:
        return _COUNTRY_ALIASES[key]
    raise ValueError(
        f"Unsupported client_country {value!r}: Part 3 needs a US or UK client "
        "(BAA vs DPA/UK GDPR decides the legal instrument)."
    )


def _aware(value: datetime | None) -> datetime | None:
    if value is not None and value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)  # SQLite drops tzinfo
    return value


# --------------------------------------------------------------------------- #
# Structured facts + PHI detection (deterministic, no LLM)
# --------------------------------------------------------------------------- #

_NUMBER_RE = re.compile(r"\d[\d,\.]*")
_CAPACITY_RE = re.compile(
    r"capacity\s+(?:of|for|to serve|to cover)\s+(?:up to\s+)?(\d[\d,]*)", re.IGNORECASE
)


def parse_int(value: Any) -> int | None:
    """'1,200 employees' -> 1200, 800 -> 800, anything else -> None (never invented)."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return int(value)
    if isinstance(value, str):
        match = _NUMBER_RE.search(value)
        if match:
            digits = match.group(0).replace(",", "").split(".")[0]
            return int(digits) if digits else None
    return None


def extract_structured(department: str, content: str, rfp_metadata: dict[str, Any] | None) -> dict[str, Any]:
    """Facts the arbitration rules read.

    revenue   -> covered_population (from the Part 1 metadata)
    clinical  -> committed_capacity (only if the draft states it explicitly:
                 "capacity for 900 members"); otherwise absent -> no conflict is invented
    compliance-> nothing: clauses are derived from the draft text (BAA / DPA + UK GDPR)
    """
    meta = rfp_metadata or {}
    if department == "revenue":
        population = parse_int(meta.get("covered_population"))
        return {"covered_population": population} if population is not None else {}
    if department == "clinical":
        match = _CAPACITY_RE.search(content or "")
        return {"committed_capacity": int(match.group(1).replace(",", ""))} if match else {}
    return {}


def detect_phi(content: str, evaluation: dict[str, Any] | None) -> bool:
    """True when the draft carries (or carried) PHI.

    Part 2 redacts every draft BEFORE storing it, so a stored draft that contains one of
    the redaction tokens (e.g. "[REDACTED_PATIENT_NAME]") means PHI was detected in it.
    Also true if the text still redacts to something different (last line of defense) or
    if an evaluator reported PHI.
    """
    text = content or ""
    if any(token in text for token in TOKENS.values()):
        return True
    if redact_text(text) != text:
        return True
    compliance = (evaluation or {}).get("compliance") or {}
    haystack = " ".join(
        [str(x) for x in compliance.get("rule_ids", [])]
        + [str(x) for x in compliance.get("violations", [])]
    ).lower()
    return bool(
        (evaluation or {}).get("contains_phi")
        or "phi" in haystack
        or "patient identif" in haystack
    )


# --------------------------------------------------------------------------- #
# Store
# --------------------------------------------------------------------------- #


class SqlTicketStore:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    # -- tickets ------------------------------------------------------------ #
    def create_ticket(self, meta: RFPMeta, status: str) -> None:
        raise NotImplementedError("Tickets are created by Part 1 (rfp_intake.service.create_ticket).")

    def _ticket(self, session: Session, ticket_id: str) -> RfpTicket:
        ticket = session.get(RfpTicket, int(ticket_id))
        if ticket is None:
            raise KeyError(f"unknown ticket {ticket_id}")
        return ticket

    def get_meta(self, ticket_id: str) -> RFPMeta:
        with Session(self.engine) as session:
            ticket = self._ticket(session, ticket_id)
            meta = ticket.rfp_metadata or {}
            needed = meta.get("departments_needed") or ticket.detected_departments or []
            return RFPMeta(
                ticket_id=str(ticket.id),
                client_name=meta.get("client_name") or "Unknown client",
                client_country=normalize_country(meta.get("client_country")),
                departments_needed=[d for d in needed if d in DEPARTMENT_ORDER],
            )

    def get_status(self, ticket_id: str) -> str:
        with Session(self.engine) as session:
            return self._ticket(session, ticket_id).status

    def set_status(self, ticket_id: str, status: str) -> None:
        with Session(self.engine) as session:
            ticket = self._ticket(session, ticket_id)
            if ticket.status != status:
                ticket.status = status
                ticket.updated_at = utc_now()
                session.add(ticket)
                session.commit()

    # -- sections ----------------------------------------------------------- #
    def _draft(self, session: Session, ticket_id: int, department: str) -> RfpDraftSection | None:
        return session.exec(
            select(RfpDraftSection)
            .where(RfpDraftSection.ticket_id == ticket_id, RfpDraftSection.department == department)
            .order_by(RfpDraftSection.id.desc())
        ).first()

    def _approval(self, session: Session, ticket: RfpTicket, draft: RfpDraftSection) -> RfpApproval:
        """Get the approval row, creating a `pending` one from the draft on first contact."""
        row = session.exec(
            select(RfpApproval).where(
                RfpApproval.ticket_id == ticket.id, RfpApproval.department == draft.department
            )
        ).first()
        if row is None:
            row = RfpApproval(
                ticket_id=ticket.id,
                department=draft.department,
                structured=extract_structured(draft.department, draft.content, ticket.rfp_metadata),
                contains_phi=detect_phi(draft.content, draft.evaluation),
            )
            session.add(row)
            session.commit()
            session.refresh(row)
        return row

    def _record(self, draft: RfpDraftSection, row: RfpApproval) -> SectionRecord:
        evaluation = dict(draft.evaluation or {})
        evaluation["passed"] = bool(draft.overall_pass)
        evaluation["iterations"] = draft.iterations
        return SectionRecord(
            ticket_id=str(draft.ticket_id),
            department_id=draft.department,
            draft_content=draft.content,
            structured=dict(row.structured or {}),
            contains_phi=row.contains_phi,
            evaluation_results=evaluation,
            approval_status=ApprovalStatus(row.approval_status),
            approver=row.approver,
            approved_at=_aware(row.approved_at),
            revision_count=row.revision_count,
            requested_changes=row.requested_changes,
        )

    def get_section(self, ticket_id: str, department_id: str) -> SectionRecord:
        with Session(self.engine) as session:
            ticket = self._ticket(session, ticket_id)
            draft = self._draft(session, ticket.id, department_id)
            if draft is None:
                raise KeyError(f"no draft for {ticket_id}/{department_id}")
            return self._record(draft, self._approval(session, ticket, draft))

    def list_sections(self, ticket_id: str) -> list[SectionRecord]:
        with Session(self.engine) as session:
            ticket = self._ticket(session, ticket_id)
            drafts = session.exec(
                select(RfpDraftSection).where(RfpDraftSection.ticket_id == ticket.id)
            ).all()
            latest: dict[str, RfpDraftSection] = {}
            for draft in sorted(drafts, key=lambda d: d.id or 0):
                latest[draft.department] = draft
            records = [self._record(d, self._approval(session, ticket, d)) for d in latest.values()]
        order = {name: i for i, name in enumerate(DEPARTMENT_ORDER)}
        return sorted(records, key=lambda r: order.get(r.department_id, 99))

    def upsert_section(self, section: SectionRecord) -> None:
        with Session(self.engine) as session:
            ticket = self._ticket(session, section.ticket_id)
            draft = self._draft(session, ticket.id, section.department_id)
            evaluation = {k: v for k, v in section.evaluation_results.items() if k != "passed"}
            if draft is None:
                draft = RfpDraftSection(ticket_id=ticket.id, department=section.department_id)
            changed = (
                draft.content != section.draft_content
                or (draft.evaluation or {}) != evaluation
            )
            if changed or draft.id is None:
                draft.content = section.draft_content
                draft.evaluation = evaluation
                draft.iterations = int(section.evaluation_results.get("iterations") or draft.iterations or 0)
                results = section.evaluation_results
                draft.overall_pass = bool(
                    results.get("passed", results.get("overall_pass", draft.overall_pass))
                )
                draft.updated_at = utc_now()
                session.add(draft)
                session.commit()
                session.refresh(draft)

            row = self._approval(session, ticket, draft)
            row.approval_status = section.approval_status.value
            row.approver = section.approver
            row.approved_at = section.approved_at
            row.revision_count = section.revision_count
            row.requested_changes = section.requested_changes
            row.structured = dict(section.structured)
            row.contains_phi = section.contains_phi
            row.updated_at = utc_now()
            session.add(row)
            session.commit()

    # -- trace -------------------------------------------------------------- #
    def append_trace(self, event: TraceEvent) -> None:
        with Session(self.engine) as session:
            session.add(
                RfpTraceEvent(
                    ticket_id=int(event.ticket_id),
                    ts=event.ts,
                    agent=event.agent,
                    department=event.department,
                    input_ref=event.input_ref[:512],
                    output_ref=event.output_ref[:512],
                )
            )
            session.commit()

    def list_trace(self, ticket_id: str) -> list[TraceEvent]:
        with Session(self.engine) as session:
            rows = session.exec(
                select(RfpTraceEvent)
                .where(RfpTraceEvent.ticket_id == int(ticket_id))
                .order_by(RfpTraceEvent.id)
            ).all()
            return [
                TraceEvent(
                    ts=r.ts,
                    ticket_id=str(r.ticket_id),
                    agent=r.agent,
                    department=r.department,
                    input_ref=r.input_ref,
                    output_ref=r.output_ref,
                )
                for r in rows
            ]

    # -- final document ------------------------------------------------------ #
    def save_final_document(self, doc: FinalDocument, markdown: str) -> None:
        with Session(self.engine) as session:
            row = session.exec(
                select(RfpFinalDocument).where(RfpFinalDocument.ticket_id == int(doc.ticket_id))
            ).first()
            if row is None:
                row = RfpFinalDocument(ticket_id=int(doc.ticket_id), generated_at=doc.generated_at)
            row.content_md = markdown
            row.path = doc.path
            row.document = doc.model_dump(mode="json")
            row.generated_at = doc.generated_at
            session.add(row)
            session.commit()

    def get_final_document(self, ticket_id: str) -> FinalDocument | None:
        with Session(self.engine) as session:
            row = session.exec(
                select(RfpFinalDocument).where(RfpFinalDocument.ticket_id == int(ticket_id))
            ).first()
            return FinalDocument.model_validate(row.document) if row and row.document else None

    def get_final_markdown(self, ticket_id: str) -> str | None:
        with Session(self.engine) as session:
            row = session.exec(
                select(RfpFinalDocument).where(RfpFinalDocument.ticket_id == int(ticket_id))
            ).first()
            return row.content_md if row else None
