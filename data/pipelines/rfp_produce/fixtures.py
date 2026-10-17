"""Reproducible RFP fixtures (synthetic, NO PHI) for tests and the E2E script.

Cases:
  meridian      US / USD, clean, all 3 departments
  thames        UK / GBP, clean, all 3 departments (DPA referencing UK GDPR)
  phi           US, clinical draft flagged contains_phi  -> phi-detected
  capacity      US, capacity 500 < population 800        -> capacity-vs-population
  wrong_clause  UK client but compliance cites BAA        -> baa-dpa-mismatch
"""

from __future__ import annotations

from typing import Any

from .models import (
    STATUS_UNDER_EVALUATION,
    RFPMeta,
    SectionRecord,
    SectionUpdate,
)
from .store import TicketStore

CASES: dict[str, dict[str, Any]] = {
    "meridian": {"client_name": "Meridian Health Network", "country": "US"},
    "thames": {"client_name": "Thames Valley NHS Partnership", "country": "UK"},
    "phi": {"client_name": "Meridian Health Network", "country": "US", "phi": True},
    "capacity": {"client_name": "Meridian Health Network", "country": "US", "capacity": 500},
    "wrong_clause": {
        "client_name": "Thames Valley NHS Partnership",
        "country": "UK",
        "wrong_clause": True,
    },
}


def clean_section(ticket_id: str, department: str, country: str) -> SectionUpdate:
    """A compliant draft for any department/country (what Part 2 would eventually emit)."""
    currency = "USD" if country == "US" else "GBP"
    if department == "revenue":
        return SectionUpdate(
            draft_content=(
                f"Pricing proposal in {currency}: per-member-per-month fee with a "
                "800-member covered population and quarterly reconciliation."
            ),
            structured={"covered_population": 800, "currency": currency},
            evaluation_results={"passed": True, "iterations": 1},
        )
    if department == "clinical":
        return SectionUpdate(
            draft_content=(
                "Clinical delivery plan: three sites, capacity for 900 members, "
                "weekly clinician staffing reviews."
            ),
            structured={"committed_capacity": 900},
            evaluation_results={"passed": True, "iterations": 1},
        )
    clause = "BAA" if country == "US" else "DPA_UK_GDPR"
    text = (
        "Business Associate Agreement (BAA) executed before any data exchange."
        if country == "US"
        else "Data Processing Agreement (DPA) under UK GDPR executed before any data exchange."
    )
    return SectionUpdate(
        draft_content=text,
        structured={"clauses": [clause]},
        evaluation_results={"passed": True, "iterations": 1},
    )


def seed_ticket(
    store: TicketStore,
    ticket_id: str,
    case: str = "meridian",
    *,
    status: str = STATUS_UNDER_EVALUATION,
) -> RFPMeta:
    """Create a ticket exactly as Part 2 would leave it: drafts stored, all pending."""
    spec = CASES[case]
    country = spec["country"]
    meta = RFPMeta(
        ticket_id=ticket_id,
        client_name=spec["client_name"],
        client_country=country,
        departments_needed=["revenue", "clinical"],
    )
    store.create_ticket(meta, status)
    for dept in meta.required_departments:
        update = clean_section(ticket_id, dept, country)
        if dept == "clinical" and "capacity" in spec:
            update.structured["committed_capacity"] = spec["capacity"]
        if dept == "clinical" and spec.get("phi"):
            update.contains_phi = True
            update.draft_content = "Clinical plan (synthetic text flagged by the evaluator)."
        if dept == "compliance" and spec.get("wrong_clause"):
            update.structured = {"clauses": ["BAA"]}
            update.draft_content = "Business Associate Agreement (BAA) executed."
        store.upsert_section(
            SectionRecord(
                ticket_id=ticket_id,
                department_id=dept,
                draft_content=update.draft_content,
                structured=update.structured,
                contains_phi=update.contains_phi,
                evaluation_results=update.evaluation_results,
            )
        )
    return meta


def make_revision_hook(store: TicketStore):
    """Hook bound to a store so it can read the ticket country reliably."""

    def hook(ticket_id: str, department: str, reason: str, previous: SectionRecord) -> SectionUpdate:
        country = store.get_meta(ticket_id).client_country
        return clean_section(ticket_id, department, country)

    return hook


def never_clean_hook(
    ticket_id: str, department: str, reason: str, previous: SectionRecord
) -> SectionUpdate:
    """A generator that keeps producing a PHI-flagged draft (to exercise the iteration cap)."""
    update = clean_section(ticket_id, department, "US")
    update.draft_content += f" (attempt after: {reason[:20]})"
    update.contains_phi = True
    return update


OWNER = {"revenue": "tom.callahan", "clinical": "marcus.reid", "compliance": "claire.whitfield"}


def approve(department: str) -> dict[str, Any]:
    return {"department": department, "decision": "approve", "actor": OWNER[department]}
