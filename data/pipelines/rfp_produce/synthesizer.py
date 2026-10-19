"""Ultimate document synthesizer: consolidates the APPROVED sections into the final
proposal. It is the last node of the flow and refuses to run unless every invariant
holds (defense in depth: the gate already checked, we check again).
"""

from __future__ import annotations

from pathlib import Path

from .arbitration import detect_conflicts
from .models import (
    DEPARTMENT_OWNERS,
    STATUS_DONE,
    ApprovalStatus,
    FinalDocument,
    utc_now_iso,
)
from .store import TicketStore

DEFAULT_OUTPUT_DIR = "data/process/rfp_final"


class SynthesisBlocked(RuntimeError):
    """The final document cannot be generated yet (pending/rejected approvals, PHI,
    or an unresolved conflict)."""


def check_ready(store: TicketStore, ticket_id: str) -> None:
    meta = store.get_meta(ticket_id)
    sections = {s.department_id: s for s in store.list_sections(ticket_id)}

    for dept in meta.required_departments:
        section = sections.get(dept)
        if section is None:
            raise SynthesisBlocked(f"missing section: {dept}")
        if section.approval_status is not ApprovalStatus.APPROVED:
            raise SynthesisBlocked(f"{dept} is {section.approval_status.value}, not approved")
        if not section.approver or section.approved_at is None:
            raise SynthesisBlocked(f"{dept} approval has no approver / timestamp")

    conflicts = detect_conflicts(meta, list(sections.values()))
    if conflicts:
        ids = ", ".join(c["conflict_id"] for c in conflicts)
        raise SynthesisBlocked(f"unresolved conflicts: {ids}")


def render_markdown(doc: FinalDocument) -> str:
    lines = [
        f"# Economic Proposal - {doc.client_name}",
        "",
        f"- Ticket: `{doc.ticket_id}`",
        f"- Currency: {doc.currency}",
        f"- Generated at: {doc.generated_at}",
        "",
    ]
    for section in doc.sections:
        lines += [
            f"## {section['department_name']}",
            "",
            section["content"],
            "",
            f"_Approved by {section['approved_by']} ({section['owner']}) at {section['approved_at']}_",
            "",
        ]
    lines += [
        "---",
        "## Approval and traceability",
        "",
        "| Department | Approved by | Approved at |",
        "| --- | --- | --- |",
    ]
    for section in doc.sections:
        lines.append(
            f"| {section['department_id']} | {section['approved_by']} | {section['approved_at']} |"
        )
    lines += ["", f"Execution trace: `{doc.trace_ref}`", ""]
    return "\n".join(lines)


DEPARTMENT_NAMES = {
    "revenue": "Financial Terms (Revenue Cycle)",
    "clinical": "Clinical Feasibility (Clinical Operations)",
    "compliance": "Regulatory Review (Compliance and Data Governance)",
}


def synthesize_final_document(
    store: TicketStore, ticket_id: str, output_dir: str | Path = DEFAULT_OUTPUT_DIR
) -> FinalDocument:
    check_ready(store, ticket_id)
    meta = store.get_meta(ticket_id)
    sections = {s.department_id: s for s in store.list_sections(ticket_id)}

    doc = FinalDocument(
        ticket_id=ticket_id,
        client_name=meta.client_name,
        currency=meta.currency,
        generated_at=utc_now_iso(),
        trace_ref=f"trace:{ticket_id}",
        sections=[
            {
                "department_id": dept,
                "department_name": DEPARTMENT_NAMES[dept],
                "owner": next(iter(DEPARTMENT_OWNERS[dept].values())),
                "content": sections[dept].draft_content,
                "approved_by": sections[dept].approver,
                "approved_at": sections[dept].approved_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
            }
            for dept in meta.required_departments
        ],
    )
    markdown = render_markdown(doc)

    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"final_doc_{ticket_id}.md"
    path.write_text(markdown, encoding="utf-8")
    doc.path = str(path)

    store.save_final_document(doc, markdown)
    store.set_status(ticket_id, STATUS_DONE)  # last: only after the artifact exists
    return doc
