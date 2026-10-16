"""Single place that must match the HealthCore CONTEXT (Milestone 9).

Everything else in the pipeline reads from here.
"""

# department_id -> definition. The ids are the exact ones required by the CONTEXT.
DEPARTMENTS: dict[str, dict[str, str]] = {
    "revenue": {
        "label": "Revenue Cycle",
        "focus": "financial terms, currency, payment structure, budget, contract value (this department owns the ticket)",
        "contact_role": "Tom Callahan, Revenue Cycle Director (ticket owner)",
    },
    "clinical": {
        "label": "Clinical Operations",
        "focus": "clinical feasibility: which clinics and staff capacity can cover the contract, covered population, services requested",
        "contact_role": "Dr. Marcus Reid, Clinical Operations",
    },
    "compliance": {
        "label": "Compliance and Data Governance",
        "focus": "regulatory review (HIPAA / UK GDPR), data handling, BAA or DPA clauses depending on the client's country",
        "contact_role": "Claire Whitfield, Compliance and Data Governance",
    },
}

# Compliance is mandatory on every RFP, without exception.
MANDATORY_DEPARTMENTS: tuple[str, ...] = ("compliance",)

CLIENT_COUNTRIES = ("US", "UK")
PROGRAM_TYPES = ("occupational_health", "corporate_wellness", "referral_network")

# Pricing currency is decided by client_country, never by the model.
CURRENCY_BY_COUNTRY = {"US": "USD", "UK": "GBP"}

# Legal instrument required by client_country (CONTEXT section 5).
LEGAL_INSTRUMENT = {
    "US": "Include a Business Associate Agreement (BAA) clause (HIPAA applies to a US client).",
    "UK": "Include a Data Processing Agreement (DPA) clause referencing UK GDPR (UK client).",
}


def currency_for(country: str | None) -> str | None:
    return CURRENCY_BY_COUNTRY.get(country or "")


# What makes a document a legitimate HealthCore RFP.
RFP_CRITERIA = (
    "A legitimate HealthCore RFP is a request FROM an institutional client (an employer, "
    "a university, a partner organization) asking HealthCore for a proposal: occupational "
    "health, corporate wellness or a referral network partnership. It can be a formal PDF "
    "or an informal email. It usually states the client, the program, the covered "
    "population, a deadline and sometimes a budget. A vendor pitch trying to SELL something "
    "to HealthCore (for example an EHR system), invoices, newsletters, resumes, contracts "
    "already signed and unrelated documents are NOT RFPs."
)

MIN_CLASSIFIER_CONFIDENCE = 0.5
ROUTING_NEXT = "proposal_generation"  # handoff target for Part 2 (drafting)
