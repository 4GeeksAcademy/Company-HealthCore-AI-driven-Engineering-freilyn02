"""Agent 4: synthesizer. Builds the Revenue Cycle-facing summary from all workers."""
from typing import Any

from .. import llm
from ..config import DEPARTMENTS, ROUTING_NEXT, currency_for

SYSTEM_PROMPT = """You write a 2-3 sentence summary of a client's RFP for HealthCore's
Revenue Cycle team, based ONLY on the client data and department findings given.
Do not invent figures. Never write patient names, diagnoses or identifiers.
Reply with JSON only: {"summary": "..."}"""


def synthesize(
    metadata: dict[str, Any],
    readability: dict[str, Any],
    worker_results: list[dict[str, Any]],
    unknown_departments: list[str],
    phi: dict[str, Any] | None = None,
    rfp_fields: dict[str, Any] | None = None,
) -> dict[str, Any]:
    rfp_fields = rfp_fields or {}
    contains_phi = bool(phi and phi.get("contains_phi"))

    by_department = []
    for result in sorted(worker_results, key=lambda r: r["department"]):
        by_department.append(
            {
                "department": result["department"],
                "label": DEPARTMENTS[result["department"]]["label"],
                "needs": result["key_aspects"],
                "open_questions": result["open_questions"],
                "contact": result["suggested_contact_role"],
                "failed": bool(result.get("failed")),
            }
        )

    try:
        raw = llm.chat_json(SYSTEM_PROMPT, f"Client: {rfp_fields}\nFindings: {by_department}")
        summary = str(raw.get("summary") or "").strip()
    except llm.LLMError:
        summary = ""
    if not summary:  # deterministic fallback, the ticket must still complete
        names = ", ".join(d["label"] for d in by_department) or "no department"
        summary = f"RFP analyzed. Departments involved: {names}."

    complexity = (readability or {}).get("complexity", "unknown")
    return {
        "summary": summary,
        "currency": currency_for(rfp_fields.get("client_country")),
        "by_department": by_department,
        "unknown_departments": unknown_departments,
        "readability_estimate": f"{complexity} complexity",
        "requires_compliance_review": contains_phi,
        "compliance_flags": ["phi_detected"] if contains_phi else [],
        "routing_next": ROUTING_NEXT,
    }
