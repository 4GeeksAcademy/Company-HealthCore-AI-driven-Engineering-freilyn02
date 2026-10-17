"""Shared fixtures for the RFP Part 2 tests."""
from data.pipelines.rfp_intake.config import LEGAL_INSTRUMENT


def make_handoff(department="revenue", country="US", currency="USD"):
    return {
        "ticket_id": 1,
        "department": department,
        "label": "Revenue Cycle",
        "client": {
            "client_name": "Acme Corp",
            "client_country": country,
            "program_type": "occupational_health",
            "covered_population": "500 employees",
            "deadline": "2026-12-01",
            "budget_range": "50,000-75,000",
        },
        "currency": currency,
        "legal_instrument": LEGAL_INSTRUMENT.get(country),
        "summary": "Acme Corp asks for an occupational health program.",
        "key_aspects": ["Needs pricing per employee"],
        "open_questions": ["Peak volume not stated"],
        "contact_role": "Tom Callahan, Revenue Cycle Director (ticket owner)",
    }
